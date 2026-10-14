"""Build today's reel: plan → bespoke composition (atelier) or template → render → cover.

VIDEO_MODE env: atelier (default — a brand-new AI-authored composition every day, falls back
to the template if it can't pass QA) | template (the fixed "Qutunun səyahəti" choreography).

Usage:  python -m autopost.build [--out out] [--date YYYY-MM-DD]
Outputs in --out: reel.mp4, cover.jpg, caption.txt, plan.json
"""
import argparse
import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import atelier
from .plan import ROOT, make_plan
from .scenes import fill_template

HF_VERSION = "0.8.156"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"
log = logging.getLogger("autopost.build")


def run(cmd, **kw):
    log.info("$ %s", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def build_workspace(plan: dict, ws: Path):
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(ROOT / "template", ws)
    tpl = (ws / "index.html").read_text(encoding="utf-8")
    html = fill_template(tpl, texts=plan["texts"], room_set=plan["room_set"], palette=plan["palette"],
                         phone=plan["phone"], seed=plan["seed"])
    (ws / "index.html").write_text(html, encoding="utf-8")

    raw = ws / "assets" / "music_raw.wav"
    run([sys.executable, "-m", "autopost.music", str(raw), "--transpose", str(plan["transpose"]),
         "--seed", str(plan["seed"])], cwd=ROOT)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", str(ws / "assets" / "music.wav")])
    raw.unlink()


def render(ws: Path, out_mp4: Path):
    run([NPX, "--yes", f"hyperframes@{HF_VERSION}", "render", "--quiet", "--quality", "high",
         "-o", str(out_mp4.resolve())], cwd=ws)


# ----------------------------------------------------------------------------- cover
def _font(weight: str, size: int):
    return ImageFont.truetype(str(ROOT / "template" / "assets" / "fonts" / f"Poppins-{weight}.ttf"), size)


def _wrap(draw, text, font, max_w):
    words = text.split()
    if draw.textlength(text, font=font) <= max_w or len(words) < 2:
        return [text]
    # two lines: pick the split that best balances the widths
    splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    a, b = min(splits, key=lambda p: max(draw.textlength(p[0], font=font), draw.textlength(p[1], font=font)))
    if max(draw.textlength(a, font=font), draw.textlength(b, font=font)) <= max_w:
        return [a, b]
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def make_cover(video: Path, title: str, out_jpg: Path, at: float = 10.2):
    frame = out_jpg.with_suffix(".frame.png")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(at), "-i", str(video),
         "-frames:v", "1", str(frame)])
    img = Image.open(frame).convert("RGB")
    frame.unlink()
    W, H = img.size

    # soft cream panel behind the title, inside the 4:5 grid-safe area (y 285 – 1635)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle((70, 330, W - 70, 760), radius=48, fill=(255, 248, 242, 255))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    d = ImageDraw.Draw(img)

    font = _font("Bold", 96)
    lines = _wrap(d, title, font, W - 220)
    while len(lines) > 3 and font.size > 60:
        font = _font("Bold", font.size - 8)
        lines = _wrap(d, title, font, W - 220)
    lh = int(font.size * 1.22)
    y = 545 - (len(lines) * lh) // 2
    for i, line in enumerate(lines):
        color = (255, 76, 0) if i == len(lines) - 1 and len(lines) > 1 else (20, 20, 20)
        d.text((W / 2, y + i * lh), line, font=font, fill=color, anchor="ma")

    # logo lockup (vector cube + wordmark) near the bottom of the safe area
    s, cy, wf = 62, 1520, _font("SemiBold", 92)
    cube_half = 86.6 * s / 100
    word_w = d.textlength("yük", font=wf) + 22 + 44 + d.textlength("az", font=wf)
    total = 2 * cube_half + 40 + word_w
    cx = W / 2 - total / 2 + cube_half
    d.rounded_rectangle((W / 2 - total / 2 - 60, cy - 100, W / 2 + total / 2 + 60, cy + 100), radius=100,
                        fill=(255, 255, 255))
    pts = lambda p: [(cx + x * s / 100, cy + y * s / 100) for x, y in p]
    for poly, col in (([(0, -100), (86.6, -50), (0, 0), (-86.6, -50)], (255, 84, 16)),
                      ([(-86.6, -50), (0, 0), (0, 100), (-86.6, 50)], (68, 68, 68)),
                      ([(0, 0), (86.6, -50), (86.6, 50), (0, 100)], (255, 76, 0))):
        d.polygon(pts(poly), fill=col, outline=(255, 255, 255), width=5)
    x = cx + cube_half + 40
    d.text((x, cy + 34), "yük", font=wf, fill=(68, 68, 68), anchor="ls")
    x += d.textlength("yük", font=wf) + 22
    d.ellipse((x, cy - 4, x + 22, cy + 18), fill=(255, 76, 0))
    x += 44
    d.text((x, cy + 34), "az", font=wf, fill=(68, 68, 68), anchor="ls")

    img.convert("RGB").save(out_jpg, quality=92)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today in Asia/Baku)")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    date = dt.date.fromisoformat(args.date) if args.date else None
    plan = make_plan(date)
    log.info("plan: %s / %s / %s (copy: %s)", plan["topic"], plan["room_set"], plan["palette"], plan["copy_source"])

    mode = (os.environ.get("VIDEO_MODE") or "atelier").lower()
    info = atelier.create(plan, out / "work") if mode == "atelier" else None
    if info:
        ws, cover_at = info["workspace"], 10.5
        plan.update(video_mode="atelier", concept=info["concept"], direction=info["direction"],
                    qa_score=info["score"], qa_issues=info["issues"], attempts=info["attempt"])
    else:
        if mode == "atelier":
            log.warning("atelier produced nothing usable — falling back to the template")
        ws, cover_at = out / "workspace", 10.2
        build_workspace(plan, ws)
        plan.update(video_mode="template", concept="Qutunun səyahəti (şablon)")
    render(ws, out / "reel.mp4")
    make_cover(out / "reel.mp4", plan["cover_title"], out / "cover.jpg", at=cover_at)
    (out / "caption.txt").write_text(plan["caption"], encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("done → %s", out)


if __name__ == "__main__":
    main()
