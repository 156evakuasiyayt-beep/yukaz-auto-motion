import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from autopost import meta


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg tools are required")
class InstagramVideoTests(unittest.TestCase):
    def test_normalizes_non_h264_video_for_instagram(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            source = Path(tmp) / "source.mp4"
            output = Path(tmp) / "normalized.mp4"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                 "-i", "color=c=red:s=320x568:d=1", "-c:v", "mpeg4", str(source)],
                check=True,
            )

            meta._normalize_instagram_video(source, output)

            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_name,codec_type,pix_fmt,r_frame_rate", "-of", "json", str(output)],
                check=True, capture_output=True, text=True,
            )
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual("h264", stream["codec_name"])
            self.assertEqual("yuv420p", stream["pix_fmt"])
            self.assertEqual("30/1", stream["r_frame_rate"])
            self.assertGreater(output.stat().st_size, 0)

    def test_rejects_unreadable_video_before_creating_instagram_container(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            source = Path(tmp) / "corrupt.mp4"
            source.write_bytes(b"not a video")
            with self.assertRaisesRegex(meta.MetaError, "normalization failed"):
                meta._normalize_instagram_video(source, Path(tmp) / "normalized.mp4")


if __name__ == "__main__":
    unittest.main()
