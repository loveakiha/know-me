---
name: know-me
description: "Cross-agent personal memory: extract, review, confirm."
version: 1.1.0
author: loveakiha, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, know-me, cross-agent]
    related_skills: [session-topic-guard]
---

# Know-Me

Build a shared, human-confirmed memory of the user that any agent can read.
Pipeline: **Observation → Candidate Fact → Human Review → Confirmed Fact**.

**Core principle:** extract aggressively, confirm conservatively — **no agent may
unilaterally define who the user is**. Final interpretation belongs to the user.

## When to Use

- First install into a profile — read `references/install.md`.
- Daily loop: `import hermes` → extract → `add-facts` → review → apply → export → sync.
- User says "remember this", "what do you know about me", or asks to review pending facts.
- Self-introduction for a fresh profile (`pm init`).

Don't use for: one-off note-taking (use `obsidian`) or raw chat logging — this
stores distilled, confirmed facts, not a message archive.

## Prerequisites

None. `pm.py` imports only the stdlib (`argparse hashlib json os re sqlite3 subprocess datetime`) — no `pip install`, nothing to compile. Optional: `git`, used only by `pm.py sync`.

## Where things live

- `pm.py` — single-file engine. Data in `data/` beside it (gitignored; **never commit it — the code is public, the data is private**).
- `schema/README.md` — observation/fact/review field definitions + confidence rubric.
- `prompts/extract.md` · `prompts/list_memory.md` — extraction prompt; "list your memory" template for web AIs.

## Install

Read `references/install.md` for the full bootstrap (clone-free fetch, mirror
order, per-profile copy, content-freshness traps). Once the engine sits beside
this file it is one command — run it, don't explore (the whole install is a
~72 KB copy, <2s):

```bash
python <SKILL_DIR>/scripts/install.py --profile <name>   # skill + engine into a profile (recommended)
python <SKILL_DIR>/scripts/install.py                    # engine only, default target
```

## Procedure — Bootstrap (first run: backfill + full confirm)

```bash
python pm.py import hermes --since 2020-01-01   # backfill history -> observations
# agent: read observations, extract candidate facts per prompts/extract.md -> facts.json
python pm.py add-facts facts.json
python pm.py review --all                        # pending list + .html widget
# deliver reviews/YYYY-MM-DD.html with  ::preview{file=".../YYYY-MM-DD.html"}
python pm.py apply "R001 对 / R002 错,reason / R003 改:new text"   # 对/错/改 = confirm/reject/change
python pm.py export                              # -> data/user_model.md
```

Done when every historical candidate is confirmed or rejected and `user_model.md` reflects it.

## Procedure — Daily (incremental)

`import hermes` (today only) → extract → `add-facts` → review (incremental) →
deliver the widget → `apply` → `export` → `sync`. Incremental `review` surfaces
only new candidates plus same-topic conflicts; `--all` is for the bootstrap above.

## Init (self-introduction)

`pm init` generates `data/reviews/init.html`: **one free-text self-intro box + three
optional fills** (name / work / family_role). Deliver with `::preview`. Submit sends
`hermes.send("PMINIT <json>")` where json =
`{"intro":"…","answers":[{"facet":"identity","key":"name","v":"…"}]}`. The agent
splits the prose into candidate facts (`source_agent=self`, `evidence_type=asserted`)
and maps each answer to one asserted fact on its facet → `add-facts` → `review` → user
confirms.

**Never surface the taxonomy as UI.** The facet/sub-tag list is the *extractor's*
vocabulary; asking the user to tick it yields zero content (ticking "姓名/称呼" [name]
only says "this bucket applies to me", which is near-always true) and inverts the core
principle — the agent classifies, the user confirms. Init's input must be **content**,
not classification.

## Config (granularity + session summary)

`pm config get` / `pm config set <key> <value>`.

- `granularity`: `exhaustive` (default, extract everything) | `concise` (≤5 key facts/day, merge same-facet).
- `session_summary`: `False` (default) | `True` — at conversation end (topic shift detected by session-topic-guard, or problem solved), the agent summarizes that session into candidates and offers judgment; then add-facts → review → apply.

## Harvest from web AIs (ChatGPT / DeepSeek)

They have no local write access — ask them to LIST their memory with
`prompts/list_memory.md`, paste the output into `facts.json`, `pm add-facts`
(`source_agent=chatgpt/deepseek`). Push back `user_model.md` by pasting. **Harvest
BEFORE pushback** or they echo back what you fed.

**Match before adding** (web-AI memory is stale and can conflict with confirmed facts
— never let it silently override): duplicates → skip; same entity but contradictory
predicate → set `conflict_with` (the agent does semantic matching, e.g. "开发
photo-agent" [developing photo-agent] conflicts with "已关停 photo-agent" [photo-agent
shut down]; `add-facts` also auto-flags same topic_key/object + different predicate);
new → normal candidate. Conflicting facts surface in review with a ⚠️冲突 (conflict)
badge for focused confirmation.

## Review semantics

- Plain entries: ✓ = `对` (confirm) · ❓ = `不确定` (skip — no write) → the user
  explains in the text box → the agent analyzes the explanation ("不记得了" [don't
  remember] → reject; "没关心X只是朋友问" [didn't care about X, a friend asked] →
  reject + new fact; "应该是Y" [should be Y] → `改`; ambiguous → ask).
- **Conflict entries (`conflict_with` non-empty) use A/B/C/D buttons, not ✓/❓** — a
  conflict is a decision, not a judgment: A = keep the confirmed fact (reject new) ·
  B = new is right (adopt; old fact marked 待复核 [for re-review]) · C = both (new as
  supplement/history) · D = other (explain; agent analyzes).
- Select-then-submit (never immediate write). Minimal cards, symbol-only English chrome.

## Pitfalls

- `data/` stays private (gitignored). Only code/docs are public.
- Web AIs are text-in/text-out only — never design around them writing via MCP/GitHub.
- R-id must stay stable within a day (reuse assigned ids; renumbering after confirm breaks rapid multi-click submissions).
- state.db `role='user'` messages contain system injections (`[Cronjob` / `[System:` / `[ASYNC` / `[IMPORTANT:` / `[CONTEXT COMPACTION`) and duplicate rows — `import` filters by prefix + dedups.
- confidence is rule-computed (asserted 3 > observed 2 > inferred 1, +evidence/cross-day/cross-agent), never model-emitted decimals.
- `apply` is pure string parsing (no LLM) — conversation text cannot trigger writes.
- **Every profile has its own `state.db`** (`profiles/<name>/state.db`). `import hermes` resolves it by `HERMES_HOME` (then `$HERMES_STATE_DB`, then `--db`, finally `%LOCALAPPDATA%\hermes\state.db`) and prints the actual path used — **never hardcode the default profile's db**, or you build someone else's memory for this profile.
  - In MSYS bash, `HERMES_HOME` must be a native path (`C:/...`): `/c/...` is not recognized by native Python and silently falls back to the default profile. `import` now emits a ⚠ warning on this.

## Verification

- [ ] `python pm.py --help` exits 0 (proves the zero-dependency engine runs).
- [ ] `import` printed the actual `state.db` path, and it is the current profile's.
- [ ] Review widget delivered and applied — `pm.py review` shows no unseen pending items.
- [ ] `data/user_model.md` regenerated by `export` after every `apply`.
