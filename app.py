"""
LUC Species Detection Explorer
==============================

Streamlit implementation of the "BirdNET Detection Explorer" design handoff,
wired to the real BirdNET acoustic dataset rather than the mockup's synthetic
rows.

Run:
    python build_cache.py     # once, to build ./data
    streamlit run app.py
"""

from __future__ import annotations

import importlib
import math
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import explorer_core as core
import theme

DATA_DIR = Path(__file__).resolve().parent / "data"

st.set_page_config(
    page_title="LUC Species Detection Explorer",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ------------------------------------------------------- local module reloading

@st.cache_resource
def _module_mtimes() -> dict:
    """Survives reruns and sessions, so we only reload when source changes."""
    return {}


def _reload_changed_modules() -> None:
    """
    Re-import local modules whose source changed since the last run.

    Streamlit reruns app.py on save but leaves imported local modules in
    sys.modules. Its own watcher does not reliably re-import them after
    structural edits (adding a dataclass field, adding a module-level function),
    which surfaces as AttributeError against a stale module object and normally
    requires killing the server. Reloading explicitly makes edits to
    explorer_core.py and theme.py take effect on save, like edits to app.py.

    theme imports constants from explorer_core, so it is reloaded second.
    """
    seen = _module_mtimes()
    reloaded = False
    for mod in (core, theme):
        try:
            mtime = Path(mod.__file__).stat().st_mtime
        except (OSError, TypeError):
            continue
        if seen.get(mod.__name__) != mtime:
            # Deliberately reloads on the first run too: the module already in
            # sys.modules may predate the current source, which is the exact
            # situation this is here to recover from.
            importlib.reload(mod)
            reloaded = True
            seen[mod.__name__] = mtime
    if reloaded:
        # Cached values were built by the previous version of the module.
        st.cache_data.clear()


_reload_changed_modules()

st.markdown(theme.CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ data load

@st.cache_data(show_spinner="Loading detection cache…")
def _load():
    return core.load_dataset(DATA_DIR)


if not (DATA_DIR / "meta.json").exists():
    st.error(
        "Detection cache not found. Run `python build_cache.py` once to build "
        "`./data` from the source CSVs, then reload."
    )
    st.stop()

DATA = _load()


# --------------------------------------------------------------- app state

def _init_state() -> None:
    if "initialised" in st.session_state:
        return
    d = core.default_filters(DATA)
    st.session_state.update(
        initialised=True,
        confidence=d.confidence,
        year_from=d.year_from,
        year_to=d.year_to,
        seasons=list(d.seasons),
        species=list(d.species),
        preserves=list(d.preserves),
        plots=list(d.plots),
        treatment_periods=list(d.treatment_periods),
        treatment_components=list(d.treatment_components),
        graph_type=d.graph_type,
        compare_by=d.compare_by,
        occ_granularity=d.occ_granularity,
        metric=d.metric,
        normalize=d.normalize,
        region_bucket=d.region_bucket,
        region_hours=list(d.region_hours),
        region_solar=list(d.region_solar),
    )


def _reset() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    _init_state()



# Widget keys whose widget is not drawn on every run. Streamlit discards a
# widget's session-state entry on any run where that widget is absent, so
# 'Daily %/Hourly %' — which only renders on the Occupancy view — vanished as
# soon as another graph type was selected, and the next run raised
# AttributeError reading it back.
_CONDITIONAL_KEYS = ("occ_granularity",)


# Every segmented control, with the values it is allowed to hold. Streamlit's
# st.segmented_control is deselectable: clicking the active segment clears it
# and the key becomes None. Nothing downstream expects that — METRIC_LABELS[None]
# raises KeyError, allowed_periods(None) silently filters everything away — so
# the value is snapped back before any of it runs.
def _segmented_options() -> dict:
    return {
        "metric": list(core.METRIC_LABELS),
        "normalize": ["total", "per_day"],
        "graph_type": ["occupancy", "region", "trends", "species"],
        "compare_by": ["none", "treatment_group", "treatment_type",
                       "preserve", "guild"],
        "confidence": list(DATA.meta["thresholds"]),
        "occ_granularity": list(core.OCC_MODES),
    }


def _coerce_segmented_state() -> None:
    """
    Restore any segmented control the user has deselected.

    Snaps back to the previous choice rather than the app default, so an
    accidental click on the active segment is a no-op rather than a reset.
    """
    last = st.session_state.setdefault("_last_segment", {})
    d = core.default_filters(DATA)
    for key, valid in _segmented_options().items():
        current = st.session_state.get(key)
        if current in valid:
            last[key] = current
        else:
            st.session_state[key] = last.get(key, getattr(d, key))


def _persist_conditional_state() -> None:
    """Restore any dropped conditional widget key and keep it from dropping again."""
    d = core.default_filters(DATA)
    for k in _CONDITIONAL_KEYS:
        if k not in st.session_state:
            v = getattr(d, k)
            st.session_state[k] = list(v) if isinstance(v, tuple) else v
        else:
            # Re-assigning marks the value as explicitly set rather than pure
            # widget state, which is what survives a run without the widget.
            st.session_state[k] = st.session_state[k]


def current_filters() -> core.Filters:
    s = st.session_state
    return core.Filters(
        confidence=s.confidence,
        year_from=s.year_from,
        year_to=s.year_to,
        seasons=tuple(s.seasons),
        species=tuple(s.species),
        preserves=tuple(s.preserves),
        plots=tuple(s.plots),
        treatment_periods=tuple(s.treatment_periods),
        treatment_components=tuple(s.treatment_components),
        graph_type=s.graph_type,
        compare_by=s.compare_by,
        occ_granularity=s.occ_granularity,
        metric=s.metric,
        normalize=s.normalize,
        region_bucket=s.region_bucket,
        region_hours=tuple(s.region_hours),
        region_solar=tuple(s.region_solar),
    )


_init_state()
_persist_conditional_state()
# Runs before any widget is drawn or any filter read, so a deselected control
# is repaired in the same rerun the deselection happens in.
_coerce_segmented_state()


# ------------------------------------------------------------------ callbacks

def _apply_toggle(current: list[str], value: str, checked: bool,
                  order: list[str]) -> list[str]:
    # Use a statement, not a ternary-for-side-effect: Streamlit's "magic"
    # auto-renders bare expression statements, so `a() if c else b()` would
    # display the expression's value (None) on every toggle.
    cur = set(current)
    if checked:
        cur.add(value)
    else:
        cur.discard(value)
    return [v for v in order if v in cur]


def _toggle_species(code: str) -> None:
    st.session_state.species = _apply_toggle(
        st.session_state.species, code, st.session_state[f"sp_{code}"],
        DATA.species_codes,
    )


def _toggle_preserve(pv: str) -> None:
    """Preserve <-> Plot cascade, kept bidirectionally consistent."""
    nxt = _apply_toggle(
        st.session_state.preserves, pv, st.session_state[f"pres_{pv}"],
        DATA.preserves,
    )
    cascaded = core.cascade_preserves(DATA, current_filters(), nxt)
    st.session_state.preserves = list(cascaded.preserves)
    _sync_checkbox_keys("plot", DATA.all_plots, list(cascaded.plots))
    st.session_state.plots = list(cascaded.plots)


def _toggle_plot(plot: str) -> None:
    st.session_state.plots = _apply_toggle(
        st.session_state.plots, plot, st.session_state[f"plot_{plot}"],
        DATA.all_plots,
    )


def _sync_checkbox_keys(prefix: str, all_values: list[str],
                        selected: list[str]) -> None:
    """
    Push a programmatic selection back onto the individual checkbox widgets.

    Streamlit gives a keyed widget's stored state precedence over its `value=`
    argument, so All/None (and the preserve cascade) must write the checkbox
    keys directly or the boxes drift out of sync with the selection.
    """
    chosen = set(selected)
    for v in all_values:
        key = f"{prefix}_{v}"
        if key in st.session_state:
            st.session_state[key] = v in chosen


def _set_species(selected: list[str]) -> None:
    _sync_checkbox_keys("sp", DATA.species_codes, selected)
    st.session_state.species = selected


def _set_preserves(selected: list[str], plots: list[str]) -> None:
    _sync_checkbox_keys("pres", DATA.preserves, selected)
    _sync_checkbox_keys("plot", DATA.all_plots, plots)
    st.session_state.preserves = selected
    st.session_state.plots = plots


def _set_plots(selected: list[str]) -> None:
    _sync_checkbox_keys("plot", DATA.all_plots, selected)
    st.session_state.plots = selected


def _toggle_season(season: str) -> None:
    st.session_state.seasons = _apply_toggle(
        st.session_state.seasons, season, st.session_state[f"seas_{season}"],
        DATA.seasons,
    )


def _set_seasons(selected: list[str]) -> None:
    _sync_checkbox_keys("seas", DATA.seasons, selected)
    st.session_state.seasons = selected


ALL_SEASONS_LABEL = "All seasons"


def _hour_label(h: int) -> str:
    suffix = "AM" if h < 12 else "PM"
    hour12 = h % 12 or 12
    return f"{hour12} {suffix}"


def _solar_label(b: int) -> str:
    """
    Name a bin of hours-relative-to-sunrise. Bin 0 begins at sunrise, -1 is the
    hour before it.
    """
    if b == 0:
        return "Sunrise → +1h"
    if b == -1:
        return "−1h → sunrise"
    if b < 0:
        return f"{b}h → {b + 1}h"
    return f"+{b}h → +{b + 1}h"


def _toggle_period(period: str) -> None:
    st.session_state.treatment_periods = _apply_toggle(
        st.session_state.treatment_periods, period,
        st.session_state[f"per_{period}"], core.TREATMENT_GROUP_CHOICES,
    )


def _set_periods(selected: list[str]) -> None:
    _sync_checkbox_keys("per", core.TREATMENT_GROUP_CHOICES, selected)
    st.session_state.treatment_periods = selected


def _toggle_ttype(comp: str) -> None:
    st.session_state.treatment_components = _apply_toggle(
        st.session_state.treatment_components, comp,
        st.session_state[f"tt_{comp}"], DATA.treatment_components,
    )


def _set_ttypes(selected: list[str]) -> None:
    _sync_checkbox_keys("tt", DATA.treatment_components, selected)
    st.session_state.treatment_components = selected


def _set_year_from() -> None:
    st.session_state.year_to = max(st.session_state.year_from, st.session_state.year_to)


def _set_year_to() -> None:
    st.session_state.year_from = min(st.session_state.year_from, st.session_state.year_to)


# ------------------------------------------------------------------- widgets

def checklist_popover(
    label: str,
    options: list[tuple[str, str]],
    selected: list[str],
    key_prefix: str,
    on_toggle,
    select_all,
    select_none,
) -> None:
    """
    Button that opens a checkbox popover — the design's pattern for long lists.

    The trigger sizes to its own text rather than filling its column, so a
    short label stays a short button. The two bulk actions are stacked rather
    than side by side, which keeps the popover as narrow as its longest
    checkbox instead of as wide as two buttons.
    """
    trigger = f"{label} ({len(selected)}/{len(options)})"
    with st.popover(trigger, use_container_width=False):
        st.button("Select All", key=f"{key_prefix}__all", on_click=select_all,
                  use_container_width=True)
        st.button("Deselect All", key=f"{key_prefix}__none", on_click=select_none,
                  use_container_width=True)
        st.markdown('<div class="luc-rule" style="margin:8px 0"></div>',
                    unsafe_allow_html=True)
        for value, text in options:
            key = f"{key_prefix}_{value}"
            if key not in st.session_state:
                st.session_state[key] = value in selected
            st.checkbox(text, key=key, on_change=on_toggle, args=(value,))


def _checklist_body(options: list[tuple[str, str]], selected: list[str],
                    key_prefix: str, on_toggle, select_all, select_none) -> None:
    """The bulk actions and checkboxes of a checklist, without the popover."""
    st.button("Select All", key=f"{key_prefix}__all", on_click=select_all,
              use_container_width=True)
    st.button("Deselect All", key=f"{key_prefix}__none", on_click=select_none,
              use_container_width=True)
    for value, text in options:
        key = f"{key_prefix}_{value}"
        if key not in st.session_state:
            st.session_state[key] = value in selected
        st.checkbox(text, key=key, on_change=on_toggle, args=(value,))


def dual_checklist_popover(trigger: str, sections: list[dict]) -> None:
    """
    One popover holding two independent checklists under their own headings.

    Treatment group and treatment activity describe the same thing — what was
    done to a plot and when — so they belong behind one control rather than two
    adjacent ones that look like alternatives to each other.
    """
    with st.popover(trigger, use_container_width=False):
        for i, sec in enumerate(sections):
            if i:
                st.markdown('<div class="luc-rule" style="margin:10px 0"></div>',
                            unsafe_allow_html=True)
            microlabel(sec["label"])
            _checklist_body(sec["options"], sec["selected"], sec["prefix"],
                            sec["on_toggle"], sec["select_all"],
                            sec["select_none"])


def choice_popover(label: str, key: str, options: list,
                   format_func=str) -> None:
    """
    Single-choice equivalent of checklist_popover.

    Uses a radio rather than a segmented control: a radio cannot be
    deselected, so it cannot leave the key as None the way the segmented
    controls did.
    """
    current = st.session_state.get(key, options[0])
    # Just the value: the microlabel above already says what it is, and
    # repeating it made the trigger wider than its column.
    with st.popover(format_func(current), use_container_width=False):
        st.radio(label, options, key=key, format_func=format_func,
                 label_visibility="collapsed")


def section_head(title: str) -> None:
    st.markdown(f'<div class="luc-section luc-section-lead '
                f'luc-section-top">{title}</div>', unsafe_allow_html=True)


def microlabel(text: str, slider: bool = False) -> None:
    extra = " luc-microlabel-slider" if slider else ""
    st.markdown(f'<div class="luc-microlabel{extra}">{text}</div>',
                unsafe_allow_html=True)


# -------------------------------------------------------------------- header

f = current_filters()
rows = core.apply_filters(DATA, f)
kpis = core.compute_kpis(DATA, f, rows)

# Two header buttons have been withdrawn rather than shipped half-working:
#
#   'Copy view link'  copied nothing and produced no link — it printed the
#                     filter state as JSON that nothing could read back. A
#                     shareable view belongs in the URL via st.query_params.
#   'Download CSV'    the export's shape is still unsettled, so it is out until
#                     the schema is agreed. core.export_csv and its tests are
#                     intact; only the button is gone.
head_l, head_r = st.columns([7, 1.1], vertical_alignment="center")
with head_l:
    st.markdown(
        f'<div class="luc-title">LUC Species Detection Explorer</div>'
        f'<div class="luc-subtitle">{core.subtitle_text(DATA, f)}</div>',
        unsafe_allow_html=True,
    )
with head_r:
    # One Reset for the whole page, on a row that already exists. Two scoped
    # resets sat on the section headings and could not be placed next to the
    # words reliably — Streamlit columns are proportional, so the gap grew with
    # the window.
    st.button("Reset", on_click=_reset, use_container_width=True,
              help="Restores every filter and chart setting to its default.")

st.markdown('<div class="luc-rule"></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ KPI cards

def kpi_card(label: str, value: str, sub: str) -> str:
    return (
        f'<div class="luc-kpi"><div class="luc-kpi-label">{label}</div>'
        f'<div class="luc-kpi-value">{value}</div>'
        f'<div class="luc-kpi-sub">{sub}</div></div>'
    )


# Reads left to right as: what was detected, then the effort behind it, then
# how much of the network that covers.
st.markdown(
    '<div class="luc-kpis luc-kpis-6">'
    + kpi_card(core.METRIC_LABELS[f.metric], f"{kpis.total_detections:,}",
               f"{core.metric_unit_short(DATA, f.metric)} · conf ≥ {f.confidence}")
    # Effort is a property of where and when the recorders ran, so these two
    # follow the plot, date and treatment filters but not species or
    # confidence. Saying "at selected plots & dates" stops that reading as a
    # bug when the numbers hold still while a species is picked.
    + kpi_card("Recordings", f"{kpis.n_recordings:,}",
               "at selected plots &amp; dates")
    + kpi_card("Hours recorded", f"{kpis.hours_recorded:,.0f}",
               "true audio, same scope")
    + kpi_card("Species richness", f"{kpis.richness}",
               f"of {kpis.n_species_tracked} tracked")
    + kpi_card("Preserves", f"{kpis.n_preserves}",
               f"of {len(DATA.preserves)} detected")
    + kpi_card("Plots", f"{kpis.active_plots}",
               f"of {len(DATA.all_plots)} detected")
    + "</div>",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------- filter toolbar

# Vertical rules between every control were reported as confusing: they implied
# grouping that was not there, since each filter is independent. The controls
# now sit in one even row and are separated by whitespace alone.
#
# This block chooses *which data* to include. 'Select Parameters', below the
# chart controls, chooses *how it is measured*.
section_head("Filter Data")

# Ordered outward from the coarsest cut to the finest: when, then where, then
# what, then what was done to it. Season sits with Year range because both
# narrow time; Treatment group and activity share one control because both
# describe the treatment, and separating them made them look like alternatives.
# Three cards side by side, grouped by what each filter narrows: when, where,
# and what. Boxing them stops six controls reading as one undifferentiated
# strip, and each card is wide enough that no label gets clipped.
def card_head(title: str) -> None:
    st.markdown(f'<div class="luc-filtercard"></div>'
                f'<div class="luc-cardhead">{title}</div>',
                unsafe_allow_html=True)


def card_gap() -> None:
    st.markdown('<div class="luc-cardgap"></div>', unsafe_allow_html=True)


c_when, c_where, c_what = st.columns(3, vertical_alignment="top")

with c_when:
    with st.container(border=True):
        card_head("Time")
        microlabel("Year range")
        # A trailing spacer, so the two four-character selects sit together at
        # the left rather than being spread across the card.
        y_from, y_to, _y_pad = st.columns([1, 1, 0.6])
        with y_from:
            st.selectbox("from", DATA.years, key="year_from",
                         on_change=_set_year_from, label_visibility="collapsed")
        with y_to:
            st.selectbox("to", DATA.years, key="year_to",
                         on_change=_set_year_to, label_visibility="collapsed")
        card_gap()
        microlabel("Season")
        checklist_popover(
            "Season",
            [(s, s) for s in DATA.seasons],
            st.session_state.seasons,
            "seas",
            _toggle_season,
            lambda: _set_seasons(list(DATA.seasons)),
            lambda: _set_seasons([]),
        )

with c_where:
    with st.container(border=True):
        card_head("Location")
        microlabel("Preserve")
        checklist_popover(
            "Preserve",
            [(p, p) for p in DATA.preserves],
            st.session_state.preserves,
            "pres",
            _toggle_preserve,
            lambda: _set_preserves(list(DATA.preserves), list(DATA.all_plots)),
            lambda: _set_preserves([], []),
        )
        card_gap()
        microlabel("Plot")
        avail = DATA.plots[DATA.plots["preserve"].isin(st.session_state.preserves)]
        checklist_popover(
            "Plot",
            [(r.plot, f"{r.plot} · {r.preserve} · {r.treatment_group}")
             for r in avail.itertuples()],
            st.session_state.plots,
            "plot",
            _toggle_plot,
            lambda: _set_plots(list(avail["plot"])),
            lambda: _set_plots([]),
        )

with c_what:
    with st.container(border=True):
        card_head("Species & Treatments")
        microlabel("Species")
        checklist_popover(
            "Species",
            # Scientific name italicised, per convention. st.checkbox renders
            # Markdown in its label, so the asterisks become italics.
            [(s["code"],
              f"{s['code']}: {s['name']}"
              + (f", *{s['scientific']}*" if s.get("scientific") else ""))
             for s in DATA.species],
            st.session_state.species,
            "sp",
            _toggle_species,
            lambda: _set_species(list(DATA.species_codes)),
            lambda: _set_species([]),
        )
        card_gap()
        # One control, two sections. These drop rows from the data; the
        # similarly-named Compare By options keep every row and split it into
        # panels instead, which is why those read 'By treatment group'.
        microlabel("Treatments")
        _n_grp = len(st.session_state.treatment_periods)
        _n_act = len(st.session_state.treatment_components)
        dual_checklist_popover(
            f"Treatments ({_n_grp}/{len(core.TREATMENT_GROUP_CHOICES)} · "
            f"{_n_act}/{len(DATA.treatment_components)})",
            [
                {
                    "label": "Treatment group",
                    "options": [(g, g) for g in core.TREATMENT_GROUP_CHOICES],
                    "selected": st.session_state.treatment_periods,
                    "prefix": "per",
                    "on_toggle": _toggle_period,
                    "select_all": lambda: _set_periods(
                        list(core.TREATMENT_GROUP_CHOICES)),
                    "select_none": lambda: _set_periods([]),
                },
                {
                    "label": "Treatment activity",
                    "options": [(c, c) for c in DATA.treatment_components],
                    "selected": st.session_state.treatment_components,
                    "prefix": "tt",
                    "on_toggle": _toggle_ttype,
                    "select_all": lambda: _set_ttypes(
                        list(DATA.treatment_components)),
                    "select_none": lambda: _set_ttypes([]),
                },
            ],
        )

# ------------------------------------------------------- graph type / compare

# No rule between the two sections: the cards already draw their own edges, so
# a divider on top of them was a third boundary doing no work, and its margins
# cost more height than the line itself.
#
# One card holding the whole chart definition, in the order you work through
# it: which chart, how to split it, how to measure it. Two side-by-side cards
# left the shorter one hanging, and the three controls are one decision anyway.
section_head("Chart")

# The 'By' prefix is what separates these from the Treatments filter above:
# these keep every row and split it into panels, that one drops rows. Same
# nouns, opposite operations, so the verb has to carry the difference.
COMPARE_LABELS = {
    "none": "None", "treatment_group": "By treatment group",
    "treatment_type": "By treatment activity", "preserve": "By preserve",
    "guild": "By forage guild",
}

# Narrower than the page: the card holds a four-option selector and two
# dropdowns, and stretching it to full width left most of it empty.
_chart_col, _chart_pad = st.columns([1.9, 2.1])
with _chart_col, st.container(border=True):
    card_head("Graphs")
    # Occupancy leads: it is the effort-corrected view and the primary result.
    # Occupancy and Map are the two spatial views and sit together; Trends and
    # Species are the two aggregate ones. 'diversity' (species richness over
    # time) was here too — with only eight target species it sat pinned at 7-8
    # in every season, drawing a flat line the Species Richness card already
    # gives as one number.
    st.segmented_control(
        "Graph type",
        ["occupancy", "region", "trends", "species"],
        key="graph_type",
        label_visibility="collapsed",
        # The value stays 'region' so saved view links and exports keep
        # working; only the label reads 'Map'.
        format_func=lambda v: "Map" if v == "region" else v.capitalize(),
    )

    card_gap()
    g_compare, g_params = st.columns([1, 1.35], vertical_alignment="bottom")
    with g_compare:
        microlabel("Compare by")
        choice_popover("Compare by", "compare_by", list(COMPARE_LABELS),
                       format_func=lambda v: COMPARE_LABELS[v])
    with g_params:
        microlabel("Parameters")
        _summary = (f"{core.METRIC_LABELS[f.metric]} · "
                    f"{'Per day' if f.normalize == 'per_day' else 'Total'} · "
                    f"conf ≥ {f.confidence}")
        with st.popover(_summary, use_container_width=False):
            # Grouped by what each answers, so the popover reads as three
            # questions rather than one undifferentiated list of radios.
            microlabel("Detection unit — what counts as one detection")
            st.radio(
                "Detection unit", ["presence", "raw"], key="metric",
                label_visibility="collapsed",
                format_func=lambda v: core.METRIC_LABELS[v],
                help="Species Presence counts each recording a species appears "
                     "in (0/1). Raw Detections counts every 3-second BirdNET "
                     "detection window, about 12x higher, and weighted toward "
                     "persistent singers.",
            )
            st.markdown('<div class="luc-rule" style="margin:10px 0"></div>',
                        unsafe_allow_html=True)
            microlabel("Scale — whether to divide by effort")
            st.radio(
                "Scale", ["total", "per_day"], key="normalize",
                label_visibility="collapsed",
                format_func=lambda v: "Total" if v == "total" else "Per day",
                help="Seasons were surveyed for very different numbers of days. "
                     "'Per day' divides by sampling days so they are "
                     "comparable. Affects Trends and Species only; Occupancy is "
                     "always effort-corrected.",
            )
            st.markdown('<div class="luc-rule" style="margin:10px 0"></div>',
                        unsafe_allow_html=True)
            microlabel("Confidence — BirdNET score floor")
            st.radio(
                "Confidence", DATA.meta["thresholds"], key="confidence",
                label_visibility="collapsed",
                format_func=lambda v: f"{v:.1f}",
                help="Keeps only detections scoring at or above this value. "
                     "Raising it trades recall for precision.",
            )

# Filters may have changed above; recompute before drawing.
#
# When the export returns, it belongs here rather than at the top of the file:
# built before the controls are read, it serves the previous interaction's
# state and the file lags one click behind the screen.
f = current_filters()
rows = core.apply_filters(DATA, f)


# ------------------------------------------------------------------- charts

def line_chart(series: list[dict], buckets: list[str], decimals: int = 0) -> go.Figure:
    fig = go.Figure()
    fmt = f",.{decimals}f"
    for s in series:
        fig.add_trace(
            go.Scatter(
                x=buckets,
                y=s["values"],
                mode="lines+markers",
                name=s["label"],
                line=dict(color=s["color"], width=2.5, shape="linear"),
                marker=dict(size=7, color=s["color"],
                            line=dict(color="#ffffff", width=1.5)),
                fill="tozeroy",
                fillcolor=core.rgba(s["color"], 0.08),
                hovertemplate=(
                    f"<b>{s['label']}</b><br>%{{x}}: %{{y:{fmt}}}<extra></extra>"
                ),
            )
        )
    fig.update_layout(**theme.plotly_layout())
    fig.update_yaxes(title=None, rangemode="tozero")
    return fig


def bar_chart(bars: pd.DataFrame, decimals: int = 0, unit: str = "detections") -> go.Figure:
    fmt = f",.{decimals}f"
    # Each species keeps the colour it has on the Region map. Both key off the
    # whole-dataset detection rank, not the current sort, so a species does not
    # change colour when a filter moves.
    rank_colors = core.species_colors_by_rank(DATA)
    fig = go.Figure(
        go.Bar(
            x=bars["species_code"],
            y=bars["detections"],
            marker_color=[rank_colors.get(c, core.ACCENT)
                          for c in bars["species_code"]],
            text=[f"{v:{fmt}}" for v in bars["detections"]],
            textposition="outside",
            textfont=dict(size=11, color=core.INK, family="Archivo"),
            customdata=bars["name"],
            hovertemplate=(
                f"<b>%{{x}}</b>  %{{customdata}}<br>%{{y:{fmt}}} {unit}<extra></extra>"
            ),
        )
    )
    fig.update_layout(**theme.plotly_layout())
    fig.update_yaxes(title=None, rangemode="tozero")
    fig.update_traces(width=0.56)
    return fig


def _readable_on(hex_bg: str) -> str:
    """Black or white text, whichever contrasts better with the cell colour."""
    h = hex_bg.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    # Perceived luminance (ITU-R BT.601).
    return core.INK if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


def occupancy_html(panel: dict, effort_label: str,
                   rate_mode: bool = False) -> str:
    """
    CSS-grid heatmap for one panel.

    Species cells use the panel's ramp; the effort row is neutral ink so it never
    competes with the occupancy colours. Unsurveyed buckets render as NA.
    """
    grid, sampling = panel["grid"], panel["sampling"]
    columns = panel["columns"]
    ramp = panel["ramp"]
    # Percentages share a fixed 0-100 scale; rates are unbounded, so the ramp
    # tops out at the largest value in this panel.
    vmax = max(float(grid.max(numeric_only=True).max() or 0), 1e-9) \
        if rate_mode else 100.0
    cols = f"104px repeat({len(columns)},minmax(0,1fr))"
    out = []

    # Name the plots, do not just count them. "7 plots" left no way to tell one
    # grid's sites from another's, which matters most in the compare-by views
    # where each panel covers a different subset.
    names = list(panel.get("plot_names") or [])
    n_plots = panel.get("n_plots", len(names))
    # A single-plot grid is titled with that plot, so repeating it underneath
    # would say the same thing twice.
    roster = ", ".join(names) if n_plots > 1 else ""

    if panel["label"]:
        swatch = core.ramp_color(ramp, 0.85)
        out.append(
            f'<div class="luc-occ-grouphead">'
            f'<span class="luc-swatch" style="background:{swatch}"></span>'
            f'{panel["label"]}'
            f'<span class="luc-occ-groupmeta">{n_plots} '
            f'{"plot" if n_plots == 1 else "plots"}</span>'
            f'</div>'
        )
    if roster:
        out.append(f'<div class="luc-occ-roster" title="{roster}">{roster}</div>')

    # No divider between periods: the colour ramp already distinguishes them,
    # and a rule would imply the columns are not one continuous timeline.
    def edge(ci: int) -> str:
        return ""

    out.append(f'<div class="luc-occ" style="grid-template-columns:{cols}">')
    # The corner cell was empty while the column beneath it held four-letter
    # codes with nothing saying what they were.
    out.append('<div class="luc-occ-corner">Species<br>code</div>')
    parts = core.bucket_label_parts(DATA)
    for ci, col in enumerate(columns):
        season, years = parts.get(col["bucket"], (col["label"], ""))
        out.append(
            f'<div class="luc-occ-collabel" style="{edge(ci)}">'
            f'<span class="luc-occ-season">{season}</span>'
            f'<span class="luc-occ-year">{years}</span></div>'
        )

    # Distinct calendar dates recorded, unioned across the selected plots. This
    # is the occupancy denominator, so the row and the percentages divide out.
    smax = max(float(sampling.max()), 1.0)
    out.append(f'<div class="luc-occ-rowlabel luc-occ-efflabel">'
               f'{effort_label}</div>')
    for ci, col in enumerate(columns):
        v = float(sampling.get(ci, 0))
        # Zero effort is never a real "0" reading, so it never prints one. Which
        # blank it gets depends on why: outside this panel's era there is
        # nothing to report, inside it the season was simply not surveyed (NA).
        if v <= 0:
            if col.get("in_era", True):
                out.append(
                    f'<div class="luc-occ-cell luc-occ-na" style="{edge(ci)}" '
                    f'title="{col["label"]}: not surveyed">NA</div>'
                )
            else:
                out.append(
                    f'<div class="luc-occ-cell luc-occ-outside" style="{edge(ci)}" '
                    f'title="{col["label"]}: outside this treatment period"></div>'
                )
            continue
        t = v / smax
        fg = "#f3f2f2" if t > 0.5 else core.INK
        out.append(
            f'<div class="luc-occ-cell" style="background:rgba(32,30,29,'
            f'{0.06 + 0.72 * t:.3f});color:{fg};{edge(ci)}" '
            f'title="{col["label"]}: {v:,.0f} {effort_label.lower()}">'
            f'{v:,.0f}</div>'
        )

    for code in grid.index:
        name = DATA.species_names.get(code, "")
        out.append(f'<div class="luc-occ-rowlabel" title="{name}">{code}</div>')
        for ci, col in enumerate(columns):
            v = grid.loc[code, ci]
            where = col["label"] + (f" ({col['period']})" if col["period"] else "")
            if pd.isna(v):
                if col.get("in_era", True):
                    out.append(
                        f'<div class="luc-occ-cell luc-occ-na" style="{edge(ci)}" '
                        f'title="{code} · {where}: not surveyed">NA</div>'
                    )
                else:
                    out.append(
                        f'<div class="luc-occ-cell luc-occ-outside" '
                        f'style="{edge(ci)}" title="{code} · {where}: outside '
                        f'this treatment period"></div>'
                    )
                continue
            v = float(v)
            if rate_mode:
                # Counts are unbounded, so the ramp is scaled to the largest
                # value on screen rather than to 100.
                bg = core.ramp_color(col["ramp"], v / vmax)
                days = float(sampling.get(ci, 0))
                per = f" · {v / days:,.1f} per sampling day" if days else ""
                out.append(
                    f'<div class="luc-occ-cell" style="background:{bg};'
                    f'color:{_readable_on(bg)};{edge(ci)}" '
                    f'title="{code} · {where}: {v:,.0f} recordings over '
                    f'{days:,.0f} sampling days{per}">{v:,.0f}</div>'
                )
            else:
                bg = core.ramp_color(col["ramp"], v / 100)
                out.append(
                    f'<div class="luc-occ-cell" style="background:{bg};'
                    f'color:{_readable_on(bg)};{edge(ci)}" '
                    f'title="{code} · {where}: {v:.1f}%">{v:.0f}</div>'
                )

    out.append("</div>")

    # One legend per ramp that actually colours a cell. Never-surveyed columns
    # carry a placeholder ramp so the grid stays chronological, but every cell
    # under them is NA, so keying that ramp added a third, unlabelled scale bar
    # that nothing on screen used.
    used, seen = [], set()
    for ci, col in enumerate(columns):
        if col["ramp"] in seen or grid.iloc[:, ci].isna().all():
            continue
        seen.add(col["ramp"])
        used.append((col["ramp"], col["period"]))
    lo, hi = ("0", f"{vmax:,.0f}") if rate_mode else ("0%", "100%")
    out.append('<div class="luc-occ-legend">')
    for r, period in used:
        out.append(
            (f'<span class="luc-occ-ramplabel">{period}</span>' if period else "")
            + f'<span>{lo}</span>'
            f'<span class="luc-occ-gradient" style="background:{core.ramp_css(r)}"></span>'
            f'<span>{hi}</span>'
        )
    out.append(
        '<span class="luc-occ-nakey"><span class="luc-occ-naswatch"></span>'
        'NA = not surveyed</span>'
    )
    # Only named when the panel actually has out-of-era columns, so grids that
    # cover their whole timeline aren't given a key to something absent.
    if any(not c.get("in_era", True) for c in columns):
        out.append(
            '<span class="luc-occ-nakey"><span class="luc-occ-outswatch"></span>'
            'outside this treatment period</span>'
        )
    out.append("</div>")
    return "".join(out)


# Plotly renamed its MapLibre traces in 5.24 (Scattermapbox -> Scattermap) and
# deprecated the originals. Bind to whichever this install actually provides so
# the app works on both old and new Plotly.
_HAS_SCATTERMAP = hasattr(go, "Scattermap")
_MAP_TRACE = go.Scattermap if _HAS_SCATTERMAP else go.Scattermapbox
_MAP_LAYOUT_KEY = "map" if _HAS_SCATTERMAP else "mapbox"


# Area-proportional radius, so a 100% bubble does not read as four times a
# 50% one. Zero-occupancy points keep a small dot rather than vanishing.
def _bubble_radius(pct: float) -> float:
    return 4.0 + 22.0 * math.sqrt(max(0.0, pct) / 100.0)


def _species_points(nodes: pd.DataFrame, code: str) -> dict:
    """lat/lon/size/customdata for one species, as a frame-ready payload."""
    sub = nodes[nodes["species_code"] == code] if len(nodes) else nodes.iloc[0:0]
    return dict(
        lat=list(sub["latitude"]),
        lon=list(sub["longitude"]),
        marker=dict(size=[_bubble_radius(p) for p in sub["occupancy_pct"]]),
        customdata=sub[["plot", "preserve", "name", "occupancy_pct",
                        "effort_sampled"]].values.tolist(),
    )


def region_map(slices: list[tuple[str, pd.DataFrame]], sites: pd.DataFrame,
               codes: list[str], effort_label: str, slider_prefix: str,
               revision: str, active: int = 0) -> go.Figure:
    """
    Real basemap from the dataset's plot coordinates, one bubble per species.

    The scrubber lives inside the figure as Plotly frames rather than as a
    Streamlit widget. A Streamlit slider reruns the script and hands the browser
    a rebuilt chart, which discards the viewport no matter what uirevision says;
    stepping a frame is a pure client-side update, so panning and zoom simply
    persist. `slices` therefore carries every step's data at once, in order.

    One figure carries one scrubber. Two independent sliders cannot share a
    figure — both would write the same trace properties, so whichever moved last
    would silently discard the other's position — which is why season and time
    of day are separate maps rather than two sliders on one.

    Species are their own traces so the legend doubles as a colour key and can
    isolate one by click, and stay translucent because they are fanned tightly
    around a shared coordinate and will overlap when zoomed out.
    """
    fig = go.Figure()
    first = slices[active][1] if slices else pd.DataFrame()

    # The AudioMoth's actual position, drawn first so the fanned species bubbles
    # sit over it. Fully opaque and small: it is a reference point, not a value.
    # It is trace 0 and never appears in a frame, so it stays put throughout.
    fig.add_trace(
        _MAP_TRACE(
            lat=sites["latitude"],
            lon=sites["longitude"],
            mode="markers",
            name="AudioMoth",
            marker=dict(size=5, color=core.RECORDER_DOT, allowoverlap=True),
            customdata=sites[["plot", "preserve"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
                "AudioMoth position<extra></extra>"
            ),
        )
    )

    rank_colors = core.species_colors_by_rank(DATA)
    for code in codes:
        pts = _species_points(first, code)
        fig.add_trace(
            _MAP_TRACE(
                lat=pts["lat"],
                lon=pts["lon"],
                mode="markers",
                name=code,
                legendgroup=code,
                marker=dict(
                    size=pts["marker"]["size"],
                    color=core.rgba(rank_colors.get(code, core.ACCENT), 0.85),
                    allowoverlap=True,
                ),
                customdata=pts["customdata"],
                hovertemplate=(
                    "<b>%{customdata[2]}</b> (" + code + ")<br>"
                    "%{customdata[0]} · %{customdata[1]}<br>"
                    "%{customdata[3]:.1f}% occupancy over "
                    "%{customdata[4]:,.0f} " + effort_label.lower()
                    + "<extra></extra>"
                ),
            )
        )

    species_traces = list(range(1, len(codes) + 1))
    fig.frames = [
        go.Frame(
            name=label,
            traces=species_traces,
            data=[_MAP_TRACE(**_species_points(nd, c)) for c in codes],
        )
        for label, nd in slices
    ]

    steps = [
        dict(
            label=label,
            method="animate",
            args=[[label], dict(mode="immediate", frame=dict(duration=0,
                                                            redraw=True),
                                transition=dict(duration=0))],
        )
        for label, _ in slices
    ]

    lat, lon = sites["latitude"], sites["longitude"]
    fig.update_layout(
        height=560,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Archivo, sans-serif", size=12, color=core.INK),
        hoverlabel=dict(bgcolor=core.INK, bordercolor=core.INK,
                        font=dict(family="Archivo", size=12, color="#ffffff")),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
            font=dict(size=11), itemsizing="constant",
            bgcolor="rgba(255,255,255,0.75)", borderwidth=0,
        ),
        sliders=[dict(
            active=active,
            steps=steps,
            x=0, y=0, len=1.0,
            pad=dict(t=8, b=4),
            currentvalue=dict(prefix=slider_prefix, font=dict(size=12),
                              xanchor="left"),
            tickcolor=core.INK,
            font=dict(size=10),
        )],
        # Distinct per map so the two do not share a viewport, and constant
        # across reruns so a filter change elsewhere does not reframe them.
        uirevision=revision,
        **{
            _MAP_LAYOUT_KEY: dict(
                style="open-street-map",
                center=dict(lat=float(lat.mean()), lon=float(lon.mean())),
                zoom=8.2,
                uirevision=revision,
            )
        },
    )
    return fig


# -------------------------------------------------------------- chart panel

title, sub = core.panel_copy(DATA, f)

# A real bordered container, not a hand-rolled <div>: markdown blocks are
# separate DOM nodes, so an opening tag in one st.markdown cannot wrap the
# widgets rendered after it.
with st.container(border=True):
    head_a, head_b = st.columns([3, 1.4], vertical_alignment="center")
    with head_a:
        # Name the preserve/plot in the heading so an aggregate is never mistaken
        # for a single site.
        where = core.selection_label(DATA, f)
        st.markdown(
            f'<div class="luc-panel-title">{title}'
            f'<span class="luc-panel-where"> - {where}</span></div>'
            f'<div class="luc-panel-sub">{sub}</div>',
            unsafe_allow_html=True,
        )
    with head_b:
        if f.graph_type == "occupancy":
            st.segmented_control(
                "Granularity",
                core.OCC_MODES,
                key="occ_granularity",
                label_visibility="collapsed",
                format_func=lambda v: core.OCC_MODE_LABELS[v],
                help="Daily/Hourly % are occupancy — the share of sampling "
                     "days a species was detected on. Count is recordings "
                     "containing it per sampling day, which keeps separating "
                     "species after occupancy has saturated at 100%.",
            )
            f = current_filters()
            title, sub = core.panel_copy(DATA, f)

    st.markdown('<div class="luc-panel-rule"></div>', unsafe_allow_html=True)

    if not kpis.has_data or rows.empty:
        st.markdown(
            '<div class="luc-empty">No detections match the current filters. '
            'widen the selection or lower the confidence threshold.</div>',
            unsafe_allow_html=True,
        )
    elif f.graph_type == "trends":
        series, buckets = core.build_series(DATA, f, rows, "detections")
        st.markdown(
            '<div class="luc-legend">'
            + "".join(
                f'<span class="luc-legend-item">'
                f'<span class="luc-swatch" style="background:{s["color"]}"></span>'
                f'{s["label"]} <span class="luc-legend-total">{s["total"]}</span></span>'
                for s in series
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        dp = 2 if f.normalize == "per_day" else 0
        st.plotly_chart(line_chart(series, buckets, decimals=dp),
                        use_container_width=True, config={"displayModeBar": False})
    elif f.graph_type == "species":
        dp = 2 if f.normalize == "per_day" else 0
        st.plotly_chart(
            bar_chart(core.species_bars(DATA, f, rows), decimals=dp,
                      unit=core.metric_phrase(DATA, f)),
            use_container_width=True, config={"displayModeBar": False})
    elif f.graph_type == "occupancy":
        effort_label = core.OCC_EFFORT_LABELS[f.occ_granularity]

        # Treatment context sits above every Occupancy grid, whatever Compare by
        # is set to.
        # Swatches only when the period ramps are actually on screen (Compare by
        # = Treat. group). Otherwise the same treatment-type information is
        # carried over as plain text, without a key to unused colours.
        treatments = core.treatment_summary(DATA, f)
        as_key = core.period_colors_in_use(f)
        if as_key:
            items = "".join(
                f'<span class="luc-treatitem">'
                f'<span class="luc-swatch" style="background:{t["color"]}"></span>'
                f'<span class="luc-treatval">{t["period"]}</span>'
                f'<span class="luc-treatkey">treatment type</span>'
                f'<span class="luc-treattype">{t["types"]}</span></span>'
                for t in treatments
            )
        else:
            items = "".join(
                f'<span class="luc-treatitem">'
                f'<span class="luc-treatkey">{t["display"]}</span>'
                f'<span class="luc-treattype">{t["types"]}</span></span>'
                for t in treatments if t["display"]
            )
        st.markdown(f'<div class="luc-treatbar">{items}</div>',
                    unsafe_allow_html=True)

        panels = core.occupancy_panels(DATA, f, rows)
        if not panels:
            st.markdown(
                '<div class="luc-empty">No groups to compare under the current '
                'filters.</div>', unsafe_allow_html=True)
        else:
            for i, panel in enumerate(panels):
                if i:
                    st.markdown('<div class="luc-occ-spacer"></div>',
                                unsafe_allow_html=True)
                st.markdown(occupancy_html(panel, effort_label,
                                           core.is_rate_mode(f)),
                            unsafe_allow_html=True)
        st.markdown(
            f'<div class="luc-occ-note">{core.occupancy_note(DATA, f)}</div>',
            unsafe_allow_html=True,
        )
    else:
        sites = core.region_sites(DATA, f)
        # Commonest species first, so it is drawn underneath and the rarer ones
        # stay visible on top. Alphabetical order painted WIWA over everything
        # else and made the fifth-commonest species look like the dominant one.
        codes = [c for c in core.species_rank(DATA) if c in set(f.species)]

        if sites.empty:
            st.markdown('<div class="luc-empty">No plots selected.</div>',
                        unsafe_allow_html=True)
        else:
            # One map with an in-figure scrubber over seasons. It slides
            # entirely client-side, so stepping costs neither a rerun nor the
            # viewport; every step's data is computed up front.
            #
            # A second map stepped by hours-relative-to-sunrise sat below this.
            # The solar machinery is all still in place (Dataset.solar_bins,
            # Filters.region_solar, the solar_* cache tables), so reinstating it
            # is a dozen lines — but it needed its own explanation to be read
            # correctly, and one map answers the question people actually ask.
            #
            # Unsampled seasons keep their slot and carry no bubbles, matching
            # how the heatmaps keep NA columns instead of dropping them.
            season_slices = []
            for label in [ALL_SEASONS_LABEL] + core.visible_buckets(DATA, f):
                fb = core.replace(
                    f, region_bucket="" if label == ALL_SEASONS_LABEL else label,
                    region_hours=(), region_solar=())
                season_slices.append(
                    (label, core.region_species_nodes(
                        DATA, fb, core.apply_filters(DATA, fb))))

            daily_label = core.OCC_EFFORT_LABELS["daily"]

            st.markdown('<div class="luc-mapsub">Across Years and Seasons</div>',
                        unsafe_allow_html=True)
            st.plotly_chart(
                region_map(season_slices, sites, codes, daily_label,
                           "Season: ", "region-season"),
                use_container_width=True, key="region_map_season",
                config={"displayModeBar": False})
            empty_seasons = [lb for lb, nd in season_slices
                             if lb != ALL_SEASONS_LABEL and nd.empty]
            st.caption(
                f"{len(sites)} plots across {sites['preserve'].nunique()} "
                f"preserves. Bubble size is occupancy per season, pooled over "
                f"all recorded hours, as a share of {daily_label.lower()}. "
                f"Black dots mark the AudioMoths' true positions, and species "
                f"are fanned around them so they don't stack; the commonest "
                f"species is drawn underneath. Drag the slider to step through "
                f"time — it keeps your zoom — or click a species in the legend "
                f"to isolate it."
                + (f" No recordings at these plots in "
                   f"{', '.join(empty_seasons)}, which show an empty map."
                   if empty_seasons else "")
            )


# The footnote needs bottom clearance of its own: the expander that follows is
# a Streamlit block with its own margins, and with only a top margin here the
# two rendered on top of each other.
st.markdown(
    f'<div class="luc-footnote">'
    f'{DATA.meta["n_detection_rows"]:,} raw detections across '
    f'{DATA.meta["n_recordings"]:,} recordings · confidence thresholds computed '
    f'per-row from the source table · detection metric is summed 0/1 presence '
    f'per recording × species.</div>',
    unsafe_allow_html=True,
)

# ------------------------------------------------------------- methodology
# Collapsed by default: it is reference material, not something to scroll past
# on every visit. The content comes from core.methodology(), which derives its
# figures from the loaded dataset so this cannot drift from what is charted.
with st.expander("Methodology — what each control and measure means"):
    for heading, entries in core.methodology(DATA):
        st.markdown(f'<div class="luc-methhead">{heading}</div>',
                    unsafe_allow_html=True)
        rows_html = "".join(
            f'<div class="luc-methrow">'
            f'<div class="luc-methterm">{term}</div>'
            f'<div class="luc-methdef">{definition}</div></div>'
            for term, definition in entries
        )
        st.markdown(f'<div class="luc-meth">{rows_html}</div>',
                    unsafe_allow_html=True)
    st.markdown(
        '<div class="luc-methnote">Full derivations, source-table joins and '
        'the verification suite are documented in DATA_METHODS.md.</div>',
        unsafe_allow_html=True,
    )
