"""Astra's Planner Glass look (palette v3, always dark: Astra is a dark player).

Follows Harbor Settings (~/.config/harbor/glass-astra, then the shared glass
files) or the user's own choice in the main menu: Look > Follow Harbor
Settings / Glass (Planner) / Normal. Spec: ~/Music/apps/glass-theme/PLANNER-SPEC.md
"""

from . import planner_glass

GLASS = ("background-color: rgba(30,26,60,0.70); "
         "background-image: linear-gradient(to bottom, rgba(255,255,255,0.10), rgba(255,255,255,0.03)); ")
EDGE = "inset 0 1px rgba(255,255,255,0.16)"

ASTRA_CSS = f"""
.controls {{ {GLASS} border-top: 1px solid rgba(255,255,255,0.12); box-shadow: {EDGE}; }}
.controls.fs {{ {GLASS} margin: 0 14px 14px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.13);
  box-shadow: {EDGE}, 0 12px 28px -12px rgba(0,0,0,0.6); }}
.controls .time {{ color: #aaa7c8; }}
.controls button.play, .badge-info, .controls button.active-toggle {{ color: #a5b4fc; }}
.controls .transport button.play, .controls.fs .transport button.ctl.play {{
  background-image: linear-gradient(135deg, #6366f1, #8b5cf6); color: #ffffff; border-radius: 9999px;
  border: 1px solid rgba(255,255,255,0.25); box-shadow: inset 0 1px rgba(255,255,255,0.30), 0 8px 18px -6px rgba(99,102,241,0.55); }}
.controls .transport button.play:hover {{ opacity: 0.92; }}
scale.seekbar trough {{ background-color: rgba(255,255,255,0.10); }}
scale.seekbar highlight {{ background-color: #6366f1; background-image: linear-gradient(to right, #6366f1, #8b5cf6); }}
scale.seekbar slider {{ background-color: #ffffff; box-shadow: 0 0 0 3px rgba(99,102,241,0.35); }}
scale.seekbar marks indicator {{ color: #a5b4fc; }}
.playlist-panel {{ {GLASS} border-left: 1px solid rgba(255,255,255,0.12); box-shadow: {EDGE}; }}
.playlist row {{ border-radius: 12px; margin: 1px 6px; }}
.playlist row.current {{ background-color: rgba(129,140,248,0.24); color: #c7d2fe; }}
.osd {{ background-color: rgba(24,21,48,0.72); border: 1px solid rgba(255,255,255,0.14);
  border-radius: 12px; box-shadow: {EDGE}, 0 10px 24px -10px rgba(0,0,0,0.6); text-shadow: none; }}
.seek-preview {{ border-radius: 12px; border: 1px solid rgba(255,255,255,0.14); }}
headerbar.fs {{ background-color: rgba(24,21,48,0.80); }}
.clock {{ color: #eeedf9; }}
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
