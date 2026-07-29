"""
Desktop Cat - a tiny shy pet that lives on your desktop.

Behavior:
- Rests/naps in a corner most of the time.
- Occasionally wanders a short distance on its own.
- When your mouse cursor gets close, it gets startled and skitters away.
- Drag it with left-click to place it wherever you like.
- Right-click for a Quit option.

Requirements:
    pip install pillow
(tkinter ships with the standard python.org Windows installer already)

Run it with:  python desktop_cat.py
No console window: pythonw desktop_cat.py
"""

import ctypes
import ctypes.wintypes
import math
import random
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

# ---------------------------------------------------------------------------
# Config - tweak these to change how the cat looks/behaves
# ---------------------------------------------------------------------------
SPRITE_SIZE = 100              # pixel size of the cat on screen
TRANSPARENT_COLOR = "magenta"  # background color that becomes invisible
TICK_MS = 120                  # how often the brain "thinks" (ms)

SHY_RADIUS = 140               # cursor distance (px) that startles the cat
FLEE_SPEED = 14                # px per tick while fleeing
WANDER_SPEED = 4               # px per tick while casually wandering
WANDER_CHANCE = 0.01           # chance per tick to start a short wander
WANDER_STEPS = 18              # how many ticks a wander lasts
NAP_CHANCE = 0.004             # chance per tick to fall asleep
NAP_TICKS = 40                 # how many ticks a nap lasts
BLINK_CHANCE = 0.05            # chance per tick to blink while idle


# ---------------------------------------------------------------------------
# Sprite drawing (Pillow) - simple siamese-style chibi cat, several poses
# ---------------------------------------------------------------------------
def draw_cat(pose="idle"):
    S = 4  # supersample factor for smooth anti-aliased edges
    W = H = 100 * S
    img = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)

    cream = (245, 230, 210, 255)
    dark = (74, 52, 40, 255)
    blue = (74, 144, 217, 255)
    pink = (230, 150, 160, 255)
    outline = (40, 30, 25, 255)
    cx, cy = W // 2, H // 2

    # tail, body, head, ears, paws
    d.ellipse([cx + 18 * S, cy + 2 * S, cx + 34 * S, cy + 30 * S], fill=dark, outline=outline, width=2 * S)
    d.ellipse([cx - 28 * S, cy - 6 * S, cx + 28 * S, cy + 38 * S], fill=cream, outline=outline, width=3 * S)
    d.ellipse([cx - 24 * S, cy - 38 * S, cx + 24 * S, cy + 8 * S], fill=cream, outline=outline, width=3 * S)
    d.polygon([(cx - 22 * S, cy - 24 * S), (cx - 26 * S, cy - 46 * S), (cx - 6 * S, cy - 34 * S)], fill=dark, outline=outline)
    d.polygon([(cx + 22 * S, cy - 24 * S), (cx + 26 * S, cy - 46 * S), (cx + 6 * S, cy - 34 * S)], fill=dark, outline=outline)
    d.ellipse([cx - 16 * S, cy + 26 * S, cx - 2 * S, cy + 40 * S], fill=cream, outline=outline, width=2 * S)
    d.ellipse([cx + 2 * S, cy + 26 * S, cx + 16 * S, cy + 40 * S], fill=cream, outline=outline, width=2 * S)

    if pose == "sleep":
        d.arc([cx - 16 * S, cy - 22 * S, cx - 2 * S, cy - 10 * S], start=200, end=340, fill=outline, width=2 * S)
        d.arc([cx + 2 * S, cy - 22 * S, cx + 16 * S, cy - 10 * S], start=200, end=340, fill=outline, width=2 * S)
    elif pose == "blink":
        d.line([cx - 14 * S, cy - 16 * S, cx - 2 * S, cy - 16 * S], fill=outline, width=2 * S)
        d.line([cx + 2 * S, cy - 16 * S, cx + 14 * S, cy - 16 * S], fill=outline, width=2 * S)
    elif pose in ("startled", "fleeing"):
        d.ellipse([cx - 16 * S, cy - 24 * S, cx - 2 * S, cy - 8 * S], fill=(255, 255, 255, 255), outline=outline, width=2 * S)
        d.ellipse([cx + 2 * S, cy - 24 * S, cx + 16 * S, cy - 8 * S], fill=(255, 255, 255, 255), outline=outline, width=2 * S)
        d.ellipse([cx - 11 * S, cy - 19 * S, cx - 5 * S, cy - 13 * S], fill=outline)
        d.ellipse([cx + 5 * S, cy - 19 * S, cx + 11 * S, cy - 13 * S], fill=outline)
        d.ellipse([cx - 3 * S, cy - 4 * S, cx + 3 * S, cy + 4 * S], fill=outline)
    else:  # idle
        d.ellipse([cx - 15 * S, cy - 23 * S, cx - 3 * S, cy - 9 * S], fill=(255, 255, 255, 255), outline=outline, width=2 * S)
        d.ellipse([cx + 3 * S, cy - 23 * S, cx + 15 * S, cy - 9 * S], fill=(255, 255, 255, 255), outline=outline, width=2 * S)
        d.ellipse([cx - 11 * S, cy - 19 * S, cx - 6 * S, cy - 12 * S], fill=blue)
        d.ellipse([cx + 6 * S, cy - 19 * S, cx + 11 * S, cy - 12 * S], fill=blue)
        d.ellipse([cx - 9 * S, cy - 17 * S, cx - 6 * S, cy - 13 * S], fill=outline)
        d.ellipse([cx + 6 * S, cy - 17 * S, cx + 9 * S, cy - 13 * S], fill=outline)

    d.polygon([(cx - 3 * S, cy - 6 * S), (cx + 3 * S, cy - 6 * S), (cx, cy - 1 * S)], fill=pink, outline=outline)
    d.arc([cx - 8 * S, cy - 4 * S, cx, cy + 6 * S], start=20, end=160, fill=outline, width=2 * S)
    d.arc([cx, cy - 4 * S, cx + 8 * S, cy + 6 * S], start=20, end=160, fill=outline, width=2 * S)

    return img.resize((SPRITE_SIZE, SPRITE_SIZE), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Cursor position via Windows API (no extra dependency beyond Pillow)
# ---------------------------------------------------------------------------
def get_cursor_pos():
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class DesktopCat:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)           # no title bar/border
        self.root.attributes("-topmost", True)      # always on top
        self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.root.configure(bg=TRANSPARENT_COLOR)

        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        self.size = SPRITE_SIZE
        # start resting in the bottom-right corner, like on a desktop
        self.x = self.screen_w - self.size - 60
        self.y = self.screen_h - self.size - 90

        # pre-render every pose once so the loop just swaps images
        self.sprites = {
            pose: ImageTk.PhotoImage(draw_cat(pose))
            for pose in ("idle", "blink", "sleep", "startled", "fleeing")
        }

        self.label = tk.Label(self.root, image=self.sprites["idle"], bg=TRANSPARENT_COLOR, bd=0)
        self.label.pack()

        self.root.geometry(f"{self.size}x{self.size}+{int(self.x)}+{int(self.y)}")

        self.label.bind("<ButtonPress-1>", self.start_drag)
        self.label.bind("<B1-Motion>", self.do_drag)
        self.label.bind("<Button-3>", self.show_menu)

        self._drag_offset = (0, 0)
        self.state = "idle"
        self.state_timer = 0
        self.wander_dir = (0, 0)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Quit", command=self.root.destroy)

        self.tick()

    # -- dragging -----------------------------------------------------
    def start_drag(self, event):
        self._drag_offset = (event.x, event.y)
        self.state = "idle"
        self.state_timer = 0

    def do_drag(self, event):
        ox, oy = self._drag_offset
        self.x = self.root.winfo_pointerx() - ox
        self.y = self.root.winfo_pointery() - oy
        self._move_to(self.x, self.y)

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    # -- helpers --------------------------------------------------------
    def _move_to(self, x, y):
        x = int(max(0, min(self.screen_w - self.size, x)))
        y = int(max(0, min(self.screen_h - self.size, y)))
        self.x, self.y = x, y
        self.root.geometry(f"+{x}+{y}")

    def _center(self):
        return self.x + self.size / 2, self.y + self.size / 2

    def _set_pose(self, pose):
        self.label.config(image=self.sprites[pose])

    # -- main brain loop --------------------------------------------------
    def tick(self):
        try:
            cx, cy = get_cursor_pos()
        except Exception:
            cx, cy = -9999, -9999

        pet_cx, pet_cy = self._center()
        dx, dy = pet_cx - cx, pet_cy - cy
        dist = math.hypot(dx, dy)

        if dist < SHY_RADIUS:
            self.state = "fleeing"
            self.state_timer = 6  # keeps fleeing a few ticks after cursor leaves range
        elif self.state == "fleeing":
            self.state_timer -= 1
            if self.state_timer <= 0:
                self.state = "startled"
                self.state_timer = 5

        if self.state == "fleeing":
            if dist > 0:
                nx, ny = dx / dist, dy / dist
            else:
                nx, ny = random.uniform(-1, 1), random.uniform(-1, 1)
            self._move_to(self.x + nx * FLEE_SPEED, self.y + ny * FLEE_SPEED)
            self._set_pose("fleeing")

        elif self.state == "startled":
            self._set_pose("startled")
            self.state_timer -= 1
            if self.state_timer <= 0:
                self.state = "idle"

        elif self.state == "wander":
            wx, wy = self.wander_dir
            self._move_to(self.x + wx * WANDER_SPEED, self.y + wy * WANDER_SPEED)
            self._set_pose("idle")
            self.state_timer -= 1
            if self.state_timer <= 0:
                self.state = "idle"

        elif self.state == "nap":
            self._set_pose("sleep")
            self.state_timer -= 1
            if self.state_timer <= 0:
                self.state = "idle"

        else:  # idle
            if random.random() < NAP_CHANCE:
                self.state = "nap"
                self.state_timer = NAP_TICKS
            elif random.random() < WANDER_CHANCE:
                self.state = "wander"
                self.state_timer = WANDER_STEPS
                angle = random.uniform(0, 2 * math.pi)
                self.wander_dir = (math.cos(angle), math.sin(angle))
            elif random.random() < BLINK_CHANCE:
                self._set_pose("blink")
            else:
                self._set_pose("idle")

        self.root.after(TICK_MS, self.tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    DesktopCat().run()