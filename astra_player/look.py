"""Astra's glass looks (always dark: Astra is a dark player).

Look (main menu or Preferences > Look): Follow Harbor Settings / Lumina Glass /
Normal. Lumina and its options come from the shared glass files, global or per
app (~/.config/harbor/glass-astra), set in Harbor Settings or here:
  lumina=CALM      the indigo look every app shares (Astra keeps it dark)
  lumina=COLOURFUL the whole window in colour: a colour set, the system accent
                   or a picked colour, with an intensity
Astra's own extra: light or dark for Colourful (~/.config/astra-player/look).
Spec: ~/Music/apps/glass-theme/PLANNER-SPEC.md
"""

import os

from gi.repository import Adw

from . import planner_glass

# ---- Lumina Glass: real glass in the shared indigo family -------------------
L_GLASS = ("background-color: rgba(30,26,60,0.58); "
           "background-image: linear-gradient(to bottom, rgba(255,255,255,0.16), rgba(255,255,255,0.04) 45%, "
           "rgba(255,255,255,0.0) 75%); ")
L_EDGE = "inset 0 1px rgba(255,255,255,0.28), inset 0 -1px rgba(255,255,255,0.05)"
L_RIM = "1px solid rgba(255,255,255,0.15)"
L_ACCENT = "linear-gradient(135deg, #6366f1, #8b5cf6)"

LUMINA_CSS = f"""
/* the shared footer rule floats bottom bars 12px in; Astra's control bar spans the window */
toolbarview > .bottom-bar {{ margin: 0; border-radius: 0; border: none; box-shadow: none;
  background-color: transparent; background-image: none; }}
.controls {{ {L_GLASS} border-top: {L_RIM}; box-shadow: {L_EDGE}; }}
/* Lumina dock: a smaller floating glass pill, centred (width set by the window),
   floating on the same black as the video */
toolbarview > .bottom-bar {{ background-color: #000000; }}
.controls.dock {{ margin: 10px 12px 14px; border-radius: 22px; border: {L_RIM};
  box-shadow: {L_EDGE}, 0 14px 30px -14px rgba(0,0,0,0.65); }}
/* fullscreen: no black strip under the dock, the video runs to the edge */
toolbarview.fs > .bottom-bar {{ background-color: transparent; }}
/* windowed dock as roomy as the fullscreen panel */
.controls.dock {{ padding: 8px 18px 12px; }}
.controls.dock button.ctl {{ min-width: 38px; min-height: 38px; }}
.controls.dock .transport button.play {{ min-width: 54px; min-height: 54px; }}
.controls.fs {{ {L_GLASS} margin: 0 14px 14px; border-radius: 18px; border: {L_RIM};
  box-shadow: {L_EDGE}, 0 16px 34px -14px rgba(0,0,0,0.65); }}
.controls .time {{ color: #aaa7c8; }}
.controls button.play, .badge-info, .controls button.active-toggle {{ color: #a5b4fc; }}
.controls .transport button:hover {{ background-color: rgba(255,255,255,0.10); }}
.controls .transport button.play, .controls.fs .transport button.ctl.play {{
  background-image: {L_ACCENT}; color: #ffffff; border-radius: 9999px;
  border: 1px solid rgba(255,255,255,0.28);
  box-shadow: inset 0 1px rgba(255,255,255,0.35), 0 8px 18px -6px rgba(99,102,241,0.55); }}
.controls .transport button.play:hover {{ opacity: 0.92; }}
scale.seekbar trough {{ background-color: rgba(255,255,255,0.10); }}
scale.seekbar highlight, scale trough highlight {{ background-color: #6366f1; background-image: linear-gradient(to right, #6366f1, #8b5cf6); }}
scale.seekbar slider {{ background-color: #ffffff; box-shadow: 0 0 0 3px rgba(99,102,241,0.35); }}
scale.seekbar marks indicator {{ color: #a5b4fc; }}
.playlist-panel {{ {L_GLASS} border-left: {L_RIM}; box-shadow: {L_EDGE}; }}
.playlist row {{ border-radius: 12px; margin: 1px 6px; }}
.playlist row:hover {{ background-color: rgba(255,255,255,0.06); }}
.playlist row.current {{ background-color: rgba(129,140,248,0.24); color: #e0e7ff;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.10); }}
.osd {{ {L_GLASS} border: {L_RIM}; border-radius: 14px;
  box-shadow: {L_EDGE}, 0 10px 26px -10px rgba(0,0,0,0.6); text-shadow: none; }}
.seek-preview {{ border-radius: 12px; border: {L_RIM}; box-shadow: 0 10px 24px -10px rgba(0,0,0,0.6); }}
headerbar.fs {{ {L_GLASS} border-bottom: {L_RIM}; }}
.idle-logo {{ color: #a5b4fc; }}
.clock {{ color: #eeedf9; }}
"""

# ---- Lumina Colourful in Astra: the whole window in colour -------------------

MODES = (("system", "Follow the system"), ("light", "Light"), ("dark", "Dark"))
LOOK_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                         "astra-player", "look")
_rgba = planner_glass._rgba


def _mix(hexcol, base, amount):
    return "rgb(%d,%d,%d)" % planner_glass._mix(hexcol, base, amount)


def colourful_css(dark, t):
    """Astra's parts in COLOURFUL: plain glass bars (no tint stripes, no
    coloured glows); the colour is in the text, icons and selections. t =
    planner_glass.tokens(..., spec) so Astra matches the other apps."""
    c1, c2, c3 = t["a1"], t["a2"], t["a3"]
    if dark:
        bar = ("background-color: rgba(26,22,52,0.72); background-image: linear-gradient(to bottom, "
               "rgba(255,255,255,0.10), rgba(255,255,255,0.02) 60%); ")
        rim, edge, shadow, idle = "rgba(255,255,255,0.14)", "rgba(255,255,255,0.26)", "rgba(0,0,0,0.5)", "rgba(0,0,0,0.20)"
        on, text, soft = (255, 255, 255), "#eeedf9", "rgba(238,237,249,0.62)"
    else:
        bar = ("background-color: rgba(255,255,255,0.62); background-image: linear-gradient(to bottom, "
               "rgba(255,255,255,0.80), rgba(255,255,255,0.40) 60%); ")
        rim, edge, shadow, idle = "rgba(255,255,255,0.90)", "rgba(255,255,255,0.95)", "rgba(76,61,180,0.22)", "rgba(255,255,255,0.12)"
        on, text, soft = (20, 16, 40), "#1e1b3a", "rgba(30,27,58,0.62)"
    # the dock sits on the video's black: light glass needs more white to stay light
    dock = "" if dark else ("background-color: rgba(255,255,255,0.90); background-image: linear-gradient("
                            "to bottom, rgba(255,255,255,0.95), rgba(255,255,255,0.78) 60%);")
    tone = 0.55 if dark else 0.80   # how much colour vs the plain text colour

    def ink(c):
        return _mix(c, on, tone)
    gloss = "linear-gradient(to bottom, rgba(255,255,255,0.30), rgba(255,255,255,0.0) 60%)"
    return f"""
:root {{ --accent-bg-color: {c2}; --accent-color: {t["accent_text"]}; --accent-fg-color: #ffffff; }}
.video-area {{ background-color: {idle}; }}
/* the dock floats on the video's black; with no video (idle screen, music)
   it sits on the same light stage as the idle screen */
toolbarview > .bottom-bar {{ margin: 0; border-radius: 0; border: none; box-shadow: none;
  background-color: {idle}; background-image: none; }}
toolbarview.stage-video > .bottom-bar {{ background-color: #000000; }}
headerbar {{ {bar} box-shadow: inset 0 -1px {rim}; }}
headerbar .title, headerbar label.title, headerbar button {{ color: {text}; }}
.controls {{ {bar} border-top: 1px solid {rim}; box-shadow: inset 0 1px {edge}; }}
.controls.dock {{ margin: 10px 12px 14px; border-radius: 22px; border: 1px solid {rim};
  box-shadow: inset 0 1px {edge}, 0 14px 30px -14px {shadow}; {dock} }}
/* fullscreen: no black strip under the dock, the video runs to the edge */
toolbarview.fs > .bottom-bar {{ background-color: transparent; }}
/* windowed dock as roomy as the fullscreen panel */
.controls.dock {{ padding: 8px 18px 12px; }}
.controls.dock button.ctl {{ min-width: 38px; min-height: 38px; }}
.controls.dock .transport button.play {{ min-width: 54px; min-height: 54px; }}
.controls.fs {{ {bar} margin: 0 14px 14px; border-radius: 18px; border: 1px solid {rim};
  box-shadow: inset 0 1px {edge}, 0 14px 30px -14px {shadow}; }}
.controls button.ctl, .controls.fs button.ctl {{ color: {text}; }}
/* one hue: tool icons neutral, transport icons in the main colour */
.controls button.ctl {{ color: {soft}; }}
.controls .transport > button {{ color: {t["i2"]}; }}
.controls .time {{ color: {soft}; }}
.controls .transport button:hover, .controls button.ctl:hover {{ background-color: {_rgba(c2, 0.14)}; }}
.controls .transport button.play, .controls.fs .transport button.ctl.play {{
  background-color: {c2}; color: #ffffff; border-radius: 9999px;
  background-image: {gloss}, {t["accent"]};
  border: 1px solid rgba(255,255,255,0.40); box-shadow: inset 0 1px rgba(255,255,255,0.50), 0 4px 10px -6px {shadow}; }}
.controls .transport button.play:hover {{ opacity: 0.92; background-color: {c2}; }}
.controls .transport > button.play, .controls.fs .transport > button.ctl.play {{ color: #ffffff; }}
/* switched-on tools sit on a small glossy colour chip */
.controls button.active-toggle {{ color: {t["i2"]}; background-color: {_rgba(c2, 0.11)}; background-image: {gloss};
  box-shadow: inset 0 0 0 1px {_rgba(c2, 0.20)}; border-radius: 10px; }}
.badge-info {{ color: {t["i2"]}; }}
.controls button.speed-chip {{ color: {t["i2"]}; font-weight: 700; font-size: 0.86em; min-width: 34px;
  background-color: {_rgba(c2, 0.10)}; border-radius: 10px; }}
.controls .quick-sep {{ background-color: {_rgba(c2, 0.22)}; min-width: 1px; }}
scale.seekbar trough, .controls.fs scale.seekbar trough {{ background-color: {_rgba(c2, 0.16)}; }}
scale.seekbar highlight, scale trough highlight {{ background-color: {c2};
  background-image: linear-gradient(to right, {c1}, {c2}, {c3}); }}
scale.seekbar slider {{ background-color: #ffffff; box-shadow: 0 0 0 2px {c2}; }}
scale.seekbar marks indicator {{ color: {t["i2"]}; }}
.playlist-panel {{ {bar} border-left: 1px solid {rim}; }}
.playlist row {{ border-radius: 12px; margin: 1px 6px; }}
.playlist row:hover {{ background-color: {_rgba(c2, 0.10)}; }}
.playlist row.current {{ background-color: {t["sel"]}; color: {t["title"]}; }}
.osd {{ {bar} color: {text}; border: 1px solid {rim}; border-radius: 14px;
  box-shadow: inset 0 1px {edge}, 0 10px 24px -12px {shadow}; text-shadow: none; }}
.seek-preview {{ border-radius: 12px; border: 1px solid {rim}; box-shadow: 0 10px 24px -12px {shadow}; }}
headerbar.fs {{ {bar} border-bottom: 1px solid {rim}; }}
headerbar.fs, headerbar.fs .header-extras button {{ color: {text}; }}
.idle-logo {{ opacity: 1; }}
.idle-title {{ color: {t["title"]}; }}
.idle-hint {{ color: {soft}; }}
.clock {{ color: {text}; }}
"""



# ---- The other Harbor glass presets in Astra (dark player) -------------------

def preset_css(spec):
    """Harbor Settings' other glass styles (CLEAR, FROSTED, GEL, TINTED, SMOKE,
    HALO, GLOW) on Astra's glass parts: the dock, the fullscreen panel, the
    header, the playlist and the OSD. Effect SOFT = flat glass, STRONG = sheen;
    opacity and rim come from the same spec."""
    style = spec.get("style", "FROSTED")
    soft = spec.get("effect") == "SOFT"
    a = max(0.2, spec.get("opacity", 75) / 100)
    if style == "CLEAR":
        a *= 0.7
    if soft:
        a = 0.5 + a * 0.5
    acc = "var(--accent-bg-color)"
    base = {"CLEAR": (24, 24, 30), "FROSTED": (58, 58, 68), "GEL": (34, 34, 44),
            "TINTED": (30, 26, 20), "SMOKE": (8, 8, 10), "HALO": (22, 22, 28),
            "GLOW": (26, 24, 30)}.get(style, (40, 40, 48))
    bg = "background-color: rgba(%d,%d,%d,%.2f);" % (*base, min(0.96, a))
    sheen = {"CLEAR": 0.05, "FROSTED": 0.12, "GEL": 0.22, "TINTED": 0.08, "SMOKE": 0.04,
             "HALO": 0.07, "GLOW": 0.08}.get(style, 0.08)
    img = "none" if soft else (
        "linear-gradient(to bottom, rgba(255,255,255,%.2f), rgba(255,255,255,0.0) %s)"
        % (sheen, "48%" if style == "GEL" else "65%"))
    if style == "TINTED":
        img = ("linear-gradient(alpha(%s,0.14), alpha(%s,0.14))" % (acc, acc)
               + ("" if soft else ", " + img))
    if style == "GLOW":
        img = ("radial-gradient(ellipse at 50%% 120%%, alpha(%s,0.38), transparent 70%%)" % acc
               + ("" if soft else ", " + img))
    rim = "1px solid rgba(255,255,255,%.2f)" % ((0.14 if not soft else 0.08) if spec.get("rim", True) else 0.0)
    shadow = "0 14px 30px -14px rgba(0,0,0,%.2f)" % (0.35 if soft else 0.65)
    if style == "HALO":
        shadow = "0 0 0 1px alpha(%s,0.45), 0 0 18px -2px alpha(%s,0.35), %s" % (acc, acc, shadow)
    if style == "GEL" and not soft:
        shadow = "inset 0 1px rgba(255,255,255,0.30), inset 0 -1px rgba(0,0,0,0.30), " + shadow
    glass = f"{bg} background-image: {img};"
    return f"""
.controls.dock, .controls.fs {{ {glass} border: {rim}; box-shadow: {shadow}; }}
headerbar, headerbar.fs {{ {glass} box-shadow: inset 0 -1px rgba(255,255,255,0.08); }}
.playlist-panel {{ {glass} border-left: {rim}; }}
.osd {{ {glass} border: {rim}; border-radius: 14px; }}
.controls.fs button.ctl {{ color: #ffffff; }}
"""

def load_mode():
    try:
        with open(LOOK_FILE, encoding="utf-8") as fh:
            for line in fh.read().splitlines():
                key, _, val = line.partition("=")
                if key.strip() == "mode" and val.strip() in dict(MODES):
                    return val.strip()
    except OSError:
        pass
    return "system"


def save_mode(mode):
    try:
        os.makedirs(os.path.dirname(LOOK_FILE), exist_ok=True)
        with open(LOOK_FILE, "w", encoding="utf-8") as fh:
            fh.write(f"mode={mode}\n")
    except OSError:
        pass


class AstraLook:
    CHOICES = (("follow", "Follow Harbor Settings"), ("planner", "Lumina Glass"), ("normal", "Normal"))

    def __init__(self, provider):
        self.provider = provider
        self.listeners = []   # window callbacks (the floating control dock)
        self.mode = load_mode()
        self.style = Adw.StyleManager.get_default()
        self.style.connect("notify::dark", lambda *_: self.apply())
        self.look = planner_glass.Look("astra", self.apply)
        self.apply()

    @property
    def spec(self):
        return self.look.spec

    @property
    def lumina(self):
        return self.look.active

    @property
    def colourful(self):
        return self.lumina and self.spec.get("lumina") == "COLOURFUL"

    def choice(self):
        return self.look.choice()

    def set_choice(self, choice):
        self.look.set_choice(choice)  # restyles through Look's callback

    def tweak(self, key, value):
        """Preferences > Look: shared Lumina keys go to glass-astra (per app,
        same as Harbor Settings); "mode" is Astra's own."""
        if key == "mode":
            self.mode = value
            save_mode(value)
            self.apply()
        else:
            self.look.set_own(key, value)

    def _scheme(self):
        if not self.colourful:
            return Adw.ColorScheme.FORCE_DARK  # Astra is a dark player
        return {"light": Adw.ColorScheme.FORCE_LIGHT,
                "dark": Adw.ColorScheme.FORCE_DARK}.get(self.mode, Adw.ColorScheme.DEFAULT)

    def apply(self):
        scheme = self._scheme()
        if self.style.get_color_scheme() != scheme:
            self.style.set_color_scheme(scheme)  # notify::dark calls apply again
        spec = self.spec
        if self.colourful:
            dark = self.style.get_dark()
            css = planner_glass.css_gtk4(dark, False, 100, spec) + colourful_css(
                dark, planner_glass.tokens(dark, False, 100, spec))
        else:
            css = self.look.css_gtk4(True)
            if css:
                css += LUMINA_CSS
            elif spec.get("effect") != "OFF" and spec.get("style") != "PLANNER":
                css = preset_css(spec)  # the other Harbor presets
        self.provider.load_from_string(css)
        for cb in self.listeners:
            cb()
