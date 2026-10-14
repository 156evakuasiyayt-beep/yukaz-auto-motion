"""One-time setup helpers.

  python -m autopost.setup_helper meta <SYSTEM_USER_TOKEN>
      → lists your Pages with their (never-expiring) Page tokens and linked Instagram account ids
  python -m autopost.setup_helper telegram <BOT_TOKEN>
      → prints the chat id of whoever last wrote to the bot (send /start to it first)
"""
import sys

import requests

from .meta import GRAPH


def meta(token: str):
    r = requests.get(f"{GRAPH}/me/accounts", timeout=60,
                     params={"fields": "id,name,access_token,instagram_business_account{id,username}",
                             "access_token": token})
    data = r.json()
    if "error" in data:
        sys.exit(f"Meta error: {data['error'].get('message')}")
    if not data.get("data"):
        sys.exit("Bu token-ə heç bir Facebook səhifəsi təyin olunmayıb (System user → Assign assets → Page).")
    for p in data["data"]:
        ig = p.get("instagram_business_account") or {}
        print(f"\nSəhifə: {p['name']}")
        print(f"  FB_PAGE_ID        = {p['id']}")
        print(f"  IG_USER_ID        = {ig.get('id', '— Instagram bağlı deyil —')}  (@{ig.get('username', '?')})")
        print(f"  META_ACCESS_TOKEN = {p['access_token']}")
    r = requests.get(f"{GRAPH}/debug_token", timeout=60, params={"input_token": token, "access_token": token})
    info = r.json().get("data", {})
    print(f"\nToken icazələri: {', '.join(info.get('scopes', []))}")
    print(f"Token bitmə tarixi: {'heç vaxt' if not info.get('expires_at') else info['expires_at']}")


def telegram(bot_token: str):
    r = requests.get(f"https://api.telegram.org/bot{bot_token}/getUpdates", timeout=60).json()
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name") or u["message"]["chat"].get("title")
             for u in r.get("result", []) if "message" in u}
    if not chats:
        sys.exit("Mesaj tapılmadı: Telegram-da botunuza /start yazın və yenidən işlədin.")
    for cid, name in chats.items():
        print(f"TELEGRAM_CHAT_ID = {cid}  ({name})")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("meta", "telegram"):
        sys.exit(__doc__)
    {"meta": meta, "telegram": telegram}[sys.argv[1]](sys.argv[2])
