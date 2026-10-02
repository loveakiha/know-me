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
**A. The engine is already beside this file** (`scripts/engine/` — true when the skill dir was carried over by `hermes profile create --clone` or `install.py`). No network, no dependencies, no repo clone required:

```bash
python <SKILL_DIR>/scripts/install.py --profile <name>   # 一条命令：装技能 + 装引擎（推荐）
python <SKILL_DIR>/scripts/install.py                    # 只装引擎到默认位置
```

**Only this SKILL.md?** (another machine / another user / a pasted or desktop copy) — **fetch the engine from the public repo; never search the local filesystem** (a D:/C: sweep is slow and turns up stale copies). The engine is stdlib-only and reads nothing beside itself, so this materializes the *whole skill* in one shot, after which every path below works offline:

```bash
SK="${HERMES_HOME:-$HOME/.hermes}/skills/know-me"   # Windows git-bash: export HERMES_HOME="$LOCALAPPDATA/hermes" (native C:/… path)
mkdir -p "$SK/prompts" "$SK/schema"
for u in https://raw.githubusercontent.com/loveakiha/know-me/main \
         https://cdn.jsdelivr.net/gh/loveakiha/know-me@main ; do
  ok=1
  for f in SKILL.md pm.py README.md schema/README.md prompts/extract.md prompts/list_memory.md; do
    curl -fsSL --max-time 30 -o "$SK/$f" "$u/$f" || { ok=0; break; }
  done
  [ "$ok" = 1 ] && break
done
python "$SK/pm.py" --help        # verify: zero deps, no pip install
```

~50 KB, <2s. Mirror order matters: `raw.githubusercontent.com` is throttled/blocked on some networks (esp. CN); jsDelivr (`cdn.jsdelivr.net/gh/<user>/<repo>@main/<path>`) is the fallback. **Never bootstrap with `git clone`** — it inherits whatever broken global proxy config the machine has (measured on this host: clone dies on a dead socks5 while plain curl succeeds). After this, `pm.py` runs in place; to give it to another *profile*, copy `$SK` to `profiles/<name>/skills/know-me/`.

**Dependencies: none.** `pm.py` imports only the stdlib (`argparse hashlib json os re sqlite3 subprocess datetime`) — no `pip install`, nothing to compile. Verified end-to-end (`init` + `export` + `install.py`) on CPython **3.8 / 3.9 / 3.13 / 3.14**; the only optional external program is `git`, used solely by `pm.py sync`.

**Content freshness:** right after a push, `raw.githubusercontent.com` can still serve the previous bytes for a few minutes and jsDelivr `@main` for up to 12h. To confirm a push landed, use `git ls-remote origin` or the codeload tarball — not a CDN fetch.


Fastest path for a new profile — this skill is NOT a bundled skill, so `hermes profile create <name>` alone seeds **bundled skills only** and will not have it:
```bash
hermes profile create <name> --clone      # 把当前 profile 的 skills 一起带过去（含 scripts/engine/，已验证）
python <SKILL_DIR>/scripts/install.py --profile <name>   # 再补引擎，0.2s
```
Run it, don't explore: the whole install is a 72 KB copy and never takes more than a second. No `--clone` → the profile simply has no know-me skill; that is the gap to close, not something to search for.

- `<SKILL_DIR>` = wherever this SKILL.md sits (`$HERMES_HOME/skills/know-me`). On this dev host that is `C:/Users/Administrator/AppData/Local/hermes/skills/know-me` — a local shortcut for *this* machine only, never the install instructions for anyone else.
- source order: `--from <repo>` (strict, errors if no `pm.py`) → repo layout (`<repo>/scripts/install.py`) → bundled `scripts/engine/`
- default target: `%LOCALAPPDATA%\hermes\know-me` (override with `--target` or `$HERMES_KNOWME_DIR`); `--print-target` prints it
- copies **code/docs only** — an existing `data/` is never written or deleted
- ends by verifying `python pm.py --help` (zero dependencies); `data/` is auto-created on first run
- bundled copy drifts: after editing `pm.py`/`schema/`/`prompts/` in the repo, re-copy them into `<SKILL_DIR>/scripts/engine/`

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

## Init (self-introduction)
`pm init` → generates `data/reviews/init.html`: **one free-text self-intro box + three optional fills** (name / work / family_role). Deliver with `::preview`. Submit sends `hermes.send("PMINIT <json>")` where json = `{"intro":"…","answers":[{"facet":"identity","key":"name","v":"…"}]}`. Agent splits the prose into candidate facts (`source_agent=self`, `evidence_type=asserted`) and maps each answer to one asserted fact on its facet → `add-facts` → `review` → user confirms.

**Never surface the taxonomy as UI.** The facet/sub-tag list is the *extractor's* vocabulary; asking the user to tick it yields zero content (ticking "姓名/称呼" says only "this bucket applies to me", which is near-always true) and inverts the core principle — the agent classifies, the user confirms. Init's input must be **content**, not classification.

## Config (granularity + session summary)
`pm config get` / `pm config set <key> <value>`.
- `granularity`: `exhaustive` (default, extract everything) | `concise` (≤5 key facts/day, merge same-facet).
- `session_summary`: `False` (default) | `True` — at conversation end (topic shift detected by session-topic-guard, or problem solved), agent summarizes that session into candidates and offers judgment; then add-facts → review → apply.

## Harvest from web AIs (ChatGPT / DeepSeek)
They have no local write access — ask them to LIST their memory with `prompts/list_memory.md`, paste the output into facts.json, `pm add-facts` (source_agent=chatgpt/deepseek). Push back `user_model.md` by pasting. **Harvest BEFORE pushback** or they echo back what you fed.

**Match before adding** (web-AI memory is stale and can conflict with confirmed facts — never let it silently override): duplicates → skip; same entity but contradictory predicate → set `conflict_with` (the agent does semantic matching, e.g. "开发 photo-agent" conflicts with "已关停 photo-agent"; `add-facts` also auto-flags same topic_key/object + different predicate); new → normal candidate. Conflicting facts surface in review with a ⚠️冲突 badge for focused confirmation.

## Review semantics
- Plain entries: ✓ = confirm · ❓ = not sure → user explains in text box → agent analyzes ("不记得了"→reject; "没关心X只是朋友问"→reject+new fact; "应该是Y"→改; ambiguous→dialogue).
- **Conflict entries (conflict_with non-empty) use A/B/C/D option buttons, not ✓/❓** — a conflict is a decision, not a judgment: A=keep confirmed (reject new) · B=new is right (adopt; old fact待复核) · C=both (new as supplement/history) · D=other (explain, agent analyzes).
- Select-then-submit (never immediate write). Minimal cards, symbol-only English chrome.

## Pitfalls
- `data/` stays private (gitignored). Only code/docs are public.
- Web AIs are text-in/text-out only — never design around them writing via MCP/GitHub.
- R-id must stay stable within a day (reuse assigned ids; renumbering after confirm breaks rapid multi-click submissions).
- state.db `role='user'` messages contain system injections (`[Cronjob` / `[System:` / `[ASYNC` / `[IMPORTANT:` / `[CONTEXT COMPACTION`) and duplicate rows — `import` filters by prefix + dedups.
- confidence is rule-computed (asserted 3 > observed 2 > inferred 1, +evidence/cross-day/cross-agent), never model-emitted decimals.
- `apply` is pure string parsing (no LLM) — conversation text cannot trigger writes.
- **每个 profile 有独立的 `state.db`**（`profiles/<name>/state.db`）。`import hermes` 按 `HERMES_HOME` 解析（其次 `$HERMES_STATE_DB`，再次 `--db`，最后才回退 `%LOCALAPPDATA%\hermes\state.db`），并打印实际用的路径——**绝不能硬编码默认 profile 的 db**，否则会给这个 profile 的人建出别人的记忆。
  - 在 MSYS bash 里 `HERMES_HOME` 必须传原生路径（`C:/...`）：`/c/...` 原生 Python 不认，会静默回退到默认 profile。现已改为打 `⚠` 告警。
