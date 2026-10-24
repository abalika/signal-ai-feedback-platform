import sqlite3
import hashlib
import json
from contextlib import closing

import pytest

from scripts.backup import copy_database
from scripts.check_package import verify
from scripts.package_delivery import source_allowed


def test_backup_restore_roundtrip_and_refuse_overwrite(tmp_path):
    source, backup, restored = (tmp_path / name for name in ("source.db", "backup.db", "restored.db"))
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("CREATE TABLE proof(value TEXT)")
        conn.execute("INSERT INTO proof VALUES (?)", ("中文 / rollback",))
        conn.commit()
    copy_database(source, backup)
    copy_database(backup, restored)
    with closing(sqlite3.connect(restored)) as conn:
        assert conn.execute("SELECT value FROM proof").fetchone()[0] == "中文 / rollback"
    for target in (source, backup):
        with pytest.raises(FileExistsError):
            copy_database(source, target)
    with pytest.raises(ValueError, match="does not exist"):
        copy_database(tmp_path / "missing.db", tmp_path / "unused.db")


def test_backup_rejects_invalid_database(tmp_path):
    invalid = tmp_path / "bad.db"
    invalid.write_bytes(b"invalid sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        copy_database(invalid, tmp_path / "backup.db")
    assert invalid.read_bytes() == b"invalid sqlite"


def test_release_integrity_detects_tampering_missing_and_unsafe_paths(tmp_path):
    file = tmp_path / "proof.txt"
    file.write_bytes(b"original")
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(json.dumps({"files": {"proof.txt": hashlib.sha256(b"original").hexdigest()}}))
    assert verify(tmp_path) == []
    file.write_bytes(b"tampered")
    assert verify(tmp_path) == ["proof.txt: changed"]
    file.unlink()
    assert verify(tmp_path) == ["proof.txt: missing"]
    manifest.write_text(json.dumps({"files": {"../private.txt": "invalid"}}))
    assert verify(tmp_path) == ["../private.txt: unsafe path"]


@pytest.mark.parametrize("path", ["server/.env", "app/.env.local", "data/user.db", "server/data/app.db", "server/.venv/pyvenv.cfg", "work/raw.json", "app/node_modules/a.js", ".git/config"])
def test_release_excludes_secrets_and_user_data(path):
    assert not source_allowed(path)


def test_release_keeps_example_config_and_source():
    assert source_allowed("server/.env.example")
    assert source_allowed("app/src/App.tsx")
