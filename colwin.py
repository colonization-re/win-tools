#!/usr/bin/env python3
"""Run colwin without installing it: `python3 colwin.py ...`"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from colwin.cli import main                                    # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
