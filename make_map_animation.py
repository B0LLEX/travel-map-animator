#!/usr/bin/env python3
"""
make_map_animation.py — Generer en Jet Lag-stil kartanimasjon der ruten tegner seg selv.

Kartfliser vert lasta ned ÉIN GONG. Alle frames teiknar rute+markørar direkte
med PIL utan nettverkskall — rask og throttle-fri.

Usage:
    python3 make_map_animation.py \
        --start "lon,lat,Stedsnavn" \
        --end   "lon,lat,Stedsnavn" \
        --stops "lon,lat,Navn" "lon,lat,Namn" \
        --title "Tog // Kristiansand → Oslo S" \
        --subtitle "Sørlandsbanen • Dag 1 • ca. 352 km" \
        --output /path/til/kart_animasjon.mp4 \
        [--zoom 7] [--fps 30] [--duration 4] [--mode driving|walking|rail] \
        [--osm-relation 200768]

Modi:
    driving  — OSRM veikjøring (buss/bil)
    walking  — OSRM gangrute
    rail     — Faktiske jernbanespor frå OpenStreetMap via Overpass API

--osm-relation (berre --mode rail):
    OSM-relasjons-ID for ei navngjeven banestrekning (t.d. 200768 = Dovrebanen).
    Hentar berre ways som er medlem av relasjonen — unngår fletter med sidespor
    og lokalbaner i tette område (Oslo). Utan flagget vert alle rail-ways i
    bounding box brukt (gammal oppførsel). Finn ID på openstreetmap.org ved å
    søkje på banenamnet og velje "Relation"-treffet.

Avhengigheter:
    pip3 install --break-system-packages staticmap pillow requests
    brew install ffmpeg
"""

import argparse, json, math, os, pathlib, shutil, subprocess, sys, tempfile, time
import requests
from staticmap import StaticMap, Line, CircleMarker
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ─────────────────────────────────────────────
# KOORDINATKONVERTERING (Mercator, same as staticmap)
# ─────────────────────────────────────────────

def _lon_to_x(lon, zoom):
    return ((lon + 180.) / 360) * (2 ** zoom)

def _lat_to_y(lat, zoom):
    return (1 - math.log(math.tan(math.radians(lat)) +
            1 / math.cos(math.radians(lat))) / math.pi) / 2 * (2 ** zoom)

def latlon_to_px(lat, lon, x_center, y_center, tile_size, width, height, zoom):
    """Konverter lat/lon til pikselkoordinatar i det renderte kartet."""
    x = _lon_to_x(lon, zoom)
    y = _lat_to_y(lat, zoom)
    px = round((x - x_center) * tile_size + width / 2)
    py = round((y - y_center) * tile_size + height / 2)
    return px, py


# ─────────────────────────────────────────────
# HJELPEFUNKSJONER
# ─────────────────────────────────────────────

def get_font(size):
    for p in ['/System/Library/Fonts/Helvetica.ttc', '/System/Library/Fonts/Arial.ttf',
              '/Library/Fonts/Arial.ttf']:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()


def fetch_osrm_route(start_lon, start_lat, end_lon, end_lat, stops=None, mode='driving'):
    """Hent faktisk veikjøring frå OSRM via alle waypoints."""
    waypoints = [(start_lon, start_lat)]
    if stops:
        waypoints += [(lon, lat) for lon, lat, *_ in stops]
    waypoints.append((end_lon, end_lat))
    coords = ";".join(f"{lon},{lat}" for lon, lat in waypoints)
    url = f"http://router.project-osrm.org/route/v1/{mode}/{coords}"
    r = requests.get(url, params={'overview': 'full', 'geometries': 'geojson'},
                     headers={'User-Agent': 'MapAnimation/2.0'}, timeout=30)
    r.raise_for_status()
    return r.json()['routes'][0]['geometry']['coordinates']


def fetch_rail_route(start_lon, start_lat, end_lon, end_lat, stops=None, relation_id=None):
    """Hent faktiske jernbanespor frå OpenStreetMap via Overpass API.

    Med relation_id vert berre ways som er medlem av den OSM-relasjonen henta
    (rein banestrekning, t.d. 200768 = Dovrebanen). Utan relation_id vert alle
    rail-ways i bounding box brukt — kan gje fletter i tette område som Oslo.
    """
    waypoints = [(start_lon, start_lat)]
    if stops:
        waypoints += [(lon, lat) for lon, lat, *_ in stops]
    waypoints.append((end_lon, end_lat))

    if relation_id:
        print(f"  Henter jernbanespor frå OSM-relasjon {relation_id}...")
        query = f"""
[out:json][timeout:60];
relation({relation_id});
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

        print(f"  Henter jernbanespor ({s_lat:.2f},{w_lon:.2f} → {n_lat:.2f},{e_lon:.2f})...")
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
                print(f"  → Prøver {endpoint}...")
            r = requests.post(endpoint, data={'data': query},
                              headers={'User-Agent': 'MapAnimation/2.0'}, timeout=90)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            print(f"  → Feil: {e}")
            if attempt == len(mirrors) - 1:
                print("  ADVARSEL: Overpass feilet — bruker OSRM driving")
                return fetch_osrm_route(start_lon, start_lat, end_lon, end_lat, stops, 'driving')

    nodes = {}
    for el in data['elements']:
        if el['type'] == 'node':
            nodes[el['id']] = (el['lon'], el['lat'])

    # Med relasjon: behold berre spor-ways (ikkje plattformer/stopp-medlem)
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
    for el in data['elements']:
        if el['type'] == 'way' and 'nodes' in el:
            if track_way_ids is not None and el['id'] not in track_way_ids:
                continue
            pts = [nodes[nid] for nid in el['nodes'] if nid in nodes]
            if len(pts) >= 2:
                segments.append(pts)

    if not segments:
        if relation_id:
            print(f"  ADVARSEL: Relasjon {relation_id} gav ingen spor — prøver bounding box")
            return fetch_rail_route(start_lon, start_lat, end_lon, end_lat, stops)
        print("  ADVARSEL: Ingen jernbanespor funnet — bruker OSRM driving")
        return fetch_osrm_route(start_lon, start_lat, end_lon, end_lat, stops, 'driving')

    print(f"  Fant {len(segments)} jernbane-segmenter")
    route = connect_rail_segments(segments, waypoints)
    print(f"  Jernbanerute: {len(route)} punkter")
    return route


def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)


def connect_rail_segments(segments, waypoints):
    """Kobler jernbane-segmenter til ein samanhengande rute."""
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
        best_i2, best_rev2, best_d2 = -1, False, float('inf')
        for i, seg in enumerate(segments):
            if used[i]: continue
            if dist(last, seg[0]) < best_d2:
                best_d2, best_i2, best_rev2 = dist(last, seg[0]), i, False
            if dist(last, seg[-1]) < best_d2:
                best_d2, best_i2, best_rev2 = dist(last, seg[-1]), i, True
        if best_d2 > 0.4 or best_i2 == -1:
            break
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
    Last ned kartfliser ÉIN GONG og returner (stilert RGBA PIL-bilete, x_center, y_center, tile_size, zoom_used).
    Alle påfølgande frames bruker dette som bakgrunn — ingen ny nedlasting.
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
                print(f"  → Prøver tile-server: {server} (venter 5s)...")
                time.sleep(5)
            m = StaticMap(
                w, h,
                url_template=server,
                headers={'User-Agent': 'MapAnimation/2.0 (nord-odal-vlog)'},
                delay_between_retries=2,
                tile_request_timeout=20,
            )
            ghost = [(lon, lat) for lon, lat in all_route_pts]
            m.add_line(Line(ghost, '#00000000', 1))
            print(f"  Laster ned kartfliser frå {server} ...")
            img = m.render(zoom=zoom)
            # Lagre koordinatsenter for pikselkonvertering
            x_center = m.x_center
            y_center = m.y_center
            tile_size = m.tile_size
            zoom_used = m.zoom

            # Jet Lag-fargestyling
            img = ImageEnhance.Color(img).enhance(0.5)
            img = ImageEnhance.Brightness(img).enhance(0.78)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            print(f"  ✅ Basiskart klar ({w}×{h}, zoom={zoom_used})")
            return img.convert('RGBA'), x_center, y_center, tile_size, zoom_used
        except Exception as e:
            last_err = e
            print(f"  Tile-feil (forsøk {attempt+1}): {e}")
    raise RuntimeError(f"Klarte ikkje laste kartfliser etter {len(tile_servers)} forsøk: {last_err}")


def draw_circle(draw, cx, cy, r, fill):
    """Teikn fylt sirkel med PIL."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def build_frame(base_img_rgba, route_pts_so_far, all_route_pts, station_markers,
                start_name, end_name, title, subtitle,
                x_center, y_center, tile_size, zoom, w, h):
    """
    Bygg éin frame ved å teikne rute + markørar på ein KOPI av base-kartet.
    Ingen nettverkskall — berre PIL-teikneoperasjonar.
    """
    img = base_img_rgba.copy()
    draw = ImageDraw.Draw(img)

    def to_px(lon, lat):
        return latlon_to_px(lat, lon, x_center, y_center, tile_size, w, h, zoom)

    # Teikn rute-linja progressivt
    if len(route_pts_so_far) >= 2:
        pixels = [to_px(lon, lat) for lon, lat in route_pts_so_far]
        # Teikn tjukk linje segment for segment
        for i in range(len(pixels) - 1):
            draw.line([pixels[i], pixels[i+1]], fill='#FF4500', width=6)

    # Mellomstasjonar (vis berre dei vi har passert)
    last_lat = route_pts_so_far[-1][1] if route_pts_so_far else all_route_pts[0][1]
    for s_lat, s_lon, name in station_markers:
        if s_lat <= last_lat + 0.01:
            px, py = to_px(s_lon, s_lat)
            draw_circle(draw, px, py, 7, '#FFFFFF')
            draw_circle(draw, px, py, 4, '#FF6B35')

    # Start-markør (alltid synleg)
    s_lon_r, s_lat_r = all_route_pts[0]
    sx, sy = to_px(s_lon_r, s_lat_r)
    draw_circle(draw, sx, sy, 13, '#FFFFFF')
    draw_circle(draw, sx, sy,  8, '#FF0000')

    # Slutt-markør (ved >95% framdrift)
    progress = len(route_pts_so_far) / max(1, len(all_route_pts))
    if progress > 0.95:
        e_lon_r, e_lat_r = all_route_pts[-1]
        ex, ey = to_px(e_lon_r, e_lat_r)
        draw_circle(draw, ex, ey, 13, '#FFFFFF')
        draw_circle(draw, ex, ey,  8, '#FF0000')

    # UI-overlay (mørke striper + tekst)
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
    """Ease in-out: langsom start og slutt, rask midten."""
    return t * t * (3 - 2 * t)


# ─────────────────────────────────────────────
# HOVED
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
    ap.add_argument('--osm-relation', type=int, default=None, metavar='ID',
                    help='OSM relation ID for banestrekninga (berre --mode rail), '
                         't.d. 200768 for Dovrebanen')
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

    # Hent rute
    if args.mode == 'rail':
        print("Henter jernbanerute frå OpenStreetMap...")
        raw_coords = fetch_rail_route(s_lon, s_lat, e_lon, e_lat, stops,
                                      relation_id=args.osm_relation)
    else:
        if args.osm_relation:
            print("  MERK: --osm-relation gjeld berre --mode rail — ignorert")
        print(f"Henter rute frå OSRM ({args.mode})...")
        raw_coords = fetch_osrm_route(s_lon, s_lat, e_lon, e_lat, stops, args.mode)

    step = max(1, len(raw_coords) // 400)
    route_pts = raw_coords[::step]
    if route_pts[-1] != raw_coords[-1]:
        route_pts.append(raw_coords[-1])
    print(f"  Rute: {len(raw_coords)} → {len(route_pts)} punkt etter tynning")

    # ── Last ned basiskart ÉIN GONG ─────────────────────────────────
    base_img, x_center, y_center, tile_size, zoom_used = render_base_map(
        route_pts, args.zoom, args.width, args.height
    )

    # Berekn frames
    n_anim  = int(args.fps * args.duration)
    n_hold  = int(args.fps * args.hold)
    n_total = n_anim + n_hold
    n_pts   = len(route_pts)

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix='map_anim_'))
    print(f"Genererer {n_total} frames (PIL-only, ingen nettverkskall)...")

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

    print(f"\nKombinerer til video: {args.output}")
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
        print("  h264_videotoolbox ikkje tilgjengeleg, bruker libx264...")
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
    print(f"✅ Ferdig: {out}  ({size_mb:.1f} MB, {n_total/args.fps:.1f}s)")


if __name__ == '__main__':
    main()
