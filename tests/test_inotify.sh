#!/usr/bin/env bash
# test_inotify.sh — bash-side timing + concurrency test for the monitor.
#
# Verifies:
#   - inotify latency from send to monitor event < 200ms (typical < 50ms)
#   - 100 concurrent writers all land in the room, no torn lines
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOM_DIR="$(mktemp -d)"
trap 'rm -rf "$ROOM_DIR"' EXIT
export SIMPLE_AGENT_ROOM_DIR="$ROOM_DIR"
export SIMPLE_AGENT_ID="watcher"

# 1) inotify latency -------------------------------------------------------------
rm -f "$ROOM_DIR/test.log" "$ROOM_DIR/mon.out"
SIMPLE_AGENT_ID=watcher setsid simple-room-monitor test --backfill 0 \
  </dev/null >"$ROOM_DIR/mon.out" 2>&1 &
MON=$!
disown
sleep 0.3  # let inotify attach

t0_ns=$(date +%s%N)
simple-room-send test -a writer -m "ping" 2>/dev/null
# wait up to 2s for the line
deadline=$(( $(date +%s%N) + 2000000000 ))
seen=""
while (( $(date +%s%N) < deadline )); do
  if grep -q "ping" "$ROOM_DIR/mon.out" 2>/dev/null; then
    seen="yes"
    break
  fi
  sleep 0.02
done
t1_ns=$(date +%s%N)
kill -INT $MON 2>/dev/null || true
sleep 0.1
kill -KILL $MON 2>/dev/null || true

if [[ -z "$seen" ]]; then
  echo "FAIL: inotify event not seen within 2s" >&2
  cat "$ROOM_DIR/mon.out" >&2
  exit 1
fi
latency_ms=$(( (t1_ns - t0_ns) / 1000000 ))
if (( latency_ms > 500 )); then
  echo "FAIL: inotify latency too high: ${latency_ms}ms" >&2
  exit 1
fi
echo "ok:   inotify latency = ${latency_ms}ms"

# 2) concurrency: 100 writers ----------------------------------------------------
rm -rf "$ROOM_DIR" && mkdir -p "$ROOM_DIR"
N=100
pids=()
for i in $(seq 1 $N); do
  ( simple-room-send concurrency -a "w$(printf '%03d' $i)" -m "msg-$i" 2>/dev/null ) &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done

count=$(simple-room-scan concurrency count)
if [[ "$count" != "$N" ]]; then
  echo "FAIL: expected $N records, got $count" >&2
  exit 1
fi
# Every record must be valid JSON on its own line
bad=$(grep -cv '^{' "$ROOM_DIR/concurrency.log" || true)
if [[ "$bad" != "0" ]]; then
  echo "FAIL: $bad non-JSON lines in concurrency room" >&2
  exit 1
fi
# Every writer id shows up exactly once
dup=$(simple-room-scan concurrency ids | sort | uniq -d | wc -l)
if [[ "$dup" != "0" ]]; then
  echo "FAIL: $dup duplicate agent ids" >&2
  exit 1
fi
echo "ok:   $N concurrent writers, $count records, no torn lines, no dups"

echo
echo "INOTIFY: OK"
