"""Telegram: daily preview with ✅/❌ approval buttons, approval wait, and result messages.

Only the chat ids in TELEGRAM_CHAT_IDS receive messages, and only those users' button
presses count. Anyone else who finds the bot gets nothing.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS (comma-separated user ids)
Usage:
  python -m autopost.notify preview --out out   # send preview + ✅/❌ buttons
  python -m autopost.notify check               # which allowed users have started the bot
  python -m autopost.notify test --out out      # preview + wait for a button (10 min), publishes nothing
"""
import argparse
import datetime as dt
import json
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger("autopost.notify")


def _api(method):
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}"


def chat_ids() -> list[str]:
    raw = os.environ.get("TELEGRAM_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


def enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and chat_ids())


def _call(method, files=None, timeout=60, **data):
    r = requests.post(_api(method), data=data, files=files, timeout=timeout)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not body.get("ok"):
        log.warning("telegram %s failed: %s", method, body.get("description") or r.text[:200])
    return body.get("result")


def send_text(text: str, reply_markup: dict | None = None) -> dict:
    """Send to every allowed chat; returns {chat_id: message_id}."""
    if not enabled():
        log.info("telegram disabled; message was:\n%s", text)
        return {}
    sent = {}
    for cid in chat_ids():
        extra = {"reply_markup": json.dumps(reply_markup)} if reply_markup else {}
        res = _call("sendMessage", chat_id=cid, text=text[:4000], disable_web_page_preview="true", **extra)
        if res:
            sent[cid] = res["message_id"]
    return sent


def approval_tag(plan: dict) -> str:
    return f"{plan['date']}:{os.environ.get('GITHUB_RUN_ID', 'local')}"


def send_preview(out: Path):
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    if plan.get("video_mode") == "atelier":
        design = f"Dizayn: {plan['concept']} · keyfiyyət balı {plan.get('qa_score')}/10"
    else:
        design = f"Dizayn: şablon · otaq: {plan['room_set']} · fon: {plan['palette']}"
    head = (f"🎬 Yük.az — {plan['date']} Reels hazırdır\n"
            f"Mövzu: {plan['topic']}\n{design}\nMətn: {plan['copy_source']}")
    if not enabled():
        log.info("telegram disabled; preview:\n%s", head)
        return
    for cid in chat_ids():
        with open(out / "cover.jpg", "rb") as f:
            _call("sendPhoto", files={"photo": f}, timeout=120, chat_id=cid, caption="Cover")
        with open(out / "reel.mp4", "rb") as f:
            _call("sendVideo", files={"video": ("reel.mp4", f, "video/mp4")}, timeout=300,
                  chat_id=cid, caption=head[:1000], supports_streaming="true")
    tag = approval_tag(plan)
    buttons = {"inline_keyboard": [[{"text": "✅ Paylaş", "callback_data": f"ok|{tag}"},
                                    {"text": "❌ Ləğv et", "callback_data": f"no|{tag}"}]]}
    caption = (out / "caption.txt").read_text(encoding="utf-8")
    msgs = send_text(f"📝 Caption:\n\n{caption}\n\n⏰ Təsdiq edilsə 09:00-da Instagram + Facebook-da paylaşılacaq.",
                     reply_markup=buttons)
    (out / "telegram.json").write_text(json.dumps({"tag": tag, "messages": msgs}), encoding="utf-8")


def _close_buttons(out: Path, note: str):
    meta = json.loads((out / "telegram.json").read_text(encoding="utf-8"))
    for cid, mid in meta["messages"].items():
        _call("editMessageReplyMarkup", chat_id=cid, message_id=mid, reply_markup=json.dumps({"inline_keyboard": []}))
    send_text(note)


def wait_for_decision(out: Path, deadline: dt.datetime) -> tuple[str, str | None]:
    """Block until an allowed user presses a button or the deadline passes.

    Returns ("approve" | "reject" | "timeout", who)."""
    meta = json.loads((out / "telegram.json").read_text(encoding="utf-8"))
    tag, allowed = meta["tag"], set(chat_ids())
    offset = None
    while True:
        left = (deadline - dt.datetime.now(deadline.tzinfo)).total_seconds()
        if left <= 0:
            _close_buttons(out, "⌛ Təsdiq vaxtı bitdi — bugünkü video paylaşılmadı.")
            return "timeout", None
        params = {"timeout": int(min(50, max(1, left))), "allowed_updates": json.dumps(["callback_query"])}
        if offset is not None:
            params["offset"] = offset
        try:
            res = requests.get(_api("getUpdates"), params=params, timeout=70).json().get("result", [])
        except requests.RequestException as e:
            log.warning("getUpdates failed: %s", e)
            time.sleep(5)
            continue
        for upd in res:
            offset = upd["update_id"] + 1
            cq = upd.get("callback_query")
            if not cq:
                continue
            action, _, cb_tag = (cq.get("data") or "").partition("|")
            user = cq["from"]
            who = user.get("first_name") or user.get("username") or str(user["id"])
            if str(user["id"]) not in allowed:
                _call("answerCallbackQuery", callback_query_id=cq["id"], text="Bu düymə sizin üçün deyil.")
                continue
            if cb_tag != tag:
                _call("answerCallbackQuery", callback_query_id=cq["id"], text="Bu köhnə videodur.")
                continue
            if action == "ok":
                _call("answerCallbackQuery", callback_query_id=cq["id"], text="Təsdiq edildi ✅")
                _close_buttons(out, f"✅ {who} təsdiq etdi — paylaşılır (09:00-dan əvvəldirsə, saat 09:00-da).")
                return "approve", who
            if action == "no":
                _call("answerCallbackQuery", callback_query_id=cq["id"], text="Ləğv edildi ❌")
                _close_buttons(out, f"❌ {who} ləğv etdi — bugünkü video paylaşılmayacaq.")
                return "reject", who


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["preview", "check", "test"])
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    if a.action == "check":
        for cid in chat_ids():
            r = requests.get(_api("getChat"), params={"chat_id": cid}, timeout=30).json()
            name = (r.get("result") or {}).get("first_name", "")
            print(f"{cid}: {'✅ botu başladıb ' + name if r.get('ok') else '❌ hələ Start basmayıb'}")
        return
    send_preview(Path(a.out))
    if a.action == "test":
        deadline = dt.datetime.now().astimezone() + dt.timedelta(minutes=10)
        print("Telegram-da düyməyə basın (10 dəq)…")
        print("nəticə:", wait_for_decision(Path(a.out), deadline))


if __name__ == "__main__":
    main()
