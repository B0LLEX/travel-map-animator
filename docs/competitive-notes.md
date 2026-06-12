# Competitive Research Notes

_Research date: 2026-06-12. Queries run: "animated travel route map video generator github", "jet lag the game style map animation open source", "python animated route map mp4 openstreetmap", "github route animation travel video CLI ffmpeg", and several follow-up targeted searches._

---

## Findings Table

| Tool | URL | Produces downloadable video file? | Open source? | Real rail geometry from OSM? | Last maintained | Watermark / account required? |
|---|---|---|---|---|---|---|
| **Route Generator** (routegen) | https://github.com/WanderlandTravelers/routegen | Yes (AVI/MP4 via ffmpeg) | Yes (GPL-3.0) | No — user draws route manually on a static background image | Last commit Sep 2018 (abandoned) | No watermark; desktop GUI app, no account | 
| **Travel Map Animation** (Flutter mobile app) | https://github.com/saadithya | Yes — exports video locally to device | Open source (Flutter/OSM/OSRM) | No — uses OSRM driving routes only, no rail | Last updated May 2026 (active) | No watermark; Android-only mobile app, no account |
| **Mapimator** | https://mapimator.com | Yes (MP4/GIF, up to 4K) | No — commercial SaaS | No — general route drawing, no OSM rail geometry | Active (commercial, 2026) | Watermark on free tier; paid plan from $12/mo removes it; account required |
| **Mult.dev** | https://mult.dev | Yes — video export from browser/app | No — commercial SaaS | No — general travel map animation | Active (commercial, 2026) | Account required; pricing not fully disclosed |
| **TravelBoast** | mobile app (iOS/Android) | Yes — shares video clips | No — commercial mobile app | No | Active (commercial) | Watermark / account required |
| **CARTO VL / Mapbox blog** | https://www.mapbox.com/blog/building-cinematic-route-animations-with-mapboxgl | In-browser animation only (no downloadable file) | SDK is open; workflow is not a tool | No | N/A — tutorial/SDK, not a tool | Mapbox API key required |
| **Oisin-M / Animate-Your-Travels** | https://github.com/Oisin-M/Animate-Your-Travels | No — browser scratch-map, no video export | Yes | No | Stale (no recent activity) | No account, but no video output |

---

## Assessment

The closest open-source neighbor is **Route Generator** (routegen), a Qt/C++ desktop GUI from 2008–2018 that lets a user manually draw a route over a static map image and encode frames to AVI/MP4 via ffmpeg. It has been unmaintained for ~8 years, has zero GitHub stars on this mirror, requires manual GUI interaction (no CLI), does not fetch real routing geometry from any service, and has no concept of OSM tile downloads, rail ways, or multi-modal routing. The Flutter mobile app (`saadithya/Travel-Map-Animation`) is the most recent active open-source alternative; it is Android-only, uses OSRM for driving geometry, but has no CLI interface, no rail support, and no scripted/batch workflow. The commercial SaaS tools — Mapimator and Mult.dev — produce polished video exports but require browser accounts and paid plans to remove watermarks; neither fetches real railway geometry from OSM relations. No CLI-first, headless, Python-based tool that produces an MP4 animated travel route from coordinate pairs — with real routing geometry (road via OSRM _and_ rail via Overpass/OSM relation filtering) — was found in any form.

---

## Differentiation Sentence (for README "Why this exists")

> `travel-map-animator` is the only open-source CLI tool that renders a complete animated travel-route MP4 — including real rail geometry fetched directly from OpenStreetMap, with no account, no watermark, and no GUI — running fully locally on a single Python file with ffmpeg.

---

## GATE: PROCEED

No dominant, maintained, open-source tool that covers the same feature set (CLI invocation, coordinate-driven, real OSRM road routing + real OSM rail geometry, PIL frame rendering, ffmpeg MP4 output, no account or watermark) was found. The nearest open-source alternative (routegen) is 8 years stale and GUI-only. The commercial tools do not expose their source and require accounts/paid plans. This project has a genuine, unoccupied niche.
