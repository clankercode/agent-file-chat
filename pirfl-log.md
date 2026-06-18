# PIRFL log

## 2026-06-18 — initial intake

### Task model

- **Goal**: Create two agent skills (`simple-agent-comms` rename, `simple-agent-room` new), set up a public `clankercode/agent-file-chat` repo, and complete e2e testing of every feature.
- **Deliverable**: Skills (SKILL.md + Python scripts), tests, GitHub repo, e2e transcript.
- **Acceptance**: Skills install globally, all features have an e2e test, repo is public with description.
- **Constraints**:
  - Single file per room.
  - Monitor-tool compatible.
  - Self-msg filtering on monitor.
  - Python scripts (pyinotify for fs events — no polling).
  - Agent should not need to know file paths.
  - ASCII flowcharts in skill docs.
  - PIRFL workflow.
  - Regular git commits.
  - e2e tests with tmux + `pi` + a model (the exact model TBD; record what works).
  - Public repo under `clankercode` org.

### Assumptions

- `pyinotify` is the right Python inotify library (already installed; `inotify_simple` is not — and the user said "python scripts" so we use Python).
- Two-`pi`-agent-in-tmux is a representative e2e test (verifies the skill works as a user would actually use it).
- I can use my own `Agent` tool to drive sub-tasks (writing/verifying tests in parallel).
- `~/.local/bin/` is on PATH and is the right install location for the global scripts.

### Blockers

- None at intake. We have gh auth, tmux, python, pyinotify, inotifywait, the pi CLI, and access to the clankercode org.

### Validators

- Unit tests (pytest).
- Bash scripts asserting the on-disk format and inotify timing.
- A two-pane tmux + pi e2e scenario.
- A smoke check of the install (which, symlinks, skill-loads).

## Plan slices (will be filled in as we go)

1. **Slice A — scaffold + simple-agent-comms**: git init, copy & rename `subagent-file-comms` to `simple-agent-comms`, install symlinks, first commit.
2. **Slice B — simple-agent-room design + scripts**: design the message format + file location; build the lib + 3 entry points; install on PATH; commit.
3. **Slice C — SKILL.md + ASCII flowcharts**: write `simple-agent-room/SKILL.md` with the flowcharts and the "agent doesn't need to know paths" usage recipe; commit.
4. **Slice D — unit + integration tests**: pytest covering the lib + each entry-point; bash test for inotify timing; commit.
5. **Slice E — e2e with tmux + pi**: write and run the two-agent scenario; capture transcript; commit.
6. **Slice F — README, LICENSE, gh repo creation**: create public repo, set description, push; commit any final docs.
7. **Slice G — PIRFL review pass**: review every script, every test, every doc against acceptance criteria; fix issues; commit.

## Reviewer prompts (to run after each slice)

- **Correctness critic**: read the script/test/docs; identify any logical, file-IO, or race-condition bug.
- **Goal-fit critic**: re-read the user request; flag anything missing or over-built.
- **Edge-case critic**: enumerate failure modes (concurrent writes, torn lines, agent-id collisions, very long messages, unicode, newlines, malformed records, file rotation).
- **Integration critic**: do the scripts in the new skill, the old skill, the symlinks, the install, and the tests all work together?
