"""Locate the patch payload from the firmware checkout under test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / 'user/w1700k-patches'
