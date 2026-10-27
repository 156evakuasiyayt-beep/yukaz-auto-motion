"""Publish a video to TikTok (Public Direct Post via TikTok Studio session cookie, or Content Posting API v2).

Env:
  TIKTOK_SESSION_ID     TikTok 'sessionid' cookie from logged-in browser (posts directly as Public via TikTok Studio)
  TIKTOK_ACCESS_TOKEN   OAuth2 user access token (or auto-refreshed via below vars)
  TIKTOK_CLIENT_KEY     TikTok App Client Key (for auto-refreshing token daily)
  TIKTOK_CLIENT_SECRET  TikTok App Client Secret
  TIKTOK_REFRESH_TOKEN  OAuth2 refresh token (valid for 365 days)
"""
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger("autopost.tiktok")
TIKTOK_API = "https://open.tiktokapis.com/v2"


class TikTokError(RuntimeError):
    pass


def publish_tiktok_studio_session(video: Path, caption: str, session_id: str) -> dict:
    """
    Uses Playwright in headless mode with the user's TikTok `sessionid` cookie
    to upload and publish the video directly as Public (Everyone) via TikTok Studio Web.
    """
    from playwright.sync_api import sync_playwright

    log.info("Publishing to TikTok Studio (Public) via TIKTOK_SESSION_ID...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        cookies = []
        for name in ("sessionid", "sessionid_ss", "sid_tt"):
            for domain in (".tiktok.com", "www.tiktok.com"):
                cookies.append(
                    {
                        "name": name,
                        "value": session_id,
                        "domain": domain,
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "None",
                    }
                )
        context.add_cookies(cookies)

        page = context.new_page()
        page.goto("https://www.tiktok.com/tiktokstudio/upload?lang=en", wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)

        log.info("TikTok Studio landed on URL: %s | Title: %s", page.url, page.title())
        try:
            body_preview = " ".join((page.locator("body").inner_text(timeout=5000) or "").split())[:300]
            log.info("TikTok Studio body preview: %s", body_preview)
        except Exception as e:
            log.warning("Could not read body text: %s", e)

        if "/login" in page.url or "login" in page.title().lower():
            browser.close()
            raise TikTokError(f"TIKTOK_SESSION_ID redirected to login ({page.url})")

        # Search all frames for input[type='file']
        target_frame = None
        for _ in range(10):
            for frame in page.frames:
                try:
                    if frame.locator("input[type='file']").count() > 0:
                        target_frame = frame
                        break
                except Exception:
                    pass
            if target_frame:
                break
            time.sleep(2)

        if target_frame:
            log.info("Found input[type='file'] in frame: %s", target_frame.url)
            target_frame.locator("input[type='file']").first.set_input_files(str(video))
        else:
            log.info("No direct input[type='file'] found; trying file chooser click...")
            with page.expect_file_chooser(timeout=20000) as fc_info:
                btn = page.locator("button:has-text('Select'), [data-e2e*='select'], [class*='upload']").first
                btn.click(force=True)
            fc_info.value.set_files(str(video))

        log.info("TikTok Studio: video file attached, waiting for editor...")
        work_ctx = target_frame or page
        editor = work_ctx.locator("[contenteditable='true']").first
        editor.wait_for(state="visible", timeout=90000)
        time.sleep(4)

        if caption:
            editor.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            clean_caption = caption.replace("\r\n", "\n")
            page.keyboard.insert_text(clean_caption[:2200])
            time.sleep(2)
            page.keyboard.press("Escape")

        post_btn = work_ctx.locator(
            "[data-e2e='post_video_button'], button:has-text('Post'), button:has-text('Paylaş')"
        ).first
        for _ in range(40):
            try:
                disabled = post_btn.get_attribute("disabled") or post_btn.get_attribute("aria-disabled")
                if disabled not in ("true", "disabled", ""):
                    break
            except Exception:
                pass
            time.sleep(3)

        time.sleep(5)
        post_btn.scroll_into_view_if_needed()
        post_btn.click(force=True)
        log.info("TikTok Studio: clicked Post button, waiting for confirmation...")
        time.sleep(12)
        log.info("TikTok Studio post-click URL: %s", page.url)
        browser.close()
        return {
            "id": "studio_direct_post",
            "mode": "public_direct_post",
            "permalink": "https://www.tiktok.com/@yuk.az",
        }


def get_valid_access_token() -> str:
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
        raise TikTokError("Neither TIKTOK_SESSION_ID, TIKTOK_REFRESH_TOKEN, nor TIKTOK_ACCESS_TOKEN is configured")
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
    session_id = os.environ.get("TIKTOK_SESSION_ID", "").strip()
    if session_id:
        try:
            return publish_tiktok_studio_session(video, caption, session_id)
        except Exception as e:
            log.warning("TikTok Studio session upload failed (%s), falling back to API", e)

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
