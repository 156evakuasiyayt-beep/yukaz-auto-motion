"""Publish a video to TikTok via the TikTok Content Posting API v2.

Env:
  TIKTOK_ACCESS_TOKEN  OAuth2 user access token with video.publish / video.upload scope
"""
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger("autopost.tiktok")
TIKTOK_API = "https://open.tiktokapis.com/v2"


class TikTokError(RuntimeError):
    pass


def _token() -> str:
    tok = os.environ.get("TIKTOK_ACCESS_TOKEN", "").strip()
    if not tok:
        raise TikTokError("TIKTOK_ACCESS_TOKEN is not set")
    return tok


def _upload_chunks(upload_url: str, video: Path):
    size = video.stat().st_size
    with open(video, "rb") as f:
        r = requests.put(
            upload_url,
            data=f,
            timeout=600,
            headers={
                "Content-Range": f"bytes 0-{size - 1}/{size}",
                "Content-Type": "video/mp4",
            },
        )
    if r.status_code not in (200, 201, 206):
        raise TikTokError(f"TikTok binary upload failed ({r.status_code}): {r.text[:500]}")


def publish_tiktok(video: Path, caption: str, cover_timestamp_ms: int = 1000) -> dict:
    """
    First attempts Direct Post (/post/publish/video/init/).
    If the TikTok app is unaudited or only has video.upload scope, automatically falls back
    to Inbox Upload (/post/publish/inbox/video/init/).
    """
    tok = _token()
    size = video.stat().st_size
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    direct_payload = {
        "post_info": {
            "title": (caption or "")[:2200],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": cover_timestamp_ms,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        },
    }

    r = requests.post(f"{TIKTOK_API}/post/publish/video/init/", headers=headers, json=direct_payload, timeout=60)
    data = r.json() if r.content else {}
    err_code = (data.get("error") or {}).get("code", "ok")

    if r.status_code == 200 and err_code == "ok":
        upload_url = data["data"]["upload_url"]
        pub_id = data["data"].get("publish_id")
        _upload_chunks(upload_url, video)
        return {"id": pub_id, "mode": "direct_post", "permalink": f"tiktok://publish/{pub_id}"}

    log.warning("TikTok direct post unavailable (%s: %s), falling back to inbox upload", r.status_code, data)
    inbox_payload = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        }
    }
    r2 = requests.post(f"{TIKTOK_API}/post/publish/inbox/video/init/", headers=headers, json=inbox_payload, timeout=60)
    data2 = r2.json() if r2.content else {}
    err_code2 = (data2.get("error") or {}).get("code", "ok")
    if r2.status_code != 200 or err_code2 != "ok":
        raise TikTokError(f"TikTok publish failed ({r2.status_code}): {data2}")

    upload_url = data2["data"]["upload_url"]
    pub_id = data2["data"].get("publish_id")
    _upload_chunks(upload_url, video)
    return {"id": pub_id, "mode": "inbox_draft", "permalink": f"tiktok://inbox/{pub_id}"}
