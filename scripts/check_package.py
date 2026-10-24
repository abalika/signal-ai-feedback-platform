"""Verify every release file against its SHA-256 manifest (no network)."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    failures = []
    for relative, expected in manifest["files"].items():
        path = root / relative
        # Reject a tampered manifest that tries to read outside the package.
        if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts or not path.resolve().is_relative_to(root):
            failures.append(relative + ": unsafe path")
        elif not path.is_file():
            failures.append(relative + ": missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(relative + ": changed")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        errors = verify(args.root)
        if errors:
            parser.exit(1, "Package integrity failed:\n" + "\n".join(errors) + "\n")
        print("PASS: all manifest file hashes match. Runtime-generated data/work/backups are excluded.")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Cannot verify package: {exc}\n")
