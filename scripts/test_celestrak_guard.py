"""python -m unittest discover -s Tools/ephemeris -p "test_*.py" """
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import celestrak_guard
from celestrak_guard import Guard, Refused, is_due, looks_like_elements

GOOD = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   26308.88559265  .00005352  00000+0  10457-3 0  9991\n"
    "2 25544  51.6327 323.8448 0007212 348.6490  11.4335 15.49180468593565\n"
)
START = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


class FakeNetwork:
    """Counts requests, which is the whole point: the guard must make none."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = 0

    def __call__(self, url, timeout=60):
        self.requests += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeClock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "guard.json")
        self.clock = FakeClock()

    def guard(self, network):
        return Guard(self.path, get=network, clock=self.clock)

    def test_asks_when_it_has_never_asked(self):
        network = FakeNetwork((200, GOOD))
        body, stamp, cached = self.guard(network).fetch()
        self.assertEqual(network.requests, 1)
        self.assertEqual(body, GOOD)
        self.assertEqual(stamp, "2026-11-05T12:00:00Z")
        self.assertFalse(cached)

    def test_within_two_hours_it_uses_the_cache_and_sends_nothing(self):
        network = FakeNetwork((200, GOOD))
        guard = self.guard(network)
        guard.fetch()

        self.clock.now = START + timedelta(hours=1, minutes=59, seconds=59)
        body, stamp, cached = guard.fetch()

        self.assertEqual(network.requests, 1)
        self.assertEqual(body, GOOD)
        self.assertEqual(stamp, "2026-11-05T12:00:00Z")
        self.assertTrue(cached)

    def test_the_two_hours_survive_a_restart(self):
        self.guard(FakeNetwork((200, GOOD))).fetch()

        self.clock.now = START + timedelta(minutes=5)
        second_run = FakeNetwork()
        self.assertTrue(self.guard(second_run).fetch()[2])
        self.assertEqual(second_run.requests, 0)

    def test_after_two_hours_it_asks_again(self):
        network = FakeNetwork((200, GOOD), (200, GOOD.replace("9991", "9992")))
        guard = self.guard(network)
        guard.fetch()

        self.clock.now = START + timedelta(hours=2)
        body, _, cached = guard.fetch()

        self.assertEqual(network.requests, 2)
        self.assertFalse(cached)
        self.assertIn("9992", body)

    def test_any_other_answer_stops_at_once_and_is_not_retried(self):
        for status in (301, 403, 404, 500):
            with self.subTest(status=status):
                if os.path.exists(self.path):
                    os.remove(self.path)
                self.clock.now = START
                network = FakeNetwork((status, ""))
                guard = self.guard(network)
                with self.assertRaises(Refused):
                    guard.fetch()
                self.assertEqual(network.requests, 1, "No retry inside the same call.")

                self.clock.now = START + timedelta(hours=1)
                with self.assertRaises(Refused):
                    guard.fetch()
                self.assertEqual(network.requests, 1, "A refusal still counts as the request it was.")

    def test_a_refusal_keeps_the_last_good_answer(self):
        network = FakeNetwork((200, GOOD), (403, ""))
        guard = self.guard(network)
        guard.fetch()

        self.clock.now = START + timedelta(hours=3)
        with self.assertRaises(Refused):
            guard.fetch()

        self.clock.now = START + timedelta(hours=4)
        body, stamp, cached = guard.fetch()
        self.assertEqual(network.requests, 2)
        self.assertEqual(body, GOOD)
        self.assertEqual(stamp, "2026-11-05T12:00:00Z")
        self.assertTrue(cached)

    def test_a_200_without_elements_is_refused_too(self):
        network = FakeNetwork((200, "No GP data found"))
        with self.assertRaises(Refused):
            self.guard(network).fetch()
        with open(self.path, encoding="utf-8") as f:
            self.assertNotIn("body", json.load(f)[celestrak_guard.ISS_URL])

    def test_a_timeout_counts_as_a_request(self):
        network = FakeNetwork(OSError("timed out"))
        guard = self.guard(network)
        with self.assertRaises(Refused):
            guard.fetch()

        self.clock.now = START + timedelta(minutes=10)
        with self.assertRaises(Refused):
            guard.fetch()
        self.assertEqual(network.requests, 1)

    def test_the_stamp_is_written_before_the_request_leaves(self):
        seen = {}

        def network(url, timeout=60):
            with open(self.path, encoding="utf-8") as f:
                seen.update(json.load(f))
            return 200, GOOD

        Guard(self.path, get=network, clock=self.clock).fetch()
        self.assertEqual(seen[celestrak_guard.ISS_URL]["last_request_utc"], "2026-11-05T12:00:00Z")

    def test_a_clock_set_back_cannot_cause_a_repeat_request(self):
        network = FakeNetwork((200, GOOD))
        guard = self.guard(network)
        guard.fetch()

        self.clock.now = START - timedelta(minutes=30)
        self.assertTrue(guard.fetch()[2])
        self.assertEqual(network.requests, 1)


class RuleTests(unittest.TestCase):
    def test_is_due(self):
        self.assertTrue(is_due(None, START))
        self.assertFalse(is_due(START, START))
        self.assertFalse(is_due(START, START + timedelta(hours=1, minutes=59)))
        self.assertTrue(is_due(START, START + timedelta(hours=2)))

    def test_elements_check(self):
        self.assertTrue(looks_like_elements(GOOD))
        self.assertFalse(looks_like_elements(""))
        self.assertFalse(looks_like_elements(None))
        self.assertFalse(looks_like_elements("<html>Forbidden</html>"))
        self.assertFalse(looks_like_elements(GOOD.replace("25544", "99999")))


if __name__ == "__main__":
    unittest.main()
