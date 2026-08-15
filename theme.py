"""
Modernist design-system tokens rendered as Streamlit CSS.

Radius 0 everywhere, 2px divider rules (never hairline), Archivo at weights
400/600/800, and the project-level accent override (#138eec).
"""

from __future__ import annotations

from explorer_core import (
    ACCENT,
    ACCENT_400,
    ACCENT_700,
    DIVIDER,
    GROUND,
    INK,
    NEUTRAL_600,
    SURFACE,
    rgba,
)

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&display=swap');

:root {{
  --accent: {ACCENT};
  --accent-400: {ACCENT_400};
  --accent-700: {ACCENT_700};
  --ink: {INK};
  --muted: {NEUTRAL_600};
  --divider: {DIVIDER};
  --ground: {GROUND};
  --surface: {SURFACE};
  --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
  --space-4: 16px; --space-6: 24px; --space-8: 32px;
}}

/* Set the font on the app root and let it inherit. Targeting [class*="st-"]
   also hits Streamlit's Material icon spans, whose glyphs are ligatures — the
   icon names then render as literal text ("expand_more"). */
html, body, .stApp {{
  font-family: 'Archivo', system-ui, sans-serif;
}}
.stApp {{ background: var(--ground); color: var(--ink); }}

/* Restore the icon font wherever Streamlit draws a Material glyph. */
[data-testid="stIconMaterial"],
[data-testid="stExpanderToggleIcon"],
.material-symbols-rounded,
span[class*="material-symbols"] {{
  font-family: 'Material Symbols Rounded' !important;
}}

/* Radius 0 everywhere — the design system has no rounded corners. */
.stApp button, .stApp input, .stApp select, .stApp textarea,
.stApp [data-baseweb="select"] > div, .stApp [data-baseweb="popover"] div {{
  border-radius: 0 !important;
}}

/* Must clear Streamlit Cloud's fixed header (Share / star / edit / GitHub),
   which is about 3rem tall and overlays the page. Locally that bar is hidden,
   so 2rem looked fine here and cropped the title once deployed. */
.block-container {{ padding-top: 3.5rem; padding-bottom: 3rem; max-width: 1500px; }}

/* ------------------------------------------------------------------ header */
.luc-title {{
  font-size: 28px; font-weight: 800; letter-spacing: -0.02em;
  line-height: 1.1; margin: 0; color: var(--ink);
}}
.luc-subtitle {{
  font-size: 11.5px; color: var(--muted); margin-top: 6px; font-weight: 400;
}}
/* Enough to separate two control rows without the 24px trough it started with,
   which pushed the charts below the fold. */
.luc-rule {{
  border-bottom: 2px solid var(--divider);
  margin: var(--space-4) 0 var(--space-3);
}}

/* ------------------------------------------------------------- section label */
.luc-section {{
  font-size: 16px; font-weight: 800; color: var(--ink);
  margin: var(--space-1) 0 var(--space-2);
}}
/* Graph type is the choice everything else qualifies, so it is set apart from
   the microlabels beside it by weight and size alone. An accent underline was
   tried here and read as a stray blue bar sitting on the Occupancy button
   directly below it. */
.luc-section-lead {{
  font-size: 20px; letter-spacing: -0.01em; margin-bottom: var(--space-2);
}}

/* Gap before a second control stacked under the first in the same column. */
.luc-substack {{ height: var(--space-3); }}
/* Pads a column whose first control has a microlabel, so it lines up with a
   neighbouring column whose first control sits under a section heading. */
.luc-subhead-pad {{ height: 26px; }}
/* Separates the KPI cards from the filter block below them. */
/* Separates one section from the one above it now that the rule between them
   is gone; the heading's own space does the dividing. */
.luc-section-top {{ margin-top: var(--space-4); }}
.luc-microlabel {{
  font-size: 10.5px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--muted); margin-bottom: 5px;
  white-space: nowrap;
}}
/* A slider prints its current value above the track, which lands exactly where
   a 5px-gap microlabel sits. These get the extra clearance. */
.luc-microlabel-slider {{ margin-bottom: 22px; }}

/* Heading over each of the two stacked region maps. */
.luc-mapsub {{
  font-size: 13px; font-weight: 800; color: var(--ink);
  margin: var(--space-3) 0 var(--space-1);
}}

/* Footnote above the methodology expander. Block display and real margins on
   both sides, so the expander below cannot ride up over it. */
.luc-footnote {{
  display: block; font-size: 11.5px; line-height: 1.6; color: var(--muted);
  margin: var(--space-6) 0 var(--space-4);
}}

/* ------------------------------------------------------ methodology block */
.luc-methhead {{
  font-size: 11px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.09em; color: var(--ink);
  margin: var(--space-4) 0 var(--space-2);
  padding-bottom: 5px; border-bottom: 1px solid var(--divider);
}}
.luc-meth {{ display: flex; flex-direction: column; gap: var(--space-2); }}
.luc-methrow {{ display: grid; grid-template-columns: 190px 1fr; gap: var(--space-3); }}
.luc-methterm {{ font-size: 12.5px; font-weight: 800; color: var(--ink); }}
.luc-methdef {{ font-size: 12.5px; line-height: 1.55; color: var(--muted); }}
.luc-methnote {{
  font-size: 11.5px; color: var(--muted); font-style: italic;
  margin-top: var(--space-4); padding-top: var(--space-2);
  border-top: 1px solid var(--divider);
}}
@media (max-width: 720px) {{
  .luc-methrow {{ grid-template-columns: 1fr; gap: 2px; }}
}}

/* --------------------------------------------------------------- KPI cards */
.luc-kpis {{
  display: grid; grid-template-columns: repeat(5, 1fr);
  border: 2px solid var(--divider); background: var(--surface);
}}
.luc-kpis-6 {{ grid-template-columns: repeat(6, 1fr); }}
/* Six cards get tighter type and padding so the row survives to a much narrower
   viewport before wrapping. Wrapping to 3x2 doubles the block's height, which
   costs far more vertical space than shrinking the numbers does legibility. */
.luc-kpis-6 .luc-kpi {{ padding: 9px 11px; }}
.luc-kpis-6 .luc-kpi-label {{ font-size: 9px; letter-spacing: 0.06em; }}
.luc-kpis-6 .luc-kpi-value {{ font-size: 22px; margin-top: 3px; }}
.luc-kpis-6 .luc-kpi-sub {{ font-size: 10.5px; line-height: 1.3; }}
@media (max-width: 1050px) {{
  .luc-kpis-6 {{ grid-template-columns: repeat(3, 1fr); }}
  .luc-kpis-6 .luc-kpi:nth-child(3n+1) {{ border-left: none; }}
  .luc-kpis-6 .luc-kpi:nth-child(n+4) {{ border-top: 2px solid var(--divider); }}
}}
.luc-kpi {{ padding: 14px 18px; border-left: 2px solid var(--divider); }}
.luc-kpi:first-child {{ border-left: none; }}
.luc-kpi-label {{
  font-size: 10px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--accent);
}}
.luc-kpi-value {{
  font-size: 28px; font-weight: 800; line-height: 1.15;
  margin-top: 6px; color: var(--ink); letter-spacing: -0.02em;
}}
.luc-kpi-sub {{ font-size: 11.5px; color: var(--muted); margin-top: 2px; }}

/* ------------------------------------------------------------ filter cards */
/* Same trick as the chart panel: st.container(border=True) gives no class to
   hook, so the card is identified by a marker div placed inside it. Lighter
   than the chart panel — these frame controls, not results, and should not
   compete with the charts for attention. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.luc-filtercard) {{
  border: 1px solid var(--divider) !important;
  border-radius: 0 !important;
  background: var(--surface);
  padding: var(--space-3) var(--space-4) var(--space-4);
  height: 100%;
}}
.luc-filtercard {{ display: none; }}
.luc-cardhead {{
  font-size: 11px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.09em; color: var(--ink);
  padding-bottom: 6px; margin-bottom: var(--space-3);
  border-bottom: 1px solid var(--divider);
}}
/* Inside a card the second control needs air from the first. */
.luc-cardgap {{ height: var(--space-3); }}

/* ------------------------------------------------------------- chart panel */
/* st.container(border=True) renders a wrapper we can't put a class on, so scope
   by content: only the wrapper containing the panel title gets the card
   treatment. Avoids styling every other vertical block on the page. */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.luc-panel-title) {{
  border: 2px solid var(--divider) !important;
  border-radius: 0 !important;
  background: var(--surface);
  padding: var(--space-3) var(--space-4) var(--space-4);
  margin-top: var(--space-3);
}}
.luc-panel-title {{ font-size: 19px; font-weight: 800; letter-spacing: -0.01em; }}
.luc-panel-sub {{ font-size: 11.5px; color: var(--muted); margin-top: 3px; }}
.luc-panel-rule {{ border-bottom: 2px solid var(--divider); margin: var(--space-3) 0 var(--space-4); }}

.luc-legend {{ display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: center; }}
.luc-legend-item {{ display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; }}
.luc-swatch {{ width: 13px; height: 13px; display: inline-block; }}
.luc-legend-total {{ color: var(--muted); font-weight: 400; }}

.luc-empty {{
  display: flex; align-items: center; justify-content: center;
  min-height: 300px; color: var(--muted); font-size: 13px;
  border: 2px dashed var(--divider);
}}

/* --------------------------------------------------------- occupancy grid */
.luc-occ {{ display: grid; gap: 2px; align-items: stretch; }}
.luc-occ-cell {{
  display: flex; align-items: center; justify-content: center;
  min-height: 32px; font-size: 12px; font-weight: 600;
}}
.luc-occ-rowlabel {{
  display: flex; align-items: center; font-size: 11px; font-weight: 800;
  letter-spacing: 0.06em; color: var(--ink);
}}
/* Names the row-label column. Same muted weight as the season headers beside
   it, so it reads as a header rather than as data. */
.luc-occ-corner {{
  display: flex; flex-direction: column; justify-content: flex-end;
  font-size: 10px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted);
  line-height: 1.25; padding-bottom: 4px;
}}

/* Season over year, so the column reads without decoding an abbreviation. */
.luc-occ-collabel {{
  display: flex; flex-direction: column; align-items: center;
  justify-content: flex-end; line-height: 1.25;
  font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); padding-bottom: 4px;
}}
.luc-occ-season {{ font-size: 10px; }}
.luc-occ-year {{ font-size: 9.5px; font-weight: 400; letter-spacing: 0.04em; }}
.luc-occ-legend {{
  display: flex; align-items: center; gap: var(--space-2);
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); font-weight: 800; margin-top: var(--space-3);
}}
.luc-occ-gradient {{
  height: 10px; width: 140px; border: 1px solid var(--divider);
  background: linear-gradient(to right, {rgba(ACCENT, 0.05)}, {rgba(ACCENT, 0.95)});
}}

/* The plots behind a grid, named. Monospaced so the codes align and scan as a
   list, and wrapping rather than truncating — a hidden plot name is the thing
   this is here to prevent. */
/* The plot roster can run to several wrapped lines at full selection, and it
   sat hard against the column headers — two dense blocks of small text with
   nothing between them. The gap below separates the list from the grid it
   describes. */
.luc-occ-roster {{
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10.5px; color: var(--muted); line-height: 1.5;
  margin: 0 0 var(--space-4); word-break: break-word;
}}

/* Effort row label sits apart from the species codes. */
.luc-occ-efflabel {{
  color: var(--muted); font-size: 10px; letter-spacing: 0.08em;
  text-transform: uppercase;
}}

/* Not surveyed: hatched, so it reads as "no data" rather than a low value. */
.luc-occ-na {{
  color: var(--muted); font-size: 10px; font-weight: 800; letter-spacing: 0.06em;
  background: repeating-linear-gradient(
    45deg, #f0efef, #f0efef 4px, #e3e0e0 4px, #e3e0e0 8px);
}}
.luc-occ-naswatch {{
  display: inline-block; width: 13px; height: 10px; margin-right: 5px;
  vertical-align: middle; border: 1px solid var(--divider);
  background: repeating-linear-gradient(
    45deg, #f0efef, #f0efef 3px, #e3e0e0 3px, #e3e0e0 6px);
}}
.luc-occ-nakey {{ margin-left: var(--space-4); display: inline-flex; align-items: center; }}

/* Outside this panel's treatment period: flat grey, no hatching and no label,
   so it recedes rather than competing with the NA cells that carry meaning. */
.luc-occ-outside {{ background: #eceaea; }}
.luc-occ-outswatch {{
  display: inline-block; width: 13px; height: 10px; margin-right: 5px;
  vertical-align: middle; border: 1px solid var(--divider); background: #eceaea;
}}

/* Compare-by group panels. */
.luc-occ-grouphead {{
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 800; color: var(--ink);
  margin: 0 0 var(--space-2);
}}
.luc-occ-groupmeta {{
  font-size: 10.5px; font-weight: 400; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.08em;
}}
.luc-occ-spacer {{
  border-top: 2px solid var(--divider);
  margin: var(--space-6) 0 var(--space-4);
}}

.luc-occ-note {{
  font-size: 11.5px; line-height: 1.55; color: var(--muted);
  border-left: 2px solid var(--divider); padding-left: var(--space-3);
  margin-top: var(--space-4);
}}
.luc-occ-note b {{ color: var(--ink); }}

.luc-panel-where {{ color: var(--muted); font-weight: 600; }}

/* Treatment context strip above every Occupancy grid. */
.luc-treatbar {{
  display: flex; flex-wrap: wrap; gap: var(--space-6);
  padding: 8px 0 12px; margin-bottom: var(--space-4);
  border-bottom: 2px solid var(--divider);
}}
.luc-treatitem {{ display: inline-flex; align-items: center; gap: 7px; }}
.luc-treatkey {{
  font-size: 10px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--muted);
}}
/* Only the colour-key form needs the label pushed off the period name. */
.luc-treatval + .luc-treatkey {{ margin-left: var(--space-2); }}
.luc-treatval {{
  font-size: 13px; font-weight: 800; color: var(--ink);
  text-transform: uppercase; letter-spacing: 0.04em;
}}
.luc-treattype {{ font-size: 13px; font-weight: 600; color: var(--ink); }}

/* Treatment-era band above the season labels on the split heatmap. */
.luc-occ-periodhead {{
  display: flex; align-items: flex-end; justify-content: center;
  font-size: 11px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.1em; padding-bottom: 4px; min-height: 22px;
}}
.luc-occ-ramplabel {{
  font-size: 10px; font-weight: 800; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--ink); margin-left: var(--space-3);
}}

/* --------------------------------------------- Streamlit widget overrides */

/* Segmented controls and pill groups.
   Both render inside div[data-testid="stButtonGroup"], and the individual
   buttons carry their own testid — targeting the buttons directly is what
   actually wins against Streamlit's defaults. */
div[data-testid="stButtonGroup"] button,
button[data-testid="stBaseButton-segmented_control"],
button[data-testid="stBaseButton-pills"],
button[data-testid="stBaseButton-segmented_controlActive"],
button[data-testid="stBaseButton-pillsActive"] {{
  border-radius: 0 !important;
  border: 1px solid var(--divider) !important;
  font-family: 'Archivo', sans-serif !important;
  font-weight: 600 !important;
  font-size: 12.5px !important;
}}

/* Active vs inactive are defined as MUTUALLY EXCLUSIVE selectors rather than
   relying on source order or !important. A plain descendant selector like
   `div[data-testid="stButtonGroup"] button` (0,1,2) actually outranks
   `button[data-testid="stBaseButton-pillsActive"]` (0,1,1), so the "inactive"
   style would otherwise win on selected pills and they'd never fill in.

   Streamlit marks the selected item differently per widget: segmented controls
   set aria-checked, pills do not — both, however, get a data-testid ending in
   "Active". Matching on the suffix covers each of them. */
/* Streamlit has marked the selected item four different ways across versions:
   a `kind` attribute ending in "Active" (<=1.44), a `data-testid` ending in
   "Active" (>=1.45), and aria-checked / aria-pressed depending on the widget.
   Match all of them so this holds regardless of the installed version. */
:is(div[data-testid="stButtonGroup"], div[data-testid="stSegmentedControl"])
  button:not([kind$="Active"]):not([data-testid$="Active"]):not([aria-checked="true"]):not([aria-pressed="true"]):not([aria-selected="true"]) {{
  background: var(--surface) !important;
  border-color: var(--divider) !important;
  color: var(--ink) !important;
}}
:is(div[data-testid="stButtonGroup"], div[data-testid="stSegmentedControl"])
  button:not([kind$="Active"]):not([data-testid$="Active"]):not([aria-checked="true"]):not([aria-pressed="true"]):not([aria-selected="true"]) * {{
  color: var(--ink) !important;
}}

:is(div[data-testid="stButtonGroup"], div[data-testid="stSegmentedControl"])
  :is(button[kind$="Active"], button[data-testid$="Active"],
      button[aria-checked="true"], button[aria-pressed="true"],
      button[aria-selected="true"]) {{
  background: var(--accent) !important;
  border-color: var(--accent) !important;
  color: #ffffff !important;
  position: relative; z-index: 1;
}}
/* Streamlit nests the label in a <p>/<div>, so recolour descendants too. */
:is(div[data-testid="stButtonGroup"], div[data-testid="stSegmentedControl"])
  :is(button[kind$="Active"], button[data-testid$="Active"],
      button[aria-checked="true"], button[aria-pressed="true"],
      button[aria-selected="true"]) * {{
  color: #ffffff !important;
}}

/* Segments butt against each other rather than sitting in a spaced row, and a
   segmented control is a single unit — it should never wrap mid-control. */
div[data-testid="stButtonGroup"] {{ gap: 0 !important; flex-wrap: nowrap; }}
div[data-testid="stButtonGroup"] button {{
  margin: 0 -1px 0 0 !important;
  white-space: nowrap !important;
  padding: 7px 10px !important;
}}

/* ...but pill groups (Season, Treatment type) stay as separate chips, per the
   design. Both widgets share stButtonGroup, so distinguish on button type. */
/* Pills are independent chips, so they may wrap onto further rows. */
div[data-testid="stButtonGroup"]:has(button[data-testid^="stBaseButton-pills"]) {{
  gap: 6px !important;
  flex-wrap: wrap !important;
}}
div[data-testid="stButtonGroup"]:has(button[data-testid^="stBaseButton-pills"]) button {{
  margin: 0 !important;
}}

/* Buttons + popover triggers. */
.stButton button, div[data-testid="stPopover"] button {{
  border-radius: 0 !important;
  border: 1px solid var(--divider) !important;
  background: var(--surface) !important;
  color: var(--ink) !important;
  font-family: 'Archivo', sans-serif !important;
  font-weight: 800 !important;
  font-size: 12.5px !important;
}}
.stButton button:hover, div[data-testid="stPopover"] button:hover {{
  border-color: var(--accent) !important; color: var(--accent) !important;
}}
/* The triggers are set to fill their column, which is right on a wide layout.
   But Streamlit stacks columns on a narrow one, and a filled column is then
   the whole page — Plot stretched edge to edge while its neighbours stayed
   small. Capping the width keeps every filter the same size at any viewport. */
/* A control must never be narrower than its own label. Streamlit shrinks
   columns as the viewport narrows and the contents get clipped — 'Season
   (3/3)' became 'Season (3/' and the year selects collapsed to a bare ':'.
   Sizing to content and refusing to shrink keeps the text whole; the row wraps
   instead, which is the readable failure mode. */
div[data-testid="stPopover"] button {{
  width: max-content; min-width: max-content; max-width: 100%;
  white-space: nowrap;
}}
/* The only selectboxes are the two year pickers. They hold four characters, so
   they are capped as well as floored — left to themselves they stretched to
   fill half the row. */
.stSelectbox div[data-baseweb="select"] {{ min-width: 88px; max-width: 116px; }}
.stSelectbox div[data-baseweb="select"] > div {{ white-space: nowrap; }}
/* Primary button = filled accent. */
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {{
  background: var(--accent) !important; border-color: var(--accent) !important;
  color: #ffffff !important;
}}
.stButton button[kind="primary"]:hover {{ color: #ffffff !important; opacity: 0.9; }}

.stDownloadButton button {{
  border-radius: 0 !important;
  border: 1px solid var(--divider) !important;
  background: var(--surface) !important;
  color: var(--ink) !important;
  font-weight: 800 !important; font-size: 12.5px !important;
  font-family: 'Archivo', sans-serif !important;
}}

/* Popover panel: the only place the design uses elevation. Give it a floor
   width so the All/None row doesn't wrap inside a narrow trigger column. */
div[data-baseweb="popover"] > div {{
  box-shadow: 0 3px 10px rgba(45,43,43,0.16) !important;
  border: 2px solid var(--divider) !important;
  border-radius: 0 !important;
}}
div[data-testid="stPopoverBody"] {{
  min-width: 300px !important;
  max-height: 460px;
  overflow-y: auto;
}}
/* Button labels never break mid-word. */
.stButton button, .stDownloadButton button, div[data-testid="stPopover"] button {{
  white-space: nowrap !important;
}}

/* Year selects. */
div[data-baseweb="select"] > div {{
  border-radius: 0 !important; border: 1px solid var(--divider) !important;
  background: var(--surface) !important; font-size: 12.5px !important;
}}

/* Vertical rules between toolbar filter groups. */
/* The filter toolbar's vertical rules are gone: they implied grouping between
   independent controls and were read as confusing. Whitespace separates them
   now. Rule kept only in case a genuine divider is wanted later. */
.luc-vrule {{ display: flex; justify-content: center; width: 100%; }}
.luc-vrule::before {{
  content: ""; border-left: 2px solid var(--divider); height: 58px;
}}

/* Tighten default Streamlit spacing so the toolbar reads as one strip. */
div[data-testid="stVerticalBlock"] {{ gap: 0.5rem; }}
div[data-testid="stHorizontalBlock"] {{ align-items: flex-end; }}
/* ...except a row of cards, which must start level and stretch to a common
   height. Bottom-alignment is right for bare controls sitting on a shared
   baseline, and wrong for boxes: it hung the shorter card off the bottom. */
div[data-testid="stHorizontalBlock"]:has(.luc-filtercard) {{
  align-items: stretch;
}}
/* The panel keeps its own breathing room; only the control strip is squeezed. */
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {{
  gap: 0.55rem;
}}

/* Checkbox accent inside popovers. */
.stCheckbox [data-baseweb="checkbox"] span[data-checked="true"] {{
  background-color: var(--accent) !important; border-color: var(--accent) !important;
}}

#MainMenu, footer {{ visibility: hidden; }}
</style>
"""


def plotly_layout(height: int = 340) -> dict:
    """Shared Plotly layout: flat, gridless-ish, Archivo, no rounded chrome."""
    return dict(
        height=height,
        margin=dict(l=48, r=18, t=18, b=44),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Archivo, system-ui, sans-serif", size=12, color=INK),
        xaxis=dict(
            showgrid=False,
            linecolor=DIVIDER,
            linewidth=2,
            ticks="outside",
            tickcolor=DIVIDER,
            tickfont=dict(size=11, color=NEUTRAL_600),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=DIVIDER,
            gridwidth=1,
            zeroline=False,
            linecolor="rgba(0,0,0,0)",
            tickfont=dict(size=11, color=NEUTRAL_600),
        ),
        showlegend=False,
        hoverlabel=dict(
            bgcolor=INK,
            font=dict(family="Archivo, sans-serif", size=12, color="#ffffff"),
            bordercolor=INK,
        ),
    )
