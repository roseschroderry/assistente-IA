import os
import smtplib
from email.message import EmailMessage
from typing import Iterable

import requests
from dotenv import load_dotenv

from .brain import brain

load_dotenv()


def _split_channels(channels: Iterable[str] | None) -> list[str]:
    if channels:
        return [str(channel).strip().lower() for channel in channels if str(channel).strip()]
    configured = os.getenv("ELITE_NOTIFY_CHANNELS", "app")
    return [channel.strip().lower() for channel in configured.split(",") if channel.strip()]


def _send_telegram(title: str, message: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return "telegram: nao configurado"
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"{title}\n{message}".strip()},
        timeout=12,
    )
    return "telegram: ok" if response.ok else f"telegram: HTTP {response.status_code}"


def _send_pushover(title: str, message: str) -> str:
    token = os.getenv("PUSHOVER_TOKEN")
    user = os.getenv("PUSHOVER_USER")
    if not token or not user:
        return "pushover: nao configurado"
    response = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={"token": token, "user": user, "title": title, "message": message},
        timeout=12,
    )
    return "pushover: ok" if response.ok else f"pushover: HTTP {response.status_code}"


def _send_webhook(channel: str, title: str, message: str) -> str:
    env_name = {
        "discord": "DISCORD_WEBHOOK_URL",
        "slack": "SLACK_WEBHOOK_URL",
        "whatsapp": "WHATSAPP_WEBHOOK_URL",
    }.get(channel)
    url = os.getenv(env_name or "")
    if not url:
        return f"{channel}: nao configurado"
    payload = {"content": f"{title}\n{message}".strip()} if channel == "discord" else {"text": f"{title}\n{message}".strip()}
    response = requests.post(url, json=payload, timeout=12)
    return f"{channel}: ok" if response.ok else f"{channel}: HTTP {response.status_code}"


def _send_email(title: str, message: str) -> str:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", username or "")
    recipient = os.getenv("SMTP_TO")
    if not host or not sender or not recipient:
        return "email: nao configurado"

    email = EmailMessage()
    email["Subject"] = title or "Assistente Elite"
    email["From"] = sender
    email["To"] = recipient
    email.set_content(message)

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(email)
    return "email: ok"


def send_notification(title: str, message: str, channels: Iterable[str] | None = None) -> dict:
    selected = _split_channels(channels)
    results = []
    for channel in selected:
        try:
            if channel == "app":
                result = "app: ok"
            elif channel == "telegram":
                result = _send_telegram(title, message)
            elif channel == "pushover":
                result = _send_pushover(title, message)
            elif channel in {"discord", "slack", "whatsapp"}:
                result = _send_webhook(channel, title, message)
            elif channel == "email":
                result = _send_email(title, message)
            else:
                result = f"{channel}: canal desconhecido"
        except Exception as exc:
            result = f"{channel}: erro {exc}"
        results.append(result)

    status = "; ".join(results)
    brain.add_notification_event(title, message, selected, status)
    return {"title": title, "message": message, "channels": selected, "status": status}
