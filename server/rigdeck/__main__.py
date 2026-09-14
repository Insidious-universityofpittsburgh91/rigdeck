"""Entry point:  python -m rigdeck  [--mock] [--port N]"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="rigdeck", description="Rig Deck server")
    parser.add_argument("--mock", action="store_true",
                        help="write fake telemetry instead of running the panel server "
                             "(for testing with the game closed)")
    parser.add_argument("--game", choices=["ETS2", "ATS"], default="ETS2",
                        help="which game the mock feed should pretend to be")
    parser.add_argument("--port", type=int, help="override the panel port for this run")
    parser.add_argument("--bindings", action="store_true",
                        help="print the vJoy button sheet to bind in the game and exit")
    parser.add_argument("--tray", action="store_true",
                        help="run in the notification area instead of a console")
    args = parser.parse_args()

    if args.tray:
        from .tray import main as run_tray
        return run_tray()

    if args.bindings:
        from .controls import binding_sheet
        print("\n  Bind these once in Options -> Controls (vJoy device 1).")
        print("  The right-hand column is the entry to look for in the game's own list.\n")
        for row in binding_sheet():
            note = f"   [sent as the {row['key']} key -- no binding needed]" if row["key"] else ""
            print(f"  Button {row['button']:>2}   {row['label']:<20} {row['game']}{note}")
        print("\n  Esc and Enter are keystrokes and appear on no button.")
        print("  Or skip the whole list:  python bindwrite.py --write  writes all of it")
        print("  into the profile itself, with the game closed.\n")
        return 0

    if args.mock:
        from .mockfeed import run
        run(game=args.game)
        return 0

    from . import config as cfgmod
    if args.port:
        cfgmod.load()
        cfgmod.update({"port": args.port})

    from .app import main as run_server
    run_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
