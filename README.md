# Golf course data (from OpenStreetMap)

Golf courses, holes, pars, tees and greens, extracted from
[OpenStreetMap](https://www.openstreetmap.org/) and arranged for use in the
Golf Counter app (Apple Watch).

**© OpenStreetMap contributors.** This data is made available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
It is a derivative database of OpenStreetMap and is shared under the same
licence. See <https://www.openstreetmap.org/copyright>.

You can fix or add a course for everyone by editing OpenStreetMap: map the
holes as `golf=hole` lines from tee to green with `ref` (hole number) and
`par`, and the greens as `golf=green` areas. Changes appear here at the next
rebuild.

## Files

### `courses.tsv`

Every named golf course, one per line, tab separated:

| column | example |
|---|---|
| id | `w188607319` (OSM `n`ode / `w`ay / `r`elation + id) |
| lat, lon | `35.93522`, `139.28688` (centre of the outline) |
| has holes | `1` when hole data with pars is in a tile |
| name | `オリムピックナショナルゴルフクラブ (West)` |
| English name | `Olympic National Golf Club (West Course)` (`name:en`, when different) |

### `v1/tiles/<lat>_<lon>.json`

Hole data for the courses whose centre is in the 1°×1° tile
(`floor(lat)_floor(lon)`), as `{course id: [nine, ...]}`:

```json
{"w188607319": [
  {"label": "OUT", "holes": [
    {"number": 1, "par": 5,
     "tee": {"lat": 35.932299, "lon": 139.289201},
     "green": {"lat": 35.93426, "lon": 139.293703},
     "front": {"lat": 35.934141, "lon": 139.293522},
     "back": {"lat": 35.934365, "lon": 139.293862}}]},
  {"label": "IN", "holes": []}
]}
```

- 18 holes numbered once each become `OUT` (1–9) and `IN` (10–18).
- Clubs with several nines get one entry per nine, named from the holes'
  own names (`East`, `West OUT`, ...) or `A`, `B`, `C`.
- `tee` is the start of the hole line, `green` the centre of the green it
  ends in, `front` / `back` the green's edges along the line of play.

Built with `tool/courses/fetch.py` and `tool/courses/build.py` (Overpass API).
