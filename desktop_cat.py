"""
Desktop Kitten - photo version with real poses.

Install:  pip install PySide6 pillow
Run:      python desktop_cat.py        (pythonw desktop_cat.py = no console window)

Keep these files in the same folder as this script:
    cat.png  cat_walk_1.png  cat_walk_2.png  cat_stretch.png  cat_rest.png  cat_sleep.png

What she does
  - Walks (4-frame step cycle with bobbing) or crawls (low, slow) to a corner of
    the screen, turns to face you, loafs, breathes, then falls asleep (floating z's).
  - Wakes up, stretches, wanders, goes back to a corner to rest. Loops forever.
  - Left-click = happy hop.  Drag = pick her up, release = she drops and lands.
  - Right-click menu: Rest in corner / Walk / Crawl / Stretch / Sleep / Quit.
  - Poses crossfade into each other so there are no hard jumps.
"""

import math
import os
import random
import sys

from PIL import Image
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QImage, QPainter,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

# ---------------------------------------------------------------------------
# Config - tweak these
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
SPRITE_HEIGHT = 140          # on-screen size of the picture canvas, in pixels
REST_CORNER = "right"        # "left", "right" or "random"
MARGIN = 6
WALK_SPEED = 95              # px / second
CRAWL_SPEED = 34
STEP_PX = 15                 # distance travelled per walk-cycle frame (smaller = faster legs)
REST_TIME = (8, 15)          # seconds loafing before she sleeps
SLEEP_TIME = (25, 60)        # seconds asleep before she stretches
FPS_MS = 16
SS = 2                       # supersampling for sharper scaling

POSES = {
    "stand": dict(sx=1.00, sy=1.00, rot=0.0, tilt=0.0),
    "held":  dict(sx=0.95, sy=1.07, rot=0.0, tilt=0.0),
    "squat": dict(sx=1.08, sy=0.88, rot=0.0, tilt=0.0),
}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def load_pix(path, factor):
    im = Image.open(path).convert("RGBA")          # images are pre-aligned; no cropping
    w, h = max(1, int(im.width * factor)), max(1, int(im.height * factor))
    im = im.resize((w, h), Image.LANCZOS)
    q = QImage(im.tobytes("raw", "RGBA"), w, h, w * 4, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(q)


class Cat(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        def need(name):
            p = os.path.join(HERE, name)
            if not os.path.exists(p):
                raise SystemExit(f"Missing {name} next to desktop_cat.py")
            return p

        base_path = need("cat.png")
        factor = SPRITE_HEIGHT * SS / Image.open(base_path).height
        self.S = {"base": load_pix(base_path, factor)}
        for key, fn in (("rest", "cat_rest.png"), ("sleep", "cat_sleep.png"),
                        ("stretch", "cat_stretch.png")):
            self.S[key] = load_pix(need(fn), factor)
        w1 = load_pix(need("cat_walk_1.png"), factor)
        w2 = load_pix(need("cat_walk_2.png"), factor)
        self.walk_frames = [w1, self.S["base"], w2, self.S["base"]]

        self.cw = self.S["base"].width() / SS
        self.ch = self.S["base"].height() / SS
        self.W = int(self.cw * 1.25) + 24
        self.H = int(self.ch * 1.35) + 110
        self.anchor_y = self.H - 6
        self.setFixedSize(self.W, self.H)

        self.geo = QApplication.primaryScreen().availableGeometry()
        self.floor = float(self.geo.bottom() - 2)
        self.x = float(self.geo.center().x())
        self.y = self.floor

        self.vx = self.vy = 0.0
        self.face = -1                       # +1 = head toward right edge, -1 = left
        self.flip_cur = float(self.face)
        self.phase = 0.0
        self.t = 0.0
        self.state = "idle"
        self.state_t = 0.0
        self.cur = dict(POSES["stand"])
        self.tgt = dict(POSES["stand"])
        self.rate = 7.0
        self.extra_lift = 0.0
        self.extra_rot = 0.0
        self.breath = 0.0
        self.breath_amp, self.breath_hz = 0.008, 0.45

        self.pix = self.S["base"]
        self.prev_pix = None
        self.fade = 1.0
        self.fade_dur = 0.14
        self.custom = False

        self.targets = []
        self.move_mode = "walk"
        self.after = self.settle
        self.idle_dur = 1.0
        self.idle_then = self.go_corner
        self.corner_side = "right"
        self.rest_dur = 10.0
        self.sleep_dur = 30.0

        self.pressed = False
        self.press_g = QPointF()
        self.grab_off = (0.0, 0.0)
        self.last_gx = 0.0
        self.drag_vx = 0.0

        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(FPS_MS)

        self.reposition()
        self.go_corner()

    # ---------------- helpers ----------------
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
        if self.custom:
            t = dict(POSES["stand"])
            if name == "squat":                       # crawling: sink the photo a bit
                t.update(sx=1.05, sy=0.90, rot=3.0)
        else:
            t = dict(POSES[name])
        self.tgt = t

    def corner_x(self):
        side = REST_CORNER if REST_CORNER != "random" else random.choice(["left", "right"])
        self.corner_side = side
        half = self.cw * 0.5
        return self.geo.left() + MARGIN + half if side == "left" \
            else self.geo.right() - MARGIN - half

    def start_move(self, targets, mode, after):
        self.targets = list(targets)
        self.move_mode = mode
        self.after = after
        self.set_state("move")

    def go_corner(self):
        self.start_move([self.corner_x()], "walk", self.settle)

    def settle(self):
        self.set_state("settle")

    def resume_move(self):
        self.set_state("move")

    def rand_x(self):
        half = self.cw * 0.5
        return random.uniform(self.geo.left() + half, self.geo.right() - half)

    def begin_wander(self):
        mode = "crawl" if random.random() < 0.35 else "walk"
        self.start_move([self.rand_x() for _ in range(random.randint(1, 3))],
                        mode, self.go_corner)

    # ---------------- menu / mouse ----------------
    def command(self, name):
        if name == "rest":
            self.go_corner()
        elif name == "walk":
            self.start_move([self.rand_x(), self.rand_x()], "walk", self.go_corner)
        elif name == "crawl":
            self.start_move([self.rand_x()], "crawl", self.go_corner)
        elif name == "stretch":
            self.set_state("stretch")
        elif name == "sleep":
            self.set_state("sleep")

    def show_menu(self, gpos):
        m = QMenu()
        for label, cmd in (("Rest in corner", "rest"), ("Walk around", "walk"),
                           ("Crawl", "crawl"), ("Stretch", "stretch"),
                           ("Sleep here", "sleep")):
            m.addAction(label, lambda c=cmd: self.command(c))
        m.addSeparator()
        m.addAction("Quit", QApplication.quit)
        m.exec(gpos)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.show_menu(e.globalPosition().toPoint())
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
        elif self.pressed and self.state in ("rest", "sleep", "idle", "settle", "stretch", "move"):
            self.set_state("hop")
        self.pressed = False

    # ---------------- state enter ----------------
    def enter_held(self):
        self.last_gx = float(QCursor.pos().x())
        self.drag_vx = 0.0

    def enter_settle(self):
        self.face = -1 if self.corner_side == "right" else 1

    def enter_rest(self):
        self.rest_dur = random.uniform(*REST_TIME)

    def enter_sleep(self):
        self.sleep_dur = random.uniform(*SLEEP_TIME)

    # ---------------- state per-frame ----------------
    def st_idle(self, dt):
        self.pose("stand")
        if self.state_t > self.idle_dur:
            self.idle_then()

    def st_move(self, dt):
        walking = self.move_mode == "walk"
        speed = WALK_SPEED if walking else CRAWL_SPEED
        tx = self.targets[0]
        d = tx - self.x
        if abs(d) < 4:
            self.x = tx
            self.vx = 0.0
            self.targets.pop(0)
            if self.targets:
                self.idle(random.uniform(1.0, 2.5), self.resume_move)
            else:
                self.after()
            return
        self.face = 1 if d > 0 else -1
        slow = clamp(abs(d) / 90.0, 0.25, 1.0)
        vt = self.face * speed * slow
        self.vx += (vt - self.vx) * (1 - math.exp(-5.0 * dt))
        self.x += self.vx * dt
        self.phase += abs(self.vx) * dt / STEP_PX
        s = min(1.0, abs(self.vx) / speed)
        self.extra_lift = abs(math.sin(self.phase * math.pi / 2)) * (3.0 if walking else 1.2) * s
        self.extra_rot = math.sin(self.phase * math.pi / 2) * 1.3 * s
        self.pose("stand" if walking else "squat")
        self.breath_amp = 0.0

    def st_settle(self, dt):
        self.pose("stand")
        self.rate = 3.5
        if self.state_t > 0.8:
            self.set_state("rest")

    def st_rest(self, dt):
        self.pose("stand")
        self.breath_amp, self.breath_hz = 0.016, 0.42
        if self.state_t > self.rest_dur:
            self.set_state("sleep")

    def st_sleep(self, dt):
        self.pose("stand")
        self.breath_amp, self.breath_hz = 0.022, 0.30
        if self.state_t > self.sleep_dur:
            self.set_state("stretch")

    def st_stretch(self, dt):
        t = self.state_t
        if t >= 4.3:
            self.idle(0.8, self.begin_wander)
            return
        self.pose("stand")
        if 0.5 < t < 3.2:
            self.tgt["tilt"] = math.sin(t * 16) * 0.7          # little tremble
        self.rate = 20.0

    def st_hop(self, dt):
        t = self.state_t
        if t < 0.15:
            self.tgt = dict(sx=1.1, sy=0.86, rot=0.0, tilt=0.0)
            self.rate = 25.0
        elif t < 0.6:
            u = (t - 0.15) / 0.45
            self.extra_lift = 60.0 * math.sin(u * math.pi)
            self.tgt = dict(sx=0.94, sy=1.12, rot=0.0, tilt=0.0)
            self.rate = 20.0
        elif t < 0.78:
            self.tgt = dict(sx=1.1, sy=0.88, rot=0.0, tilt=0.0)
            self.rate = 25.0
        else:
            self.idle(0.8, self.go_corner)

    def st_held(self, dt):
        g = QCursor.pos()
        k = 1 - math.exp(-25.0 * dt)
        self.x += (g.x() + self.grab_off[0] - self.x) * k
        self.y += (g.y() + self.grab_off[1] - self.y) * k
        self.y = clamp(self.y, self.geo.top() + self.ch * 1.2, self.floor)
        vx = (g.x() - self.last_gx) / max(dt, 1e-3)
        self.last_gx = float(g.x())
        self.drag_vx += (vx - self.drag_vx) * (1 - math.exp(-10.0 * dt))
        self.tgt = dict(POSES["held"])
        self.tgt["tilt"] = clamp(-self.drag_vx * 0.02, -20, 20)
        self.rate = 10.0

    def st_fall(self, dt):
        self.vy += 2600.0 * dt
        self.y += self.vy * dt
        self.tgt = dict(POSES["held"])
        self.rate = 10.0
        if self.y >= self.floor:
            self.y = self.floor
            self.vy = 0.0
            self.cur.update(sx=1.28, sy=0.68)                   # landing squash
            self.idle(0.7, self.go_corner)

    # ---------------- sprite choice ----------------
    def pick_pix(self):
        st = self.state
        pix = self.S["base"]
        if st == "sleep":
            pix = self.S["sleep"]
        elif st in ("settle", "rest"):
            pix = self.S["rest"]
        elif st == "stretch" and 0.35 < self.state_t < 3.6:
            pix = self.S["stretch"]
        elif st == "move":
            pix = self.walk_frames[int(self.phase) % 4]
        if pix is not self.pix:
            walk_swap = st == "move" and self.pix in self.walk_frames
            self.prev_pix = self.pix
            self.pix = pix
            self.fade = 0.0
            self.fade_dur = 0.07 if walk_swap else 0.16
        self.custom = (pix is not self.S["base"]) or st == "move"

    # ---------------- main loop ----------------
    def tick(self):
        dt = min(self.clock.restart() / 1000.0, 0.05)
        if dt <= 0:
            return
        self.t += dt
        self.state_t += dt
        self.extra_lift = 0.0
        self.extra_rot = 0.0
        self.rate = 7.0
        self.breath_amp, self.breath_hz = 0.008, 0.45

        self.pick_pix()
        getattr(self, "st_" + self.state)(dt)

        k = 1 - math.exp(-self.rate * dt)
        for key in self.cur:
            self.cur[key] += (self.tgt[key] - self.cur[key]) * k
        self.flip_cur += (self.face - self.flip_cur) * (1 - math.exp(-18.0 * dt))
        self.breath = math.sin(self.t * 2 * math.pi * self.breath_hz) * self.breath_amp
        self.fade = min(1.0, self.fade + dt / self.fade_dur)

        if self.state not in ("held", "fall"):
            self.y = self.floor
        half = self.cw * 0.5
        self.x = clamp(self.x, self.geo.left() + half, self.geo.right() - half)
        self.reposition()
        self.update()

    def reposition(self):
        self.move(round(self.x - self.W / 2), round(self.y - self.anchor_y))

    # ---------------- drawing ----------------
    def draw_pix(self, p, pix, opacity):
        pw, ph = pix.width() / SS, pix.height() / SS
        p.setOpacity(opacity)
        p.drawPixmap(QRectF(-pw / 2, -ph, pw, ph), pix, QRectF(pix.rect()))
        p.setOpacity(1.0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        ax, ay = self.W / 2, self.anchor_y
        sx = self.cur["sx"] * (1 - self.breath * 0.4)
        sy = self.cur["sy"] * (1 + self.breath)

        if self.state not in ("held", "fall"):                      # soft ground shadow
            k = 1 - min(self.extra_lift / 90.0, 0.6)
            rx = self.cw * 0.36 * sx * k
            g = QRadialGradient(QPointF(0, 0), rx)
            g.setColorAt(0, QColor(0, 0, 0, 70))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.save()
            p.translate(ax, ay - 4)
            p.scale(1, 7.0 * k / rx)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(0, 0), rx, rx)
            p.restore()

        p.save()
        p.translate(ax, ay - self.extra_lift)
        p.rotate(self.cur["rot"] * self.face + self.cur["tilt"] + self.extra_rot)
        p.scale(self.flip_cur * sx, sy)
        if self.fade < 1.0 and self.prev_pix is not None:
            self.draw_pix(p, self.prev_pix, 1.0)
            self.draw_pix(p, self.pix, self.fade)
        else:
            self.draw_pix(p, self.pix, 1.0)
        p.restore()

        if self.state == "sleep":                                   # floating z's
            f = QFont("Segoe UI", 12)
            f.setBold(True)
            for i in range(3):
                ph_ = (self.t * 0.45 + i / 3.0) % 1.0
                f.setPointSizeF(9 + ph_ * 9)
                p.setFont(f)
                p.setPen(QColor(90, 105, 170, int(220 * math.sin(ph_ * math.pi))))
                zx = ax + self.face * self.cw * 0.28 + self.face * ph_ * 14
                zy = ay - self.ch * 0.55 - ph_ * 42
                p.drawText(QPointF(zx, zy), "z")
        p.end()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    cat = Cat()
    cat.show()
    sys.exit(app.exec())
