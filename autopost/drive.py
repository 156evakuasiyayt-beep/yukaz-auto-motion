"""Fetch the next ready-to-publish Reel package (video, cover, caption) from Google Drive.

Expected Google Drive folder structure (Yük.az Reels):
  <GOOGLE_DRIVE_FOLDER_ID>/
    YYYY-MM-DD/
      yukaz_reel_YYYY-MM-DD.mp4
      yukaz_cover_YYYY-MM-DD.jpg
      yukaz_caption_YYYY-MM-DD.txt
"""
import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path

import gdown

from .plan import BAKU

log = logging.getLogger("autopost.drive")
DEFAULT_DRIVE_FOLDER_ID = "1LDJqdkgqU2_a08vSYHdkFd7nJZlTqcQa"
TRACKER_PATH = Path("content/published_drive.json")


def _extract_folder_id(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    return m.group(1) if m else raw


def load_published_dates() -> set[str]:
    if TRACKER_PATH.exists():
        try:
            data = json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
            return set(data.get("published_dates", []))
        except Exception:
            pass
    return set()


def mark_date_published(date_key: str, results: dict):
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    published = sorted(load_published_dates() | {date_key})
    history = {}
    if TRACKER_PATH.exists():
        try:
            history = json.loads(TRACKER_PATH.read_text(encoding="utf-8")).get("history", {})
        except Exception:
            history = {}
    prev_results = (history.get(date_key) or {}).get("results") or {}
    history[date_key] = {
        "published_at": dt.datetime.now(BAKU).isoformat(),
        "results": {**prev_results, **results},
    }
    TRACKER_PATH.write_text(
        json.dumps({"published_dates": published, "history": history}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_drive_package(out_dir: Path, target_date: str | None = None, force: bool = False) -> str:
    raw_folder = os.environ.get("GOOGLE_DRIVE_FOLDER_ID") or DEFAULT_DRIVE_FOLDER_ID
    folder_id = _extract_folder_id(raw_folder)
    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

    log.info("Inspecting Google Drive folder: %s", folder_url)
    files = gdown.download_folder(url=folder_url, skip_download=True, quiet=True)
    if not files:
        raise RuntimeError(f"No files found in Google Drive folder {folder_id}")

    packages: dict[str, dict[str, object]] = {}
    for f in files:
        rel_path = str(f.path).replace("\\", "/")
        parts = rel_path.split("/")
        group_key = parts[0] if len(parts) > 1 else "root"
        fname = parts[-1].lower()

        pkg = packages.setdefault(group_key, {})
        if fname.endswith((".mp4", ".mov")):
            pkg["video"] = f
        elif fname.endswith((".jpg", ".jpeg", ".png", ".webp")):
            pkg["cover"] = f
        elif fname.endswith(".txt"):
            pkg["caption"] = f

    published = set() if force else load_published_dates()
    today_str = dt.datetime.now(BAKU).strftime("%Y-%m-%d")

    out_dir.mkdir(parents=True, exist_ok=True)
    skip_marker = out_dir / "already_published.txt"
    if skip_marker.exists():
        skip_marker.unlink()

    if not target_date and not force and today_str in published:
        log.info("Today's package (%s) is already in published_dates — skipping duplicate run.", today_str)
        skip_marker.write_text(today_str, encoding="utf-8")
        return today_str

    selected_key = None
    if target_date:
        if target_date not in packages or "video" not in packages[target_date]:
            raise RuntimeError(f"Requested date folder '{target_date}' not found in Google Drive (available: {sorted(packages.keys())})")
        selected_key = target_date
    elif today_str in packages and "video" in packages[today_str] and today_str not in published:
        selected_key = today_str
    else:
        for key in sorted(packages.keys()):
            if key not in published and "video" in packages[key] and key <= today_str:
                selected_key = key
                break
        if not selected_key:
            for key in sorted(packages.keys()):
                if key not in published and "video" in packages[key]:
                    selected_key = key
                    break

    if not selected_key:
        raise RuntimeError(f"All available Google Drive packages ({sorted(packages.keys())}) have already been published.")

    pkg = packages[selected_key]
    out_dir.mkdir(parents=True, exist_ok=True)

    video_meta = pkg["video"]
    video_out = out_dir / "reel.mp4"
    log.info("Downloading video for %s (%s) -> %s", selected_key, video_meta.path, video_out)
    gdown.download(id=video_meta.id, output=str(video_out), quiet=False)

    cover_out = out_dir / "cover.jpg"
    if "cover" in pkg:
        cover_meta = pkg["cover"]
        log.info("Downloading cover for %s (%s) -> %s", selected_key, cover_meta.path, cover_out)
        gdown.download(id=cover_meta.id, output=str(cover_out), quiet=True)

    caption_out = out_dir / "caption.txt"
    caption_text = ""
    if "caption" in pkg:
        cap_meta = pkg["caption"]
        log.info("Downloading caption for %s (%s) -> %s", selected_key, cap_meta.path, caption_out)
        gdown.download(id=cap_meta.id, output=str(caption_out), quiet=True)
        if caption_out.exists():
            caption_text = caption_out.read_text(encoding="utf-8", errors="replace").strip()
    caption_out.write_text(caption_text, encoding="utf-8")

    plan = {
        "date": selected_key,
        "topic": f"Google Drive ({selected_key})",
        "source": "google_drive",
        "drive_folder_id": folder_id,
    }
    (out_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return selected_key


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--date", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    try:
        date_key = fetch_drive_package(Path(a.out), target_date=a.date or None, force=a.force)
        log.info("Successfully prepared Google Drive package for %s in %s/", date_key, a.out)
    except Exception as e:
        log.error("Failed to fetch Google Drive package: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
