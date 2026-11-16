import json
import sys
import tempfile
import types
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

sys.modules.setdefault("gdown", types.SimpleNamespace())
sys.modules.setdefault("anthropic", types.SimpleNamespace())
sys.modules.setdefault("openai", types.SimpleNamespace())
plan_stub = types.ModuleType("autopost.plan")
plan_stub.BAKU = timezone(timedelta(hours=4))
sys.modules.setdefault("autopost.plan", plan_stub)

from autopost import drive, publish, tiktok


class PublishRetryTests(unittest.TestCase):
    def test_public_folder_listing_ignores_native_docs(self):
        html = '''<html><head><title>Reels</title></head><body>
        <a href="https://drive.google.com/drive/folders/today-folder">2026-11-16</a>
        <a href="https://drive.google.com/file/d/video-id/view">yukaz_reel_2026-11-16.mp4</a>
        <a href="https://docs.google.com/document/d/old-doc/edit">old caption</a>
        </body></html>'''
        response = types.SimpleNamespace(text=html, raise_for_status=lambda: None)
        with mock.patch.object(drive.requests, "get", return_value=response):
            self.assertEqual(
                [("2026-11-16", "today-folder", "folder"),
                 ("yukaz_reel_2026-11-16.mp4", "video-id", "file")],
                drive._list_public_folder("root-folder"),
            )

    def test_only_requested_date_folder_is_read(self):
        def list_folder(folder_id):
            if folder_id == drive.DEFAULT_DRIVE_FOLDER_ID:
                return [("2026-11-11", "old-folder", "folder"),
                        ("2026-11-16", "today-folder", "folder")]
            self.assertEqual("today-folder", folder_id)
            return [("yukaz_reel_2026-11-16.mp4", "drive-video", "file"),
                    ("yukaz_caption_2026-11-16.txt", "drive-caption", "file")]

        def fake_download(file_id, path):
            path.write_bytes(b"video" if file_id == "drive-video" else b"caption")

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            out = Path(tmp) / "out"
            tracker = Path(tmp) / "published_drive.json"
            with (
                mock.patch.object(drive, "TRACKER_PATH", tracker),
                mock.patch.object(drive, "_list_public_folder", side_effect=list_folder) as listing,
                mock.patch.object(drive, "_download_file", side_effect=fake_download),
            ):
                date_key = drive.fetch_drive_package(out, target_date="2026-11-16")

            self.assertEqual("2026-11-16", date_key)
            self.assertEqual(b"video", (out / "reel.mp4").read_bytes())
            self.assertEqual("caption", (out / "caption.txt").read_text())
            self.assertEqual(2, listing.call_count)
            plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual("2026-11-16", plan["date"])

    def test_published_manual_date_is_not_downloaded_again(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            out = Path(tmp) / "out"
            tracker = Path(tmp) / "published_drive.json"
            tracker.write_text(json.dumps({"published_dates": ["2026-11-16"]}), encoding="utf-8")
            with (mock.patch.object(drive, "TRACKER_PATH", tracker),
                  mock.patch.object(drive, "_list_public_folder") as listing):
                self.assertEqual("2026-11-16", drive.fetch_drive_package(out, target_date="2026-11-16"))
                listing.assert_not_called()
            self.assertEqual("2026-11-16", (out / "already_published.txt").read_text())

    def test_wrong_date_video_is_rejected(self):
        entries = [("yukaz_reel_2026-11-15.mp4", "old-video", "file")]
        self.assertIsNone(drive._pick_file(entries, "2026-11-16", "video"))

    def test_inbox_draft_is_not_success(self):
        self.assertFalse(
            publish._is_successful_result(
                {"id": "draft-id", "mode": "inbox_draft", "permalink": "Inbox draft"}
            )
        )
        self.assertTrue(publish._is_successful_result({"id": "video-id", "mode": "public_direct_post"}))

    def test_partial_results_are_recorded_without_completing_date(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            tracker = Path(tmp) / "published_drive.json"
            with mock.patch.object(drive, "TRACKER_PATH", tracker):
                drive.record_publish_results(
                    "2026-11-03",
                    {
                        "instagram": {"id": "ig-1"},
                        "facebook": {"id": "fb-1"},
                        "tiktok": {"error": "session expired"},
                    },
                    complete=False,
                )
                data = json.loads(tracker.read_text(encoding="utf-8"))
                self.assertNotIn("2026-11-03", data["published_dates"])
                self.assertEqual("ig-1", drive.load_publish_results("2026-11-03")["instagram"]["id"])

                drive.record_publish_results(
                    "2026-11-03",
                    {"tiktok": {"id": "tt-1", "mode": "public_direct_post"}},
                    complete=True,
                )
                data = json.loads(tracker.read_text(encoding="utf-8"))
                self.assertIn("2026-11-03", data["published_dates"])
                self.assertEqual("ig-1", data["history"]["2026-11-03"]["results"]["instagram"]["id"])

    def test_tiktok_never_falls_back_to_inbox(self):
        class Response:
            status_code = 403
            content = b"{}"

            @staticmethod
            def json():
                return {"error": {"code": "unaudited_client_can_only_post_to_private_accounts"}}

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            video = Path(tmp) / "video.mp4"
            video.write_bytes(b"video")
            with (
                mock.patch.dict(tiktok.os.environ, {"TIKTOK_SESSION_ID": "legacy-cookie"}, clear=False),
                mock.patch.object(tiktok, "get_valid_access_token", return_value="token"),
                mock.patch.object(tiktok.requests, "post", return_value=Response()) as post,
            ):
                with self.assertRaisesRegex(tiktok.TikTokError, "Content Posting API audit"):
                    tiktok.publish_tiktok(video, "caption")

            self.assertEqual(1, post.call_count)
            self.assertNotIn("/inbox/", post.call_args.args[0])

    def test_tiktok_retries_then_publishes_publicly(self):
        success = {
            "id": "publish-1",
            "mode": "direct_post (PUBLIC_TO_EVERYONE)",
            "permalink": "https://www.tiktok.com/@yuk.az",
        }
        with (
            mock.patch.object(
                tiktok,
                "publish_tiktok",
                side_effect=[tiktok.TikTokError("temporary error"), success],
            ) as post,
            mock.patch.object(publish.time, "sleep") as sleep,
        ):
            result = publish._publish_tiktok_with_retry(
                Path("video.mp4"),
                "caption",
                None,
                attempts=6,
                delay_seconds=300,
            )

        self.assertEqual(success, result)
        self.assertEqual(2, post.call_count)
        sleep.assert_called_once_with(300)

    def test_tiktok_stops_after_retry_limit(self):
        with (
            mock.patch.object(
                tiktok,
                "publish_tiktok",
                side_effect=tiktok.TikTokError("still blocked"),
            ) as post,
            mock.patch.object(publish.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(tiktok.TikTokError, "still blocked"):
                publish._publish_tiktok_with_retry(
                    Path("video.mp4"),
                    "caption",
                    None,
                    attempts=3,
                    delay_seconds=10,
                )

        self.assertEqual(3, post.call_count)
        self.assertEqual([mock.call(10), mock.call(10)], sleep.call_args_list)

    def test_tiktok_audit_error_is_not_retried(self):
        with (
            mock.patch.object(
                tiktok,
                "publish_tiktok",
                side_effect=tiktok.TikTokError("unaudited_client_can_only_post_to_private_accounts"),
            ) as post,
            mock.patch.object(publish.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(tiktok.TikTokError, "unaudited_client"):
                publish._publish_tiktok_with_retry(
                    Path("video.mp4"), "caption", None, attempts=6, delay_seconds=300,
                )
        post.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
