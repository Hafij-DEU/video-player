"""Astra's glass looks (always dark: Astra is a dark player).

Look in the main menu: Follow Harbor Settings / Lumina Glass / Lumina Aurora /
Normal. Lumina Glass is the calm indigo look every app shares (Harbor
Settings, ~/.config/harbor/glass-astra). Lumina Aurora is Astra's own
colourful variant (pink, violet, sky) on top of it; Astra keeps that pick in
~/.config/astra-player/look. Spec: ~/Music/apps/glass-theme/PLANNER-SPEC.md
"""

import os

from . import planner_glass

# ---- Lumina Glass: real glass in the shared indigo family -------------------
L_GLASS = ("background-color: rgba(30,26,60,0.58); "
           "background-image: linear-gradient(to bottom, rgba(255,255,255,0.16), rgba(255,255,255,0.04) 45%, "
           "rgba(255,255,255,0.0) 75%); ")
L_EDGE = "inset 0 1px rgba(255,255,255,0.28), inset 0 -1px rgba(255,255,255,0.05)"
L_RIM = "1px solid rgba(255,255,255,0.15)"
L_ACCENT = "linear-gradient(135deg, #6366f1, #8b5cf6)"

LUMINA_CSS = f"""
.controls {{ {L_GLASS} border-top: {L_RIM}; box-shadow: {L_EDGE}; }}
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

# ---- Lumina Aurora: Astra's colourful variant ------------------------------
# Real glass: a translucent violet fill, a strong white sheen fading down, a pink
# glow at the foot, a white rim and a bright top edge (aurora colours).
GLASS = ("background-color: rgba(44,30,82,0.52); "
         "background-image: linear-gradient(to bottom, rgba(255,255,255,0.20), rgba(255,255,255,0.05) 45%, "
         "rgba(255,255,255,0.0) 70%, rgba(236,72,153,0.10)); ")
EDGE = "inset 0 1px rgba(255,255,255,0.34), inset 0 -1px rgba(255,255,255,0.06)"
RIM = "1px solid rgba(255,255,255,0.18)"
AURORA = "linear-gradient(135deg, #ec4899, #8b5cf6 55%, #38bdf8)"
AURORA_H = "linear-gradient(to right, #ec4899, #8b5cf6, #38bdf8)"

AURORA_CSS = f"""
window.background {{ background-image: linear-gradient(150deg, rgb(48,20,60), rgb(30,24,74) 50%, rgb(14,34,70)); }}
.controls {{ {GLASS} border-top: {RIM}; box-shadow: {EDGE}, 0 -10px 30px -18px rgba(236,72,153,0.45); }}
.controls.fs {{ {GLASS} margin: 0 14px 14px; border-radius: 18px; border: {RIM};
  box-shadow: {EDGE}, 0 16px 34px -14px rgba(0,0,0,0.65), 0 0 24px -8px rgba(139,92,246,0.45); }}
.controls .time {{ color: #c4b5fd; }}
.controls button.play, .badge-info, .controls button.active-toggle {{ color: #f0abfc; }}
.controls .transport > button:nth-child(3n+1) {{ color: #f9a8d4; }}
.controls .transport > button:nth-child(3n+2) {{ color: #c4b5fd; }}
.controls .transport > button:nth-child(3n) {{ color: #7dd3fc; }}
.controls .transport button:hover {{ background-color: rgba(255,255,255,0.10); }}
.controls .transport button.play, .controls.fs .transport button.ctl.play {{
  background-image: {AURORA}; color: #ffffff; border-radius: 9999px;
  border: 1px solid rgba(255,255,255,0.35);
  box-shadow: inset 0 1px rgba(255,255,255,0.45), 0 8px 22px -6px rgba(236,72,153,0.60), 0 0 18px -4px rgba(56,189,248,0.40); }}
.controls .transport button.play:hover {{ opacity: 0.92; }}
scale.seekbar trough {{ background-color: rgba(255,255,255,0.12); }}
scale.seekbar highlight, scale trough highlight {{ background-color: #8b5cf6; background-image: {AURORA_H}; }}
scale.seekbar slider {{ background-color: #ffffff; box-shadow: 0 0 0 3px rgba(236,72,153,0.40), 0 0 12px rgba(139,92,246,0.6); }}
scale.seekbar marks indicator {{ color: #f0abfc; }}
.playlist-panel {{ {GLASS} border-left: {RIM}; box-shadow: {EDGE}; }}
.playlist row {{ border-radius: 12px; margin: 1px 6px; }}
.playlist row:hover {{ background-color: rgba(255,255,255,0.07); }}
.playlist row.current {{ background-image: linear-gradient(to right, rgba(236,72,153,0.30), rgba(139,92,246,0.24), rgba(56,189,248,0.18));
  color: #ffffff; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.14); }}
.osd {{ {GLASS} border: {RIM}; border-radius: 14px;
  box-shadow: {EDGE}, 0 10px 26px -10px rgba(0,0,0,0.6); text-shadow: none; }}
.seek-preview {{ border-radius: 12px; border: {RIM}; box-shadow: 0 10px 24px -10px rgba(0,0,0,0.6); }}
headerbar.fs {{ {GLASS} border-bottom: {RIM}; }}
.idle-logo {{ color: #f0abfc; }}
.idle-title {{ color: #ffffff; }}
.clock {{ color: #fdf4ff; }}
/* the colourful part: an aurora tint across the header and the control bar */
headerbar, .controls, .controls.fs {{ background-color: rgba(40,22,78,0.70);
  background-image: linear-gradient(to bottom, rgba(255,255,255,0.18), rgba(255,255,255,0.0) 60%),
    linear-gradient(to right, rgba(236,72,153,0.42), rgba(139,92,246,0.36) 50%, rgba(56,189,248,0.36)); }}
headerbar {{ box-shadow: inset 0 -1px rgba(255,255,255,0.12), 0 6px 18px -10px rgba(236,72,153,0.55); }}
headerbar .title, headerbar label.title {{ color: #ffffff; }}
headerbar button {{ color: #fbcfe8; }}
.controls button:nth-child(3n+1) {{ color: #f9a8d4; }}
.controls button:nth-child(3n+2) {{ color: #c4b5fd; }}
.controls button:nth-child(3n) {{ color: #7dd3fc; }}
.controls button.play, .controls .transport button.play {{ color: #ffffff; }}
.controls .time {{ color: #fbcfe8; }}
.playlist-panel {{ background-image: linear-gradient(to bottom, rgba(236,72,153,0.20), rgba(139,92,246,0.16) 50%, rgba(56,189,248,0.16)); }}
.idle-title {{ color: #fbcfe8; }}
"""


LOOK_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                         "astra-player", "look")


def _aurora_saved():
    try:
        with open(LOOK_FILE, encoding="utf-8") as fh:
            return fh.read().strip() == "aurora"
    except OSError:
        return False


def _save_aurora(on):
    try:
        if on:
            os.makedirs(os.path.dirname(LOOK_FILE), exist_ok=True)
            with open(LOOK_FILE, "w", encoding="utf-8") as fh:
                fh.write("aurora\n")
        elif os.path.exists(LOOK_FILE):
            os.remove(LOOK_FILE)
    except OSError:
        pass


class AstraLook:
    CHOICES = (("follow", "Follow Harbor Settings"), ("planner", "Lumina Glass"),
               ("aurora", "Lumina Aurora (colourful)"), ("normal", "Normal"))

    def __init__(self, provider):
        self.provider = provider
        self.aurora = _aurora_saved()
        self.look = planner_glass.Look("astra", self.apply)
        self.apply()

    def choice(self):
        base = self.look.choice()
        return "aurora" if base == "planner" and self.aurora else base

    def set_choice(self, choice):
        self.aurora = choice == "aurora"
        _save_aurora(self.aurora)
        self.look.set_choice("planner" if self.aurora else choice)

    def apply(self):
        css = self.look.css_gtk4(True)
        if css:
            css += AURORA_CSS if self.aurora else LUMINA_CSS
        self.provider.load_from_string(css)
