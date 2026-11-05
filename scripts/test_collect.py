"""python -m unittest discover -s scripts -p "test_*.py" """
import json
import os
import tempfile
import unittest

import collect
from celestrak_guard import Guard
from test_celestrak_guard import FakeClock, FakeNetwork, GOOD

AURORA = {
    "Observation Time": "2026-11-05T12:00:00Z",
    "Forecast Time": "2026-11-05T12:30:00Z",
    "coordinates": [[0, 65, 42], [1, 65, 90], [5, 70, 9], [10, -70, 30], [10, 0, 0]],
}


def fake_get(url, timeout=60):
    if "ovation" in url:
        return AURORA
    if "moon/phases" in url:
        return {"phasedata": [{"phase": "Full Moon", "year": 2026, "month": 11, "day": 24, "time": "14:53"}]}
    if "eclipses" in url:
        return {"eclipses_in_year": [{"event": "Annular Solar Eclipse", "year": 2027, "month": 2, "day": 6}]}
    if "seasons" in url:
        return {"data": [{"phenom": "Equinox", "year": 2027, "month": 3, "day": 20, "time": "20:25"}]}
    raise AssertionError(url)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.old_docs = collect.DOCS
        collect.DOCS = os.path.join(self.folder.name, "docs")
        self.addCleanup(lambda: setattr(collect, "DOCS", self.old_docs))
        self.clock = FakeClock()
        self.network = FakeNetwork((200, GOOD))
        self.guard = Guard(os.path.join(self.folder.name, "guard.json"), get=self.network, clock=self.clock)

    def read(self, name):
        with open(os.path.join(collect.DOCS, name), encoding="utf-8") as f:
            return json.load(f)

    def test_writes_the_three_files(self):
        collect.collect(self.guard, get=fake_get, clock=self.clock)

        iss = self.read("iss_tle.json")
        self.assertEqual(iss["schema"], 1)
        self.assertEqual(iss["name"], "ISS (ZARYA)")
        self.assertTrue(iss["line1"].startswith("1 25544"))
        self.assertTrue(iss["line2"].startswith("2 25544"))
        self.assertEqual(iss["fetched_utc"], "2026-11-05T12:00:00Z")

        sky = self.read("sky_events.json")
        self.assertEqual(sky["aurora"]["north_max_percent"], 90)
        self.assertEqual(sky["aurora"]["south_max_percent"], 30)
        self.assertEqual(sky["aurora"]["cells"], [[0, 65, 42], [10, -70, 30]], "Every fifth degree, above a low chance.")
        self.assertEqual(len(sky["moon_phases"]), 2, "This year and next.")
        self.assertEqual(len(sky["solar_eclipses"]), 2)
        self.assertEqual(len(sky["seasons"]), 2)

        status = self.read("status.json")
        self.assertEqual(status["sources"]["celestrak"]["result"], "ok")
        self.assertEqual(status["sources"]["nasa_donki"]["result"], "skipped")

    def test_running_twice_never_asks_celestrak_twice(self):
        collect.collect(self.guard, get=fake_get, clock=self.clock)
        status = collect.collect(self.guard, get=fake_get, clock=self.clock)
        self.assertEqual(self.network.requests, 1)
        self.assertEqual(status["sources"]["celestrak"]["result"], "cached")

    def test_a_refusal_leaves_the_published_elements_alone(self):
        collect.write_json("iss_tle.json", {"schema": 1, "line1": "kept"})
        refused = Guard(os.path.join(self.folder.name, "other.json"), get=FakeNetwork((403, "")), clock=self.clock)
        status = collect.collect(refused, get=fake_get, clock=self.clock)
        self.assertEqual(status["sources"]["celestrak"]["result"], "skipped")
        self.assertEqual(self.read("iss_tle.json")["line1"], "kept")

    def test_a_failed_source_keeps_its_last_good_data(self):
        collect.collect(self.guard, get=fake_get, clock=self.clock)

        def broken(url, timeout=60):
            raise OSError("down")

        status = collect.collect(self.guard, get=broken, clock=self.clock)
        self.assertEqual(status["sources"]["noaa_aurora"]["result"], "failed")
        self.assertEqual(status["sources"]["usno"]["result"], "failed")
        sky = self.read("sky_events.json")
        self.assertEqual(sky["aurora"]["north_max_percent"], 90)
        self.assertEqual(len(sky["moon_phases"]), 2)

    def test_no_key_is_published(self):
        collect.collect(self.guard, get=fake_get, clock=self.clock)
        for name in ("iss_tle.json", "sky_events.json", "status.json"):
            with open(os.path.join(collect.DOCS, name), encoding="utf-8") as f:
                self.assertNotIn("api_key", f.read())


if __name__ == "__main__":
    unittest.main()
