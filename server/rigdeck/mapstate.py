"""Has the game moved on since the map was exported?

The road network under the panel's GPS is read out of the game's own archives once, by
export_maps.ps1, and then sits there. That is the right trade -- parsing a continent
takes seconds and a tablet cannot do it at all -- but it means a ProMods update or a new
map DLC leaves the panel drawing last month's roads with nothing to say about it. The
first sign would be a junction that is not there, at night, in the rain.

So the export records what it was made from: the mod files it read and the DLC archives
that were in the game folder. This compares that against what is there now. It cannot
re-export anything -- that needs the game closed and several minutes -- it can only say
that the time has come.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

WEB_MAPS = Path(__file__).resolve().parent.parent.parent / "web" / "maps"

TITLES = {"ETS2": "Euro Truck Simulator 2", "ATS": "American Truck Simulator"}
FOLDERS = {"ETS2": "ets2", "ATS": "ats"}

# The game logs every mod it mounts at each start, in priority order, so the last such
# block in the file is the state of play.
_ACTIVE = re.compile(r"\[mods\] Active \d+ mods")
_MOD = re.compile(r"\[mods\] Active local mod (.+?) \(name:")


def _documents() -> Path:
    return Path(os.path.expanduser("~")) / "Documents"


def active_mods(game: str) -> list[str] | None:
    """Mod names the game last started with, or None if it has never been started."""
    log = _documents() / TITLES[game] / "game.log.txt"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    start = None
    for index, line in enumerate(lines):
        if _ACTIVE.search(line):
            start = index
    if start is None:
        return []

    names = []
    for line in lines[start + 1:]:
        found = _MOD.search(line)
        if found:
            names.append(found.group(1))
        elif names and _ACTIVE.search(line):
            break
    return names


def check(game: str) -> dict:
    """
    A verdict for one game: `state` is one of

        absent   -- no map has been exported for this game at all
        unknown  -- exported, but by a version that recorded nothing to compare, or the
                    game folder has moved, so staleness cannot be judged either way
        stale    -- the mods or the DLC archives have changed since the export
        current  -- as far as can be told, the map matches the game

    `note` is the same thing as a sentence, ready to put in front of the driver.
    """
    if game not in FOLDERS:
        return {"state": "unknown", "note": ""}

    meta_path = WEB_MAPS / FOLDERS[game] / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "absent",
                "note": f"No map exported for {game} yet -- run export_maps.ps1."}

    game_dir = meta.get("gameDir")
    if not game_dir or "dlcs" not in meta:
        return {"state": "unknown", "note": ""}
    if not Path(game_dir).is_dir():
        return {"state": "unknown", "note": ""}

    changed = []

    was_dlcs = set(meta.get("dlcs") or [])
    now_dlcs = {p.name for p in Path(game_dir).glob("dlc_*.scs")}
    added = len(now_dlcs - was_dlcs)
    if added:
        changed.append(f"{added} new DLC" if added == 1 else f"{added} new DLCs")

    # Mods are recorded as file names and logged by name, so the extension comes off
    # before they are compared. A version bump renames the file, which is exactly the
    # change worth catching.
    now_mods = active_mods(game)
    if now_mods is not None:
        was_mods = {Path(name).stem.lower() for name in (meta.get("mods") or [])}
        now = {name.lower() for name in now_mods}
        # Not a count: an updated ProMods renames four files at once, and "8 changed
        # mods" for one upgrade reads like something went badly wrong.
        if now != was_mods:
            changed.append("the mod list has changed")

    if not changed:
        return {"state": "current", "note": ""}
    return {"state": "stale",
            "note": f"The {game} map is out of date ({', '.join(changed)}). "
                    f"Close the game and run export_maps.ps1."}
