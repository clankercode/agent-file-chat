#!/usr/bin/env bash
# test_e2e_pi.sh — end-to-end test of the simple-agent-room skill with two
# real `pi` agents running in a tmux session.
#
# Topology:
#
#   tmux session "sar-e2e"
#   ┌────────────────────────┬────────────────────────┐
#   │ pane 0: agent-alice    │ pane 1: agent-bob      │
#   │ (pi --print, bash only)│ (pi --print, bash only)│
#   └────────────────────────┴────────────────────────┘
#                          │
#                          ▼
#              $SIMPLE_AGENT_ROOM_DIR/e2e.log
#
# Each agent is given the SKILL as an appended system prompt and a
# scripted task that uses simple-room-send + simple-room-scan.  The
# test asserts the room file ends up with messages from BOTH agents.
#
# Requirements:
#   - `pi` on PATH
#   - `tmux`
#   - the skill installed (symlinks or repo checkout)
#   - a working model (default: minimax/MiniMax-M2.7-highspeed,
#     override with SAR_E2E_MODEL / SAR_E2E_PROVIDER)
#
# The test is skipped (exit 0 with a message) if the model can't be
# reached, so this test is friendly to offline / air-gapped environments.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="$REPO_ROOT/scripts"
SKILL_FILE="$REPO_ROOT/skills/simple-agent-room/SKILL.md"

ROOM_DIR="${SAR_E2E_ROOM_DIR:-$(mktemp -d -t sar-e2e-rooms.XXXXXX)}"
export SIMPLE_AGENT_ROOM_DIR="$ROOM_DIR"
ROOM="e2e"

MODEL_PROVIDER="${SAR_E2E_PROVIDER:-minimax}"
MODEL_NAME="${SAR_E2E_MODEL:-MiniMax-M2.7-highspeed}"

SOCKET="sar-e2e-$$"
SESSION="$SOCKET"
TRANSCRIPT_DIR="$REPO_ROOT/tests/transcripts"
mkdir -p "$TRANSCRIPT_DIR"
TRANSCRIPT="$TRANSCRIPT_DIR/e2e-$(date +%Y%m%d-%H%M%S).log"

PASS_COUNT=0
FAIL_COUNT=0
log()  { echo "  $*"; }
pass() { echo "PASS: $*"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo "FAIL: $*" >&2; FAIL_COUNT=$((FAIL_COUNT+1)); }

# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------
echo "E2E: simple-agent-room with two pi agents in tmux"
echo "  room:    $ROOM_DIR/$ROOM.log"
echo "  model:   $MODEL_PROVIDER/$MODEL_NAME"
echo "  socket:  $SOCKET"
echo

if ! command -v pi >/dev/null 2>&1; then
  fail "pi not on PATH"
  exit 1
fi
if ! command -v tmux >/dev/null 2>&1; then
  fail "tmux not on PATH"
  exit 1
fi
if [[ ! -f "$SKILL_FILE" ]]; then
  fail "SKILL.md not found at $SKILL_FILE"
  exit 1
fi

# Probe the model with a tiny call; skip the test (exit 0) if it fails.
if ! timeout 60 pi --provider "$MODEL_PROVIDER" --model "$MODEL_NAME" \
      --no-session -t off --print --no-builtin-tools --tools bash \
      'Reply with exactly: PONG' 2>/dev/null | grep -q PONG; then
  echo "SKIP: model $MODEL_PROVIDER/$MODEL_NAME unreachable or non-responsive"
  echo "  (set SAR_E2E_MODEL and SAR_E2E_PROVIDER to override)"
  exit 0
fi
pass "model probe"

# ---------------------------------------------------------------------------
# the two agent prompts
# ---------------------------------------------------------------------------
ALICE_PROMPT='You are agent-alice in a tmux pane. A second agent, agent-bob, is running in another pane and will also use the simple-agent-room skill.

The room is named exactly: e2e
The room file lives in $SIMPLE_AGENT_ROOM_DIR (a tmp dir for this test).
The CLI tools are on your PATH as: simple-room-send, simple-room-monitor, simple-room-scan.

Do this in one turn:
  1. Run: simple-room-send e2e -a alice -m "hello from alice"
  2. Run: simple-room-scan e2e tail -n 10
  3. End your reply with a single line: STATUS: ok

Do NOT spawn background monitors. Do NOT use any other tools except bash. Do NOT edit files. Just run the two commands above.'

BOB_PROMPT='You are agent-bob in a tmux pane. A second agent, agent-alice, is running in another pane and will also use the simple-agent-room skill.

The room is named exactly: e2e
The CLI tools are on your PATH as: simple-room-send, simple-room-monitor, simple-room-scan.

Do this in one turn:
  1. Run: sleep 8
  2. Run: simple-room-send e2e -a bob -m "hello from bob"
  3. Run: simple-room-scan e2e tail -n 10
  4. End your reply with a single line: STATUS: ok

Do NOT spawn background monitors. Do NOT use any other tools except bash. Do NOT edit files.'

# ---------------------------------------------------------------------------
# start tmux, find pane ids (the first window may be index 0 or 1)
# ---------------------------------------------------------------------------
echo "  starting tmux session…"
tmux -L "$SOCKET" new-session -d -x 200 -y 50 -s "$SESSION" || {
  fail "could not start tmux session"; exit 1; }
sleep 0.3
# NB: do NOT include ":0" in the target — on some tmux builds it
# misparses as "window 0 in the default session" rather than "window 0
# in $SESSION", and the split silently fails.
tmux -L "$SOCKET" split-window -h -t "$SESSION" || {
  fail "could not split window"; tmux -L "$SOCKET" kill-session 2>/dev/null; exit 1; }
pass "tmux session up"

PANE_IDS=( $(tmux -L "$SOCKET" list-panes -t "$SESSION" -F '#{pane_id}') )
if (( ${#PANE_IDS[@]} < 2 )); then
  fail "expected 2 panes, got ${#PANE_IDS[@]}"
  tmux -L "$SOCKET" kill-session 2>/dev/null
  exit 1
fi
PANE0="${PANE_IDS[0]}"
PANE1="${PANE_IDS[1]}"
log "  panes: $PANE0  $PANE1"

# ---------------------------------------------------------------------------
# write each agent's command to a wrapper script
# ---------------------------------------------------------------------------
ALICE_LOG="$TRANSCRIPT_DIR/e2e-alice-$$.log"
BOB_LOG="$TRANSCRIPT_DIR/e2e-bob-$$.log"
ALICE_SCRIPT="$TRANSCRIPT_DIR/e2e-alice-$$.sh"
BOB_SCRIPT="$TRANSCRIPT_DIR/e2e-bob-$$.sh"
: > "$ALICE_LOG"; : > "$BOB_LOG"

# We write the prompt to a file too, so the pi command line stays short.
ALICE_PROMPT_FILE="$TRANSCRIPT_DIR/e2e-alice-prompt-$$.txt"
BOB_PROMPT_FILE="$TRANSCRIPT_DIR/e2e-bob-prompt-$$.txt"
printf '%s' "$ALICE_PROMPT" > "$ALICE_PROMPT_FILE"
printf '%s' "$BOB_PROMPT" > "$BOB_PROMPT_FILE"

cat > "$ALICE_SCRIPT" <<EOF
#!/usr/bin/env bash
set -u
export SIMPLE_AGENT_ID=alice
export SIMPLE_AGENT_ROOM_DIR=$ROOM_DIR
timeout 180 pi \\
  --provider "$MODEL_PROVIDER" \\
  --model "$MODEL_NAME" \\
  --no-session \\
  -t off \\
  --print \\
  --no-builtin-tools \\
  --tools bash \\
  --append-system-prompt "@$SKILL_FILE" \\
  "\$(cat $ALICE_PROMPT_FILE)" \\
  > "$ALICE_LOG" 2>&1
echo EXIT_CODE=\$? >> "$ALICE_LOG"
EOF
chmod +x "$ALICE_SCRIPT"

cat > "$BOB_SCRIPT" <<EOF
#!/usr/bin/env bash
set -u
export SIMPLE_AGENT_ID=bob
export SIMPLE_AGENT_ROOM_DIR=$ROOM_DIR
timeout 180 pi \\
  --provider "$MODEL_PROVIDER" \\
  --model "$MODEL_NAME" \\
  --no-session \\
  -t off \\
  --print \\
  --no-builtin-tools \\
  --tools bash \\
  --append-system-prompt "@$SKILL_FILE" \\
  "\$(cat $BOB_PROMPT_FILE)" \\
  > "$BOB_LOG" 2>&1
echo EXIT_CODE=\$? >> "$BOB_LOG"
EOF
chmod +x "$BOB_SCRIPT"

log "  launching alice in pane 0…"
tmux -L "$SOCKET" send-keys -t "$PANE0" "$ALICE_SCRIPT; echo __SCRIPT_DONE__" Enter

log "  launching bob in pane 1…"
tmux -L "$SOCKET" send-keys -t "$PANE1" "$BOB_SCRIPT; echo __SCRIPT_DONE__" Enter

# ---------------------------------------------------------------------------
# wait for both agents to finish
# ---------------------------------------------------------------------------
log "  waiting for agents (up to 3 min)…"
deadline=$(( $(date +%s) + 240 ))
while (( $(date +%s) < deadline )); do
  alice_done=0; bob_done=0
  if grep -q "^EXIT_CODE=" "$ALICE_LOG" 2>/dev/null; then alice_done=1; fi
  if grep -q "^EXIT_CODE=" "$BOB_LOG"   2>/dev/null; then bob_done=1;   fi
  if (( alice_done && bob_done )); then break; fi
  sleep 2
done

# Kill tmux (we don't need the panes anymore).
tmux -L "$SOCKET" kill-session 2>/dev/null

if [[ ! -f "$ALICE_LOG" ]] || ! grep -q "^EXIT_CODE=" "$ALICE_LOG"; then
  fail "alice did not finish in time"
  echo "--- alice log (head 50) ---" >> "$TRANSCRIPT"
  head -50 "$ALICE_LOG" >> "$TRANSCRIPT" 2>/dev/null
fi
if [[ ! -f "$BOB_LOG" ]] || ! grep -q "^EXIT_CODE=" "$BOB_LOG"; then
  fail "bob did not finish in time"
  echo "--- bob log (head 50) ---" >> "$TRANSCRIPT"
  head -50 "$BOB_LOG" >> "$TRANSCRIPT" 2>/dev/null
fi

# ---------------------------------------------------------------------------
# assertions
# ---------------------------------------------------------------------------
echo
echo "  -- transcript (room) --"
simple-room-scan e2e tail -n 20 --json 2>/dev/null | head -20 | tee -a "$TRANSCRIPT"
echo
echo "  -- assertions --"

# 1) Both agents should have exited 0
alice_exit=$(grep "^EXIT_CODE=" "$ALICE_LOG" 2>/dev/null | tail -1 | cut -d= -f2)
bob_exit=$(  grep "^EXIT_CODE=" "$BOB_LOG"   2>/dev/null | tail -1 | cut -d= -f2)
if [[ "$alice_exit" == "0" ]]; then pass "alice exit=0"; else fail "alice exit=$alice_exit"; fi
if [[ "$bob_exit"   == "0" ]]; then pass "bob exit=0";   else fail "bob exit=$bob_exit";   fi

# 2) Room must contain a message from alice
if [[ "$(simple-room-scan e2e grep "hello from alice" 2>/dev/null | wc -l)" -ge 1 ]]; then
  pass "alice posted to room"
else
  fail "alice's message not in room"
fi

# 3) Room must contain a message from bob
if [[ "$(simple-room-scan e2e grep "hello from bob" 2>/dev/null | wc -l)" -ge 1 ]]; then
  pass "bob posted to room"
else
  fail "bob's message not in room"
fi

# 4) At least 2 records
count=$(simple-room-scan e2e count 2>/dev/null)
if [[ "$count" -ge 2 ]]; then
  pass "room has $count records (>=2)"
else
  fail "room has $count records (expected >=2)"
fi

# 5) Both agents appeared in the room
ids=$(simple-room-scan e2e ids 2>/dev/null | sort -u | tr '\n' ',' | sed 's/,$//')
for who in alice bob; do
  if [[ ",$ids," == *",$who,"* ]]; then pass "room lists agent '$who'"; else fail "room missing agent '$who' (have: $ids)"; fi
done

# 6) Both agents' transcripts include the STATUS line (proxy for "the
#    agent read my prompt and completed the task").
for who_log in "$ALICE_LOG:alice" "$BOB_LOG:bob"; do
  log_file="${who_log%:*}"
  who="${who_log##*:}"
  if grep -q "STATUS: ok" "$log_file"; then
    pass "$who ended with STATUS: ok"
  else
    fail "$who did NOT end with STATUS: ok (transcript: $(head -3 "$log_file" | tr '\n' '|'))"
  fi
done

# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
echo
echo "  full alice transcript: $ALICE_LOG"
echo "  full bob transcript:   $BOB_LOG"
echo "  room transcript:       $TRANSCRIPT"
echo
if (( FAIL_COUNT == 0 )); then
  echo "E2E: OK ($PASS_COUNT checks passed)"
  exit 0
else
  echo "E2E: FAIL ($FAIL_COUNT failures, $PASS_COUNT passed)" >&2
  exit 1
fi
