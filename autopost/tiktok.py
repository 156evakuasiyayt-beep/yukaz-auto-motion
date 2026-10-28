"""Publish a video to TikTok (Public Direct Post via TikTok Studio session cookie, or Content Posting API v2).

Env:
  TIKTOK_SESSION_ID     TikTok 'sessionid' cookie from logged-in browser (posts directly as Public via TikTok Studio)
  TIKTOK_ACCESS_TOKEN   OAuth2 user access token (or auto-refreshed via below vars)
  TIKTOK_CLIENT_KEY     TikTok App Client Key (for auto-refreshing token daily)
  TIKTOK_CLIENT_SECRET  TikTok App Client Secret
  TIKTOK_REFRESH_TOKEN  OAuth2 refresh token (valid for 365 days)
"""
import base64
import json
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger("autopost.tiktok")
TIKTOK_API = "https://open.tiktokapis.com/v2"


class TikTokError(RuntimeError):
    pass


def _discover_tiktok_idc(session_id: str) -> tuple[str, dict]:
    extra_cookies = {}
    raw = session_id.strip()
    if raw.startswith("[") or raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for c in parsed:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        extra_cookies[c["name"]] = str(c["value"])
                session_id = extra_cookies.get("sessionid") or extra_cookies.get("sessionid_ss") or session_id
        except Exception:
            pass
    elif "=" in raw and ";" in raw:
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                extra_cookies[k.strip()] = v.strip()
        session_id = extra_cookies.get("sessionid") or extra_cookies.get("sessionid_ss") or session_id

    log.info("Checking TikTok sessionid (len=%d, extra_cookies=%d)...", len(session_id), len(extra_cookies))

    for idc in ("alisg", "maliva", "eu-ttp2", "useast2a", "useast5", "ap-northeast-1"):
        cookies = {
            "sessionid": session_id,
            "sessionid_ss": session_id,
            "sid_tt": session_id,
            "tt-target-idc": idc,
            "store-idc": idc,
            **extra_cookies,
        }
        try:
            r = requests.get(
                "https://www.tiktok.com/passport/web/account/info/",
                cookies=cookies,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    )
                },
                timeout=15,
            )
            data = r.json() if r.content else {}
            msg = data.get("message")
            user_data = data.get("data") or {}
            uname = user_data.get("username") or user_data.get("screen_name") or user_data.get("user_id_str")
            resp_idc = r.cookies.get("tt-target-idc") or r.headers.get("x-tt-store-idc") or idc
            log.info("Probe idc=%s -> message=%s, user=%s, resp_idc=%s", idc, msg, uname, resp_idc)
            if msg == "success" and uname:
                return resp_idc, cookies
        except Exception as e:
            log.warning("Probe idc=%s error: %s", idc, e)

    return "alisg", {
        "sessionid": session_id,
        "sessionid_ss": session_id,
        "sid_tt": session_id,
        "tt-target-idc": "alisg",
        **extra_cookies,
    }


def _dismiss_tiktok_modals(page):
    """Dismisses any TikTok Studio onboarding tooltips or floating portals blocking clicks."""
    try:
        for label in ("Cancel", "Got it", "Not now", "Close", "Dismiss"):
            btn = page.locator(f"[data-floating-ui-portal] button:has-text('{label}')").first
            if btn.count() > 0 and btn.is_visible():
                btn.click(force=True)
                time.sleep(0.3)
    except Exception:
        pass
    try:
        page.evaluate(
            """() => {
                document.querySelectorAll('[data-floating-ui-portal], .joyride-portal, .react-joyride__spotlight').forEach(el => el.remove());
            }"""
        )
    except Exception:
        pass


def _set_custom_cover_ui(page, work_ctx, cover: Path):
    """Attempts to upload cover.jpg via TikTok Studio's 'Edit cover' -> 'Upload cover' modal if available."""
    try:
        # Look for 'Edit cover' button or text
        edit_cover_btn = work_ctx.locator("text='Edit cover', [class*='edit-cover'], [data-e2e*='cover']").first
        if edit_cover_btn.count() == 0:
            log.info("No 'Edit cover' button found in DOM (canvas cover interceptor is active)")
            return
        log.info("Opening 'Edit cover' dialog...")
        edit_cover_btn.click(force=True)
        time.sleep(2)

        upload_tab = page.locator("text='Upload cover'").first
        if upload_tab.count() > 0 and upload_tab.is_visible():
            log.info("Clicking 'Upload cover' tab...")
            upload_tab.click(force=True)
            time.sleep(1.5)

        img_inputs = page.locator("input[type='file'][accept*='image'], input[type='file'][accept*='png'], input[type='file'][accept*='jpg'], input[type='file'][accept*='jpeg']")
        if img_inputs.count() > 0:
            log.info("Setting cover image file on image input[type='file']: %s", cover)
            img_inputs.first.set_input_files(str(cover))
            time.sleep(3)
            confirm_btn = page.get_by_role("button", name="Confirm", exact=True).first
            if confirm_btn.count() > 0 and confirm_btn.is_visible():
                log.info("Clicking 'Confirm' on cover dialog...")
                confirm_btn.click(force=True)
                time.sleep(2)
                return
        # Close modal if Confirm wasn't found
        cancel_btn = page.get_by_role("button", name="Cancel", exact=True).first
        if cancel_btn.count() > 0 and cancel_btn.is_visible():
            cancel_btn.click(force=True)
            time.sleep(1)
    except Exception as e:
        log.warning("UI cover upload skipped (canvas cover interceptor still active): %s", e)


def _set_caption_reliably(page, work_ctx, caption: str):
    """Clears default 'reel' filename and inserts full caption into TikTok Studio editor."""
    if not caption:
        return
    clean_caption = caption.replace("\r\n", "\n")[:2200]
    editor = work_ctx.locator("[contenteditable='true']").first
    for attempt in range(3):
        _dismiss_tiktok_modals(page)
        try:
            editor.scroll_into_view_if_needed()
            editor.click(force=True)
            time.sleep(0.5)
            # Select all via JS Selection API + execCommand + keyboard
            editor.evaluate(
                """(el) => {
                    el.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    sel.removeAllRanges();
                    sel.addRange(range);
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                }"""
            )
            time.sleep(0.3)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            for _ in range(15):
                page.keyboard.press("Backspace")
                page.keyboard.press("Delete")
            time.sleep(0.3)
            page.keyboard.insert_text(clean_caption)
            time.sleep(1.5)
            page.keyboard.press("Escape")
            current_txt = (editor.inner_text() or "").strip()
            log.info("Caption check (attempt %d): len=%d, preview='%s'", attempt + 1, len(current_txt), current_txt[:80])
            if len(current_txt) >= 15 and current_txt.lower() != "reel":
                return
        except Exception as e:
            log.warning("Caption attempt %d error: %s", attempt + 1, e)
        time.sleep(1)


def _ensure_everyone_privacy(page, work_ctx):
    """Ensures 'Who can watch this video' is set to 'Everyone' (Public) and not 'Only me'."""
    try:
        _dismiss_tiktok_modals(page)
        # Look for combobox or button near 'Who can watch this video' that currently says 'Only me' or 'Friends'
        for bad_priv in ("Only me", "Friends"):
            priv_trigger = work_ctx.locator(f"[role='combobox']:has-text('{bad_priv}'), button:has-text('{bad_priv}'), [class*='select']:has-text('{bad_priv}')").first
            if priv_trigger.count() > 0 and priv_trigger.is_visible():
                log.info("Privacy dropdown currently shows '%s' — switching to 'Everyone'...", bad_priv)
                priv_trigger.scroll_into_view_if_needed()
                priv_trigger.click(force=True)
                time.sleep(1)
                everyone_opt = page.locator("[role='option']:has-text('Everyone'), li:has-text('Everyone'), div[class*='option']:has-text('Everyone')").first
                if everyone_opt.count() > 0 and everyone_opt.is_visible():
                    everyone_opt.click(force=True)
                    log.info("Selected 'Everyone' privacy option!")
                    time.sleep(1)
                    return
                # Fallback text click
                page.get_by_text("Everyone", exact=True).last.click(force=True)
                time.sleep(1)
    except Exception as e:
        log.warning("Privacy check warning: %s", e)


def publish_tiktok_studio_session(video: Path, caption: str, session_id: str, cover: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    idc, cookie_map = _discover_tiktok_idc(session_id)
    log.info("Publishing to TikTok Studio (Public) with idc=%s, cover=%s...", idc, cover)

    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--autoplay-policy=no-user-gesture-required",
    ]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True, args=launch_args)
            log.info("Launched full Google Chrome (with native H.264/MP4 support)")
        except Exception as e:
            log.warning("Chrome channel launch fallback to Chromium: %s", e)
            browser = p.chromium.launch(headless=True, args=launch_args)

        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )

        # Inject cover.jpg into HTMLCanvasElement.prototype.toBlob & toDataURL so TikTok Studio NEVER generates a black cover!
        if cover and cover.exists():
            b64_cover = base64.b64encode(cover.read_bytes()).decode("ascii")
            context.add_init_script(
                f"""(() => {{
                    const coverDataUrl = "data:image/jpeg;base64,{b64_cover}";
                    const coverImg = new Image();
                    coverImg.crossOrigin = "anonymous";
                    coverImg.src = coverDataUrl;
                    window.__customCoverImg = coverImg;

                    const origToBlob = HTMLCanvasElement.prototype.toBlob;
                    HTMLCanvasElement.prototype.toBlob = function(cb, type, quality) {{
                        try {{
                            if (window.__customCoverImg && window.__customCoverImg.complete && window.__customCoverImg.naturalWidth > 0 && this.width >= 100 && this.height >= 100) {{
                                const ctx = this.getContext('2d');
                                if (ctx) {{
                                    ctx.drawImage(window.__customCoverImg, 0, 0, this.width, this.height);
                                    console.log('[YukAz] Injected custom cover.jpg into canvas.toBlob (' + this.width + 'x' + this.height + ')');
                                }}
                            }}
                        }} catch (err) {{}}
                        return origToBlob.call(this, cb, type, quality);
                    }};

                    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
                    HTMLCanvasElement.prototype.toDataURL = function(type, quality) {{
                        try {{
                            if (window.__customCoverImg && window.__customCoverImg.complete && window.__customCoverImg.naturalWidth > 0 && this.width >= 100 && this.height >= 100) {{
                                const ctx = this.getContext('2d');
                                if (ctx) {{
                                    ctx.drawImage(window.__customCoverImg, 0, 0, this.width, this.height);
                                }}
                            }}
                        }} catch (err) {{}}
                        return origToDataURL.call(this, type, quality);
                    }};
                }})();"""
            )
            log.info("Injected custom cover.jpg (%d bytes) into browser canvas pipeline", cover.stat().st_size)

        pw_cookies = []
        for k, v in cookie_map.items():
            for domain in (".tiktok.com", "www.tiktok.com"):
                pw_cookies.append(
                    {
                        "name": k,
                        "value": v,
                        "domain": domain,
                        "path": "/",
                        "secure": True,
                        "sameSite": "None",
                    }
                )
        context.add_cookies(pw_cookies)

        page = context.new_page()
        post_api_results = []

        def on_response(resp):
            u = resp.url
            if any(k in u for k in ("/project/post", "/item/create", "/project/create")):
                try:
                    body = resp.text()[:500]
                except Exception:
                    body = "<unreadable>"
                log.info("TikTok API response [%s] %s -> %s", resp.status, u[:120], body)
                if "/project/post" in u or "/item/create" in u:
                    post_api_results.append((resp.status, body))

        page.on("response", on_response)

        page.goto("https://www.tiktok.com/tiktokstudio/upload?lang=en", wait_until="domcontentloaded", timeout=60000)
        time.sleep(10)

        log.info("TikTok Studio landed on URL: %s | Title: %s", page.url, page.title())
        if "/login" in page.url or "login" in page.title().lower():
            browser.close()
            raise TikTokError(f"TIKTOK_SESSION_ID redirected to login ({page.url})")

        _dismiss_tiktok_modals(page)

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
            log.info("Trying file chooser click...")
            with page.expect_file_chooser(timeout=20000) as fc_info:
                btn = page.locator("button:has-text('Select'), [data-e2e*='select'], [class*='upload']").first
                btn.click(force=True)
            fc_info.value.set_files(str(video))

        log.info("TikTok Studio: video file attached, waiting for editor and upload completion...")
        work_ctx = target_frame or page
        editor = work_ctx.locator("[contenteditable='true']").first
        editor.wait_for(state="visible", timeout=90000)
        time.sleep(6)

        # Wait specifically for [data-e2e='post_video_button'] to become enabled AND video upload to complete
        post_btn = work_ctx.locator("[data-e2e='post_video_button']").first
        if post_btn.count() == 0:
            post_btn = work_ctx.get_by_role("button", name="Post", exact=True).first

        for i in range(45):
            _dismiss_tiktok_modals(page)
            try:
                cls = post_btn.get_attribute("class") or ""
                disabled = post_btn.get_attribute("disabled")
                aria_dis = post_btn.get_attribute("aria-disabled")
                data_dis = post_btn.get_attribute("data-disabled")
                is_ready = (
                    disabled is None
                    and aria_dis != "true"
                    and data_dis != "true"
                    and "disabled" not in cls.lower()
                )
                if i % 3 == 0 or is_ready:
                    log.info(
                        "Upload wait (%d/45): btn_ready=%s class='%s' disabled=%s aria=%s",
                        i + 1,
                        is_ready,
                        cls[:80],
                        disabled,
                        aria_dis,
                    )
                if is_ready and i >= 4:
                    break
            except Exception as e:
                log.warning("Post button check error: %s", e)
            time.sleep(3)

        # Now that video upload is 100% complete, set cover, caption, and privacy!
        if cover and cover.exists():
            _set_custom_cover_ui(page, work_ctx, cover)

        _set_caption_reliably(page, work_ctx, caption)
        _ensure_everyone_privacy(page, work_ctx)

        time.sleep(2)
        _dismiss_tiktok_modals(page)
        post_btn.scroll_into_view_if_needed()
        time.sleep(1)

        box = post_btn.bounding_box()
        log.info("Clicking [data-e2e='post_video_button'] at box=%s, text='%s'", box, post_btn.inner_text())
        post_btn.click(force=True)

        # Wait up to 35s for post API response or redirect to /tiktokstudio/content
        for step in range(12):
            time.sleep(3)
            _dismiss_tiktok_modals(page)
            for label in ("Post now", "Continue to post", "Continue", "Confirm"):
                cbtn = page.get_by_role("button", name=label, exact=True).first
                if cbtn.count() > 0 and cbtn.is_visible():
                    log.info("Clicking secondary confirmation dialog button: %s", label)
                    cbtn.click(force=True)
            if post_api_results or "/content" in page.url:
                log.info("TikTok post confirmed! URL=%s, api_results=%s", page.url, post_api_results)
                break
            if step == 4 and not post_api_results:
                log.info("Retrying JS click on [data-e2e='post_video_button']...")
                try:
                    post_btn.evaluate("el => el.click()")
                except Exception:
                    pass

        log.info("TikTok Studio final URL: %s | post_api_results count: %d", page.url, len(post_api_results))
        try:
            body_end = " ".join((page.locator("body").inner_text(timeout=5000) or "").split())[:400]
            log.info("TikTok Studio end body: %s", body_end)
        except Exception:
            pass

        browser.close()

        if post_api_results:
            status_code, body_txt = post_api_results[-1]
            if status_code == 200 and ('"status_code":0' in body_txt.replace(" ", "") or '"item_id"' in body_txt):
                item_id = "studio_direct_post"
                permalink = "https://www.tiktok.com/@yuk.az"
                try:
                    resp_json = json.loads(body_txt)
                    resp_list = resp_json.get("single_post_resp_list") or []
                    if resp_list and resp_list[0].get("item_id"):
                        item_id = str(resp_list[0]["item_id"])
                        permalink = f"https://www.tiktok.com/@yuk.az/video/{item_id}"
                except Exception:
                    pass
                return {
                    "id": item_id,
                    "mode": "public_direct_post",
                    "permalink": permalink,
                }
            raise TikTokError(f"TikTok Studio post API returned error: {body_txt}")

        if "/content" in page.url:
            return {
                "id": "studio_direct_post",
                "mode": "public_direct_post",
                "permalink": "https://www.tiktok.com/@yuk.az",
            }

        raise TikTokError(f"TikTok Studio Post button clicked but post API did not fire (final URL: {page.url})")


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


def publish_tiktok(video: Path, caption: str, cover: Path | None = None, cover_timestamp_ms: int = 1000) -> dict:
    session_id = os.environ.get("TIKTOK_SESSION_ID", "").strip()
    if session_id:
        try:
            return publish_tiktok_studio_session(video, caption, session_id, cover=cover)
        except Exception as e:
            log.warning("TikTok Studio session upload failed (%s), falling back to OAuth2 API...", e)

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
