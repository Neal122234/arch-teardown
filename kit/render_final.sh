#!/bin/bash
# Final 1080x1920 frames: one Blender process per "render_segments" entry of the episode JSON (lock-safe, resumable).
#   kit/render_final.sh EPISODE.json FRAMES_DIR [ANCHORS.json] [segment ...]
# - frames 1..round(duration*fps) (the loop frame duration*fps+1 == frame 1 is not rendered)
# - existing frames are kept (--skip-existing), so re-running after a crash only renders what is missing
# - ANCHORS.json ("-" to skip) is exported by the first process (label anchors for overlay.py)
# - per-segment log: FRAMES_DIR.<segment>.log ; summary lines "[run] segment ..." carry s/frame
set -e
KIT="$(cd "$(dirname "$0")" && pwd)"
EP="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT="$(mkdir -p "$2" && cd "$2" && pwd)"
ANCH="${3:--}"
shift 3 2>/dev/null || shift $#
N=$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(round(d.get('duration',40)*d.get('fps',24)))" "$EP")
SEGS="$*"
[ -z "$SEGS" ] && SEGS=$(python3 -c "import json,sys;print(' '.join(s['name'] for s in json.load(open(sys.argv[1])).get('render_segments',[])))" "$EP")
[ -z "$SEGS" ] && { echo "no render_segments in $EP" >&2; exit 1; }
first=1
for s in $SEGS; do
  extra=()
  if [ $first = 1 ] && [ "$ANCH" != "-" ]; then extra=(--anchors "$(cd "$(dirname "$ANCH")" && pwd)/$(basename "$ANCH")"); fi
  first=0
  echo "$(date +%T) segment $s -> $OUT" >&2
  "$KIT/blender_locked.sh" -b --factory-startup -P "$KIT/run_episode.py" -- "$EP" \
      --anim "$OUT" --frames "1:$N" --segment "$s" --skip-existing "${extra[@]}" > "$OUT.$s.log" 2>&1
  grep -E "^\[run\] (segment $s |peak)" "$OUT.$s.log" >&2 || true
done
echo "$(date +%T) done: $(ls "$OUT" | grep -c '\.png$') frames in $OUT" >&2
