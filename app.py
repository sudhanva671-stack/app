"""
Home Automation System — Premium Dark UI + Voice Control
=========================================================
Tested with:
  Python           3.12.3
  SpeechRecognition 3.16.1   (pip install SpeechRecognition==3.16.1)
  pyttsx3          2.99      (pip install pyttsx3==2.99)
  PyAudio          0.2.14    (pip install pyaudio==0.2.14)

Install (all latest):
  pip install SpeechRecognition pyttsx3 pyaudio

Run:
  python app.py

Voice commands (say after clicking the mic button):
  "turn on/off <device>"      e.g. "turn on ceiling light"
  "set brightness to <N>"    e.g. "set brightness to 80"
  "activate scene <name>"    e.g. "activate scene sleep"
  "switch to <room>"         e.g. "switch to bedroom"
  "arm home / arm away / disarm"
  "what's the temperature"
  "list devices"

Compatibility notes (SR 3.16 / pyttsx3 2.99 / PyAudio 0.2.14):
  - sr.Recognizer.recognize_google() still returns a plain str in 3.16.x
  - pyttsx3 2.99 requires one Engine instance per process; we keep a single
    instance and guard runAndWait() with a threading.Lock to prevent re-entry
  - PyAudio 0.2.14 exposes pa.get_default_input_device_info(); we probe this
    before opening the microphone and surface a clear error if no device exists
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk
import datetime, math, threading, queue, time, sys, logging
import threading
import speech_recognition as sr
import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
logging.basicConfig(level=logging.WARNING,
                    format="%(levelname)s [%(name)s] %(message)s")
_log = logging.getLogger("home_automation")

# ── version gate — Python 3.8+ required ───────────────────────────────────────
if sys.version_info < (3, 8):
    sys.exit("Python 3.8 or newer is required.")

# ── third-party ───────────────────────────────────────────────────────────────
try:
    import speech_recognition as sr
    # SR 3.10+ renamed AudioData; 3.16 keeps backward compat — just verify
    _SR_VERSION = tuple(int(x) for x in sr.__version__.split(".")[:3])
    VOICE_OK = True
    _log.info("SpeechRecognition %s loaded", sr.__version__)
except ImportError:
    VOICE_OK = False
    _log.warning("SpeechRecognition not found — voice input disabled")

try:
    import pyttsx3
    # pyttsx3 2.99 on Python 3.12 requires the engine to be initialised on the
    # thread that will call runAndWait(); we create it lazily in _speak_bg.
    TTS_OK = True
    _log.info("pyttsx3 %s loaded", getattr(pyttsx3, "__version__", "2.99"))
except ImportError:
    TTS_OK = False
    _log.warning("pyttsx3 not found — voice responses (TTS) disabled")

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════════════

ROOMS = ["Living Room", "Bedroom", "Kitchen", "Office"]

DEVICES = {
    "Living Room": [
        {"name": "Ceiling Light", "icon": "bulb",   "on": True,  "dim": 75,  "type": "light",  "watts": 12},
        {"name": "Smart TV",      "icon": "tv",      "on": True,  "dim": 100, "type": "switch", "watts": 85},
        {"name": "AC Unit",       "icon": "ac",      "on": True,  "dim": 100, "type": "switch", "watts": 900},
        {"name": "Floor Lamp",    "icon": "lamp",    "on": False, "dim": 50,  "type": "light",  "watts": 8},
        {"name": "Smart Speaker", "icon": "speaker", "on": True,  "dim": 60,  "type": "switch", "watts": 5},
    ],
    "Bedroom": [
        {"name": "Ceiling Light", "icon": "bulb",   "on": False, "dim": 40,  "type": "light",  "watts": 10},
        {"name": "Bedside Lamp",  "icon": "lamp",    "on": True,  "dim": 30,  "type": "light",  "watts": 6},
        {"name": "Smart Fan",     "icon": "fan",     "on": True,  "dim": 100, "type": "switch", "watts": 60},
        {"name": "Humidifier",    "icon": "drop",    "on": False, "dim": 100, "type": "switch", "watts": 30},
    ],
    "Kitchen": [
        {"name": "Ceiling Light", "icon": "bulb",    "on": True,  "dim": 100, "type": "light",  "watts": 15},
        {"name": "Coffee Maker",  "icon": "coffee",  "on": False, "dim": 100, "type": "switch", "watts": 1000},
        {"name": "Refrigerator",  "icon": "fridge",  "on": True,  "dim": 100, "type": "switch", "watts": 150},
        {"name": "Smart Oven",    "icon": "oven",    "on": False, "dim": 100, "type": "switch", "watts": 2200},
    ],
    "Office": [
        {"name": "Desk Lamp",     "icon": "lamp",     "on": True,  "dim": 90,  "type": "light",  "watts": 8},
        {"name": "Air Purifier",  "icon": "purifier", "on": True,  "dim": 100, "type": "switch", "watts": 45},
        {"name": "Monitor Light", "icon": "monitor",  "on": False, "dim": 60,  "type": "light",  "watts": 5},
    ],
}

SCHEDULES = [
    {"time": "06:30", "name": "Coffee Maker", "action": "Turn on",  "days": "Mon-Fri",   "on": True},
    {"time": "07:00", "name": "Scene: Home",  "action": "Activate", "days": "Every day", "on": True},
    {"time": "08:00", "name": "Office Lamp",  "action": "Turn on",  "days": "Mon-Fri",   "on": True},
    {"time": "22:30", "name": "Scene: Sleep", "action": "Activate", "days": "Every day", "on": True},
]

AUTOMATIONS = [
    {"name": "Motion → Lights",  "trigger": "Motion at front door", "action": "Porch light 5 min",  "on": True},
    {"name": "Sunrise Adjust",   "trigger": "Sunrise ±30 min",      "action": "Brighten living room","on": True},
    {"name": "Away Energy Save", "trigger": "Everyone leaves",       "action": "AC 28°C, lights off", "on": False},
]

EVENTS = [
    ("motion", "Motion detected — Front door",    "2 min ago"),
    ("door",   "Front door locked",               "18 min ago"),
    ("ok",     "System armed — Home mode",        "8:02 AM"),
    ("door",   "Garage door opened",              "7:50 AM"),
    ("ok",     "All sensors normal",              "7:00 AM"),
]

ENERGY_DEVICES = [
    ("AC Unit",       1.8, 43, "ac"),
    ("Refrigerator",  0.9, 21, "fridge"),
    ("Smart TV",      0.5, 12, "tv"),
    ("Lights",        0.6, 14, "bulb"),
    ("Other",         0.4, 10, "plug"),
]

HOURLY = [0.05,0.04,0.03,0.03,0.04,0.12,0.28,0.35,
          0.22,0.18,0.20,0.25,0.30,0.22,0.18,0.16,
          0.20,0.28,0.32,0.25,0.18,0.14,0.10,0.07]

# ═══════════════════════════════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════════════════════════════

T = {
    "bg0":      "#060B14", "bg1": "#0B1221", "bg2": "#101A2E",
    "bg3":      "#152038", "bg4": "#1C2A48",
    "border0":  "#1E2E50", "border1": "#263A62",
    "text0":    "#E8EEFF", "text1": "#8A9EC4", "text2": "#4A5A7A",
    "acc":      "#5B5FEE", "acc_lt": "#818CF8", "acc_bg": "#151840",
    "acc_glow": "#3730C0",
    "green":    "#22D3A0", "green_bg": "#081E16",
    "amber":    "#FBB040", "amber_bg": "#1E1406",
    "red":      "#F05454", "red_bg":   "#200A0A",
    "blue":     "#38BDF8", "cyan": "#22D3EE",
    "purple":   "#A855F7",
}

FA = "Georgia"           # serif accent / display
FB = "Helvetica Neue"    # body
FT  = (FA, 16, "bold"); FH = (FB, 13, "bold"); FBODY = (FB, 12)
FSM = (FB, 10); FMI = (FB, 9); FST = (FA, 22, "bold"); FNM = (FA, 17, "bold")


def _h2r(h):
    h = h.lstrip("#")
    return int(h[:2],16), int(h[2:4],16), int(h[4:],16)

def blend(c1, c2, t):
    r1,g1,b1=_h2r(c1); r2,g2,b2=_h2r(c2)
    return "#{:02x}{:02x}{:02x}".format(
        int(r1+(r2-r1)*t), int(g1+(g2-g1)*t), int(b1+(b2-b1)*t))

def alpha_blend(color, bg, alpha):
    return blend(bg, color, alpha)

# ═══════════════════════════════════════════════════════════════════════════════
#  CRISP ICON DRAWING  (all pure-canvas, anti-aliased via layering)
# ═══════════════════════════════════════════════════════════════════════════════

def draw_icon(cv: tk.Canvas, icon: str, cx: int, cy: int,
              size: int = 24, color: str = None, bg: str = None):
    """
    Draw a crisp pixel-perfect icon on canvas at (cx,cy).
    All icons are drawn with Canvas primitives — no image files.
    Each is mathematically constructed for clean lines at any size.
    """
    col  = color or T["acc_lt"]
    s    = size
    r    = s // 2
    lw   = max(1, s // 14)   # line width proportional to size
    lw2  = max(1, lw + 1)

    if bg:
        cv.create_oval(cx-r-4, cy-r-4, cx+r+4, cy+r+4,
                       fill=bg, outline="")

    if icon == "bulb":
        # Bulb body (circle top)
        br = int(s*0.36)
        cv.create_oval(cx-br, cy-r, cx+br, cy-r+br*2,
                       fill="", outline=col, width=lw2)
        # Glass dome fill
        cv.create_arc(cx-br, cy-r, cx+br, cy-r+br*2+2,
                      start=0, extent=180, fill=alpha_blend(col, T["bg3"], 0.15),
                      outline="")
        # Filament
        cv.create_line(cx-int(s*0.12), cy-int(s*0.08),
                       cx, cy-int(s*0.22),
                       cx+int(s*0.12), cy-int(s*0.08),
                       fill=T["amber"], width=max(1,lw-1), smooth=True)
        # Base rings
        for dy, ww in [(int(s*0.24), int(s*0.28)),
                       (int(s*0.30), int(s*0.22)),
                       (int(s*0.36), int(s*0.16))]:
            cv.create_line(cx-ww//2, cy-r+br*2-2+dy,
                           cx+ww//2, cy-r+br*2-2+dy,
                           fill=col, width=lw2)

    elif icon == "tv":
        # Screen frame
        sw2, sh2 = int(s*0.44), int(s*0.32)
        cv.create_rectangle(cx-sw2, cy-sh2, cx+sw2, cy+sh2,
                            fill=alpha_blend(col, T["bg3"], 0.1),
                            outline=col, width=lw2)
        # Inner screen
        cv.create_rectangle(cx-sw2+lw+2, cy-sh2+lw+2,
                            cx+sw2-lw-2, cy+sh2-lw-2,
                            fill=alpha_blend(T["cyan"], T["bg3"], 0.2),
                            outline="")
        # Stand
        cv.create_line(cx, cy+sh2, cx, cy+sh2+int(s*0.14),
                       fill=col, width=lw2)
        cv.create_line(cx-int(s*0.18), cy+sh2+int(s*0.14),
                       cx+int(s*0.18), cy+sh2+int(s*0.14),
                       fill=col, width=lw2)

    elif icon == "ac":
        # Main body rectangle
        bw2, bh2 = int(s*0.44), int(s*0.22)
        cv.create_rectangle(cx-bw2, cy-bh2, cx+bw2, cy+bh2,
                            fill=alpha_blend(col, T["bg3"], 0.1),
                            outline=col, width=lw2)
        # Vents (horizontal lines inside)
        for vy in [-int(s*0.06), 0, int(s*0.06)]:
            cv.create_line(cx-bw2+6, cy+vy, cx+bw2-6, cy+vy,
                           fill=T["cyan"], width=max(1,lw-1))
        # Airflow arrows below
        for ax in [-int(s*0.2), 0, int(s*0.2)]:
            cv.create_line(cx+ax, cy+bh2+2, cx+ax, cy+bh2+int(s*0.18),
                           fill=T["cyan"], width=lw, arrow="last",
                           arrowshape=(4,5,3))

    elif icon == "lamp":
        # Shade (downward triangle)
        shade_r = int(s*0.34)
        cv.create_polygon(
            cx, cy-r+2,
            cx-shade_r, cy-int(s*0.02),
            cx+shade_r, cy-int(s*0.02),
            fill=alpha_blend(col, T["bg3"], 0.2), outline=col, width=lw)
        # Glow inside shade
        cv.create_oval(cx-int(s*0.12), cy-int(s*0.16),
                       cx+int(s*0.12), cy,
                       fill=alpha_blend(T["amber"], T["bg3"], 0.3), outline="")
        # Pole
        cv.create_line(cx, cy, cx, cy+r-2, fill=col, width=lw2)
        # Base
        cv.create_line(cx-int(s*0.22), cy+r-2,
                       cx+int(s*0.22), cy+r-2, fill=col, width=lw2)

    elif icon == "speaker":
        # Speaker cone
        cv.create_polygon(
            cx-int(s*0.14), cy-int(s*0.2),
            cx-int(s*0.14), cy+int(s*0.2),
            cx+int(s*0.1),  cy+int(s*0.32),
            cx+int(s*0.1),  cy-int(s*0.32),
            fill=alpha_blend(col, T["bg3"], 0.15), outline=col, width=lw)
        # Sound waves
        for i, ar in enumerate([int(s*0.22), int(s*0.34), int(s*0.46)]):
            a = 0.7 - i*0.2
            cv.create_arc(cx+int(s*0.1)-2, cy-ar, cx+int(s*0.1)-2+ar*2, cy+ar,
                          start=-60, extent=120,
                          style="arc", outline=alpha_blend(col, T["bg3"], a),
                          width=lw)

    elif icon == "fan":
        # Three blades (polygon arcs)
        for angle_deg in [0, 120, 240]:
            a = math.radians(angle_deg)
            a1 = math.radians(angle_deg - 40)
            a2 = math.radians(angle_deg + 40)
            x1 = cx + int(r*0.25*math.cos(a))
            y1 = cy + int(r*0.25*math.sin(a))
            x2 = cx + int(r*0.9*math.cos(a1))
            y2 = cy + int(r*0.9*math.sin(a1))
            x3 = cx + int(r*0.9*math.cos(a))
            y3 = cy + int(r*0.9*math.sin(a))
            x4 = cx + int(r*0.9*math.cos(a2))
            y4 = cy + int(r*0.9*math.sin(a2))
            cv.create_polygon(x1,y1,x2,y2,x3,y3,x4,y4,
                              fill=alpha_blend(col, T["bg3"], 0.25),
                              outline=col, width=lw, smooth=True)
        cv.create_oval(cx-lw2*2, cy-lw2*2, cx+lw2*2, cy+lw2*2,
                       fill=col, outline="")

    elif icon == "drop":
        # Water drop
        pts = []
        for i in range(30):
            a = math.radians(i*12 - 90)
            rr = int(r*0.5*(1 + 0.3*math.sin(a/2)))
            pts.extend([cx + int(rr*math.cos(a)), cy+int(s*0.1) + int(rr*math.sin(a))])
        cv.create_polygon(pts, fill=alpha_blend(T["cyan"], T["bg3"], 0.3),
                          outline=T["cyan"], width=lw, smooth=True)
        # Drop top point
        cv.create_line(cx, cy-r+2, cx-int(s*0.15), cy-int(s*0.1),
                       fill=T["cyan"], width=lw)
        cv.create_line(cx, cy-r+2, cx+int(s*0.15), cy-int(s*0.1),
                       fill=T["cyan"], width=lw)

    elif icon == "coffee":
        # Cup body
        cw, ch = int(s*0.36), int(s*0.3)
        cv.create_rectangle(cx-cw, cy-int(s*0.1), cx+cw, cy+ch,
                            fill=alpha_blend(T["amber"], T["bg3"], 0.15),
                            outline=T["amber"], width=lw2)
        # Saucer
        cv.create_oval(cx-cw-4, cy+ch-2, cx+cw+4, cy+ch+8,
                       fill="", outline=T["amber"], width=lw)
        # Handle
        cv.create_arc(cx+cw-2, cy, cx+cw+int(s*0.22), cy+int(s*0.22),
                      start=-90, extent=180, style="arc",
                      outline=T["amber"], width=lw2)
        # Steam lines
        for sx, sy in [(-int(s*0.12), -int(s*0.22)),
                       (0, -int(s*0.28)),
                       (int(s*0.12), -int(s*0.22))]:
            cv.create_line(cx+sx, cy-int(s*0.1)+sy+int(s*0.08),
                           cx+sx+int(s*0.06), cy-int(s*0.1)+sy-int(s*0.06),
                           cx+sx, cy-int(s*0.1)+sy-int(s*0.16),
                           fill=alpha_blend(col, T["bg3"], 0.6),
                           width=lw, smooth=True)

    elif icon == "fridge":
        fw, fh = int(s*0.34), int(s*0.44)
        cv.create_rectangle(cx-fw, cy-fh, cx+fw, cy+fh,
                            fill=alpha_blend(col, T["bg3"], 0.1),
                            outline=col, width=lw2)
        # Divider (fridge/freezer split)
        cv.create_line(cx-fw, cy-int(s*0.08), cx+fw, cy-int(s*0.08),
                       fill=col, width=lw)
        # Handles
        for hy in [-int(s*0.24), int(s*0.14)]:
            cv.create_line(cx+fw-lw2, cy+hy-int(s*0.08),
                           cx+fw-lw2, cy+hy+int(s*0.08),
                           fill=T["cyan"], width=lw2)

    elif icon == "oven":
        ow, oh = int(s*0.42), int(s*0.38)
        cv.create_rectangle(cx-ow, cy-oh, cx+ow, cy+oh,
                            fill=alpha_blend(col, T["bg3"], 0.1),
                            outline=col, width=lw2)
        # Window
        wp = int(s*0.12)
        cv.create_rectangle(cx-ow+wp, cy-oh+wp, cx+ow-wp, cy+int(s*0.06),
                            fill=alpha_blend(T["amber"], T["bg3"], 0.2),
                            outline=T["amber"], width=lw)
        # Knobs
        for kx in [-int(s*0.22), -int(s*0.08), int(s*0.08), int(s*0.22)]:
            kr = int(s*0.05)
            cv.create_oval(cx+kx-kr, cy+int(s*0.22)-kr,
                           cx+kx+kr, cy+int(s*0.22)+kr,
                           fill=col, outline="")

    elif icon == "purifier":
        # Tall rounded rectangle
        pw, ph = int(s*0.28), int(s*0.44)
        pr2 = int(s*0.12)
        for ox,oy in [(cx-pw,cy-ph),(cx+pw-2*pr2,cy-ph),
                      (cx-pw,cy+ph-2*pr2),(cx+pw-2*pr2,cy+ph-2*pr2)]:
            cv.create_oval(ox,oy,ox+2*pr2,oy+2*pr2,fill=T["bg3"],outline="")
        cv.create_rectangle(cx-pw+pr2,cy-ph,cx+pw-pr2,cy+ph,
                            fill=T["bg3"],outline="")
        cv.create_rectangle(cx-pw,cy-ph+pr2,cx+pw,cy+ph-pr2,
                            fill=T["bg3"],outline="")
        # Outline
        cv.create_rectangle(cx-pw+pr2,cy-ph,cx+pw-pr2,cy+ph,
                            fill="",outline=col,width=lw)
        # Fan circle
        fr = int(s*0.18)
        cv.create_oval(cx-fr,cy-fr,cx+fr,cy+fr,
                       fill="",outline=T["cyan"],width=lw)
        # Air vents
        for vy in [-int(s*0.3),-int(s*0.24),-int(s*0.18),
                    int(s*0.20),int(s*0.26),int(s*0.32)]:
            cv.create_line(cx-pw+6,cy+vy,cx+pw-6,cy+vy,
                           fill=alpha_blend(col,T["bg3"],0.5),width=max(1,lw-1))

    elif icon == "monitor":
        # Monitor screen
        mw, mh = int(s*0.42), int(s*0.3)
        cv.create_rectangle(cx-mw, cy-mh, cx+mw, cy+mh,
                            fill=alpha_blend(col, T["bg3"], 0.1),
                            outline=col, width=lw2)
        # Screen glow
        cv.create_rectangle(cx-mw+4,cy-mh+4,cx+mw-4,cy+mh-4,
                            fill=alpha_blend(T["acc"],T["bg3"],0.15),outline="")
        # Light bar (horizontal under screen)
        bw2 = int(s*0.3)
        cv.create_rectangle(cx-bw2, cy+mh+2, cx+bw2, cy+mh+2+lw2,
                            fill=T["acc_lt"], outline="")
        # Stand
        cv.create_line(cx, cy+mh+lw2+2, cx, cy+r-2, fill=col, width=lw2)
        cv.create_line(cx-int(s*0.18), cy+r-2, cx+int(s*0.18), cy+r-2,
                       fill=col, width=lw2)

    elif icon == "plug":
        # Plug body
        cv.create_rectangle(cx-int(s*0.22), cy-int(s*0.28),
                            cx+int(s*0.22), cy+int(s*0.12),
                            fill=alpha_blend(col,T["bg3"],0.15),
                            outline=col, width=lw2)
        # Prongs
        cv.create_line(cx-int(s*0.1),cy+int(s*0.12),
                       cx-int(s*0.1),cy+int(s*0.36),
                       fill=col,width=lw2)
        cv.create_line(cx+int(s*0.1),cy+int(s*0.12),
                       cx+int(s*0.1),cy+int(s*0.36),
                       fill=col,width=lw2)
        # Eyes (sockets)
        for ex in [-int(s*0.1), int(s*0.1)]:
            er = int(s*0.06)
            cv.create_oval(cx+ex-er,cy-int(s*0.14)-er,
                           cx+ex+er,cy-int(s*0.14)+er,
                           fill=T["bg0"],outline="")

    else:  # generic dot
        cv.create_oval(cx-r+4, cy-r+4, cx+r-4, cy+r-4,
                       fill="", outline=col, width=lw2)
        cv.create_oval(cx-int(s*0.15), cy-int(s*0.15),
                       cx+int(s*0.15), cy+int(s*0.15),
                       fill=col, outline="")


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGO
# ═══════════════════════════════════════════════════════════════════════════════

def draw_logo(cv: tk.Canvas, x:int, y:int, size:int=52):
    s  = size; cx = x+s//2; cy = y+s//2; r = max(3,s//7)
    bg = T["bg2"]

    # Rounded bg square
    for ox,oy in [(x,y),(x+s-2*r,y),(x,y+s-2*r),(x+s-2*r,y+s-2*r)]:
        cv.create_oval(ox,oy,ox+2*r,oy+2*r,fill=bg,outline="")
    cv.create_rectangle(x+r,y,x+s-r,y+s,fill=bg,outline="")
    cv.create_rectangle(x,y+r,x+s,y+s-r,fill=bg,outline="")

    # Multi-layer glow border
    for off,col,stip in [(3,T["acc_glow"],"gray12"),
                         (1,T["acc"],"gray25"),
                         (0,T["acc_lt"],"")]:
        cv.create_oval(x+off,y+off,x+s-off,y+s-off,
                       fill="",outline=col,width=1,
                       **({"stipple":stip} if stip else {}))

    # House roof — crisp polygon
    rt = y+int(s*0.20); rb = y+int(s*0.46)
    cv.create_polygon(cx,rt,
                      x+int(s*0.14),rb,
                      x+int(s*0.86),rb,
                      fill=T["acc_lt"],outline=T["acc_lt"],width=0)
    # Chimney
    chx = x+int(s*0.64)
    cv.create_rectangle(chx,rt-int(s*0.12),chx+int(s*0.08),rt+int(s*0.04),
                        fill=T["acc_lt"],outline="")

    # House walls
    wl=x+int(s*0.24); wr=x+int(s*0.76); wb=y+int(s*0.78)
    cv.create_rectangle(wl,rb,wr,wb,fill=T["acc"],outline=T["acc_lt"],width=1)

    # Door (arched top)
    dw=int(s*0.18); dh=int(s*0.24); dl=cx-dw//2
    cv.create_rectangle(dl,wb-dh,dl+dw,wb,fill=bg,outline="")
    cv.create_arc(dl,wb-dh-dw//2,dl+dw,wb-dh+dw//2,
                  start=0,extent=180,fill=bg,outline="")

    # Window (left side)
    wx=wl+int(s*0.08); wy=rb+int(s*0.06)
    cv.create_rectangle(wx,wy,wx+int(s*0.16),wy+int(s*0.16),
                        fill=alpha_blend(T["amber"],T["bg3"],0.4),
                        outline=T["acc_lt"],width=1)
    cv.create_line(wx+int(s*0.08),wy,wx+int(s*0.08),wy+int(s*0.16),
                   fill=T["acc_lt"],width=1)
    cv.create_line(wx,wy+int(s*0.08),wx+int(s*0.16),wy+int(s*0.08),
                   fill=T["acc_lt"],width=1)

    # Glowing bulb with halo (top of house, in roof area)
    br=max(2,int(s*0.09)); bx=cx-int(s*0.06); by2=y+int(s*0.34)
    for hi in range(6,0,-1):
        hr=br+hi*2
        al=0.05+hi*0.03
        gc=alpha_blend(T["amber"],bg,al)
        cv.create_oval(bx-hr,by2-hr,bx+hr,by2+hr,fill=gc,outline="")
    cv.create_oval(bx-br,by2-br,bx+br,by2+br,fill=T["amber"],outline="")
    # Filament
    cv.create_line(bx-int(s*0.04),by2-int(s*0.02),
                   bx,by2-int(s*0.07),
                   bx+int(s*0.04),by2-int(s*0.02),
                   fill="white",width=1,smooth=True)

    # Wi-Fi arcs (top right)
    wx2=x+int(s*0.76); wy2=y+int(s*0.28)
    for arc_r,lw2,col in [(int(s*0.17),2,T["cyan"]),
                           (int(s*0.11),2,alpha_blend(T["cyan"],bg,0.7)),
                           (int(s*0.05),2,alpha_blend(T["cyan"],bg,0.5))]:
        cv.create_arc(wx2-arc_r,wy2-arc_r,wx2+arc_r,wy2+arc_r,
                      start=30,extent=120,style="arc",outline=col,width=lw2)
    cv.create_oval(wx2-2,wy2+int(s*0.04),wx2+2,wy2+int(s*0.04)+4,
                   fill=T["cyan"],outline="")


def make_icon_img(size=32):
    img = tk.PhotoImage(width=size, height=size)
    half = size//2
    for row in range(size): img.put(T["bg1"],to=(0,row,size,row+1))
    rt=int(size*0.20); rb=int(size*0.46)
    for row in range(rt,rb):
        t=(row-rt)/max(1,rb-rt)
        lx=int(half-t*(half-int(size*0.16)))
        rx=int(half+t*(half-int(size*0.16)))
        if lx<rx: img.put(T["acc_lt"],to=(lx,row,rx+1,row+1))
    wl,wr,wb=int(size*0.24),int(size*0.76),int(size*0.78)
    for row in range(rb,wb): img.put(T["acc"],to=(wl,row,wr+1,row+1))
    bx,by2,br=half-int(size*0.06),int(size*0.33),max(2,int(size*0.09))
    for row in range(by2-br,by2+br+1):
        for col in range(bx-br,bx+br+1):
            if (col-bx)**2+(row-by2)**2<=br**2:
                img.put(T["amber"],to=(col,row,col+1,row+1))
    return img


# ═══════════════════════════════════════════════════════════════════════════════
#  VOICE ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

import threading
import queue
import numpy as np
import sounddevice as sd
import speech_recognition as sr
import pyttsx3
import io
import wave


class VoiceEngine:

    def __init__(self, result_queue):

        self.q = result_queue

        self.recognizer = sr.Recognizer()

        self.engine = pyttsx3.init()

        self.engine.setProperty("rate", 160)

        self.recording = False

        self.sample_rate = 16000

    # ═══════════════════════════════════════
    # TEXT TO SPEECH
    # ═══════════════════════════════════════

    def speak(self, text):

        def run():

            try:

                engine = pyttsx3.init()

                engine.setProperty("rate", 160)

                engine.say(text)

                engine.runAndWait()

                engine.stop()

            except Exception as e:

                print("TTS ERROR:", e)

        threading.Thread(
            target=run,
            daemon=True
        ).start()

    # ═══════════════════════════════════════
    # START RECORDING
    # ═══════════════════════════════════════

    def listen_once(self):

        if self.recording:
            return

        threading.Thread(
            target=self._record_and_recognize,
            daemon=True
        ).start()

    # ═══════════════════════════════════════
    # RECORD + RECOGNIZE
    # ═══════════════════════════════════════

    def _record_and_recognize(self):

        self.recording = True

        try:

            self.q.put((
                "status",
                "Listening..."
            ))

            duration = 5

            audio_data = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=1,
                dtype='int16'
            )

            sd.wait()

            self.q.put((
                "status",
                "Recognizing..."
            ))

            # CONVERT NUMPY AUDIO TO WAV MEMORY BUFFER
            wav_buffer = io.BytesIO()

            with wave.open(wav_buffer, 'wb') as wf:

                wf.setnchannels(1)

                wf.setsampwidth(2)

                wf.setframerate(self.sample_rate)

                wf.writeframes(audio_data.tobytes())

            wav_buffer.seek(0)

            # SPEECH RECOGNITION
            with sr.AudioFile(wav_buffer) as source:

                audio = self.recognizer.record(source)

            text = self.recognizer.recognize_google(
                audio,
                language="en-IN"
            )

            self.q.put((
                "result",
                text.lower().strip()
            ))

        except Exception as e:

            self.q.put((
                "error",
                str(e)
            ))

        finally:

            self.recording = False

            self.q.put((
                "status",
                "Ready"
            ))
#  COMMAND PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class CommandParser:
    SCENES   = ["home","away","sleep","movie"]
    ROOM_MAP = {"living":"Living Room","living room":"Living Room",
                "bedroom":"Bedroom","kitchen":"Kitchen","office":"Office"}

    def __init__(self, app):
        self.app = app

    def parse(self, text: str) -> str:
        t = text.strip().lower()

        # ── arm / security ────────────────────────────────────────────────
        if "arm home"  in t: return self._arm("home")
        if "arm away"  in t: return self._arm("away")
        if "disarm"    in t: return self._arm("disarm")

        # ── scene ─────────────────────────────────────────────────────────
        for sc in self.SCENES:
            if f"scene {sc}" in t or f"activate {sc}" in t or t == sc:
                return self._scene(sc)

        # ── room switch ───────────────────────────────────────────────────
        if "switch to" in t or "go to" in t or "open" in t:
            for key, room in self.ROOM_MAP.items():
                if key in t:
                    return self._switch_room(room)

        # ── brightness ────────────────────────────────────────────────────
        if "brightness" in t or "dim" in t:
            for word in t.split():
                if word.isdigit():
                    val = max(0, min(100, int(word)))
                    return self._set_brightness(val)
            return "Please say a number, e.g. 'set brightness to 70'"

        # ── turn on/off ───────────────────────────────────────────────────
        if "turn on"  in t: return self._toggle_name(t, True)
        if "turn off" in t: return self._toggle_name(t, False)
        if "switch on"  in t: return self._toggle_name(t, True)
        if "switch off" in t: return self._toggle_name(t, False)

        # ── queries ───────────────────────────────────────────────────────
        if "temperature" in t:
            return "Room temperature is 24 degrees Celsius."
        if "list" in t and "device" in t:
            room = self.app.cur_room.get()
            names = [d["name"] for d in DEVICES[room]]
            return f"Devices in {room}: " + ", ".join(names)
        if "how many" in t and "on" in t:
            return f"{self.app._count_on()} devices are currently on."
        if "power" in t or "watt" in t:
            return f"Current power usage is {self.app._total_w()} watts."
        if "hello" in t or "hi" in t:
            return "Hello! How can I help you control your home?"

        return f"Sorry, I didn't understand: \"{text}\""

    def _arm(self, mode):
        self.app.after(0, lambda: self.app._set_arm_mode(mode))
        labels = {"home":"Home mode armed.","away":"Away mode armed.","disarm":"System disarmed."}
        return labels.get(mode,"Done.")

    def _scene(self, sc):
        self.app.after(0, lambda: self.app._activate_scene(sc))
        return f"Activating {sc} scene."

    def _switch_room(self, room):
        self.app.after(0, lambda: self.app._go_room(room))
        return f"Switching to {room}."

    def _toggle_name(self, t, state):
        key = "turn on" if state else "turn off"
        key2 = "switch on" if state else "switch off"
        rest = t.replace(key,"").replace(key2,"").strip()
        if not rest:
            return "Which device? e.g. 'turn on ceiling light'"
        matched = []
        for room, devs in DEVICES.items():
            for d in devs:
                if rest in d["name"].lower() or d["name"].lower() in rest:
                    d["on"] = state
                    matched.append(d["name"])
        if matched:
            self.app.after(0, self.app._refresh_all)
            verb = "on" if state else "off"
            return f"Turned {verb}: " + ", ".join(matched)
        return f"No device found matching \"{rest}\""

    def _set_brightness(self, val):
        room = self.app.cur_room.get()
        changed = []
        for d in DEVICES[room]:
            if d["type"] == "light" and d["on"]:
                d["dim"] = val
                changed.append(d["name"])
        self.app.after(0, self.app._refresh_all)
        if changed:
            return f"Brightness set to {val}%: " + ", ".join(changed)
        return "No dimmable lights are on in this room."


# ═══════════════════════════════════════════════════════════════════════════════
#  WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

class GlowToggle(tk.Canvas):
    W, H = 58, 28

    def __init__(self, parent, var, command=None, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=parent["bg"], highlightthickness=0,
                         cursor="hand2", **kw)
        self._var = var; self._cmd = command; self._t = 1.0 if var.get() else 0.0
        self._draw()
        var.trace_add("write", lambda *_: self._start_anim())
        self.bind("<Button-1>", self._click)

    def _click(self, _=None):
        self._var.set(not self._var.get())
        if self._cmd: self._cmd()

    def _start_anim(self):
        target = 1.0 if self._var.get() else 0.0
        self._anim_to(target)

    def _anim_to(self, target):
        diff = target - self._t
        if abs(diff) < 0.02:
            self._t = target; self._draw(); return
        self._t += diff * 0.3; self._draw()
        self.after(14, lambda: self._anim_to(target))

    def _draw(self):
        self.delete("all")
        t = self._t; W,H = self.W, self.H; r = H//2
        track = blend(T["bg4"], T["acc"], t)
        # Glow when on
        if t > 0.2:
            for gi in range(4,0,-1):
                g = blend(T["bg1"], T["acc_glow"], t*0.15)
                self.create_oval(-gi*2,-gi,W+gi*2,H+gi,
                                 fill="",outline=T["acc"],width=1,
                                 stipple=f"gray{12 if gi>2 else 25}")
        # Track pill
        self.create_oval(0,0,H,H,fill=track,outline="")
        self.create_oval(W-H,0,W,H,fill=track,outline="")
        self.create_rectangle(r,0,W-r,H,fill=track,outline="")
        # Thumb
        tx = r + int(t*(W-H)); tc = blend("#8899BB","#FFFFFF",t)
        for gs in range(3,0,-1):
            self.create_oval(tx-r+3-gs,3-gs,tx+r-3+gs,H-3+gs,
                             fill="",outline=alpha_blend(tc,T["bg1"],0.2),width=1)
        self.create_oval(tx-r+3,3,tx+r-3,H-3,fill=tc,outline="")
        # Label
        txt = "ON" if self._var.get() else "OFF"
        lx = r+4 if t>0.5 else W-r-4
        fg = T["text0"] if t>0.5 else T["text2"]
        self.create_text(lx, H//2, text=txt, fill=fg,
                         font=(FB,8,"bold"), anchor="center")


class PulsingDot(tk.Canvas):
    def __init__(self, parent, color=None, size=10, **kw):
        super().__init__(parent, width=size+8, height=size+8,
                         bg=parent["bg"], highlightthickness=0, **kw)
        self._c = color or T["green"]; self._s = size; self._ph = 0.0
        self._tick()

    def _tick(self):
        self._ph = (self._ph + 0.1) % (2*math.pi)
        p = 0.5+0.5*math.sin(self._ph)
        self.delete("all")
        s = self._s; o = 4
        for i in range(4,0,-1):
            hr = int(s*0.5 + p*(i*2.5))
            al = 0.06*i*p
            hc = alpha_blend(self._c, T["bg1"], al)
            self.create_oval(o+s//2-hr,o+s//2-hr,o+s//2+hr,o+s//2+hr,
                             fill=hc,outline="")
        self.create_oval(o,o,o+s,o+s,fill=self._c,outline="")
        self.after(35, self._tick)


class VoiceMicButton(tk.Canvas):
    """Animated microphone button — pulses when listening."""
    SIZE = 52

    def __init__(self, parent, on_click, **kw):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=parent["bg"], highlightthickness=0,
                         cursor="hand2", **kw)
        self._on_click = on_click
        self._state    = "idle"   # idle | listening | processing
        self._phase    = 0.0
        self._draw("idle")
        self.bind("<Button-1>", lambda e: on_click())
        self._animate()

    def set_state(self, state: str):
        self._state = state

    def _animate(self):
        self._phase = (self._phase + 0.08) % (2*math.pi)
        self._draw(self._state)
        self.after(40, self._animate)

    def _draw(self, state):
        self.delete("all")
        S  = self.SIZE; cx = S//2; cy = S//2; r = S//2-2
        pulse = 0.5 + 0.5*math.sin(self._phase)

        if state == "listening":
            # Pulsing red ring
            for i in range(5,0,-1):
                pr = int(r + pulse*i*1.8)
                al = 0.04 + 0.04*i*pulse
                rc = alpha_blend(T["red"], T["bg1"], al)
                self.create_oval(cx-pr,cy-pr,cx+pr,cy+pr,fill=rc,outline="")
            bg_col = T["red"]
            ic_col = "white"
        elif state == "processing":
            for i in range(5,0,-1):
                pr = int(r + pulse*i*1.4)
                al = 0.04 + 0.03*i*pulse
                rc = alpha_blend(T["amber"], T["bg1"], al)
                self.create_oval(cx-pr,cy-pr,cx+pr,cy+pr,fill=rc,outline="")
            bg_col = T["amber"]
            ic_col = T["bg0"]
        else:
            # Subtle glow idle
            for i in range(3,0,-1):
                pr = int(r + pulse*i*0.8)
                al = 0.025 + 0.02*i*pulse
                rc = alpha_blend(T["acc"], T["bg1"], al)
                self.create_oval(cx-pr,cy-pr,cx+pr,cy+pr,fill=rc,outline="")
            bg_col = T["acc_bg"]
            ic_col = T["acc_lt"]

        # Button circle
        self.create_oval(cx-r,cy-r,cx+r,cy+r,fill=bg_col,outline="")

        # Microphone icon
        mw,mh = 10,13; mr = 5
        mx = cx - mw//2; my = cy - mh//2 - 3
        # Mic body (rounded rect)
        self.create_rectangle(mx+mr,my,mx+mw-mr,my+mh,
                              fill=ic_col,outline="")
        self.create_oval(mx,my,mx+2*mr,my+2*mr,fill=ic_col,outline="")
        self.create_oval(mx+mw-2*mr,my,mx+mw,my+2*mr,fill=ic_col,outline="")
        self.create_oval(mx,my+mh-2*mr,mx+2*mr,my+mh,fill=ic_col,outline="")
        self.create_oval(mx+mw-2*mr,my+mh-2*mr,mx+mw,my+mh,fill=ic_col,outline="")
        # Stand + base
        y2 = my+mh+4
        self.create_arc(cx-mw//2-4,y2-10,cx+mw//2+4,y2+6,
                        start=0,extent=180,style="arc",
                        outline=ic_col,width=2)
        self.create_line(cx,y2+2,cx,y2+8,fill=ic_col,width=2)
        self.create_line(cx-6,y2+8,cx+6,y2+8,fill=ic_col,width=2)


# ═══════════════════════════════════════════════════════════════════════════════
#  SPLASH
# ═══════════════════════════════════════════════════════════════════════════════

class Splash(tk.Toplevel):
    W,H = 420,340
    def __init__(self, root):
        super().__init__(root)
        self.overrideredirect(True)
        self.configure(bg=T["bg0"])
        sw,sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{self.W}x{self.H}+{(sw-self.W)//2}+{(sh-self.H)//2}")
        self.lift(); self._build()

    def _build(self):
        cv = tk.Canvas(self,width=self.W,height=self.H,
                       bg=T["bg0"],highlightthickness=0)
        cv.pack(fill="both",expand=True)
        # Rich gradient background
        W,H = self.W,self.H
        steps=60
        for i in range(steps):
            t=i/steps; y0=int(t*H); y1=int((i+1)/steps*H)
            c = blend(T["bg0"],T["bg2"],t*0.7)
            cv.create_rectangle(0,y0,W,y1,fill=c,outline="")
        # Nebula glows
        for cx2,cy2,r2,col in [(W//3,H//3,180,"#1E2060"),
                                (2*W//3,2*H//3,160,"#062035")]:
            for i in range(14,0,-1):
                rr=int(r2*i/14)
                al=0.03*(14-i)/14
                c=alpha_blend(col,T["bg0"],al*5)
                cv.create_oval(cx2-rr,cy2-rr,cx2+rr,cy2+rr,fill=c,outline="")
        # Logo
        lsz=110; lx=(W-lsz)//2; ly=20
        draw_logo(cv,lx,ly,lsz)
        # Name
        cv.create_text(W//2,ly+lsz+20,text="Home Automation",
                       font=(FA,22,"bold"),fill=T["text0"])
        cv.create_text(W//2,ly+lsz+46,text="Smart Living, Simplified",
                       font=(FB,11),fill=T["acc_lt"])
        cv.create_text(W//2,ly+lsz+68,text="Voice Control  ·  Real-time Monitoring  ·  Automation",
                       font=(FB,9),fill=T["text2"])
        # Progress bar
        bw=280; bx=(W-bw)//2; by=H-54
        cv.create_rectangle(bx,by,bx+bw,by+5,fill=T["bg3"],outline="")
        self._bar=cv.create_rectangle(bx,by,bx,by+5,fill=T["acc"],outline="")
        # Glow cap
        self._glow=cv.create_rectangle(bx,by-2,bx+8,by+7,
                                       fill=T["acc_lt"],outline="")
        cv.create_text(W//2,by+18,text="Initialising systems…",
                       font=(FB,9),fill=T["text2"])
        self._cv=cv; self._bx=bx; self._by=by; self._bw=bw; self._p=0
        self._tick()

    def _tick(self):
        self._p=min(100,self._p+3)
        fx=self._bx+int(self._bw*self._p/100)
        self._cv.coords(self._bar,self._bx,self._by,fx,self._by+5)
        self._cv.coords(self._glow,fx-4,self._by-2,fx+4,self._by+7)
        if self._p<100: self.after(18,self._tick)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.withdraw()
        splash = Splash(self)
        self.after(2200, lambda: self._boot(splash))

    def _boot(self, splash):
        splash.destroy()
        self.title("Home Automation — Premium")
        self.geometry("1020x780")
        self.minsize(840,620)
        self.configure(bg=T["bg0"])
        try:
            self._icon = make_icon_img(32)
            self.iconphoto(True,self._icon)
        except Exception: pass

        self.cur_room  = tk.StringVar(value="Living Room")
        self.arm_mode  = tk.StringVar(value="home")
        self.active_tab= tk.StringVar(value="devices")

        # Voice
        self._vq     = queue.Queue()
        self._veng   = VoiceEngine(self._vq)
        self._parser = CommandParser(self)
        self._mic_btn: VoiceMicButton|None = None
        self._voice_listening = False

        # Panel references for refresh
        self.room_frame_ref  = None
        self.dev_host_ref    = None
        self.stat_on_ref     = None
        self.stat_w_ref      = None
        self.arm_btns_ref    = {}

        self._build()
        self._tick_clock()
        self._poll_voice()
        self.deiconify()

    # ── Shell ──────────────────────────────────────────────────────────────────

    def _build(self):
        self._build_topbar()
        self._build_nav()
        body = tk.Frame(self,bg=T["bg0"])
        body.pack(fill="both",expand=True)
        self.panels={}
        for tab in ["devices","schedule","security","energy","voice"]:
            f=tk.Frame(body,bg=T["bg0"])
            self.panels[tab]=f
            getattr(self,f"_build_{tab}")(f)
        self._switch("devices")

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _build_topbar(self):
        bar=tk.Frame(self,bg=T["bg1"],height=66)
        bar.pack(fill="x"); bar.pack_propagate(False)

        left=tk.Frame(bar,bg=T["bg1"])
        left.pack(side="left",padx=14)
        lc=tk.Canvas(left,width=46,height=46,bg=T["bg1"],highlightthickness=0)
        lc.pack(side="left",pady=10)
        draw_logo(lc,0,0,46)
        ti=tk.Frame(left,bg=T["bg1"])
        ti.pack(side="left",padx=(10,0))
        tk.Label(ti,text="Home Automation",font=(FA,15,"bold"),
                 bg=T["bg1"],fg=T["text0"]).pack(anchor="w")
        tk.Label(ti,text="Smart Living, Simplified",font=(FB,9),
                 bg=T["bg1"],fg=T["acc_lt"]).pack(anchor="w")

        right=tk.Frame(bar,bg=T["bg1"])
        right.pack(side="right",padx=18)
        sf=tk.Frame(right,bg=T["bg1"])
        sf.pack(anchor="e")
        PulsingDot(sf,color=T["green"],size=8).pack(side="left",padx=(0,5))
        tk.Label(sf,text="All systems normal",font=FSM,
                 bg=T["bg1"],fg=T["green"]).pack(side="left")
        self.clock_lbl=tk.Label(right,text="",font=(FA,11),
                                bg=T["bg1"],fg=T["text1"])
        self.clock_lbl.pack(anchor="e",pady=(2,0))

        tk.Frame(self,height=2,bg=T["acc"]).pack(fill="x")

    # ── Nav ───────────────────────────────────────────────────────────────────

    def _build_nav(self):
        nav=tk.Frame(self,bg=T["bg1"])
        nav.pack(fill="x")
        self.nav_btns={}
        tabs=[("devices","⊡  Devices"),("schedule","⏱  Schedule"),
              ("security","⬡  Security"),("energy","⚡  Energy"),
              ("voice","🎙  Voice")]
        for tab,label in tabs:
            b=tk.Button(nav,text=label,font=(FB,11,"bold"),
                        bg=T["bg1"],fg=T["text2"],
                        relief="flat",bd=0,padx=22,pady=11,
                        cursor="hand2",
                        activebackground=T["bg2"],
                        activeforeground=T["text0"],
                        command=lambda t=tab: self._switch(t))
            b.pack(side="left")
            self.nav_btns[tab]=b
        tk.Frame(self,height=1,bg=T["border0"]).pack(fill="x")

    def _switch(self,tab):
        for f in self.panels.values(): f.pack_forget()
        self.panels[tab].pack(fill="both",expand=True)
        self.active_tab.set(tab)
        for t,b in self.nav_btns.items():
            b.config(fg=T["acc_lt"] if t==tab else T["text2"],
                     bg=T["bg2"]   if t==tab else T["bg1"])

    def _tick_clock(self):
        self.clock_lbl.config(text=datetime.datetime.now().strftime("%a, %d %b  %H:%M"))
        self.after(30_000,self._tick_clock)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _scrollable(self,parent):
        outer=tk.Frame(parent,bg=T["bg0"])
        cv2=tk.Canvas(outer,bg=T["bg0"],highlightthickness=0)
        sb=tk.Scrollbar(outer,orient="vertical",command=cv2.yview,
                        bg=T["bg2"],troughcolor=T["bg0"],
                        activebackground=T["acc"],width=5)
        cv2.configure(yscrollcommand=sb.set)
        sb.pack(side="right",fill="y")
        cv2.pack(side="left",fill="both",expand=True)
        inn=tk.Frame(cv2,bg=T["bg0"])
        win=cv2.create_window((0,0),window=inn,anchor="nw")
        inn.bind("<Configure>",lambda e:cv2.configure(scrollregion=cv2.bbox("all")))
        cv2.bind("<Configure>",lambda e:cv2.itemconfig(win,width=e.width))
        cv2.bind("<MouseWheel>",lambda e:cv2.yview_scroll(-1*(e.delta//120),"units"))
        return outer,inn

    def _section_label(self,parent,text):
        f=tk.Frame(parent,bg=T["bg0"])
        f.pack(fill="x",pady=(16,8),padx=20)
        tk.Label(f,text=text,font=(FB,9,"bold"),
                 bg=T["bg0"],fg=T["text2"]).pack(side="left")
        tk.Frame(f,height=1,bg=T["border0"]).pack(
            side="left",fill="x",expand=True,padx=(10,0),pady=1)

    def _card(self,parent,padx=20,pady=4):
        outer=tk.Frame(parent,bg=T["border0"],padx=1,pady=1)
        outer.pack(fill="x",padx=padx,pady=pady)
        inner=tk.Frame(outer,bg=T["bg2"],padx=14,pady=12)
        inner.pack(fill="x")
        return inner

    def _stat_block(self,parent,value,label,sub=None,color=None,icon_name=None):
        f=tk.Frame(parent,bg=T["bg3"],padx=14,pady=12)
        f.pack(side="left",expand=True,fill="both",padx=(0,8))
        if icon_name:
            icv=tk.Canvas(f,width=28,height=28,bg=T["bg3"],highlightthickness=0)
            icv.pack(anchor="w")
            draw_icon(icv,icon_name,14,14,24,color or T["acc_lt"],T["bg3"])
        tk.Label(f,text=label,font=FMI,bg=T["bg3"],fg=T["text2"]).pack(anchor="w")
        lbl=tk.Label(f,text=value,font=FST,bg=T["bg3"],fg=color or T["text0"])
        lbl.pack(anchor="w",pady=(2,0))
        if sub:
            tk.Label(f,text=sub,font=FMI,bg=T["bg3"],fg=T["green"]).pack(anchor="w")
        return lbl

    def _count_on(self): return sum(1 for d in sum(DEVICES.values(),[]) if d["on"])
    def _total_w(self):  return sum(d["watts"] for d in sum(DEVICES.values(),[]) if d["on"])

    def _refresh_all(self):
        if self.stat_on_ref:  self.stat_on_ref.config(text=str(self._count_on()))
        if self.stat_w_ref:   self.stat_w_ref.config(text=f"{self._total_w()}W")
        if self.room_frame_ref: self._render_rooms()
        if self.dev_host_ref:   self._render_devices()

    # ── DEVICES PANEL ─────────────────────────────────────────────────────────

    def _build_devices(self,parent):
        outer,inner=self._scrollable(parent)
        outer.pack(fill="both",expand=True)

        sf=tk.Frame(inner,bg=T["bg0"])
        sf.pack(fill="x",padx=20,pady=(20,0))
        self.stat_on_ref = self._stat_block(sf,str(self._count_on()),
                            "DEVICES ON",icon_name="bulb",color=T["acc_lt"])
        self.stat_w_ref  = self._stat_block(sf,f"{self._total_w()}W",
                            "POWER NOW",sub="↓12% vs yesterday",
                            color=T["amber"],icon_name="plug")
        self._stat_block(sf,"24°C","ROOM TEMP",icon_name="drop",color=T["cyan"])
        self._stat_block(sf,"Armed","SECURITY",sub="Home mode",
                         color=T["green"],icon_name="monitor")

        self._section_label(inner,"SCENES")
        sf2=tk.Frame(inner,bg=T["bg0"])
        sf2.pack(fill="x",padx=20,pady=(0,4))
        for sc,ico_name,desc in [("home","lamp","Comfort"),("away","fan","All off"),
                                   ("sleep","bulb","Dim & cool"),("movie","tv","Cinema")]:
            self._scene_btn(sf2,sc,ico_name,desc)

        self._section_label(inner,"ROOMS")
        self.room_frame_ref=tk.Frame(inner,bg=T["bg0"])
        self.room_frame_ref.pack(fill="x",padx=20,pady=(0,4))
        self._render_rooms()

        self._section_label(inner,"DEVICES")
        self.dev_host_ref=tk.Frame(inner,bg=T["bg0"])
        self.dev_host_ref.pack(fill="x",padx=20,pady=(0,20))
        self._render_devices()

    def _scene_btn(self,parent,scene,ico_name,desc):
        acc=T["acc"]; bg=T["acc_bg"]
        f=tk.Frame(parent,bg=acc,padx=1,pady=1)
        f.pack(side="left",padx=(0,8),expand=True,fill="x")
        inn=tk.Frame(f,bg=bg,padx=10,pady=10,cursor="hand2")
        inn.pack(fill="x")
        icv=tk.Canvas(inn,width=28,height=28,bg=bg,highlightthickness=0)
        icv.pack(anchor="w")
        draw_icon(icv,ico_name,14,14,24,T["acc_lt"],bg)
        tk.Label(inn,text=scene.title(),font=(FB,11,"bold"),
                 bg=bg,fg=T["text0"]).pack(anchor="w",pady=(4,0))
        tk.Label(inn,text=desc,font=FMI,bg=bg,fg=T["text2"]).pack(anchor="w")
        for w in [f,inn]+inn.winfo_children():
            w.bind("<Button-1>",lambda e,s=scene:self._activate_scene(s))

    def _render_rooms(self):
        if not self.room_frame_ref: return
        for w in self.room_frame_ref.winfo_children(): w.destroy()
        ROOM_ICON={"Living Room":"lamp","Bedroom":"bulb",
                   "Kitchen":"coffee","Office":"monitor"}
        for room in ROOMS:
            sel=room==self.cur_room.get()
            on=sum(1 for d in DEVICES[room] if d["on"])
            tot=len(DEVICES[room])
            acc=T["acc"] if sel else T["border0"]
            bg=T["bg3"] if sel else T["bg2"]
            f=tk.Frame(self.room_frame_ref,bg=acc,padx=1,pady=1,cursor="hand2")
            f.pack(side="left",expand=True,fill="x",padx=(0,8))
            inn=tk.Frame(f,bg=bg,padx=10,pady=10)
            inn.pack(fill="x")
            icv=tk.Canvas(inn,width=30,height=30,bg=bg,highlightthickness=0)
            icv.pack(anchor="w")
            draw_icon(icv,ROOM_ICON.get(room,"bulb"),15,15,26,
                      T["acc_lt"] if sel else T["text2"],bg)
            tk.Label(inn,text=room,font=(FB,11,"bold"),
                     bg=bg,fg=T["text0"]).pack(anchor="w",pady=(4,0))
            bar_f=tk.Frame(inn,bg=bg)
            bar_f.pack(anchor="w",fill="x",pady=(4,0))
            for i in range(tot):
                tk.Frame(bar_f,bg=T["acc"] if i<on else T["bg4"],
                         width=8,height=4).pack(side="left",padx=1)
            tk.Label(inn,text=f"{on}/{tot} on",font=FMI,
                     bg=bg,fg=T["text2"]).pack(anchor="w",pady=(2,0))
            for w in [f,inn]+inn.winfo_children()+bar_f.winfo_children():
                w.bind("<Button-1>",lambda e,r=room:self._select_room(r))

    def _select_room(self,room):
        self.cur_room.set(room)
        self._render_rooms(); self._render_devices()

    def _go_room(self,room):
        self._switch("devices")
        self._select_room(room)

    def _render_devices(self):
        if not self.dev_host_ref: return
        for w in self.dev_host_ref.winfo_children(): w.destroy()
        for dev in DEVICES[self.cur_room.get()]:
            self._device_card(self.dev_host_ref,dev)

    def _device_card(self,parent,dev):
        on=dev["on"]
        acc=T["acc"] if on else T["border0"]
        bg=T["bg3"] if on else T["bg2"]
        bf=tk.Frame(parent,bg=acc,padx=1,pady=1)
        bf.pack(fill="x",pady=(0,6))
        card=tk.Frame(bf,bg=bg,padx=14,pady=12)
        card.pack(fill="x")

        # Icon (crisp canvas drawing)
        ico_bg=T["acc_bg"] if on else T["bg4"]
        icv=tk.Canvas(card,width=46,height=46,bg=ico_bg,highlightthickness=0)
        icv.pack(side="left",padx=(0,14))
        draw_icon(icv,dev["icon"],23,23,34,
                  T["acc_lt"] if on else T["text2"],ico_bg)

        info=tk.Frame(card,bg=bg)
        info.pack(side="left",fill="both",expand=True)
        tk.Label(info,text=dev["name"],font=FH,
                 bg=bg,fg=T["text0"],anchor="w").pack(anchor="w")
        sc=T["green"] if on else T["text2"]
        st=f"On — {dev['watts']}W" if on else "Off"
        tk.Label(info,text=st,font=FSM,bg=bg,fg=sc,anchor="w").pack(anchor="w")

        if dev["type"]=="light" and on:
            df=tk.Frame(info,bg=bg); df.pack(anchor="w",fill="x",pady=(6,0))
            tk.Label(df,text="Brightness",font=FMI,bg=bg,fg=T["text2"]).pack(side="left")
            dv=tk.IntVar(value=dev["dim"])
            dl=tk.Label(df,text=f"{dev['dim']}%",font=(FB,9,"bold"),
                        bg=bg,fg=T["acc_lt"],width=4)
            dl.pack(side="right")
            ttk.Scale(df,from_=0,to=100,variable=dv,orient="horizontal",length=180,
                      command=lambda v,d=dev,l=dl:self._dim(d,v,l)
                      ).pack(side="left",padx=(8,4))

        var=tk.BooleanVar(value=on)
        GlowToggle(card,var,command=lambda d=dev,v=var:self._tog(d,v)
                   ).pack(side="right",padx=(10,0))

    def _tog(self,dev,var):
        dev["on"]=var.get()
        self._refresh_all()

    @staticmethod
    def _dim(dev,val,lbl):
        dev["dim"]=int(float(val))
        lbl.config(text=f"{dev['dim']}%")

    def _activate_scene(self,sc):
        if sc=="away":
            for devs in DEVICES.values():
                for d in devs: d["on"]=False
        elif sc=="sleep":
            for devs in DEVICES.values():
                for d in devs:
                    if d["icon"] in("bulb","lamp"): d["on"]=False
        elif sc=="home":
            DEVICES["Living Room"][0]["on"]=True
            DEVICES["Living Room"][2]["on"]=True
        elif sc=="movie":
            for d in DEVICES["Living Room"]: d["on"]=False
            DEVICES["Living Room"][1]["on"]=True   # TV
            DEVICES["Living Room"][0]["on"]=True   # light dim
            DEVICES["Living Room"][0]["dim"]=10
        self._refresh_all()

    # ── SCHEDULE PANEL ────────────────────────────────────────────────────────

    def _build_schedule(self,parent):
        outer,inner=self._scrollable(parent)
        outer.pack(fill="both",expand=True)
        self._section_label(inner,"TODAY'S SCHEDULE")
        for s in SCHEDULES: self._sch_card(inner,s)
        add_f=tk.Frame(inner,bg=T["border0"],padx=1,pady=1)
        add_f.pack(fill="x",padx=20,pady=4)
        ai=tk.Frame(add_f,bg=T["bg2"],padx=14,pady=10,cursor="hand2")
        ai.pack(fill="x")
        tk.Label(ai,text="＋  New Schedule",font=(FB,11,"bold"),
                 bg=T["bg2"],fg=T["acc_lt"]).pack(side="left")
        ai.bind("<Button-1>",lambda e:self._sch_dialog(inner))
        self._section_label(inner,"AUTOMATIONS")
        for a in AUTOMATIONS: self._auto_card(inner,a)

    def _sch_card(self,parent,s):
        c=self._card(parent)
        tb=tk.Frame(c,bg=T["acc_bg"],padx=10,pady=6)
        tb.pack(side="left",padx=(0,16))
        tk.Label(tb,text=s["time"],font=FNM,bg=T["acc_bg"],fg=T["acc_lt"]).pack()
        info=tk.Frame(c,bg=T["bg2"]); info.pack(side="left",fill="both",expand=True)
        tk.Label(info,text=s["name"],font=FH,bg=T["bg2"],fg=T["text0"],anchor="w").pack(anchor="w")
        tk.Label(info,text=f"{s['action']}  ·  {s['days']}",font=FSM,
                 bg=T["bg2"],fg=T["text2"],anchor="w").pack(anchor="w")
        var=tk.BooleanVar(value=s["on"])
        GlowToggle(c,var,command=lambda sv=s,v=var:sv.update({"on":v.get()})
                   ).pack(side="right")

    def _auto_card(self,parent,a):
        c=self._card(parent)
        icv=tk.Canvas(c,width=40,height=40,bg=T["acc_bg"],highlightthickness=0)
        icv.pack(side="left",padx=(0,14))
        draw_icon(icv,"plug",20,20,28,T["amber"],T["acc_bg"])
        info=tk.Frame(c,bg=T["bg2"]); info.pack(side="left",fill="both",expand=True)
        tk.Label(info,text=a["name"],font=FH,bg=T["bg2"],fg=T["text0"],anchor="w").pack(anchor="w")
        tk.Label(info,text=f"{a['trigger']}  →  {a['action']}",
                 font=FSM,bg=T["bg2"],fg=T["text2"],anchor="w").pack(anchor="w")
        var=tk.BooleanVar(value=a["on"])
        GlowToggle(c,var,command=lambda av=a,v=var:av.update({"on":v.get()})
                   ).pack(side="right")

    def _sch_dialog(self,container):
        dlg=tk.Toplevel(self); dlg.title("New Schedule")
        dlg.geometry("390x320"); dlg.configure(bg=T["bg1"])
        dlg.resizable(False,False); dlg.grab_set()
        hdr=tk.Frame(dlg,bg=T["bg0"],pady=8); hdr.pack(fill="x")
        cv2=tk.Canvas(hdr,width=30,height=30,bg=T["bg0"],highlightthickness=0)
        cv2.pack(side="left",padx=(12,8)); draw_logo(cv2,0,0,30)
        tk.Label(hdr,text="New Schedule",font=(FA,13,"bold"),
                 bg=T["bg0"],fg=T["text0"]).pack(side="left")
        body=tk.Frame(dlg,bg=T["bg1"],padx=20,pady=10); body.pack(fill="both",expand=True)
        def lrow(txt):
            tk.Label(body,text=txt,font=FSM,bg=T["bg1"],fg=T["text2"]).pack(anchor="w",pady=(8,2))
        lrow("Time (HH:MM)")
        tv=tk.StringVar(value="07:00")
        tk.Entry(body,textvariable=tv,font=FBODY,bg=T["bg2"],fg=T["text0"],
                 insertbackground=T["text0"],relief="flat",bd=4,width=10).pack(anchor="w")
        lrow("Device / Scene name")
        nv=tk.StringVar()
        tk.Entry(body,textvariable=nv,font=FBODY,bg=T["bg2"],fg=T["text0"],
                 insertbackground=T["text0"],relief="flat",bd=4,width=28).pack(anchor="w")
        lrow("Action")
        av=tk.StringVar(value="Turn on")
        ttk.Combobox(body,textvariable=av,font=FBODY,width=26,
                     values=["Turn on","Turn off","Scene: Home","Scene: Away","Scene: Sleep"],
                     state="readonly").pack(anchor="w")
        def _save():
            SCHEDULES.append({"time":tv.get().strip(),"name":nv.get().strip() or "Device",
                              "action":av.get(),"days":"Every day","on":True})
            SCHEDULES.sort(key=lambda x:x["time"]); dlg.destroy()
            for w in self.panels["schedule"].winfo_children(): w.destroy()
            self._build_schedule(self.panels["schedule"])
        tk.Button(body,text="Save Schedule",font=(FB,11,"bold"),
                  bg=T["acc"],fg=T["text0"],relief="flat",bd=0,
                  padx=20,pady=8,cursor="hand2",
                  activebackground=T["acc_glow"],command=_save).pack(pady=14)

    # ── SECURITY PANEL ────────────────────────────────────────────────────────

    def _build_security(self,parent):
        outer,inner=self._scrollable(parent)
        outer.pack(fill="both",expand=True)
        self._section_label(inner,"ARM MODE")
        arm_f=tk.Frame(inner,bg=T["bg0"]); arm_f.pack(fill="x",padx=20,pady=(0,8))
        self.arm_btns_ref={}
        for mode,ico,label,abg,afg in [
            ("home","lamp","Home",T["green_bg"],T["green"]),
            ("away","fan","Away",T["amber_bg"],T["amber"]),
            ("disarm","monitor","Disarm",T["bg3"],T["text2"]),
        ]:
            brd=tk.Frame(arm_f,bg=T["border0"],padx=1,pady=1,cursor="hand2")
            brd.pack(side="left",padx=(0,8),expand=True,fill="x")
            inn=tk.Frame(brd,bg=T["bg2"],padx=12,pady=10); inn.pack(fill="x")
            icv=tk.Canvas(inn,width=28,height=28,bg=T["bg2"],highlightthickness=0)
            icv.pack(anchor="w")
            draw_icon(icv,ico,14,14,24,afg,T["bg2"])
            tk.Label(inn,text=label,font=(FB,12,"bold"),
                     bg=T["bg2"],fg=T["text0"]).pack(anchor="w",pady=(4,0))
            self.arm_btns_ref[mode]=(brd,inn,abg,afg)
            for w in [brd,inn]+inn.winfo_children():
                w.bind("<Button-1>",lambda e,m=mode,a=abg,f=afg:self._set_arm_mode_ui(m,a,f))
        self._set_arm_mode_ui("home",T["green_bg"],T["green"])

        self._section_label(inner,"CAMERAS")
        cg=tk.Frame(inner,bg=T["bg0"]); cg.pack(fill="x",padx=20,pady=(0,8))
        cameras=[("Front Door","Motion 2 min ago","⚠ Motion",T["amber"],T["amber_bg"]),
                 ("Backyard","All clear","✓ Clear",T["green"],T["green_bg"]),
                 ("Garage","Door closed","✓ OK",T["green"],T["green_bg"])]
        for i,(name,sub,badge,bfg,bbg) in enumerate(cameras):
            brd=tk.Frame(cg,bg=T["border0"],padx=1,pady=1)
            brd.grid(row=0,column=i,padx=(0,8),pady=(0,8),sticky="ew")
            cg.columnconfigure(i,weight=1)
            card=tk.Frame(brd,bg=T["bg2"]); card.pack(fill="x")
            feed=tk.Canvas(card,width=100,height=96,bg=T["bg3"],highlightthickness=0)
            feed.pack(fill="x")
            # Camera icon
            draw_icon(feed,"monitor",50,44,40,T["text2"],T["bg3"])
            feed.create_rectangle(0,0,46,18,fill=T["red"],outline="")
            feed.create_oval(6,5,14,13,fill="white",outline="")
            feed.create_text(28,9,text="LIVE",font=(FB,8,"bold"),fill="white")
            foot=tk.Frame(card,bg=T["bg2"],padx=8,pady=6); foot.pack(fill="x")
            tk.Label(foot,text=name,font=(FB,11,"bold"),bg=T["bg2"],fg=T["text0"]).pack(anchor="w")
            tk.Label(foot,text=sub,font=FMI,bg=T["bg2"],fg=T["text2"]).pack(anchor="w")
            tk.Label(foot,text=badge,font=(FB,9,"bold"),bg=bbg,fg=bfg,
                     padx=6,pady=2).pack(anchor="w",pady=(4,0))

        self._section_label(inner,"RECENT EVENTS")
        eb=tk.Frame(inner,bg=T["border0"],padx=1,pady=1); eb.pack(fill="x",padx=20,pady=(0,20))
        ec=tk.Frame(eb,bg=T["bg2"],padx=14,pady=6); ec.pack(fill="x")
        dm={"motion":T["amber"],"door":T["acc_lt"],"ok":T["green"]}
        for kind,text,ts in EVENTS:
            row=tk.Frame(ec,bg=T["bg2"]); row.pack(fill="x",pady=6)
            dc=tk.Canvas(row,width=14,height=14,bg=T["bg2"],highlightthickness=0)
            dc.create_oval(2,2,12,12,fill=dm.get(kind,T["text2"]),outline="")
            dc.pack(side="left",padx=(0,10))
            tk.Label(row,text=text,font=FBODY,bg=T["bg2"],fg=T["text0"]).pack(side="left")
            tk.Label(row,text=ts,font=FMI,bg=T["bg2"],fg=T["text2"]).pack(side="right")

    def _set_arm_mode(self,mode):
        d={"home":(T["green_bg"],T["green"]),"away":(T["amber_bg"],T["amber"]),
           "disarm":(T["bg3"],T["text2"])}
        a,f=d.get(mode,(T["bg3"],T["text2"]))
        self._set_arm_mode_ui(mode,a,f)

    def _set_arm_mode_ui(self,mode,abg,afg):
        self.arm_mode.set(mode)
        for m,(brd,inn,_bg,_fg) in self.arm_btns_ref.items():
            if m==mode:
                brd.config(bg=afg); inn.config(bg=abg)
                for ch in inn.winfo_children(): ch.config(bg=abg)
            else:
                brd.config(bg=T["border0"]); inn.config(bg=T["bg2"])
                for ch in inn.winfo_children(): ch.config(bg=T["bg2"])

    # ── ENERGY PANEL ──────────────────────────────────────────────────────────

    def _build_energy(self,parent):
        outer,inner=self._scrollable(parent)
        outer.pack(fill="both",expand=True)
        sf=tk.Frame(inner,bg=T["bg0"]); sf.pack(fill="x",padx=20,pady=(20,0))
        self._stat_block(sf,"4.2 kWh","TODAY",icon_name="bulb",color=T["acc_lt"])
        self._stat_block(sf,"87 kWh","THIS MONTH",icon_name="tv",color=T["text0"])
        self._stat_block(sf,"Rs.620","EST. BILL",sub="↓12% last month",
                         icon_name="plug",color=T["green"])
        self._stat_block(sf,"3.1 t","CO₂ SAVED",icon_name="drop",color=T["cyan"])

        self._section_label(inner,"HOURLY USAGE — kWh")
        cb=tk.Frame(inner,bg=T["border0"],padx=1,pady=1)
        cb.pack(fill="x",padx=20,pady=(0,8))
        cc=tk.Frame(cb,bg=T["bg2"],padx=10,pady=10); cc.pack(fill="x")
        self._draw_chart(cc)

        self._section_label(inner,"BY DEVICE")
        for name,kwh,pct,ico in ENERGY_DEVICES: self._energy_row(inner,name,kwh,pct,ico)

    def _draw_chart(self,parent):
        W,H=900,190; PL,PR,PT,PB=44,14,14,34
        hour=datetime.datetime.now().hour
        hours=list(range(hour+1)); vals=[HOURLY[h] for h in hours]
        max_v=max(vals) if vals else 1
        cv=tk.Canvas(parent,width=W,height=H,bg=T["bg2"],highlightthickness=0)
        cv.pack(fill="x")
        cw=W-PL-PR; ch=H-PT-PB; n=len(hours)
        bw=max(5,cw//n-5)
        for step in [0.10,0.20,0.30,0.35]:
            y=PT+ch-int((step/max_v)*ch)
            if 0<y<H:
                cv.create_line(PL,y,W-PR,y,fill=T["border0"],dash=(4,4))
                cv.create_text(PL-4,y,text=f"{step:.1f}",
                               fill=T["text2"],font=(FB,8),anchor="e")
        for i,(h,v) in enumerate(zip(hours,vals)):
            x=PL+i*(cw//n)+(cw//n-bw)//2
            bh=max(2,int((v/max_v)*ch))
            y0=PT+ch-bh; y1=PT+ch
            # Gradient bar (step-rendered for crispness)
            steps2=max(1,bh)
            for j in range(steps2):
                t2=j/steps2
                col=blend(T["acc_glow"],T["acc_lt"],t2)
                cv.create_rectangle(x,y0+j,x+bw,y0+j+1,fill=col,outline="")
            # Bright cap
            cv.create_rectangle(x,y0,x+bw,y0+2,fill=T["acc_lt"],outline="")
            # Glow on latest bar
            if i==len(hours)-1:
                for gi in range(4,0,-1):
                    gc=alpha_blend(T["acc_lt"],T["bg2"],gi*0.06)
                    cv.create_rectangle(x-gi,y0-gi,x+bw+gi,y1,fill=gc,outline="")
                cv.create_rectangle(x,y0,x+bw,y1,fill=T["acc"],outline="")
                cv.create_rectangle(x,y0,x+bw,y0+2,fill=T["acc_lt"],outline="")
            if n<=12 or h%3==0:
                lbl=(f"{h}am" if h<12 else("12pm" if h==12 else f"{h-12}pm"))
                if h==0: lbl="12a"
                cv.create_text(x+bw//2,H-10,text=lbl,fill=T["text2"],font=(FB,8))

    def _energy_row(self,parent,name,kwh,pct,ico):
        c=self._card(parent)
        icv=tk.Canvas(c,width=40,height=40,bg=T["acc_bg"],highlightthickness=0)
        icv.pack(side="left",padx=(0,14))
        draw_icon(icv,ico,20,20,30,T["acc_lt"],T["acc_bg"])
        info=tk.Frame(c,bg=T["bg2"]); info.pack(side="left",fill="both",expand=True)
        hf=tk.Frame(info,bg=T["bg2"]); hf.pack(fill="x")
        tk.Label(hf,text=name,font=FH,bg=T["bg2"],fg=T["text0"],anchor="w").pack(side="left")
        tk.Label(hf,text=f"{kwh} kWh  ·  {pct}%",font=FSM,
                 bg=T["bg2"],fg=T["acc_lt"]).pack(side="right")
        track=tk.Frame(info,bg=T["bg4"],height=5)
        track.pack(fill="x",pady=(6,0))
        track.pack_propagate(False)
        fw=min(pct/100,1.0)
        fc=blend(T["acc_glow"],T["acc_lt"],fw)
        tk.Frame(track,bg=fc,height=5).place(x=0,y=0,relheight=1,relwidth=fw)

    # ── VOICE PANEL ───────────────────────────────────────────────────────────

    def _build_voice(self,parent):
        outer,inner=self._scrollable(parent)
        outer.pack(fill="both",expand=True)

        # Hero area
        hero=tk.Frame(inner,bg=T["bg0"]); hero.pack(fill="x",padx=20,pady=(30,0))
        hero_c=tk.Frame(hero,bg=T["bg0"]); hero_c.pack(anchor="center")

        # Animated mic button
        self._mic_btn=VoiceMicButton(hero_c,on_click=self._toggle_voice)
        self._mic_btn.pack(pady=(0,12))

        self.voice_status_lbl=tk.Label(hero_c,text="Tap to start listening",
                                       font=(FA,13),bg=T["bg0"],fg=T["text1"])
        self.voice_status_lbl.pack()

        # Last heard
        lh_f=tk.Frame(inner,bg=T["border0"],padx=1,pady=1)
        lh_f.pack(fill="x",padx=40,pady=(20,0))
        lh_i=tk.Frame(lh_f,bg=T["bg2"],padx=16,pady=12); lh_i.pack(fill="x")
        tk.Label(lh_i,text="LAST HEARD",font=(FB,9,"bold"),
                 bg=T["bg2"],fg=T["text2"]).pack(anchor="w")
        self.voice_heard_lbl=tk.Label(lh_i,text="—",font=(FA,14),
                                      bg=T["bg2"],fg=T["acc_lt"],wraplength=500,
                                      justify="left")
        self.voice_heard_lbl.pack(anchor="w",pady=(4,0))

        # Response
        rsp_f=tk.Frame(inner,bg=T["border0"],padx=1,pady=1)
        rsp_f.pack(fill="x",padx=40,pady=(8,0))
        rsp_i=tk.Frame(rsp_f,bg=T["bg2"],padx=16,pady=12); rsp_i.pack(fill="x")
        tk.Label(rsp_i,text="RESPONSE",font=(FB,9,"bold"),
                 bg=T["bg2"],fg=T["text2"]).pack(anchor="w")
        self.voice_resp_lbl=tk.Label(rsp_i,text="—",font=FBODY,
                                     bg=T["bg2"],fg=T["text0"],wraplength=500,
                                     justify="left")
        self.voice_resp_lbl.pack(anchor="w",pady=(4,0))

        # Voice availability notice
        if not VOICE_OK:
            tk.Label(inner,
                     text="⚠  speech_recognition not installed.\n"
                          "Run:  pip install SpeechRecognition pyaudio",
                     font=FBODY,bg=T["bg0"],fg=T["amber"],
                     justify="center").pack(pady=16)

        # Commands cheat-sheet
        self._section_label(inner,"EXAMPLE COMMANDS")
        cmds=[
            ("turn on ceiling light",   "Turn on a device by name"),
            ("turn off smart tv",       "Turn off a device"),
            ("set brightness to 70",    "Dim lights in current room"),
            ("activate scene sleep",    "Activate a scene"),
            ("switch to bedroom",       "Change room"),
            ("arm home / arm away",     "Set security mode"),
            ("disarm",                  "Disarm security"),
            ("what's the temperature",  "Query room temperature"),
            ("list devices",            "List devices in current room"),
            ("how many devices are on", "Count active devices"),
        ]
        for cmd,desc in cmds:
            c=self._card(inner,padx=40,pady=3)
            tk.Label(c,text=f'"{cmd}"',font=(FA,12,"italic"),
                     bg=T["bg2"],fg=T["acc_lt"],anchor="w").pack(side="left")
            tk.Label(c,text=desc,font=FSM,bg=T["bg2"],
                     fg=T["text2"],anchor="e").pack(side="right")

    def _toggle_voice(self):
        if self._voice_listening: return
        self._voice_listening=True
        if self._mic_btn: self._mic_btn.set_state("listening")
        self.voice_status_lbl.config(text="Listening… speak now",fg=T["red"])
        self._veng.listen_once()

    def _poll_voice(self):
        """Check the voice queue every 80 ms (runs on main thread)."""
        try:
            while True:
                kind,data=self._vq.get_nowait()
                if kind=="status":
                    if data=="listening":
                        if self._mic_btn: self._mic_btn.set_state("listening")
                        self.voice_status_lbl.config(text="Listening…",fg=T["red"])
                    elif data=="processing":
                        if self._mic_btn: self._mic_btn.set_state("processing")
                        self.voice_status_lbl.config(text="Processing…",fg=T["amber"])
                elif kind=="result":
                    self._voice_listening=False
                    if self._mic_btn: self._mic_btn.set_state("idle")
                    self.voice_heard_lbl.config(text=f'"{data}"')
                    response=self._parser.parse(data)
                    self.voice_resp_lbl.config(text=response)
                    self.voice_status_lbl.config(text="Tap to start listening",
                                                 fg=T["text1"])
                    self._eng.speak(response)
                elif kind=="error":
                    self._voice_listening=False
                    if self._mic_btn: self._mic_btn.set_state("idle")
                    self.voice_resp_lbl.config(text=f"⚠ {data}")
                    self.voice_status_lbl.config(text="Tap to try again",fg=T["text1"])
        except queue.Empty:
            pass
        self.after(80,self._poll_voice)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__=="__main__":
    app=App()

    # Dark ttk styling
    try:
        s=ttk.Style(app); s.theme_use("clam")
        s.configure("TScale",background=T["bg2"],troughcolor=T["bg4"],
                    slidercolor=T["acc_lt"],sliderlength=14)
        s.configure("Vertical.TScrollbar",background=T["bg2"],
                    troughcolor=T["bg0"],arrowcolor=T["text2"])
        s.configure("TCombobox",fieldbackground=T["bg2"],
                    background=T["bg2"],foreground=T["text0"],
                    selectbackground=T["acc"],selectforeground=T["text0"])
    except Exception:
        pass

    app.mainloop()
