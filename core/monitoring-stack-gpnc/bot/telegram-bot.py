#!/usr/bin/env python3
"""Read-only Telegram bot for Prometheus Alertmanager.

It uses the Telegram Bot API long polling, so it needs no inbound port or
public domain. The bot token and default chat ID are read from the active
Alertmanager config file, which avoids duplicating secrets in the stack
environment.

Commands:
  /start, /help, /alerts, /silences, /status, /id
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
CONFIG_FILE = os.environ.get("BOT_CONFIG_FILE", "/config/alertmanager.yml")
ALLOWED_ENV = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "50"))


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


def escape(value: object) -> str:
    return html.escape(str(value or ""))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def human_age(value: str | None) -> str:
    parsed = parse_time(value)
    if not parsed:
        return ""
    seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
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


def human_time(value: str | None) -> str:
    parsed = parse_time(value)
    if not parsed:
        return "?"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def severity_icon(severity: str) -> str:
    return {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(
        (severity or "").lower(), "⚪"
    )


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
        ("instance", "🖥"),
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
    blocks = [f"🔥 <b>{len(alerts)} active alert{'s' if len(alerts) != 1 else ''}</b>"]
    blocks.extend(format_alert(alert) for alert in alerts)
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


def keyboard() -> str:
    return json.dumps(
        {
            "inline_keyboard": [
                [
                    {"text": "🔥 Alerts", "callback_data": "alerts"},
                    {"text": "🔕 Silences", "callback_data": "silences"},
                ],
                [
                    {"text": "📊 Status", "callback_data": "status"},
                    {"text": "🔄 Refresh", "callback_data": "alerts"},
                ],
            ]
        }
    )


def send(chat_id: int, text: str, with_keyboard: bool = True) -> None:
    if len(text) > 4000:
        text = text[:3950] + "\n…"
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if with_keyboard:
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
            "🔕 /silences — active silences\n"
            "📊 /status — Alertmanager version and uptime\n"
            "🆔 /id — this chat ID",
        )
    elif command == "/alerts":
        try:
            send(chat_id, format_alerts(fetch_alerts()))
        except Exception as error:
            send(chat_id, f"❌ Could not read alerts: {escape(error)}")
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
    elif data == "silences":
        send(chat_id, format_silences(fetch_silences()))
    elif data == "status":
        send(chat_id, format_status())


def setup_commands() -> None:
    commands = [
        {"command": "alerts", "description": "Show active alerts"},
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
