"""Starts Rig Deck in the tray.

A file rather than `-m rigdeck --tray` because Windows' startup registry has nowhere to
put a working directory, and this can be launched by full path from anywhere.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rigdeck.tray import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
