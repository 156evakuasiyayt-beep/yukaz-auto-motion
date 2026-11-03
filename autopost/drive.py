"""Fetch the next ready-to-publish Reel package (video, cover, caption) from Google Drive.

Supported Google Drive folder structures:

Monthly flat folder (current production setup):
  <GOOGLE_DRIVE_FOLDER_ID>/
    current_reel.mp4

Date folders (legacy setup):
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
# Public "Yük.az Reels" root containing the dated daily packages.
DEFAULT_DRIVE_FOLDER_ID = "1LDJqdkgqU2_a08vSYHdkFd7nJZlTqcQa"
TRACKER_PATH = Path("content/published_drive.json")


def _extract_folder_id(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    return m.group(1) if m else raw


def load_tracker() -> dict:
    if TRACKER_PATH.exists():
        try:
            data = json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"published_dates": [], "history": {}}


def load_published_dates() -> set[str]:
    return set(load_tracker().get("published_dates", []))


def load_publish_results(date_key: str) -> dict:
    history = load_tracker().get("history", {})
    return dict((history.get(date_key) or {}).get("results") or {})


def record_publish_results(date_key: str, results: dict, *, complete: bool) -> None:
    """Persist an attempt, marking the date complete only when every requested platform succeeded."""
    tracker = load_tracker()
    published = set(tracker.get("published_dates", []))
    history = dict(tracker.get("history", {}))
    previous = dict((history.get(date_key) or {}).get("results") or {})
    now = dt.datetime.now(BAKU).isoformat()

    entry = dict(history.get(date_key) or {})
    entry["last_attempt_at"] = now
    entry["results"] = {**previous, **results}
    if complete:
        published.add(date_key)
        entry["published_at"] = now
    history[date_key] = entry

    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_PATH.write_text(
        json.dumps(
            {"published_dates": sorted(published), "history": history},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def mark_date_published(date_key: str, results: dict):
    record_publish_results(date_key, results, complete=True)


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
    package_date = None
    if target_date:
        if target_date in packages and "video" in packages[target_date]:
            selected_key = target_date
            package_date = target_date
        elif "video" in packages.get("root", {}):
            # The live monthly folder contains the current day's video directly.
            # A manual run supplies the intended date, so bind that flat package
            # to the requested date instead of requiring a dated subfolder.
            selected_key = "root"
            package_date = target_date
        else:
            raise RuntimeError(f"Requested date folder '{target_date}' not found in Google Drive (available: {sorted(packages.keys())})")
    elif today_str in packages and "video" in packages[today_str] and today_str not in published:
        selected_key = today_str
        package_date = today_str
    elif "video" in packages.get("root", {}) and today_str not in published:
        selected_key = "root"
        package_date = today_str
    else:
        for key in sorted(packages.keys()):
            if key == "root":
                continue
            if key not in published and "video" in packages[key] and key <= today_str:
                selected_key = key
                package_date = key
                break
        if not selected_key:
            for key in sorted(packages.keys()):
                if key == "root":
                    continue
                if key not in published and "video" in packages[key]:
                    selected_key = key
                    package_date = key
                    break

    if not selected_key:
        raise RuntimeError(f"All available Google Drive packages ({sorted(packages.keys())}) have already been published.")

    pkg = packages[selected_key]
    out_dir.mkdir(parents=True, exist_ok=True)

    video_meta = pkg["video"]
    video_out = out_dir / "reel.mp4"
    log.info("Downloading video for %s (%s) -> %s", package_date, video_meta.path, video_out)
    gdown.download(id=video_meta.id, output=str(video_out), quiet=False)

    cover_out = out_dir / "cover.jpg"
    if "cover" in pkg:
        cover_meta = pkg["cover"]
        log.info("Downloading cover for %s (%s) -> %s", package_date, cover_meta.path, cover_out)
        gdown.download(id=cover_meta.id, output=str(cover_out), quiet=True)

    caption_out = out_dir / "caption.txt"
    caption_text = ""
    if "caption" in pkg:
        cap_meta = pkg["caption"]
        log.info("Downloading caption for %s (%s) -> %s", package_date, cap_meta.path, caption_out)
        gdown.download(id=cap_meta.id, output=str(caption_out), quiet=True)
        if caption_out.exists():
            caption_text = caption_out.read_text(encoding="utf-8", errors="replace").strip()
    caption_out.write_text(caption_text, encoding="utf-8")

    plan = {
        "date": package_date,
        "topic": f"Google Drive ({package_date})",
        "source": "google_drive",
        "drive_folder_id": folder_id,
    }
    (out_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return package_date


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
