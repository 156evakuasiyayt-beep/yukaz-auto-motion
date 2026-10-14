"""Telegram notifications: daily preview (video + caption + approve link) and results.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Usage: python -m autopost.notify preview --out out [--url APPROVE_URL]
"""
import argparse
import json
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger("autopost.notify")


def _api(method):
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"


def enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_text(text: str):
    if not enabled():
        log.info("telegram disabled; message was:\n%s", text)
        return
    r = requests.post(_api("sendMessage"), timeout=60, data={
        "chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4000], "disable_web_page_preview": "true"})
    if not r.ok:
        log.warning("telegram sendMessage failed: %s", r.text[:300])


def send_preview(out: Path, approve_url: str | None):
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    head = (f"🎬 Yük.az — {plan['date']} Reels hazırdır\n"
            f"Mövzu: {plan['topic']} · otaq: {plan['room_set']} · fon: {plan['palette']} · mətn: {plan['copy_source']}")
    if not enabled():
        log.info("telegram disabled; preview:\n%s", head)
        return
    with open(out / "cover.jpg", "rb") as f:
        requests.post(_api("sendPhoto"), timeout=120, data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                      "caption": "Cover"}, files={"photo": f})
    with open(out / "reel.mp4", "rb") as f:
        r = requests.post(_api("sendVideo"), timeout=300, data={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": head[:1000], "supports_streaming": "true"},
            files={"video": ("reel.mp4", f, "video/mp4")})
    if not r.ok:
        log.warning("telegram sendVideo failed: %s", r.text[:300])
    msg = f"📝 Caption:\n\n{(out / 'caption.txt').read_text(encoding='utf-8')}"
    if approve_url:
        msg += f"\n\n✅ Təsdiq etmək üçün: {approve_url}\n(«Review deployments» → production → Approve)"
    send_text(msg)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["preview"])
    ap.add_argument("--out", default="out")
    ap.add_argument("--url")
    a = ap.parse_args()
    send_preview(Path(a.out), a.url)


if __name__ == "__main__":
    main()
