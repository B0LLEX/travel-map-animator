#!/usr/bin/env python3
"""
make_map_animation.py — Generate a Jet Lag-style animated travel-route MP4.

Map tiles are downloaded ONCE. All frames draw the route and markers directly
with PIL without network calls — fast and throttle-free.

Usage:
    python3 make_map_animation.py \
        --start "lon,lat,Place name" \
        --end   "lon,lat,Place name" \
        --stops "lon,lat,Name" "lon,lat,Name" \
        --title "Train // Kristiansand → Oslo S" \
        --subtitle "Sørlandsbanen • Day 1 • approx. 352 km" \
        --output /path/to/map_animation.mp4 \
        [--zoom 7] [--fps 30] [--duration 4] [--mode driving|walking|rail] \
        [--osm-relation 3200969,965964]

Modes:
    driving  — OSRM road routing (bus/car)
    walking  — OSRM walking route
    rail     — Actual rail tracks from OpenStreetMap via Overpass API

--osm-relation (only with --mode rail):
    OSM relation ID for a named rail line (e.g. 965964 = Dovrebanen).
    Accepts comma-separated IDs for multi-line journeys, e.g.
    "3200969,965964" (Gardermobanen+Dovrebanen) for Oslo S → Lillehammer.
    Fetches only ways that are members of the relation(s) — avoids tangling with
    branch lines and metro tracks in dense areas (Oslo). Without this flag all
    rail ways in the bounding box are used (legacy behavior). Find the ID on
    openstreetmap.org by searching for the line name and selecting the
    "Relation" result.

Dependencies:
    pip3 install --break-system-packages staticmap pillow requests
    brew install ffmpeg
"""

import argparse, math, pathlib, shutil, subprocess, tempfile, time
import requests
from staticmap import StaticMap, Line
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ─────────────────────────────────────────────
# COORDINATE CONVERSION (Mercator, same as staticmap)
# ─────────────────────────────────────────────

def _lon_to_x(lon, zoom):
    return ((lon + 180.) / 360) * (2 ** zoom)

def _lat_to_y(lat, zoom):
    return (1 - math.log(math.tan(math.radians(lat)) +
            1 / math.cos(math.radians(lat))) / math.pi) / 2 * (2 ** zoom)

def latlon_to_px(lat, lon, x_center, y_center, tile_size, width, height, zoom):
    """Convert lat/lon to pixel coordinates in the rendered map."""
    x = _lon_to_x(lon, zoom)
    y = _lat_to_y(lat, zoom)
    px = round((x - x_center) * tile_size + width / 2)
    py = round((y - y_center) * tile_size + height / 2)
    return px, py


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_font(size):
    for p in ['/System/Library/Fonts/Helvetica.ttc', '/System/Library/Fonts/Arial.ttf',
              '/Library/Fonts/Arial.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()


def fetch_osrm_route(start_lon, start_lat, end_lon, end_lat, stops=None, mode='driving'):
    """Fetch actual road routing from OSRM across all waypoints."""
    waypoints = [(start_lon, start_lat)]
    if stops:
        waypoints += [(lon, lat) for lon, lat, *_ in stops]
    waypoints.append((end_lon, end_lat))
    coords = ";".join(f"{lon},{lat}" for lon, lat in waypoints)
    url = f"http://router.project-osrm.org/route/v1/{mode}/{coords}"
    r = requests.get(url, params={'overview': 'full', 'geometries': 'geojson'},
                     headers={'User-Agent': 'travel-map-animator/1.0 (+https://github.com/B0LLEX/travel-map-animator)'},
                     timeout=30)
    r.raise_for_status()
    return r.json()['routes'][0]['geometry']['coordinates']


def fetch_rail_route(start_lon, start_lat, end_lon, end_lat, stops=None, relation_id=None):
    """Fetch actual rail tracks from OpenStreetMap via the Overpass API.

    With relation_id (a list of ints) only ways that are members of those OSM
    relations are fetched (one or more named lines, e.g. [3200969, 965964] for
    Gardermobanen+Dovrebanen). Without relation_id all rail ways in the bounding
    box are used — may tangle in dense areas like Oslo.
    """
    waypoints = [(start_lon, start_lat)]
    if stops:
        waypoints += [(lon, lat) for lon, lat, *_ in stops]
    waypoints.append((end_lon, end_lat))

    if relation_id:
        rel_ids = [relation_id] if isinstance(relation_id, int) else list(relation_id)
        print(f"  Fetching rail tracks from OSM relation(s) {', '.join(map(str, rel_ids))}...")
        rel_q = ''.join(f'relation({rid});' for rid in rel_ids)
        query = f"""
[out:json][timeout:60];
({rel_q});
(._;>>;);
out body;
"""
    else:
        all_lons = [w[0] for w in waypoints]
        all_lats = [w[1] for w in waypoints]
        margin = 0.3
        s_lat = min(all_lats) - margin
        n_lat = max(all_lats) + margin
        w_lon = min(all_lons) - margin
        e_lon = max(all_lons) + margin

        print(f"  Fetching rail tracks ({s_lat:.2f},{w_lon:.2f} → {n_lat:.2f},{e_lon:.2f})...")
        query = f"""
[out:json][timeout:60];
(
  way[railway=rail]({s_lat},{w_lon},{n_lat},{e_lon});
  way[railway=narrow_gauge]({s_lat},{w_lon},{n_lat},{e_lon});
);
(._;>;);
out body;
"""
    mirrors = [
        'https://overpass-api.de/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
        'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
    ]
    data = None
    for attempt, endpoint in enumerate(mirrors):
        try:
            if attempt > 0:
                time.sleep(5 * attempt)
                print(f"  → Trying {endpoint}...")
            r = requests.post(endpoint, data={'data': query},
                              headers={'User-Agent': 'travel-map-animator/1.0 (+https://github.com/B0LLEX/travel-map-animator)'},
                              timeout=90)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            print(f"  → Error: {e}")
            if attempt == len(mirrors) - 1:
                print("  WARNING: Overpass failed — falling back to OSRM driving")
                return fetch_osrm_route(start_lon, start_lat, end_lon, end_lat, stops, 'driving')

    nodes = {}
    for el in data['elements']:
        if el['type'] == 'node':
            nodes[el['id']] = (el['lon'], el['lat'])

    # With relation(s): keep only track ways (not platforms/stops)
    track_way_ids = None
    if relation_id:
        skip_roles = {'platform', 'stop', 'platform_entry_only', 'platform_exit_only',
                      'stop_entry_only', 'stop_exit_only'}
        track_way_ids = set()
        for el in data['elements']:
            if el['type'] == 'relation':
                track_way_ids |= {m['ref'] for m in el.get('members', [])
                                  if m['type'] == 'way' and m.get('role', '') not in skip_roles}

    segments = []
    way_node_lists = []
    for el in data['elements']:
        if el['type'] == 'way' and 'nodes' in el:
            if track_way_ids is not None and el['id'] not in track_way_ids:
                continue
            nids = [nid for nid in el['nodes'] if nid in nodes]
            if len(nids) >= 2:
                segments.append([nodes[nid] for nid in nids])
                way_node_lists.append(nids)

    if not segments:
        if relation_id:
            print("  WARNING: Relation(s) returned no tracks — retrying with bounding box")
            return fetch_rail_route(start_lon, start_lat, end_lon, end_lat, stops)
        print("  WARNING: No rail tracks found — falling back to OSRM driving")
        return fetch_osrm_route(start_lon, start_lat, end_lon, end_lat, stops, 'driving')

    print(f"  Found {len(segments)} rail segments")

    # Relation mode: shortest path through the track graph. OSM ways share node
    # IDs where tracks connect, giving real topology — parallel tracks and branch
    # lines are naturally excluded.
    if relation_id:
        route = route_via_graph(way_node_lists, nodes, waypoints[0], waypoints[-1])
        if route and len(route) >= 2:
            print(f"  Rail route (graph path): {len(route)} points")
            return route
        print("  WARNING: No connected graph path found — falling back to greedy stitching")

    route = connect_rail_segments(segments, waypoints,
                                  prefer_toward_end=bool(relation_id))
    print(f"  Rail route: {len(route)} points")
    return route


def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)


def route_via_graph(way_node_lists, node_coords, start, end):
    """Shortest path (Dijkstra) through the track graph from the node nearest
    start to the node nearest end. OSM ways share node IDs where tracks connect,
    so the graph has real topology — parallel tracks and branch lines fall away
    naturally. Returns a list of (lon, lat), or None if no path exists.
    """
    import heapq
    adj = {}
    def add_edge(a, b, w):
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))

    for nlist in way_node_lists:
        for a, b in zip(nlist, nlist[1:]):
            add_edge(a, b, dist(node_coords[a], node_coords[b]))

    # Stitch nearly-adjacent way endpoints (small data gaps, e.g. where two
    # relations meet without sharing a node).
    endpoints = list({nl[0] for nl in way_node_lists} | {nl[-1] for nl in way_node_lists})
    for i, a in enumerate(endpoints):
        ca = node_coords[a]
        for b in endpoints[i+1:]:
            d = dist(ca, node_coords[b])
            if 0 < d < 0.003:  # ~300 m
                add_edge(a, b, d)

    if not adj:
        return None
    src = min(adj, key=lambda n: dist(node_coords[n], start))
    dst = min(adj, key=lambda n: dist(node_coords[n], end))

    best = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    done = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        if u == dst:
            break
        for v, w in adj[u]:
            nd = d + w
            if nd < best.get(v, float('inf')):
                best[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))

    if dst not in done:
        return None
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    path.reverse()
    return [node_coords[n] for n in path]


def connect_rail_segments(segments, waypoints, prefer_toward_end=False):
    """Connect rail segments into a single continuous route.

    prefer_toward_end: when two candidate segments are within ~200 m of each
    other (tie-break zone), prefer the one whose far end is closest to the
    destination. This prevents the greedy walk from doubling back on parallel
    tracks in double-track sections (used as fallback in relation mode).
    """
    start = waypoints[0]
    end   = waypoints[-1]
    used = [False] * len(segments)
    route = []

    best_i, best_rev, best_d = 0, False, float('inf')
    for i, seg in enumerate(segments):
        if dist(start, seg[0]) < best_d:
            best_d, best_i, best_rev = dist(start, seg[0]), i, False
        if dist(start, seg[-1]) < best_d:
            best_d, best_i, best_rev = dist(start, seg[-1]), i, True

    seg = segments[best_i]
    route += (list(reversed(seg)) if best_rev else seg)
    used[best_i] = True

    for _ in range(len(segments) - 1):
        last = route[-1]
        # (connection distance, index, reversed, far-end distance to finish)
        candidates = []
        for i, seg in enumerate(segments):
            if used[i]: continue
            candidates.append((dist(last, seg[0]),  i, False, dist(seg[-1], end)))
            candidates.append((dist(last, seg[-1]), i, True,  dist(seg[0],  end)))
        if not candidates:
            break
        best_d2 = min(c[0] for c in candidates)
        if best_d2 > 0.4:
            break
        if prefer_toward_end:
            eps = 0.002  # ~200 m — catches switch-point endpoints on parallel tracks
            near = [c for c in candidates if c[0] <= best_d2 + eps]
            _, best_i2, best_rev2, _ = min(near, key=lambda c: c[3])
        else:
            _, best_i2, best_rev2, _ = min(candidates, key=lambda c: c[0])
        seg = segments[best_i2]
        route += (list(reversed(seg)) if best_rev2 else seg)[1:]
        used[best_i2] = True

    end_idx = min(range(len(route)), key=lambda i: dist(route[i], end))
    route = route[:end_idx+1]
    start_idx = min(range(len(route)), key=lambda i: dist(route[i], start))
    route = route[start_idx:]
    return route


def render_base_map(all_route_pts, zoom, w, h):
    """
    Download map tiles ONCE and return (styled RGBA PIL image, x_center, y_center, tile_size, zoom_used).
    All subsequent frames reuse this as background — no additional downloads.
    """
    tile_servers = [
        'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
    ]
    last_err = None
    for attempt, server in enumerate(tile_servers):
        try:
            if attempt > 0:
                print(f"  → Trying tile server: {server} (waiting 5s)...")
                time.sleep(5)
            m = StaticMap(
                w, h,
                url_template=server,
                headers={'User-Agent': 'travel-map-animator/1.0 (+https://github.com/B0LLEX/travel-map-animator)'},
                delay_between_retries=2,
                tile_request_timeout=20,
            )
            ghost = [(lon, lat) for lon, lat in all_route_pts]
            m.add_line(Line(ghost, '#00000000', 1))
            print(f"  Downloading map tiles from {server} ...")
            img = m.render(zoom=zoom)
            # Save coordinate center for pixel conversion
            x_center = m.x_center
            y_center = m.y_center
            tile_size = m.tile_size
            zoom_used = m.zoom

            # Jet Lag color styling
            img = ImageEnhance.Color(img).enhance(0.5)
            img = ImageEnhance.Brightness(img).enhance(0.78)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            print(f"  Base map ready ({w}x{h}, zoom={zoom_used})")
            return img.convert('RGBA'), x_center, y_center, tile_size, zoom_used
        except Exception as e:
            last_err = e
            print(f"  Tile error (attempt {attempt+1}): {e}")
    raise RuntimeError(f"Failed to load map tiles after {len(tile_servers)} attempts: {last_err}")


def draw_circle(draw, cx, cy, r, fill):
    """Draw a filled circle with PIL."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def build_frame(base_img_rgba, route_pts_so_far, all_route_pts, station_markers,
                start_name, end_name, title, subtitle,
                x_center, y_center, tile_size, zoom, w, h):
    """
    Build one frame by drawing route and markers onto a COPY of the base map.
    No network calls — pure PIL drawing operations.
    """
    img = base_img_rgba.copy()
    draw = ImageDraw.Draw(img)

    def to_px(lon, lat):
        return latlon_to_px(lat, lon, x_center, y_center, tile_size, w, h, zoom)

    # Draw route line progressively
    if len(route_pts_so_far) >= 2:
        pixels = [to_px(lon, lat) for lon, lat in route_pts_so_far]
        # Draw thick line segment by segment
        for i in range(len(pixels) - 1):
            draw.line([pixels[i], pixels[i+1]], fill='#FF4500', width=6)

    # Intermediate stops (show only those south of current position)
    last_lat = route_pts_so_far[-1][1] if route_pts_so_far else all_route_pts[0][1]
    for s_lat, s_lon, name in station_markers:
        if s_lat <= last_lat + 0.01:
            px, py = to_px(s_lon, s_lat)
            draw_circle(draw, px, py, 7, '#FFFFFF')
            draw_circle(draw, px, py, 4, '#FF6B35')

    # Start marker (always visible)
    s_lon_r, s_lat_r = all_route_pts[0]
    sx, sy = to_px(s_lon_r, s_lat_r)
    draw_circle(draw, sx, sy, 13, '#FFFFFF')
    draw_circle(draw, sx, sy,  8, '#FF0000')

    # End marker (shown at >95% progress)
    progress = len(route_pts_so_far) / max(1, len(all_route_pts))
    if progress > 0.95:
        e_lon_r, e_lat_r = all_route_pts[-1]
        ex, ey = to_px(e_lon_r, e_lat_r)
        draw_circle(draw, ex, ey, 13, '#FFFFFF')
        draw_circle(draw, ex, ey,  8, '#FF0000')

    # UI overlay (dark bars + text)
    ov = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d  = ImageDraw.Draw(ov)
    d.rectangle([(0, 0), (w, 100)],    fill=(0, 0, 0, 175))
    d.rectangle([(0, h - 80), (w, h)], fill=(0, 0, 0, 175))
    img = Image.alpha_composite(img, ov)

    draw2 = ImageDraw.Draw(img)
    draw2.text((30, 16), title,    font=get_font(44), fill='#FFFFFF')
    draw2.text((30, 66), subtitle, font=get_font(24), fill='#BBBBBB')
    draw2.line([(0, h - 83), (w, h - 83)], fill='#FF4500', width=2)
    draw2.text((30,      h - 60), f"▶  {start_name}", font=get_font(20), fill='#FF8C69')
    draw2.text((w - 420, h - 60), f"{end_name}  ◀",   font=get_font(20), fill='#FF8C69')

    return img.convert('RGB')


def easing(t):
    """Ease in-out: slow start and end, fast middle."""
    return t * t * (3 - 2 * t)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start',    required=True)
    ap.add_argument('--end',      required=True)
    ap.add_argument('--stops',    nargs='*', default=[])
    ap.add_argument('--title',    required=True)
    ap.add_argument('--subtitle', default='')
    ap.add_argument('--output',   required=True)
    ap.add_argument('--zoom',     type=int, default=7)
    ap.add_argument('--fps',      type=int, default=30)
    ap.add_argument('--duration', type=float, default=4.0)
    ap.add_argument('--hold',     type=float, default=1.5)
    ap.add_argument('--mode',     default='driving',
                    choices=['driving', 'walking', 'rail'])
    ap.add_argument('--osm-relation', type=str, default=None, metavar='ID[,ID...]',
                    help='OSM relation ID(s) for the rail line (only with --mode rail); '
                         'comma-separated for multi-line journeys, e.g. '
                         '"3200969,965964" for Gardermobanen+Dovrebanen '
                         '(Oslo S to Lillehammer)')
    ap.add_argument('--width',    type=int, default=1920)
    ap.add_argument('--height',   type=int, default=1080)
    args = ap.parse_args()

    def parse_point(s):
        parts = s.split(',', 2)
        return float(parts[0]), float(parts[1]), parts[2] if len(parts) > 2 else ''

    s_lon, s_lat, start_name = parse_point(args.start)
    e_lon, e_lat, end_name   = parse_point(args.end)
    stops = [parse_point(s) for s in (args.stops or [])]
    station_markers = [(lat, lon, name) for lon, lat, name in stops]

    rel_ids = None
    if args.osm_relation:
        try:
            rel_ids = [int(x) for x in args.osm_relation.split(',') if x.strip()]
        except ValueError:
            ap.error(f"--osm-relation must be integers (comma-separated): {args.osm_relation!r}")

    # Fetch route
    if args.mode == 'rail':
        print("Fetching rail route from OpenStreetMap...")
        raw_coords = fetch_rail_route(s_lon, s_lat, e_lon, e_lat, stops,
                                      relation_id=rel_ids)
    else:
        if args.osm_relation:
            print("  NOTE: --osm-relation only applies to --mode rail — ignoring")
        print(f"Fetching route from OSRM ({args.mode})...")
        raw_coords = fetch_osrm_route(s_lon, s_lat, e_lon, e_lat, stops, args.mode)

    step = max(1, len(raw_coords) // 400)
    route_pts = raw_coords[::step]
    if route_pts[-1] != raw_coords[-1]:
        route_pts.append(raw_coords[-1])
    print(f"  Route: {len(raw_coords)} → {len(route_pts)} points after decimation")

    # ── Download base map ONCE ─────────────────────────────────
    base_img, x_center, y_center, tile_size, zoom_used = render_base_map(
        route_pts, args.zoom, args.width, args.height
    )

    # Calculate frames
    n_anim  = int(args.fps * args.duration)
    n_hold  = int(args.fps * args.hold)
    n_total = n_anim + n_hold
    n_pts   = len(route_pts)

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix='map_anim_'))
    print(f"Generating {n_total} frames (PIL-only, no network calls)...")

    for frame_i in range(n_total):
        if frame_i < n_anim:
            t_eased = easing((frame_i + 1) / n_anim)
            n_show  = max(2, int(t_eased * n_pts))
        else:
            n_show = n_pts

        pts_so_far = route_pts[:n_show]
        img = build_frame(
            base_img, pts_so_far, route_pts, station_markers,
            start_name, end_name, args.title, args.subtitle,
            x_center, y_center, tile_size, zoom_used,
            args.width, args.height
        )
        img.save(tmpdir / f"frame_{frame_i:05d}.png", 'PNG')

        if frame_i % 15 == 0 or frame_i == n_total - 1:
            pct = int(100 * (frame_i + 1) / n_total)
            print(f"  [{pct:3d}%] Frame {frame_i+1}/{n_total}", end='\r', flush=True)

    print(f"\nAssembling video: {args.output}")
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-framerate', str(args.fps),
        '-i', str(tmpdir / 'frame_%05d.png'),
        '-c:v', 'h264_videotoolbox',
        '-b:v', '8000k',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        str(out)
    ]
    result = subprocess.run(ffmpeg_cmd, capture_output=True)
    if result.returncode != 0:
        print("  h264_videotoolbox not available, using libx264...")
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-framerate', str(args.fps),
            '-i', str(tmpdir / 'frame_%05d.png'),
            '-c:v', 'libx264', '-preset', 'fast',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            str(out)
        ]
        subprocess.run(ffmpeg_cmd, check=True)

    shutil.rmtree(tmpdir)
    size_mb = out.stat().st_size / 1_000_000
    print(f"Done: {out}  ({size_mb:.1f} MB, {n_total/args.fps:.1f}s)")


if __name__ == '__main__':
    main()
