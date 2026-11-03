"""Publish a video publicly with TikTok Content Posting API v2 and OAuth2 tokens.

Env:
  TIKTOK_ACCESS_TOKEN   OAuth2 user access token
  TIKTOK_CLIENT_KEY     TikTok App Client Key used to refresh the token
  TIKTOK_CLIENT_SECRET  TikTok App Client Secret
  TIKTOK_REFRESH_TOKEN  OAuth2 refresh token

The TikTok app must pass the Content Posting API audit before it can publish with
``PUBLIC_TO_EVERYONE``. This module never falls back to Inbox drafts or private posts.
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
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()

    if client_key and client_secret and refresh_token:
        response = requests.post(
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
        data = response.json() if response.content else {}
        if response.status_code == 200 and "access_token" in data:
            log.info("Refreshed TikTok access token successfully")
            return data["access_token"]
        log.warning(
            "TikTok token refresh failed (%s: %s), trying TIKTOK_ACCESS_TOKEN",
            response.status_code,
            data,
        )

    token = os.environ.get("TIKTOK_ACCESS_TOKEN", "").strip()
    if not token:
        raise TikTokError(
            "Neither a refresh-token configuration nor TIKTOK_ACCESS_TOKEN is configured"
        )
    return token


def _upload_chunks(upload_url: str, video: Path) -> None:
    size = video.stat().st_size
    with video.open("rb") as video_file:
        response = requests.put(
            upload_url,
            data=video_file,
            timeout=600,
            headers={
                "Content-Range": f"bytes 0-{size - 1}/{size}",
                "Content-Type": "video/mp4",
            },
        )
    if response.status_code not in (200, 201, 206):
        raise TikTokError(
            f"TikTok binary upload failed ({response.status_code}): {response.text[:500]}"
        )


def publish_tiktok(
    video: Path,
    caption: str,
    cover: Path | None = None,
    cover_timestamp_ms: int = 1000,
) -> dict:
    del cover  # TikTok API uses a video-frame timestamp for the cover.

    token = get_valid_access_token()
    size = video.stat().st_size
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    payload = {
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

    response = requests.post(
        f"{TIKTOK_API}/post/publish/video/init/",
        headers=headers,
        json=payload,
        timeout=60,
    )
    data = response.json() if response.content else {}
    error = data.get("error") or {}
    error_code = error.get("code", "ok")

    if response.status_code != 200 or error_code != "ok":
        audit_hint = ""
        if error_code == "unaudited_client_can_only_post_to_private_accounts":
            audit_hint = (
                " TikTok app must pass the Content Posting API audit before public posting is allowed."
            )
        raise TikTokError(
            f"TikTok public direct post init failed ({response.status_code}, {error_code}): "
            f"{error.get('message') or data}.{audit_hint}"
        )

    upload_url = data["data"]["upload_url"]
    publish_id = data["data"].get("publish_id")
    _upload_chunks(upload_url, video)
    return {
        "id": publish_id,
        "mode": "direct_post (PUBLIC_TO_EVERYONE)",
        "permalink": "https://www.tiktok.com/@yuk.az",
    }
