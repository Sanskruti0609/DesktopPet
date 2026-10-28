"""
DesktopPet - a little gray-and-white kitten who lives on your desktop.

Run:   pip install -r requirements.txt
       python desktop_cat.py          (pythonw desktop_cat.py = no console window)

She never gets in your way:
  - Clicks pass straight through her transparent areas (Windows); only her body is clickable.
  - She walks along the top of the taskbar / bottom of the screen.
  - She hides herself automatically while a fullscreen game or video is running (Windows).
  - Quit any time from the tray icon or by right-clicking her.

What she does
  - Walks (smooth tweened walk cycle) or crawls, rests in a corner, falls asleep, wakes up,
    stretches, wanders, repeats.  At night she sleeps longer.
  - Hover the cursor over her while she sleeps -> she wakes up GRUMPY (angry eyes, shaking,
    "Grr!").  Leave her alone and she calms down and goes back to sleep.  Keep bugging her
    for too long and she stomps off to the other corner.
  - Move the cursor slowly over her while she's awake -> she purrs with hearts (and may doze
    off happily under your cursor... where you can wake her up again).
  - Click = hop.  Drag = pick her up (legs dangle), release = she drops and lands.
  - Sometimes she wanders over to sit near your cursor (can be turned off).
  - Optional break reminder: every 45 min she stretches and tells you to take a break.
"""

import ctypes
import math
import os
import random
import sys
from ctypes import wintypes
from datetime import datetime

from PIL import Image
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import (QAction, QBrush, QColor, QCursor, QFont, QIcon, QImage,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
                           QRadialGradient, QTransform)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

# ---------------------------------------------------------------------------
# CONFIG - tweak these
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

SPRITE_HEIGHT = 150          # on-screen size of her picture canvas, in pixels
REST_CORNER = "right"        # "left", "right" or "random"
MARGIN = 6                   # gap between her and the screen edge
WALK_SPEED = 95              # px / second
CRAWL_SPEED = 34
WALK_CYCLE_PX = 62           # distance she travels per full walk cycle (smaller = faster legs)
CRAWL_CYCLE_PX = 46
REST_TIME = (8, 15)          # seconds loafing before she dozes off
SLEEP_TIME = (25, 60)        # seconds asleep before she wakes up and stretches
NIGHT_HOURS = (22, 6)        # between these hours she sleeps much longer
BREAK_MINUTES = 45
FOLLOW_EVERY = (60, 150)     # seconds between "go sit near the cursor" urges
CHATTER_EVERY = (50, 130)    # seconds between random speech bubbles
CHATTER = ["mew?", "mrrp!", "*purr*", "feed me?", "meow~", "boop!", "*stretch*"]
SS = 2                       # supersampling for sharp scaling

POSES = {
    "stand": dict(sx=1.00, sy=1.00, rot=0.0, tilt=0.0),
    "crawl": dict(sx=1.05, sy=0.87, rot=2.5, tilt=0.0),
    "held":  dict(sx=0.95, sy=1.07, rot=0.0, tilt=0.0),
}
TOP_FRAC = {"stand": 0.97, "walk": 0.92, "rest": 0.56, "sleep": 0.50, "doze": 0.55,
            "stretch": 0.82, "angry": 0.56, "content": 0.55}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def ease(u):
    u = clamp(u, 0.0, 1.0)
    return u * u * (3 - 2 * u)


def is_night():
    h = datetime.now().hour
    a, b = NIGHT_HOURS
    return h >= a or h < b


def heart_path(s):
    p = QPainterPath()
    p.moveTo(0, s)
    p.cubicTo(-s * 1.3, -s * 0.1, -s * 0.5, -s * 1.0, 0, -s * 0.35)
    p.cubicTo(s * 0.5, -s * 1.0, s * 1.3, -s * 0.1, 0, s)
    return p


class Spr:
    """One loaded picture (pixmap for drawing + image for click/hover tests)."""

    def __init__(self, path, factor):
        im = Image.open(path).convert("RGBA")
        w, h = max(1, int(im.width * factor)), max(1, int(im.height * factor))
        im = im.resize((w, h), Image.LANCZOS)
        self.img = QImage(im.tobytes("raw", "RGBA"), w, h, w * 4,
                          QImage.Format_RGBA8888).copy()
        self.pix = QPixmap.fromImage(self.img)
        self.w, self.h = w / SS, h / SS

    def solid(self, x, y):
        ix, iy = int(x * SS), int(y * SS)
        if 0 <= ix < self.img.width() and 0 <= iy < self.img.height():
            return self.img.pixelColor(ix, iy).alpha() > 40
        return False


class Cat(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # ---- settings ----
        self.settings = QSettings("DesktopPet", "Cat")
        self.opt = {k: self.settings.value(k, d, type=bool) for k, d in
                    (("follow", True), ("chatty", True), ("fs_hide", True), ("breaks", False))}

        # ---- sprites ----
        stand_path = os.path.join(ASSETS, "stand.png")
        if not os.path.exists(stand_path):
            raise SystemExit("assets/stand.png not found - keep the assets folder next to desktop_cat.py")
        base_im = Image.open(stand_path)
        factor = SPRITE_HEIGHT * SS / base_im.height
        self.f = SPRITE_HEIGHT / base_im.height                   # logical px per source px
        A = lambda n: os.path.join(ASSETS, n + ".png")
        self.sp = {n: Spr(A(n), factor) for n in ("stand", "rest", "sleep", "stretch", "angry")}
        self.walk = [Spr(A("walk_%02d" % i), factor) for i in range(9)]
        self.doze = ([self.sp["rest"]] + [Spr(A("doze_%d" % i), factor) for i in range(6)]
                     + [self.sp["sleep"]])
        self.content = self.doze[3]

        self.cw = self.sp["stand"].w
        self.ch = self.sp["stand"].h
        paws_bottom = base_im.convert("RGBA").getbbox()[3]
        self.pad_px = (base_im.height - paws_bottom) * self.f

        self.W = int(self.cw * 1.15) + 40
        self.H = int(self.ch * 1.25) + 120
        self.anchor_y = self.H - 6
        self.setFixedSize(self.W, self.H)

        # ---- screen ----
        self.geo = QApplication.primaryScreen().availableGeometry()
        self.floor = float(self.geo.bottom() + self.pad_px)
        self.x = float(self.geo.center().x())
        self.y = self.floor
        self.wx = self.wy = None
        self.fx = self.fy = 0.0

        # ---- motion / animation state ----
        self.vx = self.vy = 0.0
        self.face = -1                       # +1 = looking right, -1 = looking left
        self.flip_cur = float(self.face)
        self.cycle = 0.0
        self.t = 0.0
        self.state = "idle"
        self.state_t = 0.0
        self.cur = dict(POSES["stand"])
        self.tgt = dict(POSES["stand"])
        self.rate = 7.0
        self.extra_lift = self.extra_rot = self.shake = 0.0
        self.breath = 0.0
        self.breath_amp, self.breath_hz = 0.008, 0.45
        self.dip = 0.0
        self.dip_t = 1.0

        self.key = "stand"
        self.spec = (self.sp["stand"], None, 0.0)
        self.prev_spec = None
        self.fade = 1.0
        self.fade_dur = 0.2
        self.xf = QTransform()

        self.targets = []
        self.move_mode = "walk"
        self.speed_mult = 1.0
        self.after = self.settle
        self.idle_dur = 1.0
        self.idle_then = self.go_corner
        self.corner_side = "right"
        self.settle_face = None
        self.sleep_after_settle = False
        self.rest_dur = 10.0
        self.sleep_dur = 30.0
        self.doze_pos = 0.0
        self.doze_start = 0.0
        self.grudge = 0.0
        self.pet_t = 0.0
        self.heart_t = 0.0
        self.grumpy_hover = 0.0
        self.need_away = False               # after purr-napping, cursor must leave before she can get grumpy

        self.hover = False
        self.hover_t = 0.0
        self.away_t = 10.0
        self.cursor_speed = 0.0
        self.last_cur = QCursor.pos()

        self.bubble = None                   # [text, time_left]
        self.hearts = []
        self.chat_t = random.uniform(*CHATTER_EVERY)
        self.follow_t = random.uniform(*FOLLOW_EVERY)

        self.pressed = False
        self.press_g = QPointF()
        self.grab_off = (0.0, 0.0)
        self.last_gx = 0.0
        self.drag_vx = 0.0

        self._ct = None                      # current click-through flag
        self.hidden_fs = False
        self.fs_timer = 0.0

        self.build_menu()
        self.build_tray()

        self.break_timer = QTimer(self)
        self.break_timer.timeout.connect(self.break_time)
        self.break_timer.start(BREAK_MINUTES * 60 * 1000)

        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(10)

        self.reposition()
        self.go_corner()

    # =====================================================================
    # menu / tray / settings
    # =====================================================================
    def build_menu(self):
        m = QMenu()
        for label, cmd in (("Rest in corner", "rest"), ("Walk around", "walk"),
                           ("Crawl", "crawl"), ("Stretch", "stretch"),
                           ("Sleep", "sleep")):
            m.addAction(label, lambda c=cmd: self.command(c))
        m.addSeparator()
        for key, label in (("follow", "Sometimes sit near my cursor"),
                           ("chatty", "Speech bubbles"),
                           ("fs_hide", "Hide during fullscreen apps"),
                           ("breaks", "Break reminder (every %d min)" % BREAK_MINUTES)):
            act = QAction(label, m)
            act.setCheckable(True)
            act.setChecked(self.opt[key])
            act.toggled.connect(lambda v, k=key: self.set_opt(k, v))
            m.addAction(act)
        m.addSeparator()
        m.addAction("Quit", QApplication.quit)
        self.menu = m

    def build_tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            icon = QIcon(self.sp["stand"].pix.scaled(64, 64, Qt.KeepAspectRatio,
                                                      Qt.SmoothTransformation))
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip("DesktopPet")
            self.tray.setContextMenu(self.menu)
            self.tray.show()

    def set_opt(self, key, value):
        self.opt[key] = bool(value)
        self.settings.setValue(key, bool(value))

    def break_time(self):
        if self.opt["breaks"] and self.state not in ("held", "fall"):
            self.say("Stretch break!", 3.5)
            self.command("stretch")

    # =====================================================================
    # helpers
    # =====================================================================
    def set_state(self, name):
        self.state = name
        self.state_t = 0.0
        fn = getattr(self, "enter_" + name, None)
        if fn:
            fn()

    def idle(self, dur, then):
        self.set_state("idle")
        self.idle_dur = dur
        self.idle_then = then

    def pose(self, name):
        self.tgt = dict(POSES[name])

    def say(self, text, dur=2.2):
        if self.opt["chatty"]:
            self.bubble = [text, dur]

    def cursor_x(self):
        return float(QCursor.pos().x())

    def corner_x(self, side=None):
        side = side or (REST_CORNER if REST_CORNER != "random"
                        else random.choice(["left", "right"]))
        self.corner_side = side
        half = self.cw * 0.5
        return self.geo.left() + MARGIN + half if side == "left" \
            else self.geo.right() - MARGIN - half

    def rand_x(self):
        half = self.cw * 0.5
        return random.uniform(self.geo.left() + half, self.geo.right() - half)

    def start_move(self, targets, mode, after, speed_mult=1.0):
        self.targets = list(targets)
        self.move_mode = mode
        self.after = after
        self.speed_mult = speed_mult
        self.set_state("move")

    def go_corner(self):
        self.start_move([self.corner_x()], "walk", self.settle)

    def settle(self, face=None):
        self.settle_face = face
        self.set_state("settle")

    def go_follow(self):
        cx = self.cursor_x()
        side = -1 if self.x < cx else 1
        tx = clamp(cx + side * 190, self.geo.left() + self.cw * 0.5,
                   self.geo.right() - self.cw * 0.5)
        self.say("mew!", 1.6)
        self.start_move([tx], "walk", lambda: self.settle(1 if cx > self.x else -1))

    def begin_wander(self):
        mode = "crawl" if random.random() < 0.35 else "walk"
        self.start_move([self.rand_x() for _ in range(random.randint(1, 3))],
                        mode, self.go_corner)

    def decide(self):
        r = random.random()
        if self.opt["follow"] and r < 0.3 and abs(self.cursor_x() - self.x) > 300:
            self.go_follow()
        elif r < 0.5:
            self.begin_wander()
        else:
            self.go_corner()

    def command(self, name):
        self.vx = 0.0
        if name == "rest":
            self.go_corner()
        elif name == "walk":
            self.start_move([self.rand_x(), self.rand_x()], "walk", self.go_corner)
        elif name == "crawl":
            self.start_move([self.rand_x()], "crawl", self.go_corner)
        elif name == "stretch":
            self.set_state("stretch")
        elif name == "sleep":
            self.sleep_after_settle = True
            self.settle()

    # =====================================================================
    # mouse
    # =====================================================================
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.menu.exec(QCursor.pos())
        elif e.button() == Qt.LeftButton:
            g = QCursor.pos()
            self.pressed = True
            self.press_g = QPointF(g)
            self.grab_off = (self.x - g.x(), self.y - g.y())

    def mouseMoveEvent(self, e):
        if self.pressed and self.state != "held":
            g = QCursor.pos()
            if math.hypot(g.x() - self.press_g.x(), g.y() - self.press_g.y()) > 6:
                self.set_state("held")

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.state == "held":
            self.vy = 0.0
            self.set_state("fall")
        elif self.pressed:
            if self.state in ("sleep", "dozing"):
                self.set_state("wake_angry")
            elif self.state in ("rest", "idle", "settle", "stretch", "move", "pet"):
                self.vx = 0.0
                self.set_state("hop")
                self.say("mew!", 1.4)
        self.pressed = False

    # =====================================================================
    # state enter
    # =====================================================================
    def enter_held(self):
        self.last_gx = float(QCursor.pos().x())
        self.drag_vx = 0.0

    def enter_settle(self):
        if self.settle_face is not None:
            self.face = self.settle_face
        else:
            self.face = -1 if self.corner_side == "right" else 1
        self.vx = 0.0

    def enter_rest(self):
        if is_night():
            self.rest_dur = random.uniform(3, 6)
            self.sleep_dur = random.uniform(120, 300)
        else:
            self.rest_dur = random.uniform(*REST_TIME)
            self.sleep_dur = random.uniform(*SLEEP_TIME)

    def enter_dozing(self):
        self.doze_start = self.doze_pos = 0.0

    def enter_waking(self):
        self.doze_start = 7.0

    def enter_wake_angry(self):
        self.doze_start = self.doze_pos if self.doze_pos > 0 else 7.0
        self.grudge = 15.0

    def enter_grumpy(self):
        self.grumpy_hover = 0.0
        self.say("Grr!", 2.0)

    def enter_pet(self):
        self.pet_t = 0.0
        self.heart_t = 0.0
        self.say("purr~", 2.0)

    def enter_stretch(self):
        self.vx = 0.0

    # =====================================================================
    # state per-frame
    # =====================================================================
    def st_idle(self, dt):
        self.pose("stand")
        if self.state_t > self.idle_dur:
            self.idle_then()

    def st_move(self, dt):
        crawl = self.move_mode == "crawl"
        speed = (CRAWL_SPEED if crawl else WALK_SPEED) * self.speed_mult
        cyc_px = CRAWL_CYCLE_PX if crawl else WALK_CYCLE_PX
        tx = self.targets[0]
        d = tx - self.x
        if abs(d) < 3:
            self.x = tx
            self.vx = 0.0
            self.targets.pop(0)
            if self.targets:
                self.idle(random.uniform(1.0, 2.5), self.resume_move)
            else:
                self.speed_mult = 1.0
                self.after()
            return
        self.face = 1 if d > 0 else -1
        slow = clamp(abs(d) / 110.0, 0.2, 1.0)
        vt = self.face * speed * slow
        self.vx += (vt - self.vx) * (1 - math.exp(-4.5 * dt))
        self.x += self.vx * dt
        self.cycle += abs(self.vx) * dt / cyc_px
        s = min(1.0, abs(self.vx) / speed)
        self.extra_lift = (0.5 + 0.5 * math.cos(4 * math.pi * self.cycle)) * (2.2 if not crawl else 1.0) * s
        self.pose("crawl" if crawl else "stand")
        self.breath_amp = 0.0

    def resume_move(self):
        self.set_state("move")

    def st_settle(self, dt):
        self.pose("stand")
        if self.state_t > 0.9:
            if self.sleep_after_settle:
                self.sleep_after_settle = False
                self.set_state("dozing")
            else:
                self.set_state("rest")

    def st_rest(self, dt):
        self.pose("stand")
        self.breath_amp, self.breath_hz = 0.016, 0.42
        if self.state_t > self.rest_dur:
            self.set_state("dozing")

    def st_dozing(self, dt):
        self.pose("stand")
        self.breath_amp, self.breath_hz = 0.018, 0.36
        u = self.state_t / 2.0
        self.doze_pos = ease(u) * 7.0
        if u >= 1.0:
            self.set_state("sleep")

    def st_sleep(self, dt):
        self.pose("stand")
        self.doze_pos = 7.0
        self.breath_amp, self.breath_hz = 0.022, 0.30
        if self.state_t > self.sleep_dur:
            self.set_state("waking")

    def st_waking(self, dt):
        self.pose("stand")
        self.breath_amp, self.breath_hz = 0.016, 0.42
        u = self.state_t / 1.3
        self.doze_pos = self.doze_start * (1 - ease(u))
        if u >= 1.0:
            self.doze_pos = 0.0
            self.set_state("stretch")

    def st_stretch(self, dt):
        t = self.state_t
        if t >= 4.0:
            self.idle(0.6, self.begin_wander)
            return
        self.pose("stand")
        if 0.5 < t < 3.0:
            self.tgt["tilt"] = math.sin(t * 15) * 0.6       # little tremble
        self.breath_amp, self.breath_hz = 0.012, 0.5
        self.rate = 20.0

    def st_wake_angry(self, dt):
        self.pose("stand")
        u = self.state_t / 0.45
        self.doze_pos = self.doze_start * (1 - ease(u))
        if u >= 1.0:
            self.doze_pos = 0.0
            self.set_state("grumpy")

    def st_grumpy(self, dt):
        self.pose("stand")
        self.breath_amp, self.breath_hz = 0.02, 0.9
        self.shake = math.sin(self.t * 62) * 1.8 * clamp(1.0 - self.state_t / 1.6, 0.0, 1.0)
        if self.hover:
            self.grumpy_hover += dt
        if self.state_t > 2.4 and self.away_t > 1.0:
            self.say("Hmph.", 1.6)
            self.set_state("rest")
            self.rest_dur = random.uniform(2.0, 3.5)       # goes straight back to sleep
        elif self.grumpy_hover > 6.0:
            self.say("Hmph!", 2.0)
            self.grudge = 25.0
            side = "left" if self.corner_side == "right" else "right"
            self.start_move([self.corner_x(side)], "walk", self.settle, speed_mult=1.5)

    def st_pet(self, dt):
        self.pose("stand")
        self.pet_t += dt
        self.breath_amp, self.breath_hz = 0.02, 1.4        # purring
        self.heart_t -= dt
        if self.heart_t <= 0 and self.hover:
            self.heart_t = 0.5
            self.spawn_heart()
        if self.away_t > 1.0:
            self.set_state("rest")
        elif self.pet_t > 9.0:
            self.say("zzz...", 2.0)
            self.need_away = True
            self.set_state("dozing")                        # falls asleep, happy

    def st_hop(self, dt):
        t = self.state_t
        if t < 0.15:
            self.tgt = dict(sx=1.1, sy=0.88, rot=0.0, tilt=0.0)
            self.rate = 25.0
        elif t < 0.62:
            u = (t - 0.15) / 0.47
            self.extra_lift = 55.0 * math.sin(u * math.pi)
            self.tgt = dict(sx=0.95, sy=1.10, rot=0.0, tilt=0.0)
            self.rate = 20.0
            self.cycle += dt * 1.2
        elif t < 0.8:
            self.tgt = dict(sx=1.1, sy=0.88, rot=0.0, tilt=0.0)
            self.rate = 25.0
        else:
            self.idle(0.8, self.decide)

    def st_held(self, dt):
        g = QCursor.pos()
        k = 1 - math.exp(-25.0 * dt)
        self.x += (g.x() + self.grab_off[0] - self.x) * k
        self.y += (g.y() + self.grab_off[1] - self.y) * k
        self.y = clamp(self.y, self.geo.top() + self.ch * 1.1, self.floor)
        vx = (g.x() - self.last_gx) / max(dt, 1e-3)
        self.last_gx = float(g.x())
        self.drag_vx += (vx - self.drag_vx) * (1 - math.exp(-10.0 * dt))
        self.cycle += dt * 1.5                                # legs paddle
        self.tgt = dict(POSES["held"])
        self.tgt["tilt"] = clamp(-self.drag_vx * 0.02, -20, 20)
        self.rate = 10.0

    def st_fall(self, dt):
        self.vy += 2600.0 * dt
        self.y += self.vy * dt
        self.cycle += dt * 1.8
        self.tgt = dict(POSES["held"])
        self.tgt["tilt"] = 0.0
        self.rate = 10.0
        if self.y >= self.floor:
            self.y = self.floor
            self.vy = 0.0
            self.cur.update(sx=1.25, sy=0.72)                 # landing squash
            self.idle(0.8, self.go_corner)

    # =====================================================================
    # reactions to the cursor
    # =====================================================================
    def reactions(self, dt):
        st = self.state
        if self.hover:
            self.hover_t += dt
            self.away_t = 0.0
        else:
            self.hover_t = 0.0
            self.away_t += dt
        self.grudge = max(0.0, self.grudge - dt)
        if st in ("held", "fall", "hop") or self.pressed:
            return
        if self.need_away and not self.hover:
            self.need_away = False
        if (st in ("sleep", "dozing") and self.hover and self.hover_t > 0.12
                and not self.need_away):
            self.set_state("wake_angry")
        elif (st in ("idle", "rest", "settle") and self.hover and self.hover_t > 0.6
              and self.cursor_speed < 500 and self.grudge <= 0):
            self.vx = 0.0
            self.set_state("pet")

    def spawn_heart(self):
        hx, hy = self.head_pos(0.0)
        self.hearts.append(dict(x=hx + random.uniform(-14, 14), y=hy,
                                vx=random.uniform(-8, 8), life=1.6, size=random.uniform(4.5, 7)))

    def head_pos(self, dy=0.0):
        """approx. head position in widget coordinates (for hearts / vein / bubble)"""
        f = self.f
        ax = self.W / 2 + self.face * (195 * f)
        ay = self.anchor_y - (237 * f) - dy
        if self.key in ("stand", "walk"):
            ax = self.W / 2 + self.face * (210 * f)
            ay = self.anchor_y - (400 * f) - dy
        return ax, ay

    # =====================================================================
    # picture selection
    # =====================================================================
    def seq(self, pos):
        pos = clamp(pos, 0.0, 7.0)
        a = int(pos)
        b = min(a + 1, 7)
        return self.doze[a], self.doze[b], pos - a

    def frame_spec(self):
        st, sp = self.state, self.sp
        if st == "move" or st in ("held", "fall") or (st == "hop" and 0.15 < self.state_t < 0.62):
            pos = (self.cycle % 1.0) * 16.0
            if pos > 8.0:
                pos = 16.0 - pos
            a = min(int(pos), 8)
            b = min(a + 1, 8)
            return "walk", (self.walk[a], self.walk[b], pos - a)
        if st in ("settle", "rest"):
            return "rest", (sp["rest"], None, 0.0)
        if st in ("dozing", "waking", "wake_angry"):
            return "doze", self.seq(self.doze_pos)
        if st == "sleep":
            return "sleep", (sp["sleep"], None, 0.0)
        if st == "grumpy":
            return "angry", (sp["angry"], None, 0.0)
        if st == "pet":
            return "content", (self.content, None, 0.0)
        if st == "stretch":
            if 0.2 < self.state_t < 3.2:
                return "stretch", (sp["stretch"], None, 0.0)
            if self.state_t <= 0.2 and self.key in ("doze", "rest"):
                return "rest", (sp["rest"], None, 0.0)
            return "stand", (sp["stand"], None, 0.0)
        return "stand", (sp["stand"], None, 0.0)

    # =====================================================================
    # click-through / fullscreen (Windows)
    # =====================================================================
    def hit(self, g, tol):
        spr = self.spec[0] if self.spec[2] < 0.5 or self.spec[1] is None else self.spec[1]
        inv, ok = self.xf.inverted()
        if not ok or self.wx is None:
            return False
        lx, ly = g.x() - self.wx, g.y() - self.wy
        for ox, oy in ((0, 0), (tol, 0), (-tol, 0), (0, tol), (0, -tol)):
            p = inv.map(QPointF(lx + ox, ly + oy))
            if spr.solid(p.x() + spr.w / 2, p.y() + spr.h):
                return True
        return False

    def set_clickthrough(self, on):
        if sys.platform != "win32" or on == self._ct:
            return
        try:
            u = ctypes.windll.user32
            u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.GetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            hwnd = int(self.winId())
            ex = u.GetWindowLongW(hwnd, -20)
            ex = (ex | 0x20 | 0x80000) if on else (ex & ~0x20)
            u.SetWindowLongW(hwnd, -20, ex)
            self._ct = on
        except Exception:
            self._ct = on

    def fullscreen_app_active(self):
        if sys.platform != "win32":
            return False
        try:
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            if not hwnd or hwnd == int(self.winId()):
                return False
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(hwnd, cls, 64)
            if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
                return False
            r = wintypes.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            scr = QApplication.primaryScreen()
            dpr = scr.devicePixelRatio()
            g = scr.geometry()
            return (r.left <= g.left() * dpr + 1 and r.top <= g.top() * dpr + 1 and
                    r.right - r.left >= g.width() * dpr - 2 and
                    r.bottom - r.top >= g.height() * dpr - 2)
        except Exception:
            return False

    def check_fullscreen(self):
        fs = self.opt["fs_hide"] and self.fullscreen_app_active()
        if fs and not self.hidden_fs:
            self.hidden_fs = True
            self.hide()
            self.timer.setInterval(500)
        elif not fs and self.hidden_fs:
            self.hidden_fs = False
            self._ct = None
            self.show()
            self.clock.restart()
            self.timer.setInterval(10)

    # =====================================================================
    # main loop
    # =====================================================================
    def tick(self):
        dt = min(self.clock.restart() / 1000.0, 0.05)
        if dt <= 0:
            return
        self.fs_timer -= dt
        if self.fs_timer <= 0 or (self.hidden_fs and self.fs_timer <= 0.5):
            self.fs_timer = 1.0
            self.check_fullscreen()
        if self.hidden_fs:
            return

        self.t += dt
        self.state_t += dt
        self.extra_lift = self.extra_rot = self.shake = 0.0
        self.rate = 7.0
        self.breath_amp, self.breath_hz = 0.008, 0.45

        # cursor + hover
        g = QCursor.pos()
        sp_now = math.hypot(g.x() - self.last_cur.x(), g.y() - self.last_cur.y()) / dt
        self.cursor_speed += (sp_now - self.cursor_speed) * (1 - math.exp(-8.0 * dt))
        self.last_cur = g
        self.hover = self.hit(g, 8)
        self.reactions(dt)

        # random life: chatter + follow urge
        if self.state in ("idle", "rest", "move"):
            self.chat_t -= dt
            if self.chat_t <= 0:
                self.chat_t = random.uniform(*CHATTER_EVERY)
                if self.bubble is None:
                    self.say(random.choice(CHATTER), 2.0)
        if self.state in ("idle", "rest") and self.opt["follow"]:
            self.follow_t -= dt
            if self.follow_t <= 0:
                self.follow_t = random.uniform(*FOLLOW_EVERY)
                if abs(self.cursor_x() - self.x) > 350 and not self.hover:
                    self.go_follow()

        getattr(self, "st_" + self.state)(dt)

        # smooth pose
        k = 1 - math.exp(-self.rate * dt)
        for key in self.cur:
            self.cur[key] += (self.tgt[key] - self.cur[key]) * k
        self.flip_cur += (self.face - self.flip_cur) * (1 - math.exp(-24.0 * dt))
        self.breath = math.sin(self.t * 2 * math.pi * self.breath_hz) * self.breath_amp

        # picture + crossfade
        key, spec = self.frame_spec()
        if key != self.key:
            old = self.key
            self.prev_spec = self.spec
            self.key = key
            self.fade = 0.0
            pair = {old, key}
            if "doze" in pair:
                self.fade_dur = 0.06
            elif pair <= {"walk", "stand"}:
                self.fade_dur = 0.12
            else:
                self.fade_dur = 0.24
                self.dip_t = 0.0
        self.spec = spec
        self.fade = min(1.0, self.fade + dt / self.fade_dur)
        if self.dip_t < 1.0:
            self.dip_t = min(1.0, self.dip_t + dt / 0.28)
        self.dip = math.sin(self.dip_t * math.pi) if self.dip_t < 1.0 else 0.0

        # particles + bubble
        for h in self.hearts:
            h["life"] -= dt
            h["y"] -= 26 * dt
            h["x"] += h["vx"] * dt
        self.hearts = [h for h in self.hearts if h["life"] > 0]
        if self.bubble:
            self.bubble[1] -= dt
            if self.bubble[1] <= 0:
                self.bubble = None

        # position / clamp
        if self.state not in ("held", "fall"):
            self.y = self.floor
        half = self.cw * 0.5
        self.x = clamp(self.x, self.geo.left() + half * 0.9, self.geo.right() - half * 0.9)
        self.compute_transform()
        self.reposition()

        # click-through unless the cursor is on her
        want = self.pressed or self.state == "held" or self.hit(g, 12)
        self.set_clickthrough(not want)

        self.update()
        slow = (self.state in ("sleep", "rest") and self.fade >= 1.0 and not self.hearts
                and self.bubble is None and not self.hover)
        want_iv = 33 if slow else 10
        if self.timer.interval() != want_iv:
            self.timer.setInterval(want_iv)

    def compute_transform(self):
        c = self.cur
        gsx = c["sx"] * (1 - self.breath * 0.4) * (1 + 0.04 * self.dip)
        gsy = c["sy"] * (1 + self.breath) * (1 - 0.06 * self.dip)
        t = QTransform()
        t.translate(self.W / 2 + self.fx + self.shake, self.anchor_y + self.fy - self.extra_lift)
        t.rotate(c["rot"] * self.face + c["tilt"] + self.extra_rot)
        t.scale(self.flip_cur * gsx, gsy)
        self.xf = t

    def reposition(self):
        tx, ty = self.x - self.W / 2, self.y - self.anchor_y
        ix, iy = math.floor(tx), math.floor(ty)
        self.fx, self.fy = tx - ix, ty - iy          # sub-pixel remainder is drawn, not moved
        if (ix, iy) != (self.wx, self.wy):
            self.move(ix, iy)
            self.wx, self.wy = ix, iy

    # =====================================================================
    # drawing
    # =====================================================================
    def draw_spr(self, p, spr, op):
        p.setOpacity(op)
        p.drawPixmap(QRectF(-spr.w / 2, -spr.h, spr.w, spr.h), spr.pix, QRectF(spr.pix.rect()))

    def draw_spec(self, p, spec, op):
        a, b, fr = spec
        self.draw_spr(p, a, op)
        if b is not None and b is not a and fr > 0.002:
            self.draw_spr(p, b, op * fr)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        ax, ay = self.W / 2 + self.fx, self.anchor_y + self.fy

        # ground shadow
        if self.state not in ("held", "fall"):
            k = 1 - min(self.extra_lift / 90.0, 0.6)
            rx = self.cw * 0.34 * k
            g = QRadialGradient(QPointF(0, 0), rx)
            g.setColorAt(0, QColor(0, 0, 0, 60))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.save()
            p.translate(ax, ay - self.pad_px + 2)
            p.scale(1, 7.0 / rx)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(0, 0), rx, rx)
            p.restore()

        # the kitten
        p.setTransform(self.xf)
        if self.fade < 1.0 and self.prev_spec is not None:
            self.draw_spec(p, self.prev_spec, 1.0)
            self.draw_spec(p, self.spec, self.fade)
        else:
            self.draw_spec(p, self.spec, 1.0)
        p.resetTransform()
        p.setOpacity(1.0)

        # overlays
        if self.state == "sleep":
            self.draw_zzz(p)
        if self.state == "grumpy":
            hx, hy = self.head_pos(0.0)
            self.draw_vein(p, hx + self.face * 12, hy - 22, 9.0 + 1.2 * math.sin(self.t * 14))
        for h in self.hearts:
            a = clamp(h["life"] / 0.5, 0.0, 1.0) if h["life"] < 0.5 else 1.0
            p.save()
            p.translate(h["x"], h["y"])
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(238, 92, 128, int(235 * a)))
            p.drawPath(heart_path(h["size"]))
            p.restore()
        if self.bubble:
            self.draw_bubble(p, self.bubble[0], min(1.0, self.bubble[1] / 0.3))
        p.end()

    def draw_zzz(self, p):
        f = QFont("Segoe UI", 12)
        f.setBold(True)
        hx, hy = self.head_pos(0.0)
        for i in range(3):
            ph = (self.t * 0.45 + i / 3.0) % 1.0
            f.setPointSizeF(9 + ph * 9)
            p.setFont(f)
            p.setPen(QColor(90, 105, 170, int(220 * math.sin(ph * math.pi))))
            p.drawText(QPointF(hx + self.face * (8 + ph * 16), hy - 10 - ph * 40), "z")

    def draw_vein(self, p, cx, cy, r):
        p.setPen(QPen(QColor(215, 40, 45), 2.8, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        for sx_, sy_ in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            path = QPainterPath(QPointF(cx + sx_ * r * 0.28, cy + sy_ * r))
            path.quadTo(QPointF(cx + sx_ * r * 0.28, cy + sy_ * r * 0.28),
                        QPointF(cx + sx_ * r, cy + sy_ * r * 0.28))
            p.drawPath(path)

    def draw_bubble(self, p, text, alpha):
        f = QFont("Segoe UI", 9)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 20
        h = fm.height() + 10
        top = self.anchor_y - TOP_FRAC.get(self.key, 0.9) * self.ch - self.extra_lift
        cx = self.W / 2 + self.fx
        x = clamp(cx - w / 2, 4, self.W - w - 4)
        y = top - h - 12
        p.setOpacity(alpha)
        p.setPen(QPen(QColor(110, 110, 125), 1.4))
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawRoundedRect(QRectF(x, y, w, h), 9, 9)
        tail = QPolygonF([QPointF(cx - 5, y + h - 0.5), QPointF(cx + 5, y + h - 0.5),
                          QPointF(cx, y + h + 8)])
        p.setPen(Qt.NoPen)
        p.drawPolygon(tail)
        p.setPen(QPen(QColor(110, 110, 125), 1.4))
        p.drawLine(QPointF(cx - 5, y + h), QPointF(cx, y + h + 8))
        p.drawLine(QPointF(cx + 5, y + h), QPointF(cx, y + h + 8))
        p.setPen(QColor(60, 55, 70))
        p.drawText(QRectF(x, y, w, h), Qt.AlignCenter, text)
        p.setOpacity(1.0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    cat = Cat()
    cat.show()
    sys.exit(app.exec())
