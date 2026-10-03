#!/usr/bin/env python3
"""Prevent a release tag from describing a different engine version."""
import json
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[1]
version = json.loads((root / "zstd-version.json").read_text())["version"]
if len(sys.argv) != 2 or not re.fullmatch(r"zstd-" + re.escape(version) + r"-[1-9][0-9]*", sys.argv[1]):
    raise SystemExit(f"Release tag must be zstd-{version}-<positive packaging revision>")
