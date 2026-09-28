"""Run as `python tools/l2mod <command>`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from l2mod.cli import main  # noqa: E402

sys.exit(main())
