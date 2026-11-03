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
    def test_flat_month_folder_is_bound_to_requested_date(self):
        source = types.SimpleNamespace(path="166 Yükdaşıma - Youtube Gəncə.mp4", id="drive-video")

        def fake_download(*, id, output, quiet):
            self.assertEqual("drive-video", id)
            Path(output).write_bytes(b"video")

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            out = Path(tmp) / "out"
            tracker = Path(tmp) / "published_drive.json"
            with (
                mock.patch.object(drive, "TRACKER_PATH", tracker),
                mock.patch.object(drive.gdown, "download_folder", return_value=[source], create=True),
                mock.patch.object(drive.gdown, "download", side_effect=fake_download, create=True),
            ):
                date_key = drive.fetch_drive_package(out, target_date="2026-11-03")

            self.assertEqual("2026-11-03", date_key)
            self.assertEqual(b"video", (out / "reel.mp4").read_bytes())
            plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual("2026-11-03", plan["date"])

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


if __name__ == "__main__":
    unittest.main()
