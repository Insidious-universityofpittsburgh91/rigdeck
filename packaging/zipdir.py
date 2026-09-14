r"""Zip a folder with separators a zip file is actually allowed to have.

Windows tools will happily write `RigDeck\server\app.py` as an entry name, which is
not a path in the zip format -- it is a file whose name contains backslashes. Windows'
own extractor tolerates it; plenty of others create one file with a very odd name, and
the person on the other end has a broken folder and no idea why.

    python zipdir.py <folder> <output.zip>
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1

    source, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if not source.is_dir():
        print(f"  no such folder: {source}")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    files = sorted(p for p in source.rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            zf.write(path, "/".join(path.relative_to(source.parent).parts))

    size = target.stat().st_size
    print(f"  {len(files)} files, {size / 1048576:.1f} MB -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
