# Installing know-me

The engine (`pm.py`) is stdlib-only and reads nothing beside itself. Three ways to
get it into place; all are a few tens of KB, <2s, and offline after fetch.

## A. Engine already beside this file (normal case)

True when the skill dir was carried over by `hermes profile create --clone` or
`install.py` (the engine lives in `scripts/engine/`). No network, no deps, no clone:

```bash
python <SKILL_DIR>/scripts/install.py --profile <name>   # skill + engine, one command (recommended)
python <SKILL_DIR>/scripts/install.py                    # engine only, default target
```

## B. Only this SKILL.md (another machine / user / pasted copy)

Fetch the engine from the public repo — **never search the local filesystem** (a
`D:`/`C:` sweep is slow and turns up stale copies). The engine reads nothing beside
itself, so this materializes the *whole skill* in one shot; after it, every path
works offline:

```bash
SK="${HERMES_HOME:-$HOME/.hermes}/skills/know-me"   # Windows git-bash: export HERMES_HOME="$LOCALAPPDATA/hermes" (native C:/… path)
mkdir -p "$SK/prompts" "$SK/schema" "$SK/references"
for u in https://raw.githubusercontent.com/loveakiha/know-me/main \
         https://cdn.jsdelivr.net/gh/loveakiha/know-me@main ; do
  ok=1
  for f in SKILL.md pm.py README.md schema/README.md prompts/extract.md prompts/list_memory.md references/install.md; do
    curl -fsSL --max-time 30 -o "$SK/$f" "$u/$f" || { ok=0; break; }
  done
  [ "$ok" = 1 ] && break
done
python "$SK/pm.py" --help        # verify: zero deps, no pip install
```

Mirror order matters: `raw.githubusercontent.com` is throttled/blocked on some
networks (esp. CN); jsDelivr (`cdn.jsdelivr.net/gh/<user>/<repo>@main/<path>`) is the
fallback. **Never bootstrap with `git clone`** — it inherits whatever broken global
proxy config the machine has (on a host with a dead socks5 proxy, clone dies while
plain curl succeeds). After this, `pm.py` runs in place; to give it to another
*profile*, copy `$SK` to `profiles/<name>/skills/know-me/`.

## C. Fastest path for a new profile

This skill is NOT a bundled skill, so `hermes profile create <name>` alone seeds
**bundled skills only** and will not have it:

```bash
hermes profile create <name> --clone      # carry this profile's skills over (incl. scripts/engine/)
python <SKILL_DIR>/scripts/install.py --profile <name>   # add the engine, 0.2s
```

No `--clone` → the profile simply has no know-me skill; that is the gap to close,
not something to search for.

## Installer reference

- `<SKILL_DIR>` = wherever this SKILL.md sits (`$HERMES_HOME/skills/know-me`).
- source order: `--from <repo>` (strict, errors if no `pm.py`) → repo layout (`<repo>/scripts/install.py`) → bundled `scripts/engine/`.
- default target: `%LOCALAPPDATA%\hermes\know-me` (override with `--target` or `$HERMES_KNOWME_DIR`); `--print-target` prints it.
- copies **code/docs only** — an existing `data/` is never written or deleted.
- ends by verifying `python pm.py --help` (zero dependencies); `data/` is auto-created on first run.
- bundled copy drifts: after editing `pm.py`/`schema/`/`prompts/` in the repo, re-copy them into `<SKILL_DIR>/scripts/engine/`.

## Dependencies

None. `pm.py` imports only the stdlib (`argparse hashlib json os re sqlite3 subprocess datetime`). Verified end-to-end (`init` + `export` + `install.py`) on CPython **3.8 / 3.9 / 3.13 / 3.14**; the only optional external program is `git`, used solely by `pm.py sync`.

## Content freshness

Right after a push, `raw.githubusercontent.com` can still serve the previous bytes
for a few minutes and jsDelivr `@main` for up to 12h. To confirm a push landed, use
`git ls-remote origin` or the codeload tarball — not a CDN fetch.
