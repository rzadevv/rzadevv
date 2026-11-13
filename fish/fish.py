#!/usr/bin/env python3
"""A wild pixel-art fish for a GitHub profile README, in the style of git-koi.

A tiger-striped predator with a glowing dorsal line patrols the pond in a
figure eight, dashes through a school of fry, and gulps one on each pass. The
rest of the school scatters and regroups. Every day the Action redraws it:
the colour morph and stripe pattern change with the date, and the school has
one fry per push you made the day before (at least 4, at most 14).

    python3 fish/fish.py              # fetch activity, draw fish/fish.gif
    PUSHES=7 python3 fish/fish.py     # skip the fetch (local testing)
    SEED=2026-11-13 python3 fish/fish.py

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
from PIL import Image

OUT = Path(__file__).resolve().parent / "fish.gif"

CW, CH = 512, 288            # canvas, pixels
F = 120                      # frames per loop
FRAME_MS = 70
SUB = 4                      # physics substeps per frame
CX, CY, AX, AY = 256, 146, 160, 74   # figure-eight patrol

# Endesga 32, the palette git-koi uses
HEX = """181425 262b44 3a4466 5a6988 8b9bb4 c0cbdc ffffff 124e89 0099db 2ce8f5
3e2731 a22633 e43b44 f6757a be4a2f f77622 feae34 fee761 733e39
193c3e 265c42 3e8948 63c74d""".split()
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
    "jade dragon": dict(base=R("193c3e", "265c42", "3e8948", "63c74d"),
                        stripe=R("181425", "262b44", "193c3e"),
                        crown=R("be4a2f", "feae34", "fee761"),
                        line=R("0099db", "2ce8f5", "ffffff"),
                        tip=R("feae34", "fee761", "ffffff")),
}
FIN = R("3a4466", "5a6988", "8b9bb4", "c0cbdc", "ffffff")

BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + .5) / 16


def shade(L, ramp, ys, xs, spread=.42):
    v = np.clip(L, 0, 1) * (len(ramp) - 1) + (BAYER[ys % 4, xs % 4] - .5) * spread
    idx = np.clip(np.rint(v), 0, len(ramp) - 1).astype(int)
    return np.asarray(ramp)[idx]


def vnoise(rng_seed, u, v):
    """Smooth value noise on (u, v), deterministic per seed."""
    g = np.random.default_rng(rng_seed).random((64, 64))
    u, v = u % 63, v % 63
    i, j = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - i, v - j
    fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
    a, b = g[i, j], g[i + 1, j]
    c, d = g[i, j + 1], g[i + 1, j + 1]
    return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + d * fu) * fv


# ------------------------------------------------------------------ motion --

def head_at(t):
    u = (t - F / 4) / F
    th = 2 * math.pi * u + .32 * math.sin(4 * math.pi * u)        # dash through the middle
    return np.array([CX + AX * math.sin(th), CY + AY * math.sin(2 * th)])


def head_pos(t):
    """Patrol path plus a tail-beat wiggle that grows with speed."""
    p = head_at(t)
    d = head_at(t + .5) - head_at(t - .5)
    sp = np.linalg.norm(d) + 1e-9
    n = np.array([-d[1], d[0]]) / sp
    amp = 1.2 + .55 * sp
    return p + n * amp * math.sin(2 * math.pi * 18 * t / F)


def follow(pts, head, seg):
    pts[0] = head
    for i in range(1, len(pts)):
        d = pts[i] - pts[i - 1]
        pts[i] = pts[i - 1] + d / (np.linalg.norm(d) + 1e-9) * seg


def follow_biased(pts, base, seg, bias_dir, k):
    pts[0] = base
    for i in range(1, len(pts)):
        d = pts[i] - pts[i - 1]
        d = d / (np.linalg.norm(d) + 1e-9)
        d = d * (1 - k) + bias_dir * k
        pts[i] = pts[i - 1] + d / (np.linalg.norm(d) + 1e-9) * seg


def rot(v, a):
    c, s = math.cos(a), math.sin(a)
    return np.array([v[0] * c - v[1] * s, v[0] * s + v[1] * c])


def perp(v):
    return np.array([-v[1], v[0]])


def unit(v):
    return v / (np.linalg.norm(v) + 1e-9)


N, SEG = 26, 6.0
EATS = (F // 4, 3 * F // 4)


def simulate(n_fry, seed):
    rng = np.random.default_rng(seed)
    body = np.array([head_at(0) - [i * SEG, 0] for i in range(N)], float)
    tails = [np.repeat(body[-1:], 12, 0).astype(float) for _ in range(2)]
    whisk = [np.repeat(body[:1], n, 0).astype(float) for n in (13, 13, 7, 7)]
    slots = [(rng.uniform(8, 40), rng.uniform(0, math.tau), int(rng.choice([-2, -1, 1, 2])),
              rng.uniform(.5, .8)) for _ in range(n_fry)]
    fry = np.array([[CX, CY]] * n_fry, float) + rng.normal(0, 10, (n_fry, 2))
    vel = np.zeros_like(fry)
    eaten = {}                       # eat frame -> fry index (fixed after the first loop)
    hidden = np.zeros(n_fry, bool)
    rec = []

    def school_target(k, t):
        r, ph, m, sq = slots[k]
        a = ph + 2 * math.pi * m * t / F
        c = np.array([CX + 22 * math.sin(2 * math.pi * t / F), CY + 14 * math.sin(4 * math.pi * t / F + 1)])
        return c + r * np.array([math.cos(a), math.sin(a) * sq])

    loops = 4
    for f_abs in range(loops * F):
        f = f_abs % F
        for s in range(SUB):
            t = f + s / SUB
            follow(body, head_pos(t), SEG)
            axis = unit(body[-1] - body[-2])
            for side, tl in zip((-1, 1), tails):
                follow_biased(tl, body[-2] * .3 + body[-1] * .7, 4.1, unit(axis + side * 1.0 * perp(axis)), .2)
            fwd = unit(body[0] - body[1])
            for i, w in enumerate(whisk):
                side = -1 if i % 2 == 0 else 1
                base = body[0] + fwd * (8 if i < 2 else 5) + perp(fwd) * side * (5 if i < 2 else 8)
                follow_biased(w, base, 3.4, unit(-.45 * fwd + side * perp(fwd)), .2)
            mouth = body[0] + fwd * 7
            # the school
            for k in range(n_fry):
                if hidden[k]:
                    continue
                acc = .02 * (school_target(k, t) - fry[k]) - .11 * vel[k]
                d = fry[k] - mouth
                dist = np.linalg.norm(d) + 1e-9
                if dist < 95:
                    acc += d / dist * 1.7 * (1 - dist / 95) ** 2
                vel[k] += acc / SUB * 4
                sp = np.linalg.norm(vel[k])
                if sp > 4.2:
                    vel[k] *= 4.2 / sp
                fry[k] += vel[k] / SUB
        mouth = body[0] + unit(body[0] - body[1]) * 7
        # eating: choose victims on the first loop, then keep them fixed
        for te in EATS:
            if f == te - 6 and te not in eaten:
                taken = set(eaten.values())
                order = np.argsort(np.linalg.norm(fry - mouth, axis=1))
                eaten[te] = int(next(i for i in order if i not in taken))
            if te in eaten:
                k = eaten[te]
                if te - 6 <= f < te:
                    fry[k] += (mouth - fry[k]) * .45            # sucked in
                    vel[k] *= 0
                if f == te:
                    hidden[k] = True
                if f == (te + 16) % F:                          # a new one swims in from the edge
                    hidden[k] = False
                    fry[k] = np.array([CX + (CW / 2 + 12) * (1 if mouth[0] < CX else -1), CY + rng.uniform(-60, 60)])
                    vel[k] = unit(np.array([CX, CY]) - fry[k]) * 3.5
        if f_abs >= (loops - 1) * F:
            rec.append(dict(body=body.copy(), tails=[t.copy() for t in tails], whisk=[w.copy() for w in whisk],
                            fry=fry.copy(), fvel=vel.copy(), hidden=hidden.copy(), mouth=mouth.copy()))
    return rec


# --------------------------------------------------------------- drawing --

def resample(pts, step=1.25):
    seglen = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seglen)])
    n = max(2, int(s[-1] / step))
    q = np.linspace(0, s[-1], n)
    return np.stack([np.interp(q, s, pts[:, 0]), np.interp(q, s, pts[:, 1])], 1)


def tube(pts, radius_fn):
    """Rasterise a tapered tube along pts. Returns (ys, xs, u, s) for covered pixels."""
    sp = resample(pts)
    u_pts = np.linspace(0, 1, len(sp))
    r = radius_fn(u_pts)
    x0, y0 = int(np.floor((sp[:, 0] - r).min())) - 1, int(np.floor((sp[:, 1] - r).min())) - 1
    x1, y1 = int(np.ceil((sp[:, 0] + r).max())) + 2, int(np.ceil((sp[:, 1] + r).max())) + 2
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, CW), min(y1, CH)
    if x1 <= x0 or y1 <= y0:
        return (np.array([], int),) * 2 + (np.array([]),) * 2
    ys, xs = np.mgrid[y0:y1, x0:x1]
    px, py = xs.ravel() + .5, ys.ravel() + .5
    dx = px[:, None] - sp[None, :, 0]
    dy = py[:, None] - sp[None, :, 1]
    d = np.sqrt(dx * dx + dy * dy)
    score = d - r[None, :]
    j = score.argmin(1)
    inside = score[np.arange(len(j)), j] <= 0
    j = j[inside]
    tang = np.gradient(sp, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
    cross = tang[j, 0] * dy[inside, j] - tang[j, 1] * dx[inside, j]
    s = np.clip(cross / np.maximum(r[j], .5), -1, 1)
    return ys.ravel()[inside], xs.ravel()[inside], u_pts[j], s


def body_radius(u):
    w = np.where(u < .2, .62 + .38 * np.sqrt(np.clip(u / .2, 0, 1)), 1.0)
    w = np.where(u > .42, 1 - .8 * np.clip((u - .42) / .58, 0, 1) ** 1.25, w)
    return 13.0 * w


def line(img, a, b, color):
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    for i in range(n + 1):
        x = int(round(a[0] + (b[0] - a[0]) * i / n))
        y = int(round(a[1] + (b[1] - a[1]) * i / n))
        if 0 <= x < CW and 0 <= y < CH:
            img[y, x] = color


def dilate(m):
    o = m.copy()
    o[1:] |= m[:-1]; o[:-1] |= m[1:]; o[:, 1:] |= m[:, :-1]; o[:, :-1] |= m[:, 1:]
    return o


def draw_frame(fr, f, morph, seed, bubbles, glints):
    img = np.full((CH, CW), -1, int)
    body, tails, whisk = fr["body"], fr["tails"], fr["whisk"]

    # ---- fry (under the fish, own outline)
    fmask = np.zeros((CH, CW), bool)
    fry_paint = []
    for k, (p, v) in enumerate(zip(fr["fry"], fr["fvel"])):
        if fr["hidden"][k]:
            continue
        d = unit(v) if np.linalg.norm(v) > .2 else np.array([1.0, 0])
        n = perp(d)
        wag = math.sin(f * 1.1 + k * 1.7)
        pts = np.array([p + d * 2, p - d * 3, p - d * 7 + n * wag * 1.2])
        ys, xs, u, sv = tube(pts, lambda u: 2.6 - 1.6 * u)
        L = .45 + .55 * np.sqrt(np.clip(1 - sv * sv, 0, 1)) - .2 * sv
        col = shade(L, R("5a6988", "8b9bb4", "c0cbdc", "ffffff"), ys, xs)
        tail = [p - d * 9 + n * (2.5 + wag), p - d * 9 - n * (2.5 - wag)]
        fry_paint.append((ys, xs, col, p + d * 1.5 + n * 1.1, tail, p - d * 7 + n * wag * 1.2))
        fmask[ys, xs] = True
    for ys, xs, col, eye, tail, root in fry_paint:
        for tp in tail:
            line(img, root, tp, C["8b9bb4"])
    tailmask = img >= 0
    img[dilate(fmask | tailmask) & ~(fmask | tailmask)] = OUTLINE
    for ys, xs, col, eye, tail, root in fry_paint:
        img[ys, xs] = col
        ex, ey = int(round(eye[0])), int(round(eye[1]))
        if 0 <= ex < CW and 0 <= ey < CH:
            img[ey, ex] = OUTLINE

    # ---- bubbles
    for b in bubbles:
        age = (f - b["t"]) % F
        if age >= b["life"]:
            continue
        p = b["p"] + b["v"] * age + perp(unit(b["v"])) * math.sin(age * .5 + b["ph"]) * 1.2
        x, y = int(round(p[0])), int(round(p[1]))
        if age >= b["life"] - 2:                                     # pop
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                if 0 <= x + dx < CW and 0 <= y + dy < CH:
                    img[y + dy, x + dx] = C["c0cbdc"]
            continue
        r = b["r"]
        for dy in range(-r - 1, r + 2):
            for dx in range(-r - 1, r + 2):
                dd = math.hypot(dx, dy)
                if 0 <= x + dx < CW and 0 <= y + dy < CH and r - .5 <= dd <= r + .5:
                    img[y + dy, x + dx] = C["c0cbdc"]
        if 0 <= x - 1 < CW and 0 <= y - 1 < CH:
            img[y - 1, x - 1] = C["ffffff"]

    # ---- fish: fins first, then body
    fish = np.zeros((CH, CW), bool)
    fwd = unit(body[0] - body[1])
    t_cyc = 2 * math.pi * f / F

    def paint_fin(pts, rad, phase_tip=.62, rays=True):
        ys, xs, u, s = tube(np.asarray(pts), rad)
        if not len(ys):
            return
        L = .35 + .55 * (1 - np.abs(s)) + .1 * np.sin(u * 9)
        col = shade(L, FIN, ys, xs)
        if rays:
            ray = (np.floor((s + 1) * 2.4 + u * 1.5) % 2 == 0) & (u > .15)
            col = np.where(ray, shade(L - .3, FIN, ys, xs), col)
        tipm = u > phase_tip + .08 * np.sin(s * 5 + f * .2)
        col = np.where(tipm, shade(.4 + .5 * (1 - np.abs(s)), morph["tip"], ys, xs), col)
        img[ys, xs] = col
        fish[ys, xs] = True

    # whiskers (roots tucked under the head)
    for w in whisk:
        for i, (a, b) in enumerate(zip(w, w[1:])):
            q = i / (len(w) - 1)
            line(img, a, b, C["8b9bb4"] if q < .35 else C["5a6988"] if q < .75 else morph["line"][-2])

    # pectoral and pelvic fins, sculling
    for side in (-1, 1):
        for idx, length, spread, rmax, beat in ((4, 30, 1.0, 7.0, 0), (13, 16, .75, 4.2, 1.4)):
            a = body[idx]
            ax = unit(body[idx + 1] - body[idx - 1])
            n = perp(ax)
            ang = side * (0.95 + .35 * math.sin(t_cyc * 7 + beat + (side > 0) * .9)) * spread
            dirv = rot(ax, ang)
            root = a + n * side * body_radius(np.array([idx / (N - 1)]))[0] * .7
            pts = [root + dirv * length * i / 6 + n * side * math.sin(i * .5) * 1.5 for i in range(7)]
            paint_fin(pts, lambda u, rm=rmax: rm * np.sin(np.clip(u, .08, 1) * math.pi) ** .7 + .6)

    # long flowing tail lobes
    for tl in tails:
        paint_fin(tl, lambda u: 1.8 + 9.5 * np.sin(np.clip(u, 0, 1) * math.pi * .8) ** 1.1, phase_tip=.58)

    # body
    ys, xs, u, s = tube(body, body_radius)
    L = .3 + .62 * np.sqrt(np.clip(1 - s * s, 0, 1)) - .2 * s - .12 * np.clip((u - .8) * 5, 0, 1)
    col = shade(L, morph["base"], ys, xs)
    n1 = vnoise(seed, u * 30, s * 3 + 7)
    stripe_v = (u * 10.5 + .55 * np.abs(s) ** 1.3 + .45 * n1) % 1
    stripe = (stripe_v < .34) & (u > .17) & (u < .93) & (np.abs(s) > .12 + .35 * n1)
    col = np.where(stripe, shade(L - .1, morph["stripe"], ys, xs), col)
    crown = (((u - .1) / .055) ** 2 + (s / (.34 - 1.6 * np.clip(.1 - u, -.1, .1))) ** 2
             < 1 + .5 * (vnoise(seed + 1, u * 40, s * 4) - .5))
    col = np.where(crown, shade(L - .12, morph["crown"], ys, xs), col)
    # glowing dorsal line with a pulse running down it
    pulse = sum(np.exp(-((u - ((f / F * 3 + k / 3) % 1) * .62 - .16) / .05) ** 2) for k in range(1))
    dl = (np.abs(s + .06 * np.sin(u * 20 + f * .4)) < .11) & (u > .16) & (u < .8)
    col = np.where(dl, shade(.25 + .75 * pulse, morph["line"], ys, xs, .6), col)
    img[ys, xs] = col
    fish[ys, xs] = True
    # twinkling scales
    for gu, gs, ph in glints:
        if math.sin(t_cyc * 3 + ph) > .9:
            j = int(gu * (N - 1))
            ax = unit(body[j + 1] - body[j - 1]) if 0 < j < N - 1 else fwd
            p = body[j] + perp(ax) * gs * body_radius(np.array([gu]))[0] * -1
            x, y = int(round(p[0])), int(round(p[1]))
            if 0 <= x < CW and 0 <= y < CH and fish[y, x]:
                img[y, x] = C["ffffff"]

    # eyes, red-irised
    for side in (-1, 1):
        p = body[0] - fwd * 3 + perp(fwd) * side * 5.6
        x, y = int(round(p[0])), int(round(p[1]))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if abs(dx) + abs(dy) < 2:
                    img[y + dy, x + dx] = OUTLINE
        img[y, x] = C["e43b44"]
        g = p + fwd * .8 - perp(fwd) * side * .8
        img[int(round(g[1])), int(round(g[0]))] = C["ffffff"]

    # mouth opens just before each strike
    for te in EATS:
        if 0 <= te - f <= 4:
            gape = 1 - (te - f) / 5
            ys, xs, u, s = tube(body[:6], lambda u: body_radius(u * 5 / 25))
            m = (u < .2 * gape + .02) & (np.abs(s) < .55 * gape)
            img[ys[m], xs[m]] = -1
            fish[ys[m], xs[m]] = False
            inner = (u < .2 * gape) & (np.abs(s) < .3 * gape)
            img[ys[inner], xs[inner]] = C["3e2731"]
            fish[ys[inner], xs[inner]] = True

    img[dilate(fish) & ~fish] = OUTLINE

    # snap sparkle on the strike frames
    for te in EATS:
        if 0 <= f - te < 3:
            m = fr["mouth"] + fwd * 4
            r0, r1 = 5 + (f - te) * 3, 9 + (f - te) * 4
            for a in range(0, 360, 45):
                d = rot(fwd, math.radians(a))
                line(img, m + d * r0, m + d * r1, C["ffffff"] if a % 90 == 0 else C["fee761"])
    return img


def build(n_fry, seed_text):
    seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:8], 16)
    morph_name = list(MORPHS)[seed % len(MORPHS)]
    morph = MORPHS[morph_name]
    rec = simulate(n_fry, seed)
    rng = np.random.default_rng(seed + 3)
    bubbles = []
    for te in EATS:                                            # a burst on every gulp
        fwd = unit(rec[te]["body"][0] - rec[te]["body"][1])
        for i in range(7):
            bubbles.append(dict(t=te + i % 3, p=rec[te]["mouth"] + rng.normal(0, 2, 2),
                                v=rot(fwd, rng.uniform(-1.4, 1.4)) * rng.uniform(.5, 1.2),
                                r=int(rng.integers(1, 3)), life=int(rng.integers(12, 22)), ph=rng.uniform(0, 6)))
    for t0 in range(5, F, 17):                                 # the odd breath from the gills
        b = rec[t0]["body"]
        side = perp(unit(b[0] - b[1])) * (1 if t0 % 2 else -1)
        bubbles.append(dict(t=t0, p=b[3] + side * 12, v=side * .45, r=1, life=20, ph=rng.uniform(0, 6)))
    glints = [(rng.uniform(.2, .85), rng.uniform(-.8, .8), rng.uniform(0, 6)) for _ in range(16)]

    frames = []
    pal = sum(PAL, ()) + (0, 0, 0) * (256 - len(PAL) - 1) + (255, 0, 255)
    T = 255
    for f, fr in enumerate(rec):
        img = draw_frame(fr, f, morph, seed, bubbles, glints)
        a = np.where(img < 0, T, img).astype(np.uint8)
        im = Image.fromarray(a, "P")
        im.putpalette(pal)
        frames.append(im)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0,
                   transparency=T, disposal=2, optimize=False)
    return morph_name


# ---------------------------------------------------------------- driver --

def pushes_on(user, token, day):
    req = urllib.request.Request(f"https://api.github.com/users/{user}/events/public?per_page=100",
                                 headers={"Accept": "application/vnd.github+json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        events = json.load(r)
    return sum(1 for e in events if e.get("type") == "PushEvent"
               and e.get("created_at", "")[:10] == day.isoformat())


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    seed_text = os.environ.get("SEED", today.isoformat())
    if "PUSHES" in os.environ:
        pushes = int(os.environ["PUSHES"])
    else:
        try:
            pushes = pushes_on(os.environ.get("GH_USER", ""), os.environ.get("GH_TOKEN"),
                               today - dt.timedelta(days=1))
        except Exception as e:
            print(f"could not fetch activity: {e}", file=sys.stderr)
            pushes = 6
    n_fry = max(4, min(14, pushes))
    morph = build(n_fry, seed_text)
    print(f"{seed_text}: {morph}, {n_fry} fry -> {OUT}")


if __name__ == "__main__":
    main()
