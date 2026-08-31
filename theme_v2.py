"""
Version 2 look — the Claude Design "Species Explorer Dashboard" mockup.

Layered on top of theme.CSS rather than replacing it. The chart internals
(the occupancy grid, the legends, the methodology table) already have styled
classes there and are unchanged in v2; only the page shell around them is new.
Appending means v2 inherits all of that and overrides just what it restyles,
so a fix to a heatmap class benefits both versions.

Tokens are taken from the mockup as designed:
  ink #201e1d, accent #146AB3, page #ffffff, hairline #ddd9d7,
  muted #6b6866 / #8d8987, Archivo throughout, square corners except the
  KPI cards, and 2px ink rules under every section heading.
"""

from __future__ import annotations

import theme

V2_INK = "#201e1d"
V2_ACCENT = "#146AB3"
V2_MUTED = "#6b6866"
V2_FAINT = "#8d8987"
V2_HAIR = "#ddd9d7"
V2_CARD_EDGE = "#e2dedc"
V2_TRACK = "#e4e0de"

_V2 = f"""
/* ═══════════════════════════════════════════════ v2 shell — sidebar layout */

/* The mockup is a white page, not the light-grey one v1 uses. */
.stApp, body {{ background: #ffffff; }}

/* The header strip Cloud injects would otherwise sit over the title. */
.block-container {{
  padding-top: 2.4rem !important;
  padding-bottom: 4rem !important;
  max-width: 100% !important;
}}

/* ── sidebar ────────────────────────────────────────────────────────────── */
/* Width is a starting position, not a lock. Streamlit's own divider is
   draggable and writes an inline width onto this element; the earlier
   `width: 302px !important` beat that inline style, which is why the panel
   could not be resized. No !important here, so the drag wins, and the bounds
   keep it between unusable and half the page. */
section[data-testid="stSidebar"] {{
  background: #ffffff;
  border-right: 2px solid {V2_INK};
  width: 302px;
  min-width: 210px !important;
  max-width: 620px !important;
}}
section[data-testid="stSidebar"] > div {{ padding-top: 0; }}
section[data-testid="stSidebar"] .block-container {{ padding-top: 0 !important; }}
.v2-brand {{
  padding: 4px 0 16px;
  border-bottom: 2px solid {V2_INK};
  margin-bottom: 18px;
}}
.v2-kicker {{
  font-size: 13px; letter-spacing: 0.13em; font-weight: 700;
  color: {V2_ACCENT}; text-transform: uppercase;
}}
.v2-brandtitle {{
  font-size: 22px; font-weight: 700; line-height: 1.1; margin-top: 6px;
  color: {V2_INK};
}}

/* Group heading inside the sidebar: Time, Location, Species, Treatments. */
.v2-group {{
  /* Larger and darker than the design's 11px/#6b6866: at that size the group
     headings sat below the control labels beneath them and stopped reading as
     headings at all. */
  font-size: 14px; letter-spacing: 0.12em; font-weight: 800;
  color: {V2_INK}; text-transform: uppercase;
  margin: 4px 0 14px;
}}
.v2-grouprule {{ border-top: 1px solid {V2_HAIR}; margin: 18px 0 14px; }}

/* Control label + its live value, on one baseline. */
.v2-ctl {{
  display: flex; justify-content: space-between; align-items: baseline;
  /* Clearance from the control underneath. At 2px the label sat on the
     slider track and on the top edge of the dropdowns. */
  margin: 0 0 9px;
}}
/* Control names and their values move together, so the value never looks
   like a different tier of information from the label beside it. */
.v2-ctl-name {{ font-size: 15px; font-weight: 600; color: {V2_INK}; }}
.v2-ctl-val {{
  font-size: 15px; font-weight: 700; color: {V2_ACCENT};
  font-variant-numeric: tabular-nums;
}}

/* ── main column ────────────────────────────────────────────────────────── */
.v2-title {{
  font-size: 38px; font-weight: 700; letter-spacing: -0.02em; line-height: 1;
  color: {V2_INK}; margin: 0;
}}
.v2-scope {{
  margin-top: 10px; font-size: 13px; color: {V2_MUTED};
  font-variant-numeric: tabular-nums;
}}
.v2-headrule {{ border-bottom: 2px solid {V2_INK}; margin: 20px 0 24px; }}

/* KPI cards. The one place the design allows a radius. */
.v2-kpis {{
  display: grid; gap: 16px; margin: 0 0 22px;
  grid-template-columns: repeat(auto-fit, minmax(178px, 1fr));
}}
.v2-kpi {{
  border: 1px solid {V2_CARD_EDGE}; border-radius: 10px; background: #ffffff;
  box-shadow: 0 1px 2px rgba(32,30,29,0.06);
  padding: 15px 17px 16px; min-width: 0;
}}
.v2-kpi-label {{ font-size: 13px; font-weight: 700; color: {V2_INK}; }}
.v2-kpi-value {{
  font-size: clamp(19px, 2.1vw, 32px); font-weight: 700; line-height: 1.15;
  margin-top: 4px; letter-spacing: -0.02em; white-space: nowrap;
  font-variant-numeric: tabular-nums; color: {V2_INK};
}}
.v2-kpi-sub {{ font-size: 11.5px; color: {V2_FAINT}; margin-top: 7px; }}

/* Section heading: title left, scope note right, 2px ink rule beneath. */
.v2-panelhead {{
  display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: 2px solid {V2_INK}; padding-bottom: 9px; gap: 18px;
}}
.v2-panelh2 {{ margin: 0; font-size: 19px; font-weight: 700; color: {V2_INK}; }}
.v2-panelnote {{
  font-size: 11px; color: {V2_FAINT}; letter-spacing: 0.05em;
  text-transform: uppercase; text-align: right; flex: 0 1 auto;
}}
.v2-panelsub {{ font-size: 12px; color: {V2_MUTED}; margin: 9px 0 2px; }}
/* Used when a panel puts a control on its heading row: the heading and the
   control are separate Streamlit columns, so the rule cannot be a border on
   the heading itself and is drawn as its own full-width element beneath. */
.v2-panelrule {{ border-bottom: 2px solid {V2_INK}; margin: 2px 0 0; }}
.v2-sectiongap {{ height: 34px; }}

/* Species key above the hourly chart and the map. */
.v2-key {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 14px 0 18px; }}
.v2-key-item {{
  display: flex; align-items: center; gap: 7px;
  font-size: 12px; font-weight: 600; color: {V2_INK};
}}
/* Square swatches, as the design draws them, not the round dots v1 uses. */
.v2-key-dot {{ width: 12px; height: 12px; display: inline-block; }}

/* Map credit: small, flush to the bottom right of the map it belongs to.
   MapLibre's own control is hidden because it sits inside the frame at a size
   that competes with the basemap's own labels; the requirement is that the
   attribution is present and legible, not that it is in the corner of the
   canvas. */
.v2-mapcredit {{
  text-align: right; font-size: 10px; color: {V2_FAINT};
  margin: -6px 0 6px;
}}
.v2-mapcredit a {{ color: {V2_FAINT}; text-decoration: underline; }}
.maplibregl-ctrl-attrib, .mapboxgl-ctrl-attrib,
.maplibregl-ctrl-bottom-right, .mapboxgl-ctrl-bottom-right {{
  display: none !important;
}}

/* The roster above each occupancy grid. Given a label so it is not a loose
   string of codes, and set in the muted tone so it stays subordinate to the
   grid it describes. */
.luc-occ-roster {{
  /* Archivo, not the monospace theme.py sets. Monospace made sense when this
     was a column of plot codes; now that it reads as a sentence it should be
     the same face as everything else on the panel. */
  font-family: 'Archivo', system-ui, sans-serif !important;
  font-size: 11.5px !important;
  color: {V2_MUTED} !important;
  margin: 2px 0 10px !important;
}}
.luc-occ-rosterkey {{
  font-family: 'Archivo', system-ui, sans-serif;
  font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: {V2_FAINT};
  margin-right: 8px;
}}

/* ── Streamlit widget overrides, v2 ─────────────────────────────────────── */

/* Square, hairline-bordered selects that fill the sidebar, per the mockup —
   v1's rule caps them at 116px, which is right for a toolbar and wrong here. */
section[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
  border-radius: 0 !important;
  border: 1px solid {V2_HAIR} !important;
  min-width: 0 !important; max-width: none !important;
  background: #ffffff !important;
}}
/* The selected value sits in a nested div of its own, which carries its own
   font-size — sizing the control alone leaves the text small inside a
   full-height box. Set on the value and on the menu options together, so the
   list matches what the closed control shows. */
section[data-testid="stSidebar"] div[data-baseweb="select"] div[data-baseweb="base-input"],
section[data-testid="stSidebar"] div[data-baseweb="select"] input,
section[data-testid="stSidebar"] div[data-baseweb="select"] > div > div,
section[data-testid="stSidebar"] div[data-baseweb="select"] span,
div[data-baseweb="popover"] li,
div[data-baseweb="popover"] div[role="option"] {{
  font-size: 14px !important;
  line-height: 1.45 !important;
}}
/* The four checklist dropdowns. Their trigger is a popover button, styled to
   read as a select: full width, one fixed row, hairline border, value left,
   chevron right. */
section[data-testid="stSidebar"] div[data-testid="stPopover"] {{
  margin-bottom: 16px;
}}
section[data-testid="stSidebar"] div[data-testid="stPopover"] > div > button {{
  border-radius: 0 !important;
  border: 1px solid {V2_HAIR} !important;
  background: #ffffff !important;
  color: {V2_INK} !important;
  font-family: 'Archivo', sans-serif !important;
  font-weight: 400 !important;
  font-size: 14px !important;
  width: 100% !important;
  justify-content: space-between !important;
  text-align: left !important;
  padding: 6px 10px !important;
  min-height: 0 !important;
}}
section[data-testid="stSidebar"] div[data-testid="stPopover"] > div > button p {{
  font-size: 14px !important;
  font-weight: 400 !important;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
/* The open panel sizes to its longest option rather than to Streamlit's
   default popover width, which left a column of empty space beside a list of
   short preserve names. Capped so a long plot label wraps instead of pushing
   the panel off the side of the sidebar. */
/* Two boxes were showing because two elements were each drawing one: the
   floating surface Streamlit positions (which theme.py gives a 2px border)
   and the body inside it. Sizing only the body to its content left it as a
   narrow panel inside a wider bordered one. The surface is the box; the body
   is transparent and borderless, and both size to the longest option. */
/* The floating surface is now just a positioner: no border, no shadow, no
   fill. The body below is the box, so there is one outline rather than two —
   and, importantly, one opaque background. */
div[data-baseweb="popover"] > div {{
  width: max-content !important;
  min-width: 0 !important;
  max-width: 340px !important;
  border: none !important;
  box-shadow: none !important;
  background: transparent !important;
}}
div[data-testid="stPopoverBody"] {{
  width: max-content !important;
  min-width: 0 !important;
  max-width: 320px !important;
  /* max-content sizes to the text exactly, so the breathing room has to come
     from padding. Even on both sides, and modest — the point of sizing to
     content was to stop the empty column beside short names. */
  padding: 12px 18px !important;
  /* Opaque, or the page reads straight through the list. */
  background: #ffffff !important;
  border: 1px solid {V2_INK} !important;
  box-shadow: 0 4px 14px rgba(32,30,29,0.18) !important;
}}
div[data-testid="stPopoverBody"] label {{ width: max-content; }}

/* Left padding again, with the popover element in the selector so it outranks
   whatever Streamlit sets on the body itself — the shorthand above was being
   applied on the right but reset on the left. */
div[data-baseweb="popover"] div[data-testid="stPopoverBody"] {{
  padding-left: 20px !important;
  /* The padding was there all along — it was being eaten. Streamlit sets
     box-sizing: border-box globally, and with `width: max-content` that makes
     the width exactly the content's width *including* padding, so the rows
     were squeezed back out over the left inset. Content-box puts the padding
     outside the measured width, which is what makes it visible. */
  box-sizing: content-box !important;
}}
div[data-baseweb="popover"] div[data-testid="stPopoverBody"] > div {{
  padding-left: 0 !important;
  margin-left: 0 !important;
}}

/* The bulk action inside a popover matches the Season/Species one: outlined
   accent text, sized to itself rather than spanning the popover. */
div[data-testid="stPopoverBody"] .stButton button {{
  width: auto !important;
  border: 1px solid {V2_ACCENT} !important;
  background: #ffffff !important;
  color: {V2_ACCENT} !important;
  padding: 1px 6px !important;
  text-transform: uppercase;
}}
div[data-testid="stPopoverBody"] .stButton button p {{
  font-size: 12px !important;
  font-weight: 700 !important;
  letter-spacing: 0.06em !important;
  line-height: 1.5 !important;
}}
div[data-testid="stPopoverBody"] .stButton button:hover {{
  background: {V2_ACCENT} !important;
}}
div[data-testid="stPopoverBody"] .stButton button:hover p {{
  color: #ffffff !important;
}}
div[data-testid="stPopoverBody"] label p {{ font-size: 13px !important; }}
section[data-testid="stSidebar"] .stSelectbox {{
  min-width: 0 !important; max-width: none !important; margin-bottom: 10px;
}}

/* Sliders in the accent, with the value read out in the label row above
   rather than in Streamlit's floating bubble. */
section[data-testid="stSidebar"] div[data-testid="stSlider"] [role="slider"] {{
  background-color: {V2_ACCENT} !important;
  border-color: #ffffff !important;
}}
/* Matched on a substring rather than exact testids: Streamlit has renamed
   these across versions (stThumbValue / stSliderThumbValue, TickBar /
   stSliderTickBar), and the exact names missed the pale blue values that were
   still riding on the track. */
section[data-testid="stSidebar"] [data-testid*="ThumbValue"],
section[data-testid="stSidebar"] [data-testid*="TickBar"],
section[data-testid="stSidebar"] [class*="StyledThumbValue"] {{
  display: none !important;
}}
section[data-testid="stSidebar"] div[data-testid="stSlider"] {{
  padding-top: 0; margin-bottom: 0;
}}
/* Streamlit reserves room beneath the track for the tick bar it draws. That
   bar is hidden above, but the space it held stayed, which is what left the
   scale floating below the line. */
section[data-testid="stSidebar"] div[data-testid="stSlider"] > div {{
  padding-bottom: 0 !important;
}}
/* Each step gets a mark on the track and a label centred under it, both
   absolutely placed at the step's own percentage. Flexbox space-between put
   the labels between the steps rather than on them, which read as a different
   scale from the one the thumb snaps to. */
.v2-ticks {{
  /* Pulled up until the marks meet the track. The negative margin is doing
     the work of the space BaseWeb's slider keeps around its thumb, which is
     taller than the 4px line it draws. */
  /* The bottom margin is the gap to whatever control comes next —
     Season under the year scale, Detection unit under confidence. */
  position: relative; height: 19px; margin: -17px 0 26px;
  font-size: 11px; color: {V2_FAINT}; font-variant-numeric: tabular-nums;
}}
.v2-tick {{ position: absolute; transform: translateX(-50%); top: 7px; }}
.v2-tick-mark {{
  position: absolute; top: -1px; width: 1px; height: 6px;
  background: {V2_HAIR}; transform: translateX(-50%);
}}

/* Chips. Selected chips are filled by the caller (species get their own
   colour); this is the unselected state and the shared geometry. */
section[data-testid="stSidebar"] .stButton button {{
  border-radius: 0 !important;
  border: 1px solid {V2_HAIR} !important;
  background: #ffffff !important;
  color: {V2_INK} !important;
  font-family: 'Archivo', sans-serif !important;
  font-weight: 700 !important;
  font-size: 11px !important;
  padding: 4px 2px !important;
  letter-spacing: 0;
  min-height: 0 !important;
  width: 100%;
}}
/* The label is a <p> inside the button and does not shrink with it, so at
   narrow panel widths 'Summer' simply drew past the border. Clipped to the
   chip instead, with an ellipsis to show it has been cut. */
section[data-testid="stSidebar"] .stButton button {{ overflow: hidden; }}
section[data-testid="stSidebar"] .stButton button p,
section[data-testid="stSidebar"] .stButton button div {{
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 100%;
}}
section[data-testid="stSidebar"] .stButton button[kind="primary"] {{
  background: {V2_ACCENT} !important;
  border-color: {V2_ACCENT} !important;
  color: #ffffff !important;
}}
/* Species chips are smaller than the season ones — there are eight now and
   there will be twenty-odd, and a four-letter code needs very little room.
   Matched on the key prefix, so this misses the season chips. */
section[data-testid="stSidebar"] [class*="st-key-v2sp_"] button {{
  font-size: 10px !important;
  padding: 3px 1px !important;
  font-weight: 700 !important;
}}

/* Species chips size to their own text and wrap, rather than dividing the row
   into five equal columns. Streamlit's columns are percentage-width, so a
   narrow panel squeezed every chip until the four-letter code ellipsed to a
   single letter — which is the one thing the chip has to show. Letting the row
   wrap means the chips keep their width and spill onto another line instead.
   Scoped by the key prefix so the season chips keep their even columns. */
div[data-testid="stHorizontalBlock"]:has([class*="st-key-v2sp_"]) {{
  flex-wrap: wrap !important;
  gap: 5px !important;
}}
div[data-testid="stHorizontalBlock"]:has([class*="st-key-v2sp_"]) > div {{
  flex: 0 0 auto !important;
  width: auto !important;
  min-width: 0 !important;
}}
section[data-testid="stSidebar"] [class*="st-key-v2sp_"] button {{
  width: auto !important;
  padding: 3px 6px !important;
  overflow: visible !important;
}}
section[data-testid="stSidebar"] [class*="st-key-v2sp_"] button p,
section[data-testid="stSidebar"] [class*="st-key-v2sp_"] button div {{
  overflow: visible !important;
  text-overflow: clip !important;
}}

/* Tighten the gaps between chip columns so a row reads as one strip. */
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {{ gap: 5px; }}
section[data-testid="stSidebar"] div[data-testid="stElementContainer"] {{ margin-bottom: 0; }}

/* The bulk all/none action. The mockup draws this as bare blue text, which
   did not read as clickable at all — it is an outlined accent button here,
   sized well below the chips so it stays secondary to them. */
section[data-testid="stSidebar"] .st-key-v2_bulk_seas button,
section[data-testid="stSidebar"] .st-key-v2_bulk_sp button {{
  border: 1px solid {V2_ACCENT} !important;
  background: #ffffff !important;
  color: {V2_ACCENT} !important;
  font-size: 12px !important; letter-spacing: 0.06em;
  font-weight: 700 !important;
  text-transform: uppercase;
  padding: 1px 6px !important;
  line-height: 1.7 !important;
  width: auto !important; min-width: 0;
  margin-bottom: 8px;
}}
/* The size has to be set on the label too, not just the button. Streamlit
   wraps a button's text in its own <p> inside a markdown container, and that
   <p> carries a font-size of its own — which is why every reduction on the
   button alone left this text exactly where it was. */
section[data-testid="stSidebar"] .st-key-v2_bulk_seas button p,
section[data-testid="stSidebar"] .st-key-v2_bulk_seas button div,
section[data-testid="stSidebar"] .st-key-v2_bulk_sp button p,
section[data-testid="stSidebar"] .st-key-v2_bulk_sp button div {{
  font-size: 12px !important;
  line-height: 1.5 !important;
  letter-spacing: 0.06em !important;
}}

section[data-testid="stSidebar"] .st-key-v2_bulk_seas button:hover,
section[data-testid="stSidebar"] .st-key-v2_bulk_sp button:hover {{
  background: {V2_ACCENT} !important; color: #ffffff !important;
}}

/* Reset spans the sidebar and is the one outlined-ink control. */
section[data-testid="stSidebar"] .st-key-v2_reset button {{
  border: 1px solid {V2_INK} !important;
  font-size: 12.5px !important; padding: 9px !important;
}}

/* Panel-level toggles (heatmap mode, hourly facet) sit on the heading row. */
div[data-testid="stButtonGroup"] button {{ font-size: 11.5px !important; }}

/* Type in the panel is a fixed size at every width. It was briefly scaled to
   the sidebar's own width in cqw so it would shrink as the divider moved, but
   only the text responded — the chips and dropdowns are laid out by Streamlit
   and kept their size — so narrowing the panel shrank the headings against
   controls that had not moved. Labels wrap or ellipse when the panel gets
   tight, which is the ordinary behaviour and reads better than a heading that
   changes size as you drag. */

"""

# theme.CSS is a complete <style> element, so the v2 rules need their own —
# appended raw they landed after the closing tag and rendered as page text.
CSS = theme.CSS + "\n<style>\n" + _V2 + "\n</style>\n"


def species_chip_css(colors: dict) -> str:
    """
    Per-species chip styling, generated because the colours live in the data.

    A selected chip is filled with the species' own colour — the same colour it
    carries on the map, the bars and the hourly lines — so the sidebar doubles
    as the legend for the whole page. Streamlit puts an `st-key-<key>` class on
    each keyed widget's container, which is what makes per-chip targeting
    possible without wrapping every button in a marker div.
    """
    out = []
    for code, hex_color in colors.items():
        k = f'section[data-testid="stSidebar"] .st-key-v2sp_{code} button'
        out.append(
            f'{k}[kind="primary"] {{ background: {hex_color} !important; '
            f'border-color: {hex_color} !important; color: #ffffff !important; }}'
        )
        # Unselected chips keep the colour as a dot, so a species is
        # identifiable before it is switched on.
        out.append(
            f'{k}[kind="secondary"] {{ border-left: 3px solid {hex_color} !important; }}'
        )
    return "<style>" + "\n".join(out) + "</style>"
