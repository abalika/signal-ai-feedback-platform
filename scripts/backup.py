"""SQLite consistent backup/restore; destination must be new, never overwrite."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def copy_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError("Source database does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Atomic exclusive creation also rejects source == destination and races.
    with destination.open("xb"):
        pass
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Source integrity check failed")
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        print(copy_database(args.source, args.destination))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Database copy failed: {exc}\nUse a new destination; original data is unchanged.\n")
