#!/usr/bin/env python3
"""Execute the real-machine Module 1–2 acceptance workflow."""

from pathlib import Path

from repo_intel.acceptance import acceptance_main

if __name__ == "__main__":
    raise SystemExit(
        acceptance_main(repo_root=Path(__file__).resolve().parents[1]),
    )
