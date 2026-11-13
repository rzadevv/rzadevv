#!/usr/bin/env python3
"""Monkey vs lion: an animated SVG for a GitHub profile README.

Every day the lion stalks the monkey, leaps, misses, and gets mocked. The
day's git activity changes the episode: each push is a banana in the pile
under the tree, the lines change daily, and the running tally never stops
favouring the monkey.

    python3 jungle/scene.py            # fetch activity, update state, draw
    BANANAS=7 python3 jungle/scene.py  # skip the fetch (local testing)

Python 3 standard library only. Writes jungle/jungle.svg and jungle/state.json.
"""
import datetime as dt
import json
import math
import os
import random
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
OUT = HERE / "jungle.svg"

W, H = 720, 384
GROUND = 300
D = 14.0  # length of one episode, seconds

INK = "#2a2420"
PAPER = "#f6efe0"
FUR = "#e2ab4f"
FUR_DARK = "#c98c35"
MANE = "#9b4f1c"
MUZZLE = "#f4dcaa"
MONKEY = "#7b4a2b"
MONKEY_DARK = "#5e3820"
FACE = "#ecc9a0"
LEAF = "#4f8a4a"
LEAF_DARK = "#356b3a"
BARK = "#7a5634"
BANANA = "#f4cf3b"
RED = "#c8412d"
SERIF = "'Iowan Old Style','Palatino Linotype',Palatino,Georgia,serif"

MOCKS = [
    "too slow, kitty!", "ooh ooh, missed again!", "nice try, fluffy.",
    "is that all, your majesty?", "you call that a jump?", "vegetarian today?",
    "skill issue.", "catch me tomorrow!", "the trees are mine, mane-boy.",
    "do cats even jump?", "eat grass, king.", "aim higher. literally.",
]
COMEBACKS = [
    "grrr…", "i was stretching.", "lag.", "tomorrow. tomorrow.",
    "the sun was in my eyes.", "not fair. trees.", "…", "i let you win.",
]

# ---------------------------------------------------------------- timing ----


def _frames(frames):
    frames = sorted(frames, key=lambda f: f[0])
    if frames[0][0] > 0:
        frames.insert(0, (0.0, frames[0][1]))
    if frames[-1][0] < D:
        frames.append((D, frames[-1][1]))
    kts, prev = [], -1.0
    for t, _ in frames:
        k = max(min(t / D, 1.0), prev + 1e-4 if prev >= 0 else 0.0)
        kts.append(k)
        prev = k
    kts[-1] = 1.0
    kts = [min(k, 1.0) for k in kts]
    for i in range(len(kts) - 2, -1, -1):          # keep it monotonic after clamping
        kts[i] = min(kts[i], kts[i + 1])
    return (";".join(f"{k:.4f}" for k in kts),
            ";".join(str(v) for _, v in frames))


def tf(kind, frames, calc="linear"):
    k, v = _frames(frames)
    return (f'<animateTransform attributeName="transform" type="{kind}" dur="{D}s" '
            f'repeatCount="indefinite" calcMode="{calc}" keyTimes="{k}" values="{v}"/>')


def anim(attr, frames, calc="linear"):
    k, v = _frames(frames)
    return (f'<animate attributeName="{attr}" dur="{D}s" repeatCount="indefinite" '
            f'calcMode="{calc}" keyTimes="{k}" values="{v}"/>')


def show(t0, t1, fade=0.12):
    return anim("opacity", [(0, 0), (t0, 0), (t0 + fade, 1), (t1 - fade, 1), (t1, 0)])


def cycle(t0, t1, period, a, b, rest=0):
    """Oscillate between a and b from t0 to t1, at rest otherwise."""
    fr = [(0, rest), (t0, rest)]
    t, flip = t0 + period / 2, True
    while t < t1:
        fr.append((t, a if flip else b))
        flip = not flip
        t += period / 2
    fr.append((t1, rest))
    return fr


# ------------------------------------------------------------------- ink ----

class Pen:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def _wob(self, pts, amp):
        out = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d = math.hypot(x1 - x0, y1 - y0) or 1
            n = max(1, int(d / 14))
            nx, ny = -(y1 - y0) / d, (x1 - x0) / d
            for i in range(1, n + 1):
                t, j = i / n, (self.r.uniform(-amp, amp) if i < n else 0)
                out.append((x0 + (x1 - x0) * t + nx * j, y0 + (y1 - y0) * t + ny * j))
        return out

    @staticmethod
    def d(pts, close=False):
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + ("Z" if close else "")

    def path(self, pts, w=1.8, color=INK, fill="none", amp=.6, close=False, op=1, sketch=True):
        p = self._wob(pts + ([pts[0]] if close else []), amp)
        o = ""
        if fill != "none":
            o += f'<path d="{self.d(p, True)}" fill="{fill}"/>'
        if w:
            o += (f'<path d="{self.d(p)}" fill="none" stroke="{color}" stroke-width="{w}" '
                  f'stroke-linecap="round" stroke-linejoin="round" opacity="{op}"/>')
            if sketch:
                q = self._wob([(x + self.r.uniform(-.7, .7), y + self.r.uniform(-.7, .7))
                               for x, y in pts] + ([pts[0]] if close else []), amp)
                o += (f'<path d="{self.d(q)}" fill="none" stroke="{color}" stroke-width="{w*.4:.2f}" '
                      f'stroke-linecap="round" stroke-linejoin="round" opacity="{.5*op:.2f}"/>')
        return o

    def ellipse(self, cx, cy, rx, ry, w=1.8, fill="none", rot=0, n=26, **kw):
        a0 = self.r.uniform(0, math.tau)
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        pts = []
        for i in range(n):
            a = a0 + math.tau * i / n
            x, y = rx * math.cos(a), ry * math.sin(a)
            pts.append((cx + x * c - y * s, cy + x * s + y * c))
        return self.path(pts, w=w, fill=fill, close=True, amp=.35, **kw)

    def blob(self, cx, cy, r, bumps=9, depth=.22, w=1.8, fill="none", ry=None, **kw):
        ry = ry or r
        pts = []
        a0 = self.r.uniform(0, math.tau)
        for i in range(bumps * 4):
            a = a0 + math.tau * i / (bumps * 4)
            k = 1 + depth * (abs(math.sin(i * math.pi / 4)) - .5) + self.r.uniform(-.04, .04)
            pts.append((cx + r * k * math.cos(a), cy + ry * k * math.sin(a)))
        return self.path(pts, w=w, fill=fill, close=True, amp=.3, **kw)

    def spiky(self, cx, cy, r, spikes=14, depth=.28, fill="none", w=1.8):
        pts = []
        a0 = self.r.uniform(0, math.tau)
        for i in range(spikes * 2):
            a = a0 + math.pi * i / spikes
            rr = r * (1 + (depth if i % 2 else -depth * .3)) * self.r.uniform(.92, 1.06)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        return self.path(pts, w=w, fill=fill, close=True, amp=.4)


def text(x, y, s, size=14, anchor="middle", color=INK, weight="normal", extra=""):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}" '
            f'font-family="{SERIF}" font-style="italic" font-weight="{weight}"{extra}>{escape(s)}</text>')


def bubble(pen, x, y, s, tail_to, size=15):
    w = len(s) * size * .5 + 28
    h = size + 18
    x0, y0 = x - w / 2, y - h / 2
    tx, ty = tail_to
    bx = min(max(tx, x0 + 18), x0 + w - 18)
    pts = [(x0 + 8, y0), (x0 + w - 8, y0), (x0 + w, y0 + 8), (x0 + w, y0 + h - 8), (x0 + w - 8, y0 + h),
           (bx + 8, y0 + h), (tx, ty), (bx - 6, y0 + h), (x0 + 8, y0 + h), (x0, y0 + h - 8), (x0, y0 + 8)]
    return pen.path(pts, w=1.6, fill="#fffdf6", close=True) + text(x, y + size * .35, s, size)


def star(cx, cy, r, fill=BANANA):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + math.pi * i / 5
        rr = r if i % 2 == 0 else r * .45
        pts.append(f"{cx + rr * math.cos(a):.1f},{cy + rr * math.sin(a):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="{INK}" stroke-width="1"/>'


# ------------------------------------------------------------- the lion ----
# Local coordinates: facing right, origin on the ground under the belly.

WALKS = [(0.0, 1.5), (2.2, 4.8), (10.9, 13.0)]


def leg_frames(phase):
    fr = [(0, 0)]
    for t0, t1 in WALKS:
        fr.append((t0, 0))
        t, flip = t0 + .2, phase
        while t < t1:
            fr.append((t, 16 if flip else -16))
            flip = not flip
            t += .4
        fr.append((t1, 0))
    return fr


def lion(pen):
    o = []
    a = o.append

    def leg(x, phase, fill):
        g = f'<g>{tf("rotate", [(t, f"{v} {x} -36") for t, v in leg_frames(phase)])}'
        g += pen.path([(x - 8, -42), (x + 8, -42), (x + 5, -20), (x + 5, -6), (x - 5, -6), (x - 6, -20)],
                      fill=fill, close=True, w=1.7)
        g += pen.ellipse(x + 3, -3.5, 9, 4.6, fill=fill, w=1.6)
        g += pen.path([(x + 3, -6), (x + 4, -1)], w=.9) + pen.path([(x + 7, -6), (x + 8, -1)], w=.9)
        return g + "</g>"

    # tail, swishing on its own clock
    a('<g><animateTransform attributeName="transform" type="rotate" dur="1.9s" repeatCount="indefinite" '
      'values="0 -50 -48;14 -50 -48;-6 -50 -48;0 -50 -48"/>')
    a(pen.path([(-50, -48), (-70, -52), (-84, -66), (-90, -86)], w=3.4, color=FUR_DARK, sketch=False))
    a(pen.path([(-50, -48), (-70, -52), (-84, -66), (-90, -86)], w=1.2))
    a(pen.spiky(-91, -91, 7, spikes=7, fill=MANE, w=1.4) + "</g>")

    a(leg(-38, True, FUR_DARK))      # far legs
    a(leg(24, False, FUR_DARK))
    # body
    a(pen.ellipse(0, -48, 54, 23, fill=FUR, w=2))
    a(pen.ellipse(-30, -44, 20, 19, fill=FUR, w=1.6))                       # haunch
    a(pen.ellipse(32, -46, 16, 18, fill=FUR, w=1.4))                        # shoulder
    a(pen.path([(-30, -30), (-5, -27), (25, -30)], w=1, op=.6))            # belly line
    for x in (-20, -10, 0):                                                  # fur strokes
        a(pen.path([(x, -62), (x + 6, -58)], w=.9, op=.5))
    a(leg(-26, False, FUR))          # near legs
    a(leg(34, True, FUR))

    # head group: mane, face, eyes, jaw
    a('<g>' + tf("rotate", [(0, "0 55 -62"), (1.5, "0 55 -62"), (1.7, "-8 55 -62"), (2.1, "-8 55 -62"),
                            (2.25, "0 55 -62"), (9.9, "0 55 -62"), (10.05, "-10 55 -62"),
                            (10.6, "-10 55 -62"), (10.75, "0 55 -62")]))
    a(pen.spiky(55, -64, 31, spikes=16, fill=MANE, w=1.8))
    a(pen.spiky(55, -64, 24, spikes=12, depth=.18, fill="#b8662a", w=1))
    a(pen.ellipse(44, -82, 6, 6, fill=FUR, w=1.6))                          # ear
    a(pen.ellipse(60, -62, 20, 19, fill=FUR, w=1.9))                        # face
    # mouth interior + teeth (hidden behind the jaw when it is closed)
    a(f'<path d="M64,-50 L84,-50 L66,-41 Z" fill="#7a1f1a"/>')
    a(f'<g>{anim("opacity", [(0, 0), (5.5, 0), (5.6, 1), (6.4, 1), (6.45, 0), (9.95, 0), (10.0, 1), (10.6, 1), (10.65, 0)])}'
      f'<path d="M70,-50 L72,-46 L74,-50 M76,-50 L78,-46 L80,-50" fill="#fff" stroke="{INK}" stroke-width=".6"/></g>')
    # lower jaw
    a('<g>' + tf("rotate", [(0, "0 64 -48"), (5.5, "0 64 -48"), (5.65, "28 64 -48"), (6.38, "28 64 -48"),
                            (6.45, "0 64 -48"), (9.95, "0 64 -48"), (10.05, "18 64 -48"),
                            (10.55, "18 64 -48"), (10.62, "0 64 -48")]))
    a(pen.path([(64, -50), (80, -49), (77, -43), (66, -42)], fill=MUZZLE, close=True, w=1.4) + "</g>")
    a(pen.ellipse(72, -55, 11, 7, fill=MUZZLE, w=1.4))                      # muzzle
    a(f'<path d="M78,-61 L84,-60 L80,-56 Z" fill="#5a2a1c"/>')               # nose
    a(pen.path([(80, -56), (79, -52)], w=1))
    for wx in (0, 4):                                                        # whiskers
        a(pen.path([(74 + wx, -53), (90 + wx, -56 + wx)], w=.6, op=.7))
    # eyes: normal / narrowed while hunting / dizzy spirals
    a(f'<g>{anim("opacity", [(0, 1), (6.9, 1), (6.95, 0), (10.4, 0), (10.45, 1)], "discrete")}'
      f'<ellipse cx="64" cy="-69" rx="3.2" ry="3.6" fill="#fff" stroke="{INK}" stroke-width="1"/>'
      f'<circle cx="65.5" cy="-69" r="1.8" fill="{INK}"/>'
      + pen.path([(58, -76), (70, -73)], w=1.6) + "</g>")
    spiral = "M64,-69 m-1,0 a1,1 0 1,1 2,0 a2,2 0 1,1 -4,0 a3,3 0 1,1 6,0 a4,4 0 1,1 -8,0"
    a(f'<g>{anim("opacity", [(0, 0), (6.9, 0), (6.95, 1), (10.4, 1), (10.45, 0)], "discrete")}'
      f'<path d="{spiral}" fill="none" stroke="{INK}" stroke-width="1.2">'
      f'<animateTransform attributeName="transform" type="rotate" dur=".8s" repeatCount="indefinite" '
      f'values="0 64 -69;360 64 -69"/></path></g>')
    a("</g>")
    return "".join(o)


# ------------------------------------------------------------ the monkey ----
# Local coordinates: facing left, origin where it sits on the branch.

def monkey(pen):
    o = []
    a = o.append
    # tail curling below the branch
    a('<g><animateTransform attributeName="transform" type="rotate" dur="2.6s" repeatCount="indefinite" '
      'values="0 8 -6;10 8 -6;-4 8 -6;0 8 -6"/>')
    a(pen.path([(8, -6), (16, 10), (20, 28), (14, 42), (4, 42), (2, 34), (9, 31)], w=3, color=MONKEY_DARK, sketch=False))
    a(pen.path([(8, -6), (16, 10), (20, 28), (14, 42), (4, 42), (2, 34), (9, 31)], w=1) + "</g>")
    # far arm: rests on the knee, then thumbs the ear while mocking
    far = [(0, "0 7 -32"), (7.3, "0 7 -32"), (7.5, "-150 7 -32")]
    far += [(t, f"{v} 7 -32") for t, v in cycle(7.6, 8.9, .24, -140, -160, -150)][2:]
    far += [(8.95, "0 7 -32"), (10.2, "0 7 -32"), (10.35, "-150 7 -32"),
            (10.4, "-150 7 -32")] + [(t, f"{v} 7 -32") for t, v in cycle(10.45, 11.4, .24, -140, -160, -150)][2:] \
        + [(11.5, "0 7 -32")]
    a(f'<g>{tf("rotate", far)}' + pen.path([(7, -32), (15, -20), (12, -9)], w=4, color=MONKEY_DARK, sketch=False)
      + pen.ellipse(12, -8, 3.4, 3, fill=FACE, w=1) + "</g>")
    # legs dangling over the branch
    a(pen.path([(-6, -9), (-11, 4), (-7, 15)], w=4.5, color=MONKEY_DARK, sketch=False))
    a(pen.path([(5, -9), (3, 6), (8, 15)], w=4.5, color=MONKEY_DARK, sketch=False))
    a(pen.ellipse(-6, 16, 4, 2.6, fill=FACE, w=1) + pen.ellipse(9, 16, 4, 2.6, fill=FACE, w=1))
    # body
    a(pen.ellipse(0, -22, 13, 17, fill=MONKEY, w=1.9))
    a(pen.ellipse(-3, -18, 7, 10, fill=FACE, w=1.1))
    # head
    a('<g>' + tf("rotate", [(0, "0 -4 -46")] + [(t, f"{v} -4 -46") for t, v in cycle(7.6, 8.9, .3, -12, 12)][1:]
                 + [(t, f"{v} -4 -46") for t, v in cycle(10.45, 11.4, .3, -12, 12)][1:]))
    a(pen.ellipse(9, -50, 6, 6, fill=FACE, w=1.5))                           # far ear
    a(pen.ellipse(-3, -48, 14, 13, fill=MONKEY, w=1.9))
    a(pen.ellipse(-18, -49, 6, 6.5, fill=FACE, w=1.5))                       # near ear
    a(pen.ellipse(-18, -49, 3, 3.5, fill="#d7a77a", w=0))
    a(pen.path([(-15, -54), (-9, -60), (-2, -60), (3, -55), (2, -48), (-4, -43), (-2, -37),
                (-12, -35), (-17, -40), (-15, -46)], fill=FACE, close=True, w=1.2))
    a(pen.path([(-5, -62), (-2, -67), (1, -61)], w=1.4, color=MONKEY_DARK))  # tuft
    # eyes: open / squinting with glee while mocking
    a(f'<g>{anim("opacity", [(0, 1), (7.3, 1), (7.35, 0), (11.6, 0), (11.65, 1)], "discrete")}'
      f'<circle cx="-11" cy="-51" r="2" fill="{INK}"/><circle cx="-4" cy="-51" r="2" fill="{INK}"/>'
      f'<circle cx="-11.6" cy="-51.7" r=".6" fill="#fff"/><circle cx="-4.6" cy="-51.7" r=".6" fill="#fff"/>'
      f'<animate attributeName="opacity" dur="4.1s" repeatCount="indefinite" values="1;1;0;1" keyTimes="0;.95;.97;1"/></g>')
    a(f'<g>{anim("opacity", [(0, 0), (7.3, 0), (7.35, 1), (11.6, 1), (11.65, 0)], "discrete")}'
      + pen.path([(-14, -50), (-11, -53), (-8, -50)], w=1.4) + pen.path([(-7, -50), (-4, -53), (-1, -50)], w=1.4) + "</g>")
    a(f'<circle cx="-9" cy="-44" r=".8" fill="{INK}"/><circle cx="-6" cy="-44" r=".8" fill="{INK}"/>')
    # mouth: chewing grin, then a big open laugh with tongue
    a(f'<g>{anim("opacity", [(0, 1), (7.3, 1), (7.35, 0), (11.6, 0), (11.65, 1)], "discrete")}'
      + pen.path([(-13, -40), (-8, -38), (-3, -40)], w=1.3) + "</g>")
    a(f'<g>{anim("opacity", [(0, 0), (7.3, 0), (7.35, 1), (11.6, 1), (11.65, 0)], "discrete")}'
      f'<path d="M-14,-41 Q-8,-33 -2,-41 Z" fill="#5c1d16" stroke="{INK}" stroke-width="1.1"/>'
      f'<ellipse cx="-9" cy="-35" rx="3.6" ry="4.5" fill="#e0556b" stroke="{INK}" stroke-width="1">'
      f'<animate attributeName="ry" dur=".5s" repeatCount="indefinite" values="4.5;6;4.5"/></ellipse></g>')
    a("</g>")
    # near arm: eats the banana, then waves, then throws the peel
    near = [(0, "0 -9 -32")] + [(t, f"{v} -9 -32") for t, v in cycle(.3, 5.6, .9, -14, 4)][1:]
    near += [(6.0, "40 -9 -32"), (6.4, "-60 -9 -32"), (7.2, "-60 -9 -32"), (7.5, "-140 -9 -32")]
    near += [(t, f"{v} -9 -32") for t, v in cycle(7.6, 8.5, .24, -130, -160, -145)][2:]
    near += [(8.6, "-170 -9 -32"), (8.85, "-20 -9 -32"), (9.1, "0 -9 -32"), (10.2, "0 -9 -32"),
             (10.35, "-150 -9 -32")] + [(t, f"{v} -9 -32") for t, v in cycle(10.45, 11.4, .24, -140, -160, -150)][2:] \
        + [(11.5, "0 -9 -32")]
    a(f'<g>{tf("rotate", near)}' + pen.path([(-9, -32), (-20, -24), (-17, -37)], w=4.2, color=MONKEY_DARK, sketch=False)
      + pen.ellipse(-17, -38, 3.4, 3, fill=FACE, w=1))
    a(f'<g>{anim("opacity", [(0, 1), (8.8, 1), (8.82, 0), (13.0, 0), (13.1, 1)], "discrete")}'
      + pen.path([(-24, -38), (-21, -48), (-14, -54), (-13, -51), (-18, -46), (-20, -38)],
                 fill=BANANA, close=True, w=1.2) + "</g></g>")
    return "".join(o)


# ------------------------------------------------------------- scenery ----

def scenery(pen, bananas):
    o = []
    a = o.append
    a('<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
      '<stop offset="0" stop-color="#bfdcec"/><stop offset=".7" stop-color="#f6e2bf"/>'
      '<stop offset="1" stop-color="#f3d39a"/></linearGradient>'
      f'<clipPath id="card"><rect x="2" y="2" width="{W-4}" height="{H-4}" rx="8"/></clipPath></defs>')
    a(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{PAPER}"/>')
    a('<g clip-path="url(#card)">')
    a(f'<rect x="0" y="0" width="{W}" height="{GROUND+4}" fill="url(#sky)"/>')
    # sun, hills, clouds
    a(pen.ellipse(120, 78, 26, 26, fill="#f7c65b", w=1.4))
    for i in range(10):
        ang = math.tau * i / 10
        a(pen.path([(120 + 33 * math.cos(ang), 78 + 33 * math.sin(ang)),
                    (120 + 41 * math.cos(ang), 78 + 41 * math.sin(ang))], w=1.3, sketch=False))
    a(pen.path([(0, 250), (90, 222), (190, 236), (300, 210), (420, 232), (540, 214), (720, 236),
                (720, 304), (0, 304)], fill="#c7cf9a", close=True, w=1.2, op=.6))
    a(pen.path([(0, 270), (130, 252), (260, 266), (380, 248), (520, 262), (720, 250),
                (720, 304), (0, 304)], fill="#b5c27f", close=True, w=1.2, op=.6))
    for cx, cy, s, dur in ((260, 60, 1, 60), (430, 104, .7, 80)):
        a(f'<g><animateTransform attributeName="transform" type="translate" dur="{dur}s" '
          f'repeatCount="indefinite" values="0 0;-40 0;0 0"/>')
        a(pen.blob(cx, cy, 30 * s, bumps=5, depth=.35, ry=12 * s, fill="#fffaf0", w=1.3) + "</g>")
    # a bird crossing the sky
    a('<g><animateMotion dur="23s" repeatCount="indefinite" path="M-30,70 C200,40 420,100 760,50"/>'
      '<path d="M-7,0 Q-3,-5 0,0 Q3,-5 7,0" fill="none" stroke="#2a2420" stroke-width="1.4">'
      '<animate attributeName="d" dur=".5s" repeatCount="indefinite" '
      'values="M-7,0 Q-3,-5 0,0 Q3,-5 7,0;M-7,-3 Q-3,1 0,0 Q3,1 7,-3;M-7,0 Q-3,-5 0,0 Q3,-5 7,0"/></path></g>')
    # ground
    a(pen.path([(0, GROUND), (W, GROUND), (W, H), (0, H)], fill="#dcc488", close=True, w=0))
    a(pen.path([(0, GROUND), (180, GROUND + 1), (360, GROUND - 1), (540, GROUND + 1), (W, GROUND)], w=1.8, amp=1))
    for x in range(12, W, 23):                                                 # grass flecks
        y = GROUND + 6 + pen.r.uniform(0, 12)
        a(pen.path([(x, y), (x + 2, y - 5)], w=.9, op=.5, sketch=False))
    # tree: trunk, two branches, canopy, vine
    a(pen.path([(586, GROUND + 2), (594, 200), (590, 120), (596, 40), (632, 40), (628, 120),
                (634, 200), (648, GROUND + 2)], fill=BARK, close=True, w=2))
    for y in range(70, 290, 22):
        a(pen.path([(600, y), (608, y + 6)], w=.9, op=.5))
        a(pen.path([(620, y + 10), (626, y + 4)], w=.9, op=.5))
    a(pen.path([(596, 160), (560, 156), (520, 150), (500, 144), (520, 157), (560, 166), (594, 172)],
               fill=BARK, close=True, w=1.8))                                  # low branch
    a(pen.path([(628, 96), (668, 92), (700, 82), (710, 86), (672, 102), (630, 108)],
               fill=BARK, close=True, w=1.8))                                  # high branch
    for cx, cy, r, fill in ((560, 30, 58, LEAF_DARK), (680, 24, 62, LEAF_DARK), (620, 6, 60, LEAF),
                            (520, 54, 34, LEAF), (708, 58, 34, LEAF)):
        a(pen.blob(cx, cy, r, bumps=8, depth=.25, ry=r * .7, fill=fill, w=1.8))
    for cx, cy in ((540, 22), (600, 40), (660, 14), (700, 46), (580, -4)):
        a(pen.path([(cx, cy), (cx + 8, cy - 4), (cx + 12, cy + 2)], w=1, op=.5, sketch=False))
    a('<g><animateTransform attributeName="transform" type="rotate" dur="5s" repeatCount="indefinite" '
      'values="0 512 50;4 512 50;-3 512 50;0 512 50"/>')
    a(pen.path([(512, 50), (509, 90), (514, 130), (510, 170), (515, 200)], w=2.2, color="#5d7d3a", sketch=False))
    for y in (80, 120, 160, 196):
        a(pen.ellipse(517, y, 6, 3, fill=LEAF, w=1, rot=-30))
    a("</g>")
    # bananas from yesterday's pushes, piled against the trunk
    rnd = random.Random(bananas * 7 + 1)
    for i in range(min(bananas, 12)):
        row, col = divmod(i, 5)
        row, col = divmod(i, 4)
        bx = 704 - col * 16 + row * 7 + rnd.uniform(-2, 2)
        by = GROUND - 5 - row * 8
        ang = rnd.uniform(-30, 30)
        a(f'<g transform="rotate({ang:.0f} {bx:.0f} {by:.0f})">'
          + pen.path([(bx - 10, by - 3), (bx - 4, by + 2), (bx + 4, by + 2), (bx + 10, by - 4),
                      (bx + 9, by + 1), (bx + 3, by + 5), (bx - 4, by + 5), (bx - 9, by + 1)],
                     fill=BANANA, close=True, w=1.2)
          + f'<circle cx="{bx-10:.0f}" cy="{by-3:.0f}" r="1.6" fill="{INK}"/>' + "</g>")
    for gx in (210, 290, 420, 470, 690):
        gy = GROUND + 30 + pen.r.uniform(-4, 8)
        a(pen.path([(gx - 8, gy), (gx - 4, gy - 14), (gx, gy), (gx + 3, gy - 18), (gx + 6, gy), (gx + 10, gy - 12), (gx + 12, gy)],
                   fill="#8aa356", close=False, w=1.3))
    for fx, c in ((240, "#e86f5a"), (450, "#fff"), (700, "#e8b34a")):
        fy = GROUND + 18
        a(pen.path([(fx, fy + 10), (fx + 1, fy)], w=1.1, sketch=False) + f'<circle cx="{fx+1}" cy="{fy}" r="4" fill="{c}" stroke="{INK}" stroke-width="1"/>')
    return "".join(o)


def bush(pen, x, y):
    o = pen.blob(x, y, 70, bumps=7, depth=.3, ry=48, fill=LEAF_DARK, w=1.9)
    o += pen.blob(x + 30, y + 14, 48, bumps=6, depth=.3, ry=34, fill=LEAF, w=1.6)
    for i in range(7):
        lx, ly = x - 50 + i * 16, y - 20 + (i % 3) * 14
        o += pen.path([(lx, ly), (lx + 7, ly - 4), (lx + 10, ly + 2)], w=1, op=.5, sketch=False)
    return o


# -------------------------------------------------------------- episode ----

def render(state):
    pen = Pen("jungle")
    rnd = random.Random(state["day"])
    mock1, mock2 = rnd.sample(MOCKS, 2)
    comeback = rnd.choice(COMEBACKS)
    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    a("<title>The lion tries to eat the monkey. Again.</title>")
    a(scenery(pen, state["bananas"]))

    # --- the lion: path through the episode
    lion_xy = [(0, "-10 300"), (1.5, "70 300"), (2.2, "70 300"), (4.8, "320 300"),
               (5.2, "322 304"), (5.55, "322 306"), (5.9, "420 200"), (6.3, "496 160"),
               (6.6, "500 214"), (6.9, "496 300"), (10.8, "496 300"), (13.0, "-10 300")]
    lion_rot = [(0, "0 0 -48"), (5.55, "0 0 -48"), (5.9, "-22 0 -48"), (6.3, "-4 0 -48"),
                (6.6, "26 0 -48"), (6.9, "4 0 -48"), (7.2, "0 0 -48")] \
        + [(t, f"{v} 0 -48") for t, v in cycle(7.2, 10.4, .6, -3, 3)][1:]
    lion_sq = [(0, "1 1"), (5.2, "1 1"), (5.4, "1.05 .88"), (5.55, "1.08 .84"), (5.65, ".95 1.08"),
               (6.8, "1 1"), (6.92, "1.18 .7"), (7.15, "1.06 .86"), (10.6, "1.06 .86"), (10.8, "1 1")]
    shadow = [(t, f"{v.split()[0]} {GROUND + 2}") for t, v in lion_xy]
    a(f'<g>{tf("translate", shadow)}<ellipse cx="0" cy="0" rx="62" ry="6" fill="{INK}" opacity=".18">'
      + anim("rx", [(0, 62), (5.55, 62), (6.3, 30), (6.9, 70), (10.8, 70), (11.0, 62)]) + "</ellipse></g>")
    a(f'<g>{tf("translate", lion_xy)}<g>{tf("rotate", lion_rot)}<g>{tf("scale", lion_sq)}'
      f'<g>{tf("scale", [(0, "1 1"), (10.85, "1 1"), (10.86, "-1 1"), (13.4, "-1 1"), (13.41, "1 1")], "discrete")}'
      f'<g transform="scale(1.12)">{lion(pen)}</g></g></g></g></g>')

    # --- the bush the lion hides in, drawn in front of it
    a(bush(pen, 60, 268))

    # --- the monkey
    mk_xy = [(0, "556 152"), (5.95, "556 152"), (6.05, "560 146"), (6.25, "600 80"), (6.45, "650 96"),
             (6.6, "652 92")]
    mk_xy += [(t, f"652 {92 - v}") for t, v in cycle(7.6, 8.5, .3, 9, 0)][2:]
    mk_xy += [(t, f"652 {92 - v}") for t, v in cycle(10.45, 11.3, .3, 9, 0)][2:]
    mk_xy += [(12.0, "652 92"), (12.3, "610 70"), (12.6, "556 152")]
    a(f'<g>{tf("translate", mk_xy)}<g transform="scale(1.15)">{monkey(pen)}</g></g>')

    # --- effects
    a(f'<g opacity="0">{show(6.25, 6.95, .05)}<g transform="rotate(-8 340 112)">'
      + text(340, 112, "CHOMP!", 30, color=RED, weight="700") + "</g></g>")
    a(f'<g opacity="0">{show(6.9, 7.6, .05)}')                                # landing dust
    for dx, r in ((-40, 12), (-10, 16), (25, 14), (55, 11)):
        a(f'<circle cx="{496+dx}" cy="{GROUND-6}" r="{r}" fill="#efe2c2" stroke="{INK}" stroke-width="1">'
          f'<animate attributeName="r" dur="{D}s" repeatCount="indefinite" '
          f'keyTimes="0;{6.9/D:.4f};{7.6/D:.4f};1" values="{r*.3};{r*.3};{r*1.5};{r*.3}"/></circle>')
    a("</g>")
    a(f'<g opacity="0">{show(7.0, 10.4)}')                                    # dizzy stars
    for i in range(3):
        a(f'<g>{star(0, 0, 6)}<animateMotion dur="1.2s" begin="-{i*.4:.1f}s" repeatCount="indefinite" '
          f'path="M567,208 a26,8 0 1,0 0.1,0"/></g>')
    a("</g>")
    # banana peel thrown at the lion's head
    peel = [(0, "628 62"), (8.8, "628 62"), (9.05, "600 120"), (9.35, "566 222"), (9.6, "530 240"),
            (9.9, "450 296"), (12.9, "450 296")]
    a(f'<g opacity="0">{show(8.8, 12.9, .05)}<g>{tf("translate", peel)}'
      f'<g>{tf("rotate", [(0, "0"), (8.8, "0"), (9.9, "540"), (12.9, "540")])}'
      + pen.path([(-8, 4), (-3, -6), (0, 0), (3, -6), (8, 4), (0, 2)], fill=BANANA, close=True, w=1.2)
      + "</g></g></g>")
    a(f'<g opacity="0">{show(9.35, 9.95, .05)}' + text(512, 188, "bonk!", 20, color=RED, weight="700") + "</g>")

    # speech
    a(f'<g opacity="0">{show(7.4, 8.9)}{bubble(pen, 560, 46, mock1, (630, 66))}</g>')
    a(f'<g opacity="0">{show(10.0, 11.0)}{bubble(pen, 360, 212, comeback, (500, 236))}</g>')
    a(f'<g opacity="0">{show(10.4, 11.9)}{bubble(pen, 548, 46, mock2, (630, 66))}</g>')
    a(f'<g opacity="0">{show(1.5, 2.3)}' + text(160, 192, "…", 34, weight="700") + "</g>")

    a("</g>")  # end clip

    # caption under the picture
    a(f'<line x1="0" y1="{GROUND+1}" x2="{W}" y2="{GROUND+1}" stroke="none"/>')
    b = state["bananas"]
    line = (f'day {state["day"]}  ·  monkey {state["day"]}, lion 0  ·  '
            + (f'yesterday: {b} push{"es" if b != 1 else ""} → {b} banana{"s" if b != 1 else ""}'
               if b else "no pushes yesterday, so no bananas. the monkey is judging you."))
    a(f'<rect x="0" y="{GROUND+44}" width="{W}" height="{H-GROUND-44}" fill="{PAPER}"/>')
    a(text(W / 2, H - 15, line, 14, color="#5c544a"))
    a(f'<rect x="2" y="2" width="{W-4}" height="{H-4}" rx="8" fill="none" stroke="#d6cbb5" stroke-width="1.5"/>')
    a("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------- driver ----

def count_pushes(user, token, day):
    """Commits the user pushed on `day` (UTC), from public events."""
    req = urllib.request.Request(f"https://api.github.com/users/{user}/events/public?per_page=100",
                                 headers={"Accept": "application/vnd.github+json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        events = json.load(r)
    n = 0
    for e in events:
        if e.get("type") == "PushEvent" and e.get("created_at", "")[:10] == day.isoformat():
            p = e.get("payload") or {}
            n += p.get("size") or len(p.get("commits") or []) or 1
    return n


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    state = {"start": today.isoformat(), "day": 1, "bananas": 0}
    if STATE.exists():
        state.update(json.loads(STATE.read_text()))
    state["day"] = (today - dt.date.fromisoformat(state["start"])).days + 1
    if os.environ.get("BANANAS") is not None:
        state["bananas"] = int(os.environ["BANANAS"])
    else:
        user = os.environ.get("GH_USER", "")
        try:
            state["bananas"] = count_pushes(user, os.environ.get("GH_TOKEN"), today - dt.timedelta(days=1))
        except Exception as e:  # keep yesterday's bananas rather than fail the run
            print(f"could not fetch activity: {e}", file=sys.stderr)
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    OUT.write_text(render(state))
    print(f"day {state['day']}, {state['bananas']} bananas -> {OUT}")


if __name__ == "__main__":
    main()
