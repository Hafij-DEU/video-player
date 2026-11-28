"""Astra's Lumina Glass look (aurora colours, always dark: Astra is a dark player).

Follows Harbor Settings (~/.config/harbor/glass-astra, then the shared glass
files) or the user's own choice in the main menu: Look > Follow Harbor
Settings / Lumina Glass / Normal. Spec: ~/Music/apps/glass-theme/PLANNER-SPEC.md
"""

from . import planner_glass

# Real glass: a translucent violet fill, a strong white sheen fading down, a pink
# glow at the foot, a white rim and a bright top edge (aurora colours).
GLASS = ("background-color: rgba(44,30,82,0.52); "
         "background-image: linear-gradient(to bottom, rgba(255,255,255,0.20), rgba(255,255,255,0.05) 45%, "
         "rgba(255,255,255,0.0) 70%, rgba(236,72,153,0.10)); ")
EDGE = "inset 0 1px rgba(255,255,255,0.34), inset 0 -1px rgba(255,255,255,0.06)"
RIM = "1px solid rgba(255,255,255,0.18)"
AURORA = "linear-gradient(135deg, #ec4899, #8b5cf6 55%, #38bdf8)"
AURORA_H = "linear-gradient(to right, #ec4899, #8b5cf6, #38bdf8)"

ASTRA_CSS = f"""
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
"""


class AstraLook:
    def __init__(self, provider):
        self.provider = provider
        self.look = planner_glass.Look("astra", self.apply)
        self.apply()

    def choice(self):
        return self.look.choice()

    def set_choice(self, choice):
        self.look.set_choice(choice)

    def apply(self):
        css = self.look.css_gtk4(True)
        self.provider.load_from_string(css + ASTRA_CSS if css else "")
