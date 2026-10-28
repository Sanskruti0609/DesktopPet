# DesktopPet

A small gray-and-white kitten that lives on your desktop. She walks, crawls, rests in a corner,
sleeps, stretches, reacts to your mouse, and sometimes follows your cursor.
She stays out of your way: clicks pass through her, and she hides during fullscreen apps.

## Run

```
pip install -r requirements.txt
python desktop_cat.py        # or: pythonw desktop_cat.py  (no console window)
```

Keep the `assets/` folder next to `desktop_cat.py`. Quit from the tray icon or by right-clicking her.

## What she does

| You do                                            | She does                                                                                                                                              |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Nothing                                           | Walks / crawls around, rests in a corner, falls asleep, wakes up, stretches, repeats. Sleeps longer at night.                                         |
| Hover over her while she sleeps                   | Wakes up grumpy (angry eyes, shaking, "Grr!"), then goes back to sleep once you leave. Bug her for 6+ seconds and she stomps off to the other corner. |
| Move the cursor slowly over her while she's awake | Purrs with floating hearts, and may nap happily under your cursor.                                                                                    |
| Click                                             | Happy hop                                                                                                                                             |
| Drag and release                                  | Picks her up (legs dangle), she drops and lands                                                                                                       |
| Nothing, for a while                              | Sometimes wanders over to sit near your cursor                                                                                                        |
| Right-click / tray icon                           | Menu: Rest, Walk, Crawl, Stretch, Sleep, toggles, Quit                                                                                                |

### Menu options (saved between runs)

- **Sometimes sit near my cursor**
- **Speech bubbles**
- **Hide during fullscreen apps** (Windows)
- **Break reminder** every 45 minutes (off by default)

## Tweaking

Everything adjustable is in the CONFIG block at the top of `desktop_cat.py`:
size (`SPRITE_HEIGHT`), corner, speeds, leg speed (`WALK_CYCLE_PX`), sleep/rest times, night hours.

## Assets

`assets/` holds the kitten pictures. `walk_00..08` and `doze_0..5` are in-between frames generated
from your key poses (walk 1 / walk 2 and rest / sleep), `angry.png` is the rest pose with angry eyelids.
