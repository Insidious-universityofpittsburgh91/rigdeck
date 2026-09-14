"""Write every Rig Deck binding straight into the game's controls.sii.

    python bindwrite.py                 # newest profile, shows what it will do first
    python bindwrite.py --write         # actually write it
    python bindwrite.py --list          # every profile found, newest first
    python bindwrite.py --profile <dir> # a particular one

Binding these by hand means walking two lists that are in different orders -- the
panel's and the game's -- and pressing the right pair thirty-one times. Skip one entry
and every binding after it silently lands one button early, which is how a tap on the
air horn ends up pulling the parking brake. The button numbers are already written down
in controls.py; this puts them where the game reads them.

The game must be closed. It holds the profile open and rewrites controls.sii from
memory when it exits, so anything written underneath a running game is thrown away.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rigdeck import controls as controlsmod
from rigdeck import gameproc

# vJoy's DirectInput product GUID always starts with its VID/PID pair, 1234:BEAD.
VJOY_PRODUCT = "BEAD1234"

DOCS = {
    "ETS2": "Euro Truck Simulator 2",
    "ATS": "American Truck Simulator",
}

DEVICE = re.compile(r'"device (joy\d*) `([^`]*)`"')
MIX = re.compile(r'^(\s*config_lines\[\d+\]: "mix )([a-z0-9_]+)( `)([^`]*)(`")\s*$')


def profiles() -> list[Path]:
    """Every controls.sii on this machine, newest first."""
    found = []
    home = Path.home() / "Documents"
    for game, folder in DOCS.items():
        root = home / folder
        # Steam profiles live beside the local ones and are the ones normally in use.
        for holder in ("profiles", "steam_profiles"):
            for profile in sorted((root / holder).glob("*")):
                path = profile / "controls.sii"
                if path.is_file():
                    found.append(path)
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def label(path: Path) -> str:
    game = next((g for g, folder in DOCS.items() if folder in str(path)), "?")
    try:                                    # profile folders are hex-encoded names
        name = bytes.fromhex(path.parent.name).decode("utf-8")
    except ValueError:
        name = path.parent.name
    return f"{game}  {name}"


def vjoy_slot(lines: list[str]) -> str | None:
    """Which of joy..joy6 the game has vJoy sitting in, if any.

    Bindings name the slot, not the device, so a vJoy that has moved slots takes
    every binding with it -- and one that is in no slot at all cannot be bound.
    """
    for line in lines:
        found = DEVICE.search(line)
        if found and VJOY_PRODUCT in found.group(2).upper():
            return found.group(1)
    return None


def free_slot(lines: list[str]) -> str | None:
    """The first empty controller slot -- the one the game itself would fill next."""
    for line in lines:
        found = DEVICE.search(line)
        if found and found.group(1).startswith("joy") and not found.group(2):
            return found.group(1)
    return None


def vjoy_device_string() -> str | None:
    """vJoy's DirectInput identifier, taken from a profile that already has it.

    The identifier is the pair of GUIDs the game writes for a device -- an instance
    GUID that Windows keeps stable for as long as the device exists on this machine,
    and vJoy's product GUID. Copying it into another profile is the same string the
    game would have written there itself.
    """
    for path in profiles():
        with open(path, "r", encoding="utf-8", newline="") as fh:
            for line in fh:
                found = DEVICE.search(line)
                if found and VJOY_PRODUCT in found.group(2).upper():
                    return found.group(2)
    return None


def claim(lines: list[str], slot: str, device: str) -> list[str]:
    """Put vJoy in a slot the game has left empty."""
    out = []
    for line in lines:
        found = DEVICE.search(line)
        if found and found.group(1) == slot and not found.group(2):
            line = line.replace(f'"device {slot} ``"', f'"device {slot} `{device}`"')
        out.append(line)
    return out


def rebind(lines: list[str], slot: str) -> tuple[list[str], list[str]]:
    """Put every action on its own button and clear this slot off everything else."""
    wanted = {row["sii"]: row for row in controlsmod.binding_sheet() if row["sii"]}
    term = re.compile(rf"\b{slot}\.b\d+\?\d+\s*\|\s*")
    out, notes, seen = [], [], set()

    for line in lines:
        found = MIX.match(line.rstrip("\r\n"))
        if not found:
            out.append(line)
            continue

        head, name, open_q, body, close_q = found.groups()
        ending = line[len(line.rstrip("\r\n")):]
        was = body
        body = term.sub("", body)               # this slot's old binding, wherever it sat

        row = wanted.get(name)
        if row:
            seen.add(name)
            marker = f"semantical.{name}?0"
            press = f"{slot}.b{row['button']}?0 | "
            body = body.replace(marker, press + marker) if marker in body else press + body
            notes.append(f"  b{row['button']:>2}  {row['label']:<20} -> {name}")
        elif was != body:
            notes.append(f"  --   cleared {slot} off {name}")

        out.append(f"{head}{name}{open_q}{body}{close_q}{ending}")

    for name, row in wanted.items():
        if name not in seen:
            notes.append(f"  !!   {row['label']}: the game has no '{name}' control -- skipped")
    return out, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="write Rig Deck's bindings into a profile")
    parser.add_argument("--list", action="store_true", help="show the profiles and exit")
    parser.add_argument("--profile", help="path to a profile folder or its controls.sii")
    parser.add_argument("--write", action="store_true",
                        help="write the file; without this it only says what it would do")
    parser.add_argument("--claim", action="store_true",
                        help="if vJoy is in no controller slot, put it in the first free "
                             "one instead of stopping (saves a trip through the game's "
                             "own Controls page)")
    args = parser.parse_args()

    found = profiles()
    if args.list:
        for path in found:
            print(f"  {label(path)}\n      {path}")
        return 0 if found else 1

    running = gameproc.running_game()
    if running and args.write:
        print(f"  {running} is running. It rewrites controls.sii when it exits, so anything")
        print("  written now is thrown away. Close the game and run this again.")
        return 2

    if args.profile:
        path = Path(args.profile)
        if path.is_dir():
            path = path / "controls.sii"
    elif found:
        path = found[0]
    else:
        print("  No profile found under Documents. Has the game been run once?")
        return 1

    if not path.is_file():
        print(f"  No controls.sii at {path}")
        return 1

    # newline="" so the file's own line endings survive the round trip untouched
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    if not text.lstrip().startswith("SiiNunit"):
        print("  That profile is saved in the binary format, which this cannot edit.")
        print("  Set   uset g_save_format \"2\"   in the game console and save once.")
        return 1

    lines = text.splitlines(keepends=True)
    print(f"  {label(path)}")
    print(f"  {path}")

    slot = vjoy_slot(lines)
    claiming = False
    if slot is None:
        if not args.claim:
            print("\n  vJoy is in none of this profile's six controller slots, so nothing can")
            print("  be bound to it. Either open the game's Options -> Controls and pick vJoy")
            print("  there once, or run this again with --claim to put it in the first free")
            print("  slot directly.")
            return 1
        slot = free_slot(lines)
        device = vjoy_device_string()
        if slot is None:
            print("\n  All six controller slots are taken, so vJoy has nowhere to go. Free one")
            print("  in the game's Options -> Controls first.")
            return 1
        if device is None:
            print("\n  No profile on this machine has vJoy in a slot, so there is no device")
            print("  string to copy. Pick vJoy once in the game's Options -> Controls.")
            return 1
        lines = claim(lines, slot, device)
        claiming = True

    print(f"  vJoy is device '{slot}' -- bindings will be written as {slot}.bN")
    if claiming:
        print(f"  '{slot}' was empty; vJoy is being put in it.")
    print()

    out, notes = rebind(lines, slot)
    print("\n".join(notes))

    if not args.write:
        print("\n  Nothing written. Run again with --write to do it.")
        return 0

    backup = path.with_suffix(".sii.rigdeck-backup")
    count = 1
    while backup.exists():
        count += 1
        backup = path.with_suffix(f".sii.rigdeck-backup{count}")
    with open(backup, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out))
    print(f"\n  Written. The file as it was is kept at {backup.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
