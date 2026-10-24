"""Check tracked publication files for credentials, private paths and user data.

This guard prints file names and issue categories only, never matching values.
It complements manual review; it is not a proof that arbitrary data is public.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "credential": re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)"),
    "absolute_machine_path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),
    "private_home_path": re.compile(r"/(?:Users|home)/[^/\s`\"<>]+/"),
    "phone_number": re.compile(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])"),
}
EMAIL = re.compile(r"[A-Za-z0-9_.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PUBLIC_EMAIL_DOMAINS = {"example.com", "example.org", "example.test", "users.noreply.github.com"}
DENIED_PARTS = {".git", ".venv", "node_modules", "work", "delivery", "data", "backups", "__pycache__"}
DENIED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx", ".pyc"}


def inspect_file(relative, data):
    path = Path(relative)
    issues = []
    if (DENIED_PARTS.intersection(path.parts) or path.suffix.lower() in DENIED_SUFFIXES
            or (path.name.startswith('.env') and path.name != '.env.example')):
        issues.append("excluded_local_file")
    if b'\0' in data:
        return issues
    content = data.decode('utf-8', errors='replace')
    for kind, pattern in PATTERNS.items():
        if pattern.search(content):
            issues.append(kind)
    if any(m.group(1).lower() not in PUBLIC_EMAIL_DOMAINS for m in EMAIL.finditer(content)):
        issues.append("personal_email")
    return issues


def check(root=ROOT):
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    return [(name, issue) for name in names if name for issue in inspect_file(name, (root / name).read_bytes())]


if __name__ == '__main__':
    issues = check()
    for name, kind in issues:
        print(f'{name}: {kind}')
    print(f'Publication privacy check: {len(issues)} issue(s). Matching values are never printed.')
    raise SystemExit(bool(issues))
