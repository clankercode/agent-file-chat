#!/usr/bin/env bash
# install.sh — install the agent-file-chat skills globally.
#
# What this does:
#   1. Symlink every skill in ./skills/ into ~/.claude/skills/ and
#      ~/.agents/skills/ (the two directories pi and Claude Code scan
#      for SKILL.md).
#   2. Symlink every binary in ./skills/<skill>/bin/ into ~/.local/bin/
#      (assumed on $PATH).
#
# Idempotent: re-running skips existing symlinks that already point to
# the right place; overwrites broken ones; leaves unrelated files alone.
# Pass --force to overwrite any pre-existing symlink at the target.
#
# Usage:
#   ./install.sh            # install
#   ./install.sh --force    # overwrite existing symlinks
#   ./install.sh --uninstall # reverse the install (see uninstall.sh)
#
# No sudo. No packages installed. No files modified outside this repo,
# ~/.claude/skills/, ~/.agents/skills/, and ~/.local/bin/.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"

CLAUDE_SKILLS="${HOME}/.claude/skills"
AGENTS_SKILLS="${HOME}/.agents/skills"
LOCAL_BIN="${HOME}/.local/bin"

FORCE=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    --uninstall|-u) UNINSTALL=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "install.sh: unknown arg: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$CLAUDE_SKILLS" "$AGENTS_SKILLS" "$LOCAL_BIN"

link_one() {
  # link_one <src> <dst>
  local src="$1" dst="$2"
  if [[ -e "$dst" || -L "$dst" ]]; then
    if [[ -L "$dst" ]] && [[ "$(readlink -f "$dst")" == "$(readlink -f "$src")" ]]; then
      echo "ok:   $dst (already correct)"
      return 0
    fi
    if (( FORCE )); then
      rm -f "$dst"
    else
      echo "skip: $dst exists and is not our symlink (use --force to overwrite)"
      return 0
    fi
  fi
  ln -s "$src" "$dst"
  echo "ok:   $dst -> $src"
}

unlink_one() {
  # unlink_one <dst> <expected_src>
  local dst="$1" expected="$2"
  if [[ -L "$dst" ]]; then
    local resolved
    resolved="$(readlink -f "$dst")"
    if [[ -n "$expected" ]] && [[ "$resolved" != "$(readlink -f "$expected")" ]]; then
      echo "skip: $dst is a symlink but not ours (→ $resolved)"
      return 0
    fi
    rm "$dst"
    echo "ok:   removed $dst"
  elif [[ -e "$dst" ]]; then
    echo "skip: $dst exists and is not a symlink"
  fi
}

if (( UNINSTALL )); then
  echo "Uninstalling agent-file-chat skills…"
  for skill in "$SKILLS_DIR"/*/; do
    [[ -d "$skill" ]] || continue
    skill="${skill%/}"
    name="$(basename "$skill")"
    unlink_one "$CLAUDE_SKILLS/$name" "$skill"
    unlink_one "$AGENTS_SKILLS/$name" "$skill"
    if [[ -d "$skill/bin" ]]; then
      for bin in "$skill/bin"/*; do
        [[ -e "$bin" ]] || continue
        bn="$(basename "$bin")"
        unlink_one "$LOCAL_BIN/$bn" "$bin"
      done
    fi
  done
  echo
  echo "Uninstall complete.  (Re-run './install.sh' to re-install.)"
  exit 0
fi

echo "Installing agent-file-chat skills…"
echo "  repo:        $REPO_ROOT"
echo "  claude:      $CLAUDE_SKILLS"
echo "  agents:      $AGENTS_SKILLS"
echo "  bin:         $LOCAL_BIN"
echo

skill_count=0
bin_count=0
for skill in "$SKILLS_DIR"/*/; do
  [[ -d "$skill" ]] || continue
  [[ -f "$skill/SKILL.md" ]] || continue
  # strip trailing slash from the glob
  skill="${skill%/}"
  name="$(basename "$skill")"
  link_one "$skill" "$CLAUDE_SKILLS/$name"
  link_one "$skill" "$AGENTS_SKILLS/$name"
  skill_count=$((skill_count + 1))
  if [[ -d "$skill/bin" ]]; then
    for bin in "$skill/bin"/*; do
      [[ -e "$bin" ]] || continue
      bn="$(basename "$bin")"
      link_one "$bin" "$LOCAL_BIN/$bn"
      bin_count=$((bin_count + 1))
    done
  fi
done

echo
echo "Install complete: $skill_count skill(s), $bin_count bin symlink(s)."
echo "Re-run with --uninstall to reverse, or --force to overwrite."
