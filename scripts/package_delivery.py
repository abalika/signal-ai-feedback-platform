"""Build a new Windows x64 offline ZIP from tracked source + local runtimes.

Run verify.ps1 first. Requires this repository's Windows Python venv and npm
dependencies. Does not download anything, read .env, or include user databases.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENIED_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "data", "work", "delivery", "backups"}
DENIED_SUFFIXES = {".db", ".sqlite3", ".sqlite", ".pyc", ".pyo"}


def source_allowed(relative):
    path = Path(relative)
    return (not DENIED_PARTS.intersection(path.parts) and path.suffix.lower() not in DENIED_SUFFIXES
            and (not path.name.startswith(".env") or path.name == ".env.example"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build(output, name):
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("This package target requires Windows x64")
    if not (ROOT / "app/dist/index.html").is_file():
        raise ValueError("Build frontend before packaging")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True)
    if dirty.strip():
        raise ValueError("Commit tracked changes before packaging so the revision is reviewable")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    package = output / name
    package.mkdir(exist_ok=False)
    for relative in tracked:
        if relative and source_allowed(relative):
            copy_file(ROOT / relative, package / relative)
    shutil.copytree(ROOT / "app/dist", package / "app/dist")
    runtime = package / "runtime"
    runtime.mkdir()
    base = Path(sys.base_prefix)
    for filename in ("python.exe", "python3.dll", f"python{sys.version_info.major}{sys.version_info.minor}.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        copy_file(base / filename, runtime / filename)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(base / "DLLs", runtime / "DLLs", ignore=ignore)
    def stdlib_ignore(directory, names):
        denied = set(ignore(directory, names))
        if Path(directory) == base / "Lib":
            denied.update({"site-packages", "test", "idlelib", "turtledemo", "tkinter", "ensurepip"}.intersection(names))
        return denied
    shutil.copytree(base / "Lib", runtime / "Lib", ignore=stdlib_ignore)
    site_packages = Path(sysconfig.get_path("purelib"))
    if site_packages.resolve() == (base / "Lib/site-packages").resolve():
        raise ValueError("Run with project venv, not a global Python environment")
    shutil.copytree(site_packages, runtime / "Lib/site-packages", ignore=ignore)
    (runtime / f"python{sys.version_info.major}{sys.version_info.minor}._pth").write_text("Lib\nDLLs\nLib/site-packages\n..\nimport site\n", encoding="utf-8")
    # Preserve notices for the bundled frontend. Includes build dependency
    # notices too, so future bundle composition changes do not omit notices.
    modules = ROOT / "app/node_modules"
    for path in modules.rglob("*"):
        if path.is_file() and path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
            copy_file(path, package / "licenses/frontend" / path.relative_to(modules))
    (package / "交付说明.txt").write_text("Signal 本机离线交付\n\n完整解压后双击 start.bat，打开 http://127.0.0.1:8010。\n默认离线固定回放，无模型调用。dsh/真实模型本轮未测。\n完整说明：docs/用户手册.md\n校验：runtime\\python.exe scripts\\check_package.py .\n评测：runtime\\python.exe scripts\\evaluate.py\n源码开发需要另外安装 Node.js 并执行 scripts/setup.ps1。\nPython 许可见 runtime/LICENSE.txt；Python 依赖许可位于 runtime/Lib/site-packages/*dist-info；前端许可见 licenses/frontend。\n", encoding="utf-8-sig")
    # Include a reproducible report as evidence; it contains only fixture inputs.
    subprocess.run([str(runtime / "python.exe"), str(package / "scripts/evaluate.py"), "--output", str(package / "reports/acceptance")], cwd=package, check=True)
    # The evaluator creates only an empty work directory, not release data.
    files = {path.relative_to(package).as_posix(): sha256(path) for path in sorted(package.rglob("*")) if path.is_file() and "__pycache__" not in path.parts and path.relative_to(package).parts[0] not in {"work", "data", "backups"}}
    dependencies = sorted(f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions())
    manifest = {"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(), "revision": revision, "target": "Windows x64", "python": platform.python_version(), "offline_default": True, "live_model_tested": False, "dependencies": dependencies, "files": files}
    (package / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output / (name + ".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in [package / relative for relative in files] + [package / "MANIFEST.json"]:
            zipped.write(path, path.relative_to(output).as_posix())
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(sha256(archive) + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "sha256": sha256(archive), "files": len(files), "revision": revision}))
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "delivery")
    parser.add_argument("--name", default="Signal-Windows-x64-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    if Path(args.name).name != args.name or args.name in {".", ".."}:
        parser.error("name must be a plain folder name")
    try:
        build(args.output, args.name)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Packaging failed: {exc}\nExisting outputs are preserved; use a new name to retry.\n")
