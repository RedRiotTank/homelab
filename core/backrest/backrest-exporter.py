#!/usr/bin/env python3
"""Expose Backrest plan status as Prometheus metrics and JSON.

Backrest's own API requires authentication. This small exporter keeps the
credentials on the internal network, exposes an unauthenticated /metrics
endpoint for Prometheus, and a /status endpoint for the Telegram bot.

Environment:
  BACKREST_URL                  default http://backrest:9898
  BACKREST_EXPORTER_USER        default prometheus
  BACKREST_EXPORTER_PASSWORD    required
  BACKREST_STALE_SECONDS        default 129600 (36 hours)
  REFRESH_SECONDS               default 60
  EXPORTER_PORT                 default 9797
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BACKREST_URL = os.environ.get("BACKREST_URL", "http://backrest:9898").rstrip("/")
USER = os.environ.get("BACKREST_EXPORTER_USER", "prometheus")
PASSWORD = os.environ.get("BACKREST_EXPORTER_PASSWORD", "")
STALE_SECONDS = int(os.environ.get("BACKREST_STALE_SECONDS", "129600"))
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "60"))
PORT = int(os.environ.get("EXPORTER_PORT", "9797"))

STATE: dict = {"up": False, "error": "not refreshed", "plans": [], "repos": [], "last_refresh": 0}
LOCK = threading.Lock()


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def backrest_call(method: str, body: dict | None = None) -> object:
    if not PASSWORD:
        raise RuntimeError("BACKREST_EXPORTER_PASSWORD is not set")
    auth = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    data = json.dumps(body or {}).encode()
    request = urllib.request.Request(
        f"{BACKREST_URL}/v1.Backrest/{method}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_status(value: object) -> str:
    text = str(value or "").upper()
    if "SUCCESS" in text:
        return "success"
    if "WARNING" in text:
        return "warning"
    if "ERROR" in text or "FAIL" in text:
        return "failed"
    if "CANCEL" in text:
        return "cancelled"
    return "unknown"


def collect() -> dict:
    summary = backrest_call("GetSummaryDashboard")
    config = backrest_call("GetConfig")
    now = time.time()

    plan_repo = {
        str(plan.get("id")): str(plan.get("repo") or "")
        for plan in (config.get("plans") or [])
    }
    repo_uri = {
        str(repo.get("id")): str(repo.get("uri") or "")
        for repo in (config.get("repos") or [])
    }

    plans: list[dict] = []
    for plan in summary.get("planSummaries") or []:
        plan_id = str(plan.get("id") or "unknown")
        repo_id = plan_repo.get(plan_id, "")
        recent = plan.get("recentBackups") or {}
        timestamps = [as_int(value) for value in (recent.get("timestampMs") or [])]
        statuses = list(recent.get("status") or [])
        pairs = sorted(zip(timestamps, statuses), key=lambda pair: pair[0])
        last_timestamp = pairs[-1][0] if pairs else 0
        last_status = normalize_status(pairs[-1][1]) if pairs else "unknown"
        successful = [
            timestamp
            for timestamp, status in pairs
            if normalize_status(status) in ("success", "warning")
        ]
        last_success = max(successful) if successful else 0
        age = max(0, int(now - last_success / 1000)) if last_success else None
        stale = bool(last_success and age is not None and age > STALE_SECONDS)
        no_backup = not bool(last_success)
        plans.append(
            {
                "id": plan_id,
                "repo": repo_id,
                "repo_uri": repo_uri.get(repo_id, ""),
                "last_backup": int(last_timestamp / 1000) if last_timestamp else 0,
                "last_success": int(last_success / 1000) if last_success else 0,
                "last_status": last_status,
                "last_backup_failed": 1 if last_status == "failed" else 0,
                "last_backup_warning": 1 if last_status == "warning" else 0,
                "success_30d": as_int(plan.get("backupsSuccessLast30days")),
                "failed_30d": as_int(plan.get("backupsFailed30days")),
                "next_backup": int(as_int(plan.get("nextBackupTimeMs")) / 1000),
                "stale": 1 if stale else 0,
                "no_backup": 1 if no_backup else 0,
            }
        )

    repos: list[dict] = []
    for repo in summary.get("repoSummaries") or []:
        repo_id = str(repo.get("id") or "unknown")
        repos.append(
            {
                "id": repo_id,
                "uri": repo_uri.get(repo_id, ""),
                "success_30d": as_int(repo.get("backupsSuccessLast30days")),
                "failed_30d": as_int(repo.get("backupsFailed30days")),
            }
        )

    return {
        "up": True,
        "error": "",
        "last_refresh": int(now),
        "plans": plans,
        "repos": repos,
    }


def refresh() -> None:
    global STATE
    try:
        new_state = collect()
        with LOCK:
            STATE = new_state
        log(f"refreshed {len(new_state['plans'])} plans")
    except Exception as error:
        with LOCK:
            STATE = {
                "up": False,
                "error": str(error),
                "last_refresh": int(time.time()),
                "plans": STATE.get("plans", []),
                "repos": STATE.get("repos", []),
            }
        log(f"refresh failed: {error}")


def refresh_loop() -> None:
    while True:
        refresh()
        time.sleep(max(10, REFRESH_SECONDS))


def label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_metrics() -> str:
    with LOCK:
        state = dict(STATE)
    lines = [
        "# HELP backrest_up Whether the Backrest API was reachable.",
        "# TYPE backrest_up gauge",
        f"backrest_up {1 if state.get('up') else 0}",
        "# HELP backrest_last_refresh_timestamp_seconds Last successful refresh time.",
        "# TYPE backrest_last_refresh_timestamp_seconds gauge",
        f"backrest_last_refresh_timestamp_seconds {state.get('last_refresh', 0)}",
    ]
    for plan in state.get("plans", []):
        labels = f'plan_id="{label(plan["id"])}",repo_id="{label(plan["repo"])}"'
        metrics = {
            "backrest_plan_last_backup_timestamp_seconds": plan["last_backup"],
            "backrest_plan_last_success_timestamp_seconds": plan["last_success"],
            "backrest_plan_last_backup_failed": plan["last_backup_failed"],
            "backrest_plan_last_backup_warning": plan["last_backup_warning"],
            "backrest_plan_backups_success_30d": plan["success_30d"],
            "backrest_plan_backups_failed_30d": plan["failed_30d"],
            "backrest_plan_next_backup_timestamp_seconds": plan["next_backup"],
            "backrest_plan_stale": plan["stale"],
            "backrest_plan_no_backup": plan["no_backup"],
        }
        for name, value in metrics.items():
            lines.append(f"{name}{{{labels}}} {value}")
    for repo in state.get("repos", []):
        labels = f'repo_id="{label(repo["id"])}"'
        lines.append(
            f"backrest_repo_backups_success_30d{{{labels}}} {repo['success_30d']}"
        )
        lines.append(
            f"backrest_repo_backups_failed_30d{{{labels}}} {repo['failed_30d']}"
        )
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/metrics":
            body = render_metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/status":
            with LOCK:
                body = json.dumps(STATE, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:
        return


def main() -> None:
    if "--test" in __import__("sys").argv:
        print(json.dumps(collect(), indent=2))
        return
    refresh()
    threading.Thread(target=refresh_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
