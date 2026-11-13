#!/usr/bin/env python3
"""A wild pixel-art fish for a GitHub profile README, in the style of git-koi.

A striped predator patrols a small pond in a figure eight, dashes through a
school of fry and strikes. It is redrawn every day from your activity:

* growth: your contribution streak sets its life stage. hatchling (0-2 days),
  young (3-6), adult (7-13), elder (14-29) and, at a 30-day streak, a dragon
  with horns and frilled fins. Break the streak and it starts over.
* mood: yesterday's contributions. none -> hungry (thin, misses both strikes),
  1-5 -> fed (catches one), 6+ -> feasting (plump, catches both).
* colour morph and stripes change with the date.
* the pond follows the season: autumn leaves, winter ice and snow, spring
  petals, summer lotus and a dragonfly.
* rare days: a golden fish, a heron's shadow passing over, or a fishing hook.
* variety: one of five routes (mirrored), eight colour morphs, four patterns
  (tiger, patches, spots, bands), its own fin and whisker length; some days a
  beetle lands on the water and gets gulped, or the fish slaps its tail.
* every loop: a straggler fry is chased and hides under a lily pad, and the
  school scatters when the fish dashes through.

    python3 fish/fish.py                      # fetch activity, draw fish/fish.gif
    STREAK=31 CONTRIB=8 DATE=2026-07-02 EVENT=heron python3 fish/fish.py

Needs Pillow and numpy.
"""
import datetime as dt
import hashlib
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE / "fish.gif"
STATE = HERE / "state.json"

CW, CH = 800, 288
F = 160
FRAME_MS = 60
SUB = 4
CX, CY = 400, 144
PA, PB = CW / 2 - 4, CH / 2 - 4        # edge of the water (rounded rectangle), used for winter frost
N_FRY = 10

HEX = """181425 262b44 3a4466 5a6988 8b9bb4 c0cbdc ffffff 124e89 0099db 2ce8f5
3e2731 a22633 e43b44 f6757a be4a2f f77622 feae34 fee761 733e39
193c3e 265c42 3e8948 63c74d 68386c b55088 e8b796 c28569""".split()
PAL = [tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in HEX]
C = {h: i for i, h in enumerate(HEX)}


def R(*hs):
    return [C[h] for h in hs]


OUTLINE = C["181425"]
MORPHS = {
    "fire tiger": dict(base=R("a22633", "e43b44", "f77622", "feae34", "fee761"),
                       stripe=R("181425", "262b44", "3a4466"),
                       crown=R("3e2731", "a22633", "e43b44", "f6757a"),
                       line=R("124e89", "0099db", "2ce8f5", "ffffff"),
                       tip=R("f77622", "feae34", "fee761")),
    "ghost": dict(base=R("5a6988", "8b9bb4", "c0cbdc", "ffffff"),
                  stripe=R("124e89", "0099db", "2ce8f5"),
                  crown=R("a22633", "e43b44", "f6757a"),
                  line=R("a22633", "e43b44", "f6757a", "ffffff"),
                  tip=R("0099db", "2ce8f5", "ffffff")),
    "jade": dict(base=R("193c3e", "265c42", "3e8948", "63c74d"),
                 stripe=R("181425", "262b44", "193c3e"),
                 crown=R("be4a2f", "feae34", "fee761"),
                 line=R("0099db", "2ce8f5", "ffffff"),
                 tip=R("feae34", "fee761", "ffffff")),
}
MORPHS.update({
    "kohaku": dict(base=R("8b9bb4", "c0cbdc", "ffffff", "ffffff"),
                   stripe=R("a22633", "e43b44", "f77622"),
                   crown=R("a22633", "e43b44", "f6757a"),
                   line=R("124e89", "0099db", "2ce8f5", "ffffff"),
                   tip=R("e43b44", "f6757a", "ffffff")),
    "azure": dict(base=R("124e89", "0099db", "2ce8f5", "ffffff"),
                  stripe=R("181425", "262b44", "124e89"),
                  crown=R("feae34", "fee761", "ffffff"),
                  line=R("fee761", "ffffff", "fee761", "ffffff"),
                  tip=R("2ce8f5", "ffffff", "ffffff")),
    "ember": dict(base=R("3e2731", "a22633", "e43b44", "f77622"),
                  stripe=R("181425", "262b44", "3e2731"),
                  crown=R("feae34", "fee761", "ffffff"),
                  line=R("f77622", "feae34", "fee761", "ffffff"),
                  tip=R("e43b44", "f77622", "feae34")),
    "sakura": dict(base=R("c28569", "e8b796", "ffffff", "ffffff"),
                   stripe=R("68386c", "b55088", "f6757a"),
                   crown=R("b55088", "f6757a", "ffffff"),
                   line=R("b55088", "f6757a", "ffffff", "ffffff"),
                   tip=R("f6757a", "e8b796", "ffffff")),
})
PATTERNS = ["tiger", "patches", "spots", "bands"]
GOLDEN = dict(base=R("733e39", "be4a2f", "feae34", "fee761", "ffffff"),
              stripe=R("be4a2f", "f77622", "feae34"),
              crown=R("a22633", "e43b44", "f6757a"),
              line=R("fee761", "ffffff", "2ce8f5", "ffffff"),
              tip=R("feae34", "fee761", "ffffff"))
FIN = R("3a4466", "5a6988", "8b9bb4", "c0cbdc", "ffffff")
ROCK = R("181425", "262b44", "3a4466", "5a6988", "8b9bb4")
PAD = R("193c3e", "265c42", "3e8948", "63c74d")
PAD_AUTUMN = R("3e2731", "733e39", "be4a2f", "feae34")
LOTUS = R("68386c", "b55088", "f6757a", "ffffff")
ICE = R("8b9bb4", "c0cbdc", "ffffff")

STAGES = [  # (min streak, name, scale, fin length factor)
    (0, "hatchling", .9, .85), (3, "young", .95, .95), (7, "adult", 1.0, 1.0),
    (14, "elder", 1.05, 1.25), (30, "dragon", 1.12, 1.35)]

BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + .5) / 16


def shade(L, ramp, ys, xs, spread=.42):
    v = np.clip(L, 0, 1) * (len(ramp) - 1) + (BAYER[ys % 4, xs % 4] - .5) * spread
    return np.asarray(ramp)[np.clip(np.rint(v), 0, len(ramp) - 1).astype(int)]


def vnoise(seed, u, v):
    g = np.random.default_rng(seed).random((64, 64))
    u, v = np.asarray(u) % 63, np.asarray(v) % 63
    i, j = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - i, v - j
    fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
    a, b, c, d = g[i, j], g[i + 1, j], g[i, j + 1], g[i + 1, j + 1]
    return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + d * fu) * fv


def rot(v, a):
    c, s = math.cos(a), math.sin(a)
    return np.array([v[0] * c - v[1] * s, v[0] * s + v[1] * c])


def perp(v):
    return np.array([-v[1], v[0]])


def unit(v):
    return v / (np.linalg.norm(v) + 1e-9)


def dilate(m):
    o = m.copy()
    o[1:] |= m[:-1]; o[:-1] |= m[1:]; o[:, 1:] |= m[:, :-1]; o[:, :-1] |= m[:, 1:]
    return o


def poly_mask(pts):
    im = Image.new("1", (CW, CH), 0)
    ImageDraw.Draw(im).polygon([(float(x), float(y)) for x, y in pts], fill=1)
    return np.array(im, bool)


def line(img, a, b, color, mask=None):
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    for i in range(n + 1):
        x = int(round(a[0] + (b[0] - a[0]) * i / n))
        y = int(round(a[1] + (b[1] - a[1]) * i / n))
        if 0 <= x < CW and 0 <= y < CH:
            img[y, x] = color
            if mask is not None:
                mask[y, x] = True


def ring(img, c, r, color, density=1.0, seed=0):
    n = max(8, int(2 * math.pi * r))
    rng = np.random.default_rng(seed)
    for i in range(n):
        if density < 1 and rng.random() > density:
            continue
        a = 2 * math.pi * i / n
        x, y = int(round(c[0] + r * math.cos(a))), int(round(c[1] + r * .55 * math.sin(a)))
        if 0 <= x < CW and 0 <= y < CH:
            img[y, x] = color


# ------------------------------------------------------------------ config --

class Chase:
    """The story of one curious fry.

    It wanders off from the school towards the bottom-right corner. The big fish
    comes round the corner, spots it, and chases it up the right side; the fry
    zigzags ahead of the jaws and dives under a lily pad just in time. The fish
    snaps at empty water and swims on; the fry peeks out and sneaks home.
    Everything is a function of the frame, so the loop stays seamless.
    """

    def __init__(self, dash):
        T, _, _, strikes = _path(dash)
        k, m = 240, len(WAYPOINTS)

        def gap(t):                                    # frames to the nearest strike
            return min((min(abs(t - u) % F, F - abs(t - u) % F) for u in strikes), default=F)

        best = None
        for c in range(m):                             # chase round the corner furthest from the strikes
            if not is_corner(WAYPOINTS[c]):
                continue
            t_c = T[c * k]
            t_n = T[((c + 1) % m) * k] + (F if c + 1 == m else 0)
            window = [t_c - 14 + i for i in range(0, int(t_n - t_c) + 40, 4)]
            score = min(gap(t) for t in window)
            if best is None or score > best[0]:
                best = (score, t_c, t_n)
        if best is None:
            best = (0, T[0], T[k])
        _, t_br, t_tr = best
        self.notice = int(round(t_br - 14))
        self.hide = int(round(t_br + (t_tr - t_br) * .45 + 3))
        self.snap = self.hide + 3
        self.out = self.hide + 30
        self.home = self.out + 46
        hp = head_at(self.snap + 3, dash)
        self.pad = hp + unit(np.array([CX, CY]) - hp) * 14         # right in its path
        self.pad = np.clip(self.pad, (24, 24), (CW - 24, CH - 24))

        def route(t):
            return head_at(t, dash)

        def chase_pos(f):
            q = (f - self.notice) / (self.hide - self.notice)
            t = f + 13 - 8 * q                                   # the gap closes
            d = unit(route(t + .5) - route(t - .5))
            return route(t) + perp(d) * 7 * math.sin((f - self.notice) * .9)

        def ease(q):
            return .5 - .5 * math.cos(math.pi * min(max(q, 0.0), 1.0))

        start, dive_from = chase_pos(self.notice), chase_pos(self.hide)
        school = SCHOOL + unit(self.pad - SCHOOL) * 55
        peek = self.pad + unit(school - self.pad) * 15
        pos, hidden, alert = np.zeros((F, 2)), np.zeros(F, bool), np.zeros(F, bool)
        for f in range(self.notice, self.notice + F):
            if f <= self.hide:
                p = chase_pos(f)
            elif f <= self.hide + 4:
                p = dive_from + (self.pad - dive_from) * ease((f - self.hide) / 4)
            elif f <= self.out:
                p = self.pad.copy()
            elif f <= self.out + 8:
                p = self.pad + (peek - self.pad) * ease((f - self.out) / 8)
            elif f <= self.out + 16:
                p = peek.copy()                                  # is it gone?
            elif f <= self.home:
                p = peek + (school - peek) * ease((f - self.out - 16) / (self.home - self.out - 16))
            else:                                                # drifts off again, nosing about
                q = (f - self.home) / (self.notice + F - self.home)
                p = school + (start - school) * ease(q)
                p = p + np.array([math.sin(q * 9), math.cos(q * 7)]) * 10 * math.sin(math.pi * q)
            g = f % F
            pos[g] = p
            hidden[g] = self.hide + 3 <= f <= self.out
            alert[g] = self.notice <= f <= self.notice + 10
        self.pos, self.hidden, self.alert = pos, hidden, alert
        self.notice, self.hide, self.snap, self.out = (self.notice % F, self.hide % F, self.snap % F, self.out % F)
        self.vel = (np.roll(pos, -1, 0) - np.roll(pos, 1, 0)) / 2


class Day:
    """Everything that varies from day to day."""

    def __init__(self, date, streak, contrib, event=None):
        self.date, self.streak, self.contrib = date, streak, contrib
        self.seed = int(hashlib.sha256(date.isoformat().encode()).hexdigest()[:8], 16)
        for lo, name, scale, fins in STAGES:
            if streak >= lo:
                self.stage, self.S, self.fins = name, scale, fins
        # a quiet day is a calm cruise, not a failed hunt
        self.mood = "resting" if contrib == 0 else "hunting" if contrib <= 5 else "feasting"
        self.width = {"resting": 1.0, "hunting": 1.0, "feasting": 1.06}[self.mood]
        self.dash = .1 if self.mood == "resting" else .32
        rng = np.random.default_rng(self.seed)
        # today's route, mirrored at random
        self.route = list(ROUTES)[int(rng.integers(len(ROUTES)))]
        way, school = ROUTES[self.route]
        flip = np.array([rng.choice([-1, 1]) * RX, rng.choice([-1, 1]) * RY])
        configure(np.array(way) * flip + (CX, CY), np.array(school) * flip + (CX, CY))
        strikes = tuple(_path(self.dash)[3])
        self.eats = () if self.mood == "resting" else strikes
        self.catches = {"resting": set(), "hunting": set(strikes[:1]), "feasting": set(strikes)}[self.mood]
        self.chase = Chase(self.dash)
        self.snaps = list(self.eats) + [self.chase.snap]
        # this fish's own build
        self.fin_mul = rng.uniform(.88, 1.18)
        self.whisk_mul = rng.uniform(.8, 1.3)
        self.width *= rng.uniform(.94, 1.06)
        self.tail_spread = rng.uniform(.75, 1.25)
        self.pattern = PATTERNS[int(rng.integers(len(PATTERNS)))]

        # extra moments, on some days: an insect on the surface, a tail slap in a turn
        def free(t, pad):
            busy = list(strikes) + [self.chase.notice + i for i in range(0, (self.chase.out - self.chase.notice) % F, 3)]
            return all(min(abs(t - u) % F, F - abs(t - u) % F) > pad for u in busy)

        self.bug = None
        if rng.random() < .65:
            options = [t for t in range(F) if free(t, 26)]
            if options:
                self.bug = int(options[int(rng.integers(len(options)))])
                self.snaps.append(self.bug)
        self.slap = None
        if rng.random() < .5:
            T = _path(self.dash)[0]
            corners = [int(round(T[i * 240])) % F for i, c in enumerate(WAYPOINTS) if is_corner(c)]
            corners = [t for t in corners if free(t, 12) and (self.bug is None or abs(t - self.bug) > 12)]
            if corners:
                self.slap = corners[int(rng.integers(len(corners)))]
        if event is None:
            h = self.seed % 100
            event = "golden" if h < 6 else "heron" if h < 12 else "hook" if h < 18 else ""
        self.event = event
        names = list(MORPHS)
        self.morph_name = "golden" if event == "golden" else names[int(rng.integers(len(names)))]
        if self.morph_name == "kohaku":
            self.pattern = "patches"
        self.morph = GOLDEN if event == "golden" else MORPHS[self.morph_name]
        m = date.month
        self.season = ("winter" if m in (12, 1, 2) else "spring" if m in (3, 4, 5)
                       else "summer" if m in (6, 7, 8) else "autumn")

    def label(self):
        bits = [f"{self.stage} {self.morph_name}", f"{self.streak}-day streak", self.mood]
        if self.event in ("heron", "hook"):
            bits.append(f"{self.event}!")
        return " - ".join(bits).upper()


# ------------------------------------------------------------------ motion --

RX, RY = 318, 90
# each route: waypoints and where the school gathers, in units of (RX, RY) around the centre
ROUTES = {
    "bow-tie": ([(-1, -1), (0, 0), (1, 1), (1, -1), (0, 0), (-1, 1)], (0, 0)),
    "grand tour": ([(-1, -1), (0, -1.02), (1, -1), (1, 0), (1, 1), (0, .05), (-1, 1), (-1, 0)], (0, .05)),
    "double eight": ([(-1, -.2), (-.6, -1), (0, 0), (.6, 1), (1, .2), (.6, -1), (0, 0), (-.6, 1)], (0, 0)),
    "zigzag": ([(-1, -1), (-.4, 1), (.2, -1), (1, 1), (1, -1), (.1, .1), (-1, 1)], (.1, .1)),
    "racetrack": ([(-1, -1), (0, -1.02), (1, -1), (1, 1), (.3, .25), (-.3, -.25), (-1, 1)], (0, 0)),
}
FRAMES_PER_LEG = 30
WAYPOINTS = SCHOOL = None
_PATHS = {}


def configure(waypoints, school):
    """Set today's route. The loop length follows the number of legs."""
    global WAYPOINTS, SCHOOL, F
    WAYPOINTS, SCHOOL = np.asarray(waypoints, float), np.asarray(school, float)
    F = FRAMES_PER_LEG * len(WAYPOINTS)
    _PATHS.clear()


def is_corner(p):
    return abs(p[0] - CX) > .9 * RX and abs(p[1] - CY) > .85 * RY


def _path(dash):
    """Closed Catmull-Rom loop through the waypoints, timed so the fish slows into
    the corners and dashes past the school. Returns (times, xs, ys, strike times)."""
    if dash in _PATHS:
        return _PATHS[dash]
    P, m, k = WAYPOINTS, len(WAYPOINTS), 240
    pts = []
    for i in range(m):
        p0, p1, p2, p3 = P[i - 1], P[i], P[(i + 1) % m], P[(i + 2) % m]
        for j in range(k):
            t = j / k
            pts.append(.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                             + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    pts = np.array(pts + [pts[0]])
    ds = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    mid = (pts[:-1] + pts[1:]) / 2
    dsch = np.linalg.norm(mid - SCHOOL, axis=1)
    corners = [c for c in P if is_corner(c)] or [P[0]]
    dk = np.min([np.linalg.norm(mid - c, axis=1) for c in corners], axis=0)
    v = 1 + 2.2 * dash * np.exp(-(dsch / 80) ** 2) - .3 * np.exp(-(dk / 70) ** 2)
    T = np.concatenate([[0], np.cumsum(ds / v)])
    T *= F / T[-1]
    # strikes: every pass close by the school
    d = np.linalg.norm(pts[:-1] - SCHOOL, axis=1)
    n = len(d)
    mins = [i for i in range(n) if d[i] < 45 and d[i] <= d[i - 1] and d[i] <= d[(i + 1) % n]]
    if not mins:
        mins = [int(d.argmin())]
    strikes = []
    for i in sorted(mins, key=lambda i: d[i]):
        t = int(round(T[i])) % F
        if all(min(abs(t - u), F - abs(t - u)) > 20 for u in strikes):
            strikes.append(t)
    _PATHS[dash] = (T, pts[:, 0], pts[:, 1], sorted(strikes))
    return _PATHS[dash]


def head_at(t, dash=.32):
    T, xs, ys, _ = _path(dash)
    t = t % F
    return np.array([np.interp(t, T, xs), np.interp(t, T, ys)])


def head_pos(t, day):
    p = head_at(t, day.dash)
    d = head_at(t + .5, day.dash) - head_at(t - .5, day.dash)
    sp = np.linalg.norm(d) + 1e-9
    amp = (1.2 + .55 * sp) * (.7 if day.mood == "resting" else 1.0)
    return p + perp(d) / sp * amp * math.sin(2 * math.pi * 18 * t / F)


def follow(pts, head, seg):
    pts[0] = head
    for i in range(1, len(pts)):
        pts[i] = pts[i - 1] + unit(pts[i] - pts[i - 1]) * seg


def follow_biased(pts, base, seg, bias, k):
    pts[0] = base
    for i in range(1, len(pts)):
        d = unit(pts[i] - pts[i - 1]) * (1 - k) + bias * k
        pts[i] = pts[i - 1] + unit(d) * seg


def heron_at(f):
    """Centre of the heron's shadow, frames 34-86, else None."""
    a, b = int(.28 * F), int(.72 * F)
    if not a <= f <= b:
        return None
    q = (f - a) / (b - a)
    return np.array([-110 + q * (CW + 220), 70 + q * 110])


N = 26


def simulate(day):
    S = day.S
    seg = 6.0 * S
    rng = np.random.default_rng(day.seed)
    body = np.array([head_at(0) - [i * seg, 0] for i in range(N)], float)
    tails = [np.repeat(body[-1:], 12, 0).astype(float) for _ in range(2)]
    wl = {"hatchling": 8, "young": 11, "dragon": 17}.get(day.stage, 13)
    whisk = [np.repeat(body[:1], n, 0).astype(float) for n in (wl, wl, 7, 7)]
    slots = [(rng.uniform(10, 44), rng.uniform(0, math.tau), int(rng.choice([-2, -1, 1, 2])),
              rng.uniform(.5, .8)) for _ in range(N_FRY)]
    fry = np.array([SCHOOL] * N_FRY, float) + rng.normal(0, 10, (N_FRY, 2))
    vel = np.zeros_like(fry)
    victims, hidden, rec = {}, np.zeros(N_FRY, bool), []

    def target(k, t):
        r, ph, m, sq = slots[k]
        a = ph + 2 * math.pi * m * t / F
        c = SCHOOL + np.array([20 * math.sin(2 * math.pi * t / F), 12 * math.sin(4 * math.pi * t / F + 1)])
        return c + r * np.array([math.cos(a), math.sin(a) * sq])

    loops = 4
    for f_abs in range(loops * F):
        f = f_abs % F
        for s in range(SUB):
            t = f + s / SUB
            follow(body, head_pos(t, day), seg)
            axis = unit(body[-1] - body[-2])
            for side, tl in zip((-1, 1), tails):
                follow_biased(tl, body[-2] * .3 + body[-1] * .7, 4.1 * S * day.fins * day.fin_mul,
                              unit(axis + side * day.tail_spread * perp(axis)), .2)
            fwd = unit(body[0] - body[1])
            for i, w in enumerate(whisk):
                side = -1 if i % 2 == 0 else 1
                base = body[0] + fwd * (8 if i < 2 else 5) * S + perp(fwd) * side * (5 if i < 2 else 8) * S
                follow_biased(w, base, 3.4 * S * day.whisk_mul, unit(-.45 * fwd + side * perp(fwd)), .2)
            mouth = body[0] + fwd * 7 * S
            heron = heron_at(f) if day.event == "heron" else None
            for k in range(N_FRY):
                if hidden[k]:
                    continue
                acc = .03 * (target(k, t) - fry[k]) - .11 * vel[k]
                for src, rad, power in ((mouth, 115, 2.2), (heron, 130, 1.2)):
                    if src is None:
                        continue
                    d = fry[k] - src
                    dist = np.linalg.norm(d) + 1e-9
                    if dist < rad:
                        acc += d / dist * power * (1 - dist / rad) ** 2
                        if src is mouth:                        # fountain: split to either side of the fish
                            side = 1 if fwd[0] * d[1] - fwd[1] * d[0] > 0 else -1
                            acc += perp(fwd) * side * 1.6 * (1 - dist / rad) ** 2
                for j in range(N_FRY):                          # personal space
                    if j != k and not hidden[j]:
                        d = fry[k] - fry[j]
                        dist = np.linalg.norm(d)
                        if 0 < dist < 8:
                            acc += d / dist * .35 * (1 - dist / 8)
                vel[k] += acc / SUB * 4
                sp = np.linalg.norm(vel[k])
                if sp > 5.5:
                    vel[k] *= 5.5 / sp
                fry[k] += vel[k] / SUB
        fwd = unit(body[0] - body[1])
        mouth = body[0] + fwd * 7 * S
        for te in day.eats:
            if f == te - 6 and te not in victims:
                taken = set(victims.values())
                order = np.argsort(np.linalg.norm(fry - mouth, axis=1))
                victims[te] = int(next(i for i in order if i not in taken))
            if te not in victims:
                continue
            k = victims[te]
            if te in day.catches:
                if te - 6 <= f < te:
                    fry[k] += (mouth - fry[k]) * .45
                    vel[k] *= 0
                if f == te:
                    hidden[k] = True
                if f == (te + 16) % F:
                    hidden[k] = False
                    fry[k] = np.array([CX + 380 * (1 if mouth[0] < CX else -1), CY + rng.uniform(-40, 40)])
                    vel[k] = unit(SCHOOL - fry[k]) * 3.5
            else:
                if te - 6 <= f < te - 2:                        # nearly...
                    fry[k] += (mouth - fry[k]) * .25
                if f == te - 2:                                 # ...and it darts away
                    vel[k] = unit(fry[k] - mouth + perp(fwd) * 3) * 9
        if f_abs >= (loops - 1) * F:
            rec.append(dict(body=body.copy(), tails=[t.copy() for t in tails], whisk=[w.copy() for w in whisk],
                            fry=fry.copy(), fvel=vel.copy(), hidden=hidden.copy(), mouth=mouth.copy()))
    return rec


# ----------------------------------------------------------------- the fish --

def resample(pts, step=1.25):
    sl = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(sl)])
    n = max(2, int(s[-1] / step))
    q = np.linspace(0, s[-1], n)
    return np.stack([np.interp(q, s, pts[:, 0]), np.interp(q, s, pts[:, 1])], 1)


def tube(pts, radius_fn):
    sp = resample(np.asarray(pts, float))
    u_pts = np.linspace(0, 1, len(sp))
    r = radius_fn(u_pts)
    x0, y0 = max(int(np.floor((sp[:, 0] - r).min())) - 1, 0), max(int(np.floor((sp[:, 1] - r).min())) - 1, 0)
    x1, y1 = min(int(np.ceil((sp[:, 0] + r).max())) + 2, CW), min(int(np.ceil((sp[:, 1] + r).max())) + 2, CH)
    if x1 <= x0 or y1 <= y0:
        e = np.array([], int)
        return e, e, np.array([]), np.array([])
    ys, xs = np.mgrid[y0:y1, x0:x1]
    px, py = xs.ravel() + .5, ys.ravel() + .5
    dx, dy = px[:, None] - sp[None, :, 0], py[:, None] - sp[None, :, 1]
    score = np.sqrt(dx * dx + dy * dy) - r[None, :]
    j = score.argmin(1)
    inside = score[np.arange(len(j)), j] <= 0
    j = j[inside]
    tang = np.gradient(sp, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
    cross = tang[j, 0] * dy[inside, j] - tang[j, 1] * dx[inside, j]
    return ys.ravel()[inside], xs.ravel()[inside], u_pts[j], np.clip(cross / np.maximum(r[j], .5), -1, 1)


def draw_fish(fr, f, day, glints):
    """Returns (index image, mask) of the fish alone."""
    S, morph = day.S, day.morph
    img = np.full((CH, CW), -1, int)
    fish = np.zeros((CH, CW), bool)
    body, tails, whisk = fr["body"], fr["tails"], fr["whisk"]
    fwd = unit(body[0] - body[1])
    tc = 2 * math.pi * f / F

    def body_radius(u):
        w = np.where(u < .2, .62 + .38 * np.sqrt(np.clip(u / .2, 0, 1)), 1.0)
        w = np.where(u > .42, 1 - .8 * np.clip((u - .42) / .58, 0, 1) ** 1.25, w)
        return 13.0 * S * day.width * w

    def paint(ys, xs, col):
        img[ys, xs] = col
        fish[ys, xs] = True

    def fin(pts, rad, tip_from=.62):
        ys, xs, u, s = tube(pts, rad)
        if not len(ys):
            return
        L = .35 + .55 * (1 - np.abs(s)) + .1 * np.sin(u * 9)
        col = shade(L, FIN, ys, xs)
        ray = (np.floor((s + 1) * 2.4 + u * 1.5) % 2 == 0) & (u > .15)
        col = np.where(ray, shade(L - .3, FIN, ys, xs), col)
        tip = u > tip_from + .08 * np.sin(s * 5 + f * .2)
        col = np.where(tip, shade(.4 + .5 * (1 - np.abs(s)), morph["tip"], ys, xs), col)
        paint(ys, xs, col)

    # whiskers, roots under the head
    for w in whisk:
        for i, (a, b) in enumerate(zip(w, w[1:])):
            q = i / (len(w) - 1)
            line(img, a, b, C["8b9bb4"] if q < .35 else C["5a6988"] if q < .75 else morph["line"][-2])

    # pectoral + pelvic fins
    for side in (-1, 1):
        for idx, length, spread, rmax, beat in ((4, 30, 1.0, 7.0, 0), (13, 16, .75, 4.2, 1.4)):
            ax = unit(body[idx + 1] - body[idx - 1])
            n = perp(ax)
            ang = side * (.95 + .35 * math.sin(tc * 7 + beat + (side > 0) * .9)) * spread
            dirv = rot(ax, ang)
            root = body[idx] + n * side * body_radius(np.array([idx / (N - 1)]))[0] * .7
            L = length * S * day.fins * day.fin_mul
            pts = [root + dirv * L * i / 6 + n * side * math.sin(i * .5) * 1.5 * S for i in range(7)]
            fin(pts, lambda u, rm=rmax * S: rm * np.sin(np.clip(u, .08, 1) * math.pi) ** .7 + .6)

    # dragon frills: a row of little sail fins down both flanks
    if day.stage == "dragon":
        for idx in range(6, 19, 3):
            ax = unit(body[idx + 1] - body[idx - 1])
            for side in (-1, 1):
                n = perp(ax)
                root = body[idx] + n * side * body_radius(np.array([idx / (N - 1)]))[0] * .8
                tipp = root + rot(ax, side * (2.2 + .25 * math.sin(tc * 5 + idx))) * 9 * S
                fin([root, (root + tipp) / 2, tipp], lambda u: 2.6 * S * (1 - u) + .5, tip_from=.45)

    for tl in tails:
        fin(tl, lambda u: (1.8 + 9.5 * np.sin(np.clip(u, 0, 1) * math.pi * .8) ** 1.1) * S, tip_from=.58)

    # body
    ys, xs, u, s = tube(body, body_radius)
    L = .3 + .62 * np.sqrt(np.clip(1 - s * s, 0, 1)) - .2 * s - .12 * np.clip((u - .8) * 5, 0, 1)
    col = shade(L, morph["base"], ys, xs)
    n1 = vnoise(day.seed, u * 30, s * 3 + 7)
    inb = (u > .14) & (u < .93)
    if day.pattern == "tiger":                                   # chevron stripes from the flanks
        sv = (u * 10.5 + .55 * np.abs(s) ** 1.3 + .45 * n1) % 1
        stripe = (sv < .34) & inb & (np.abs(s) > .12 + .35 * n1)
    elif day.pattern == "patches":                               # big koi patches
        stripe = (vnoise(day.seed + 3, u * 7, s * 1.6 + 3) > .52) & inb
    elif day.pattern == "spots":                                 # leopard spots
        sp = vnoise(day.seed + 4, u * 26, s * 4.5 + 9)
        stripe = (sp > .66) & inb & (np.abs(s) > .15)
    else:                                                        # three broad saddles
        sv = (u * 3.4 + .25 * n1) % 1
        stripe = (sv < .3) & inb & (u > .22)
    col = np.where(stripe, shade(L - .1, morph["stripe"], ys, xs), col)
    crown = (((u - .1) / .055) ** 2 + (s / (.34 - 1.6 * np.clip(.1 - u, -.1, .1))) ** 2
             < 1 + .5 * (vnoise(day.seed + 1, u * 40, s * 4) - .5))
    col = np.where(crown, shade(L - .12, morph["crown"], ys, xs), col)
    pulse = np.exp(-((u - ((f / F * 3) % 1) * .62 - .16) / .05) ** 2)
    dl = (np.abs(s + .06 * np.sin(u * 20 + f * .4)) < .11) & (u > .16) & (u < .8) & (day.stage != "hatchling")
    col = np.where(dl, shade(.25 + .75 * pulse, morph["line"], ys, xs, .6), col)
    paint(ys, xs, col)

    for gu, gs, ph in glints:
        if math.sin(tc * 3 + ph) > .9:
            j = int(gu * (N - 1))
            ax = unit(body[j + 1] - body[j - 1])
            p = body[j] - perp(ax) * gs * body_radius(np.array([gu]))[0]
            x, y = int(round(p[0])), int(round(p[1]))
            if 0 <= x < CW and 0 <= y < CH and fish[y, x]:
                img[y, x] = C["ffffff"]

    # dragon horns: ivory antlers swept out past the head, with a forward tine
    if day.stage == "dragon":
        horn = R("5a6988", "c0cbdc", "ffffff")
        hm = np.zeros((CH, CW), bool)
        parts = []
        for side in (-1, 1):
            base = body[0] - fwd * 4 * S + perp(fwd) * side * 6 * S
            back = rot(-fwd, side * -.95)
            p1 = base + back * 9 * S
            p2 = p1 + rot(back, side * .45) * 11 * S
            tine = p1 + rot(back, side * -1.2) * 6 * S
            for a, b in ((base, p1), (p1, p2), (p1, tine)):
                ys, xs, u, s = tube([a, (a + b) / 2, b], lambda u: 1.7 * S * (1 - .45 * u) + .5)
                parts.append((ys, xs, shade(.5 + .45 * (1 - np.abs(s)) - .2 * s, horn, ys, xs)))
                hm[ys, xs] = True
        img[dilate(hm) & ~hm] = OUTLINE
        fish |= dilate(hm)
        for ys, xs, col in parts:
            img[ys, xs] = col

    # eyes
    for side in (-1, 1):
        p = body[0] - fwd * 3 * S + perp(fwd) * side * 5.6 * S
        x, y = int(round(p[0])), int(round(p[1]))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if abs(dx) + abs(dy) < 2 and 0 <= y + dy < CH and 0 <= x + dx < CW:
                    img[y + dy, x + dx] = OUTLINE
        if 0 <= y < CH and 0 <= x < CW:
            img[y, x] = C["e43b44"]
        g = p + fwd * .8 - perp(fwd) * side * .8
        gx, gy = int(round(g[0])), int(round(g[1]))
        if 0 <= gy < CH and 0 <= gx < CW:
            img[gy, gx] = C["ffffff"]

    # mouth opens before each strike, and at the lily pad
    for te in day.snaps:
        if 0 <= te - f <= 4:
            gape = 1 - (te - f) / 5
            ys, xs, u, s = tube(body[:6], lambda u: body_radius(u * 5 / 25))
            m = (u < .2 * gape + .02) & (np.abs(s) < .55 * gape)
            img[ys[m], xs[m]] = -1
            fish[ys[m], xs[m]] = False
            inner = (u < .2 * gape) & (np.abs(s) < .3 * gape)
            img[ys[inner], xs[inner]] = C["3e2731"]
            fish[ys[inner], xs[inner]] = True

    out = dilate(fish) & ~fish
    img[out] = OUTLINE
    return img, fish | out


# -------------------------------------------------------------- the pond --

class Pond:
    """A pond seen from straight above: a rim of stones around open water.

    The water itself stays transparent, so the page behind it is the pond.
    Everything inside is muted so the fish is the only bright thing.
    """

    @staticmethod
    def rim_point(th, k=1.0):
        """Point on the rounded-rectangle rim (a superellipse) at angle th."""
        c, sn = math.cos(th), math.sin(th)
        return np.array([CX + PA * k * math.copysign(abs(c) ** .5, c),
                         CY + PB * k * math.copysign(abs(sn) ** .5, sn)])

    @staticmethod
    def rnorm(x, y):
        return ((np.abs(x - CX) / PA) ** 4 + (np.abs(y - CY) / PB) ** 4) ** .25

    def __init__(self, day):
        self.day = day
        rng = np.random.default_rng(day.seed + 11)
        self.rng = rng
        self.rim = np.full((CH, CW), -1, int)
        self.under = np.full((CH, CW), -1, int)
        self._submerged(CX - 170, CY + 96)
        hp = day.chase.pad
        self.pads = [(hp[0], hp[1], 18, rng.uniform(0, 6))]
        for _ in range(int(rng.integers(1, 5))):                 # a few more, somewhere near the banks
            for _try in range(20):
                x = CX + rng.uniform(-.92, .92) * (CW / 2)
                y = rng.choice([rng.uniform(16, 40), rng.uniform(CH - 40, CH - 16)])
                if all(math.hypot(x - px, y - py) > 40 for px, py, _, _ in self.pads):
                    self.pads.append((x, y, rng.uniform(7, 15), rng.uniform(0, 6)))
                    if rng.random() < .4:                        # a baby pad alongside
                        self.pads.append((x + rng.uniform(-22, 22), y + rng.uniform(-8, 8), rng.uniform(5, 7),
                                          rng.uniform(0, 6)))
                    break
        self.leaves = [(CX + rng.uniform(-330, 330), CY + rng.uniform(-90, 90), rng.uniform(3, 6),
                        rng.uniform(0, 6), int(rng.choice([-1, 1])), int(rng.integers(0, 3)))
                       for _ in range(int(rng.integers(2, 7)))]
        self.flakes = [(rng.uniform(0, CW), rng.uniform(0, CH), rng.uniform(0, 6)) for _ in range(20)]
        self.drips = [(int(rng.uniform(0, F)), self.inside(rng)) for _ in range(3)]
        self.hook = np.array([CX + rng.uniform(-260, 260), CY + rng.uniform(-60, 60)])
        self.ice = np.zeros((CH, CW), bool)
        if day.season == "winter":
            yy, xx = np.mgrid[0:CH, 0:CW]
            rn = self.rnorm(xx, yy)
            n = vnoise(day.seed + 5, xx / 8.0, yy / 8.0)
            self.ice = (rn < 1.0) & (rn > .975 - .05 * n) & (vnoise(day.seed + 6, xx / 30.0, yy / 30.0) > .35)

    def inside(self, rng):
        return np.array([CX + rng.uniform(-.75, .75) * PA, CY + rng.uniform(-.65, .65) * PB])

    def _stone(self, layer, cx, cy, rx, ry, ramp, light=.62):
        pts = []
        for i in range(12):
            a = 2 * math.pi * i / 12
            r = 1 + self.rng.uniform(-.1, .08)
            pts.append((cx + rx * r * math.cos(a), cy + ry * r * math.sin(a)))
        m = poly_mask(pts)
        ys, xs = np.nonzero(m)
        L = light - .4 * ((xs - cx) / rx + (ys - cy) / ry) / 2 - .2 * ((ys - cy) / ry) ** 2
        L = L + .25 * (vnoise(int(cx * 7 + cy), xs / 3.0, ys / 3.0) - .5)
        layer[ys, xs] = shade(L, ramp, ys, xs, .7)
        layer[dilate(m) & ~m] = OUTLINE
        return m

    def _build_rim(self):
        rng = self.rng
        ramp = R("181425", "262b44", "3a4466", "5a6988", "8b9bb4")
        ths = np.linspace(0, math.tau, 3000)
        pts = np.array([self.rim_point(t) for t in ths])
        cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        total = cum[-1]
        boulders = rng.uniform(0, total, 5)
        pos = 0.0
        while pos < total - 6:
            i = int(np.searchsorted(cum, pos))
            x, y = pts[min(i, len(pts) - 1)]
            inward = unit(np.array([CX, CY]) - (x, y))
            n = vnoise(self.day.seed + 21, pos / 40.0, 1.5)
            size = 5 + 8 * n + rng.uniform(-1, 1.5)
            if np.min(np.abs(boulders - pos)) < 10:
                size = rng.uniform(13, 17)
            x, y = np.array([x, y]) + inward * rng.uniform(-2.5, 2.5)
            m = self._stone(self.rim, x, y, size, size * rng.uniform(.62, .85), ramp, light=.5)
            if rng.random() < .25:
                ys, xs = np.nonzero(m)
                pick = (rng.random(len(ys)) < .18) & (ys < y)
                self.rim[ys[pick], xs[pick]] = C["265c42"]
            if rng.random() < .45:
                q = np.array([x, y]) + inward * (rng.uniform(.5, .9) * size + 4)
                self._stone(self.rim, q[0], q[1], rng.uniform(2.5, 5.5), rng.uniform(2, 4), ramp, light=.55)
            pos += size * rng.uniform(1.2, 1.6)
        for _ in range(9):                                          # reeds just outside the rim
            t = rng.uniform(0, math.tau)
            bx, by = self.rim_point(t, 1.05)
            if not (4 < bx < CW - 10 and 12 < by < CH - 2):
                continue
            for j in range(4):
                ang = -math.pi / 2 + rng.uniform(-.6, .6)
                ln = rng.uniform(5, 10)
                line(self.rim, (bx + j * 2 - 3, by), (bx + j * 2 - 3 + ln * math.cos(ang), by + ln * math.sin(ang)),
                     C["3e8948"] if j % 2 else C["265c42"])

    def _submerged(self, cx, cy):
        """A sunken rock, drawn as a dithered silhouette: it reads as under water."""
        m = poly_mask([(cx + 20 * math.cos(a) * (1 + .1 * math.sin(3 * a)), cy + 13 * math.sin(a))
                       for a in np.linspace(0, math.tau, 14)])
        yy, xx = np.nonzero(m)
        keep = (yy + xx) % 2 == 0
        self.under[yy[keep], xx[keep]] = C["262b44"]

    def floor_layer(self):
        return self.under.copy()

    def surface(self, img, f, rec):
        d = self.day
        tc = 2 * math.pi * f / F
        events = [(te, rec[te]["mouth"]) for te in d.eats] + self.drips
        events += [(d.chase.hide + 3, d.chase.pad), (d.chase.snap, rec[d.chase.snap]["mouth"])]
        if d.bug is not None:
            bp = rec[d.bug]["mouth"]
            events += [(t0 % F, bp) for t0 in range(d.bug - 60, d.bug, 15)] + [(d.bug, bp)]
        if d.slap is not None:
            events.append((d.slap, (rec[d.slap]["tails"][0][-1] + rec[d.slap]["tails"][1][-1]) / 2))
        if d.event == "hook":
            events += [(t0, self.hook.copy()) for t0 in (0, 80)]
        for t0, p in events:
            age = (f - t0) % F
            if age < 24:
                for k, off in enumerate((0, 7)):
                    r = 3 + (age - off) * 1.2
                    if r > 2:
                        ring(img, p, r, C["3a4466"] if r > 14 else C["5a6988"], density=1 - age / 28, seed=t0 + k)

        if d.season == "winter":
            ys, xs = np.nonzero(self.ice)
            img[ys, xs] = shade(.35 + .5 * vnoise(d.seed + 9, xs / 5.0, ys / 5.0), R("5a6988", "8b9bb4", "c0cbdc"), ys, xs, .9)
            img[dilate(~self.ice) & self.ice & ~dilate(self.rim >= 0)] = C["5a6988"]

        pad_ramp = R("193c3e", "265c42", "3e8948")
        for i, (cx, cy, r, a0) in enumerate(self.pads):
            if self.ice[int(cy), int(cx)]:
                continue
            a = a0 + .1 * math.sin(tc + i)
            if i == 0:                                           # the hiding pad shakes
                for t0, amp in ((d.chase.hide + 3, .25), (d.chase.snap, .45)):
                    age = (f - t0) % F
                    if age < 18:
                        a += amp * math.exp(-age / 5) * math.sin(age * 1.9)
            pts = [(cx, cy)] + [(cx + r * math.cos(a + .4 + (2 * math.pi - .8) * k / 24),
                                 cy + r * math.sin(a + .4 + (2 * math.pi - .8) * k / 24)) for k in range(25)]
            m = poly_mask(pts)
            ys, xs = np.nonzero(m)
            rr = np.hypot(xs - cx, ys - cy) / r
            img[ys, xs] = shade(.9 - .5 * rr - .25 * ((xs - cx) + (ys - cy)) / (2 * r), pad_ramp, ys, xs, .6)
            for k in range(6):
                ang = a + .4 + (2 * math.pi - .8) * (k + .5) / 6
                line(img, (cx, cy), (cx + r * .75 * math.cos(ang), cy + r * .75 * math.sin(ang)), C["193c3e"])
            img[dilate(m) & ~m] = OUTLINE

        if d.season in ("spring", "summer"):                     # one small flower on the big pad
            cx, cy = self.pads[0][0] + 3, self.pads[0][1] + 2
            fm = np.zeros((CH, CW), bool)
            for k in range(6):
                ang = 2 * math.pi * k / 6 + .15 * math.sin(tc)
                tip = (cx + 7 * math.cos(ang), cy + 7 * math.sin(ang))
                pts = [(cx, cy), (cx + 3 * math.cos(ang - .55), cy + 3 * math.sin(ang - .55)), tip,
                       (cx + 3 * math.cos(ang + .55), cy + 3 * math.sin(ang + .55))]
                m = poly_mask(pts)
                ys, xs = np.nonzero(m)
                img[ys, xs] = shade(.95 - .6 * np.hypot(xs - cx, ys - cy) / 7, LOTUS, ys, xs, .6)
                fm |= m
            img[dilate(fm) & ~fm] = OUTLINE
            img[int(cy), int(cx)] = C["fee761"]

        if d.season == "autumn":                                  # a few fallen leaves, turning slowly
            for x0, y0, rad, ph, dirn, kind in self.leaves:
                ang = ph + dirn * tc
                p = np.array([x0 + rad * math.cos(ang), y0 + rad * math.sin(ang)])
                u = np.array([math.cos(ang * .5 + ph), math.sin(ang * .5 + ph)])
                pts = [p + u * 7] + [p + u * 7 * math.cos(t) + perp(u) * 3.4 * math.sin(t) for t in np.linspace(.3, 2.8, 6)] \
                      + [p - u * 7] + [p + u * 7 * math.cos(t) - perp(u) * 3.4 * math.sin(t) for t in np.linspace(2.8, .3, 6)]
                m = poly_mask(pts)
                ys, xs = np.nonzero(m)
                ramp = [R("733e39", "be4a2f"), R("733e39", "c28569"), R("3e2731", "733e39")][kind]
                img[ys, xs] = shade(.6 - .3 * ((xs - p[0]) * u[0] + (ys - p[1]) * u[1]) / 7, ramp, ys, xs, .8)
                img[dilate(m) & ~m] = OUTLINE
                line(img, p - u * 6, p + u * 6, C["3e2731"])
                line(img, p - u * 7, p - u * 10, C["3e2731"])

        if d.season == "spring":
            for x0, y0, rad, ph, dirn, kind in self.leaves * 2:
                ang = ph + kind + dirn * tc
                x, y = int(x0 + rad * 3 * math.cos(ang)), int(y0 + rad * 2 * math.sin(ang))
                img[y, x] = C["f6757a"]
                img[y, x + 1] = C["e8b796"]

        if d.season == "winter":
            for x0, y0, ph in self.flakes:
                y = (y0 + CH * f / F) % (CH + 6) - 3
                xi, yi = int(x0 + 4 * math.sin(tc * 2 + ph)) % CW, int(y)
                if 0 <= yi < CH:
                    img[yi, xi] = C["c0cbdc"]

        if d.season == "summer":                                  # a dragonfly skimming the water
            p = np.array([CX + 300 * math.sin(tc * 2 + .6), CY - 96 + 12 * math.sin(tc * 3)])
            v = unit(np.array([600 * math.cos(tc * 2 + .6), 36 * math.cos(tc * 3)]))
            for k in range(7):
                q = p - v * k
                img[int(q[1]), int(q[0])] = C["0099db"] if k else C["124e89"]
            up = f % 2 == 0
            for side in (-1, 1):
                for off in (1.5, 3.5):
                    base = p - v * off
                    line(img, base, base + perp(v) * side * 6 + v * (1.5 if up else -1.5), C["8b9bb4"])

        if d.bug is not None:                                    # a beetle struggling on the surface
            age = (d.bug - f) % F
            bp = rec[d.bug]["mouth"]
            if 0 < age <= 60:
                jx, jy = int(bp[0]) + (f % 3 == 0), int(bp[1]) + (f % 4 == 1)
                m = np.zeros((CH, CW), bool)
                body = [(dx, dy) for dx in range(-1, 2) for dy in range(0, 4)] + [(0, -1)]
                for dx, dy in body:
                    m[jy + dy, jx + dx] = True
                flap = 2 if f % 2 else -2
                wings = [((jx - 1, jy + 1), (jx - 6, jy + 1 + flap)), ((jx + 1, jy + 1), (jx + 6, jy + 1 - flap)),
                         ((jx - 1, jy + 3), (jx - 5, jy + 5 - flap)), ((jx + 1, jy + 3), (jx + 5, jy + 5 + flap))]
                for a, b in wings:
                    line(img, a, b, C["c0cbdc"], m)
                img[dilate(m) & ~m] = OUTLINE
                for a, b in wings:
                    line(img, a, b, C["c0cbdc"])
                for dx, dy in body:
                    img[jy + dy, jx + dx] = C["3e2731"] if dy < 0 else (C["c28569"] if dx == -1 and dy == 1 else C["733e39"])
        for t0, p in ((d.bug, rec[d.bug]["mouth"]) if d.bug is not None else (None, None),
                      (d.slap, (rec[d.slap]["tails"][0][-1] + rec[d.slap]["tails"][1][-1]) / 2) if d.slap is not None else (None, None)):
            if t0 is None:
                continue
            age = (f - t0) % F
            if age < 6:                                          # splash droplets
                for a in range(0, 360, 30):
                    r = 9 + age * 4
                    x = int(p[0] + r * math.cos(math.radians(a + t0 * 7)))
                    y = int(p[1] + r * .7 * math.sin(math.radians(a + t0 * 7)))
                    col = C["ffffff"] if age < 3 else C["8b9bb4"]
                    for dx, dy in ((0, 0), (1, 0), (0, 1)) if age < 3 else ((0, 0),):
                        if 0 <= x + dx < CW and 0 <= y + dy < CH:
                            img[y + dy, x + dx] = col

        if d.event == "hook":
            hx = self.hook[0] + 2 * math.sin(tc)
            hy = self.hook[1] + 2 * math.sin(tc * 2)
            m = np.zeros((CH, CW), bool)
            for dx, dy, c in ((-1, -1, "e43b44"), (0, -1, "e43b44"), (1, -1, "e43b44"),
                              (-1, 0, "c0cbdc"), (0, 0, "c0cbdc"), (1, 0, "c0cbdc"), (0, -2, "e43b44")):
                img[int(hy) + dy, int(hx) + dx] = C[c]
                m[int(hy) + dy, int(hx) + dx] = True
            img[dilate(m) & ~m] = OUTLINE
            line(img, (hx, hy - 3), (hx + 60, hy - 120), C["5a6988"])     # the line, leaving the frame

        img[self.rim >= 0] = self.rim[self.rim >= 0]

    def sky(self, img, f):
        """Above the water: the heron's shadow sweeping across."""
        if self.day.event != "heron":
            return
        c = heron_at(f)
        if c is None:
            return
        w = 100 - 22 * (1 + math.sin(f * .45))
        shape = [(80, 0), (63, -3), (57, -6), (49, -4), (32, -4), (16, -8),
                 (6, -w * .45), (-4, -w), (-16, -w * .95), (-26, -w * .55), (-30, -8),
                 (-46, -5), (-60, -2), (-90, -1), (-90, 2), (-60, 2), (-46, 5),
                 (-30, 8), (-26, w * .55), (-16, w * .95), (-4, w), (6, w * .45), (16, 8),
                 (32, 4), (49, 4), (57, 6), (63, 3)]
        u = np.array([1.0, .5]) / math.hypot(1, .5)
        m = poly_mask([c + u * x * 1.1 + perp(u) * y * 1.1 for x, y in shape])
        yy, xx = np.nonzero(m)
        keep = (yy + xx) % 2 == 0
        img[yy[keep], xx[keep]] = C["262b44"]


# ------------------------------------------------------------- pixel text --

GLYPHS = {
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
    "M": "101111111101101", "N": "110101101101101", "O": "010101101101010", "P": "110101110100100",
    "Q": "010101101110011", "R": "110101110101101", "S": "011100010001110", "T": "111010010010010",
    "U": "101101101101111", "V": "101101101101010", "W": "101101111111101", "X": "101101010101101",
    "Y": "101101010010010", "Z": "111001010100111", "0": "111101101101111", "1": "010110010010111",
    "2": "110001010100111", "3": "110001010001110", "4": "101101111001001", "5": "111100110001110",
    "6": "011100111101111", "7": "111001010010010", "8": "111101111101111", "9": "111101111001110",
    "-": "000000111000000", "!": "010010010000010", " ": "000000000000000",
}


def text(img, s, x, y, color, scale=1):
    for ch in s:
        for i, bit in enumerate(GLYPHS.get(ch, GLYPHS[" "])):
            if bit == "1":
                r, c = divmod(i, 3)
                img[y + r * scale:y + (r + 1) * scale, x + c * scale:x + (c + 1) * scale] = color
        x += 4 * scale


# ------------------------------------------------------------------ build --

def draw_fry(img, fr, f, ramp=None):
    fmask, tm, paint = np.zeros((CH, CW), bool), np.zeros((CH, CW), bool), []
    for k, (p, v) in enumerate(zip(fr["fry"], fr["fvel"])):
        if fr["hidden"][k]:
            continue
        d = unit(v) if np.linalg.norm(v) > .2 else np.array([1.0, 0])
        n = perp(d)
        wag = math.sin(f * 1.1 + k * 1.7)
        root = p - d * 10 + n * wag * 1.5
        ys, xs, u, sv = tube([p + d * 3, p - d * 4, root], lambda u: 3.3 - 2.0 * u)
        L = .45 + .55 * np.sqrt(np.clip(1 - sv * sv, 0, 1)) - .2 * sv
        near = np.linalg.norm(p - fr["mouth"]) < 120
        r = ramp or (R("5a6988", "8b9bb4", "c0cbdc", "ffffff") if np.linalg.norm(v) > 3.4 and near   # panic flash
                     else R("3a4466", "5a6988", "8b9bb4", "c0cbdc"))
        col = shade(L, r, ys, xs)
        tail = [root - d * 4 + n * (3.5 + wag), root - d * 4 - n * (3.5 - wag)]
        paint.append((ys, xs, col, p + d * 2 + n * 1.4, tail, root))
        fmask[ys, xs] = True
    for ys, xs, col, eye, tail, root in paint:
        for tp in tail:
            line(img, root, tp, C["5a6988"], tm)
    allm = fmask | tm
    img[dilate(allm) & ~allm] = OUTLINE
    for ys, xs, col, eye, tail, root in paint:
        img[ys, xs] = col
        ex, ey = int(round(eye[0])), int(round(eye[1]))
        if 0 <= ex < CW and 0 <= ey < CH:
            img[ey, ex] = OUTLINE


def draw_bubbles(img, f, bubbles):
    for b in bubbles:
        age = (f - b["t"]) % F
        if age >= b["life"]:
            continue
        p = b["p"] + b["v"] * age + perp(unit(b["v"])) * math.sin(age * .5 + b["ph"]) * 1.2
        x, y = int(round(p[0])), int(round(p[1]))
        if age >= b["life"] - 2:
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                if 0 <= x + dx < CW and 0 <= y + dy < CH:
                    img[y + dy, x + dx] = C["c0cbdc"]
            continue
        r = b["r"]
        for dy in range(-r - 1, r + 2):
            for dx in range(-r - 1, r + 2):
                if 0 <= x + dx < CW and 0 <= y + dy < CH and r - .5 <= math.hypot(dx, dy) <= r + .5:
                    img[y + dy, x + dx] = C["c0cbdc"]
        if 0 <= x - 1 < CW and 0 <= y - 1 < CH:
            img[y - 1, x - 1] = C["ffffff"]


def build(day, out=OUT):
    rec = simulate(day)
    pond = Pond(day)
    rng = np.random.default_rng(day.seed + 3)
    bubbles = []
    for te in day.eats:
        fwd = unit(rec[te]["body"][0] - rec[te]["body"][1])
        for i in range(7 if te in day.catches else 3):
            bubbles.append(dict(t=te + i % 3, p=rec[te]["mouth"] + rng.normal(0, 2, 2),
                                v=rot(fwd, rng.uniform(-1.4, 1.4)) * rng.uniform(.5, 1.2),
                                r=int(rng.integers(1, 3)), life=int(rng.integers(12, 22)), ph=rng.uniform(0, 6)))
    for t0 in range(5, F, 17):
        b = rec[t0]["body"]
        side = perp(unit(b[0] - b[1])) * (1 if t0 % 2 else -1)
        bubbles.append(dict(t=t0, p=b[3] + side * 12 * day.S, v=side * .45, r=1, life=20, ph=rng.uniform(0, 6)))
    ch = day.chase
    fwd = unit(rec[ch.snap]["body"][0] - rec[ch.snap]["body"][1])
    for i in range(4):
        bubbles.append(dict(t=ch.snap + i % 2, p=rec[ch.snap]["mouth"] + rng.normal(0, 2, 2),
                            v=rot(fwd, rng.uniform(-1.2, 1.2)) * rng.uniform(.4, .9),
                            r=1, life=int(rng.integers(10, 16)), ph=rng.uniform(0, 6)))
    if day.bug is not None:
        fwd = unit(rec[day.bug]["body"][0] - rec[day.bug]["body"][1])
        for i in range(4):
            bubbles.append(dict(t=day.bug + i % 2, p=rec[day.bug]["mouth"] + rng.normal(0, 2, 2),
                                v=rot(fwd, rng.uniform(-1.3, 1.3)) * rng.uniform(.4, .9),
                                r=1, life=int(rng.integers(10, 16)), ph=rng.uniform(0, 6)))
    speeds = [np.linalg.norm(rec[(f + 1) % F]["body"][0] - rec[f - 1]["body"][0]) / 2 for f in range(F)]
    wake_from = float(np.percentile(speeds, 62))
    glints = [(rng.uniform(.2, .85), rng.uniform(-.8, .8), rng.uniform(0, 6))
              for _ in range(40 if day.event == "golden" else 16)]
    label = day.label()
    sdx, sdy = int(round(6 * day.S)), int(round(9 * day.S))

    frames = []
    pal = sum(PAL, ()) + (0, 0, 0) * (256 - len(PAL) - 1) + (255, 0, 255)
    for f, fr in enumerate(rec):
        img = pond.floor_layer()
        fimg, fmask = draw_fish(fr, f, day, glints)
        sh = np.zeros_like(fmask)                       # the fish's shadow on the floor
        sh[sdy:, sdx:] = fmask[:-sdy, :-sdx]
        yy, xx = np.nonzero(sh & ~fmask)
        keep = (yy + xx) % 2 == 0
        img[yy[keep], xx[keep]] = C["262b44"]
        # wake: a V of ripples behind the head while it dashes
        h0, h1 = rec[(f - 1) % F]["body"][0], rec[(f + 1) % F]["body"][0]
        speed = np.linalg.norm(h1 - h0) / 2
        if speed > wake_from:
            fwd = unit(fr["body"][0] - fr["body"][1])
            for side in (-1, 1):
                dirv = rot(-fwd, side * .42)
                for k in range(3, 22):
                    if (k + f) % 3 == 0:
                        q = fr["body"][0] + fwd * 6 + dirv * k * 2.2
                        x, y = int(q[0]), int(q[1])
                        if 0 <= x < CW and 0 <= y < CH and img[y, x] < 0:
                            img[y, x] = C["3a4466"] if k < 14 else C["262b44"]
        draw_fry(img, fr, f)
        ch = day.chase
        draw_fry(img, dict(fry=ch.pos[f:f + 1], fvel=ch.vel[f:f + 1], hidden=ch.hidden[f:f + 1],
                           mouth=np.array([-999.0, -999.0])), f,
                 ramp=R("3a4466", "733e39", "c28569", "e8b796"))
        draw_bubbles(img, f, bubbles)
        img[fmask] = fimg[fmask]
        fwd = unit(fr["body"][0] - fr["body"][1])
        for te in day.eats:                              # strike flash
            if 0 <= f - te < 3 and te in day.catches:
                m = fr["mouth"] + fwd * 4
                r0, r1 = 5 + (f - te) * 3, 9 + (f - te) * 4
                for a in range(0, 360, 45):
                    dv = rot(fwd, math.radians(a))
                    line(img, m + dv * r0, m + dv * r1, C["ffffff"] if a % 90 == 0 else C["fee761"])
        pond.surface(img, f, rec)
        if ch.alert[f]:                                          # "!"
            x, y = int(ch.pos[f][0]), int(ch.pos[f][1]) - 14
            hop = 1 if (f - ch.notice) % 4 < 2 else 0
            px = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 5)]
            m = np.zeros((CH, CW), bool)
            for dx, dy in px:
                for ox in (0, 1):
                    if 0 <= y + dy - hop < CH and 0 <= x + dx + ox < CW:
                        m[y + dy - hop, x + dx + ox] = True
            img[dilate(m) & ~m] = OUTLINE
            img[m] = C["fee761"]
        pond.sky(img, f)
        im = Image.fromarray(np.where(img < 0, 255, img).astype(np.uint8), "P")
        im.putpalette(pal)
        frames.append(im)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0,
                   transparency=255, disposal=2, optimize=False)


# ----------------------------------------------------------------- driver --

def calendar(user, token):
    """{date: contributions} for the past year, from the GraphQL API."""
    q = {"query": "query($u:String!){user(login:$u){contributionsCollection{contributionCalendar"
                  "{weeks{contributionDays{date contributionCount}}}}}}", "variables": {"u": user}}
    req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps(q).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        weeks = json.load(r)["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}


def pushes_on(user, token, day):
    req = urllib.request.Request(f"https://api.github.com/users/{user}/events/public?per_page=100",
                                 headers={"Accept": "application/vnd.github+json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        events = json.load(r)
    return sum(1 for e in events if e.get("type") == "PushEvent" and e.get("created_at", "")[:10] == day.isoformat())


def activity(today):
    """(streak ending yesterday, contributions yesterday)."""
    yday = today - dt.timedelta(days=1)
    user, token = os.environ.get("GH_USER", ""), os.environ.get("GH_TOKEN", "")
    try:
        cal = calendar(user, token)
        streak, d = 0, yday
        while cal.get(d.isoformat(), 0) > 0:
            streak += 1
            d -= dt.timedelta(days=1)
        return streak, cal.get(yday.isoformat(), 0)
    except Exception as e:
        print(f"calendar unavailable ({e}); falling back to public push events", file=sys.stderr)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    try:
        contrib = pushes_on(user, token, yday)
    except Exception as e:
        print(f"events unavailable ({e})", file=sys.stderr)
        contrib = state.get("contrib", 1)
    streak = state.get("streak", 0)
    if state.get("date") != today.isoformat():
        streak = streak + 1 if contrib > 0 else 0
    STATE.write_text(json.dumps({"date": today.isoformat(), "streak": streak, "contrib": contrib}) + "\n")
    return streak, contrib


def main():
    today = (dt.date.fromisoformat(os.environ["DATE"]) if "DATE" in os.environ
             else dt.datetime.now(dt.timezone.utc).date())
    if "STREAK" in os.environ or "CONTRIB" in os.environ:
        streak, contrib = int(os.environ.get("STREAK", 7)), int(os.environ.get("CONTRIB", 3))
    else:
        streak, contrib = activity(today)
    day = Day(today, streak, contrib, os.environ.get("EVENT"))
    build(day)
    print(f"{today}: {day.label().lower()} ({day.season}, {day.route}, {day.pattern}, {F} frames"
          f"{', beetle' if day.bug is not None else ''}{', tail slap' if day.slap is not None else ''}) -> {OUT}")


if __name__ == "__main__":
    main()
