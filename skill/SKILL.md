---
name: map-animation
description: Use when the user wants an animated map where a travel route draws itself progressively (Jet Lag-style), or asks to "lag kartanimasjon", "animert kart", or "draw the route on a map". Covers bus, train, and any multi-leg journey.
---

# Map Animation — Jet Lag-stil animert rute

## Overview

Generer en MP4-video (1920×1080) der en reiserute tegner seg gradvis på et desaturert
OpenStreetMap-kart, med stasjonspunkter og Jet Lag-stil overlay.

Scriptet `~/ObsidianVault/projects/tools/make_map_animation.py` gjør all jobben.
Kall det — ikke reimplementer logikken inline.

## Avhengigheter (installer én gang)

```bash
pip3 install --break-system-packages staticmap pillow requests
brew install ffmpeg   # hvis ikke allerede installert
```

## Rask oppskrift

```bash
python3 ~/ObsidianVault/projects/tools/make_map_animation.py \
  --start  "10.7531,59.9110,Oslo S" \
  --end    "7.9971,58.1456,Kristiansand" \
  --stops  "10.2038,59.7402,Drammen" \
             "9.6506,59.6722,Kongsberg" \
             "9.3227,59.4180,Nordagutu" \
  --title    "Tog // Oslo S → Kristiansand" \
  --subtitle "Sørlandsbanen • ca. 352 km" \
  --output   ~/ObsidianVault/raw/video-projects/PROSJEKT/kart_animasjon.mp4 \
  --zoom 7 --duration 5 --hold 2 --mode driving
```

## Argumenter

| Argument     | Påkrevd | Default  | Forklaring |
|-------------|---------|---------|------------|
| `--start`   | ✅      | —       | `"lon,lat,Navn"` startpunkt |
| `--end`     | ✅      | —       | `"lon,lat,Navn"` sluttpunkt |
| `--stops`   | ❌      | ingen   | En eller flere `"lon,lat,Navn"` mellomstasjoner |
| `--title`   | ✅      | —       | Stor tekst øverst på kartet |
| `--subtitle`| ❌      | tom     | Liten undertekst under tittel |
| `--output`  | ✅      | —       | Utfil (`.mp4`) |
| `--zoom`    | ❌      | 7       | OSM-zoomnivå (6=hele Norge, 11=by) |
| `--fps`     | ❌      | 30      | Frames per sekund |
| `--duration`| ❌      | 4.0     | Sekunder for selve animasjonen |
| `--hold`    | ❌      | 1.5     | Ekstra sekunder med ferdig kart |
| `--mode`    | ❌      | driving | `driving` eller `walking` (OSRM) eller `rail` (faktiske OSM jernbanespor) |

## Riktig zoom per strekning

| Distanse | Anbefalt zoom |
|----------|--------------|
| < 10 km  (by → by) | 12 |
| 10–50 km  (buss/lokal) | 11 |
| 50–150 km (regional) | 10 |
| 150–400 km (tog) | 7–8 |
| > 400 km  (hele Norge) | 6 |

## Hente koordinater til stops

Bruk Overpass API — slik finner du togstasjoner automatisk:

```python
import requests
q = '[out:json];node[railway=station][name~"Kongsberg"](59.0,9.0,60.0,10.0);out body;'
r = requests.post('https://overpass-api.de/api/interpreter',
                  data={'data': q}, headers={'User-Agent': 'MapAnim/1.0'})
for e in r.json()['elements']:
    print(f"{e['lon']},{e['lat']},{e['tags']['name']}")
```

For bussholdeplasser: bytt `railway=station` med `highway=bus_stop`.

## Koordinatformat: lon,lat (ikke lat,lon!)

OSRM og staticmap bruker **longitude, latitude** — IKKE latitude, longitude.
```
Oslo S:          lon=10.7531, lat=59.9110  → "10.7531,59.9110,Oslo S"
Kristiansand:    lon=7.9971,  lat=58.1456  → "7.9971,58.1456,Kristiansand"
```

## Output-plassering

Lagre alltid i prosjektmappen:
```
~/ObsidianVault/raw/video-projects/<prosjekt-slug>/kart_<etappe>.mp4
```

## Modus-valg: driving vs rail

| Transport | Modus | Forklaring |
|-----------|-------|------------|
| Buss / bil | `driving` | OSRM følger veier — riktig for buss |
| Gang | `walking` | OSRM gangrute |
| Tog / jernbane | `rail` | Henter faktiske sporgeometrier fra OSM via Overpass API |

**Aldri bruk `driving` for tog** — OSRM kan ta feil vei parallelt med sporet.
`--mode rail` bruker `railway=rail`-ways fra OpenStreetMap og kobler segmentene i riktig rekkefølge.

```bash
# Eksempel: Sørlandsbanen med faktisk jernbanespor
python3 $TOOLS \
  --start "7.9871,58.1456,Kristiansand" \
  --end   "10.7531,59.9110,Oslo S" \
  --stops "9.6506,59.6722,Kongsberg" \
          "10.2038,59.7402,Drammen" \
  --title "Tog // Kristiansand → Oslo S" \
  --subtitle "Sørlandsbanen • ca. 352 km" \
  --output ~/kart_anim_tog.mp4 \
  --zoom 7 --duration 6 --hold 2 --mode rail
```

## Feil og løsninger

| Feil | Løsning |
|------|---------|
| `OSRM: 400 Bad Request` | Sjekk at koordinater er `lon,lat`, ikke omvendt |
| `ffmpeg: h264_videotoolbox not found` | Scriptet faller automatisk tilbake til libx264 |
| Kart er feil sted | Juster `--zoom` — for høy zoom → kart strekker seg utenfor |
| Animasjonen er for rask | Øk `--duration` (f.eks. `--duration 6`) |
| For mange frames, tregt | Bruk `--fps 24` eller `--duration 3` |
| `rail`: Ingen spor funnet | Sjekk bounding box — prøv med større margin. Faller tilbake til driving. |
| `rail`: Rute hopper mellom steder | Legg til flere `--stops` som stasjonspunkter langs ruten |
| Overpass 406-feil | User-Agent mangler — bruker nå `requests`-biblioteket korrekt |

## Eksempel: Nord-Odal reise (4 etapper)

```bash
TOOLS=~/ObsidianVault/projects/tools/make_map_animation.py
PROJ=~/ObsidianVault/raw/video-projects/nord-odal-dag1-2026-04-17

# Etappe 1: Buss Tingsaker → Kristiansand
python3 $TOOLS \
  --start "8.3974,58.2612,Tingsaker (Lillesand)" \
  --end   "7.9957,58.1462,Kristiansand Rutebilstasjon" \
  --title "Buss 100 // Tingsaker → Kristiansand" \
  --subtitle "Dag 1 • E18/E39 • ca. 31 km" \
  --output $PROJ/kart_anim_1_buss_lillesand.mp4 \
  --zoom 11 --duration 3 --hold 1.5

# Etappe 2: Tog Kristiansand → Oslo S (Sørlandsbanen)
python3 $TOOLS \
  --start "7.9871,58.1456,Kristiansand" \
  --end   "10.7531,59.9110,Oslo S" \
  --stops "7.9676,58.2532,Vennesla" \
          "8.6307,58.6575,Nelaug" \
          "9.0233,58.8699,Gjerstad" \
          "9.1562,58.9715,Neslandsvatn" \
          "9.0641,59.0961,Drangedal" \
          "9.1012,59.2989,Lunde" \
          "9.0695,59.4093,Bø" \
          "9.3227,59.4180,Nordagutu" \
          "9.6506,59.6722,Kongsberg" \
          "9.9107,59.7673,Hokksund" \
          "10.2038,59.7402,Drammen" \
  --title "Tog // Kristiansand → Oslo S" \
  --subtitle "Sørlandsbanen • ca. 352 km" \
  --output $PROJ/kart_anim_2_tog_kristiansand.mp4 \
  --zoom 7 --duration 6 --hold 2

# Etappe 3: Tog Oslo S → Eidsvoll (Gardermobanen)
python3 $TOOLS \
  --start "10.7531,59.9110,Oslo S" \
  --end   "11.2477,60.3297,Eidsvoll" \
  --stops "11.0452,59.9534,Lillestrøm" \
          "11.1769,60.1423,Jessheim" \
          "11.0968,60.1932,Oslo lufthavn" \
          "11.2029,60.2489,Dal" \
          "11.1694,60.2879,Eidsvoll verk" \
  --title "Tog // Oslo S → Eidsvoll" \
  --subtitle "Gardermobanen • ca. 68 km" \
  --output $PROJ/kart_anim_3_tog_eidsvoll.mp4 \
  --zoom 10 --duration 4 --hold 1.5

# Etappe 4: Buss Eidsvoll → Skarnes (Nord-Odal)
python3 $TOOLS \
  --start "11.2477,60.3297,Eidsvoll" \
  --end   "11.6811,60.2541,Skarnes (Nord-Odal)" \
  --stops "11.4600,60.2650,Feiring" \
          "11.6100,60.2550,Hvam" \
  --title "Buss 121 // Eidsvoll → Skarnes" \
  --subtitle "Nord-Odal • ca. 44 km" \
  --output $PROJ/kart_anim_4_buss_nordodal.mp4 \
  --zoom 11 --duration 3 --hold 1.5
```

## Temperatur / CPU-tips

Scriptet bruker `h264_videotoolbox` (M-chip hardware encoder) automatisk.
CPU holdes under 5% selv med 200+ frames. Ingen fare for overoppheting.
