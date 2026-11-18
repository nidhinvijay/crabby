# Claude crab pet: a little crab that walks around your screen while Claude works.
#
# - Reads small state files written by the crabby mod (state-*.json in this folder): one crab per live Claude chat,
#   plus one helper crab per running subagent. With two or more chats, hover over a crab to see its project name.
# - Draws only on your screen. No network, no other files touched.
# - Drag it with the mouse. Let go near the left or right edge and it sticks there; near the
#   top it hangs for a moment, then drops; anywhere else it falls to the bottom.
# - Double-click it to change its outfit. It also changes outfit by itself every few minutes.
# - Right-click it for a menu: outfit, size, sleep, quit.
# - It gets tired when your plan usage is high,
#   shakes when a turn fails, holds a prop for the tool Claude uses, and jumps when Claude needs you.
# - Remembers outfit, size and resting spot in settings.json (this folder).
# - Stop it: run /pet again in Claude, or create a file named "quit" here.
import ctypes
import datetime
import glob
import json
import math
import os
import random
import sys
import time
import traceback
import zlib
import tkinter as tk

BASE = os.path.dirname(os.path.abspath(__file__))
ALIVE = os.path.join(BASE, 'alive')
QUIT = os.path.join(BASE, 'quit')
LOG = os.path.join(BASE, 'pet.log')
DEBUG = bool(os.environ.get('CRAB_DEBUG'))
SETTINGS = os.path.join(BASE, 'settings.json')
MAC = sys.platform == 'darwin'
KEY = 'systemTransparent' if MAC else '#fe00fe'  # this colour becomes see-through (and click-through on Windows)
BUSY_STALE_S = 20 * 60     # ignore "busy" from a session that went quiet this long ago
BOTTOM_MARGIN = 0          # gap between the crab's feet and the bottom edge (0 = standing right on it; was 14)
STICK_PX = 70              # let go this close to an edge and it sticks
GRAVITY = 2200.0
OUTFITS = ['other', 'chef', 'pirate', 'dev', 'student', 'manager', 'teacher', 'wizard', 'scientist', 'ninja', 'musician', 'gardener', 'viking', 'santa']
OUTFIT_EVERY = (150, 420)  # seconds, random between these

PET_HOLD_S = 0.45          # press and hold this long without moving = petting
BREAK_AFTER_S = 3600       # after this long of non-stop work the crab stretches and yawns ("take a break")
BREAK_EVERY_S = 1800       # ...and again every this long while the work goes on
DEEP_AFTER = int(os.environ.get('CRAB_DEEP', 600))  # seconds idle before it stops redrawing completely
MIGRATE_AFTER = (300, 300)  # seconds on a secondary screen before the crab walks over to the main screen
WANDER_IDLE_S = 60         # after Claude goes quiet the crab wanders this long, then walks to its bed in the bottom-right corner
AWAKE_FOR = 90           # seconds it stays awake (tricks) after it gets home, then it dozes
TRICK_DUR = {'blink': 0.25, 'wave': 1.6, 'hop': 0.6, 'yawn': 1.3}
TOOL_PROP = {'Read': 'lens', 'Grep': 'lens', 'Glob': 'lens', 'WebSearch': 'lens', 'WebFetch': 'lens', 'ToolSearch': 'lens',
             'Edit': 'hammer', 'Write': 'hammer', 'NotebookEdit': 'hammer', 'MultiEdit': 'hammer',
             'Bash': 'term', 'PowerShell': 'term'}
NAMES = {'other': 'Plain', 'chef': 'Chef', 'pirate': 'Pirate', 'dev': 'Dev', 'student': 'Student', 'manager': 'Manager', 'teacher': 'Teacher', 'wizard': 'Wizard', 'scientist': 'Scientist', 'ninja': 'Ninja', 'musician': 'Musician', 'gardener': 'Gardener', 'viking': 'Viking', 'santa': 'Santa hat'}
if time.localtime().tm_mon != 12 and 'santa' in OUTFITS:
    OUTFITS.remove('santa')  # the Santa hat is for December only
CLAY = '#d97757'
UI_FONT, SYM_FONT = ('Helvetica Neue', 'Apple Symbols') if MAC else ('Segoe UI', 'Segoe UI Symbol')

SPR_W, SPR_H = 30, 26      # sprite size in sprite pixels
PAD, TOP_PAD = 4, 30       # TOP_PAD: room beside the crab for the bubble, hearts and z's


def load_prefs():
    try:
        with open(SETTINGS, encoding='utf-8') as fh:
            p = json.load(fh)
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


PREFS = load_prefs()


def save_prefs():
    try:
        tmp = SETTINGS + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(PREFS, fh)
        os.replace(tmp, SETTINGS)
    except Exception:
        pass


def set_scale(n):
    global SCALE, FLOOR_W, FLOOR_H, WALL_W, WALL_H
    SCALE = max(2, min(5, int(n)))
    FLOOR_W, FLOOR_H = SPR_W * SCALE + PAD * 2, SPR_H * SCALE + TOP_PAD + PAD
    WALL_W, WALL_H = SPR_H * SCALE + TOP_PAD + PAD, SPR_W * SCALE + PAD * 2


set_scale(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else PREFS.get('size', 3))
APP = {}                   # callbacks the crab's menu uses (filled in main)


def dims(S):
    """Window sizes for a crab drawn at scale S: standing/hanging, and on a wall."""
    return (SPR_W * S + PAD * 2, SPR_H * S + TOP_PAD + PAD, SPR_H * S + TOP_PAD + PAD, SPR_W * S + PAD * 2)


def log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%H:%M:%S ') + msg + '\n')
    except Exception:
        pass


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


try:
    ctypes.windll.winmm.timeBeginPeriod(1)  # finer timer, so the drop animation can run at 60 fps
except Exception:
    pass


class RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]


# ---- macOS: screens and window flags through the Objective-C runtime (no extra packages) ----
if MAC:
    import ctypes.util
    _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
    ctypes.cdll.LoadLibrary(ctypes.util.find_library('AppKit'))
    _objc.objc_getClass.restype = ctypes.c_void_p
    _objc.objc_getClass.argtypes = [ctypes.c_char_p]
    _objc.sel_registerName.restype = ctypes.c_void_p
    _objc.sel_registerName.argtypes = [ctypes.c_char_p]

    class CGRect(ctypes.Structure):
        _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double), ('w', ctypes.c_double), ('h', ctypes.c_double)]

    def _msg(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
        f = ctypes.cast(_objc.objc_msgSend, ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
        return f(obj, _objc.sel_registerName(sel), *args)

    def _nsapp():
        return _msg(_objc.objc_getClass(b'NSApplication'), b'sharedApplication')

    def mac_accessory():
        """No Dock icon and no app menu: the crab is a background helper."""
        _msg(_nsapp(), b'setActivationPolicy:', 1, argtypes=(ctypes.c_long,))

    def mac_all_spaces():
        """Show every crab window on all Spaces, also next to full-screen apps."""
        wins = _msg(_nsapp(), b'windows')
        for i in range(_msg(wins, b'count', restype=ctypes.c_ulong)):
            nw = _msg(wins, b'objectAtIndex:', i, argtypes=(ctypes.c_ulong,))
            _msg(nw, b'setCollectionBehavior:', 1 | 16 | 256, argtypes=(ctypes.c_ulong,))  # all spaces, stationary, full-screen aux
            _msg(nw, b'setHasShadow:', False, argtypes=(ctypes.c_bool,))
            _msg(nw, b'setLevel:', 25, argtypes=(ctypes.c_long,))  # status-bar level: above normal windows and Dock replacements
            _msg(nw, b'setHidesOnDeactivate:', False, argtypes=(ctypes.c_bool,))

    def mac_left_down():
        """Is the left mouse button held right now (asked from the system, not from Tk's events)?"""
        return bool(_msg(_objc.objc_getClass(b'NSEvent'), b'pressedMouseButtons', restype=ctypes.c_ulong) & 1)

    def mac_screens():
        """[(work, full, primary)] in Tk coordinates (origin top-left of the main screen, y down).
        The work area leaves out the menu bar and the Dock, so the crab stands on top of the Dock."""
        arr = _msg(_objc.objc_getClass(b'NSScreen'), b'screens')
        raw = []
        for i in range(_msg(arr, b'count', restype=ctypes.c_ulong)):
            sc = _msg(arr, b'objectAtIndex:', i, argtypes=(ctypes.c_ulong,))
            raw.append((_msg(sc, b'frame', restype=CGRect), _msg(sc, b'visibleFrame', restype=CGRect)))
        if not raw:
            return []
        ph = raw[0][0].h  # Cocoa measures from the bottom of the main screen

        def flip(r):
            return (int(round(r.x)), int(round(ph - (r.y + r.h))), int(round(r.x + r.w)), int(round(ph - r.y)))
        return [(flip(v), flip(f), i == 0) for i, (f, v) in enumerate(raw)]


if MAC:
    _V = ctypes.c_void_p
    _cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreFoundation'))
    _cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreGraphics'))
    _cg.CGWindowListCopyWindowInfo.restype = _V
    _cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    _cg.CGRectMakeWithDictionaryRepresentation.argtypes = [_V, ctypes.POINTER(CGRect)]
    _cf.CFArrayGetCount.argtypes = [_V]
    _cf.CFArrayGetCount.restype = ctypes.c_long
    _cf.CFArrayGetValueAtIndex.argtypes = [_V, ctypes.c_long]
    _cf.CFArrayGetValueAtIndex.restype = _V
    _cf.CFDictionaryGetValue.argtypes = [_V, _V]
    _cf.CFDictionaryGetValue.restype = _V
    _cf.CFNumberGetValue.argtypes = [_V, ctypes.c_long, _V]
    _cf.CFStringCreateWithCString.argtypes = [_V, ctypes.c_char_p, ctypes.c_uint32]
    _cf.CFStringCreateWithCString.restype = _V
    _cf.CFRelease.argtypes = [_V]
    _K_BOUNDS = _cf.CFStringCreateWithCString(None, b'kCGWindowBounds', 0x08000100)
    _K_LAYER = _cf.CFStringCreateWithCString(None, b'kCGWindowLayer', 0x08000100)
    _K_PID = _cf.CFStringCreateWithCString(None, b'kCGWindowOwnerPID', 0x08000100)

    def mac_bars():
        """Bars that other apps pin to a screen edge above normal windows (uBar and other Dock replacements):
        [(left, top, right, bottom)]. The real Dock is already left out of the work area by macOS."""
        out, me = [], os.getpid()
        arr = _cg.CGWindowListCopyWindowInfo(1, 0)  # on-screen windows only
        if not arr:
            return out
        try:
            for i in range(_cf.CFArrayGetCount(arr)):
                d = _cf.CFArrayGetValueAtIndex(arr, i)
                n = ctypes.c_int(0)
                lv, pv, bv = _cf.CFDictionaryGetValue(d, _K_LAYER), _cf.CFDictionaryGetValue(d, _K_PID), _cf.CFDictionaryGetValue(d, _K_BOUNDS)
                if not (lv and bv):
                    continue
                _cf.CFNumberGetValue(lv, 3, ctypes.byref(n))
                if not 0 < n.value < 1000:  # normal windows are 0; the menu bar and system overlays sit far higher
                    continue
                if pv:
                    pid = ctypes.c_int(0)
                    _cf.CFNumberGetValue(pv, 3, ctypes.byref(pid))
                    if pid.value == me:
                        continue
                r = CGRect()
                if _cg.CGRectMakeWithDictionaryRepresentation(bv, ctypes.byref(r)):
                    out.append((int(r.x), int(r.y), int(r.x + r.w), int(r.y + r.h)))
        finally:
            _cf.CFRelease(arr)
        return out

    def mac_apply_bars(mons):
        """A wide, low bar along the bottom of a screen counts as the floor: the crab stands on top of it."""
        for bl, bt, br, bb in mac_bars():
            for m in mons:
                l, t, r, b = m.full
                if bl <= l + 4 and br >= r - 4 and abs(bb - b) <= 4 and 12 <= bb - bt <= (b - t) // 4 and (br - bl) >= (r - l) * 0.6:
                    wl, wt, wr, wb = m.work
                    m.work = (wl, wt, wr, min(wb, bt))


def work_area():
    if MAC:
        try:
            return mac_screens()[0][0]
        except Exception:
            return 0, 0, 1280, 720
    r = RECT()
    ok = ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    if not ok or r.right <= r.left:
        return 0, 0, 1280, 720
    return r.left, r.top, r.right, r.bottom


class POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


def parse_iso(v):
    try:
        return datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_ulong), ('rcMonitor', RECT), ('rcWork', RECT), ('dwFlags', ctypes.c_ulong)]


try:
    ctypes.windll.user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
except Exception:
    pass


class Mon:
    """One screen: its usable (work) area, its full area, and which sides are outer edges of the whole desktop."""

    def __init__(self, work, full, primary):
        self.work, self.full, self.primary = work, full, primary
        self.outer = [True, True, True, True]  # left, top, right, bottom: False when another screen touches there


MON_CACHE = {}


def get_monitors():
    found = []
    if MAC:
        try:
            found = [Mon(w, f, p) for w, f, p in mac_screens()]
        except Exception:
            found = []
        try:
            mac_all_spaces()  # Tk can drop the window level again; keep the crabs in front
        except Exception:
            pass
    else:
        u = ctypes.windll.user32
        PROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_void_p)

        def cb(h, dc, rc, lp):
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if u.GetMonitorInfoW(h, ctypes.byref(mi)):
                w, f = mi.rcWork, mi.rcMonitor
                found.append(Mon((w.left, w.top, w.right, w.bottom), (f.left, f.top, f.right, f.bottom), bool(mi.dwFlags & 1)))
            return 1

        try:
            u.EnumDisplayMonitors(None, None, PROC(cb), 0)
        except Exception:
            found = []
    if not found:
        a = work_area()
        found.append(Mon(a, a, True))
    found.sort(key=lambda m: not m.primary)
    same = []
    for m in found:  # reuse the same Mon object for the same screen, so a crab's remembered screen stays valid
        c = MON_CACHE.get(m.full)
        if c is None:
            c = MON_CACHE[m.full] = m
        else:
            c.work, c.primary = m.work, m.primary
        same.append(c)
    for k in [k for k in MON_CACHE if k not in {m.full for m in same}]:
        del MON_CACHE[k]
    found = same
    link_monitors(found)
    try:
        (mac_apply_bars if MAC else apply_taskbars)(found)
    except Exception:
        pass
    return found


try:
    _u2 = ctypes.windll.user32
    _u2.FindWindowExW.restype = ctypes.c_void_p
    _u2.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    _u2.IsWindowVisible.argtypes = [ctypes.c_void_p]
except Exception:
    pass


def apply_taskbars(mons):
    """An auto-hide taskbar that is showing counts as the floor: the crab stands on it instead of behind it.
    The real taskbar windows are asked every time, so a taskbar that slides up or away is noticed."""
    u = ctypes.windll.user32
    for cls in ('Shell_TrayWnd', 'Shell_SecondaryTrayWnd'):
        h = u.FindWindowExW(None, None, cls, None)
        while h:
            r = RECT()
            try:
                ok = u.IsWindowVisible(h) and u.GetWindowRect(h, ctypes.byref(r))
            except Exception:
                ok = False
            if ok and (r.right - r.left) > (r.bottom - r.top):  # a bar along the bottom (or top) of a screen
                cx = (r.left + r.right) // 2
                for m in mons:
                    l, t, rr, b = m.full
                    if l <= cx < rr and r.top > t + (b - t) // 2 and b - r.top >= 12:  # at least 12 px of it is on screen
                        wl, wt, wr, wb = m.work
                        m.work = (wl, wt, wr, min(wb, r.top))
            h = u.FindWindowExW(None, h, cls, None)


def link_monitors(mons):
    """An edge is 'inner' (the crab may walk across it) when another screen touches it."""
    for m in mons:
        m.outer = [True, True, True, True]
    for m in mons:
        l, t, r, b = m.full
        for o in mons:
            if o is m:
                continue
            ol, ot, orr, ob = o.full
            v = min(b, ob) - max(t, ot) > 0
            hz = min(r, orr) - max(l, ol) > 0
            if abs(orr - l) <= 2 and v:
                m.outer[0] = False
            if abs(ol - r) <= 2 and v:
                m.outer[2] = False
            if abs(ob - t) <= 2 and hz:
                m.outer[1] = False
            if abs(ot - b) <= 2 and hz:
                m.outer[3] = False


def pick_mon(mons, cx, cy):
    """The screen that holds the point, or the nearest one."""
    best, bd = mons[0], 1e18
    for m in mons:
        l, t, r, b = m.work
        dx, dy = max(l - cx, 0, cx - r), max(t - cy, 0, cy - b)
        d = dx * dx + dy * dy
        if d < bd:
            best, bd = m, d
    return best


def in_any(mons, cx, cy):
    return any(m.work[0] <= cx < m.work[2] and m.work[1] <= cy < m.work[3] for m in mons)


def tool_window(win):
    """Hide it from the taskbar and Alt+Tab, and don't steal focus when clicked."""
    if MAC:
        mac_all_spaces()
        return
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
    user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x80 | 0x08000000)  # LAYERED | TOOLWINDOW | NOACTIVATE


with open(os.path.join(BASE, 'sprites.json'), encoding='utf-8') as fh:
    SPR = json.load(fh)


def conv(c):
    """tk has no alpha: drop faint glass, make strong glints solid."""
    if c.startswith('rgba'):
        p = [x.strip() for x in c[5:-1].split(',')]
        if float(p[3]) < 0.5:
            return None
        return '#%02x%02x%02x' % (int(p[0]), int(p[1]), int(p[2]))
    return c


SPRITES = {}
for name, rects in SPR.items():
    out = []
    for x, y, w, h, c, cls in rects:
        col = conv(c)
        if col is not None:
            out.append((x, y, w, h, col, cls))
    SPRITES[name] = out


def place(surf, x, y, w, h, dirn, S=None):
    """Map a sprite rectangle to canvas pixels for the surface the crab stands on."""
    S = S or SCALE
    if dirn < 0:
        x = SPR_W - x - w
    if surf == 'floor':
        return PAD + x * S, TOP_PAD + y * S, PAD + (x + w) * S, TOP_PAD + (y + h) * S
    if surf == 'ceil':
        yy = SPR_H - y - h
        return PAD + x * S, PAD + yy * S, PAD + (x + w) * S, PAD + (yy + h) * S
    if surf == 'left':
        sx = PAD + (SPR_H - y - h) * S
        return sx, PAD + x * S, sx + h * S, PAD + (x + w) * S
    sx = TOP_PAD + y * S  # right wall
    return sx, PAD + x * S, sx + h * S, PAD + (x + w) * S


class Crab:
    def __init__(self, root, cid, tier, main, mons, sid='', slot=0):
        self.id, self.main = cid, main
        self.sid, self.slot, self.label = sid, slot, ''
        self.climb, self.wall_until, self.roam_fall, self.vx = None, None, False, 0.0
        self.pose, self.pose_until = None, 0.0          # 'greet' (meeting a friend), 'break' (stretch), 'joy' (limit reset)
        self.greet_cd, self.next_break, self.busy_since = 0.0, 0.0, 0
        self.cup, self.info = False, {}
        self.petting, self.moved, self.press_t, self.press_xy = False, False, 0.0, (0, 0)
        self.tip, self.tip_after = None, None
        self.tier = tier if tier in SPRITES else 'other'
        self.mons = mons
        self.mon = mons[0] if main else random.choice(mons)
        bounds = self.bounds = self.mon.work
        self.surf = 'floor'
        self.scale = SCALE if main else max(1, SCALE - 1)  # helpers are one step smaller than the main crab
        self.fw, self.fh, self.ww, self.wh = dims(self.scale)
        self.w, self.h = self.fw, self.fh
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.configure(bg=KEY)
        if MAC:
            self.win.attributes('-transparent', True)
        else:
            self.win.attributes('-transparentcolor', KEY)
        self.cv = tk.Canvas(self.win, width=self.w, height=self.h, bg=KEY, highlightthickness=0, bd=0, cursor='pointinghand' if MAC else 'hand2')
        self.cv.pack()
        left, top, right, bottom = bounds
        self.x = float(random.randint(left, max(left, right - self.w)))
        self.y = float(self.floor_y())
        if not main:
            self.y = float(random.randint(top, max(top, self.floor_y())))
        self.home = (float(right - self.w - 24), float(self.floor_y()))
        self.dir, self.phase, self.phase_t = 1, 0, 0.0
        self.mode, self.pause_until = 'pause', 0.0
        self.tx, self.ty = self.x, self.y
        self.vy = 0.0
        self.ceil_until = 0.0
        self.speed = (70.0 if main else random.uniform(55.0, 95.0)) * self.scale / 2
        self.resting = False
        self.shown = None
        self.pos_shown = None
        self.next_outfit = time.time() + random.uniform(*OUTFIT_EVERY) if main else None
        now0 = time.time()
        self.sleeping, self.asleep, self.deep = False, False, False
        self.idle_since, self.rest_since, self.prev_mode = now0, now0, ''
        self.trick, self.trick_t0, self.next_trick = None, 0.0, now0 + 4
        self.shake_until, self.ox, self.oy = 0.0, 0, 0
        self.mood, self.tool, self.needs = 'ok', '', False
        self.exhausted = False  # usage at 90% or more: an idle crab goes to bed at once instead of wandering
        if main:  # the sleeping spot: the remembered one (or the corner of the main screen), shifted along the floor per chat
            hx0, m0, remembered = None, None, False
            if isinstance(PREFS.get('home_x'), (int, float)):
                hx0 = float(PREFS['home_x'])
                m0 = next((m for m in mons if m.work[0] <= hx0 + self.w / 2 < m.work[2]), None)
                remembered = m0 is not None
            if m0 is None:
                m0 = mons[0]
                hx0 = float(m0.work[2] - self.w - 24)
            hx0 = min(max(hx0, m0.work[0]), m0.work[2] - self.w)
            hx = hx0 - slot * (self.w + 8)
            if hx < m0.work[0]:
                hx = min(hx0 + slot * (self.w + 8), m0.work[2] - self.w)
            self.set_mon(m0)
            self.home = (hx, float(self.floor_y()))
            if remembered or slot:
                self.x, self.y = hx, float(self.floor_y())
        self.fx_t0, self.fx_swapped, self.fx_new = None, False, 'other'
        self.drag_off = (0, 0)
        self.win.geometry('%dx%d+%d+%d' % (self.w, self.h, int(self.x), int(self.y)))
        self.win.update_idletasks()
        try:
            tool_window(self.win)
        except Exception:
            log('tool_window failed: ' + traceback.format_exc())
        self.cv.bind('<ButtonPress-1>', self.on_press)
        self.cv.bind('<B1-Motion>', self.on_motion)
        self.cv.bind('<ButtonRelease-1>', self.on_release)
        self.cv.bind('<Double-Button-1>', self.on_double)
        self.cv.bind('<Button-3>', self.on_menu)
        if MAC:  # on a Mac the right button is button 2, and Control-click is a right click too
            self.cv.bind('<Button-2>', self.on_menu)
            self.cv.bind('<Control-ButtonPress-1>', self.on_menu)
        self.cv.bind('<Enter>', self.on_enter)
        self.cv.bind('<Leave>', lambda ev: self.hide_tip())

    # ---- geometry helpers ----
    def floor_y(self):
        return self.bounds[3] - BOTTOM_MARGIN - self.fh + PAD  # + PAD: the window has a see-through strip under the feet

    def bed(self):
        """The sleeping spot: the bottom-right corner of the screen it is on (the main screen once it has migrated), shifted left per chat."""
        m = getattr(self, 'rest_mon', None)
        if m is None or m not in self.mons:
            m = self.mon
        x = m.work[2] - self.fw - 24 - self.slot * (self.fw + 6)
        x = float(min(max(x, m.work[0]), m.work[2] - self.fw))
        return x, float(m.work[3] - BOTTOM_MARGIN - self.fh + PAD)

    def set_mon(self, mon):
        self.mon, self.bounds = mon, mon.work

    def refresh_mons(self, mons):
        """Screens may change (plugged, moved, taskbar): keep the crab on one that exists."""
        self.mons = mons
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        m = pick_mon(mons, cx, cy)
        self.set_mon(m)
        if self.mode != 'drag' and not in_any(mons, cx, cy):
            l, t, r, b = m.work
            self.x = float(min(max(self.x, l), r - self.w))
            self.y = float(min(max(self.y, t), b - BOTTOM_MARGIN - self.h + PAD))
            self.pos_shown = None
        if self.surf == 'floor' and self.mode not in ('drag', 'jump', 'fall', 'ceil'):  # the floor may have moved (taskbar up or away)
            fy = self.floor_y()
            if self.y > fy + 1:
                self.y, self.pos_shown = float(fy), None  # the taskbar slid up: stand on top of it
            elif self.y < fy - 2:
                self.mode, self.vy, self.roam_fall = 'fall', 0.0, True  # the taskbar went away: drop to the floor at once
        hx = self.home[0]
        hm = pick_mon(mons, hx + self.fw / 2, self.home[1])
        hx = min(max(hx, hm.work[0]), hm.work[2] - self.fw)
        self.home = (hx, float(hm.work[3] - BOTTOM_MARGIN - self.fh + PAD))

    def set_surface(self, surf):
        if surf == self.surf:
            return
        self.surf = surf
        self.w, self.h = (self.fw, self.fh) if surf in ('floor', 'ceil') else (self.ww, self.wh)
        self.cv.config(width=self.w, height=self.h)
        self.win.geometry('%dx%d+%d+%d' % (self.w, self.h, int(self.x), int(self.y)))
        self.shown = None
        self.pos_shown = None

    # ---- hover label (only when several chats each have a crab) ----
    def on_enter(self, ev):
        if self.label and self.mode != 'drag' and self.tip is None and self.tip_after is None:
            self.tip_after = self.win.after(350, self.show_tip)

    def show_tip(self):
        self.tip_after = None
        if not self.label or self.tip is not None:
            return
        try:
            t = tk.Toplevel(self.win)
            t.overrideredirect(True)
            t.attributes('-topmost', True)
            tk.Label(t, text=self.card_text(), justify='left', bg='#2b2b2f', fg='#f4f3ee', font=(UI_FONT, 9), padx=8, pady=4).pack()
            t.update_idletasks()
            tw, th = t.winfo_reqwidth(), t.winfo_reqheight()
            l, tp, r, b = self.bounds
            x = int(min(max(self.x + self.w / 2 - tw / 2, l), r - tw))
            y = int(self.y + TOP_PAD - th - 6) if self.surf == 'floor' else int(self.y - th - 4)
            if y < tp:
                y = int(self.y + self.h + 2)
            t.geometry('+%d+%d' % (x, y))
            if MAC:
                t.update_idletasks()
                mac_all_spaces()
            else:
                hwnd = ctypes.windll.user32.GetParent(t.winfo_id()) or t.winfo_id()
                st_ = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, st_ | 0x80 | 0x08000000)  # TOOLWINDOW | NOACTIVATE
            self.tip = t
        except Exception:
            self.tip = None

    def card_text(self):
        """What the hover card says: project, what the chat is doing, for how long, and the plan usage."""
        i = self.info or {}
        lines = [self.label]
        if i:
            if i.get('needs'):
                what = 'Waiting for you'
            elif i.get('busy'):
                t = i.get('tool', '')
                what = {'lens': 'Looking through files', 'hammer': 'Editing files', 'term': 'Running commands'}.get(TOOL_PROP.get(t, ''), ('Using ' + t) if t else 'Thinking')
            else:
                what = 'Resting'
            n = i.get('agents', 0)
            if n:
                what += ' · %d helper%s' % (n, 's' if n > 1 else '')
            lines.append(what)
            if self.busy_since:
                mins = int((time.time() * 1000 - self.busy_since) / 60000)
                lines.append('Working for %d min' % mins if mins >= 1 else 'Just started')
        u, resets = APP['usage']() if 'usage' in APP else (-1, 0)
        if u >= 0:
            line = 'Plan: %d%% used' % round(u)
            if resets > time.time():
                secs = int(resets - time.time())
                h, m = secs // 3600, (secs % 3600) // 60
                line += (' · resets in %dh %02dm' % (h, m)) if h else (' · resets in %d min' % m)
            lines.append(line)
        return '\n'.join(lines)

    def hide_tip(self):
        if self.tip_after is not None:
            try:
                self.win.after_cancel(self.tip_after)
            except Exception:
                pass
            self.tip_after = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None

    def destroy(self):
        self.hide_tip()
        try:
            self.win.destroy()
        except Exception:
            pass

    # ---- mouse: drag, drop, stick ----
    def on_press(self, ev):
        self.hide_tip()
        if DEBUG:
            log('press %s at %d,%d' % (self.sid[:6], ev.x_root, ev.y_root))
        self.idle_since = time.time()
        self.press_t, self.press_xy, self.moved, self.petting = time.time(), (ev.x_root, ev.y_root), False, False
        self.wall_until, self.climb = None, None
        self.mode = 'drag'
        self.vy = 0.0
        if self.surf != 'floor':
            self.set_surface('floor')
            self.x, self.y = ev.x_root - self.w / 2, ev.y_root - self.h / 2
            self.drag_off = (self.w / 2, self.h / 2)
            self.win.geometry('+%d+%d' % (int(self.x), int(self.y)))
        else:
            self.drag_off = (ev.x_root - self.x, ev.y_root - self.y)

    def on_motion(self, ev):
        if self.mode != 'drag':
            return
        if not self.moved and abs(ev.x_root - self.press_xy[0]) + abs(ev.y_root - self.press_xy[1]) > 5:
            self.moved, self.petting = True, False
        self.x, self.y = ev.x_root - self.drag_off[0], ev.y_root - self.drag_off[1]
        self.pos_shown = (int(self.x), int(self.y))
        self.win.geometry('+%d+%d' % (int(self.x), int(self.y)))

    def mac_drag_poll(self):
        """macOS stops sending motion events when a fast pointer leaves the small window, which dropped the crab.
        While dragging, follow the real pointer and watch the real button instead."""
        class E:
            pass
        e = E()
        e.x_root, e.y_root = self.win.winfo_pointerxy()
        if mac_left_down():
            self.on_motion(e)
        else:
            self.on_release(e, real=True)

    def on_release(self, ev, real=False):
        if self.mode != 'drag':
            return
        if MAC and not real:
            # Tk reports a release when a fast pointer outruns the window; trust only the real button (mac_drag_poll)
            if DEBUG:
                log('tk release ignored=%s' % mac_left_down())
            if mac_left_down():
                return
        if not self.moved:  # just a click or a pet, not a drag: stay where it is
            self.petting = False
            if self.y < self.floor_y() - 2:
                self.mode, self.vy, self.roam_fall = 'fall', 0.0, True
            else:
                self.mode, self.pause_until = 'pause', time.time() + 0.4
            return
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        mon = pick_mon(self.mons, cx, cy)  # the screen it was dropped on
        self.set_mon(mon)
        left, top, right, bottom = mon.work
        if self.main:  # only the outer edges of the whole desktop stick; inner edges are for walking across
            if cx - left < STICK_PX and mon.outer[0]:
                return self.attach('left')
            if right - cx < STICK_PX and mon.outer[2]:
                return self.attach('right')
            if cy - top < STICK_PX and mon.outer[1]:
                return self.attach('ceil')
        self.x = min(max(self.x, left), right - self.w)
        self.mode, self.vy = 'fall', 0.0

    def on_double(self, ev):
        if self.main and self.sleeping:
            self.sleeping = False
            self.idle_since = time.time()
        elif self.main and self.fx_t0 is None:
            self.start_fx(time.time())

    def on_menu(self, ev):
        if not self.main:
            return
        m = tk.Menu(self.win, tearoff=0)
        om = tk.Menu(m, tearoff=0)
        for o in OUTFITS:
            om.add_command(label=NAMES[o], command=lambda o=o: APP['outfit'](self, o))
        om.add_separator()
        om.add_command(label='Surprise me', command=lambda: APP['outfit'](self, None))
        m.add_cascade(label='Change outfit', menu=om)
        sm = tk.Menu(m, tearoff=0)
        for n, label in ((2, 'Small'), (3, 'Medium'), (4, 'Large'), (5, 'Extra large')):
            sm.add_command(label=label + (' (now)' if n == SCALE else ''), command=lambda n=n: APP['size'](n))
        m.add_cascade(label='Change size', menu=sm)
        m.add_command(label='Wake up' if self.sleeping else 'Put to sleep', command=lambda: APP['sleep'](self))
        m.add_command(label='Hide for 1 hour', command=APP['hide'])
        m.add_separator()
        m.add_command(label='Quit crab', command=APP['quit'])
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    def shake(self, now):
        self.shake_until = now + 1.3

    def start_pose(self, name, now, dur):
        if self.pose is None and self.surf == 'floor' and self.mode in ('walk', 'pause', 'rest') and self.fx_t0 is None:
            self.pose, self.pose_until = name, now + dur
            return True
        return False

    def attach(self, surf):
        left, top, right, bottom = self.bounds
        self.set_surface(surf)
        low = bottom - BOTTOM_MARGIN - self.h + PAD
        if surf == 'left':
            self.x, self.y = float(left), float(min(max(self.y, top), low))
        elif surf == 'right':
            self.x, self.y = float(right - self.w), float(min(max(self.y, top), low))
        else:  # hang from the top for a moment, then drop
            self.y = float(top)
            self.x = float(min(max(self.x, left), right - self.w))
            self.ceil_until = time.time() + 1.6
            self.mode = 'ceil'
            return
        self.mode, self.pause_until = 'pause', time.time() + 0.5
        self.win.geometry('+%d+%d' % (int(self.x), int(self.y)))

    # ---- outfit change ----
    def start_fx(self, now, want=None):
        used = APP['used'](self) if 'used' in APP else set()  # keep chats looking different
        choices = [o for o in OUTFITS if o != self.tier and o not in used] or [o for o in OUTFITS if o != self.tier]
        self.fx_new = want if want in OUTFITS else random.choice(choices)
        self.fx_t0, self.fx_swapped = now, False

    # ---- behaviour ----
    def pick_target(self):
        left, top, right, bottom = self.bounds
        low = bottom - BOTTOM_MARGIN - self.h + PAD
        if self.surf == 'floor':
            tm = self.mon
            if len(self.mons) > 1 and random.random() < 0.3:  # now and then, visit another screen
                tm = random.choice([m for m in self.mons if m is not self.mon])
            left, top, right, bottom = tm.work
            low = bottom - BOTTOM_MARGIN - self.h + PAD
            self.climb = None
            edges = [sd for sd, ok in (('left', tm.outer[0]), ('right', tm.outer[2])) if ok]
            if edges and tm is self.mon and random.random() < 0.25:  # sometimes go and climb a side wall of the desktop
                self.climb = random.choice(edges)
                self.tx = float(left) if self.climb == 'left' else float(right - self.w)
            else:
                self.tx = random.uniform(left, max(left, right - self.w))
            self.ty = low  # walk along the floor, not diagonally through the air
        else:  # crawling along a wall
            self.tx = self.x
            self.ty = random.uniform(top, max(top, low))
        self.mode = 'walk'

    def start_jump(self, d):
        k = self.scale / 3.0
        self.vy = -math.sqrt(2 * GRAVITY * random.uniform(40, 110) * k)
        self.vx = d * random.uniform(110, 260) * k
        self.dir, self.mode = d, 'jump'

    def go_main(self, now):
        """Head for the main screen: the main crab to its bed, a helper to a spot on the floor there."""
        pm = next((m for m in self.mons if m.primary), self.mons[0])
        self.climb = None
        if self.main:
            self.rest_mon = pm
            self.tx, self.ty = self.bed()
        else:
            l, t, r, b = pm.work
            self.tx = random.uniform(l, max(l, r - self.w))
            self.ty = float(b - BOTTOM_MARGIN - self.fh + PAD)
        self.mode = 'walk'

    def update(self, dt, now, working, hearts):
        active = False
        main = self.main
        mood = self.mood if main else 'ok'
        still = main and (self.sleeping or mood == 'dead')       # stays where it is
        calling = main and self.needs and mood != 'dead'         # Claude waits for the user
        if main and self.fx_t0 is None and self.mode not in ('drag', 'fall', 'ceil') and now >= self.next_outfit:
            self.start_fx(now)
        if self.fx_t0 is not None:
            active = True
            t = now - self.fx_t0
            if t >= 0.45 and not self.fx_swapped:
                self.tier, self.fx_swapped = self.fx_new, True
                if main and self.slot == 0:
                    PREFS['outfit'] = self.tier
                    save_prefs()
            if t >= 1.1:
                self.fx_t0 = None
                self.next_outfit = now + random.uniform(*OUTFIT_EVERY)

        if main:  # any activity resets the idle clock (a sleeping or collapsed crab only wakes for the mouse)
            act = self.mode in ('drag', 'fall', 'ceil') or self.fx_t0 is not None
            if not still:
                act = act or working or calling or hearts
            if act:
                self.idle_since = now

        # a crab left on a secondary screen walks over to the main screen after MIGRATE_AFTER seconds
        # (every crab: main or helper; from a wall too; a sleeping one wakes up for the walk)
        on_second = self.mon is not None and not self.mon.primary and mood != 'dead'
        if on_second and self.mode != 'drag':
            if getattr(self, 'mig_at', None) is None:
                self.mig_at = now + random.uniform(*MIGRATE_AFTER)
            elif now >= self.mig_at and self.mode not in ('fall', 'ceil', 'jump'):
                if self.surf != 'floor':
                    self.set_surface('floor')  # climb down from the wall first; it heads over once it lands
                    self.wall_until = None
                    self.mode, self.vy, self.roam_fall = 'fall', 0.0, True
                else:
                    if main:
                        self.sleeping = False
                        still = False
                    self.go_main(now)
                    self.mig_at = None
        else:
            self.mig_at = None
            if main and self.mon is not None and self.mon.primary:
                self.rest_mon = None

        # a wall climb that was the crab's own idea ends by itself: it climbs down
        if self.wall_until is not None:
            if self.surf not in ('left', 'right') or self.mode == 'drag':
                self.wall_until = None
            elif now >= self.wall_until and self.mode != 'fall':
                self.wall_until = None
                self.set_surface('floor')
                self.mode, self.vy, self.roam_fall = 'fall', 0.0, True

        if self.pose is not None and (now >= self.pose_until or self.mode in ('drag', 'fall', 'jump', 'ceil')):
            self.pose = None
        if not self.busy_since:
            self.next_break = 0.0
        elif (main and self.pose is None and now >= self.next_break and now * 1000 - self.busy_since > BREAK_AFTER_S * 1000
              and self.start_pose('break', now, 2.8)):
            self.next_break = now + BREAK_EVERY_S  # an hour of work: stretch and yawn

        walking = False
        if self.mode == 'drag':
            active, walking = True, True  # legs dangle and kick
            if main and not self.moved and now - self.press_t > PET_HOLD_S:
                self.petting = True  # held still: it is being petted
            if self.petting:
                walking = False
        elif self.mode == 'fall':
            active, walking = True, True
            self.vy += GRAVITY * dt
            self.y += self.vy * dt
            fy = self.floor_y()
            if self.y >= fy:
                self.y, self.vy = float(fy), 0.0
                self.home = (self.x, float(fy))  # rest where it landed
                if main and self.slot == 0 and not self.roam_fall and self.mon is self.mons[0]:  # only a drop on the main screen is remembered
                    PREFS['home_x'] = int(self.x)
                    save_prefs()
                self.roam_fall = False
                self.mode, self.pause_until = 'pause', now + 0.5
        elif self.mode == 'jump':
            active, walking = True, True
            self.vy += GRAVITY * dt
            self.y += self.vy * dt
            nx = self.x + self.vx * dt
            if in_any(self.mons, nx + self.w / 2, self.y + self.h / 2):
                self.x = nx
            else:
                self.vx = 0.0  # never jump off into space that belongs to no screen
            m2 = pick_mon(self.mons, self.x + self.w / 2, self.y + self.h / 2)
            if m2 is not self.mon:
                self.set_mon(m2)
            fy = self.floor_y()
            if self.y >= fy:
                self.y, self.vy, self.vx = float(fy), 0.0, 0.0
                self.mode, self.pause_until = 'pause', now + 0.15
        elif self.mode == 'ceil':
            active = True
            if now >= self.ceil_until:
                self.set_surface('floor')
                self.mode, self.vy = 'fall', 0.0
        elif self.pose is not None and self.mode in ('walk', 'pause', 'rest'):
            pass  # greeting a friend, stretching or hopping for joy: stand still for a moment
        else:
            idle_main = main and not working and not still and not calling
            if still or calling:
                self.mode = 'rest'
            elif idle_main and (self.surf == 'floor' or self.wall_until is not None) and not self.exhausted and now - self.idle_since < WANDER_IDLE_S:
                # just went quiet: wander around like when working, before going to bed
                if self.mode == 'rest':
                    self.mode, self.pause_until = 'pause', now + 0.3
                if self.mode == 'pause' and now >= self.pause_until:
                    self.pick_target()
            elif idle_main:
                if self.surf == 'floor':
                    self.climb = None
                    self.tx, self.ty = self.bed()
                    if abs(self.tx - self.x) > 2 or abs(self.ty - self.y) > 2:
                        self.mode = 'walk'
                    elif self.mode != 'walk':
                        self.mode = 'rest'
                else:
                    self.mode = 'rest'  # stuck to a wall: sleep right there
            else:
                if self.mode == 'rest':
                    self.mode, self.pause_until = 'pause', now + 0.3
                if self.mode == 'pause' and now >= self.pause_until:
                    self.pick_target()
            if self.mode == 'walk':
                dx, dy = self.tx - self.x, self.ty - self.y
                dist = (dx * dx + dy * dy) ** 0.5
                step = self.speed * dt * (0.55 if mood == 'tired' else 1.0)
                if dist <= step or dist < 1:
                    self.x, self.y = self.tx, self.ty
                    if self.climb and self.surf == 'floor':
                        side, self.climb = self.climb, None
                        self.attach(side)
                        self.wall_until = now + random.uniform(8, 20)
                    elif idle_main:
                        self.mode = 'rest'
                    else:
                        self.mode, self.pause_until = 'pause', now + random.uniform(0.6, 3.0)
                else:
                    if (self.surf == 'floor' and mood == 'ok' and dist > 180 * self.scale / 3 and abs(self.y - self.floor_y()) < 3
                            and random.random() < dt / 7.0):
                        self.start_jump(1 if dx > 0 else -1)  # now and then it hops
                    nx, ny = self.x + dx / dist * step, self.y + dy / dist * step
                    if self.surf == 'floor' and not in_any(self.mons, nx + self.w / 2, ny + self.h / 2):
                        nx, ny = self.tx, self.ty  # a gap between screens is in the way: hop over it
                    self.x, self.y = nx, ny
                    if self.surf == 'floor':
                        m2 = pick_mon(self.mons, nx + self.w / 2, ny + self.h / 2)
                        if m2 is not self.mon:
                            self.set_mon(m2)
                    if self.surf == 'floor':
                        if abs(dx) > 2:
                            self.dir = 1 if dx > 0 else -1
                    else:
                        self.dir = 1 if dy > 0 else -1
                    walking = True
                    active = True
        if self.mode != self.prev_mode:
            if self.mode == 'rest':
                self.rest_since, self.next_trick, self.trick = now, now + random.uniform(2, 5), None
            self.prev_mode = self.mode
        self.resting = self.mode == 'rest'

        at_rest = main and self.resting and not calling and mood != 'dead' and self.fx_t0 is None
        self.asleep = at_rest and (self.sleeping or now - self.rest_since > AWAKE_FOR)
        self.deep = main and self.resting and now - self.idle_since > DEEP_AFTER and not calling
        if at_rest and not self.asleep and not self.deep:  # idle tricks: blink, wave, hop, yawn
            if self.trick is None and now >= self.next_trick:
                self.trick, self.trick_t0 = random.choice(('blink', 'wave', 'hop', 'yawn')), now
            if self.trick is not None and now - self.trick_t0 > TRICK_DUR[self.trick]:
                self.trick, self.next_trick = None, now + random.uniform(5, 13)
        else:
            self.trick = None
        shaking = main and now < self.shake_until
        self.cup = bool(at_rest and not self.asleep and not self.deep and mood == 'ok' and self.tier == 'other'
                        and 6 <= time.localtime(now).tm_hour < 11)  # a cup of coffee in the morning
        # small window offsets: hop, jump for attention, shake after an error
        oy = ox = 0
        if self.surf == 'floor' and main:
            if calling:
                oy = -int(abs(math.sin(now * math.pi / 0.45)) * 5 * self.scale)
            elif self.pose == 'joy':
                oy = -int(abs(math.sin(now * math.pi / 0.4)) * 4 * self.scale)
            elif self.petting:
                oy = -int(abs(math.sin(now * math.pi / 0.3)) * 1.5 * self.scale)
            elif self.trick == 'hop':
                oy = -int(abs(math.sin(math.pi * (now - self.trick_t0) / 0.3)) * 4 * self.scale)
        if shaking:
            ox = int(math.sin(now * 45) * 6 * max(0.2, (self.shake_until - now) / 1.3))
        self.ox, self.oy = ox, oy
        if self.trick or calling or shaking or self.pose or self.petting:
            active = True

        if walking:
            self.phase_t += dt
            if self.phase_t >= 0.13:
                self.phase_t, self.phase = 0.0, (self.phase + 1) % 2
        self.draw(now, walking, working, hearts, mood, calling, shaking)
        return active

    # ---- drawing ----
    def anchor(self):
        """Where the bubble, hearts and z's start, and which way is 'up' away from the crab."""
        S = self.scale
        if self.surf == 'floor':
            return self.w / 2, TOP_PAD - 2, 0, -1, 1, 0
        if self.surf == 'ceil':
            return self.w / 2, self.h - TOP_PAD + 2, 0, 1, 1, 0
        if self.surf == 'left':
            return PAD + SPR_H * S + 2, self.h / 2, 1, 0, 0, 1
        return TOP_PAD - 2, self.h / 2, -1, 0, 0, 1

    def draw(self, now, walking, working, hearts, mood, calling, shaking):
        ix, iy = int(self.x) + self.ox, int(self.y) + self.oy
        if (ix, iy) != self.pos_shown:  # moving the window is cheap; redrawing the crab only when its pose changes
            self.pos_shown = (ix, iy)
            self.win.geometry('+%d+%d' % (ix, iy))
        main = self.main
        fx_t = None if self.fx_t0 is None else now - self.fx_t0
        trick = self.trick if main else None
        prop = TOOL_PROP.get(self.tool) if (main and working and not calling) else None
        pose = self.pose
        petting = main and self.petting
        smooth = fx_t is not None or pose is not None or petting or (main and ((hearts and self.surf == 'floor') or trick or calling or shaking))
        if smooth:
            tick = int(now * 15)
        elif self.deep:
            tick = -1  # fully static: no redraws at all
        elif self.resting and main and not self.asleep and mood == 'ok':
            tick = -1  # awake and sitting still: nothing moves until the next trick
        elif self.resting or working or mood == 'tired':
            tick = int(now * 3)
        else:
            tick = -1
        key = (self.phase if walking else -1, self.dir, walking, working, hearts, tick, self.surf, self.tier,
               mood, prop, calling, trick, shaking, self.deep, self.asleep, pose, petting, self.cup)
        if key == self.shown:
            return
        self.shown = key
        cv = self.cv
        cv.delete('all')
        S = self.scale
        surf, dirn = self.surf, self.dir

        def R(x, y, w, h, col):
            a, b, c2, d = place(surf, x, y, w, h, dirn, S)
            cv.create_rectangle(a, b, c2, d, fill=col, outline='')

        fr = tick if tick >= 0 else 0
        claws_up = pose in ('break', 'joy')
        waving = (trick == 'wave') or calling or pose == 'greet' or claws_up
        show_crab = fx_t is None or fx_t < 0.2 or fx_t > 0.5
        bob = 1 if walking and self.phase == 1 else 0
        if show_crab:
            for x, y, w, h, col, cls in SPRITES[self.tier]:
                if waving and x == 23 and w == 4 and h == 4 and y in (14, 10) and col.lower() == CLAY:
                    continue  # the right claw is drawn raised below
                if claws_up and x == 3 and w == 4 and h == 4 and y == 14 and col.lower() == CLAY:
                    continue  # so is the left one
                if cls == 'la':
                    dy = -1 if (walking and self.phase == 0) else 0
                elif cls == 'lb':
                    dy = -1 if (walking and self.phase == 1) else 0
                else:
                    dy = bob
                R(x, y + dy, w, h, col)
            eyes_shut = trick in ('blink', 'yawn') or pose == 'break' or petting or (mood == 'tired' and (fr % 9 == 0))
            if eyes_shut:
                R(9, 12, 2, 2, CLAY)
                R(19, 12, 2, 2, CLAY)
            elif mood == 'tired':  # heavy droopy lids
                R(9, 12, 2, 1, CLAY)
                R(19, 12, 2, 1, CLAY)
            if mood == 'dead':  # collapsed: X eyes, tongue out
                for ex in (9, 19):
                    R(ex, 12, 2, 2, CLAY)
                    a, b, c2, d = place(surf, ex, 12, 2, 2, dirn, S)
                    cv.create_line(a, b, c2, d, fill='#1f1e1d', width=2)
                    cv.create_line(a, d, c2, b, fill='#1f1e1d', width=2)
                R(14, 17, 3, 1, '#1f1e1d')
                R(15, 18, 2, 2, '#ff7f9f')
            if trick == 'yawn' or pose == 'break':
                t0 = self.trick_t0 if trick == 'yawn' else self.pose_until - 2.8
                R(13, 17, 4, 1 + max(0, min(3, int((now - t0) * 5))), '#1f1e1d')
            if petting:  # happy little smile
                R(12, 16, 1, 1, '#1f1e1d')
                R(13, 17, 4, 1, '#1f1e1d')
                R(17, 16, 1, 1, '#1f1e1d')
            if waving:
                k = (fr // 3) % 2 if tick >= 0 else 0
                R(23, 12, 2, 3, CLAY)
                R(23, 8 + 2 * k, 4, 4, CLAY)
                if claws_up:
                    R(3, 12, 2, 3, CLAY)
                    R(3, 8 + 2 * (1 - k), 4, 4, CLAY)
            if mood == 'tired':  # big round blue sweat drops sliding down both cheeks
                for dx0, dy0, off in ((4, 8, 0), (21, 8, 3)):
                    ty = dy0 + ((fr // 2 + off) % 6)
                    R(dx0 + 2, ty, 1, 1, '#2f8cff')
                    R(dx0 + 1, ty + 1, 3, 1, '#2f8cff')
                    R(dx0, ty + 2, 5, 2, '#2f8cff')
                    R(dx0 + 1, ty + 4, 3, 1, '#2f8cff')
                    R(dx0 + 1, ty + 2, 1, 1, '#d6efff')
            if prop == 'lens':
                sh = 0 if (fr // 2) % 2 == 0 else 1
                for rx, ry, rw, rh in ((26, 1, 2, 1), (26, 4, 2, 1), (25, 2, 1, 2), (28, 2, 1, 2)):
                    R(rx + sh, ry, rw, rh, '#3a3a3c')
                R(26 + sh, 2, 2, 2, '#a9d6f5')
                R(28 + sh, 5, 1, 1, '#3a3a3c')
                R(29 + sh, 6, 1, 1, '#3a3a3c')
            elif prop == 'hammer':
                if (fr // 2) % 2 == 0:
                    R(27, 4, 1, 5, '#7a4a26')
                    R(25, 2, 5, 2, '#8e929a')
                else:
                    R(27, 6, 1, 4, '#7a4a26')
                    R(25, 8, 5, 2, '#8e929a')
            elif prop == 'term':
                R(23, 1, 7, 6, '#2b2b2f')
                R(24, 2, 1, 1, '#7fe08a')
                R(25, 3, 1, 1, '#7fe08a')
                R(24, 4, 1, 1, '#7fe08a')
                if (fr // 2) % 2 == 0:
                    R(26, 4, 2, 1, '#e6e8ee')
            if self.cup:  # morning coffee in the free claw
                R(1, 10, 4, 4, '#f4f3ee')
                R(1, 10, 4, 1, '#6b3f1d')
                R(0, 11, 1, 2, '#f4f3ee')
                R(2, 8, 1, 1, '#cfd8e6')
                R(3, 6, 1, 1, '#cfd8e6')

        ax, ay, rx, ry, px, py = self.anchor()

        def pt(off, up):
            return ax + rx * up + px * off, ay + ry * up + py * off

        if fx_t is not None:  # whoosh: a puff of cloud, then sparkles, and the outfit changes
            a, b, c2, d = place(self.surf, 11, 9, 8, 8, self.dir, S)
            mx, my = (a + c2) / 2, (b + d) / 2
            R_ = 13 * S
            k = math.sin(math.pi * min(fx_t / 0.75, 1.0))
            if k > 0:
                for ox, oy, rr in ((0, 0, 0.8), (-0.5, 0.2, 0.55), (0.5, 0.15, 0.55), (-0.2, -0.45, 0.5), (0.25, -0.4, 0.5), (0.0, 0.45, 0.5)):
                    r = R_ * rr * k
                    cv.create_oval(mx + ox * R_ * k - r, my + oy * R_ * k - r, mx + ox * R_ * k + r, my + oy * R_ * k + r, fill='#ffffff', outline='#cfd8e6')
            if fx_t > 0.4:
                grow = (fx_t - 0.4) * 1.8
                for i in range(7):
                    ang = i * (2 * math.pi / 7) + fx_t * 3
                    sx, sy = mx + math.cos(ang) * R_ * (0.5 + grow), my + math.sin(ang) * R_ * (0.5 + grow)
                    col = ('#ffd45e', '#ff9fc0', '#9fe0ff')[i % 3]
                    cv.create_rectangle(sx - 1, sy - 4, sx + 1, sy + 4, fill=col, outline='')
                    cv.create_rectangle(sx - 4, sy - 1, sx + 4, sy + 1, fill=col, outline='')
        elif calling:  # "I need you": jumping and waving, with a gold question mark
            x0, y0 = pt(-14, 8)
            cv.create_text(x0, y0, text='?', fill='#e8a317', font=(UI_FONT, 14, 'bold'))
        elif shaking:  # a turn failed
            x0, y0 = pt(0, 10)
            cv.create_text(x0, y0, text='!', fill='#e5484d', font=(UI_FONT, 16, 'bold'))
        elif pose == 'greet':  # two crabs meet
            x0, y0 = pt(0, 10)
            cv.create_text(x0, y0, text='♥', fill='#ff6f8d', font=(SYM_FONT, 12, 'bold'))
        elif pose == 'break':  # a long stretch of work: time for a coffee break
            x0, y0 = pt(0, 12)
            cv.create_rectangle(x0 - 8, y0 - 4, x0 + 6, y0 + 8, fill='#f4f3ee', outline='')  # a little coffee cup
            cv.create_rectangle(x0 - 8, y0 - 4, x0 + 6, y0 - 1, fill='#6b3f1d', outline='')
            cv.create_rectangle(x0 + 6, y0, x0 + 10, y0 + 5, fill='#f4f3ee', outline='')
            cv.create_rectangle(x0 - 5, y0 - 12, x0 - 3, y0 - 7, fill='#cfd8e6', outline='')
            cv.create_rectangle(x0 + 1, y0 - 14, x0 + 3, y0 - 9, fill='#cfd8e6', outline='')
        elif pose == 'joy':  # the usage limit reset
            for i, off in enumerate((-14, 0, 14)):
                x0, y0 = pt(off, 6 + ((now * 18 + i * 7) % 18))
                cv.create_text(x0, y0, text='✦', fill='#ffd45e', font=(SYM_FONT, 11, 'bold'))
        elif main and (hearts or petting) and self.surf == 'floor':
            for i, off in enumerate((-16, 0, 16)):
                up = 4 + ((now * 14 + i * 9) % 26)
                x0, y0 = pt(off, up)
                cv.create_text(x0, y0, text='♥', fill='#ff6f8d', font=(SYM_FONT, 11, 'bold'))
        elif main and self.asleep:
            t = 2 if self.deep else int(now * 1.5) % 3
            for i in range(3):
                if i <= t:
                    x0, y0 = pt(14 + i * 7, 2 + i * 8)
                    cv.create_text(x0, y0, text='z' if i == 0 else 'Z', fill='#8aa0d0', font=(UI_FONT, 8 + i * 3, 'bold'))
        elif main and working and self.mode != 'drag' and mood != 'dead':
            on = int(now * 3) % 3
            dots = [pt((i - 1) * 8, 10) for i in range(3)]  # just the three dots, no bubble, on every surface
            for i, (x0, y0) in enumerate(dots):
                cv.create_oval(x0 - 2, y0 - 2, x0 + 2, y0 + 2, fill='#5b6f95' if i == on else '#b8c4dc', outline='')


IDLE_GONE_S = 60           # an idle chat's crab goes away after this long (the newest chat always keeps one)
SEEN_AT = {}
NEEDS_MAX_S = 60           # "needs you" only counts this long after Claude asked (it cannot see you answer, so it must not wave for ever)
LIVE_S = 180              # a session is "live" while its state file was updated this recently (the mod writes every minute)


def read_state():
    """All live sessions (one state file each) and the highest plan usage among them."""
    sessions, usage, resets = [], -1.0, 0
    now_ms = time.time() * 1000
    for f in glob.glob(os.path.join(BASE, 'state-*.json')):
        try:
            with open(f, encoding='utf-8') as fh:
                j = json.load(fh)
        except Exception:
            continue
        age = now_ms - j.get('updatedAt', 0)
        if age > 24 * 3600 * 1000 or j.get('closed'):
            try:
                os.remove(f)  # an old file, or a chat that said goodbye
            except Exception:
                pass
            continue
        if age > LIVE_S * 1000:
            continue  # the chat is gone (or asleep for good): no crab
        u = j.get('usage', -1)
        if isinstance(u, (int, float)) and u >= 0:
            if float(u) >= usage:
                resets = parse_iso(j.get('resetsAt', ''))
            usage = max(usage, float(u))  # the 5-hour limit is account-wide
        sid = str(j.get('sid') or os.path.basename(f)[6:-5])
        agents = {}
        for a in j.get('agents', []):
            agents[str(a.get('id'))] = a.get('tier', 'other')
        sessions.append({'sid': sid, 'project': str(j.get('project') or ''), 'busy': bool(j.get('busy')), 'agents': agents,
                         'done': j.get('doneAt', 0), 'err': j.get('errorAt', 0), 'needs': bool(j.get('needs')) and bool(j.get('busy')) and now_ms - (j.get('needsAt') or 0) < NEEDS_MAX_S * 1000,
                         'tool': str(j.get('tool') or ''), 'busy_since': j.get('busySince', 0) or 0})
    sessions.sort(key=lambda s: s['sid'])
    # chats idle for more than IDLE_GONE_S lose their crab; the most recently active one always keeps its crab
    for s in sessions:
        first = SEEN_AT.setdefault(s['sid'], now_ms)
        s['last'] = now_ms if (s['busy'] or s['agents']) else max(s['done'] or 0, s['err'] or 0, first)
    if len(sessions) > 1:
        keep = max(sessions, key=lambda s: s['last'])
        sessions = [s for s in sessions if s is keep or now_ms - s['last'] < IDLE_GONE_S * 1000]
    return {'sessions': sessions, 'usage': usage, 'resets': resets}


def alive_age():
    try:
        return time.time() - os.path.getmtime(ALIVE)
    except Exception:
        return 9999


def hue_pick(sid, used):
    """A stable outfit for a session, picked from its id, avoiding outfits already worn."""
    base = zlib.crc32(sid.encode()) % len(OUTFITS)
    for k in range(len(OUTFITS)):
        o = OUTFITS[(base + k) % len(OUTFITS)]
        if o not in used:
            return o
    return OUTFITS[base]


def greet_pairs(live_list, now):
    """Two crabs walking past each other on the same floor stop and wave."""
    cand = [c for c in live_list if c.surf == 'floor' and c.mode in ('walk', 'pause') and c.pose is None
            and now >= c.greet_cd and c.fx_t0 is None and not c.sleeping]
    for i, a in enumerate(cand):
        for b in cand[i + 1:]:
            if a.pose is not None or b.pose is not None or a.mon is not b.mon:
                continue
            if abs((a.x + a.w / 2) - (b.x + b.w / 2)) < 0.7 * (a.w + b.w) / 2 and abs((a.y + a.h) - (b.y + b.h)) < 30:
                for c, o in ((a, b), (b, a)):
                    c.pose, c.pose_until = 'greet', now + 1.4
                    c.greet_cd = now + random.uniform(30, 70)
                    c.dir = 1 if o.x > c.x else -1
                break


EMPTY = {'sid': '', 'project': '', 'busy': False, 'agents': {}, 'done': 0, 'err': 0, 'needs': False, 'tool': '', 'busy_since': 0}


def main():
    if alive_age() < 6:
        return  # already running
    try:
        os.remove(QUIT)
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    if MAC:
        try:
            mac_accessory()
        except Exception:
            log('mac_accessory failed: ' + traceback.format_exc())
    crabs = {}   # ('m', sid) for a session's main crab, ('a', sid, agent) for its helpers
    st = {'last': time.time(), 'state_t': 0.0, 'beat_t': 0.0, 's': {'sessions': [], 'usage': -1.0},
          'err_seen': {}, 'rescale': False, 'mon_t': 0.0, 'hide_until': 0.0, 'greet_t': 0.0, 'slots': {}, 'dbg_t': 0.0, 'n': 0}

    def mains():
        return [c for c in crabs.values() if c.main]

    def used_by_others(me):
        out = set()
        for c in mains():
            if c is not me:
                out.add(c.tier)
                if c.fx_t0 is not None:
                    out.add(c.fx_new)
        return out

    def beat():
        try:
            with open(ALIVE, 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass

    def stop():
        try:
            os.remove(ALIVE)
        except Exception:
            pass
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass
        root.destroy()

    def set_outfit(c, o):
        if c.fx_t0 is None:
            c.start_fx(time.time(), o)

    def set_size(n):
        PREFS['size'] = int(n)
        set_scale(n)
        save_prefs()
        st['rescale'] = True

    def toggle_sleep(c):
        c.sleeping = not c.sleeping
        c.idle_since = time.time()
        c.shown = None

    def hide_for_hour():
        st['hide_until'] = time.time() + 3600
        for c in crabs.values():
            c.hide_tip()
            try:
                c.win.withdraw()
            except Exception:
                pass

    def show_all():
        st['hide_until'] = 0.0
        for c in crabs.values():
            try:
                c.win.deiconify()
                tool_window(c.win)
                c.win.attributes('-topmost', True)
                c.shown, c.pos_shown = None, None
            except Exception:
                pass
        st['state_t'] = 0.0

    APP.update({'outfit': set_outfit, 'size': set_size, 'sleep': toggle_sleep, 'quit': stop, 'used': used_by_others,
                'hide': hide_for_hour, 'usage': lambda: (st['s']['usage'], st['s'].get('resets', 0))})
    beat()

    def make_main(sid, slot, mons_, tier=None):
        if tier is None:
            used = {c.tier for c in mains()}
            pref = PREFS.get('outfit')
            tier = pref if (slot == 0 and pref in OUTFITS and pref not in used) else hue_pick(sid, used)
        c = Crab(root, ('m', sid), tier, True, mons_, sid=sid, slot=slot)
        crabs[('m', sid)] = c
        return c

    def reconcile(mons2, now):
        """Make the crabs match the live sessions: one main crab each, plus that session's helpers."""
        sess = st['s']['sessions'] or [EMPTY]
        live = {x['sid']: x for x in sess}
        slots = st['slots']
        for sid in list(slots):
            if sid not in live:
                del slots[sid]
        for x in sess:
            if x['sid'] not in slots:
                n = 0
                while n in slots.values():
                    n += 1
                slots[x['sid']] = n
        for key in list(crabs):
            c = crabs[key]
            if c.sid not in live or (key[0] == 'a' and key[2] not in live[c.sid]['agents']):
                c.destroy()
                del crabs[key]
        for x in sess:
            sid = x['sid']
            if ('m', sid) not in crabs:
                make_main(sid, slots[sid], mons2)
            for aid, tier in x['agents'].items():
                if ('a', sid, aid) not in crabs and len(crabs) < 16:
                    crabs[('a', sid, aid)] = Crab(root, aid, tier, False, mons2, sid=sid)
        multi = len(sess) >= 2
        seen, labels = {}, {}
        for x in sorted(sess, key=lambda v: slots[v['sid']]):
            name = x['project'] or 'Chat (no folder)'
            seen[name] = seen.get(name, 0) + 1
            labels[x['sid']] = name if seen[name] == 1 else '%s (%d)' % (name, seen[name])
        u = st['s']['usage']
        mood = 'dead' if u >= 100 else ('tired' if u > 80 else 'ok')
        prev_u = st.get('usage_prev', -1.0)
        if prev_u >= 30 and u >= 0 and prev_u - u >= 15:  # the 5-hour limit just reset: a happy hop
            for c in mains():
                c.start_pose('joy', now, 2.4)
        if u >= 0:
            st['usage_prev'] = u
        for c in crabs.values():
            x = live[c.sid]
            c.refresh_mons(mons2)
            if c.main:
                c.slot = slots[c.sid]
                c.label = labels[c.sid]
                c.mood, c.tool, c.needs = mood, x['tool'], x['needs']
                c.exhausted = u >= 90
                c.busy_since = x['busy_since'] if x['busy'] else 0
                c.info = {'tool': x['tool'], 'busy': x['busy'], 'agents': len(x['agents']), 'needs': x['needs']}
                seen_err = st['err_seen'].get(c.sid)
                if seen_err is None or x['err'] > seen_err:
                    if x['err'] and now * 1000 - x['err'] < 6000:
                        c.shake(now)
                    st['err_seen'][c.sid] = x['err']

    def rebuild():
        """Size changed: make every crab again at the new size."""
        saved = [(c.sid, c.slot, c.tier, c.x, c.y, c.w, c.h) for c in mains()]
        for c in crabs.values():
            c.destroy()
        crabs.clear()
        mons2 = get_monitors()
        for sid, slot, tier, x, y, w, h in saved:
            m = make_main(sid, slot, mons2, tier)
            mon = pick_mon(mons2, x + w / 2, y + h / 2)
            m.set_mon(mon)
            m.x = min(max(x, mon.work[0]), mon.work[2] - m.w)
            m.y = float(m.floor_y())
            m.home = (m.x, m.y)
            if slot == 0:
                PREFS['home_x'] = int(m.x)
        save_prefs()
        st['rescale'] = False
        st['state_t'] = 0.0  # re-read state now, so helper crabs come back

    st['s'] = read_state()
    reconcile(get_monitors(), time.time())

    def tick():
        try:
            now = time.time()
            dt = min(0.25, now - st['last'])
            st['last'] = now
            if now - st['beat_t'] > 2:
                st['beat_t'] = now
                beat()
                if os.path.exists(QUIT):
                    stop()
                    return
            if st['hide_until']:
                if now < st['hide_until']:
                    root.after(1000, tick)
                    return
                show_all()
            if st['rescale']:
                rebuild()
            if now - st['mon_t'] > 0.3:  # the taskbar slides up and away: follow it quickly
                st['mon_t'] = now
                mons3 = get_monitors()
                for c in crabs.values():
                    c.refresh_mons(mons3)
            if now - st['state_t'] > 0.95:
                st['state_t'] = now
                st['s'] = read_state()
                reconcile(get_monitors(), now)
            live_list = list(crabs.values())
            if MAC:
                for c in live_list:
                    if c.mode == 'drag':
                        try:
                            c.mac_drag_poll()
                        except Exception:
                            log(traceback.format_exc())
            if len(live_list) > 1 and now - st['greet_t'] > 0.25:
                st['greet_t'] = now
                greet_pairs(live_list, now)  # two crabs meet: they wave at each other
            by_sid = {x['sid']: x for x in (st['s']['sessions'] or [EMPTY])}
            now_ms = now * 1000
            fast, any_working, any_hearts = False, False, False
            for c in live_list:
                x = by_sid.get(c.sid)
                if x is None:
                    continue
                if c.main:
                    working = x['busy'] or len(x['agents']) > 0
                    hearts = (not working) and x['done'] > 0 and (now_ms - x['done'] < 4000)
                else:
                    working, hearts = True, False
                any_working = any_working or (working and c.main)
                any_hearts = any_hearts or hearts
                if c.update(dt, now, working, hearts):
                    fast = True
            ms = [c for c in live_list if c.main]
            if DEBUG and now - st['dbg_t'] > 2:
                st['dbg_t'] = now
                log('crabs=%d mains=%s' % (len(crabs), [(c.sid[:6], c.tier, c.mode, c.pose, c.label) for c in ms]))
            if any(c.mode in ('drag', 'fall', 'jump') for c in live_list):
                delay = 16
            elif fast or any_hearts:
                delay = 33
            elif ms and len(ms) == len(live_list) and all(c.deep for c in ms) and not any_working:
                delay = 1000
            elif any_working or any(c.asleep or c.mood == 'tired' for c in ms):
                delay = 120
            else:
                delay = 330
            root.after(delay, tick)
        except Exception:
            log(traceback.format_exc())
            root.after(500, tick)

    root.after(50, tick)
    root.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log(traceback.format_exc())
