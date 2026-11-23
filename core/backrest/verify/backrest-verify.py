#!/usr/bin/env python3
"""Monthly Backrest/Restic restore verification.

The service restores the latest Core snapshot from the local repository and from
one rotating remote repository, verifies the restored tree, validates the
database dumps and the staged configuration, and exposes the result through
`/status` and `/metrics`.

It never writes to a repository: every Restic command uses `--no-lock` and the
repositories are mounted read-only. The Docker socket is intentionally not
mounted.

Environment:
  BACKREST_CONFIG                  default /config/config.json
  BACKREST_REPO_DIR                default /repos/external
  BACKREST_VERIFY_STATE_DIR        default /verify/state
  BACKREST_VERIFY_SCRATCH_DIR      default /verify/scratch
  BACKREST_VERIFY_RCLONE_CONFIG    default /rclone/rclone.conf
  BACKREST_VERIFY_DAY              default 16
  BACKREST_VERIFY_HOUR             default 4
  BACKREST_VERIFY_MINUTE           default 0
  BACKREST_VERIFY_TIMEZONE         default Europe/Madrid
  BACKREST_VERIFY_REMOTE_ROTATION  default GDrive-RedServer,miixzify
  BACKREST_VERIFY_READ_DATA_PERCENT default 10
  BACKREST_VERIFY_MIN_FREE_GB      default 40
  BACKREST_VERIFY_MAX_SNAPSHOT_AGE_HOURS default 36
  BACKREST_VERIFY_MAX_RETRIES      default 3
  BACKREST_VERIFY_RETRY_HOURS      default 24
  BACKREST_VERIFY_KEEP_REPORTS     default 12
  BACKREST_VERIFY_PORT             default 9798
  BACKREST_URL                     default http://backrest:9898
  BACKREST_EXPORTER_USER           default prometheus
  BACKREST_EXPORTER_PASSWORD       optional; used for the idle check
"""

from __future__ import annotations

import argparse
import base64
import calendar
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import yaml
except ImportError:  # pragma: no cover - the image installs py3-yaml
    yaml = None


CONFIG_PATH = Path(os.environ.get("BACKREST_CONFIG", "/config/config.json"))
STATE_DIR = Path(os.environ.get("BACKREST_VERIFY_STATE_DIR", "/verify/state"))
SCRATCH_DIR = Path(os.environ.get("BACKREST_VERIFY_SCRATCH_DIR", "/verify/scratch"))
RCLONE_SOURCE = Path(
    os.environ.get("BACKREST_VERIFY_RCLONE_CONFIG", "/rclone/rclone.conf")
)
# Keep the writable rclone copy in the container's ephemeral /tmp, never in the
# state volume: the state volume is inside /var/lib/docker/volumes and would be
# captured by the Core backup, and rclone.conf must stay out of the backup.
RCLONE_CONFIG = Path("/tmp/rclone.conf")

DAY = int(os.environ.get("BACKREST_VERIFY_DAY", "16"))
HOUR = int(os.environ.get("BACKREST_VERIFY_HOUR", "4"))
MINUTE = int(os.environ.get("BACKREST_VERIFY_MINUTE", "0"))
ENABLED = os.environ.get("BACKREST_VERIFY_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
    "off",
)
TIMEZONE = os.environ.get("BACKREST_VERIFY_TIMEZONE", "Europe/Madrid")
ROTATION = [
    item.strip()
    for item in os.environ.get(
        "BACKREST_VERIFY_REMOTE_ROTATION", "GDrive-RedServer,miixzify"
    ).split(",")
    if item.strip()
]
READ_DATA_PERCENT = int(os.environ.get("BACKREST_VERIFY_READ_DATA_PERCENT", "10"))
MIN_FREE_GB = int(os.environ.get("BACKREST_VERIFY_MIN_FREE_GB", "40"))
MAX_SNAPSHOT_AGE_HOURS = int(
    os.environ.get("BACKREST_VERIFY_MAX_SNAPSHOT_AGE_HOURS", "36")
)
MAX_RETRIES = int(os.environ.get("BACKREST_VERIFY_MAX_RETRIES", "3"))
RETRY_HOURS = int(os.environ.get("BACKREST_VERIFY_RETRY_HOURS", "24"))
KEEP_REPORTS = int(os.environ.get("BACKREST_VERIFY_KEEP_REPORTS", "12"))
PORT = int(os.environ.get("BACKREST_VERIFY_PORT", "9798"))
CHECK_TIMEOUT = int(os.environ.get("BACKREST_VERIFY_CHECK_TIMEOUT", "21600"))
RESTORE_TIMEOUT = int(os.environ.get("BACKREST_VERIFY_RESTORE_TIMEOUT", "21600"))

BACKREST_URL = os.environ.get("BACKREST_URL", "http://backrest:9898").rstrip("/")
BACKREST_USER = os.environ.get("BACKREST_EXPORTER_USER", "prometheus")
BACKREST_PASSWORD = os.environ.get("BACKREST_EXPORTER_PASSWORD", "")

CORE_PATHS = [
    item.strip()
    for item in os.environ.get(
        "BACKREST_VERIFY_CORE_PATHS",
        "/backup/docker_volumes,/backup/homelab,/backup/opt,/data/dbdumps,"
        "/data/scripts,/data/stack-envs,/data/home-config,/data/host-config",
    ).split(",")
    if item.strip()
]
HEAVY_PATHS = [
    item.strip()
    for item in os.environ.get(
        "BACKREST_VERIFY_HEAVY_PATHS", "/backup/srv/nextcloud_data"
    ).split(",")
    if item.strip()
]
RESTORE_PATHS = [
    item.strip()
    for item in os.environ.get("BACKREST_VERIFY_RESTORE_PATHS", "").split(",")
    if item.strip()
]
REQUIRED_ENV_KEYS = [
    item.strip()
    for item in os.environ.get(
        "BACKREST_VERIFY_REQUIRED_ENV_KEYS",
        "BACKREST_EXPORTER_PASSWORD,CF_API_TOKEN,SECRET_ENCRYPTION_KEY,"
        "HEADSCALE_AUTHKEY,ROMM_AUTH_SECRET_KEY,ADMIN_TOKEN",
    ).split(",")
    if item.strip()
]

STATE_FILE = STATE_DIR / "state.json"
STATUS_FILE = STATE_DIR / "status.json"
HISTORY_FILE = STATE_DIR / "history.jsonl"
REPORTS_DIR = STATE_DIR / "reports"
LOCK_FILE = STATE_DIR / "run.lock"
RESTIC = shutil.which("restic") or "/usr/local/bin/restic"

STATE_LOCK = threading.Lock()
STATE: dict = {}


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def now_epoch() -> int:
    return int(time.time())


def tzinfo() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def stamp(epoch: int | float | None) -> str:
    if not epoch:
        return "never"
    return dt.datetime.fromtimestamp(float(epoch), tzinfo()).strftime(
        "%Y-%m-%d %H:%M %Z"
    )


def month_key(epoch: int | float) -> str:
    return dt.datetime.fromtimestamp(float(epoch), tzinfo()).strftime("%Y-%m")


def next_monthly(now: int | None = None) -> int:
    current = dt.datetime.fromtimestamp(now or now_epoch(), tzinfo())
    last_day = calendar.monthrange(current.year, current.month)[1]
    candidate = current.replace(
        day=min(DAY, last_day),
        hour=HOUR,
        minute=MINUTE,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        last_day = calendar.monthrange(year, month)[1]
        candidate = candidate.replace(
            year=year, month=month, day=min(DAY, last_day)
        )
    return int(candidate.timestamp())


def read_json(path: Path, default: dict | None = None) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(default or {})


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def default_state() -> dict:
    return {
        "last_run": 0,
        "last_success": 0,
        "next_run": 0,
        "result": "never",
        "duration_seconds": 0,
        "rotation": [],
        "repo": "",
        "snapshots": {},
        "checks": [],
        "checks_total": 0,
        "checks_failed": 0,
        "metrics": {},
        "error": "",
        "attempts": 0,
        "manual": False,
        "last_manual": 0,
    }


def load_state() -> dict:
    state = default_state()
    state.update(read_json(STATE_FILE))
    status = read_json(STATUS_FILE)
    if status:
        state.update({k: v for k, v in status.items() if k != "up"})
    return state


def publish_state(state: dict) -> None:
    global STATE
    payload = dict(state)
    payload["up"] = True
    with STATE_LOCK:
        STATE = payload
    write_json_atomic(STATE_FILE, state)
    write_json_atomic(STATUS_FILE, payload)


def current_state() -> dict:
    with STATE_LOCK:
        return dict(STATE)


def acquire_lock() -> int | None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(
        self,
        name: str,
        status: str,
        detail: str = "",
        duration: float | None = None,
    ) -> None:
        detail = " ".join(str(detail).split())
        if len(detail) > 1200:
            detail = detail[:1197] + "..."
        item = {"name": name, "status": status, "detail": detail}
        if duration is not None:
            item["duration_seconds"] = round(duration, 1)
        self.items.append(item)
        log(f"{status.upper():4} {name}" + (f" — {detail}" if detail else ""))

    @property
    def failed(self) -> list[dict]:
        return [item for item in self.items if item["status"] == "fail"]

    @property
    def passed(self) -> list[dict]:
        return [item for item in self.items if item["status"] == "pass"]


def run_cmd(
    args: list[str],
    env: dict | None = None,
    timeout: int = 600,
    cwd: str | None = None,
) -> dict:
    started = time.monotonic()
    try:
        process = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
        return {
            "args": args,
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "duration": time.monotonic() - started,
        }
    except subprocess.TimeoutExpired:
        return {
            "args": args,
            "returncode": 124,
            "stdout": "",
            "stderr": f"timeout after {timeout}s",
            "duration": time.monotonic() - started,
        }
    except FileNotFoundError as error:
        return {
            "args": args,
            "returncode": 127,
            "stdout": "",
            "stderr": str(error),
            "duration": time.monotonic() - started,
        }


def last_line(text: str) -> str:
    for line in reversed((text or "").strip().splitlines()):
        if line.strip():
            return line.strip()
    return ""


def load_config() -> dict:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"cannot read {CONFIG_PATH}: {error}") from error
    if not config.get("repos"):
        raise RuntimeError("Backrest config has no repositories")
    return config


def repo_maps(config: dict) -> tuple[dict, dict, dict, str]:
    repos = {
        str(repo.get("id")): repo
        for repo in (config.get("repos") or [])
        if repo.get("id")
    }
    plan_for = {
        str(plan.get("repo")): str(plan.get("id"))
        for plan in (config.get("plans") or [])
        if str(plan.get("id", "")).endswith("_CoreConfigs")
    }
    heavy_for = {
        str(plan.get("repo")): str(plan.get("id"))
        for plan in (config.get("plans") or [])
        if str(plan.get("id", "")).endswith("_HeavyData")
    }
    return repos, plan_for, heavy_for, str(config.get("instance") or "")


def restic_env(repo_id: str, repo: dict) -> dict:
    env = os.environ.copy()
    env["RESTIC_PASSWORD"] = str(repo.get("password") or "")
    cache = SCRATCH_DIR / "cache" / repo_id
    cache.mkdir(parents=True, exist_ok=True)
    env["RESTIC_CACHE_DIR"] = str(cache)
    env["RCLONE_CONFIG"] = str(RCLONE_CONFIG)
    env["HOME"] = str(SCRATCH_DIR / "home")
    env["TMPDIR"] = str(SCRATCH_DIR / "tmp")
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    return env


def restic(
    repo_id: str,
    repo: dict,
    args: list[str],
    timeout: int,
) -> dict:
    command = [RESTIC, "-r", str(repo.get("uri")), "--no-lock", *args]
    return run_cmd(command, env=restic_env(repo_id, repo), timeout=timeout)


def parse_snapshot_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def select_snapshot(
    snapshots: list[dict],
    plan_id: str,
    expected_paths: list[str],
) -> dict:
    tagged = [
        snapshot
        for snapshot in snapshots
        if f"plan:{plan_id}" in (snapshot.get("tags") or [])
    ]
    if not tagged:
        raise RuntimeError(f"no snapshot tagged plan:{plan_id}")
    tagged.sort(
        key=lambda item: parse_snapshot_time(item.get("time"))
        or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    )
    selected = tagged[-1]
    parsed = parse_snapshot_time(selected.get("time"))
    age = int(time.time() - parsed.timestamp()) if parsed else 0
    paths = list(selected.get("paths") or [])
    missing = [path for path in expected_paths if path not in paths]
    return {
        "id": selected.get("id"),
        "short_id": selected.get("short_id") or str(selected.get("id"))[:8],
        "time": selected.get("time"),
        "age_seconds": max(0, age),
        "paths": paths,
        "missing_paths": missing,
        "plan": plan_id,
        "tags": selected.get("tags") or [],
    }


def tree_metrics(root: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = Path(dirpath) / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            files += 1
            total += stat.st_size
    return files, total


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gzip_size(path: Path) -> int:
    total = 0
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(chunk)
    return total


def sqlite_ok(path: Path) -> bool:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA integrity_check;").fetchone()
        return bool(row and row[0] == "ok")
    finally:
        connection.close()


def parse_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def api_call(method: str, body: dict) -> object:
    if not BACKREST_PASSWORD:
        raise RuntimeError("BACKREST_EXPORTER_PASSWORD is not set")
    auth = base64.b64encode(f"{BACKREST_USER}:{BACKREST_PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        f"{BACKREST_URL}/v1.Backrest/{method}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def check_restic_version(checks: Checks) -> None:
    result = run_cmd([RESTIC, "version"], timeout=30)
    if result["returncode"] == 0 and result["stdout"].startswith("restic 0.19"):
        checks.add("preflight:restic", "pass", last_line(result["stdout"]))
    else:
        checks.add(
            "preflight:restic",
            "fail",
            result["stderr"] or result["stdout"] or "restic not available",
        )


def prepare_rclone(checks: Checks) -> None:
    if not RCLONE_SOURCE.is_file():
        checks.add(
            "preflight:rclone",
            "fail",
            f"rclone config not found at {RCLONE_SOURCE}",
        )
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RCLONE_SOURCE, RCLONE_CONFIG)
    RCLONE_CONFIG.chmod(0o600)
    checks.add("preflight:rclone", "pass", "writable temporary copy")


def check_disk(checks: Checks) -> bool:
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(SCRATCH_DIR)
    free_gb = usage.free / (1024**3)
    if free_gb >= MIN_FREE_GB:
        checks.add(
            "preflight:disk", "pass", f"{free_gb:.1f} GiB free (minimum {MIN_FREE_GB})"
        )
        return True
    checks.add(
        "preflight:disk",
        "fail",
        f"{free_gb:.1f} GiB free, need at least {MIN_FREE_GB} GiB",
    )
    return False


def check_idle(instance: str, checks: Checks) -> None:
    if not instance or not BACKREST_PASSWORD:
        checks.add("preflight:backrest_idle", "skip", "API credentials not configured")
        return
    try:
        operations = api_call(
            "GetOperations", {"selector": {"instanceId": instance}}
        ).get("operations", [])
        current = now_epoch() * 1000
        active = []
        for operation in operations:
            status = str(operation.get("status") or "")
            start = int(operation.get("unixTimeStartMs") or 0)
            if status in ("STATUS_IN_PROGRESS", "STATUS_RUNNING"):
                active.append(operation)
            elif status == "STATUS_PENDING" and start and start <= current:
                active.append(operation)
        if active:
            checks.add(
                "preflight:backrest_idle",
                "fail",
                f"{len(active)} Backrest operation(s) in progress",
            )
        else:
            checks.add("preflight:backrest_idle", "pass", "no active operations")
    except Exception as error:  # API is advisory for this check
        checks.add("preflight:backrest_idle", "skip", str(error))


def validate_manifest(root: Path, checks: Checks) -> None:
    data = root / "data"
    manifest = data / "stack-envs" / "manifest.sha256"
    if not manifest.is_file():
        checks.add("manifest", "fail", "manifest.sha256 missing")
        return
    data_root = data.resolve()
    total = 0
    failures: list[str] = []
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        expected, relative = parts[0], parts[1].strip()
        relative = relative[2:] if relative.startswith("./") else relative.lstrip("/")
        path = (data / relative).resolve()
        if data_root not in path.parents and path != data_root:
            failures.append(f"path escape: {relative}")
            continue
        if not path.is_file():
            failures.append(f"missing: {relative}")
            continue
        if sha256_file(path) != expected:
            failures.append(f"hash mismatch: {relative}")
            continue
        total += 1
    if failures:
        checks.add(
            "manifest",
            "fail",
            f"{len(failures)} failure(s): " + "; ".join(failures[:5]),
        )
    else:
        checks.add("manifest", "pass", f"{total} files verified")


def validate_dbdumps(root: Path, checks: Checks) -> None:
    dbdumps = root / "data" / "dbdumps"
    if not dbdumps.is_dir():
        checks.add("dbdumps", "fail", "dbdumps directory missing")
        return

    required = {
        "appflowy-postgres.sql.gz": 1_000_000,
        "nextcloud-postgres.dump": 100_000,
        "romm-mariadb.sql.gz": 1_000_000,
        "komodo-mongo.archive.gz": 1_000_000,
    }
    missing = []
    for name, minimum in required.items():
        path = dbdumps / name
        if not path.is_file() or path.stat().st_size < minimum:
            missing.append(name)
    if missing:
        checks.add("dbdumps:files", "fail", "missing or too small: " + ", ".join(missing))
    else:
        checks.add("dbdumps:files", "pass", f"{len(required)} dumps present")

    gz_failures = []
    for path in sorted(dbdumps.glob("*.gz")):
        try:
            size = gzip_size(path)
            if size <= 0:
                gz_failures.append(f"{path.name}: empty")
        except (OSError, EOFError, gzip.BadGzipFile) as error:
            gz_failures.append(f"{path.name}: {error}")
    if gz_failures:
        checks.add("dbdumps:gzip", "fail", "; ".join(gz_failures[:5]))
    else:
        checks.add("dbdumps:gzip", "pass", "all gzip archives decompress")

    sqlite_dir = dbdumps / "sqlite"
    sqlite_files = sorted(sqlite_dir.glob("*.sqlite")) if sqlite_dir.is_dir() else []
    bad_sqlite = []
    for path in sqlite_files:
        try:
            if not sqlite_ok(path):
                bad_sqlite.append(path.name)
        except sqlite3.Error as error:
            bad_sqlite.append(f"{path.name}: {error}")
    expected_sqlite = 8
    if len(sqlite_files) < expected_sqlite:
        bad_sqlite.append(f"only {len(sqlite_files)} of {expected_sqlite} sqlite dumps")
    if bad_sqlite:
        checks.add("dbdumps:sqlite", "fail", "; ".join(bad_sqlite[:5]))
    else:
        checks.add("dbdumps:sqlite", "pass", f"{len(sqlite_files)} databases ok")

    nextcloud = dbdumps / "nextcloud-postgres.dump"
    if nextcloud.is_file():
        result = run_cmd(["pg_restore", "--list", str(nextcloud)], timeout=120)
        if result["returncode"] == 0 and ";" in result["stdout"]:
            checks.add("dbdumps:postgres", "pass", "Nextcloud pg_restore --list ok")
        else:
            checks.add(
                "dbdumps:postgres",
                "fail",
                last_line(result["stderr"] or result["stdout"]),
            )
    else:
        checks.add("dbdumps:postgres", "fail", "Nextcloud dump missing")

    appflowy = dbdumps / "appflowy-postgres.sql.gz"
    if appflowy.is_file():
        try:
            with gzip.open(appflowy, "rb") as handle:
                head = handle.read(256 * 1024).decode("utf-8", "replace")
            marker = "PostgreSQL database dump" in head or "CREATE DATABASE" in head
            checks.add(
                "dbdumps:appflowy",
                "pass" if marker else "fail",
                "PostgreSQL dump marker found" if marker else "expected SQL marker missing",
            )
        except (OSError, EOFError, gzip.BadGzipFile) as error:
            checks.add("dbdumps:appflowy", "fail", str(error))

    romm = dbdumps / "romm-mariadb.sql.gz"
    if romm.is_file():
        try:
            with gzip.open(romm, "rb") as handle:
                head = handle.read(256 * 1024).decode("utf-8", "replace")
            marker = "MariaDB dump" in head or "CREATE DATABASE" in head
            checks.add(
                "dbdumps:mariadb",
                "pass" if marker else "fail",
                "MariaDB dump marker found" if marker else "expected SQL marker missing",
            )
        except (OSError, EOFError, gzip.BadGzipFile) as error:
            checks.add("dbdumps:mariadb", "fail", str(error))

    vaultwarden = dbdumps / "vaultwarden-data"
    vw_missing = [
        name
        for name in ("config.json", "rsa_key.pem")
        if not (vaultwarden / name).is_file()
    ]
    if vw_missing:
        checks.add("dbdumps:vaultwarden", "fail", "missing: " + ", ".join(vw_missing))
    else:
        try:
            json.loads((vaultwarden / "config.json").read_text(encoding="utf-8"))
            checks.add("dbdumps:vaultwarden", "pass", "keys and config present")
        except ValueError as error:
            checks.add("dbdumps:vaultwarden", "fail", f"config.json: {error}")


def validate_configuration(root: Path, checks: Checks) -> int:
    data = root / "data"
    stack_root = data / "stack-envs" / "opt" / "stacks"
    env_files = sorted(stack_root.rglob(".env")) if stack_root.is_dir() else []
    keys: dict[str, str] = {}
    for path in env_files:
        try:
            keys.update(parse_env(path))
        except OSError:
            continue
    missing_keys = [key for key in REQUIRED_ENV_KEYS if not keys.get(key)]
    if len(env_files) < 10:
        checks.add(
            "config:stack_envs",
            "fail",
            f"only {len(env_files)} stack .env files found",
        )
    elif missing_keys:
        checks.add(
            "config:stack_envs",
            "fail",
            "missing required keys: " + ", ".join(missing_keys),
        )
    else:
        checks.add("config:stack_envs", "pass", f"{len(env_files)} files")

    alertmanager = data / "home-config" / "alertmanager-telegram.local.yml"
    if not alertmanager.is_file():
        checks.add("config:telegram", "fail", "alertmanager config missing")
    elif yaml is None:
        checks.add("config:telegram", "skip", "PyYAML not available")
    else:
        try:
            document = yaml.safe_load(alertmanager.read_text(encoding="utf-8")) or {}
            telegram = []
            for receiver in document.get("receivers") or []:
                telegram.extend(receiver.get("telegram_configs") or [])
            if telegram and telegram[0].get("bot_token") and telegram[0].get("chat_id"):
                checks.add("config:telegram", "pass", "bot token and chat id present")
            else:
                checks.add("config:telegram", "fail", "telegram receiver incomplete")
        except Exception as error:
            checks.add("config:telegram", "fail", str(error))

    ssh_dir = data / "home-config" / ".ssh"
    private_keys = [
        path
        for path in ssh_dir.glob("*")
        if path.is_file() and not path.name.endswith(".pub")
    ] if ssh_dir.is_dir() else []
    bad_modes = [
        path.name
        for path in private_keys
        if (path.stat().st_mode & 0o077) != 0
    ]
    if len(private_keys) >= 2 and not bad_modes:
        checks.add("config:ssh", "pass", f"{len(private_keys)} private keys, mode 600")
    else:
        checks.add(
            "config:ssh",
            "fail",
            f"{len(private_keys)} private keys; bad modes: {', '.join(bad_modes) or 'none'}",
        )

    git_head = data / "stack-envs" / "git-head.txt"
    if git_head.is_file():
        values = parse_env(git_head)
        commit = values.get("commit", "")
        if len(commit) == 40 and all(c in "0123456789abcdef" for c in commit.lower()):
            checks.add("config:git", "pass", f"HEAD {commit[:12]}")
        else:
            checks.add("config:git", "fail", "git-head.txt has no valid commit")
    else:
        checks.add("config:git", "skip", "git-head.txt not staged")

    host = data / "host-config"
    host_files = [path for path in host.rglob("*") if path.is_file()]
    required_host = ["fstab", "hosts", "ssh/sshd_config"]
    host_missing = [
        name for name in required_host if not (host / name).is_file()
    ]
    if len(host_files) >= 10 and not host_missing:
        checks.add("config:host", "pass", f"{len(host_files)} files")
    else:
        checks.add(
            "config:host",
            "fail",
            f"{len(host_files)} files; missing: {', '.join(host_missing) or 'none'}",
        )

    homelab = root / "backup" / "homelab"
    compose_files = sorted(homelab.rglob("docker-compose*.yml"))
    if yaml is None:
        checks.add("config:compose", "skip", "PyYAML not available")
    else:
        bad = []
        for path in compose_files:
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as error:
                bad.append(f"{path.name}: {error}")
        if len(compose_files) < 5 or bad:
            checks.add(
                "config:compose",
                "fail",
                f"{len(compose_files)} files; " + "; ".join(bad[:3]),
            )
        else:
            checks.add("config:compose", "pass", f"{len(compose_files)} Compose files parse")

    headscale = root / "backup" / "opt" / "core" / "headscale" / "config" / "config.yaml"
    if headscale.is_file() and yaml is not None:
        try:
            yaml.safe_load(headscale.read_text(encoding="utf-8"))
            checks.add("config:headscale", "pass", "config.yaml parses")
        except Exception as error:
            checks.add("config:headscale", "fail", str(error))

    komodo_env = root / "backup" / "opt" / "core" / "komodo" / ".env"
    if komodo_env.is_file():
        komodo_keys = parse_env(komodo_env)
        required = [key for key in ("KOMODO_PASSKEY", "KOMODO_JWT_SECRET") if not komodo_keys.get(key)]
        checks.add(
            "config:komodo",
            "fail" if required else "pass",
            "missing: " + ", ".join(required) if required else "secrets present",
        )

    return len(env_files)


def validate_secrets(root: Path, checks: Checks) -> None:
    docker_volumes = root / "backup" / "docker_volumes"
    backrest_config = docker_volumes / "backrest_config" / "_data" / "config.json"
    if backrest_config.is_file():
        try:
            config = json.loads(backrest_config.read_text(encoding="utf-8"))
            ok = bool(config.get("repos")) and bool(config.get("plans"))
            checks.add(
                "secrets:backrest",
                "pass" if ok else "fail",
                "repos and plans present" if ok else "repos/plans missing",
            )
        except ValueError as error:
            checks.add("secrets:backrest", "fail", str(error))
    else:
        checks.add("secrets:backrest", "fail", "backrest config missing")

    for name, relative in (
        ("npm", docker_volumes / "npm_data" / "_data" / "database.sqlite"),
        ("headscale", docker_volumes / "headscale_data" / "_data" / "db.sqlite"),
    ):
        if not relative.is_file():
            checks.add(f"secrets:{name}", "fail", "database missing")
            continue
        try:
            ok = sqlite_ok(relative)
            checks.add(
                f"secrets:{name}",
                "pass" if ok else "fail",
                "sqlite integrity ok" if ok else "sqlite corruption",
            )
        except sqlite3.Error as error:
            checks.add(f"secrets:{name}", "fail", str(error))

    cert_dir = docker_volumes / "npm_letsencrypt" / "_data" / "live"
    certs = list(cert_dir.glob("*/fullchain.pem")) if cert_dir.is_dir() else []
    checks.add(
        "secrets:tls",
        "pass" if certs else "skip",
        f"{len(certs)} certificate(s)" if certs else "no live certificates found",
    )


def validate_heavy(root: Path, checks: Checks) -> tuple[int, int]:
    data = root / "backup" / "srv" / "nextcloud_data"
    if not data.is_dir():
        checks.add("heavy:nextcloud", "fail", "nextcloud_data directory missing")
        return 0, 0
    files, size = tree_metrics(data)
    if files >= 100 and size >= 100 * 1024 * 1024:
        checks.add(
            "heavy:nextcloud",
            "pass",
            f"{files} files, {size / (1024**3):.2f} GiB",
        )
    else:
        checks.add(
            "heavy:nextcloud",
            "fail",
            f"{files} files, {size / (1024**2):.1f} MiB",
        )
    return files, size


def prune_reports() -> None:
    reports = sorted(REPORTS_DIR.glob("report-*.md"))
    for path in reports[:-KEEP_REPORTS] if KEEP_REPORTS > 0 else []:
        try:
            path.unlink()
        except OSError:
            pass


def write_report(status: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    moment = dt.datetime.fromtimestamp(status["last_run"], tzinfo()).strftime(
        "%Y%m%d-%H%M%S"
    )
    path = REPORTS_DIR / f"report-{moment}.md"
    lines = [
        f"# Backup verification report — {stamp(status['last_run'])}",
        "",
        f"- Result: **{status['result'].upper()}**",
        f"- Duration: {status['duration_seconds']}s",
        f"- Rotation: {', '.join(status.get('rotation') or []) or 'n/a'}",
        f"- Remote restored: {status.get('repo') or 'n/a'}",
        f"- Snapshots: {json.dumps(status.get('snapshots') or {}, sort_keys=True)}",
        f"- Metrics: {json.dumps(status.get('metrics') or {}, sort_keys=True)}",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for item in status.get("checks") or []:
        detail = str(item.get("detail") or "").replace("|", "\\|")
        lines.append(f"| `{item['name']}` | {item['status']} | {detail} |")
    if status.get("error"):
        lines.extend(["", f"**Error:** {status['error']}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    prune_reports()
    return path


def run_drill(
    manual: bool = False,
    repos_override: list[str] | None = None,
    skip_heavy: bool = False,
    no_restore: bool = False,
    restore_paths: list[str] | None = None,
) -> dict:
    started = now_epoch()
    clock = time.monotonic()
    checks = Checks()
    snapshots: dict = {}
    restored_bytes = 0
    restored_files = 0
    config_files = 0
    rotation: list[str] = []
    selected_remote = ""
    severe_error = ""
    previous = load_state()

    log(f"drill start (manual={manual}, no_restore={no_restore})")
    try:
        config = load_config()
        repos, plan_for, heavy_for, instance = repo_maps(config)
        check_restic_version(checks)
        prepare_rclone(checks)
        if not check_disk(checks):
            raise RuntimeError("not enough scratch space")
        check_idle(instance, checks)
        shutil.rmtree(SCRATCH_DIR / "run", ignore_errors=True)

        rotation = [repo for repo in ROTATION if repo in repos]
        if not rotation:
            raise RuntimeError("no configured remote repositories for rotation")
        month = dt.datetime.now(tzinfo()).month
        selected_remote = rotation[month % len(rotation)]
        default_repos = ["local-repo-srv", selected_remote]
        restore_repos = repos_override or default_repos
        restore_repos = list(dict.fromkeys(repo for repo in restore_repos if repo))
        unknown = [repo for repo in restore_repos if repo not in repos]
        if unknown:
            raise RuntimeError("unknown repository: " + ", ".join(unknown))
        if "local-repo-srv" not in repos:
            raise RuntimeError("local-repo-srv is not configured")

        for repo_id in sorted(repos):
            repo = repos[repo_id]
            checks.add(f"repo_check:{repo_id}", "skip", "starting")
            result = restic(
                repo_id,
                repo,
                ["check", f"--read-data-subset={READ_DATA_PERCENT}%"],
                CHECK_TIMEOUT,
            )
            checks.items = [
                item
                for item in checks.items
                if item["name"] != f"repo_check:{repo_id}"
            ]
            checks.add(
                f"repo_check:{repo_id}",
                "pass" if result["returncode"] == 0 else "fail",
                last_line(result["stdout"] or result["stderr"]),
                result["duration"],
            )

        for repo_id in restore_repos:
            repo = repos[repo_id]
            plan_id = plan_for.get(repo_id)
            if not plan_id:
                checks.add(f"snapshot:{repo_id}:core", "fail", "no Core plan")
                continue
            snapshot_result = restic(
                repo_id, repo, ["snapshots", "--json"], 600
            )
            if snapshot_result["returncode"] != 0:
                checks.add(
                    f"snapshot:{repo_id}:core",
                    "fail",
                    last_line(snapshot_result["stderr"]),
                )
                continue
            try:
                snapshots_list = json.loads(snapshot_result["stdout"])
                snapshot = select_snapshot(snapshots_list, plan_id, CORE_PATHS)
            except Exception as error:
                checks.add(f"snapshot:{repo_id}:core", "fail", str(error))
                continue
            snapshots.setdefault(repo_id, {})["core"] = {
                "id": snapshot["id"],
                "short_id": snapshot["short_id"],
                "time": snapshot["time"],
                "age_seconds": snapshot["age_seconds"],
            }
            age_ok = snapshot["age_seconds"] <= MAX_SNAPSHOT_AGE_HOURS * 3600
            if snapshot["missing_paths"]:
                checks.add(
                    f"snapshot:{repo_id}:core",
                    "fail",
                    "missing paths: " + ", ".join(snapshot["missing_paths"]),
                )
            elif not age_ok:
                checks.add(
                    f"snapshot:{repo_id}:core",
                    "fail",
                    f"snapshot is {snapshot['age_seconds'] // 3600}h old",
                )
            else:
                checks.add(
                    f"snapshot:{repo_id}:core",
                    "pass",
                    f"{snapshot['short_id']} · {snapshot['age_seconds'] // 3600}h old",
                )
            if no_restore:
                continue

            target = SCRATCH_DIR / "run" / repo_id / "core"
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            restore_args = [
                "restore",
                snapshot["id"],
                "--target",
                str(target),
                "--verify",
            ]
            for include in restore_paths or RESTORE_PATHS:
                restore_args.extend(["--include", include])
            result = restic(
                repo_id,
                repo,
                restore_args,
                RESTORE_TIMEOUT,
            )
            if result["returncode"] != 0:
                checks.add(
                    f"restore:{repo_id}:core",
                    "fail",
                    last_line(result["stderr"] or result["stdout"]),
                    result["duration"],
                )
                shutil.rmtree(target, ignore_errors=True)
                continue
            files, size = tree_metrics(target)
            restored_files += files
            restored_bytes += size
            checks.add(
                f"restore:{repo_id}:core",
                "pass",
                f"{files} files, {size / (1024**3):.2f} GiB",
                result["duration"],
            )
            validate_manifest(target, checks)
            validate_dbdumps(target, checks)
            config_files = max(config_files, validate_configuration(target, checks))
            validate_secrets(target, checks)
            shutil.rmtree(target, ignore_errors=True)

        if (
            selected_remote
            and selected_remote in restore_repos
            and not skip_heavy
            and selected_remote in heavy_for
        ):
            repo = repos[selected_remote]
            plan_id = heavy_for[selected_remote]
            snapshot_result = restic(
                selected_remote, repo, ["snapshots", "--json"], 600
            )
            if snapshot_result["returncode"] != 0:
                checks.add(
                    f"snapshot:{selected_remote}:heavy",
                    "fail",
                    last_line(snapshot_result["stderr"]),
                )
            else:
                try:
                    snapshots_list = json.loads(snapshot_result["stdout"])
                    snapshot = select_snapshot(
                        snapshots_list, plan_id, HEAVY_PATHS
                    )
                    snapshots.setdefault(selected_remote, {})["heavy"] = {
                        "id": snapshot["id"],
                        "short_id": snapshot["short_id"],
                        "time": snapshot["time"],
                        "age_seconds": snapshot["age_seconds"],
                    }
                    age_ok = (
                        snapshot["age_seconds"] <= MAX_SNAPSHOT_AGE_HOURS * 3600
                    )
                    if snapshot["missing_paths"] or not age_ok:
                        checks.add(
                            f"snapshot:{selected_remote}:heavy",
                            "fail",
                            "missing paths or stale snapshot",
                        )
                    else:
                        checks.add(
                            f"snapshot:{selected_remote}:heavy",
                            "pass",
                            f"{snapshot['short_id']} · {snapshot['age_seconds'] // 3600}h old",
                        )
                    if not no_restore:
                        target = SCRATCH_DIR / "run" / selected_remote / "heavy"
                        shutil.rmtree(target, ignore_errors=True)
                        target.mkdir(parents=True, exist_ok=True)
                        result = restic(
                            selected_remote,
                            repo,
                            [
                                "restore",
                                snapshot["id"],
                                "--target",
                                str(target),
                                "--verify",
                            ],
                            RESTORE_TIMEOUT,
                        )
                        if result["returncode"] != 0:
                            checks.add(
                                f"restore:{selected_remote}:heavy",
                                "fail",
                                last_line(result["stderr"] or result["stdout"]),
                                result["duration"],
                            )
                        else:
                            files, size = validate_heavy(target, checks)
                            restored_files += files
                            restored_bytes += size
                            checks.add(
                                f"restore:{selected_remote}:heavy",
                                "pass",
                                f"{files} files, {size / (1024**3):.2f} GiB",
                                result["duration"],
                            )
                        shutil.rmtree(target, ignore_errors=True)
                except Exception as error:
                    checks.add(
                        f"snapshot:{selected_remote}:heavy", "fail", str(error)
                    )
    except Exception as error:
        severe_error = str(error)
        checks.add("drill", "fail", severe_error)
    finally:
        duration = int(time.monotonic() - clock)
        failures = checks.failed
        result = "pass" if not failures else "fail"
        previous_success = int(previous.get("last_success") or 0)
        attempts = int(previous.get("attempts") or 0)
        if result == "pass":
            attempts = 0
            last_success = started
        else:
            last_success = previous_success
            attempts += 1
        if manual:
            next_run = int(previous.get("next_run") or 0)
            if next_run <= now_epoch():
                next_run = next_monthly()
        elif result == "pass":
            next_run = next_monthly()
        elif attempts < MAX_RETRIES:
            next_run = now_epoch() + RETRY_HOURS * 3600
        else:
            next_run = next_monthly()
            attempts = 0
        status = {
            "up": True,
            "result": result,
            "last_run": started,
            "last_success": last_success,
            "next_run": next_run,
            "duration_seconds": duration,
            "rotation": rotation,
            "repo": selected_remote,
            "snapshots": snapshots,
            "checks": checks.items,
            "checks_total": len(checks.items),
            "checks_failed": len(failures),
            "metrics": {
                "restored_bytes": restored_bytes,
                "restored_files": restored_files,
                "read_data_percent": READ_DATA_PERCENT,
                "config_files": config_files,
            },
            "error": severe_error or (failures[0]["detail"] if failures else ""),
            "attempts": attempts,
            "manual": manual,
            "last_manual": started if manual else int(previous.get("last_manual") or 0),
        }
        publish_state(status)
        path = write_report(status)
        with HISTORY_FILE.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": started,
                        "result": result,
                        "duration_seconds": duration,
                        "checks": len(checks.items),
                        "failed": len(failures),
                        "repo": selected_remote,
                        "report": path.name,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        log(
            f"drill finished: {result.upper()} in {duration}s, "
            f"{len(failures)} failed check(s), report {path.name}"
        )
        shutil.rmtree(SCRATCH_DIR / "run", ignore_errors=True)
        shutil.rmtree(SCRATCH_DIR / "cache", ignore_errors=True)
        return status


def render_metrics() -> str:
    state = current_state()
    result = str(state.get("result") or "never")
    success = 1 if result == "pass" else 0
    metrics = state.get("metrics") or {}
    lines = [
        "# HELP backrest_verify_up Whether the verification service is running.",
        "# TYPE backrest_verify_up gauge",
        "backrest_verify_up 1",
        "# HELP backrest_verify_last_run_timestamp_seconds Last drill start time.",
        "# TYPE backrest_verify_last_run_timestamp_seconds gauge",
        f"backrest_verify_last_run_timestamp_seconds {int(state.get('last_run') or 0)}",
        "# HELP backrest_verify_last_success_timestamp_seconds Last PASS.",
        "# TYPE backrest_verify_last_success_timestamp_seconds gauge",
        f"backrest_verify_last_success_timestamp_seconds {int(state.get('last_success') or 0)}",
        "# HELP backrest_verify_next_run_timestamp_seconds Next scheduled drill.",
        "# TYPE backrest_verify_next_run_timestamp_seconds gauge",
        f"backrest_verify_next_run_timestamp_seconds {int(state.get('next_run') or 0)}",
        "# HELP backrest_verify_success Whether the last drill passed.",
        "# TYPE backrest_verify_success gauge",
        f"backrest_verify_success {success}",
        "# HELP backrest_verify_duration_seconds Last drill duration.",
        "# TYPE backrest_verify_duration_seconds gauge",
        f"backrest_verify_duration_seconds {int(state.get('duration_seconds') or 0)}",
        "# HELP backrest_verify_checks_total Checks in the last drill.",
        "# TYPE backrest_verify_checks_total gauge",
        f"backrest_verify_checks_total {int(state.get('checks_total') or 0)}",
        "# HELP backrest_verify_checks_failed Failed checks in the last drill.",
        "# TYPE backrest_verify_checks_failed gauge",
        f"backrest_verify_checks_failed {int(state.get('checks_failed') or 0)}",
        "# HELP backrest_verify_restored_bytes Bytes restored in the last drill.",
        "# TYPE backrest_verify_restored_bytes gauge",
        f"backrest_verify_restored_bytes {int(metrics.get('restored_bytes') or 0)}",
        "# HELP backrest_verify_restored_files Files restored in the last drill.",
        "# TYPE backrest_verify_restored_files gauge",
        f"backrest_verify_restored_files {int(metrics.get('restored_files') or 0)}",
        "# HELP backrest_verify_read_data_percent Read-data subset percentage.",
        "# TYPE backrest_verify_read_data_percent gauge",
        f"backrest_verify_read_data_percent {READ_DATA_PERCENT}",
        "# HELP backrest_verify_config_files Staged stack .env files.",
        "# TYPE backrest_verify_config_files gauge",
        f"backrest_verify_config_files {int(metrics.get('config_files') or 0)}",
        "# HELP backrest_verify_snapshot_age_seconds Selected snapshot age.",
        "# TYPE backrest_verify_snapshot_age_seconds gauge",
    ]
    for repo_id, kinds in (state.get("snapshots") or {}).items():
        for kind, snapshot in (kinds or {}).items():
            age = int((snapshot or {}).get("age_seconds") or 0)
            lines.append(
                f'backrest_verify_snapshot_age_seconds{{repo="{repo_id}",kind="{kind}"}} {age}'
            )
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/metrics":
            body = render_metrics().encode()
            content_type = "text/plain; version=0.0.4"
        elif self.path == "/status":
            body = json.dumps(current_state(), separators=(",", ":")).encode()
            content_type = "application/json"
        elif self.path == "/healthz":
            body = b"ok\n"
            content_type = "text/plain"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return


def scheduler_loop() -> None:
    if not ENABLED:
        log("scheduler disabled by BACKREST_VERIFY_ENABLED; HTTP endpoints stay up")
        while True:
            time.sleep(3600)
    state = load_state()
    if not state.get("next_run"):
        state["next_run"] = next_monthly()
        publish_state(state)
    log(f"next drill: {stamp(state['next_run'])}")
    while True:
        state = load_state()
        current = current_state()
        if any(
            state.get(key) != current.get(key)
            for key in (
                "last_run",
                "last_success",
                "next_run",
                "result",
                "checks_total",
                "checks_failed",
            )
        ):
            # A manual run may have written status.json from a separate
            # process (for example a one-off drill); reflect it in /status.
            publish_state(state)
        now = now_epoch()
        next_run = int(state.get("next_run") or 0)
        if next_run and now >= next_run:
            fd = acquire_lock()
            if fd is None:
                log("another drill is running; skipping this slot")
                time.sleep(300)
                continue
            try:
                run_drill(manual=False)
            finally:
                release_lock(fd)
        time.sleep(30)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backrest restore verification")
    parser.add_argument("--run-now", action="store_true", help="run one drill and exit")
    parser.add_argument(
        "--repos",
        help="comma-separated repository IDs to restore (default: local + rotated remote)",
    )
    parser.add_argument(
        "--skip-heavy", action="store_true", help="skip the HeavyData restore"
    )
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="run repository checks and snapshot coverage only",
    )
    parser.add_argument(
        "--paths",
        help="comma-separated restore includes (testing; default: full snapshot)",
    )
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    publish_state(load_state())

    if args.run_now:
        fd = acquire_lock()
        if fd is None:
            log("a drill is already running")
            return 1
        try:
            overrides = (
                [item.strip() for item in args.repos.split(",") if item.strip()]
                if args.repos
                else None
            )
            paths = (
                [item.strip() for item in args.paths.split(",") if item.strip()]
                if args.paths
                else None
            )
            status = run_drill(
                manual=True,
                repos_override=overrides,
                skip_heavy=args.skip_heavy,
                no_restore=args.no_restore,
                restore_paths=paths,
            )
            print(json.dumps(status, indent=2))
            return 0 if status["result"] == "pass" else 1
        finally:
            release_lock(fd)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"listening on :{PORT}; scheduling day {DAY} at {HOUR:02d}:{MINUTE:02d} {TIMEZONE}")
    scheduler_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
