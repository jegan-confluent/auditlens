"""Container entrypoint for the AuditLens API.

The API should run as UID/GID 1000, but Docker named volumes are created as
root-owned on first use. This entrypoint fixes only the runtime data directory
ownership while running as root, then drops privileges before starting uvicorn.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


APP_UID = int(os.environ.get("AUDITLENS_UID", "1000"))
APP_GID = int(os.environ.get("AUDITLENS_GID", "1000"))
RUNTIME_DIR = Path(os.environ.get("AUDITLENS_RUNTIME_DIR", "/var/lib/auditlens"))
DEFAULT_COMMAND = [
    "uvicorn",
    "backend.app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8080",
]


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:"):
        return None
    parsed = urlparse(database_url)
    if parsed.path:
        return Path(unquote(parsed.path))
    if database_url.startswith("sqlite:///"):
        return Path(unquote(database_url.removeprefix("sqlite:///")))
    return None


def _safe_chown(path: Path) -> None:
    try:
        os.chown(path, APP_UID, APP_GID)
    except FileNotFoundError:
        return


def _prepare_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if os.geteuid() != 0:
        return

    _safe_chown(RUNTIME_DIR)
    mode = stat.S_IMODE(RUNTIME_DIR.stat().st_mode)
    try:
        os.chmod(RUNTIME_DIR, mode | stat.S_IRWXU | stat.S_IRWXG)
    except PermissionError:
        pass

    sqlite_path = _sqlite_path_from_url(os.environ.get("DATABASE_URL", ""))
    if sqlite_path is None:
        return
    try:
        sqlite_path.relative_to(RUNTIME_DIR)
    except ValueError:
        return

    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{sqlite_path}{suffix}")
        if candidate.exists():
            _safe_chown(candidate)


def _drop_privileges() -> None:
    if os.geteuid() != 0:
        return
    os.setgroups([])
    os.setgid(APP_GID)
    os.setuid(APP_UID)


def main() -> None:
    _prepare_runtime_dir()
    _drop_privileges()
    command = sys.argv[1:] or DEFAULT_COMMAND
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
