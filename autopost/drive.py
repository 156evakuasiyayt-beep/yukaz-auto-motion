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
from urllib.parse import urlparse

import gdown
import requests
from bs4 import BeautifulSoup

from .plan import BAKU

log = logging.getLogger("autopost.drive")
# Public "Yük.az Reels" root containing the dated daily packages.
DEFAULT_DRIVE_FOLDER_ID = "1LDJqdkgqU2_a08vSYHdkFd7nJZlTqcQa"
TRACKER_PATH = Path("content/published_drive.json")


def _extract_folder_id(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    return m.group(1) if m else raw


def _list_public_folder(folder_id: str) -> list[tuple[str, str, str]]:
    """List only direct children, without probing archived Google Docs exports."""
    response = requests.get(
        "https://drive.google.com/embeddedfolderview",
        params={"id": folder_id},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    if not soup.title:
        raise RuntimeError(f"Could not read public Drive folder {folder_id}")

    entries = []
    for link in soup.find_all("a", href=True):
        url = urlparse(link["href"])
        name = link.get_text(strip=True)
        folder = re.fullmatch(r"/drive/folders/([\w-]+)", url.path)
        file = re.fullmatch(r"/file/d/([\w-]+)/view", url.path)
        if url.netloc == "drive.google.com" and folder:
            entries.append((name, folder.group(1), "folder"))
        elif url.netloc == "drive.google.com" and file:
            entries.append((name, file.group(1), "file"))
    return entries


def _pick_file(entries: list[tuple[str, str, str]], date_key: str, kind: str):
    extensions = {
        "video": (".mp4", ".mov"),
        "cover": (".jpg", ".jpeg", ".png", ".webp"),
        "caption": (".txt",),
    }[kind]
    matches = [(name, file_id) for name, file_id, type_ in entries
               if type_ == "file" and name.lower().endswith(extensions)]
    dated = [(name, file_id) for name, file_id in matches if date_key in name]
    matches = dated
    if len(matches) > 1:
        raise RuntimeError(f"Multiple {kind} files for {date_key}: {[name for name, _ in matches]}")
    return matches[0] if matches else None


def _download_file(file_id: str, path: Path) -> None:
    result = gdown.download(id=file_id, output=str(path), quiet=True)
    if not result or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Google Drive download failed for file {file_id}")


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
    today_str = dt.datetime.now(BAKU).strftime("%Y-%m-%d")
    date_key = target_date or today_str
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_key):
            raise ValueError("Expected YYYY-MM-DD")
        dt.date.fromisoformat(date_key)
    except ValueError as error:
        raise ValueError(f"Invalid Drive package date: {date_key}") from error

    out_dir.mkdir(parents=True, exist_ok=True)
    skip_marker = out_dir / "already_published.txt"
    if skip_marker.exists():
        skip_marker.unlink()
    if not force and date_key in load_published_dates():
        log.info("%s is already published — skipping duplicate run", date_key)
        skip_marker.write_text(date_key, encoding="utf-8")
        return date_key

    log.info("Inspecting Google Drive folder for %s: %s", date_key, folder_id)
    root_entries = _list_public_folder(folder_id)
    matching_folders = [entry for entry in root_entries
                        if entry[2] == "folder" and entry[0] == date_key]
    if len(matching_folders) > 1:
        raise RuntimeError(f"Multiple Google Drive folders named {date_key}")
    if matching_folders:
        package_entries = _list_public_folder(matching_folders[0][1])
    else:
        # A flat folder is valid only when the filename names the requested date.
        package_entries = [entry for entry in root_entries
                           if entry[2] == "file" and date_key in entry[0]]

    video = _pick_file(package_entries, date_key, "video")
    if not video:
        raise RuntimeError(f"No video found for {date_key} in Google Drive folder {folder_id}")
    cover = _pick_file(package_entries, date_key, "cover")
    caption = _pick_file(package_entries, date_key, "caption")

    video_out = out_dir / "reel.mp4"
    log.info("Downloading video for %s (%s) -> %s", date_key, video[0], video_out)
    _download_file(video[1], video_out)

    cover_out = out_dir / "cover.jpg"
    if cover:
        log.info("Downloading cover for %s (%s) -> %s", date_key, cover[0], cover_out)
        _download_file(cover[1], cover_out)

    caption_out = out_dir / "caption.txt"
    caption_text = ""
    if caption:
        log.info("Downloading caption for %s (%s) -> %s", date_key, caption[0], caption_out)
        _download_file(caption[1], caption_out)
        caption_text = caption_out.read_text(encoding="utf-8", errors="replace").strip()
    caption_out.write_text(caption_text, encoding="utf-8")

    plan = {
        "date": date_key,
        "topic": f"Google Drive ({date_key})",
        "source": "google_drive",
        "drive_folder_id": folder_id,
    }
    (out_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return date_key


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
