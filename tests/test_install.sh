#!/usr/bin/env bash
# test_install.sh — smoke check the global install.
#
# Verifies:
#   - the three CLI tools are on PATH
#   - the skill symlinks exist in ~/.claude/skills/ and ~/.agents/skills/
#   - each tool's --help (or no-arg invocation) succeeds
#   - both SKILL.md files have valid YAML frontmatter
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok:   $*"; }

# 1) CLI tools on PATH
for tool in simple-room-send simple-room-monitor simple-room-scan; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    fail "$tool not on PATH (expected symlink in ~/.local/bin/)"
  fi
  ok "$tool on PATH at $(command -v "$tool")"
done

# 2) Skill symlinks present and pointing into this repo
for dir in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
  for skill in simple-agent-comms simple-agent-room; do
    target="$dir/$skill"
    if [[ ! -L "$target" ]]; then
      fail "$target is not a symlink"
    fi
    resolved="$(readlink -f "$target")"
    case "$resolved" in
      "$REPO_ROOT"/skills/*) ok "symlink $target → $resolved" ;;
      *) fail "symlink $target resolves to $resolved (not under $REPO_ROOT/skills/)" ;;
    esac
  done
done

# 3) Each CLI runs (--help or no-arg exits 0)
for tool in simple-room-send simple-room-monitor simple-room-scan; do
  case "$tool" in
    simple-room-send) "$tool" --help >/dev/null 2>&1 || fail "$tool --help failed" ;;
    simple-room-monitor) "$tool" --help >/dev/null 2>&1 || fail "$tool --help failed" ;;
    simple-room-scan) "$tool" --help >/dev/null 2>&1 || fail "$tool --help failed" ;;
  esac
  ok "$tool --help"
done

# 4) Each SKILL.md has a parseable YAML frontmatter (name, description present)
for skill in simple-agent-comms simple-agent-room; do
  md="$REPO_ROOT/skills/$skill/SKILL.md"
  if [[ ! -f "$md" ]]; then fail "$md missing"; fi
  python3 - "$md" <<'PY' || fail "$md: frontmatter parse failed"
import re, sys
p = sys.argv[1]
text = open(p).read()
m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
if not m:
    sys.exit(1)
fm = m.group(1)
for key in ("name:", "description:"):
    if key not in fm:
        sys.exit(2)
PY
  ok "frontmatter valid in $md"
done

echo
echo "INSTALL SMOKE: OK"
