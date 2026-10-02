---
name: know-me
description: "Install or run know-me (pm.py) personal memory tool."
version: 1.0.0
author: know-me contributors
license: MIT
metadata:
  hermes:
    tags: [memory, know-me, cross-agent]
---

# know me — cross-agent personal memory

Build a shared memory of the user that any agent can read, gated by human confirmation: **Observation → Candidate Fact → Human Review → Confirmed Fact**.

Core principle: extract aggressively, confirm conservatively — **no agent may unilaterally define who the user is**. Final interpretation belongs to the user.

## Where things live
- `pm.py` — single-file engine, stdlib only (no deps). Data in `data/` next to it (gitignored; **never commit it — the code is open, the data is private**).
- `schema/README.md` — observation/fact/review field definitions + confidence rubric.
- `prompts/extract.md` · `prompts/list_memory.md` — extraction prompt; "list your memory" template for web AIs.

## Install
1. Clone the repo (or copy `pm.py` + `schema/` + `prompts/`).
2. `python pm.py --help` — zero dependencies.
3. `data/` is auto-created on first run and gitignored.

## First run (bootstrap — backfill + full confirm)
```bash
python pm.py import hermes --since 2020-01-01   # backfill history -> observations
# agent: read observations, extract candidate facts per prompts/extract.md -> facts.json
python pm.py add-facts facts.json
python pm.py review --all                        # pending list + .html widget
# deliver reviews/YYYY-MM-DD.html with  ::preview{file=".../YYYY-MM-DD.html"}
python pm.py apply "R001 对 / R002 不确定:... / R003 改:..."
python pm.py export                              # -> data/user_model.md
```

## Daily
`import hermes` (today only) → extract → add-facts → review (incremental) → deliver widget → apply → export → sync.

## Harvest from web AIs (ChatGPT / DeepSeek)
They have no local write access — ask them to LIST their memory with `prompts/list_memory.md`, paste the output into facts.json, `pm add-facts` (source_agent=chatgpt/deepseek). Push back `user_model.md` by pasting. **Harvest BEFORE pushback** or they echo back what you fed.

## Review semantics
- ✓ = confirm (saved as fact on submit). ❓ = not sure → user explains in the text box → agent analyzes the text: "不记得了"→delete/reject; "没关心X，只是朋友问"→reject + extract new fact; "应该是Y"→改; ambiguous→dialogue.
- Select-then-submit (never immediate write — a misclick would corrupt the store). Minimal cards, symbol-only English chrome.

## Pitfalls
- `data/` stays private (gitignored). Only code/docs are public.
- Web AIs are text-in/text-out only — never design around them writing via MCP/GitHub.
- R-id must stay stable within a day (reuse assigned ids; renumbering after confirm breaks rapid multi-click submissions).
- state.db `role='user'` messages contain system injections (`[Cronjob` / `[System:` / `[ASYNC` / `[IMPORTANT:` / `[CONTEXT COMPACTION`) and duplicate rows — `import` filters by prefix + dedups.
- confidence is rule-computed (asserted 3 > observed 2 > inferred 1, +evidence/cross-day/cross-agent), never model-emitted decimals.
- `apply` is pure string parsing (no LLM) — conversation text cannot trigger writes.
