"""Publish a reel to Instagram (Reels) and a Facebook Page (Reels) via the Graph API.

Env:
  META_ACCESS_TOKEN  long-lived Page token (System User token from Business Manager)
  FB_PAGE_ID         Facebook Page id
  IG_USER_ID         Instagram professional account id linked to that Page
  GRAPH_VERSION      optional, default v25.0
"""
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger("autopost.meta")
GV = os.environ.get("GRAPH_VERSION", "v25.0")
GRAPH = f"https://graph.facebook.com/{GV}"
RUPLOAD = "https://rupload.facebook.com"


class MetaError(RuntimeError):
    pass


def _token():
    tok = os.environ.get("META_ACCESS_TOKEN")
    if not tok:
        raise MetaError("META_ACCESS_TOKEN is not set")
    return tok


def _check(r: requests.Response, what: str) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:500]}
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        raise MetaError(f"{what} failed ({r.status_code}): {data}")
    return data


def _upload_binary(url: str, video: Path):
    size = video.stat().st_size
    with open(video, "rb") as f:
        r = requests.post(url, data=f, timeout=600, headers={
            "Authorization": f"OAuth {_token()}", "offset": "0", "file_size": str(size),
            "Content-Type": "application/octet-stream"})
    return _check(r, "binary upload")


def hosted_cover_url(page_id: str, cover: Path) -> str:
    """Upload the cover as an unpublished Page photo and return its CDN URL (IG needs a public URL)."""
    with open(cover, "rb") as f:
        r = requests.post(f"{GRAPH}/{page_id}/photos", timeout=120,
                          data={"published": "false", "access_token": _token()},
                          files={"source": ("cover.jpg", f, "image/jpeg")})
    photo_id = _check(r, "cover photo upload")["id"]
    r = requests.get(f"{GRAPH}/{photo_id}", timeout=60,
                     params={"fields": "images", "access_token": _token()})
    images = _check(r, "cover photo lookup")["images"]
    return max(images, key=lambda i: i["width"] * i["height"])["source"]


# ----------------------------------------------------------------------------- Instagram
def publish_instagram(ig_user_id: str, video: Path, caption: str, cover_url: str | None) -> dict:
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
              "access_token": _token()}
    if cover_url:
        params["cover_url"] = cover_url
    else:
        params["thumb_offset"] = "10200"
    r = requests.post(f"{GRAPH}/{ig_user_id}/media", data=params, timeout=60)
    container = _check(r, "IG container create")
    cid = container["id"]
    _upload_binary(container.get("uri") or f"{RUPLOAD}/ig-api-upload/{GV}/{cid}", video)

    deadline = time.time() + 600
    while True:
        r = requests.get(f"{GRAPH}/{cid}", timeout=60,
                         params={"fields": "status_code,status", "access_token": _token()})
        st = _check(r, "IG container status")
        code = st.get("status_code")
        log.info("IG container %s: %s", cid, code)
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise MetaError(f"IG processing failed: {st}")
        if time.time() > deadline:
            raise MetaError("IG processing timed out")
        time.sleep(10)

    r = requests.post(f"{GRAPH}/{ig_user_id}/media_publish", timeout=60,
                      data={"creation_id": cid, "access_token": _token()})
    media_id = _check(r, "IG publish")["id"]
    r = requests.get(f"{GRAPH}/{media_id}", timeout=60,
                     params={"fields": "permalink", "access_token": _token()})
    permalink = _check(r, "IG permalink").get("permalink")
    return {"id": media_id, "permalink": permalink}


# ----------------------------------------------------------------------------- Facebook Page
def publish_facebook(page_id: str, video: Path, caption: str, cover: Path | None) -> dict:
    r = requests.post(f"{GRAPH}/{page_id}/video_reels", timeout=60,
                      data={"upload_phase": "start", "access_token": _token()})
    start = _check(r, "FB reel start")
    vid = start["video_id"]
    _upload_binary(start.get("upload_url") or f"{RUPLOAD}/video-upload/{GV}/{vid}", video)

    r = requests.post(f"{GRAPH}/{page_id}/video_reels", timeout=60, data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": caption, "access_token": _token()})
    _check(r, "FB reel finish")

    if cover:
        # best effort: the reel is already live, a failed thumbnail must not fail the run
        for _ in range(12):
            time.sleep(10)
            with open(cover, "rb") as f:
                r = requests.post(f"{GRAPH}/{vid}/thumbnails", timeout=120,
                                  data={"is_preferred": "true", "access_token": _token()},
                                  files={"source": ("cover.jpg", f, "image/jpeg")})
            if r.ok:
                break
            log.info("FB thumbnail not accepted yet (%s), retrying", r.status_code)
        else:
            log.warning("FB custom thumbnail could not be set: %s", r.text[:300])
    return {"id": vid, "permalink": f"https://www.facebook.com/reel/{vid}"}
