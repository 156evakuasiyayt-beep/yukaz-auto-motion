"""Scene library for the daily reel: illustrated items, room sets and sky palettes.

The template (template/index.html) has a fixed 21 s choreography; this module only
decides *what* fills it: which household items fly into the box, which ones spring
out in the new home, and what time of day the journey happens.
"""
import html
import json
import random

# ----------------------------------------------------------------------------- items
# Flat illustrations, no outlines. viewBox sizes are the natural aspect ratios.
ITEMS = {
    "sofa": ("0 0 300 180", """
        <rect x="30" y="20" width="240" height="90" rx="26" fill="#5b5b5b" />
        <rect x="44" y="34" width="104" height="66" rx="18" fill="#ff8a4c" /><rect x="152" y="34" width="104" height="66" rx="18" fill="#ff8a4c" />
        <rect x="18" y="92" width="264" height="58" rx="20" fill="#444" />
        <rect x="2" y="66" width="52" height="92" rx="22" fill="#5b5b5b" /><rect x="246" y="66" width="52" height="92" rx="22" fill="#5b5b5b" />
        <rect x="40" y="152" width="14" height="24" rx="4" fill="#2a2a2a" /><rect x="246" y="152" width="14" height="24" rx="4" fill="#2a2a2a" />"""),
    "lamp": ("0 0 120 370", """
        <rect x="55" y="110" width="10" height="236" fill="#444" /><ellipse cx="60" cy="352" rx="44" ry="13" fill="#444" />
        <path d="M30 10 L90 10 L116 110 L4 110 Z" fill="#ffc9a5" />"""),
    "plant": ("0 0 140 200", """
        <g class="leaves">
          <path d="M70 118 C40 90 20 80 12 44 C46 50 64 76 70 118Z" fill="#6e9c6a" />
          <path d="M70 118 C98 88 116 76 128 40 C94 46 76 74 70 118Z" fill="#5e8c61" />
          <path d="M70 118 C62 80 60 44 72 8 C86 44 82 84 70 118Z" fill="#7baa72" />
        </g>
        <path d="M30 118 L110 118 L100 196 L40 196 Z" fill="#ff4c00" /><rect x="24" y="110" width="92" height="16" rx="6" fill="#ff6a00" />"""),
    "art": ("0 0 260 200", """
        <rect x="0" y="0" width="260" height="200" rx="10" fill="#444" />
        <rect x="14" y="14" width="232" height="172" rx="4" fill="#ffc9a5" />
        <circle cx="164" cy="84" r="34" fill="#ff4c00" /><path d="M14 186 L84 104 L134 154 L174 124 L246 186 Z" fill="#444" />"""),
    "art2": ("0 0 260 200", """
        <rect x="0" y="0" width="260" height="200" rx="10" fill="#444" />
        <rect x="14" y="14" width="232" height="172" rx="4" fill="#fff3ea" />
        <circle cx="84" cy="78" r="30" fill="#ff4c00" /><path d="M14 186 L104 110 L154 150 L194 124 L246 164 L246 186 Z" fill="#5e8c61" />"""),
    "clock": ("0 0 140 140", """
        <circle cx="70" cy="70" r="62" fill="#fff" stroke="#444" stroke-width="10" />
        <line x1="70" y1="70" x2="70" y2="34" stroke="#444" stroke-width="8" stroke-linecap="round" />
        <line x1="70" y1="70" x2="96" y2="80" stroke="#444" stroke-width="8" stroke-linecap="round" />
        <circle cx="70" cy="70" r="8" fill="#ff4c00" />"""),
    "desk": ("0 0 300 170", """
        <rect x="0" y="0" width="300" height="22" rx="6" fill="#5b5b5b" />
        <rect x="14" y="22" width="14" height="148" fill="#444" />
        <rect x="190" y="22" width="96" height="148" rx="6" fill="#444" />
        <rect x="204" y="44" width="68" height="40" rx="5" fill="#5b5b5b" /><rect x="204" y="100" width="68" height="40" rx="5" fill="#5b5b5b" />
        <rect x="230" y="60" width="16" height="6" rx="3" fill="#ff8a4c" /><rect x="230" y="116" width="16" height="6" rx="3" fill="#ff8a4c" />"""),
    "chair": ("0 0 140 220", """
        <rect x="30" y="0" width="80" height="96" rx="22" fill="#444" />
        <rect x="40" y="12" width="60" height="44" rx="14" fill="#ff8a4c" />
        <rect x="16" y="100" width="108" height="30" rx="14" fill="#5b5b5b" />
        <rect x="64" y="130" width="12" height="52" fill="#2a2a2a" />
        <path d="M20 192 L120 192" stroke="#2a2a2a" stroke-width="12" stroke-linecap="round" />
        <circle cx="24" cy="208" r="9" fill="#2a2a2a" /><circle cx="116" cy="208" r="9" fill="#2a2a2a" />"""),
    "monitor": ("0 0 200 170", """
        <rect x="0" y="0" width="200" height="128" rx="12" fill="#444" />
        <rect x="12" y="12" width="176" height="104" rx="6" fill="#ffc9a5" />
        <rect x="34" y="70" width="22" height="34" fill="#ff4c00" /><rect x="66" y="52" width="22" height="52" fill="#ff6a00" />
        <rect x="98" y="38" width="22" height="66" fill="#ff4c00" /><rect x="130" y="60" width="22" height="44" fill="#ff8a4c" />
        <rect x="90" y="128" width="20" height="28" fill="#5b5b5b" /><rect x="56" y="154" width="88" height="14" rx="7" fill="#444" />"""),
    "shelf": ("0 0 260 150", """
        <rect x="18" y="20" width="34" height="110" rx="4" fill="#ff4c00" /><rect x="56" y="34" width="30" height="96" rx="4" fill="#ffc9a5" />
        <rect x="90" y="14" width="34" height="116" rx="4" fill="#5b5b5b" /><rect x="128" y="30" width="30" height="100" rx="4" fill="#ff8a4c" />
        <rect x="170" y="72" width="64" height="58" rx="6" fill="#444" /><circle cx="202" cy="62" r="18" fill="#7baa72" />
        <rect x="0" y="130" width="260" height="16" rx="5" fill="#444" />"""),
    "fridge": ("0 0 150 279", """
        <rect x="6" y="4" width="138" height="266" rx="22" fill="#e6ded6" />
        <rect x="6" y="94" width="138" height="8" fill="#cfc5bc" />
        <rect x="112" y="34" width="10" height="40" rx="5" fill="#444" /><rect x="112" y="118" width="10" height="60" rx="5" fill="#444" />
        <circle cx="40" cy="44" r="9" fill="#ff4c00" /><rect x="30" y="130" width="34" height="24" rx="4" fill="#ffc9a5" />
        <rect x="22" y="268" width="16" height="10" fill="#444" /><rect x="112" y="268" width="16" height="10" fill="#444" />"""),
    "washer": ("0 0 180 200", """
        <rect x="4" y="4" width="172" height="192" rx="18" fill="#e6ded6" />
        <rect x="4" y="4" width="172" height="34" rx="18" fill="#d4c9bf" />
        <circle cx="30" cy="21" r="7" fill="#ff4c00" /><rect x="110" y="16" width="50" height="10" rx="5" fill="#444" />
        <circle cx="90" cy="115" r="58" fill="#444" /><circle cx="90" cy="115" r="44" fill="#ffc9a5" />
        <path d="M50 120 Q90 96 130 120 L130 132 Q90 158 50 132 Z" fill="#ff8a4c" />"""),
    "tv": ("0 0 240 150", """
        <rect x="0" y="0" width="240" height="150" rx="12" fill="#444" />
        <rect x="10" y="10" width="220" height="130" rx="6" fill="#ff8a4c" />
        <circle cx="160" cy="60" r="22" fill="#fff3ea" />
        <path d="M10 140 L80 80 L130 120 L170 95 L230 135 L230 140 Z" fill="#444" />"""),
}

# ----------------------------------------------------------------------------- room sets
# Each entry: (item, left, top, width, height[, flags]).  Room A = old home (items fly
# INTO the box, 5 items, on the beat).  Room B = new home (items spring OUT).
# Flags: "swing" (wall item swings on its nail), "grow" (plant leaves grow), "glow" (lamp).
ROOM_SETS = {
    "home": {
        "label": "ev",
        "A": [("art", 620, 470, 260, 200), ("clock", 840, 760, 140, 140), ("lamp", 750, 980, 120, 370),
              ("plant", 890, 1150, 140, 200), ("sofa", 40, 1124, 380, 228)],
        "B": [("sofa", 330, 1124, 420, 252), ("lamp", 120, 980, 120, 370, "glow"),
              ("plant", 860, 1150, 140, 200, "grow"), ("art2", 150, 500, 260, 200, "swing")],
    },
    "office": {
        "label": "ofis",
        "A": [("shelf", 600, 520, 260, 150), ("monitor", 120, 980, 200, 170), ("plant", 925, 1150, 140, 200),
              ("chair", 790, 1130, 140, 220), ("desk", 40, 1150, 360, 204)],
        "B": [("desk", 360, 1150, 360, 204), ("monitor", 440, 980, 200, 170), ("chair", 170, 1130, 140, 220),
              ("plant", 860, 1150, 140, 200, "grow"), ("shelf", 150, 520, 260, 150, "swing")],
    },
    "appliance": {
        "label": "texnika",
        "A": [("tv", 600, 480, 300, 188), ("clock", 920, 760, 130, 130), ("plant", 280, 1150, 140, 200),
              ("washer", 800, 1128, 200, 222), ("fridge", 60, 996, 190, 354)],
        "B": [("fridge", 850, 996, 190, 354), ("washer", 110, 1128, 200, 222), ("plant", 640, 1150, 140, 200, "grow"),
              ("tv", 150, 500, 300, 188, "swing")],
    },
}

# ----------------------------------------------------------------------------- palettes
# Colour swaps applied ONLY inside the journey (LAND) block of the template.
PALETTES = {
    "sunset": {"map": {}, "capj": "#141414", "stars": False},
    "morning": {
        "map": {
            "#ffeadc": "#eef6fb", "#ffd8bd": "#dcecf5", "#ffb98e": "#fde3cc", "#fff6ef": "#ffd27a",
            "#f7b48d": "#c5d6e0", "#f39a68": "#f6c49f", "#ee8b56": "#efb185", "#8c7468": "#9eacb5",
        },
        "capj": "#141414", "stars": False,
    },
    "night": {
        "map": {
            "#ffeadc": "#151a36", "#ffd8bd": "#262d5c", "#ffb98e": "#4b3f73", "#fff6ef": "#fff1cc",
            "#f7b48d": "#343a6b", "#fff0e4": "#cfd3ee", "#f39a68": "#433b6e", "#ee8b56": "#3a3262",
            "#8c7468": "#252a4f", "#5b5b5b": "#ff6a00", "#444444": "#ff4c00",
            "#f4d6be": "#2b2747", "#f7e0cd": "#231f3c", "#e8c4a6": "#3a3456",
            "#6e9c6a": "#3f6b55", "#5e8c61": "#35604b", "#7baa72": "#4a7a5e",
        },
        "capj": "#ffffff", "stars": True,
    },
}


def _item_html(prefix, entry):
    name, left, top, w, h = entry[:5]
    vb, body = ITEMS[name]
    return (f'<div id="{prefix}-{name}" class="abs" style="left: {left}px; top: {top}px; width: {w}px; height: {h}px">'
            f'<svg viewBox="{vb}">{body}</svg></div>')


def _stars(seed):
    rng = random.Random(seed)
    dots = "".join(
        f'<circle cx="{rng.randint(10, 1070)}" cy="{rng.randint(20, 900)}" r="{rng.choice([1.5, 2, 2.5, 3])}" fill="#fff6e8" opacity="{rng.choice([0.5, 0.7, 0.9])}" />'
        for _ in range(70))
    return f'<svg class="abs" style="left: 0; top: 0; width: 1080px; height: 1920px" viewBox="0 0 1080 1920">{dots}</svg>'


def fill_template(template: str, *, texts: dict, room_set: str, palette: str, phone: str, seed: int) -> str:
    rs = ROOM_SETS[room_set]
    pal = PALETTES[palette]

    room_a = "\n".join(_item_html("a", e) for e in rs["A"])
    room_b = "\n".join(_item_html("b", e) for e in rs["B"])
    fly_in = [{"id": f"#a-{e[0]}", "t": 1.5 + 0.25 * i, "cx": e[1] + e[3] / 2, "cy": e[2] + e[4] / 2}
              for i, e in enumerate(rs["A"])]
    fly_out = []
    glow_style, has_glow = "display: none", "false"
    for i, e in enumerate(rs["B"]):
        flags = e[5:] if len(e) > 5 else ()
        fly_out.append({"id": f"#b-{e[0]}", "t": round(12.8 + 0.08 * i, 2), "cx": e[1] + e[3] / 2,
                        "cy": e[2] + e[4] / 2, "swing": "swing" in flags, "grow": "grow" in flags})
        if "glow" in flags:
            glow_style = f"left: {e[1] + e[3] / 2 - 260}px; top: {e[2] - 200}px"
            has_glow = "true"

    out = template
    # palette swap restricted to the journey world (CSS + markup)
    for start, end in (("/* LAND-CSS-START */", "/* LAND-CSS-END */"), ("<!-- LAND-START -->", "<!-- LAND-END -->")):
        a, b = out.index(start), out.index(end)
        block = out[a:b]
        for src, dst in pal["map"].items():
            block = block.replace(src, dst)
        out = out[:a] + block + out[b:]

    repl = {
        "{{ROOM_A_ITEMS}}": room_a, "{{ROOM_B_ITEMS}}": room_b,
        "{{FLY_IN}}": json.dumps(fly_in), "{{FLY_OUT}}": json.dumps(fly_out),
        "{{GLOW_STYLE}}": glow_style, "{{HAS_GLOW}}": has_glow,
        "{{STARS}}": _stars(seed) if pal["stars"] else "",
        "{{CAPJ_COLOR}}": pal["capj"], "{{PHONE}}": phone,
        "{{HOOK}}": html.escape(texts["hook"]), "{{J1}}": html.escape(texts["journey_1"]),
        "{{J2}}": html.escape(texts["journey_2"]), "{{F1}}": html.escape(texts["final_1"]),
        "{{F2}}": html.escape(texts["final_2"]),
    }
    for k, v in repl.items():
        out = out.replace(k, v)
    leftover = [k for k in repl if k in out]
    if leftover or "{{" in out:
        raise ValueError(f"unfilled placeholders: {leftover}")
    return out
