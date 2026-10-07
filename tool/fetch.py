#!/usr/bin/env python3
"""Downloads golf data from OpenStreetMap (Overpass), one box at a time.

    python3 tool/courses/fetch.py <cache-dir>

Saves raw Overpass JSON per box in <cache-dir>/raw/. Boxes that time out or
come back too big are split into four and retried, so the whole world can be
fetched without a single huge query. Already-fetched boxes are skipped, so the
script can be stopped and restarted.

Only one request runs at a time, with a pause between requests, to stay well
inside the Overpass usage policy.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

QUERY = """[out:json][timeout:300][maxsize:536870912][bbox:{s},{w},{n},{e}];
(nwr["leisure"="golf_course"];);
out tags center bb;
(way["golf"="hole"];);
out tags geom;
(way["golf"="green"];way["golf"="tee"];);
out tags geom;
"""


def fetch(box, endpoint):
    s, w, n, e = box
    data = urllib.parse.urlencode({"data": QUERY.format(s=s, w=w, n=n, e=e)}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={"User-Agent": "golf-course-data builder (tomople)"})
    with urllib.request.urlopen(req, timeout=400) as res:
        body = res.read()
    parsed = json.loads(body)
    remark = parsed.get("remark", "")
    if "runtime error" in remark or "Query timed out" in remark or "out of memory" in remark:
        raise RuntimeError(remark)
    return parsed


def name(box):
    return "_".join(f"{v:g}" for v in box)


def main(cache):
    raw = os.path.join(cache, "raw")
    os.makedirs(raw, exist_ok=True)
    # Land between 60S and 72N, in 20-degree boxes.
    queue = [(lat, lon, lat + 20, lon + 20) for lat in range(-60, 72, 20) for lon in range(-180, 180, 20)]
    # Where most courses are first (Japan / Korea, North America, Europe),
    # so a stopped run has already got the useful part.
    first = [(20, 120), (20, 140), (40, 140), (20, 100), (20, -100), (20, -80), (40, -80), (40, -100),
             (20, -120), (40, -120), (40, -20), (40, 0), (40, 20), (20, -20), (20, 0), (-40, 140), (-40, 160)]
    queue.sort(key=lambda b: first.index((b[0], b[1])) if (b[0], b[1]) in first else 99)
    turn = 0
    while queue:
        box = queue.pop(0)
        out = os.path.join(raw, name(box) + ".json")
        if os.path.exists(out) or os.path.exists(out + ".split"):
            if os.path.exists(out + ".split"):
                queue[:0] = split(box)
            continue
        endpoint = ENDPOINTS[turn % len(ENDPOINTS)]
        turn += 1
        try:
            started = time.time()
            got = fetch(box, endpoint)
            with open(out, "w") as f:
                json.dump(got, f)
            print(f"ok   {name(box):28} {len(got['elements']):7} el  {time.time() - started:5.0f}s", flush=True)
            time.sleep(3)
        except Exception as error:  # timeout, too big, 429, 504...
            msg = str(error)[:80]
            size = box[2] - box[0]
            heavy = any(k in msg for k in ("timed out", "memory", "runtime error", "timeout"))
            if heavy and size > 1.25:
                open(out + ".split", "w").close()
                print(f"split {name(box):27} ({msg})", flush=True)
                queue[:0] = split(box)
            else:
                # Busy server (429 / 504): wait and ask for the same box again.
                print(f"retry {name(box):27} ({msg})", flush=True)
                queue.insert(0, box)
            # A busy server: the next try goes to the next server.
            time.sleep(5 if heavy else 10)


def split(box):
    s, w, n, e = box
    ms, mw = (s + n) / 2, (w + e) / 2
    return [(s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)]


if __name__ == "__main__":
    main(sys.argv[1])
