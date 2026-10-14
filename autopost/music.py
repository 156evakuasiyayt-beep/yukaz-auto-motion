"""Original, deterministic score + SFX for "Qutunun səyahəti" (Yük.az reel v2).

120 BPM, 21 s, C major (C–Am–F–G). Warm marimba + soft groove; every on-screen
action has its own sound locked to the timings in art-direction.md.
Usage: python -m autopost.music OUT.wav [--transpose N] [--seed S]
(normalize afterwards with ffmpeg loudnorm — done by autopost.build).
"""
import argparse
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100
DUR = 21.0
N = int(SR * DUR)
_ap = argparse.ArgumentParser()
_ap.add_argument("out")
_ap.add_argument("--transpose", type=int, default=0)
_ap.add_argument("--seed", type=int, default=11)
_ap.add_argument("--mode", choices=["template", "bed"], default="template",
                 help="template = SFX locked to the fixed template; bed = generic score + SFX on --cuts")
_ap.add_argument("--cuts", default="", help="bed mode: comma-separated scene-cut times (s) for whooshes")
_ap.add_argument("--endcard", type=float, default=16.5, help="bed mode: end-card start time (s)")
ARGS = _ap.parse_args()
rng = np.random.default_rng(ARGS.seed)
OUT = Path(ARGS.out)


def filt(x, kind, f, order=2):
    return sosfilt(butter(order, f, kind, fs=SR, output="sos"), x)


def tt(d):
    return np.arange(int(d * SR)) / SR


def noise(d):
    return rng.standard_normal(int(d * SR))


def mtof(m):
    return 440.0 * 2 ** ((m + ARGS.transpose - 69) / 12)


def place(buf, sig, t, gain=1.0):
    i = int(round(t * SR))
    if i >= len(buf) or i < 0:
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def sweep_sine(f0, f1, d, curve=1.0):
    t = tt(d)
    f = f0 + (f1 - f0) * (t / d) ** curve
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


# ------------------------------------------------------------------ voices
def marimba(m, d=0.6, bright=1.0):
    t = tt(d)
    f = mtof(m)
    x = np.sin(2 * np.pi * f * t) + 0.35 * bright * np.sin(2 * np.pi * f * 3.9 * t) * np.exp(-t * 30)
    x += 0.15 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 12)
    return x * np.exp(-t * 7) * np.clip(t / 0.002, 0, 1) * 0.3


def glock(m, d=1.2):
    t = tt(d)
    f = mtof(m)
    x = np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 8)
    return x * np.exp(-t * 3.5) * 0.18


def kick(g=1.0):
    t = tt(0.35)
    f = 48 + 80 * np.exp(-t * 30)
    return np.tanh(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * 1.5) * 0.75 * g


def snap():
    t = tt(0.12)
    return filt(noise(0.12), "band", [1500, 5000]) * np.exp(-t * 55) * 0.35


def shaker(g=1.0):
    t = tt(0.07)
    env = np.sin(np.pi * np.clip(t / 0.07, 0, 1)) ** 2
    return filt(noise(0.07), "high", 6000) * env * 0.11 * g


def bass(m, d):
    t = tt(d)
    f = mtof(m)
    x = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    env = np.clip(t / 0.01, 0, 1) * np.exp(-t * 3) * np.clip((d - t) / 0.03, 0, 1)
    return x * env * 0.42


def pad(notes, d, cutoff=1800, g=1.0):
    t = tt(d)
    x = np.zeros_like(t)
    for m in notes:
        for dt in (-0.004, 0.0, 0.005):
            ph = mtof(m) * (1 + dt) * t
            x += 2 * (ph - np.floor(ph + 0.5))
    x = filt(x / (len(notes) * 3), "low", cutoff)
    return x * np.clip(t / 0.4, 0, 1) * np.clip((d - t) / 0.4, 0, 1) * 0.16 * g


# ------------------------------------------------------------------ sfx
def bloop(f0, f1):
    t = tt(0.16)
    return sweep_sine(f0, f1, 0.16, 0.6) * np.exp(-t * 18) * 0.32


def tock(f=820, g=1.0):
    t = tt(0.1)
    x = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.3 * t)
    return x * np.exp(-t * 45) * 0.3 * g


def whoosh(d=0.45, g=1.0):
    t = tt(d)
    env = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2
    n = noise(d)
    x = t / d
    return (filt(n, "low", 1200) * (1 - x) + filt(n, "high", 2500) * x) * env * 0.28 * g


def zip_(d=0.22):
    t = tt(d)
    am = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * (60 + 140 * t / d) * t))
    return filt(noise(d), "band", [2000, 7000]) * am * np.sin(np.pi * t / d) * 0.3


def boing():
    t = tt(0.35)
    f = 220 + 380 * (t / 0.35) + 25 * np.sin(2 * np.pi * 18 * t)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7) * 0.25


def thud(g=1.0):
    t = tt(0.4)
    f = 55 + 70 * np.exp(-t * 25)
    return np.tanh(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 10) * 2) * 0.55 * g


def riser(d):
    t = tt(d)
    x = t / d
    return (filt(noise(d), "band", [1500, 8000]) * 0.4 + sweep_sine(300, 1500, d, 2) * 0.1) * x ** 2.4 * 0.7


def chime(notes, start, spacing, buf, g=1.0):
    for k, m in enumerate(notes):
        place(buf, glock(m), start + k * spacing, g)


# ------------------------------------------------------------------ arrangement
music = np.zeros(N)
drums = np.zeros(N)
sfx = np.zeros(N)
send = np.zeros(N)
kicks = []

C = ([48, 55, 60, 64, 67], 36, [72, 76, 79, 84])
AM = ([45, 52, 57, 60, 64], 33, [69, 72, 76, 81])
F = ([41, 53, 57, 60, 65], 29, [69, 72, 77, 81])
G = ([43, 50, 55, 59, 62], 31, [67, 71, 74, 79])
bars = [(0, C), (2, AM), (4, F), (6, G), (8, C), (10, AM), (12, F), (14, G)]

BED = ARGS.mode == "bed"
END = ARGS.endcard if BED else 15.0
if BED:
    groove = lambda t: 2.5 <= t < END - 0.5
else:
    groove = lambda t: (4.0 <= t < 10.9) or (12.5 <= t < 14.9)

for t0, (pad_notes, root, arp) in bars:
    seg = 1.0 if (t0 == 14 and not BED) else min(2.0, END - t0)
    if seg <= 0:
        continue
    place(music, pad(pad_notes[1:], seg + 0.3, 1500 if t0 < 4 else 2000, 0.8 if t0 < 4 else 1.0), t0)
    pattern = [0, 1, 2, 3, 2, 1, 3, 2]
    for k in range(int(seg / 0.25)):
        nt = t0 + k * 0.25
        if t0 < (2.5 if BED else 4) and k % 2 == 1:
            continue  # sparser intro
        if not BED and 11.0 <= nt < 12.2:
            continue  # breath at the door
        m = arp[pattern[k % 8]]
        place(music, marimba(m), nt, 0.9)
        place(send, marimba(m), nt, 0.4)
    for k in range(int(seg / 0.5)):
        nt = t0 + k * 0.5
        if groove(nt):
            place(music, bass(root, 0.45), nt)

# drums
t = 0.0
while t < END - 1e-6:
    beat = round(t / 0.5)
    if 0.5 <= t < (2.5 if BED else 4.0) and beat % 2 == 1:
        place(drums, snap(), t, 0.8)
        place(send, snap(), t, 0.4)
    if groove(t):
        place(drums, kick(0.9), t)
        kicks.append(t)
        if beat % 2 == 1:
            place(drums, snap(), t)
        for s in range(4):
            place(drums, shaker(1.0 if s % 2 else 0.6), t + s * 0.125)
    t += 0.5

if not BED:
    # break at the door (11.0 – 12.2)
    place(music, pad([52, 57, 60, 64], 1.4, 1200), 11.0, 1.2)
    place(sfx, riser(0.8), 11.45, 0.8)

# end card: resolve on C
place(music, pad([48, 55, 60, 64, 67, 72], DUR - END, 2400, 1.3), END)
place(music, bass(36, 2.5), END, 1.2)
hit = END + (0.0 if BED else 0.95)
place(drums, kick(1.0), hit)
kicks.append(hit)
melody = [(16.0, 79), (16.25, 76), (16.5, 72), (16.75, 76), (17.0, 79), (17.5, 84), (18.0, 83), (18.25, 79), (18.5, 76), (19.0, 72)]
for nt, m in melody:
    nt += END - 15.0
    if nt < DUR - 0.8:
        place(music, marimba(m, 0.9), nt, 0.9)
        place(send, marimba(m, 0.9), nt, 0.6)

if BED:
    # generic sound design: whoosh into every scene cut, riser + hit into the end card
    for c in [float(x) for x in ARGS.cuts.split(",") if x.strip()]:
        if 0.4 < c < END - 0.3:
            place(sfx, whoosh(0.45, 0.85), c - 0.35)
            place(sfx, tock(900, 0.5), c)
    place(sfx, riser(1.0), END - 1.0, 0.8)
    place(sfx, thud(0.8), END)
    chime([84, 91, 96], END + 0.05, 0.07, sfx, 0.9)

# ------------------------------------------------------------------ SFX (locked to picture)
if not BED:
    place(sfx, bloop(300, 600), 1.0, 0.9)  # box pops in
    for k, tp in enumerate([1.5, 1.75, 2.0, 2.25, 2.5]):  # items fly into the box
        place(sfx, whoosh(0.3, 0.6), tp)
        place(sfx, bloop(420 + k * 70, 820 + k * 110), tp + 0.3)
    place(sfx, thud(0.5), 3.0)  # flaps close
    place(sfx, zip_(), 3.15)  # tape
    place(sfx, boing(), 3.5)  # jump
    place(sfx, whoosh(0.5, 0.9), 3.6)  # wall rises
    chime([84, 88, 91], 3.75, 0.06, sfx, 0.9)  # turns into the logo cube
    place(sfx, thud(0.8), 4.05)
    for k in range(12):  # hop landings
        land = 5.0 + 0.5 * k
        place(sfx, tock(760 if k % 2 else 980, 0.8), land)
        if k in (3, 7, 11):
            place(sfx, whoosh(0.4, 0.6), land - 0.42)
    place(sfx, tock(1100), 11.45)  # hop to the door
    chime([79, 84], 11.5, 0.08, sfx, 0.8)  # door opens
    place(sfx, whoosh(0.45, 1.0), 11.8)  # zoom through the door
    place(sfx, thud(0.8), 12.55)  # lands in the new room
    chime([72, 76, 79, 84, 88], 12.7, 0.05, sfx, 1.0)  # unfolds
    for k, tp in enumerate([12.8, 12.9, 13.0, 13.1]):
        place(sfx, bloop(700 + k * 90, 350 + k * 60), tp, 0.8)
    place(sfx, whoosh(0.5, 0.9), 14.6)  # iris to end card
    place(sfx, thud(0.7), 15.95)  # cube assembles
    chime([84, 91, 96], 15.95, 0.07, sfx, 0.9)
    place(sfx, tock(1500, 0.6), 16.3)  # orange dot
    place(sfx, bloop(500, 900), 17.4, 0.7)  # phone pill

# ------------------------------------------------------------------ mix
t_all = np.arange(N) / SR
duck = np.ones(N)
for kt in kicks:
    m = t_all >= kt
    d = t_all[m] - kt
    duck[m] = np.minimum(duck[m], 1 - 0.35 * np.exp(-d / 0.1))
music *= duck

ir_t = tt(1.8)
ir_l = noise(1.8) * np.exp(-ir_t * 2.6)
ir_r = noise(1.8) * np.exp(-ir_t * 2.6)
src = filt(send + sfx * 0.2, "low", 7000)
rev_l = fftconvolve(src, ir_l)[:N] * 0.02
rev_r = fftconvolve(src, ir_r)[:N] * 0.02

haas = int(0.011 * SR)
music_r = np.concatenate([np.zeros(haas), music[:-haas]])
L = drums + music + sfx + rev_l
R = drums + music_r * 0.9 + music * 0.1 + sfx + rev_r
fade = np.clip((DUR - t_all) / 1.5, 0, 1)
mix = np.stack([L * fade, R * fade], axis=1)
mix = filt(mix.T, "high", 30).T
mix /= np.max(np.abs(mix))
mix = np.tanh(mix * 1.4) / np.tanh(1.4)

OUT.parent.mkdir(parents=True, exist_ok=True)
wavfile.write(OUT, SR, (mix * 0.95 * 32767).astype(np.int16))
print("wrote", OUT)
