#!/usr/bin/env python3
"""Table tennis against your README.

Visitors open an issue titled "pingpong: <shot>". A GitHub Action runs this
script, which plays one exchange against the bot, updates state.json and
redraws assets/pingpong.svg (an animated SVG that GitHub renders in READMEs).

Usage (what the Action does):
    ISSUE_NUMBER=12 ISSUE_TITLE="pingpong: smash" ISSUE_USER=octocat \
        python3 pingpong/game.py move

Other commands:
    python3 pingpong/game.py render          # redraw the SVG from state.json
    python3 pingpong/game.py render --debug  # also draw the ball path
"""
import json
import math
import os
import random
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "pingpong" / "state.json"
OUT = ROOT / "assets" / "pingpong.svg"

WIN_SCORE = 11
HISTORY = 5

# shot -> (P(your shot lands on the table), P(the bot returns it | it lands))
SHOTS = {
    "loop": (0.88, 0.70),   # safe topspin: rarely misses, bot usually gets it back
    "smash": (0.55, 0.25),  # risky: often out/net, but hard for the bot to return
    "chop": (0.85, 0.65),   # backspin: low and annoying
    "lob": (0.92, 0.65),    # high and slow: nearly always lands
}
# where the ball bounces on the bot's half (x), and how high the arc is (y of control point)
SHAPE = {
    "loop": dict(bounce=410, arc=60),
    "smash": dict(bounce=470, arc=22),
    "chop": dict(bounce=380, arc=42),
    "lob": dict(bounce=440, arc=95),
}

# ---------------------------------------------------------------- state ----

def default_state():
    return {
        "you": 0, "bot": 0,            # current game score
        "games_you": 0, "games_bot": 0,
        "rally": 0, "best_rally": 0,
        "finished": False,             # current game just ended; reset on next move
        "last": None,                  # last exchange, drives the animation
        "history": [],
        "players": {},
    }


def load_state():
    if STATE.exists():
        s = default_state()
        s.update(json.loads(STATE.read_text()))
        return s
    return default_state()


def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2) + "\n")


# ---------------------------------------------------------------- rules ----

def parse_shot(title):
    m = re.match(r"^\s*pingpong\s*:\s*([a-z]+)\s*$", title or "", re.I)
    if not m:
        return None
    shot = m.group(1).lower()
    return shot if shot in SHOTS else None


def play(state, user, shot, seed):
    """Play one exchange. Mutates and returns state. Deterministic per seed."""
    rng = random.Random(seed)
    if state["finished"]:
        state.update(you=0, bot=0, rally=0, finished=False)

    p_in, p_ret = SHOTS[shot]
    if rng.random() > p_in:
        outcome = rng.choice(["net", "out"])
        point = "bot"
    elif rng.random() > p_ret:
        outcome = "winner"
        point = "you"
    else:
        outcome = "returned"
        point = None

    state["rally"] += 1
    state["best_rally"] = max(state["best_rally"], state["rally"])
    note = ""
    if point:
        state[point] += 1
        state["rally"] = 0
        if state[point] >= WIN_SCORE:
            state["games_" + point] += 1
            state["finished"] = True
            note = "game to you!" if point == "you" else "game to the bot!"

    state["players"][user] = state["players"].get(user, 0) + 1
    state["last"] = dict(user=user, shot=shot, outcome=outcome, point=point,
                         note=note, rally=state["rally"])
    state["history"] = (state["history"] + [state["last"]])[-HISTORY:]
    return state


def describe(last):
    shot, out = last["shot"], last["outcome"]
    if out == "net":
        s = f"a {shot} that clipped the net. Point to the bot."
    elif out == "out":
        s = f"a {shot} that flew long. Point to the bot."
    elif out == "winner":
        s = f"a {shot} the bot could not return. Point to you!"
    else:
        s = f"a {shot}, and the bot sent it back. Your turn!"
    return s + (f" {last['note'].capitalize()}" if last.get("note") else "")


# ------------------------------------------------------------- geometry ----
# Side view of the table. Everything is drawn like ink in a notebook: lines
# are jittered with a fixed seed so the picture looks hand-drawn but does not
# change between commits (only the ball, score and text do).

W, H = 640, 376
FLOOR_Y = 300
TABLE_Y = 222                 # table surface
TABLE_X0, TABLE_X1 = 160, 480
NET_X, NET_H = 320, 20
BALL_R = 5
BALL_Y = TABLE_Y - BALL_R
HIT_L = (146, 190)            # your paddle centre
HIT_R = (494, 190)            # the bot's paddle centre

SHAPE.update({
    "loop": dict(bounce=420, arc=58),
    "smash": dict(bounce=458, arc=20),
    "chop": dict(bounce=392, arc=40),
    "lob": dict(bounce=440, arc=96),
})

PAPER = "#f7f2e8"
INK = "#24221f"
RULE = "#bcd0e2"
MARGIN = "#e2a297"
RED = "#d2452f"
YELLOW = "#f2c14e"
FELT = "#3d7a62"
SERIF = "'Iowan Old Style','Palatino Linotype',Palatino,Georgia,serif"


def ctrl(p0, p1, arc_up):
    """Control point so the parabola peaks about `arc_up` px above the chord."""
    return ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2 - 2 * arc_up)


def qpt(seg, t):
    p0, c, p1 = seg
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
            u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])


def build_path(last):
    """Segments of the ball's flight plus the moments that matter.

    Returns (segs, events) where events maps a name to the index of the
    segment boundary at which it happens.
    """
    shot, outcome = last["shot"], last["outcome"]
    sh = SHAPE[shot]
    bounce = (sh["bounce"], BALL_Y)
    segs, ev = [], {}
    if outcome == "net":
        tape = (NET_X - 5, TABLE_Y - NET_H + 2)
        back = (NET_X - 34, BALL_Y)
        roll = (NET_X - 70, BALL_Y)
        segs += [(HIT_L, ctrl(HIT_L, tape, 16), tape),
                 (tape, ctrl(tape, back, 10), back),
                 (back, ctrl(back, roll, 6), roll)]
        ev["mark"] = 1
    elif outcome == "out":
        floor = (612, FLOOR_Y - BALL_R)
        segs.append((HIT_L, ctrl(HIT_L, floor, 128), floor))
        ev["mark"] = 1
    else:
        segs.append((HIT_L, ctrl(HIT_L, bounce, sh["arc"]), bounce))
        if outcome == "winner":
            gone = (652, 252)
            segs.append((bounce, ctrl(bounce, gone, 26), gone))
            ev["bot_miss"] = ev["mark"] = 1
        else:
            back = (TABLE_X0 + 80, BALL_Y)
            segs += [(bounce, ctrl(bounce, HIT_R, 26), HIT_R),
                     (HIT_R, ctrl(HIT_R, back, 78), back),
                     (back, ctrl(back, HIT_L, 42), HIT_L)]
            ev["bot"] = ev["mark"] = 2
    return segs, ev


def sample(segs, n=96):
    """Points spaced evenly by arc length, and where each segment ends (0..1)."""
    fine, ends = [segs[0][0]], []
    for s in segs:
        fine += [qpt(s, i / 40) for i in range(1, 41)]
        ends.append(len(fine) - 1)
    cum = [0.0]
    for a, b in zip(fine, fine[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    total = cum[-1]
    pts, j = [], 0
    for k in range(n):
        target = total * k / (n - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        span = (cum[j + 1] - cum[j]) or 1
        f = (target - cum[j]) / span
        a, b = fine[j], fine[j + 1]
        pts.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return pts, [0.0] + [cum[e] / total for e in ends], total


# ----------------------------------------------------------------- ink ----

class Pen:
    """Wobbly ink lines, deterministic per drawing."""

    def __init__(self, seed="rza"):
        self.rng = random.Random(seed)

    def _wobble(self, pts, amp):
        out = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(d / 16))
            nx, ny = (-(y1 - y0) / d, (x1 - x0) / d) if d else (0, 0)
            for i in range(1, n + 1):
                t = i / n
                j = self.rng.uniform(-amp, amp) if i < n else 0
                out.append((x0 + (x1 - x0) * t + nx * j, y0 + (y1 - y0) * t + ny * j))
        return out

    @staticmethod
    def _d(pts, close=False):
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return d + ("Z" if close else "")

    def line(self, pts, w=1.8, color=INK, fill="none", amp=0.7, close=False, extra=""):
        p1 = self._wobble(pts + ([pts[0]] if close else []), amp)
        p2 = self._wobble([(x + self.rng.uniform(-.6, .6), y + self.rng.uniform(-.6, .6))
                           for x, y in pts] + ([pts[0]] if close else []), amp)
        out = ""
        if fill != "none":
            out += f'<path d="{self._d(p1, True)}" fill="{fill}" stroke="none"/>'
        out += (f'<path d="{self._d(p1)}" fill="none" stroke="{color}" stroke-width="{w}" '
                f'stroke-linecap="round" stroke-linejoin="round"{extra}/>')
        out += (f'<path d="{self._d(p2)}" fill="none" stroke="{color}" stroke-width="{w*.45:.2f}" '
                f'stroke-linecap="round" stroke-linejoin="round" opacity=".55"{extra}/>')
        return out

    def circle(self, cx, cy, r, w=1.8, fill="none", color=INK):
        turns, n = 1.12, 22
        start = self.rng.uniform(0, math.tau)
        pts = []
        for i in range(n + 1):
            a = start + math.tau * turns * i / n
            rr = r + self.rng.uniform(-r * .05, r * .05)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        out = ""
        if fill != "none":
            out += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"/>'
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return out + (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{w}" '
                      f'stroke-linecap="round" stroke-linejoin="round"/>')


DIGITS = {
    "0": [(1, 0), (9, 0), (10, 3), (10, 13), (8, 16), (2, 16), (0, 13), (0, 3), (1, 0)],
    "1": [(2, 4), (6, 0), (6, 16)],
    "2": [(0, 3), (3, 0), (8, 0), (10, 3), (10, 6), (0, 16), (10, 16)],
    "3": [(0, 0), (10, 0), (4, 7), (8, 8), (10, 11), (10, 14), (7, 16), (0, 15)],
    "4": [(8, 16), (8, 0), (0, 11), (10, 11)],
    "5": [(10, 0), (1, 0), (0, 7), (7, 6), (10, 9), (10, 13), (7, 16), (0, 15)],
    "6": [(9, 0), (3, 3), (0, 9), (0, 14), (3, 16), (8, 16), (10, 13), (10, 10), (7, 8), (2, 8), (0, 10)],
    "7": [(0, 0), (10, 0), (3, 16)],
    "8": [(5, 8), (1, 6), (1, 2), (4, 0), (7, 0), (10, 2), (10, 6), (5, 8), (0, 11), (0, 14),
          (3, 16), (7, 16), (10, 14), (10, 11), (5, 8)],
    "9": [(10, 6), (8, 8), (3, 8), (0, 6), (0, 2), (3, 0), (8, 0), (10, 2), (10, 8), (9, 16)],
}


def number(pen, n, x, y, align="left", s=1.9):
    txt = str(n)
    adv = 15 * s
    width = adv * len(txt) - 5 * s
    x0 = x - width if align == "right" else x
    return "".join(pen.line([(x0 + i * adv + px * s, y + py * s) for px, py in DIGITS[ch]], w=3.2, amp=.5)
                   for i, ch in enumerate(txt))


def tally(pen, n, x, y):
    out = ""
    for i in range(n):
        g, k = divmod(i, 5)
        gx = x + g * 30
        if k < 4:
            out += pen.line([(gx + k * 5, y), (gx + k * 5 + 1, y + 13)], w=1.5)
        else:
            out += pen.line([(gx - 3, y + 11), (gx + 19, y + 2)], w=1.5)
    return out


def text(x, y, s, size=14, anchor="middle", color=INK, extra=""):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}" '
            f'font-family="{SERIF}" font-style="italic"{extra}>{s}</text>')


# ------------------------------------------------------------ characters ----

def swing(t, loop, miss=False):
    """Rotate the arm about the shoulder: wind up, hit at fraction t, follow through."""
    if t is None:
        return ""
    k = [0.0, t - .10, t - .03, t, t + .05, t + .14, 1.0]
    k = [min(max(v, 0.0), 1.0) for v in k]
    for i in range(1, len(k)):
        k[i] = max(k[i], k[i - 1] + 0.001)
    k[-1] = 1.0
    k = [min(v, 1.0) for v in k]
    v = [0, 0, 24, 2 if not miss else 14, -40, 0, 0]
    return (f'<animateTransform attributeName="transform" type="rotate" dur="{loop:.2f}s" '
            f'repeatCount="indefinite" keyTimes="{";".join(f"{x:.3f}" for x in k)}" '
            f'values="{";".join(f"{a} 6 -94" for a in v)}"/>')


def arm(pen, rubber, anim):
    return (f'<g>{anim}'
            + pen.line([(6, -94), (21, -88), (33, -101)], w=2)
            + pen.line([(32, -101), (40, -106)], w=4.2, color="#9c6b3c", amp=.2)
            + pen.circle(46, -110, 10.5, w=1.8, fill=rubber)
            + "</g>")


def you(pen, anim):
    o = '<g transform="translate(100,300)">'
    o += pen.line([(0, -58), (-12, -30), (-17, 0), (-25, 0)], w=2)       # legs, knees bent
    o += pen.line([(0, -58), (11, -30), (15, 0), (24, 0)], w=2)
    o += pen.line([(-11, -98), (11, -98), (13, -60), (-13, -60)], w=1.8, fill=YELLOW, close=True)
    o += pen.line([(-8, -96), (-21, -80), (-14, -68)], w=2)               # free arm
    o += pen.circle(0, -113, 13, w=2, fill=PAPER)
    hair = [(13.5 * math.cos(math.radians(a)) + (3 if i % 2 else 0) * math.cos(math.radians(a)),
             -113 + (13.5 + (4.5 if i % 2 else 0)) * math.sin(math.radians(a)))
            for i, a in enumerate(range(195, 352, 13))]
    o += pen.line(hair, w=1.7, amp=.3)                                     # scribbly hair
    o += f'<circle cx="4" cy="-115" r="1.6" fill="{INK}"/><circle cx="9" cy="-115" r="1.6" fill="{INK}"/>'
    o += f'<path d="M2,-108 Q7,-103 11,-109" fill="none" stroke="{INK}" stroke-width="1.5" stroke-linecap="round"/>'
    o += arm(pen, RED, anim)
    return o + "</g>"


def bot(pen, anim, loop):
    o = '<g transform="translate(540,300) scale(-1,1)">'
    o += ('<g><animateTransform attributeName="transform" type="translate" dur="2.4s" '
          'repeatCount="indefinite" values="0 0;0 -1.5;0 0"/>')
    o += pen.line([(-6, -60), (-8, 0), (-16, 0)], w=2)
    o += pen.line([(6, -60), (8, 0), (16, 0)], w=2)
    o += pen.line([(-13, -98), (13, -98), (13, -60), (-13, -60)], w=1.8, fill="#c3ccd2", close=True)
    o += pen.line([(-6, -86), (6, -86)], w=1.2) + pen.line([(-6, -80), (2, -80)], w=1.2)
    o += pen.line([(-8, -96), (-20, -82), (-13, -70)], w=2)
    o += pen.line([(-14, -125), (14, -125), (14, -101), (-14, -101)], w=2, fill="#dfe5e8", close=True)
    o += pen.line([(0, -125), (0, -136)], w=1.6)
    o += (f'<circle cx="0" cy="-138" r="3" fill="{RED}" stroke="{INK}" stroke-width="1.2">'
          '<animate attributeName="opacity" dur="1.6s" repeatCount="indefinite" values="1;.25;1"/></circle>')
    o += f'<rect x="2" y="-117" width="4" height="5" fill="{INK}"/><rect x="8" y="-117" width="4" height="5" fill="{INK}"/>'
    o += pen.line([(3, -107), (12, -107)], w=1.4)
    o += arm(pen, "#2e2b28", anim)
    return o + "</g></g>"


# ------------------------------------------------------------------ svg ----

OUTCOME_NOTE = {"net": "net!", "out": "long…", "winner": "winner!", "returned": "back it comes"}


def render(state, debug=False):
    pen = Pen()
    last = state["last"]
    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    a('<title>Table tennis against the README</title>')

    # paper
    a(f'<rect x="2" y="2" width="{W-4}" height="{H-4}" rx="6" fill="{PAPER}" stroke="#d9d0bf"/>')
    for y in range(58, H - 10, 26):
        a(f'<line x1="2" y1="{y}" x2="{W-2}" y2="{y}" stroke="{RULE}" stroke-width=".8" opacity=".55"/>')
    a(f'<line x1="44" y1="2" x2="44" y2="{H-2}" stroke="{MARGIN}" stroke-width="1" opacity=".8"/>')
    for cx, rot in ((70, -8), (W - 70, 7)):                                     # tape
        a(f'<rect x="{cx-30}" y="-6" width="60" height="20" fill="#efe3b8" opacity=".75" '
          f'transform="rotate({rot} {cx} 4)"/>')

    # score
    a(number(pen, state["you"], 300, 20, align="right"))
    a(pen.line([(318, 32), (318.5, 33)], w=3.4) + pen.line([(318, 44), (318.5, 45)], w=3.4))
    a(number(pen, state["bot"], 338, 20))
    a(text(232, 46, "you", 15, "end", "#6b655b"))
    a(text(406, 46, "bot", 15, "start", "#6b655b"))
    if state["games_you"] or state["games_bot"]:
        a(text(232, 66, "games", 11, "end", "#8a8377"))
        a(tally(pen, state["games_you"], 244, 56) if state["games_you"] else "")
        a(tally(pen, state["games_bot"], 356, 56) if state["games_bot"] else "")

    # floor, table, net
    a(pen.line([(56, FLOOR_Y), (W - 20, FLOOR_Y)], w=1.4, amp=1.1))
    for lx in (TABLE_X0 + 30, TABLE_X1 - 30):
        a(pen.line([(lx - 12, FLOOR_Y), (lx, TABLE_Y + 10), (lx + 12, FLOOR_Y)], w=2))
    a(pen.line([(TABLE_X0, TABLE_Y), (TABLE_X1, TABLE_Y), (TABLE_X1, TABLE_Y + 10),
                (TABLE_X0, TABLE_Y + 10)], w=2, fill=FELT, close=True))
    a(pen.line([(TABLE_X0 + 3, TABLE_Y + 2.5), (TABLE_X1 - 3, TABLE_Y + 2.5)], w=1, color="#f7f2e8", amp=.3))
    for hx in range(TABLE_X0 + 8, TABLE_X1 - 4, 9):                             # hatching
        a(f'<line x1="{hx}" y1="{TABLE_Y+9}" x2="{hx+5}" y2="{TABLE_Y+4}" stroke="{INK}" '
          f'stroke-width=".7" opacity=".45"/>')
    net = ""
    for i in range(1, 6):
        net += f'<line x1="{NET_X-4}" y1="{TABLE_Y-i*4}" x2="{NET_X+4}" y2="{TABLE_Y-i*4}" stroke="{INK}" stroke-width=".6" opacity=".5"/>'
    a(net + pen.line([(NET_X - 4, TABLE_Y), (NET_X - 4, TABLE_Y - NET_H), (NET_X + 4, TABLE_Y - NET_H),
                      (NET_X + 4, TABLE_Y)], w=1.6))

    if not last:
        a(you(pen, ""))
        a(bot(pen, "", 1))
        a(pen.circle(HIT_L[0] + 2, HIT_L[1] - 26, BALL_R, w=1.3, fill="#f39c35"))
        a(text(320, 140, "your serve. pick a shot below ↓", 16))
    else:
        segs, ev = build_path(last)
        pts, ends, length = sample(segs)
        speed = 330 if last["shot"] == "smash" else 230
        pre, move, post = 0.55, max(1.3, length / speed), 1.8
        loop = pre + move + post
        at = lambda f: (pre + move * f) / loop                                   # noqa: E731

        bot_t = at(ends[ev["bot"]]) if "bot" in ev else None
        if "bot_miss" in ev:
            bot_t = min(at(ends[1]) * 0.6 + at(ends[2]) * 0.4, 0.97)
        a(you(pen, swing(at(0), loop)))
        a(bot(pen, swing(bot_t, loop, miss="bot_miss" in ev), loop))

        # dotted trajectory, as if a coach drew it
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        a(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.3" stroke-dasharray=".1 6" '
          f'stroke-linecap="round" opacity="{1 if debug else .32}"/>')
        peak = min(pts[: max(2, int(len(pts) * (ends[1])))], key=lambda p: p[1])
        a(text(peak[0], peak[1] - 12, last["shot"], 13, color="#6b655b"))

        # ball, its trail and its shadow, sampled so they stay in sync
        n = len(pts)
        times = [0.0] + [at(k / (n - 1)) for k in range(n)] + [1.0]
        kt = ";".join(f"{t:.4f}" for t in times)

        def series(vals):
            vals = [vals[0]] + vals + [vals[-1]]
            return ";".join(f"{v:.1f}" if isinstance(v, float) else str(v) for v in vals)

        def anim(attr, vals, delay=0.0):
            return (f'<animate attributeName="{attr}" dur="{loop:.2f}s" begin="{delay}s" '
                    f'repeatCount="indefinite" keyTimes="{kt}" values="{series(vals)}"/>')

        sx, sy, srx, sop = [], [], [], []
        for x, y in pts:
            on_table = TABLE_X0 <= x <= TABLE_X1 and y <= BALL_Y + 1
            ground = TABLE_Y - 1 if on_table else FLOOR_Y
            h = max(0.0, ground - y)
            sx.append(x); sy.append(float(ground))
            srx.append(max(2.0, 6 - h / 25)); sop.append(max(0.05, .35 - h / 400))
        a(f'<ellipse cx="{pts[0][0]}" cy="{TABLE_Y-1}" rx="5" ry="1.6" fill="{INK}" opacity=".3">'
          + anim("cx", sx) + anim("cy", sy) + anim("rx", srx) + anim("opacity", sop) + "</ellipse>")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        for delay, r, op in ((0.08, 3.6, .22), (0.04, 4.3, .4)):
            a(f'<circle cx="{xs[0]}" cy="{ys[0]}" r="{r}" fill="#f39c35" opacity="{op}">'
              + anim("cx", xs, delay) + anim("cy", ys, delay) + "</circle>")
        a(f'<circle cx="{xs[0]}" cy="{ys[0]}" r="{BALL_R}" fill="#f39c35" stroke="{INK}" stroke-width="1.3">'
          + anim("cx", xs) + anim("cy", ys) + "</circle>")

        # the outcome, scribbled in when it happens
        mark_t = at(ends[ev["mark"]]) if ev["mark"] < len(ends) else at(1)
        mx, my = {"net": (NET_X + 26, TABLE_Y - 48), "out": (580, 262),
                  "winner": (560, 128), "returned": (HIT_R[0] - 26, 128)}[last["outcome"]]
        color = RED if last["point"] == "bot" else ("#2f7a4f" if last["point"] == "you" else INK)
        t0, t1 = max(mark_t - 0.005, 0.001), min(mark_t + 0.04, 0.995)
        a(text(mx, my, OUTCOME_NOTE[last["outcome"]], 19, color=color,
               extra=f' font-weight="600" opacity="0" transform="rotate(-6 {mx} {my})"'
               .replace('opacity="0"', 'opacity="0"'))
          .replace("</text>", f'<animate attributeName="opacity" dur="{loop:.2f}s" repeatCount="indefinite" '
                              f'keyTimes="0;{t0:.3f};{t1:.3f};1" values="0;0;1;1"/></text>'))

    # what happened
    if last:
        a(text(W / 2 + 22, 334, f'@{escape(last["user"])} played {escape(describe(last))}', 15))
    bits = [f'rally {state["rally"]}', f'best rally {state["best_rally"]}', f'first to {WIN_SCORE}']
    hist = state["history"][-4:-1]
    if hist:
        bits.append("before: " + ", ".join(
            ("✓ " if h["outcome"] == "winner" else "↔ " if h["outcome"] == "returned" else "✗ ")
            + f'@{escape(h["user"])} {h["shot"]}' for h in reversed(hist)))
    a(text(W / 2 + 22, 358, "  ·  ".join(bits), 12, color="#8a8377"))
    a("</svg>")
    return "\n".join(o)


def write_svg(state, debug=False):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(state, debug))


# ------------------------------------------------------------------ cli ----

def main(argv):
    cmd = argv[1] if len(argv) > 1 else "render"
    if cmd == "render":
        write_svg(load_state(), debug="--debug" in argv)
        return 0
    if cmd == "move":
        number = os.environ.get("ISSUE_NUMBER", "0")
        title = os.environ.get("ISSUE_TITLE", "")
        user = os.environ.get("ISSUE_USER", "")
        owner = os.environ.get("REPO_OWNER", "")
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", user):
            print(json.dumps({"ok": False, "message": "I could not read your username."}))
            return 2
        shot = parse_shot(title)
        state = load_state()
        if shot is None:
            print("unknown shot; expected one of: " + ", ".join(SHOTS))
            result = {"ok": False, "message": "I did not recognise that shot. Use one of: "
                      + ", ".join(SHOTS) + "."}
        elif state["last"] and state["last"]["user"] == user and user != owner:
            result = {"ok": False, "message": "You hit the last ball! Let someone else take the next shot."}
        else:
            play(state, user, shot, seed=f"{number}-{user}-{shot}")
            save_state(state)
            write_svg(state)
            result = {"ok": True, "message": f"You played {describe(state['last'])}"}
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
