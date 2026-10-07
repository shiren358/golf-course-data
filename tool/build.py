#!/usr/bin/env python3
"""Turns the raw Overpass boxes (fetch.py) into the files the app uses.

    python3 tool/courses/build.py <cache-dir> <out-dir>

Writes:
  <out-dir>/courses.tsv          every named course: id, lat, lon, has-holes, name, English name
                                 (bundled in the app: offline search and "nearby")
  <out-dir>/v1/tiles/<lat>_<lon>.json
                                 hole data per 1°×1° tile: {course id: [Nine]}
                                 (served from GitHub Pages, fetched when a course is picked)

Data © OpenStreetMap contributors, ODbL 1.0. The output is a derivative
database and is published under the same licence.

How holes become nines
----------------------
A mapped hole (golf=hole) is a line from the tee to the green, with `ref`
(hole number) and `par`. Holes are given to the course whose outline holds
the middle of the line.

* Numbers 1–18 used once each: OUT = 1–9, IN = 10–18.
* Numbers used more than once (a club with East / West / South nines):
  chains are built from every hole 1 (and every hole 10), each time taking
  the next number whose tee is nearest the last green. A chain is named from
  the holes' own names ("East No. 3" → "East"), else A, B, C.
"""
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict

SKIP_NAME = re.compile(
    r"練習|打ちっぱなし|打ちっ放し|パークゴルフ|グラウンド・?ゴルフ|ショートコース練習|"
    r"driving range|practice|mini ?golf|minigolf|putting|pitch ?(and|&|n) ?putt|disc ?golf|frisbee|footgolf|"
    r"golf range|par ?3 range|simulator|indoor",
    re.I)


def load(cache):
    courses, holes, greens = {}, {}, {}
    for path in sorted(glob.glob(os.path.join(cache, "raw", "*.json"))):
        with open(path) as f:
            data = json.load(f)
        for e in data.get("elements", []):
            key = e["type"][0] + str(e["id"])
            tags = e.get("tags", {})
            if tags.get("leisure") == "golf_course":
                courses[key] = e
            elif tags.get("golf") == "hole" and e.get("geometry"):
                holes[key] = e
            elif tags.get("golf") == "green" and e.get("geometry"):
                greens[key] = e
    return courses, holes, greens


def center_of(e):
    if "center" in e:
        return e["center"]["lat"], e["center"]["lon"]
    if "lat" in e:
        return e["lat"], e["lon"]
    b = e.get("bounds")
    if b:
        return (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2
    return None


def bounds_of(e):
    b = e.get("bounds")
    if not b:
        return None
    return b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]


def metres(a, b):
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111_320, (a[1] - b[1]) * 111_320 * math.cos(lat))


def as_int(v):
    try:
        return int(str(v).strip().split(";")[0])
    except ValueError:
        return None


def pt(p):
    return {"lat": round(p[0], 6), "lon": round(p[1], 6)}


def inside(point, poly):
    """Ray casting; poly is a list of (lat, lon)."""
    y, x = point
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi:
            hit = not hit
        j = i
    return hit


class GreenIndex:
    """Greens by 0.01° cell, to find the green at the end of a hole."""

    def __init__(self, greens):
        self.cells = defaultdict(list)
        for g in greens.values():
            poly = [(p["lat"], p["lon"]) for p in g["geometry"]]
            if len(poly) < 3:
                continue
            c = (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
            self.cells[(int(c[0] * 100), int(c[1] * 100))].append((c, poly))

    def find(self, end):
        best = None
        cy, cx = int(end[0] * 100), int(end[1] * 100)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for c, poly in self.cells.get((cy + dy, cx + dx), []):
                    d = 0 if inside(end, poly) else metres(end, c)
                    if d < 40 and (best is None or d < best[0]):
                        best = (d, c, poly)
        return best


def hole_info(e, greens):
    tags = e["tags"]
    line = [(p["lat"], p["lon"]) for p in e["geometry"]]
    tee, end = line[0], line[-1]
    info = {"number": None, "tee": pt(tee), "green": pt(end)}
    par = as_int(tags.get("par"))
    if par and 3 <= par <= 6:
        info["par"] = par
    hcp = as_int(tags.get("handicap"))
    if hcp and 1 <= hcp <= 18:
        info["handicap"] = hcp
    found = greens.find(end)
    if found and len(line) >= 2:
        _, c, poly = found
        info["green"] = pt(c)
        # Front and back along the last leg of the hole line.
        a = line[-2]
        lat = math.radians(c[0])
        dy, dx = (end[0] - a[0]), (end[1] - a[1]) * math.cos(lat)
        n = math.hypot(dy, dx)
        if n > 0:
            dy, dx = dy / n, dx / n
            proj = [((p[0] - c[0]) * dy + (p[1] - c[1]) * math.cos(lat) * dx) for p in poly]
            lo, hi = min(proj), max(proj)
            info["front"] = pt((c[0] + dy * lo, c[1] + dx * lo / math.cos(lat)))
            info["back"] = pt((c[0] + dy * hi, c[1] + dx * hi / math.cos(lat)))
    return info


def nine_label(holes, fallback):
    """'East No. 3', 'East 3', '東3番' → 'East' / '東'."""
    words = []
    for h in holes:
        name = h.get("_name") or ""
        name = re.sub(r"(hole|no\.?|#|番|ホール)", " ", name, flags=re.I)
        name = re.sub(r"\d+", " ", name).strip(" -.:")
        if name:
            words.append(name.strip())
    if words:
        common = max(set(words), key=words.count)
        if words.count(common) >= max(2, len(holes) // 2) and len(common) <= 16:
            return common
    return fallback


def group_name(h):
    """'East No. 3' → 'East'; None when the name is only a number."""
    name = h.get("_name") or ""
    name = re.sub(r"(hole|no\.?|#|番|ホール)", " ", name, flags=re.I)
    name = re.sub(r"\d+", " ", name).strip(" -.:")
    name = re.sub(r"\s+", " ", name).strip()
    return name if 0 < len(name) <= 16 else None


def make_nines(holes):
    # Clubs whose holes are named by course ("East No. 3", "West No. 12"):
    # each named course is its own OUT / IN.
    groups = defaultdict(list)
    for h in holes:
        groups[group_name(h)].append(h)
    named = {k: v for k, v in groups.items() if k and len(v) >= 3}
    if len(named) >= 2 and sum(len(v) for v in named.values()) >= len(holes) * 0.8:
        nines = []
        for name in sorted(named):
            part = simple_nines(named[name])
            if part is None:
                continue
            if len(part) == 1:
                nines.append((name, part[0][1]))
            else:
                nines += [(f"{name} {label}", chain) for label, chain in part]
        if nines:
            return nines
    return simple_nines(holes) or chain_nines(holes)


def simple_nines(holes):
    """OUT 1–9 / IN 10–18 when every number is used once; else None."""
    by_ref = defaultdict(list)
    for h in holes:
        if h["number"]:
            by_ref[h["number"]].append(h)
    if not by_ref or not all(len(v) == 1 for v in by_ref.values()) or max(by_ref) > 18:
        return None
    out = [by_ref[n][0] for n in range(1, 10) if n in by_ref]
    inn = [by_ref[n][0] for n in range(10, 19) if n in by_ref]
    return [x for x in (("OUT", out), ("IN", inn)) if x[1]]


def chain_nines(holes):
    by_ref = defaultdict(list)
    for h in holes:
        if h["number"]:
            by_ref[h["number"]].append(h)
    if not by_ref:
        return []
    # Several holes per number: build chains.
    used = set()
    chains = []
    for start in (1, 10):
        for first in by_ref.get(start, []):
            if id(first) in used:
                continue
            chain = [first]
            used.add(id(first))
            for n in range(start + 1, start + 9):
                last = chain[-1]
                options = [h for h in by_ref.get(n, []) if id(h) not in used]
                if not options:
                    break
                nxt = min(options, key=lambda h: metres(
                    (last["green"]["lat"], last["green"]["lon"]), (h["tee"]["lat"], h["tee"]["lon"])))
                if metres((last["green"]["lat"], last["green"]["lon"]), (nxt["tee"]["lat"], nxt["tee"]["lon"])) > 800:
                    break
                chain.append(nxt)
                used.add(id(nxt))
            if len(chain) >= 3:
                chains.append((start, chain))
    nines = []
    letters = iter("ABCDEFGH")
    for start, chain in chains:
        base = nine_label(chain, None)
        label = base or next(letters, "X")
        if base and any(b == base for b, _ in [(nine_label(c, None), s) for s, c in chains if c is not chain]):
            label = f"{base} {'OUT' if start == 1 else 'IN'}"
        while any(label == l for l, _ in nines):
            label += "'"
        nines.append((label, chain))
    return nines


def main(cache, out):
    courses, holes, greens = load(cache)
    print(f"{len(courses)} courses, {len(holes)} holes, {len(greens)} greens")
    green_index = GreenIndex(greens)

    # Courses with an outline, by 0.1° cell, to place holes.
    cells = defaultdict(list)
    for key, c in courses.items():
        b = bounds_of(c)
        if b:
            for y in range(int(math.floor(b[0] * 10)), int(math.floor(b[2] * 10)) + 1):
                for x in range(int(math.floor(b[1] * 10)), int(math.floor(b[3] * 10)) + 1):
                    cells[(y, x)].append((key, b))
    per_course = defaultdict(list)
    for e in holes.values():
        geom = e["geometry"]
        mid = geom[len(geom) // 2]
        m = (mid["lat"], mid["lon"])
        best = None
        for key, b in cells.get((int(math.floor(m[0] * 10)), int(math.floor(m[1] * 10))), []):
            if b[0] <= m[0] <= b[2] and b[1] <= m[1] <= b[3]:
                area = (b[2] - b[0]) * (b[3] - b[1])
                if best is None or area < best[0]:
                    best = (area, key)
        if best:
            info = hole_info(e, green_index)
            info["number"] = as_int(e["tags"].get("ref"))
            info["_name"] = e["tags"].get("name")
            per_course[best[1]].append(info)

    tiles = defaultdict(dict)
    rows = []
    with_par = 0
    for key, c in courses.items():
        tags = c.get("tags", {})
        name = (tags.get("name") or "").strip()
        if (not name or SKIP_NAME.search(name) or tags.get("golf") == "driving_range"
                or tags.get("indoor") == "yes" or "level" in tags):
            continue
        center = center_of(c)
        if not center:
            continue
        nines = []
        for label, chain in make_nines(per_course.get(key, [])):
            hs = []
            for h in sorted(chain, key=lambda h: h["number"]):
                h = {k: v for k, v in h.items() if not k.startswith("_")}
                hs.append(h)
            nines.append({"label": label, "holes": hs})
        has = any("par" in h for n in nines for h in n["holes"])
        if has:
            with_par += 1
            tiles[f"{math.floor(center[0])}_{math.floor(center[1])}"][key] = nines
        name_en = (tags.get("name:en") or "").strip()
        if name_en == name:
            name_en = ""
        clean = lambda s: s.replace("\t", " ").replace("\n", " ")
        rows.append(f"{key}\t{center[0]:.5f}\t{center[1]:.5f}\t{1 if has else 0}\t{clean(name)}\t{clean(name_en)}")

    os.makedirs(os.path.join(out, "v1", "tiles"), exist_ok=True)
    rows.sort()
    with open(os.path.join(out, "courses.tsv"), "w") as f:
        f.write("\n".join(rows) + "\n")
    for name, data in tiles.items():
        with open(os.path.join(out, "v1", "tiles", name + ".json"), "w") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"{len(rows)} named courses, {with_par} with pars, {len(tiles)} tiles")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
