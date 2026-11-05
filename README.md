# Cosmic Vista 3D public data cache

Public astronomy data, collected once a day by GitHub Actions and published as static files with GitHub Pages. The Cosmic Vista 3D iOS app reads only these files, so it never calls the source services itself. There is no server, no account and no API key here.

| File | Contents | Source | Terms |
|---|---|---|---|
| [`iss_tle.json`](https://onetechno.github.io/cosmic-vista-data/iss_tle.json) | Two-line elements of the ISS | [CelesTrak](https://celestrak.org/) | [Usage policy](https://celestrak.org/usage-policy.php): at most once every two hours, stop on any answer other than 200 |
| [`sky_events.json`](https://onetechno.github.io/cosmic-vista-data/sky_events.json) | Aurora forecast summary | [NOAA SWPC](https://www.swpc.noaa.gov/) | U.S. government work |
| | Moon phases, solar eclipses and seasons, this year and next | [U.S. Naval Observatory](https://aa.usno.navy.mil/data/api) | U.S. government work |
| [`status.json`](https://onetechno.github.io/cosmic-vista-data/status.json) | How each source's last collection went | This repository | |

NASA DONKI (solar flares and CMEs) needs an API key, so it is not collected. This repository holds no keys.

`scripts/celestrak_guard.py` writes down every CelesTrak request before sending it. Within two hours, it answers from its cache and sends nothing. A source that fails keeps its last good data.

Run the tests, with no network: `python -m unittest discover -s scripts -p "test_*.py"`

This project is not affiliated with or endorsed by NASA, NOAA, the U.S. Naval Observatory or CelesTrak.
