"""Shared exact release-image validation for firmware helpers."""
import hashlib
from pathlib import Path


def collect(targets, profile):
    directory = Path(targets) / profile["target"]
    names = tuple(profile["images"])
    patterns = ('*.bin',) if profile["device"] == "MX4200" else (
        '*sysupgrade.itb', '*installer.itb', '*chainload-uboot.itb')
    candidates = sorted({p for pattern in patterns for p in directory.glob(pattern)
                         if (profile["device"] != "MX4200" or "factory" in p.name or "sysupgrade" in p.name)})
    if len(candidates) != len(names) or {p.name for p in candidates} != set(names):
        raise ValueError("unexpected release image names/count")
    result = []
    for path in sorted((directory / name for name in names), key=lambda p: p.name):
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError("missing, empty or symlink release image: " + path.name)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result.append({"name": path.name, "size": path.stat().st_size,
                       "digest": "sha256:" + digest})
    return result
