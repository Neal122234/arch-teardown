#!/bin/bash
# Run Blender headless, but only one instance at a time (8 GB machine: two Blenders + agents run out of memory).
#   kit/blender_locked.sh <blender args...>      e.g. kit/blender_locked.sh -b --factory-startup -P kit/run_episode.py -- episodes/ep01_pantheon/episode.json --draft
# Waits (polling) while another process holds the lock; stale locks (dead pid) are cleared automatically.
#   BLENDER            Blender executable        (default /Applications/Blender.app/Contents/MacOS/Blender)
#   ARCH_BLENDER_LOCK  lock directory            (default $ARCH_KIT_OUT/.blender.lock, i.e. <repo>/out/.blender.lock)
#                      point every project that renders on this machine at the same lock.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
LOCK="${ARCH_BLENDER_LOCK:-${ARCH_KIT_OUT:-$REPO/out}/.blender.lock}"
if [ ! -x "$BLENDER" ]; then echo "Blender not found at $BLENDER (set BLENDER=...)" >&2; exit 127; fi
mkdir -p "$(dirname "$LOCK")"
n=0
until mkdir "$LOCK" 2>/dev/null; do
  pid=$(cat "$LOCK/pid" 2>/dev/null)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  [ $((n % 15)) -eq 0 ] && echo "waiting for Blender lock $LOCK (held by pid ${pid:-?}) ..." >&2
  n=$((n + 1)); sleep 4
done
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM
"$BLENDER" "$@"
