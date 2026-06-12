#!/usr/bin/env bash
# Renders a 1920x1080 MP4 of a driving route Oslo -> Bergen.
python3 "$(dirname "$0")/../make_map_animation.py" \
  --start "10.7531,59.9110,Oslo" \
  --end   "5.3242,60.3929,Bergen" \
  --title "Oslo → Bergen" --subtitle "~460 km" \
  --mode driving --zoom 7 \
  --output oslo_bergen.mp4
