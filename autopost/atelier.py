"""Atelier mode: a brand-new hand-authored HyperFrames composition every day.

The LLM writes the full composition (index.html) for today's topic and creative
direction, following OpenMontage's HyperFrames composition contract and bespoke-
composition craft rules. Every attempt goes through:

  static guards → `hyperframes lint` → `hyperframes check` → snapshot contact sheet
  → LLM art-director review (score 1–10)

Failures and low scores are fed back for a fix pass (max ATTEMPTS). If nothing
passes, build.py falls back to the fixed template so a day is never empty.
"""
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from . import llm
from .plan import ROOT

log = logging.getLogger("autopost.atelier")
HF = "hyperframes@0.8.156"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"
ATTEMPTS = 3
PASS_SCORE = 7
DURATION = 21.0
ENDCARD = 16.5
SNAP_TIMES = [0.6, 3.5, 7.0, 10.5, 14.0, 18.8]

# One creative direction per day (rotates). Each must look nothing like the others.
CONCEPTS = [
    "Paper cut-out diorama: layered cardstock shapes with soft drop shadows, parallax depth, pieces sliding in like a pop-up book.",
    "Origami: boxes and furniture fold themselves out of flat orange paper sheets with crisp crease lines.",
    "Isometric city block of Baku: tiny isometric buildings, a parcel cube travels along streets, camera glides over the grid.",
    "Blueprint / technical drawing: white line-art on deep navy grid that draws itself (SVG stroke draw), then fills with brand colour.",
    "Night neon: dark violet city skyline with glowing orange neon outlines (Flame Towers), light trails, soft bloom using layered strokes.",
    "Map journey: stylised map of Azerbaijan-like regions with a dotted route drawing between pins, pins pop with springs.",
    "Bold Swiss typography poster: huge cropped geometric shapes, strict grid, words and blocks slamming on beat.",
    "Conveyor belt factory: boxes ride a moving belt, get wrapped, taped and stamped with the cube logo.",
    "Puzzle: a home is assembled piece by piece from jigsaw pieces snapping into place with overshoot.",
    "Day-to-night split screen: the same street transforms from morning to night as a wipe crosses the frame.",
    "Unboxing macro: extreme close-up camera inside a box opening, items rising out in slow, satisfying arcs.",
    "Building blocks / toy style: chunky rounded 3D-ish blocks stack into a house, playful bounces and squash.",
    "Retro 80s sunset grid: synthwave perspective grid, big sun with stripes, chrome-ish orange type.",
    "Ink line animation: single continuous orange line draws furniture, a road and a house in one stroke.",
    "Floating islands: each room of a home is a small floating island; pieces hop between islands to the new home.",
    "Stacked cards carousel: content cards swipe in 3D perspective like a premium app showcase.",
    "Weather of moving: calm after the storm — rain clouds disappear as boxes arrive, sun comes out over a new home.",
    "Kinetic geometry: circles, squares and the cube's three rhombi morph and orbit to tell the story abstractly.",
    "Mosaic tiles: Azerbaijani-pattern inspired tiles flip to reveal each scene (tasteful, modern geometric pattern).",
    "Elevator ride: a vertical journey floor by floor through a building, doors open on each scene.",
    "Clock & time: a big analog clock face, hands sweep, each hour reveals a step of the move (7/24 feeling).",
    "Shadow theatre: warm backlit screen, silhouettes of furniture and boxes move gracefully.",
    "Caspian seaside: soft waves, boulevard lamps, a calm teal-and-orange palette, the cube rides along the coast.",
    "Checklist UI: a beautiful oversized checklist where each item ticks with a satisfying stroke-draw check.",
    "Rubber-hose cartoon: bouncy, characterful boxes with tiny legs walking to the new home (no faces needed).",
    "Glassmorphism: frosted translucent panels over warm blurred colour blobs, crisp white type, premium UI feel.",
    "Spiral camera: the camera spirals out from the logo cube revealing the whole world around it.",
    "Pixel / voxel: chunky pixel-art moving day, crisp steps(), bright brand colours, nostalgic but premium.",
    "Gift wrapping: every item is carefully wrapped like a present — ribbons, bows, the brand promise of care.",
    "Window frames: the story is seen through a row of windows of an apartment building, each window a scene.",
]

LOGO_SNIPPET = """<!-- Yük.az logo lockup (use EXACTLY these shapes/colours; scale with the wrapper) -->
<div class="logo-lockup" style="display:flex;align-items:center;gap:28px">
  <svg viewBox="-96 -110 192 220" style="width:150px;height:172px;display:block;overflow:visible">
    <g stroke="#ffffff" stroke-width="7" stroke-linejoin="round">
      <polygon points="0,-100 86.6,-50 0,0 -86.6,-50" fill="#ff4c00"/>
      <polygon points="-86.6,-50 0,0 0,100 -86.6,50" fill="#444444"/>
      <polygon points="0,0 86.6,-50 86.6,50 0,100" fill="#ff4c00"/>
    </g>
  </svg>
  <div style="font-family:Poppins;font-weight:600;font-size:128px;line-height:1;color:#444444;display:flex;align-items:center">
    <span>yük</span><span style="display:inline-block;width:30px;height:30px;border-radius:50%;background:#ff4c00;margin:24px 22px 0"></span><span>az</span>
  </div>
</div>
(On dark backgrounds, place the lockup on a white rounded panel so the grey stays readable.)"""

SKELETON = """<!doctype html>
<html lang="az">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080, height=1920" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
  @font-face { font-family: "Poppins"; font-weight: 500; src: url("assets/fonts/Poppins-Medium.ttf"); }
  @font-face { font-family: "Poppins"; font-weight: 600; src: url("assets/fonts/Poppins-SemiBold.ttf"); }
  @font-face { font-family: "Poppins"; font-weight: 700; src: url("assets/fonts/Poppins-Bold.ttf"); }
  @font-face { font-family: "Poppins"; font-weight: 800; src: url("assets/fonts/Poppins-ExtraBold.ttf"); }
  @font-face { font-family: "Poppins"; font-weight: 900; src: url("assets/fonts/Poppins-Black.ttf"); }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: 1080px; height: 1920px; overflow: hidden; background: #fff; }
  #root { position: relative; width: 1080px; height: 1920px; overflow: hidden; font-family: "Poppins", sans-serif; }
  .scene { position: absolute; inset: 0; width: 1080px; height: 1920px; overflow: hidden; }
  .bg { position: absolute; inset: 0; }
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="21" data-width="1080" data-height="1920">
  <audio id="bgm" src="assets/music.wav" data-start="0" data-duration="21" data-track-index="10" data-volume="1"></audio>
  <section id="s1" class="scene clip" data-start="0" data-duration="3.1" data-track-index="1" style="z-index:1">
    <div class="bg" style="background:#fff3ea"></div>
    <!-- … -->
  </section>
  <!-- more scenes; overlapping clips use different data-track-index; stacking via z-index -->
</div>
<script>
  window.__timelines = window.__timelines || {};
  const tl = gsap.timeline({ paused: true });
  // all tweens at ABSOLUTE times, e.g. tl.fromTo("#s1-title", {yPercent:110}, {yPercent:0, duration:0.6, ease:"expo.out"}, 0.2);
  window.__timelines["main"] = tl;
  tl.seek(0);
</script>
</body>
</html>"""

SYSTEM = f"""You are a senior motion designer AND a HyperFrames engineer working inside OpenMontage (atelier / bespoke-composition mode).
You hand-author ONE complete HyperFrames composition (a single index.html) for a 9:16 Instagram/Facebook Reel for the brand Yük.az — a moving & cargo company in Azerbaijan.
The result must look like a premium agency motion-design piece: rich layered flat-vector illustration, confident typography, smooth physical motion. Never a slideshow.

## Format
1080×1920, 30 fps, exactly {DURATION:g} s. Music is 120 BPM: a beat every 0.5 s — land key hits and scene cuts on multiples of 0.5 s.

## Story beats (times are fixed)
- 0.0–~2.5 s HOOK: show the hook text. The very first frame (t=0) must already be a designed, non-blank frame and motion must start immediately.
- ~2.5–{ENDCARD} s STORY: 2–4 scenes that visualise today's topic in today's creative direction. Show journey_1 + journey_2 together in one scene, and final_1 + final_2 (final_2 highlighted in orange) as the payoff just before the end card.
- {ENDCARD}–{DURATION:g} s END CARD: Yük.az logo lockup (snippet below), the slogan, and a phone pill (orange rounded pill, white bold phone number with a small phone icon). Everything readable and still for at least the last 2.5 s (gentle ambient motion only).

## Text rules (critical — the client asked for very little, calm, tidy text)
- On-screen words: ONLY the provided hook, journey_1, journey_2, final_1, final_2, slogan, phone. No other words, labels, numbers or fake UI text anywhere.
- Poppins only (weights 500–900 are loaded). Mixed case, never all caps for sentences. Hook 80–100 px, other lines 60–84 px, phone 48–56 px.
- At most two lines of text visible at the same time. Each text stays fully readable (static) ≥1.2 s.
- Text safe area: x 80–1000, y 240–1560 (Instagram UI covers the rest). Never clip or overlap text with illustration.
- Contrast: dark ink #141414 on light backgrounds, white on dark backgrounds; orange #ff4c00 only for the highlighted words.
- Text entrances: masked slide-up reveals, soft spring pops or word staggers — never typewriter, never shaking.

## Brand
Colours: orange #ff4c00 / #ff6a00, peach #ffc9a5, cream #fff3ea, sand #f4d6be, logo grey #444444, ink #141414, white. You may add at most two accent colours that suit today's direction (e.g. sage #6e9c6a, navy #1b2140, teal #2f8f8a).
Illustration: flat vector built from inline SVG and CSS shapes, rounded and friendly, layered for depth (background / midground / foreground). Subjects: boxes, furniture, appliances, homes, rooms, streets, Baku skyline (Flame Towers), maps, routes, the isometric logo cube.
FORBIDDEN: trucks, vans, any vehicles; human faces; photos or external images; external fonts; emoji; large soft radial-gradient glows (they band in video).
{LOGO_SNIPPET}

## Craft (OpenMontage bespoke-composition rules)
- Commit to today's creative direction and make it unmistakable. Every scene has a DIFFERENT primary subject and composition (centred vs split vs off-grid, close vs wide). No hero element reused as the scaffold of every scene.
- Compose 2–4 motion techniques per beat: multi-phase camera (push/pull on a .world wrapper), parallax depth layers, spring-pop entrances, SVG stroke draw (strokeDasharray/strokeDashoffset), center-outward expansion, masked reveals, scale-swap / zoom-through transitions, staggered build-ups, motion-blur streaks (stretched semi-transparent ghosts).
- Disney principles: anticipation before big moves, overshoot + settle, follow-through, arcs, stagger. Use at least 3 different eases (e.g. expo.out, back.out(1.7), power3.inOut, sine.inOut, elastic.out(1,0.4)).
- Keep subtle ambient motion so nothing is frozen for more than ~1 s (except the final 2.5 s).
- Scene transitions must be designed (wipes, masks, zoom-through, morph), never hard cuts to blank.

## HyperFrames technical contract (violations break the render)
- Root: <div id="root" data-composition-id="main" data-start="0" data-duration="21" data-width="1080" data-height="1920">, explicitly sized. Put the scene fill on a full-bleed child (.bg), never on #root.
- Every timed element (scenes, overlays, wipes) needs class="clip", a unique id, data-start, data-duration, data-track-index. Clips that overlap in time must use different track indexes; visual stacking is controlled ONLY by CSS z-index.
- Keep the provided <audio id="bgm" …> as a direct child of #root, unchanged.
- Exactly one timeline: const tl = gsap.timeline({{paused:true}}) built synchronously at load, registered as window.__timelines["main"] = tl; end with tl.seek(0). All positions are ABSOLUTE times in seconds.
- Use tl.fromTo for entrances (explicit from AND to). If an element/property gets a second fromTo later, add immediateRender:false to the later one. Prefer tl.to for exits.
- Never put a CSS transform on an element that GSAP animates (set initial state with fromTo instead). Never gsap.set later-scene elements at load (use tl.set(sel, vars, time)).
- Animate only: x, y, xPercent, yPercent, scale, scaleX, scaleY, rotation, opacity, color, backgroundColor, borderRadius, strokeDashoffset, attr on SVG. Never display/visibility/width/height/top/left.
- Deterministic: no Math.random, Date.now, performance.now, requestAnimationFrame, setTimeout, event listeners, network fetches. No repeat:-1 (finite repeats that end before 21 s). Seeded pseudo-random only if needed.
- Transformed elements must be block-level with a real size (not inline spans). No <br> in text; use sized containers / flex.
- Unique ids across the page; stable id selectors for every GSAP target.
- Only external resource allowed: the GSAP script in the skeleton. Fonts: the @font-face rules in the skeleton.
- Keep it to ≤ 700 lines, clean and readable.

## Skeleton (follow this structure)
{SKELETON}

## Output
Return JSON: concept_title (short, English), scene_plan (one line per scene), scene_cuts (seconds of the major scene transitions, on 0.5 s beats, between 1 and {ENDCARD}), html (the complete index.html)."""

REVIEW_SYSTEM = """You are the creative director of a top motion-design studio reviewing frames of a 9:16 Instagram Reel for Yük.az (moving company).
You get one contact sheet with 6 labelled frames (t = time in seconds). Judge it like a client-facing deliverable.
Score 1–10 (7 = good enough to post, 9 = award-worthy). List concrete, fixable issues, each naming the frame time:
overlapping / clipped / cut-off text, text outside the safe area, low contrast, blank or near-empty frames, broken or misaligned layout,
crude or unrecognisable illustration, ugly colour clashes, end card without a clear logo + phone, too much text, wrong language/typos (Azerbaijani).
Return JSON: score, issues (list of short sentences)."""


class Composition(BaseModel):
    concept_title: str
    scene_plan: list[str]
    scene_cuts: list[float]
    html: str


class Review(BaseModel):
    score: int
    issues: list[str]


def concept_for(day: int) -> str:
    return CONCEPTS[day % len(CONCEPTS)]


def _brief(plan: dict) -> str:
    t = plan["texts"]
    return (
        f"Topic of the day (Azerbaijani brief): {plan['topic_brief']}\n"
        f"Creative direction of the day: {concept_for(plan['day'])}\n\n"
        "Exact on-screen texts (copy them character-for-character, Azerbaijani):\n"
        f"- hook: {t['hook']}\n- journey_1: {t['journey_1']}\n- journey_2: {t['journey_2']}\n"
        f"- final_1: {t['final_1']}\n- final_2 (orange highlight): {t['final_2']}\n"
        f"- slogan: {plan['slogan']}\n- phone: {plan['phone']}\n"
    )


def _run(cmd, cwd, timeout=600):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def static_problems(html: str, plan: dict) -> list[str]:
    probs = []
    must = ['data-composition-id="main"', 'window.__timelines["main"]', 'id="bgm"', 'data-duration="21"']
    probs += [f"missing required contract piece: {m}" for m in must if m not in html]
    if re.search(r"Math\.random|Date\.now|performance\.now|requestAnimationFrame|setTimeout|repeat:\s*-1", html):
        probs.append("uses a non-deterministic API or repeat:-1 (forbidden)")
    urls = set(re.findall(r"https?://[^\s\"')]+", html)) - {"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"}
    if urls:
        probs.append(f"external resources are forbidden: {sorted(urls)[:5]}")
    if "<img" in html.lower():
        probs.append("<img> is forbidden — draw everything with inline SVG/CSS")
    for key in ("hook", "final_2"):
        if plan["texts"][key] not in html:
            probs.append(f"exact text for {key} not found: {plan['texts'][key]!r}")
    if plan["phone"] not in html:
        probs.append(f"phone number {plan['phone']!r} not found in end card")
    return probs


def contact_sheet(snap_dir: Path, out_jpg: Path) -> Path | None:
    frames = sorted(snap_dir.glob("frame-*.png"))
    if len(frames) < 3:
        return None
    w, h = 360, 640
    sheet = Image.new("RGB", (w * 3, (h + 40) * 2), "white")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(ROOT / "template" / "assets" / "fonts" / "Poppins-SemiBold.ttf"), 26)
    for i, (f, t) in enumerate(zip(frames, SNAP_TIMES)):
        x, y = (i % 3) * w, (i // 3) * (h + 40)
        d.text((x + 12, y + 4), f"t = {t:g} s", fill=(20, 20, 20), font=font)
        sheet.paste(Image.open(f).convert("RGB").resize((w, h)), (x, y + 40))
    sheet.save(out_jpg, quality=88)
    return out_jpg


def prepare_workspace(ws: Path, html: str, plan: dict, cuts: list[float]):
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "assets").mkdir(parents=True)
    shutil.copytree(ROOT / "template" / "assets" / "fonts", ws / "assets" / "fonts")
    shutil.copy(ROOT / "template" / "hyperframes.json", ws / "hyperframes.json")
    (ws / "index.html").write_text(html, encoding="utf-8")
    raw = ws / "assets" / "music_raw.wav"
    cut_arg = ",".join(f"{c:.2f}" for c in cuts)
    subprocess.run([sys.executable, "-m", "autopost.music", str(raw), "--mode", "bed", "--cuts", cut_arg,
                    "--endcard", str(ENDCARD), "--transpose", str(plan["transpose"]), "--seed", str(plan["seed"])],
                   cwd=ROOT, check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", str(ws / "assets" / "music.wav")], check=True)
    raw.unlink()


def evaluate(ws: Path, plan: dict, html: str) -> tuple[list[str], Review | None, Path | None]:
    """Return (blocking problems, review, contact sheet)."""
    probs = static_problems(html, plan)
    if probs:
        return probs, None, None
    code, out = _run([NPX, "--yes", HF, "lint", "."], ws)
    out = _strip_ansi(out)
    if code != 0 or re.search(r"[1-9]\d* error\(s\)", out):
        errs = [l.strip() for l in out.splitlines() if "✗" in l or "Fix:" in l][:20]
        return ["hyperframes lint errors:"] + (errs or [out[-2000:]]), None, None
    code, out = _run([NPX, "--yes", HF, "check", "."], ws, timeout=900)
    if code != 0:
        return ["hyperframes check failed:", _strip_ansi(out)[-2500:]], None, None
    snap_dir = (ws.parent / f"{ws.name}-snaps").resolve()
    shutil.rmtree(snap_dir, ignore_errors=True)
    code, out = _run([NPX, "--yes", HF, "snapshot", ".", "--no-end", "--timeout", "20000", "-o", str(snap_dir),
                      "--at", ",".join(f"{t:g}" for t in SNAP_TIMES)], ws, timeout=900)
    sheet = contact_sheet(snap_dir, (ws.parent / f"{ws.name}-sheet.jpg").resolve()) if code == 0 else None
    if sheet is None:
        return ["snapshot capture failed: " + _strip_ansi(out)[-1500:]], None, None
    review = llm.structured(REVIEW_SYSTEM, f"Today's texts and brief:\n{_brief(plan)}", Review,
                            images=[sheet], max_tokens=3000, label=f"review-{ws.name.rsplit('-', 1)[-1]}")
    return [], review, sheet


def create(plan: dict, work: Path) -> dict | None:
    """Try to produce an approved bespoke composition. Returns info dict (with 'workspace') or None."""
    if llm.provider() is None:
        log.warning("atelier needs an LLM key — skipping")
        return None
    best = None
    feedback, prev_html = None, None
    for attempt in range(1, ATTEMPTS + 1):
        if feedback is None:
            prompt = _brief(plan) + "\nWrite today's composition."
        else:
            prompt = (_brief(plan) + "\nYour previous composition had these problems:\n- " + "\n- ".join(feedback)
                      + "\n\nFix ALL of them and return the corrected complete composition. Keep what works."
                      + f"\n\nPrevious index.html:\n```html\n{prev_html}\n```")
        log.info("atelier attempt %d/%d — %s", attempt, ATTEMPTS, concept_for(plan["day"])[:60])
        comp = llm.structured(SYSTEM, prompt, Composition, max_tokens=24000, label=f"compose-{attempt}")
        if comp is None:
            feedback = feedback or ["the previous request failed; produce a valid, complete composition"]
            continue
        cuts = sorted(c for c in comp.scene_cuts if 1.0 <= c <= ENDCARD)
        ws = work / f"atelier-{attempt}"
        prepare_workspace(ws, comp.html, plan, cuts)
        probs, review, sheet = evaluate(ws, plan, comp.html)
        prev_html = comp.html
        if probs:
            log.warning("attempt %d blocked: %s", attempt, probs[:3])
            feedback = probs
            continue
        score = review.score if review else 0
        issues = review.issues if review else ["review unavailable"]
        log.info("attempt %d review: %s/10 — %s", attempt, score, issues[:3])
        info = {"workspace": ws, "concept": comp.concept_title, "direction": concept_for(plan["day"]),
                "scene_plan": comp.scene_plan, "score": score, "issues": issues, "attempt": attempt,
                "sheet": str(sheet)}
        if best is None or score > best["score"]:
            best = info
        if score >= PASS_SCORE:
            return info
        feedback = issues
    if best and best["score"] >= 5:
        log.warning("no attempt reached %d/10; using best (%s/10)", PASS_SCORE, best["score"])
        return best
    return None


def describe(info: dict) -> str:
    return json.dumps({k: v for k, v in info.items() if k != "workspace"}, ensure_ascii=False)
