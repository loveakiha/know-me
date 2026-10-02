#!/usr/bin/env python3
"""know-me self-installer — stdlib only, no network required.

Makes the know-me engine (pm.py + schema/ + prompts/) available in any Hermes
profile or machine, so a freshly created profile can self-install.

Engine source resolution (first match wins):
  1. --from PATH                     an explicit repo checkout
  2. <script>/../                    the repo layout  (repo/scripts/install.py)
  3. <script>/engine/                the bundled copy (skill/scripts/engine/)

Target resolution:
  --target PATH  >  $HERMES_KNOWME_DIR  >  %LOCALAPPDATA%/hermes/know-me

Copies CODE/DOCS ONLY. An existing data/ directory is never written or removed
(the data is private; the code is public).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE_FILES = ["pm.py", "README.md"]
ENGINE_DIRS = ["schema", "prompts"]


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "hermes"
    return Path.home() / ".hermes"


def hermes_root() -> Path:
    """The top-level hermes dir (the one that contains profiles/)."""
    home = hermes_home()
    if (home / "profiles").is_dir():
        return home
    if home.parent.name == "profiles":   # session ran inside profiles/<name>/
        return home.parent.parent
    return home


def install_skill_into_profile(profile: str) -> Path | None:
    """Copy THIS skill directory into profiles/<profile>/skills/. Returns the new skill dir."""
    src_skill = Path(__file__).resolve().parent.parent
    if not (src_skill / "SKILL.md").is_file():
        return None
    root = hermes_root()
    prof_dir = root / "profiles" / profile
    if not prof_dir.is_dir():
        raise SystemExit(f"profile {profile!r} does not exist: {prof_dir}\nCreate it first: hermes profile create {profile}")
    dst = prof_dir / "skills" / src_skill.name
    shutil.copytree(
        src_skill, dst, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data"),
    )
    return dst


def resolve_source(explicit: str | None) -> Path:
    here = Path(__file__).resolve().parent
    candidates: list[Path] = []
    if explicit:
        cand = Path(explicit).expanduser()
        if not (cand / "pm.py").is_file():
            raise SystemExit(f"--from {explicit}: no pm.py there")
        candidates.append(cand)
    candidates.append(here.parent)      # repo layout: <repo>/scripts/install.py
    candidates.append(here / "engine")  # bundled layout: <skill>/scripts/engine/
    for cand in candidates:
        if (cand / "pm.py").is_file():
            return cand
    raise SystemExit(
        "know-me engine not found. Tried:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + "\nPass --from <path-to-repo>, or clone github.com/loveakiha/know-me."
    )


def install(src: Path, target: Path) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in ENGINE_FILES:
        s = src / name
        if s.is_file():
            shutil.copyfile(s, target / name)
            written.append(name)
    for name in ENGINE_DIRS:
        s = src / name
        if s.is_dir():
            d = target / name
            d.mkdir(exist_ok=True)
            for f in sorted(s.iterdir()):
                if f.is_file():
                    shutil.copyfile(f, d / f.name)
                    written.append(f"{name}/{f.name}")
    return written


def verify(target: Path) -> bool:
    for exe in ([sys.executable] if sys.executable else []) + ["python", "python3"]:
        try:
            r = subprocess.run(
                [exe, "pm.py", "--help"], cwd=target,
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            print(f"  verified: {exe} pm.py --help -> ok")
            return True
    print("  WARNING: could not verify (run `python pm.py --help` yourself)")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the know-me engine (and optionally the skill itself into a profile).")
    ap.add_argument("--from", dest="src", default=None, help="repo checkout to copy from")
    ap.add_argument("--target", default=None, help="install dir (default: %%LOCALAPPDATA%%/hermes/know-me)")
    ap.add_argument("--print-target", action="store_true", help="print the resolved target and exit")
    ap.add_argument("--profile", default=None,
                    help="one-shot: copy this skill into profiles/<NAME>/skills/ AND install the engine into profiles/<NAME>/know-me")
    args = ap.parse_args()

    if args.profile:
        root = hermes_root()
        dst_skill = install_skill_into_profile(args.profile)
        print(f"skill  : {dst_skill}")
        args.target = str(root / "profiles" / args.profile / "know-me")

    target = Path(
        args.target or os.environ.get("HERMES_KNOWME_DIR") or (hermes_home() / "know-me")
    ).expanduser()
    if args.print_target:
        print(target)
        return 0

    src = resolve_source(args.src)
    print(f"engine: {src}")
    print(f"target: {target}")
    if (target / "data").is_dir():
        print("  note: existing data/ found — left untouched (private).")

    for rel in install(src, target):
        print(f"  + {rel}")

    print("\nnext steps:")
    if verify(target):
        pass
    print(f'  cd "{target}" && python pm.py init      # self-introduction (optional)')
    print(f'  cd "{target}" && python pm.py import hermes --since 2020-01-01   # bootstrap')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
