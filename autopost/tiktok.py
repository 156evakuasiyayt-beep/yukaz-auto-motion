"""Publish a video to TikTok via the TikTok Content Posting API v2.

Env:
  TIKTOK_ACCESS_TOKEN   OAuth2 user access token (or auto-refreshed via below vars)
  TIKTOK_CLIENT_KEY     TikTok App Client Key (for auto-refreshing token daily)
  TIKTOK_CLIENT_SECRET  TikTok App Client Secret
  TIKTOK_REFRESH_TOKEN  OAuth2 refresh token (valid for 365 days)
"""
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger("autopost.tiktok")
TIKTOK_API = "https://open.tiktokapis.com/v2"


class TikTokError(RuntimeError):
    pass


def get_valid_access_token() -> str:
    """
    If TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, and TIKTOK_REFRESH_TOKEN are configured,
    automatically exchanges the refresh_token for a fresh access_token (since TikTok
    access_tokens expire after 24h while refresh_tokens last 365 days).
    Falls back to TIKTOK_ACCESS_TOKEN if refresh credentials are not set.
    """
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()

    if client_key and client_secret and refresh_token:
        r = requests.post(
            f"{TIKTOK_API}/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code == 200 and "access_token" in data:
            log.info("Refreshed TikTok access token successfully")
            return data["access_token"]
        log.warning("TikTok token refresh failed (%s: %s), trying TIKTOK_ACCESS_TOKEN", r.status_code, data)

    tok = os.environ.get("TIKTOK_ACCESS_TOKEN", "").strip()
    if not tok:
        raise TikTokError("Neither TIKTOK_REFRESH_TOKEN nor TIKTOK_ACCESS_TOKEN is configured")
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
    In Sandbox mode, Direct Post requires privacy_level=SELF_ONLY (or Inbox upload).
    Automatically tries PUBLIC_TO_EVERYONE -> SELF_ONLY (Sandbox) -> Inbox Upload.
    """
    tok = get_valid_access_token()
    size = video.stat().st_size
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    for privacy in ("PUBLIC_TO_EVERYONE", "SELF_ONLY"):
        direct_payload = {
            "post_info": {
                "title": (caption or "")[:2200],
                "privacy_level": privacy,
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
            return {"id": pub_id, "mode": f"direct_post ({privacy})", "permalink": "https://www.tiktok.com/@yuk.az"}

        log.warning("TikTok direct post (%s) returned %s: %s", privacy, r.status_code, data)

    log.warning("Falling back to TikTok inbox upload")
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
    return {"id": pub_id, "mode": "inbox_draft", "permalink": "https://www.tiktok.com/@yuk.az (Inbox draft)"}
