"""
The one way this project asks CelesTrak for anything.

CelesTrak's usage policy (https://celestrak.org/usage-policy.php): the data only changes every two hours, so the same data must not be
requested more than once in that time, and any answer other than 200 means stop at once. Repeat offenders get blocked, and their whole
address range with them.

So every request is written down before it is sent, a request that fails still counts, and within two hours the last good answer comes
back from the cache instead. Standard library only. The same file is used in the public data repository, Onetechno/cosmic-vista-data.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ISS_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
MIN_INTERVAL = timedelta(hours=2)
USER_AGENT = "CosmicVista3D-data-cache"


class Refused(Exception):
    """CelesTrak answered with something other than usable data. Never retry this within the interval."""


def now_utc():
    return datetime.now(timezone.utc)


def _format(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def is_due(last_request, now, interval=MIN_INTERVAL):
    """True when a new request is allowed. A stamp slightly in the future also waits, so a clock change cannot cause a repeat request."""
    if last_request is None:
        return True
    return abs(now - last_request) >= interval


def looks_like_elements(body, catalog_number="25544"):
    """CelesTrak can answer 200 with a message instead of data, so 200 alone is not enough."""
    lines = [line.strip() for line in (body or "").splitlines()]
    has_first = any(line.startswith("1 " + catalog_number) and len(line) == 69 for line in lines)
    has_second = any(line.startswith("2 " + catalog_number) and len(line) == 69 for line in lines)
    return has_first and has_second


def http_get(url, timeout=60):
    """Returns (status, body). Redirects are not followed: the policy treats 301 as a reason to stop."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""


class Guard:
    """Remembers each URL's last request and last good answer in one JSON file."""

    def __init__(self, state_path, get=http_get, clock=now_utc):
        self.state_path = state_path
        self.get = get
        self.clock = clock
        self.state = {}
        if os.path.exists(state_path):
            with open(state_path, encoding="utf-8") as f:
                self.state = json.load(f)

    def _save(self):
        folder = os.path.dirname(self.state_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temporary = self.state_path + ".tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.state, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(temporary, self.state_path)

    def last_request(self, url):
        text = self.state.get(url, {}).get("last_request_utc")
        return _parse(text) if text else None

    def fetch(self, url=ISS_URL, validate=looks_like_elements):
        """
        Returns (body, fetched_utc, came_from_cache). Within the interval there is no network request at all, and without a cached answer
        that is a Refused. Any answer that is not usable raises Refused, and the next request still waits for the interval.
        """
        now = self.clock()
        entry = self.state.setdefault(url, {})

        if not is_due(self.last_request(url), now):
            if entry.get("body"):
                return entry["body"], entry.get("last_good_utc"), True
            raise Refused("Asked within two hours of the last request, and no earlier answer is kept.")

        # Written first, so a crash or a timeout still counts as the request it was.
        entry["last_request_utc"] = _format(now)
        entry["last_status"] = None
        self._save()

        try:
            status, body = self.get(url)
        except OSError as error:
            entry["last_status"] = "no answer: " + type(error).__name__
            self._save()
            raise Refused("No answer from CelesTrak. Not retrying.") from error

        entry["last_status"] = status
        if status != 200 or not validate(body):
            self._save()
            raise Refused("CelesTrak answered %s. Stopping, as its usage policy asks." % status)

        entry["body"] = body
        entry["last_good_utc"] = _format(now)
        self._save()
        return body, entry["last_good_utc"], False
