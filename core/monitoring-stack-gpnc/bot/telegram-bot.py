#!/usr/bin/env python3
"""Read-only Telegram bot for Prometheus Alertmanager.

It uses the Telegram Bot API long polling, so it needs no inbound port or
public domain. The bot token and default chat ID are read from the active
Alertmanager config file, which avoids duplicating secrets in the stack
environment.

Commands:
  /start, /help, /alerts, /silences, /status, /id, /backups, /verify
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TELEGRAM_API = os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")
ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093").rstrip("/")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/")
BACKREST_STATUS_URL = os.environ.get(
    "BACKREST_STATUS_URL", "http://backrest-exporter:9797/status"
).rstrip("/")
BACKREST_VERIFY_STATUS_URL = os.environ.get(
    "BACKREST_VERIFY_STATUS_URL", "http://backrest-verify:9798/status"
).rstrip("/")
CONFIG_FILE = os.environ.get("BOT_CONFIG_FILE", "/config/alertmanager.yml")
ALLOWED_ENV = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
NODE_NAMES_ENV = os.environ.get("NODE_DISPLAY_NAMES", "")
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "50"))

NODE_NAMES: dict[str, str] = {}
for item in (part.strip() for part in NODE_NAMES_ENV.split(",")):
    if ":" in item:
        key, value = item.split(":", 1)
        if key.strip() and value.strip():
            NODE_NAMES[key.strip()] = value.strip()


def log(message: str) -> None:
    print(message, flush=True)


def read_telegram_settings() -> tuple[str, int]:
    try:
        text = open(CONFIG_FILE, encoding="utf-8").read()
    except OSError as error:
        sys.exit(f"cannot read {CONFIG_FILE}: {error}")

    token_match = re.search(r"bot_token:\s*'([^']+)'", text) or re.search(
        r'bot_token:\s*"([^"]+)"', text
    )
    chat_match = re.search(r"chat_id:\s*(-?\d+)", text)
    if not token_match or not chat_match:
        sys.exit(
            f"{CONFIG_FILE} does not define a Telegram bot_token and chat_id; "
            "enable the telegram-bot profile only with a Telegram config."
        )
    return token_match.group(1).strip(), int(chat_match.group(1))


TOKEN, DEFAULT_CHAT_ID = read_telegram_settings()
ALLOWED_CHATS = {
    int(item.strip()) for item in ALLOWED_ENV.split(",") if item.strip()
} or {DEFAULT_CHAT_ID}


def telegram(method: str, params: dict, timeout: int = 65) -> dict:
    url = f"{TELEGRAM_API}/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def alertmanager(path: str) -> object:
    request = urllib.request.Request(f"{ALERTMANAGER_URL}{path}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def prometheus(query: str) -> list[dict]:
    url = f"{PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(query)}"
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode())
    return (payload.get("data") or {}).get("result") or []


def escape(value: object) -> str:
    return html.escape(str(value or ""))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def human_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "just now"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def human_age(value: str | None) -> str:
    parsed = parse_time(value)
    if not parsed:
        return ""
    seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    return human_duration(seconds)


def human_age_epoch(value: int | float | None) -> str:
    if not value:
        return "never"
    return human_duration(int(time.time() - float(value)))


def human_time_epoch(value: int | float | None) -> str:
    if not value:
        return "—"
    return datetime.fromtimestamp(float(value)).astimezone().strftime("%Y-%m-%d %H:%M")


def human_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.1f} {units[index]}" if index else f"{int(size)} B"


def human_time(value: str | None) -> str:
    parsed = parse_time(value)
    if not parsed:
        return "?"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def severity_icon(severity: str) -> str:
    return {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(
        (severity or "").lower(), "⚪"
    )


def node_name(alert: dict) -> str:
    labels = alert.get("labels") or {}
    node = labels.get("node") or labels.get("instance") or "unknown"
    if ":" in node and not node.startswith("["):
        node = node.split(":", 1)[0]
    return NODE_NAMES.get(node, node)


def format_alert(alert: dict) -> str:
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    severity = (labels.get("severity") or "").lower()
    icon = severity_icon(severity)
    line = f"{icon} <b>{escape(labels.get('alertname', 'alert'))}</b>"
    meta = []
    if severity:
        meta.append(f"<b>{escape(severity.upper())}</b>")
    for key, emoji in (
        ("device", "💾"),
        ("name", "📦"),
        ("job", "⚙️"),
    ):
        if labels.get(key):
            meta.append(f"{emoji} <code>{escape(labels[key])}</code>")
    if meta:
        line += " · " + " · ".join(meta)

    details = [line]
    if annotations.get("summary"):
        details.append(f"<i>{escape(annotations['summary'])}</i>")
    if annotations.get("description"):
        details.append(escape(annotations["description"]))
    started = human_age(alert.get("startsAt"))
    if started:
        details.append(f"🕒 {escape(started)}")
    return "\n".join(details)


def format_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return "✅ <b>No active alerts</b>"
    groups: dict[str, list[dict]] = {}
    for alert in alerts:
        groups.setdefault(node_name(alert), []).append(alert)
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    blocks = [f"🔥 <b>{len(alerts)} active alert{'s' if len(alerts) != 1 else ''}</b>"]
    for node in sorted(groups, key=str.lower):
        blocks.append(f"🖥 <b>Node: {escape(node)}</b>")
        items = sorted(
            groups[node],
            key=lambda alert: (
                severity_rank.get(
                    ((alert.get("labels") or {}).get("severity") or "").lower(), 9
                ),
                (alert.get("labels") or {}).get("alertname", ""),
            ),
        )
        blocks.extend(format_alert(alert) for alert in items)
    return "\n\n".join(blocks)


def matcher_op(matcher: dict) -> str:
    is_regex = bool(matcher.get("isRegex"))
    is_equal = matcher.get("isEqual", True)
    if is_regex:
        return "=~" if is_equal else "!~"
    return "=" if is_equal else "!="


def format_silences(silences: list[dict]) -> str:
    active = [s for s in silences if (s.get("status") or {}).get("state") == "active"]
    if not active:
        return "🔕 <b>No active silences</b>"
    blocks = [f"🔕 <b>{len(active)} active silence{'s' if len(active) != 1 else ''}</b>"]
    for silence in active:
        labels = silence.get("matchers") or []
        matcher_text = ", ".join(
            f"{m.get('name')}{matcher_op(m)}{m.get('value')}" for m in labels
        )
        block = [
            f"🔇 <b>{escape(silence.get('createdBy', 'silence'))}</b>",
            f"<code>{escape(matcher_text)}</code>",
        ]
        if silence.get("comment"):
            block.append(f"<i>{escape(silence['comment'])}</i>")
        ends = human_time(silence.get("endsAt"))
        if ends != "?":
            block.append(f"⏳ ends {escape(ends)}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def format_status() -> str:
    status = alertmanager("/api/v2/status")
    version = (status.get("versionInfo") or {}).get("version", "?")
    uptime = human_age(status.get("uptime")) or "?"
    cluster = (status.get("cluster") or {}).get("status", "?")
    return (
        "📊 <b>Alertmanager</b>\n"
        f"Version: <code>{escape(version)}</code>\n"
        f"Uptime: {escape(uptime)}\n"
        f"Cluster: {escape(cluster)}"
    )


def format_containers() -> str:
    def pmap(query: str) -> dict[tuple[str, str], float]:
        values: dict[tuple[str, str], float] = {}
        for item in prometheus(query):
            labels = item.get("metric") or {}
            name = labels.get("name")
            if not name:
                continue
            node = labels.get("node") or labels.get("instance") or "unknown"
            if ":" in node and not node.startswith("["):
                node = node.split(":", 1)[0]
            try:
                values[(node, name)] = float(item["value"][1])
            except (KeyError, IndexError, ValueError):
                continue
        return values

    memory = pmap("sum by (node,name) (container_memory_working_set_bytes{name=~\".+\"})")
    cpu = pmap("sum by (node,name) (rate(container_cpu_usage_seconds_total{name=~\".+\"}[5m]))")
    mem_limit = pmap("max by (node,name) (container_spec_memory_limit_bytes{name=~\".+\"})")
    cpu_limit = pmap(
        "max by (node,name) (container_spec_cpu_quota{name=~\".+\"} / container_spec_cpu_period{name=~\".+\"})"
    )

    keys = set(memory) | set(cpu) | set(mem_limit) | set(cpu_limit)
    if not keys:
        return "📦 <b>No container metrics found</b>"

    def fmt_bytes(value: float) -> str:
        if value >= 1024**3:
            return f"{value / 1024**3:.1f}G"
        return f"{value / 1024**2:.0f}M"

    def fmt_cpu(value: float) -> str:
        return f"{value:.2f}c"

    groups: dict[str, list[str]] = {}
    for node, name in keys:
        display = NODE_NAMES.get(node, node)
        mem = memory.get((node, name), 0.0)
        cpu_value = cpu.get((node, name), 0.0)
        mem_lim = mem_limit.get((node, name), 0.0)
        cpu_lim = cpu_limit.get((node, name), 0.0)
        if mem_lim <= 0 or mem_lim > 1e15:
            mem_lim = 0.0
        if cpu_lim <= 0 or cpu_lim > 1e6:
            cpu_lim = 0.0
        cpu_text = fmt_cpu(cpu_value) + (f"/{fmt_cpu(cpu_lim)}" if cpu_lim else "")
        mem_text = fmt_bytes(mem) + (f"/{fmt_bytes(mem_lim)}" if mem_lim else "")
        flag = "" if cpu_lim and mem_lim else " ⚠️"
        groups.setdefault(display, []).append(
            f"• <code>{escape(name)}</code> {cpu_text} {mem_text}{flag}"
        )

    blocks = [
        f"📦 <b>{len(keys)} containers</b>",
        "<i>cpu / memory; ⚠️ = missing limit</i>",
    ]
    for display in sorted(groups, key=str.lower):
        blocks.append(f"🖥 <b>Node: {escape(display)}</b> ({len(groups[display])})")
        blocks.extend(sorted(groups[display]))
    return "\n\n".join(blocks)


def fetch_backrest_status() -> dict:
    request = urllib.request.Request(BACKREST_STATUS_URL)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def format_backups(status: dict) -> str:
    if not status.get("up"):
        return (
            "💾 <b>Backrest</b> ❌\n"
            f"<i>{escape(status.get('error') or 'status unavailable')}</i>"
        )

    plans = status.get("plans") or []
    if not plans:
        return "💾 <b>Backrest</b>\nNo backup plans found."

    icons = {
        "success": "✅",
        "warning": "⚠️",
        "failed": "❌",
        "cancelled": "⏹",
        "unknown": "⚪",
    }

    def issues(plan: dict) -> list[str]:
        result = []
        if plan.get("stale"):
            result.append("⏳ stale")
        if plan.get("no_backup"):
            result.append("🚨 no successful backup")
        if plan.get("last_backup_failed"):
            result.append("❌ last backup failed")
        return result

    attention = sum(1 for plan in plans if issues(plan))
    repo_checks = {
        str(repo.get("id")): repo for repo in (status.get("repos") or [])
    }
    blocks = [
        "💾 <b>Backrest</b> ✅",
        f"<i>{len(plans)} plans · {attention} need attention</i>",
    ]
    groups: dict[str, list[dict]] = {}
    for plan in plans:
        groups.setdefault(plan.get("repo") or "unknown", []).append(plan)

    for repo in sorted(groups, key=str.lower):
        check = repo_checks.get(repo, {})
        check_time = check.get("last_check") or 0
        if check_time:
            check_icon = "❌" if check.get("last_check_failed") else "✅"
            check_text = (
                f"last check: {check_icon} "
                f"{human_age_epoch(check_time)}"
            )
        else:
            check_text = "last check: ⚪ never"
        blocks.append(
            f"📦 <b>Repo: {escape(repo)}</b>\n<i>{check_text}</i>"
        )
        for plan in sorted(groups[repo], key=lambda item: item.get("id", "")):
            status_name = plan.get("last_status") or "unknown"
            icon = icons.get(status_name, "⚪")
            flags = issues(plan)
            line = f"{icon} <b>{escape(plan.get('id'))}</b>"
            if flags:
                line += " · " + " · ".join(flags)
            last = (
                f"last success: {human_age_epoch(plan.get('last_success'))}"
                if plan.get("last_success")
                else "last success: never"
            )
            next_backup = plan.get("next_backup") or 0
            next_text = human_time_epoch(next_backup)
            if next_backup and next_backup < time.time():
                next_text += " ⚠️ overdue"
            blocks.append(
                f"{line}\n"
                f"{last} · last status: {escape(status_name)}\n"
                f"next: {escape(next_text)}\n"
                f"30d: {int(plan.get('success_30d', 0))} ok / "
                f"{int(plan.get('failed_30d', 0))} failed"
            )
    return "\n\n".join(blocks)


def fetch_backrest_verify_status() -> dict:
    request = urllib.request.Request(BACKREST_VERIFY_STATUS_URL)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def format_verify(status: dict) -> str:
    if not status.get("up"):
        return (
            "🧪 <b>Backup verification</b> ❌\n"
            f"<i>{escape(status.get('error') or 'status unavailable')}</i>"
        )

    result = str(status.get("result") or "never").lower()
    icons = {"pass": "✅", "fail": "❌", "never": "⚪"}
    icon = icons.get(result, "⚪")
    last_run = int(status.get("last_run") or 0)
    last_success = int(status.get("last_success") or 0)
    duration = int(status.get("duration_seconds") or 0)
    checks_total = int(status.get("checks_total") or 0)
    checks_failed = int(status.get("checks_failed") or 0)
    metrics = status.get("metrics") or {}
    restored_bytes = int(metrics.get("restored_bytes") or 0)
    restored_files = int(metrics.get("restored_files") or 0)
    next_run = int(status.get("next_run") or 0)
    now = time.time()

    if not last_run:
        blocks = [
            "🧪 <b>Backup verification</b> ⚪",
            "<i>No drill has run yet.</i>",
        ]
    else:
        duration_text = (
            human_duration(duration) if duration >= 60 else f"{duration}s"
        )
        blocks = [
            f"🧪 <b>Backup verification</b> {icon}\n"
            f"Last: <b>{escape(result.upper())}</b> · "
            f"{escape(human_time_epoch(last_run))} · {escape(duration_text)}"
        ]
        if last_success:
            blocks.append(
                f"Last success: {escape(human_age_epoch(last_success))} ago"
            )

    if status.get("repo"):
        blocks.append(
            f"Remote: <code>{escape(status['repo'])}</code> (rotation)"
        )
    if restored_bytes or restored_files:
        blocks.append(
            f"Restored: {escape(human_bytes(restored_bytes))} · "
            f"{restored_files:,} files"
        )
    if checks_total:
        blocks.append(
            f"Checks: {checks_total - checks_failed} passed · "
            f"{checks_failed} failed"
        )
    if next_run:
        next_text = human_time_epoch(next_run)
        if next_run <= now:
            next_text += " ⚠️ overdue"
        else:
            next_text += f" (in {human_duration(int(next_run - now))})"
        blocks.append(f"Next: {escape(next_text)}")

    snapshots = status.get("snapshots") or {}
    snapshot_lines = []
    for repo_id in sorted(snapshots):
        entries = snapshots.get(repo_id) or {}
        parts = []
        for kind in ("core", "heavy"):
            snapshot = entries.get(kind)
            if snapshot:
                parts.append(
                    f"{kind} <code>{escape(snapshot.get('short_id') or '?')}</code>"
                )
        if parts:
            snapshot_lines.append(
                f"• {escape(repo_id)}: " + ", ".join(parts)
            )
    if snapshot_lines:
        blocks.append("Snapshots:\n" + "\n".join(snapshot_lines[:4]))

    failures = [
        check
        for check in (status.get("checks") or [])
        if str(check.get("status") or "").lower() == "fail"
    ]
    if failures:
        blocks.append("❌ <b>Failed checks</b>")
        for check in failures[:3]:
            detail = check.get("detail") or ""
            line = f"• <code>{escape(check.get('name'))}</code>"
            if detail:
                line += f": <i>{escape(detail)}</i>"
            blocks.append(line)
    elif status.get("error"):
        blocks.append(f"<i>{escape(status['error'])}</i>")
    return "\n\n".join(blocks)


def keyboard() -> str:
    return json.dumps(
        {
            "inline_keyboard": [
                [
                    {"text": "🔥 Alerts", "callback_data": "alerts"},
                    {"text": "📦 Containers", "callback_data": "containers"},
                ],
                [
                    {"text": "💾 Backups", "callback_data": "backups"},
                    {"text": "🧪 Verify", "callback_data": "verify"},
                ],
                [
                    {"text": "🔕 Silences", "callback_data": "silences"},
                    {"text": "📊 Status", "callback_data": "status"},
                ],
                [
                    {"text": "🔄 Refresh alerts", "callback_data": "alerts"},
                ],
            ]
        }
    )


def send(chat_id: int, text: str, with_keyboard: bool = True) -> None:
    limit = 3900
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = line if not current else current + "\n" + line
    if current:
        chunks.append(current)
    if not chunks:
        chunks = [""]

    for index, chunk in enumerate(chunks):
        params = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if with_keyboard and index == len(chunks) - 1:
            params["reply_markup"] = keyboard()
        telegram("sendMessage", params)


def is_allowed(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHATS


def fetch_alerts() -> list[dict]:
    return alertmanager("/api/v2/alerts?active=true&silenced=false&inhibited=false")


def fetch_silences() -> list[dict]:
    return alertmanager("/api/v2/silences")


def handle_command(chat_id: int, text: str) -> None:
    command = text.split()[0].split("@")[0].lower()
    if command == "/id":
        send(chat_id, f"🆔 <code>{chat_id}</code>", with_keyboard=False)
        return
    if not is_allowed(chat_id):
        log(f"ignored command from unauthorized chat {chat_id}")
        return
    if command in ("/start", "/help"):
        send(
            chat_id,
            "🤖 <b>Homelab alerts</b>\n"
            "I can show the current Alertmanager state.\n\n"
            "🔥 /alerts — active alerts\n"
            "📦 /containers — all containers and limits\n"
            "💾 /backups — Backrest plan status\n"
            "🧪 /verify — monthly restore drill result\n"
            "🔕 /silences — active silences\n"
            "📊 /status — Alertmanager version and uptime\n"
            "🆔 /id — this chat ID",
        )
    elif command == "/alerts":
        try:
            send(chat_id, format_alerts(fetch_alerts()))
        except Exception as error:
            send(chat_id, f"❌ Could not read alerts: {escape(error)}")
    elif command == "/containers":
        try:
            send(chat_id, format_containers())
        except Exception as error:
            send(chat_id, f"❌ Could not read containers: {escape(error)}")
    elif command == "/backups":
        try:
            send(chat_id, format_backups(fetch_backrest_status()))
        except Exception as error:
            send(chat_id, f"❌ Could not read backups: {escape(error)}")
    elif command == "/verify":
        try:
            send(chat_id, format_verify(fetch_backrest_verify_status()))
        except Exception as error:
            send(chat_id, f"❌ Could not read verification: {escape(error)}")
    elif command == "/silences":
        try:
            send(chat_id, format_silences(fetch_silences()))
        except Exception as error:
            send(chat_id, f"❌ Could not read silences: {escape(error)}")
    elif command == "/status":
        try:
            send(chat_id, format_status())
        except Exception as error:
            send(chat_id, f"❌ Could not read status: {escape(error)}")
    else:
        send(chat_id, "Use /help to see the available commands.")


def handle_callback(callback: dict) -> None:
    chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
    if chat_id is None:
        return
    telegram("answerCallbackQuery", {"callback_query_id": callback["id"]})
    if not is_allowed(chat_id):
        log(f"ignored callback from unauthorized chat {chat_id}")
        return
    data = callback.get("data")
    if data == "alerts":
        send(chat_id, format_alerts(fetch_alerts()))
    elif data == "containers":
        send(chat_id, format_containers())
    elif data == "backups":
        send(chat_id, format_backups(fetch_backrest_status()))
    elif data == "verify":
        try:
            send(chat_id, format_verify(fetch_backrest_verify_status()))
        except Exception as error:
            send(chat_id, f"❌ Could not read verification: {escape(error)}")
    elif data == "silences":
        send(chat_id, format_silences(fetch_silences()))
    elif data == "status":
        send(chat_id, format_status())


def setup_commands() -> None:
    commands = [
        {"command": "alerts", "description": "Show active alerts"},
        {"command": "containers", "description": "Show all containers and limits"},
        {"command": "backups", "description": "Show Backrest backup status"},
        {"command": "verify", "description": "Show restore verification result"},
        {"command": "silences", "description": "Show active silences"},
        {"command": "status", "description": "Alertmanager status and uptime"},
        {"command": "help", "description": "Show available commands"},
        {"command": "id", "description": "Show this chat ID"},
    ]
    payload = json.dumps(commands)
    try:
        telegram("setMyCommands", {"commands": payload})
        telegram(
            "setMyCommands",
            {
                "commands": payload,
                "scope": json.dumps({"type": "all_group_chats"}),
            },
        )
        telegram(
            "setChatMenuButton",
            {"menu_button": json.dumps({"type": "commands"})},
        )
        log("telegram commands menu configured")
    except Exception as error:
        log(f"could not configure telegram commands menu: {error}")


def poll() -> None:
    setup_commands()
    log(
        f"telegram bot started: alertmanager={ALERTMANAGER_URL} "
        f"allowed_chats={len(ALLOWED_CHATS)}"
    )
    offset = 0
    while True:
        params = {
            "timeout": POLL_TIMEOUT,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        if offset:
            params["offset"] = offset
        try:
            updates = telegram("getUpdates", params, timeout=POLL_TIMEOUT + 15)
        except Exception as error:
            log(f"getUpdates failed: {error}")
            time.sleep(5)
            continue
        for update in updates.get("result", []):
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            try:
                if "message" in update and update["message"].get("text"):
                    message = update["message"]
                    handle_command(message["chat"]["id"], message["text"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
            except Exception as error:
                log(f"update failed: {error}")


def self_test() -> None:
    print(format_alerts(fetch_alerts()))
    print()
    print(format_silences(fetch_silences()))
    print()
    print(format_status())


if __name__ == "__main__":
    if "--test" in sys.argv:
        self_test()
    else:
        poll()
