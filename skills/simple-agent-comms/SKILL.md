---
name: simple-agent-comms
description: Two-way streaming comms with a long-running background subagent via a pair of append-only files + a Monitor, when you need its intermediate updates/questions (not just its final report) and inter-agent messaging (c2c / SendMessage-to-coordinator) is unreliable. Use when coordinating with a spawned Agent that runs for a while. The "simple" variant picks a single cache directory and stable script names so the agent never needs to know file paths.
license: MIT
---

# Simple agent ↔ coordinator file comms

## When to use

A background subagent (Agent tool) only returns its findings in its **final** message. If you need it to stream **intermediate** updates, ask you questions mid-task, or hand off design findings while still working — and the messaging channels are flaky (c2c broken; a running subagent often can't reliably address the coordinator back) — use two files plus a Monitor. Durable, order-preserving, no dependency on any message broker.

Channels:
- **`SendMessage` (you → agent)** works: messages are delivered at the agent's next tool round. Use it only to *bootstrap* (tell the agent the file paths).
- **Agent → you** is the unreliable direction. Solve it with a file the agent appends to and you `Monitor`.

For many-to-many chat (a "room" of agents), use the sibling skill `simple-agent-room` instead.

## The pattern

```
        you (coordinator)                  spawned subagent
        ────────────────                   ────────────────
            │                                   │
   bootstrap │ SendMessage: "tail A, append B"   │
            │ ─────────────────────────────────► │
            │                                   │
            │ ◄──── append [agent] … to A ────── │
   Monitor  │ (event: new line in A)             │
   watch A  │                                   │
            │                                   │
   append   │ ── append [coord] … to B ──────► │
            │                          agent tails B
```

1. **Make two append-only files** under the default cache dir (one pair per agent):
   ```sh
   mkdir -p ~/.cache/agent-comms
   A=~/.cache/agent-comms/<agent>-to-coord.md   # agent -> you  (you Monitor this)
   B=~/.cache/agent-comms/coord-to-<agent>.md   # you -> agent  (agent tails this)
   : > "$A"; printf '# coordinator -> %s (read/tail this)\n' "<agent>" > "$B"
   ```

2. **Monitor the agent→you file** so each new line pings you (uses `watch-file.sh`, shipped in this skill folder; also at `~/.local/bin/watch-file.sh`):
   ```
   Monitor({ command: "watch-file.sh ~/.cache/agent-comms/<agent>-to-coord.md",
             persistent: true, description: "<agent> replies" })
   ```
   `watch-file.sh` does `tail -n 0 -F` (only new lines, follows truncation), line-buffered, skipping blank + `#` comment/header lines. Optional 2nd arg = an extra grep filter.

3. **Bootstrap the agent** (one `SendMessage`, or bake it into the spawn prompt): tell it to **read** `coord-to-<agent>.md` (`tail` it) and **append** its messages to `<agent>-to-coord.md`. Tell it which broker NOT to use (e.g. "c2c is broken").

4. **Talk:**
   - You → agent: `cat >> "$B" <<'EOF' … EOF` (append `[coord] …` lines). The agent reads `B` when it tails it.
   - Agent → you: it appends `[<agent>] …` lines to `A`; your Monitor surfaces each new line as an event (not a user reply — an event).

5. **Tear down:** `TaskStop` the Monitor when the agent finishes; the files stay as a transcript.

## Conventions

- **Prefix every line** with `[coord]` or `[<agent>]` so the transcript is attributable.
- **Append, never rewrite** — both files are logs.
- The agent's spawn prompt should say "for intermediate updates/questions, append to `<A>`; read `<B>` for my replies" so it doesn't try a broken broker first.
- One file-pair per agent; reuse `~/.cache/agent-comms/`.
- Events from the Monitor are background events, not the user — don't treat a reply landing mid-turn as the user answering you.

## Files

- `watch-file.sh` — the Monitor command. `watch-file.sh <file> [extra-grep]`.
