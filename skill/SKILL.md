---
name: map-animation
description: Use when the user wants an animated map where a travel route draws itself progressively (Jet Lag-style), or asks to "animate a route", "draw the route on a map", or "travel map animation". Covers driving, walking, and rail journeys.
---

# Map Animation — Jet Lag-style animated route

## Overview

Generate a 1920×1080 MP4 video where a travel route draws itself progressively over a
desaturated OpenStreetMap basemap, with station markers and Jet Lag-style overlay bars.

The script `make_map_animation.py` (in the repo root) does all the work.
Call it — do not re-implement the logic inline.

## Dependencies (install once)

```bash
pip install -r requirements.txt
brew install ffmpeg        # macOS
# apt install ffmpeg       # Debian/Ubuntu
```

## Quick recipe

```bash
python3 make_map_animation.py \
  --start  "10.7531,59.9110,Oslo" \
  --end    "5.3242,60.3929,Bergen" \
  --title  "Oslo - Bergen" \
  --subtitle "~460 km" \
  --output  /path/to/output.mp4 \
  --zoom 7 --duration 5 --hold 2 --mode driving
```

## Arguments

| Argument         | Required | Default   | Description |
|-----------------|----------|-----------|-------------|
| `--start`       | yes      | —         | `"lon,lat,Place name"` start point |
| `--end`         | yes      | —         | `"lon,lat,Place name"` end point |
| `--stops`       | no       | none      | One or more `"lon,lat,Name"` intermediate stops |
| `--title`       | yes      | —         | Large text shown at the top of the map |
| `--subtitle`    | no       | empty     | Small text shown below the title |
| `--output`      | yes      | —         | Output file path (`.mp4`) |
| `--zoom`        | no       | 7         | OSM zoom level (6 = continent, 11 = city) |
| `--fps`         | no       | 30        | Frames per second |
| `--duration`    | no       | 4.0       | Seconds for the drawing animation |
| `--hold`        | no       | 1.5       | Extra seconds on the finished map |
| `--mode`        | no       | driving   | `driving` or `walking` (OSRM) or `rail` (OSM rail ways via Overpass) |
| `--osm-relation`| no       | none      | OSM relation ID(s) for a named rail line (only with `--mode rail`); comma-separated for multi-line journeys, e.g. `3200969,965964` for Gardermobanen+Dovrebanen |
| `--width`       | no       | 1920      | Output video width in pixels |
| `--height`      | no       | 1080      | Output video height in pixels |

## Zoom level per distance

| Distance              | Recommended zoom |
|-----------------------|-----------------|
| < 10 km (city to city)| 12              |
| 10–50 km (local bus)  | 11              |
| 50–150 km (regional)  | 10              |
| 150–400 km (train)    | 7–8             |
| > 400 km (country)    | 6               |

## Coordinate format: lon,lat (NOT lat,lon!)

OSRM and staticmap use **longitude, latitude** — not latitude, longitude.

```
Oslo:    lon=10.7531, lat=59.9110  →  "10.7531,59.9110,Oslo"
Bergen:  lon=5.3242,  lat=60.3929  →  "5.3242,60.3929,Bergen"
```

Getting coordinates for stops with Overpass:

```python
import requests
q = '[out:json];node[railway=station][name~"Voss"](59.0,5.0,61.0,7.0);out body;'
r = requests.post('https://overpass-api.de/api/interpreter',
                  data={'data': q}, headers={'User-Agent': 'MapAnim/1.0'})
for e in r.json()['elements']:
    print(f"{e['lon']},{e['lat']},{e['tags']['name']}")
```

For bus stops: replace `railway=station` with `highway=bus_stop`.

## Output path

Save to any path you choose — for example:

```
~/videos/oslo_bergen.mp4
./outputs/leg1.mp4
```

## Mode selection: driving vs walking vs rail

| Transport          | Mode      | Notes |
|--------------------|-----------|-------|
| Car / bus          | `driving` | OSRM road routing |
| Walking            | `walking` | OSRM walking route |
| Train / railway    | `rail`    | Real track geometry from OSM via Overpass API |

**Never use `driving` for trains** — OSRM may follow a parallel road instead of the track.
`--mode rail` fetches `railway=rail` ways from OpenStreetMap and stitches them in order.

For clean results on named rail lines, use `--osm-relation <ID>`. The script routes through
the track graph using Dijkstra shortest-path on shared OSM nodes — parallel tracks and branch
lines are excluded automatically. For journeys spanning multiple named lines, pass comma-separated
IDs (e.g. `--osm-relation 3200969,965964` for Gardermobanen+Dovrebanen). Without any relation
flag, all rail ways in the bounding box are used (may look tangled in dense areas).

Find a relation ID on openstreetmap.org: search the line name, pick the "Relation" result,
and copy the number from the URL (e.g. `relation/965964` → ID is `965964`).

## Worked example: Oslo → Bergen (driving)

```bash
python3 make_map_animation.py \
  --start "10.7531,59.9110,Oslo" \
  --end   "5.3242,60.3929,Bergen" \
  --title "Oslo - Bergen" \
  --subtitle "~460 km" \
  --output oslo_bergen.mp4 \
  --zoom 7 --duration 5 --hold 2 --mode driving
```

## Worked example: Oslo S → Lillehammer (rail, Gardermobanen + Dovrebanen)

```bash
python3 make_map_animation.py \
  --start "10.7531,59.9110,Oslo S" \
  --end   "10.4663,61.1153,Lillehammer" \
  --title "Oslo S - Lillehammer" \
  --subtitle "~181 km • Gardermobanen + Dovrebanen" \
  --output oslo_lillehammer.mp4 \
  --zoom 8 --duration 5 --hold 2 \
  --mode rail --osm-relation 3200969,965964
```

Single-line variant (Dovrebanen only, from Eidsvoll):

```bash
python3 make_map_animation.py \
  --start "10.7531,59.9110,Oslo S" \
  --end   "10.4663,61.1153,Lillehammer" \
  --title "Dovrebanen // Oslo S - Lillehammer" \
  --subtitle "~183 km" \
  --output dovrebanen.mp4 \
  --zoom 8 --duration 5 --hold 2 \
  --mode rail --osm-relation 965964
```

## Troubleshooting

| Error | Fix |
|-------|-----|
| `OSRM: 400 Bad Request` | Check that coordinates are `lon,lat` not `lat,lon` |
| `ffmpeg: h264_videotoolbox not found` | Script auto-falls back to libx264 |
| Map is in the wrong location | Adjust `--zoom` — too high and the route goes off-screen |
| Animation is too fast | Increase `--duration` (e.g. `--duration 6`) |
| Too many frames, slow | Use `--fps 24` or `--duration 3` |
| `rail`: no tracks found | Check bounding box; falls back to driving automatically |
| `rail`: route jumps around | Add more `--stops` as waypoints; or use `--osm-relation` |
| Overpass 406 error | User-Agent is set correctly by the script; retry after a minute |
