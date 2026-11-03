"""Publish today's built or Google Drive reel.

Usage: python -m autopost.publish --out out [--platforms instagram,facebook,tiktok] [--wait-until 09:00]
                                   [--approval telegram|none] [--approval-deadline 14:00] [--dry-run]
Each platform is attempted independently; the run fails (exit 1) if any required platform failed.
"""
import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path

from . import drive, meta, notify, tiktok
from .plan import BAKU

log = logging.getLogger("autopost.publish")


def _is_successful_result(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        bool(result.get("id"))
        and "error" not in result
        and "skipped" not in result
        and result.get("mode") != "inbox_draft"
    )


def _today_at(hhmm: str) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.now(BAKU).replace(hour=h, minute=m, second=0, microsecond=0)


def wait_until(hhmm: str):
    now = dt.datetime.now(BAKU)
    target = _today_at(hhmm)
    if now < target:
        secs = (target - now).total_seconds()
        log.info("waiting %.0f min until %s Asia/Baku", secs / 60, hhmm)
        time.sleep(secs)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--platforms", default="instagram,facebook,tiktok")
    ap.add_argument("--wait-until")
    ap.add_argument("--approval", choices=["telegram", "none"], default="telegram")
    ap.add_argument("--approval-deadline", default="14:00", help="HH:MM Asia/Baku; no answer by then → skip today")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    out = Path(a.out)
    video, cover = out / "reel.mp4", out / "cover.jpg"
    if not cover.exists():
        cover = None
    caption = (out / "caption.txt").read_text(encoding="utf-8")
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    platforms = [p.strip() for p in a.platforms.split(",") if p.strip()]

    if a.dry_run:
        log.info("DRY RUN — would publish %s (%s) to %s", video, plan["topic"], platforms)
        log.info("caption:\n%s", caption)
        return

    if a.approval == "telegram":
        if not notify.enabled():
            sys.exit("approval=telegram but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS are not set")
        if not (out / "telegram.json").exists():
            log.warning("no telegram.json from the build job — sending the preview from here")
            notify.send_preview(out)
        decision, who = notify.wait_for_decision(out, _today_at(a.approval_deadline))
        log.info("approval: %s (%s)", decision, who)
        if decision != "approve":
            return

    if a.wait_until:
        wait_until(a.wait_until)

    page_id, ig_id = os.environ.get("FB_PAGE_ID"), os.environ.get("IG_USER_ID")
    results, failed = {}, []
    previous_results = (
        drive.load_publish_results(plan["date"])
        if plan.get("source") == "google_drive"
        else {}
    )

    cover_url = None
    if "instagram" in platforms and page_id and cover:
        try:
            cover_url = meta.hosted_cover_url(page_id, cover)
        except meta.MetaError as e:
            log.warning("cover hosting failed, IG will use a video frame: %s", e)

    for p in platforms:
        if _is_successful_result(previous_results.get(p)):
            results[p] = previous_results[p]
            log.info("%s already published successfully for %s — skipping duplicate", p, plan["date"])
            continue
        try:
            if p == "instagram":
                results[p] = meta.publish_instagram(ig_id, video, caption, cover_url)
            elif p == "facebook":
                results[p] = meta.publish_facebook(page_id, video, caption, cover)
            elif p == "tiktok":
                if not any(os.environ.get(k, "").strip() for k in ("TIKTOK_REFRESH_TOKEN", "TIKTOK_ACCESS_TOKEN")):
                    log.error("TikTok credentials are not configured")
                    failed.append(p)
                    results[p] = {"error": "TikTok credentials are not configured"}
                    continue
                results[p] = tiktok.publish_tiktok(video, caption, cover=cover)
            else:
                raise ValueError(f"unknown platform {p}")
            log.info("%s ✓ %s", p, results[p])
        except Exception as e:  # keep going: one platform failing must not block the other
            log.error("%s ✗ %s", p, e)
            failed.append(p)
            results[p] = {"error": str(e)[:500]}

    (out / "publish_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    if plan.get("source") == "google_drive":
        complete = all(_is_successful_result(results.get(p)) for p in platforms)
        drive.record_publish_results(plan["date"], results, complete=complete)
        if not complete:
            log.warning(
                "Google Drive package %s remains incomplete; it will be retried without duplicating successful platforms",
                plan["date"],
            )

    lines = [f"📣 Yük.az — {plan['date']} paylaşım nəticəsi"]
    for p, r in results.items():
        if "skipped" in r:
            lines.append(f"⚠️ {p}: {r['skipped']}")
        else:
            lines.append(f"{'❌' if 'error' in r else '✅'} {p}: {r.get('permalink') or r.get('error')}")
    if notify.enabled():
        notify.send_text("\n".join(lines))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
