"""Install or remove the Quest Navigator patch to the Alt+U quest window.

The patch itself is UnrealScript source in tools/l2mod/patches/quest-navigator.l2patch, compiled and verified by
l2mod. This script is kept for the commands in README.md:

    python patch_questtreewnd.py            # build, verify and install (the client must be closed)
    python patch_questtreewnd.py --check    # build and verify, write nothing
    python patch_questtreewnd.py --restore  # put the stock interface.u back
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "l2mod"))

from l2mod.cli import main  # noqa: E402

PATCH = os.path.join(HERE, "..", "l2mod", "patches", "quest-navigator.l2patch")

if __name__ == "__main__":
    if "--restore" in sys.argv:
        sys.exit(main(["restore", "interface.u"]))
    if "--check" in sys.argv:
        sys.exit(main(["build", PATCH]))
    sys.exit(main(["install", PATCH]))
