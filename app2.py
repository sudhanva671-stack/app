"""
Home Automation System — Python/Tkinter
Run: python app.py
Requires: Python 3.8+, no extra dependencies (uses only stdlib)
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import datetime
import random

# ── Data ──────────────────────────────────────────────────────────────────────

ROOMS = ["Living Room", "Bedroom", "Kitchen", "Office"]

DEVICES = {
    "Living Room": [
        {"name": "Ceiling Light", "icon": "💡", "on": True,  "dim": 75,  "type": "light"},
        {"name": "Smart TV",      "icon": "📺", "on": True,  "dim": 100, "type": "switch"},
        {"name": "AC Unit",       "icon": "❄️",  "on": True,  "dim": 100, "type": "switch"},
        {"name": "Floor Lamp",    "icon": "🪔", "on": False, "dim": 50,  "type": "light"},
    ],
    "Bedroom": [
        {"name": "Ceiling Light", "icon": "💡", "on": False, "dim": 40,  "type": "light"},
        {"name": "Bedside Lamp",  "icon": "🪔", "on": True,  "dim": 30,  "type": "light"},
        {"name": "Smart Fan",     "icon": "🌀", "on": True,  "dim": 100, "type": "switch"},
    ],
    "Kitchen": [
        {"name": "Ceiling Light", "icon": "💡", "on": True,  "dim": 100, "type": "light"},
        {"name": "Coffee Maker",  "icon": "☕", "on": False, "dim": 100, "type": "switch"},
        {"name": "Refrigerator",  "icon": "🧊", "on": True,  "dim": 100, "type": "switch"},
        {"name": "Smart Oven",    "icon": "🍳", "on": False, "dim": 100, "type": "switch"},
    ],
    "Office": [
        {"name": "Desk Lamp",     "icon": "💡", "on": True,  "dim": 90,  "type": "light"},
        {"name": "Air Purifier",  "icon": "🌬️", "on": True,  "dim": 100, "type": "switch"},
        {"name": "Monitor Light", "icon": "🖥️", "on": False, "dim": 60,  "type": "light"},
    ],
}

SCHEDULES = [
    {"time": "06:30", "name": "Coffee Maker",  "action": "Turn on",        "days": "Mon–Fri",   "on": True},
    {"time": "07:00", "name": "Scene: Home",   "action": "Activate",       "days": "Every day", "on": True},
    {"time": "08:00", "name": "Office Lamp",   "action": "Turn on",        "days": "Mon–Fri",   "on": True},
    {"time": "22:30", "name": "Scene: Sleep",  "action": "Activate",       "days": "Every day", "on": True},
]

AUTOMATIONS = [
    {"name": "Motion → Lights",   "trigger": "Motion at front door",   "action": "Porch light on 5 min", "on": True},
    {"name": "Sunrise adjust",    "trigger": "Sunrise ±30 min",        "action": "Brighten living room",  "on": True},
    {"name": "Away energy save",  "trigger": "Everyone leaves home",   "action": "AC 28°C, lights off",   "on": False},
]

EVENTS = [
    ("Motion",  "Motion detected — Front door",   "2 min ago"),
    ("Door",    "Front door locked",              "18 min ago"),
    ("OK",      "System armed — Home mode",       "8:02 AM"),
    ("Door",    "Garage door opened",             "7:50 AM"),
    ("OK",      "All sensors normal — daily check","7:00 AM"),
]

# Energy kWh per device
ENERGY = [
    ("AC Unit",       1.8, 43),
    ("Refrigerator",  0.9, 21),
    ("Smart TV",      0.5, 12),
    ("Lights (all)",  0.6, 14),
    ("Other",         0.4, 10),
]

HOURLY_PATTERN = [0.05,0.04,0.03,0.03,0.04,0.12,0.28,0.35,
                  0.22,0.18,0.20,0.25,0.30,0.22,0.18,0.16,
                  0.20,0.28,0.32,0.25,0.18,0.14,0.10,0.07]

# ── Colour palette ─────────────────────────────────────────────────────────────

C = {
    "bg":        "#F7F7F5",
    "surface":   "#FFFFFF",
    "border":    "#E0DED8",
    "text":      "#1A1A18",
    "muted":     "#6B6B67",
    "hint":      "#A0A09C",
    "blue":      "#378ADD",
    "blue_bg":   "#E6F1FB",
    "blue_txt":  "#0C447C",
    "green":     "#639922",
    "green_bg":  "#EAF3DE",
    "green_txt": "#27500A",
    "amber":     "#BA7517",
    "amber_bg":  "#FAEEDA",
    "amber_txt": "#633806",
    "red":       "#E24B4A",
    "red_bg":    "#FCEBEB",
    "red_txt":   "#791F1F",
    "nav_active":"#378ADD",
}

FONT_TITLE  = ("Helvetica Neue", 15, "bold")
FONT_HEADER = ("Helvetica Neue", 13, "bold")
FONT_BODY   = ("Helvetica Neue", 12)
FONT_SMALL  = ("Helvetica Neue", 10)
FONT_STAT   = ("Helvetica Neue", 22, "bold")


# ── Helpers ────────────────────────────────────────────────────────────────────

def devices_on_count():
    return sum(1 for devs in DEVICES.values() for d in devs if d["on"])


def badge_canvas(parent, text, bg, fg, width=90):
    """Draw a rounded-pill badge on a Canvas."""
    c = tk.Canvas(parent, width=width, height=24, bg=parent["bg"],
                  highlightthickness=0)
    c.create_rectangle(2, 2, width-2, 22, fill=bg, outline=bg, width=0)
    c.create_text(width//2, 12, text=text, fill=fg,
                  font=("Helvetica Neue", 10, "bold"))
    return c


def toggle_button(parent, var, command, width=48):
    """Return a simple checkbutton styled as a toggle."""
    btn = tk.Checkbutton(
        parent, variable=var, command=command,
        bg=parent["bg"], activebackground=parent["bg"],
        selectcolor=C["blue"], indicatoron=False,
        relief="flat", bd=0,
        width=4, height=1,
        fg=C["surface"], activeforeground=C["surface"],
        font=FONT_SMALL,
    )
    def refresh(*_):
        if var.get():
            btn.config(bg=C["blue"], text="ON ", fg=C["surface"])
        else:
            btn.config(bg=C["border"], text="OFF", fg=C["muted"])
    var.trace_add("write", refresh)
    refresh()
    return btn


# ── Main App ───────────────────────────────────────────────────────────────────

class HomeAutomationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Home Automation System")
        self.geometry("860x700")
        self.resizable(True, True)
        self.configure(bg=C["bg"])

        self.current_room = tk.StringVar(value="Living Room")
        self.thermostat   = tk.IntVar(value=22)
        self.arm_mode     = tk.StringVar(value="home")
        self.active_tab   = tk.StringVar(value="devices")

        self._build_ui()
        self._refresh_clock()

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        top = tk.Frame(self, bg=C["surface"], pady=10, padx=16)
        top.pack(fill="x")
        tk.Label(top, text="🏠  My Home", font=FONT_TITLE,
                 bg=C["surface"], fg=C["text"]).pack(side="left")
        self.clock_lbl = tk.Label(top, text="", font=FONT_SMALL,
                                  bg=C["surface"], fg=C["muted"])
        self.clock_lbl.pack(side="right", padx=(0, 8))
        tk.Label(top, text="● All systems normal", font=FONT_SMALL,
                 bg=C["surface"], fg=C["green"]).pack(side="right", padx=8)

        # Divider
        tk.Frame(self, height=1, bg=C["border"]).pack(fill="x")

        # Nav tabs
        nav = tk.Frame(self, bg=C["surface"])
        nav.pack(fill="x")
        self.nav_btns = {}
        for tab, label in [("devices","🔌  Devices"),("schedule","📅  Schedule"),
                            ("security","🛡  Security"),("energy","⚡  Energy")]:
            b = tk.Button(nav, text=label, font=FONT_BODY,
                          bg=C["surface"], fg=C["muted"], relief="flat", bd=0,
                          padx=18, pady=10, cursor="hand2",
                          command=lambda t=tab: self._switch_tab(t))
            b.pack(side="left")
            self.nav_btns[tab] = b

        tk.Frame(self, height=1, bg=C["border"]).pack(fill="x")

        # Content area
        self.content = tk.Frame(self, bg=C["bg"])
        self.content.pack(fill="both", expand=True, padx=16, pady=14)

        self.panels = {}
        for tab in ["devices","schedule","security","energy"]:
            f = tk.Frame(self.content, bg=C["bg"])
            self.panels[tab] = f
            builder = getattr(self, f"_build_{tab}")
            builder(f)

        self._switch_tab("devices")

    def _switch_tab(self, tab):
        for t, f in self.panels.items():
            f.pack_forget()
        self.panels[tab].pack(fill="both", expand=True)
        self.active_tab.set(tab)
        for t, b in self.nav_btns.items():
            if t == tab:
                b.config(fg=C["blue"], font=("Helvetica Neue", 12, "bold"))
            else:
                b.config(fg=C["muted"], font=FONT_BODY)

    def _refresh_clock(self):
        now = datetime.datetime.now()
        self.clock_lbl.config(text=now.strftime("%a %d %b  %H:%M"))
        self.after(30000, self._refresh_clock)

    # ── Devices panel ─────────────────────────────────────────────────────────

    def _build_devices(self, parent):
        # Stats row
        stats_frame = tk.Frame(parent, bg=C["bg"])
        stats_frame.pack(fill="x", pady=(0, 12))
        self.stat_on_lbl = self._stat_card(stats_frame, str(devices_on_count()), "Devices on")
        self._stat_card(stats_frame, "4", "Rooms active")
        self._stat_card(stats_frame, "24°C", "Room temp")
        self._stat_card(stats_frame, "1.4 kW", "Power now", color=C["amber"])

        # Room selector
        tk.Label(parent, text="ROOMS", font=FONT_SMALL, bg=C["bg"],
                 fg=C["hint"]).pack(anchor="w", pady=(0, 6))
        self.room_frame = tk.Frame(parent, bg=C["bg"])
        self.room_frame.pack(fill="x", pady=(0, 14))
        self._render_rooms()

        # Devices list
        tk.Label(parent, text="DEVICES", font=FONT_SMALL, bg=C["bg"],
                 fg=C["hint"]).pack(anchor="w", pady=(0, 6))
        scroll_host = tk.Frame(parent, bg=C["bg"])
        scroll_host.pack(fill="both", expand=True)
        self.dev_canvas = tk.Canvas(scroll_host, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(scroll_host, orient="vertical",
                           command=self.dev_canvas.yview)
        self.dev_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.dev_canvas.pack(side="left", fill="both", expand=True)
        self.dev_inner = tk.Frame(self.dev_canvas, bg=C["bg"])
        self.dev_canvas_win = self.dev_canvas.create_window(
            (0, 0), window=self.dev_inner, anchor="nw")
        self.dev_inner.bind("<Configure>", lambda e: self.dev_canvas.configure(
            scrollregion=self.dev_canvas.bbox("all")))
        self.dev_canvas.bind("<Configure>", lambda e: self.dev_canvas.itemconfig(
            self.dev_canvas_win, width=e.width))
        self._render_devices()

    def _stat_card(self, parent, value, label, color=None):
        f = tk.Frame(parent, bg=C["surface"], bd=0,
                     highlightbackground=C["border"], highlightthickness=1)
        f.pack(side="left", expand=True, fill="x", padx=(0, 8))
        tk.Label(f, text=label, font=FONT_SMALL, bg=C["surface"],
                 fg=C["muted"]).pack(anchor="w", padx=10, pady=(8, 0))
        lbl = tk.Label(f, text=value, font=FONT_STAT, bg=C["surface"],
                       fg=color or C["text"])
        lbl.pack(anchor="w", padx=10, pady=(0, 8))
        return lbl

    def _render_rooms(self):
        for w in self.room_frame.winfo_children():
            w.destroy()
        for room in ROOMS:
            is_sel = room == self.current_room.get()
            on_count = sum(1 for d in DEVICES[room] if d["on"])
            total = len(DEVICES[room])
            border = C["blue"] if is_sel else C["border"]
            f = tk.Frame(self.room_frame, bg=C["surface"],
                         highlightbackground=border, highlightthickness=2 if is_sel else 1,
                         cursor="hand2", padx=10, pady=10)
            f.pack(side="left", expand=True, fill="x", padx=(0, 8))
            icons = {"Living Room":"🛋", "Bedroom":"🛏", "Kitchen":"🍳", "Office":"💻"}
            ico_fg = C["blue"] if is_sel else C["muted"]
            tk.Label(f, text=icons.get(room, "🏠"), font=("Helvetica Neue", 20),
                     bg=C["surface"], fg=ico_fg).pack(anchor="w")
            tk.Label(f, text=room, font=("Helvetica Neue", 11, "bold"),
                     bg=C["surface"], fg=C["text"]).pack(anchor="w")
            tk.Label(f, text=f"{on_count}/{total} on", font=FONT_SMALL,
                     bg=C["surface"], fg=C["muted"]).pack(anchor="w")
            f.bind("<Button-1>", lambda e, r=room: self._select_room(r))
            for child in f.winfo_children():
                child.bind("<Button-1>", lambda e, r=room: self._select_room(r))

    def _select_room(self, room):
        self.current_room.set(room)
        self._render_rooms()
        self._render_devices()

    def _render_devices(self):
        for w in self.dev_inner.winfo_children():
            w.destroy()
        room = self.current_room.get()
        for idx, dev in enumerate(DEVICES[room]):
            self._device_row(self.dev_inner, room, idx, dev)

    def _device_row(self, parent, room, idx, dev):
        row = tk.Frame(parent, bg=C["surface"],
                       highlightbackground=C["border"], highlightthickness=1)
        row.pack(fill="x", pady=(0, 6))

        # Icon
        ico_bg = C["blue_bg"] if dev["on"] else C["bg"]
        ico_fg = C["blue"] if dev["on"] else C["hint"]
        ico_f = tk.Frame(row, bg=ico_bg, width=40, height=40)
        ico_f.pack(side="left", padx=(10, 10), pady=10)
        ico_f.pack_propagate(False)
        tk.Label(ico_f, text=dev["icon"], font=("Helvetica Neue", 18),
                 bg=ico_bg, fg=ico_fg).place(relx=.5, rely=.5, anchor="center")

        # Info
        info = tk.Frame(row, bg=C["surface"])
        info.pack(side="left", fill="both", expand=True, pady=10)
        tk.Label(info, text=dev["name"], font=FONT_HEADER,
                 bg=C["surface"], fg=C["text"], anchor="w").pack(anchor="w")
        status = "On" if dev["on"] else "Off"
        tk.Label(info, text=status, font=FONT_SMALL,
                 bg=C["surface"], fg=C["muted"], anchor="w").pack(anchor="w")
        if dev["type"] == "light" and dev["on"]:
            dim_var = tk.IntVar(value=dev["dim"])
            dim_frame = tk.Frame(info, bg=C["surface"])
            dim_frame.pack(anchor="w", fill="x", pady=(4, 0))
            tk.Label(dim_frame, text="Brightness:", font=FONT_SMALL,
                     bg=C["surface"], fg=C["muted"]).pack(side="left")
            dim_lbl = tk.Label(dim_frame, text=f"{dev['dim']}%",
                               font=FONT_SMALL, bg=C["surface"], fg=C["blue"],
                               width=4)
            dim_lbl.pack(side="right", padx=(0, 10))
            sl = ttk.Scale(dim_frame, from_=0, to=100, orient="horizontal",
                           variable=dim_var, length=160,
                           command=lambda v, d=dev, l=dim_lbl: self._set_dim(d, v, l))
            sl.pack(side="left", padx=6)

        # Toggle
        var = tk.BooleanVar(value=dev["on"])
        btn = toggle_button(row, var,
                            command=lambda d=dev, v=var, r=room: self._toggle_dev(d, v, r))
        btn.pack(side="right", padx=12, pady=10)

    def _toggle_dev(self, dev, var, room):
        dev["on"] = var.get()
        self.stat_on_lbl.config(text=str(devices_on_count()))
        self._render_rooms()
        self._render_devices()

    def _set_dim(self, dev, val, lbl):
        dev["dim"] = int(float(val))
        lbl.config(text=f"{dev['dim']}%")

    # ── Schedule panel ────────────────────────────────────────────────────────

    def _build_schedule(self, parent):
        tk.Label(parent, text="TODAY'S SCHEDULE", font=FONT_SMALL,
                 bg=C["bg"], fg=C["hint"]).pack(anchor="w", pady=(0, 6))
        for i, s in enumerate(SCHEDULES):
            self._schedule_row(parent, i, s)

        add_btn = tk.Button(parent, text="＋  Add schedule",
                            font=FONT_BODY, bg=C["surface"], fg=C["muted"],
                            relief="flat", bd=0, padx=12, pady=8, cursor="hand2",
                            highlightbackground=C["border"], highlightthickness=1,
                            command=self._add_schedule_dialog)
        add_btn.pack(fill="x", pady=(4, 16))

        tk.Label(parent, text="AUTOMATIONS", font=FONT_SMALL,
                 bg=C["bg"], fg=C["hint"]).pack(anchor="w", pady=(0, 6))
        for i, a in enumerate(AUTOMATIONS):
            self._automation_row(parent, i, a)

    def _schedule_row(self, parent, idx, s):
        row = tk.Frame(parent, bg=C["surface"],
                       highlightbackground=C["border"], highlightthickness=1)
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text=s["time"], font=("Helvetica Neue", 18, "bold"),
                 bg=C["surface"], fg=C["text"], width=5).pack(side="left", padx=12, pady=10)
        info = tk.Frame(row, bg=C["surface"])
        info.pack(side="left", fill="both", expand=True, pady=10)
        tk.Label(info, text=s["name"], font=FONT_HEADER,
                 bg=C["surface"], fg=C["text"], anchor="w").pack(anchor="w")
        tk.Label(info, text=f"{s['action']} · {s['days']}", font=FONT_SMALL,
                 bg=C["surface"], fg=C["muted"], anchor="w").pack(anchor="w")
        var = tk.BooleanVar(value=s["on"])
        btn = toggle_button(row, var, command=lambda sv=s, v=var: sv.update({"on": v.get()}))
        btn.pack(side="right", padx=12, pady=10)

    def _automation_row(self, parent, idx, a):
        row = tk.Frame(parent, bg=C["surface"],
                       highlightbackground=C["border"], highlightthickness=1)
        row.pack(fill="x", pady=(0, 6))
        ico_f = tk.Frame(row, bg=C["blue_bg"], width=40, height=40)
        ico_f.pack(side="left", padx=(10, 10), pady=10)
        ico_f.pack_propagate(False)
        tk.Label(ico_f, text="⚡", font=("Helvetica Neue", 18),
                 bg=C["blue_bg"], fg=C["blue"]).place(relx=.5, rely=.5, anchor="center")
        info = tk.Frame(row, bg=C["surface"])
        info.pack(side="left", fill="both", expand=True, pady=10)
        tk.Label(info, text=a["name"], font=FONT_HEADER,
                 bg=C["surface"], fg=C["text"], anchor="w").pack(anchor="w")
        tk.Label(info, text=f"{a['trigger']} → {a['action']}", font=FONT_SMALL,
                 bg=C["surface"], fg=C["muted"], anchor="w").pack(anchor="w")
        var = tk.BooleanVar(value=a["on"])
        btn = toggle_button(row, var, command=lambda av=a, v=var: av.update({"on": v.get()}))
        btn.pack(side="right", padx=12, pady=10)

    def _add_schedule_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Add Schedule")
        dlg.geometry("360x260")
        dlg.configure(bg=C["bg"])
        dlg.resizable(False, False)
        dlg.grab_set()

        def lbl(text): 
            return tk.Label(dlg, text=text, font=FONT_BODY, bg=C["bg"], fg=C["muted"])

        lbl("Time (HH:MM)").pack(anchor="w", padx=20, pady=(16, 2))
        time_var = tk.StringVar(value="07:00")
        tk.Entry(dlg, textvariable=time_var, font=FONT_BODY, width=10).pack(anchor="w", padx=20)

        lbl("Device / Scene name").pack(anchor="w", padx=20, pady=(10, 2))
        name_var = tk.StringVar()
        tk.Entry(dlg, textvariable=name_var, font=FONT_BODY, width=28).pack(anchor="w", padx=20)

        lbl("Action").pack(anchor="w", padx=20, pady=(10, 2))
        action_var = tk.StringVar(value="Turn on")
        ttk.Combobox(dlg, textvariable=action_var, font=FONT_BODY, width=26,
                     values=["Turn on","Turn off","Scene: Home","Scene: Away","Scene: Sleep"],
                     state="readonly").pack(anchor="w", padx=20)

        def save():
            t = time_var.get().strip()
            n = name_var.get().strip() or "New device"
            a = action_var.get()
            SCHEDULES.append({"time": t, "name": n, "action": a,
                              "days": "Every day", "on": True})
            SCHEDULES.sort(key=lambda x: x["time"])
            dlg.destroy()
            # Refresh panel
            for w in self.panels["schedule"].winfo_children():
                w.destroy()
            self._build_schedule(self.panels["schedule"])

        tk.Button(dlg, text="Save", font=FONT_HEADER, bg=C["blue"], fg="white",
                  relief="flat", bd=0, padx=20, pady=8, cursor="hand2",
                  command=save).pack(pady=16)

    # ── Security panel ────────────────────────────────────────────────────────

    def _build_security(self, parent):
        tk.Label(parent, text="ARM MODE", font=FONT_SMALL,
                 bg=C["bg"], fg=C["hint"]).pack(anchor="w", pady=(0, 8))
        arm_frame = tk.Frame(parent, bg=C["bg"])
        arm_frame.pack(fill="x", pady=(0, 14))
        self.arm_btns = {}
        for mode, label, active_bg, active_fg in [
            ("home",  "🏠  Home",   C["green_bg"],  C["green"]),
            ("away",  "🚶  Away",   C["amber_bg"],  C["amber"]),
            ("disarm","🛡  Disarm", C["bg"],         C["muted"]),
        ]:
            b = tk.Button(arm_frame, text=label, font=FONT_BODY,
                          bg=C["surface"], fg=C["muted"],
                          relief="flat", bd=0, padx=16, pady=7,
                          highlightbackground=C["border"], highlightthickness=1,
                          cursor="hand2",
                          command=lambda m=mode, bg=active_bg, fg=active_fg:
                              self._set_arm(m, bg, fg))
            b.pack(side="left", padx=(0, 8))
            self.arm_btns[mode] = (b, active_bg, active_fg)
        self._set_arm("home", C["green_bg"], C["green"])

        tk.Label(parent, text="CAMERAS", font=FONT_SMALL,
                 bg=C["bg"], fg=C["hint"]).pack(anchor="w", pady=(0, 8))
        cam_grid = tk.Frame(parent, bg=C["bg"])
        cam_grid.pack(fill="x", pady=(0, 14))
        cameras = [
            ("Front door",  "Motion 2 min ago", "Motion", C["amber_bg"], C["amber"]),
            ("Backyard",    "All clear",         "Clear",  C["green_bg"], C["green"]),
            ("Garage",      "Door closed",       "OK",     C["green_bg"], C["green"]),
        ]
        for i, (name, sub, badge, bbg, bfg) in enumerate(cameras):
            col = i % 3
            row_num = i // 3
            f = tk.Frame(cam_grid, bg=C["surface"],
                         highlightbackground=C["border"], highlightthickness=1)
            f.grid(row=row_num, column=col, padx=(0, 8), pady=(0, 8), sticky="ew")
            cam_grid.columnconfigure(col, weight=1)
            feed = tk.Frame(f, bg=C["bg"], height=80)
            feed.pack(fill="x")
            feed.pack_propagate(False)
            tk.Label(feed, text="📷", font=("Helvetica Neue", 28),
                     bg=C["bg"], fg=C["hint"]).place(relx=.5, rely=.5, anchor="center")
            tk.Label(feed, text="LIVE", font=("Helvetica Neue", 9, "bold"),
                     bg=C["red"], fg="white").place(x=6, y=6)
            footer = tk.Frame(f, bg=C["surface"])
            footer.pack(fill="x", padx=8, pady=6)
            tk.Label(footer, text=name, font=("Helvetica Neue", 11, "bold"),
                     bg=C["surface"], fg=C["text"]).pack(anchor="w")
            tk.Label(footer, text=sub, font=FONT_SMALL,
                     bg=C["surface"], fg=C["muted"]).pack(anchor="w")
            tk.Label(footer, text=badge, font=("Helvetica Neue", 10, "bold"),
                     bg=bbg, fg=bfg, padx=6, pady=2).pack(anchor="w", pady=(4, 0))

        tk.Label(parent, text="RECENT EVENTS", font=FONT_SMALL,
                 bg=C["bg"], fg=C["hint"]).pack(anchor="w", pady=(0, 6))
        evt_f = tk.Frame(parent, bg=C["surface"],
                         highlightbackground=C["border"], highlightthickness=1)
        evt_f.pack(fill="x")
        dot_colors = {"Motion": C["blue"], "Door": C["red"], "OK": C["green"]}
        for kind, text, time in EVENTS:
            row = tk.Frame(evt_f, bg=C["surface"])
            row.pack(fill="x", padx=12, pady=5)
            dot = tk.Canvas(row, width=10, height=10, bg=C["surface"], highlightthickness=0)
            dot.create_oval(1, 1, 9, 9, fill=dot_colors.get(kind, C["muted"]), outline="")
            dot.pack(side="left", padx=(0, 8))
            tk.Label(row, text=text, font=FONT_BODY, bg=C["surface"],
                     fg=C["text"]).pack(side="left")
            tk.Label(row, text=time, font=FONT_SMALL, bg=C["surface"],
                     fg=C["hint"]).pack(side="right")

    def _set_arm(self, mode, active_bg, active_fg):
        self.arm_mode.set(mode)
        for m, (btn, abg, afg) in self.arm_btns.items():
            if m == mode:
                btn.config(bg=abg, fg=afg)
            else:
                btn.config(bg=C["surface"], fg=C["muted"])

    # ── Energy panel ──────────────────────────────────────────────────────────

    def _build_energy(self, parent):
        # Stats
        stats = tk.Frame(parent, bg=C["bg"])
        stats.pack(fill="x", pady=(0, 14))
        self._stat_card(stats, "4.2 kWh",  "Today")
        self._stat_card(stats, "87 kWh",   "This month")
        self._stat_card(stats, "₹620",     "Est. bill",   color=C["green"])
        self._stat_card(stats, "−12%",     "vs last month", color=C["green"])

        tk.Label(parent, text="HOURLY USAGE TODAY (kWh)", font=FONT_SMALL,
                 bg=C["bg"], fg=C["hint"]).pack(anchor="w", pady=(0, 6))

        chart_f = tk.Frame(parent, bg=C["surface"],
                           highlightbackground=C["border"], highlightthickness=1)
        chart_f.pack(fill="x", pady=(0, 14))
        self._draw_bar_chart(chart_f)

        tk.Label(parent, text="BY DEVICE", font=FONT_SMALL,
                 bg=C["bg"], fg=C["hint"]).pack(anchor="w", pady=(0, 6))
        for name, kwh, pct in ENERGY:
            self._energy_device_row(parent, name, kwh, pct)

    def _draw_bar_chart(self, parent):
        W, H = 800, 160
        PAD_L, PAD_R, PAD_T, PAD_B = 36, 12, 12, 28
        hour_now = datetime.datetime.now().hour
        hours = list(range(hour_now + 1))
        values = [HOURLY_PATTERN[h] for h in hours]
        max_v = max(values) if values else 1

        cv = tk.Canvas(parent, width=W, height=H, bg=C["surface"], highlightthickness=0)
        cv.pack(fill="x", padx=10, pady=10)

        chart_w = W - PAD_L - PAD_R
        chart_h = H - PAD_T - PAD_B
        n = len(hours)
        bar_w = max(4, chart_w // n - 3)

        for i, (h, v) in enumerate(zip(hours, values)):
            x = PAD_L + i * (chart_w // n) + (chart_w // n - bar_w) // 2
            bar_h = int((v / max_v) * chart_h)
            y0 = PAD_T + chart_h - bar_h
            y1 = PAD_T + chart_h
            cv.create_rectangle(x, y0, x + bar_w, y1,
                                 fill=C["blue"], outline="")
            if n <= 12 or h % 3 == 0:
                label = f"{h}am" if h < 12 else ("12pm" if h == 12 else f"{h-12}pm")
                if h == 0: label = "12am"
                cv.create_text(x + bar_w // 2, H - 8, text=label,
                               fill=C["hint"], font=("Helvetica Neue", 8))

        # y-axis labels
        for step in [0.1, 0.2, 0.3]:
            y = PAD_T + chart_h - int((step / max_v) * chart_h)
            if 0 < y < H:
                cv.create_line(PAD_L - 4, y, W - PAD_R, y,
                               fill=C["border"], dash=(2, 4))
                cv.create_text(PAD_L - 6, y, text=f"{step:.1f}",
                               fill=C["hint"], font=("Helvetica Neue", 8), anchor="e")

    def _energy_device_row(self, parent, name, kwh, pct):
        row = tk.Frame(parent, bg=C["surface"],
                       highlightbackground=C["border"], highlightthickness=1)
        row.pack(fill="x", pady=(0, 6))
        ico_f = tk.Frame(row, bg=C["blue_bg"], width=40, height=40)
        ico_f.pack(side="left", padx=(10, 10), pady=10)
        ico_f.pack_propagate(False)
        icons = {"AC Unit":"❄️","Refrigerator":"🧊","Smart TV":"📺",
                 "Lights (all)":"💡","Other":"🔌"}
        tk.Label(ico_f, text=icons.get(name, "🔌"), font=("Helvetica Neue", 18),
                 bg=C["blue_bg"], fg=C["blue"]).place(relx=.5, rely=.5, anchor="center")
        info = tk.Frame(row, bg=C["surface"])
        info.pack(side="left", fill="both", expand=True, pady=10)
        header = tk.Frame(info, bg=C["surface"])
        header.pack(fill="x")
        tk.Label(header, text=name, font=FONT_HEADER, bg=C["surface"],
                 fg=C["text"], anchor="w").pack(side="left")
        tk.Label(header, text=f"{kwh} kWh · {pct}%", font=FONT_SMALL,
                 bg=C["surface"], fg=C["muted"]).pack(side="right", padx=10)
        bar_host = tk.Frame(info, bg=C["bg"], height=6)
        bar_host.pack(fill="x", pady=(4, 0), padx=(0, 10))
        bar_host.pack_propagate(False)
        bar_host.update_idletasks()
        bar_fill = tk.Frame(bar_host, bg=C["blue"], height=6)
        bar_fill.place(x=0, y=0, relheight=1,
                       relwidth=min(pct / 100, 1.0))


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = HomeAutomationApp()
    app.mainloop()