"""
LUC Species Detection Explorer.

The Claude Design "Species Explorer Dashboard" layout: every filter in a left
sidebar, every chart stacked down one scrolling page. This is the deployed
app. The previous single-chart layout is kept as app_v1.py and still runs; the
two share explorer_core.py, so the numbers on both are the same numbers,
computed by the same tested code.

    streamlit run app.py          # this one
    streamlit run app_v1.py       # the previous layout

Deliberate differences from v1, all of them the mockup's design:
  · No graph picker. Every chart is on the page at once, which means each
    filter change redraws five figures rather than one.
  · No 'Compare by'. The per-plot pretreat/posttreat panels are unreachable
    here; core.occupancy_panels still supports them, so restoring the control
    is a few lines if the loss bites.
  · Preserve and Plot are single-select — one preserve or all — rather than
    v1's checklists.
  · Confidence is a slider. It snaps to the four thresholds the cache holds
    (0.3/0.5/0.7/0.9); the mockup's continuous 0.3-1.0 track is not backed by
    data. The mockup's time-of-day slider is absent for the same reason: hours
    reach only two of the charts, so a global hour filter would be a change to
    explorer_core rather than to this file.

Two controls the mockup omits are kept, because without them the charts they
sit on have no defined behaviour: the heatmap's Daily/Hourly/Count toggle
(which the mockup itself keeps) and the hourly chart's Year/Season/Preserve
facet. Both are drawn as small toggles on their panel heading, in the
mockup's own idiom.
"""

from __future__ import annotations

import importlib
import math
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components

import explorer_core as core
import theme
import theme_v2

DATA_DIR = Path(__file__).resolve().parent / "data"

st.set_page_config(
    page_title="LUC Species Detection Explorer",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------------- local module reloading

@st.cache_resource
def _module_mtimes() -> dict:
    return {}


def _reload_changed_modules() -> None:
    """Re-import local modules whose source changed. See app.py for why."""
    seen = _module_mtimes()
    reloaded = False
    for mod in (core, theme, theme_v2):
        try:
            mtime = Path(mod.__file__).stat().st_mtime
        except (OSError, TypeError):
            continue
        if seen.get(mod.__name__) != mtime:
            importlib.reload(mod)
            reloaded = True
            seen[mod.__name__] = mtime
    if reloaded:
        st.cache_data.clear()


_reload_changed_modules()

st.markdown(theme_v2.CSS, unsafe_allow_html=True)


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

st.markdown(theme_v2.species_chip_css(core.species_colors_by_rank(DATA)),
            unsafe_allow_html=True)

ALL_SEASONS_LABEL = "All seasons"

# Calendar order, not the order the cache happens to list. Autumn has no
# recordings yet but keeps its place, so the gap in coverage is visible.
SEASON_ORDER = ["Spring", "Summer", "Autumn", "Winter"]

# The heatmap's four modes. The first three are counting units and come from
# core; 'treatment' is a grouping of the daily grid and belongs to this page
# only, so v1's own toggle is left alone.
V2_OCC_MODES = {
    **{m: core.OCC_MODE_LABELS[m] for m in core.OCC_MODES},
    "treatment": "By Treatment",
}


# --------------------------------------------------------------- app state

def _init_state() -> None:
    if "v2_initialised" in st.session_state:
        return
    d = core.default_filters(DATA)
    st.session_state.update(
        v2_initialised=True,
        confidence=d.confidence,
        seasons=list(d.seasons),
        species=list(d.species),
        preserves=list(d.preserves),
        plots=list(d.plots),
        treatment_periods=list(d.treatment_periods),
        treatment_components=list(d.treatment_components),
        occ_granularity=d.occ_granularity,
        hour_facet=d.hour_facet,
        metric=d.metric,
        # Sections start open. collapsible_head keeps them from here, and
        # Reset puts them back, which is the behaviour you want: a reset page
        # should show everything.
        v2_open_occ=True,
        v2_open_hour=True,
        v2_open_map=True,
        # The four checklists write straight to the filter lists above; their
        # individual checkbox keys are created on first render.
    )


def _reset() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    _init_state()


# Segmented controls are deselectable — clicking the live segment clears the
# key to None, and METRIC_LABELS[None] raises. Snap back before anything reads
# the value. (Same guard as v1; both panel toggles render on every run here,
# so the conditional-widget garbage collection v1 fights does not arise.)
def _coerce_segmented_state() -> None:
    last = st.session_state.setdefault("_last_segment", {})
    d = core.default_filters(DATA)
    for key, valid in {"occ_granularity": list(V2_OCC_MODES),
                       "hour_facet": list(core.HOUR_FACETS)}.items():
        current = st.session_state.get(key)
        if current in valid:
            last[key] = current
        else:
            st.session_state[key] = last.get(key, getattr(d, key))


def current_filters() -> core.Filters:
    s = st.session_state
    d = core.default_filters(DATA)
    y_from, y_to = s.get("year_range", (d.year_from, d.year_to))
    return core.Filters(
        confidence=s.confidence,
        year_from=y_from,
        year_to=y_to,
        seasons=tuple(s.seasons),
        species=tuple(s.species),
        preserves=tuple(s.preserves),
        plots=tuple(s.plots),
        treatment_periods=tuple(s.treatment_periods),
        treatment_components=tuple(s.treatment_components),
        graph_type="occupancy",
        # Fixed in v2: the mockup has no Compare by and no Parameters popover.
        # Panels that need a different graph_type ask for it with core.replace.
        compare_by="none",
        occ_granularity=s.occ_granularity,
        metric=s.metric,
        normalize="total",
        region_bucket="",
        region_hours=(),
        region_solar=(),
        hour_facet=s.hour_facet,
    )


_init_state()
_coerce_segmented_state()


# ------------------------------------------------------------------ callbacks

def _order(values, ordering) -> list:
    keep = set(values)
    return [v for v in ordering if v in keep]


def _toggle_chip(field: str, value: str, ordering: list) -> None:
    cur = set(st.session_state[field])
    cur.discard(value) if value in cur else cur.add(value)
    st.session_state[field] = _order(cur, ordering)


def _bulk(field: str, ordering: list) -> None:
    """
    All or nothing, deciding the same way the button's label does.

    It used to branch on whether the list was empty, while the label branched
    on whether it was full. With two of three seasons selected the button read
    'Select All' and cleared them, and after a Clear the pair could disagree
    about what the next click meant.
    """
    st.session_state[field] = ([] if len(st.session_state[field]) >= len(ordering)
                               else list(ordering))


def _plots_for(preserves: list[str]) -> list[str]:
    sel = set(preserves)
    return [r.plot for r in DATA.plots.itertuples() if r.preserve in sel]


# Which setter a checklist's bulk action goes through. Preserve is not simply
# a list assignment — it has to cascade to the plots — so they are named here
# rather than inferred from the field.
_SET_ALL = {}


def _apply_toggle(current: list[str], value: str, checked: bool,
                  order: list[str]) -> list[str]:
    # A statement rather than a ternary: Streamlit auto-renders bare
    # expression statements, so `a() if c else b()` would print its None.
    cur = set(current)
    if checked:
        cur.add(value)
    else:
        cur.discard(value)
    return [v for v in order if v in cur]


def _sync_checkbox_keys(prefix: str, all_values: list[str],
                        selected: list[str]) -> None:
    """
    Push a programmatic selection back onto the individual checkboxes.

    A keyed widget's stored state takes precedence over its `value=` argument,
    so Select All, Deselect All and the preserve cascade have to write the
    checkbox keys directly or the boxes drift out of step with the selection.
    """
    chosen = set(selected)
    for v in all_values:
        key = f"{prefix}_{v}"
        if key in st.session_state:
            st.session_state[key] = v in chosen


def _toggle_preserve(pv: str) -> None:
    """Preserve <-> Plot cascade, kept consistent in both directions."""
    nxt = _apply_toggle(st.session_state.preserves, pv,
                        st.session_state[f"pres_{pv}"], list(DATA.preserves))
    plots = _plots_for(nxt)
    st.session_state.preserves = nxt
    _sync_checkbox_keys("plot", list(DATA.all_plots), plots)
    st.session_state.plots = plots


def _set_preserves(selected: list[str]) -> None:
    plots = _plots_for(selected)
    _sync_checkbox_keys("pres", list(DATA.preserves), selected)
    _sync_checkbox_keys("plot", list(DATA.all_plots), plots)
    st.session_state.preserves = selected
    st.session_state.plots = plots


def _toggle_plot(plot: str) -> None:
    st.session_state.plots = _apply_toggle(
        st.session_state.plots, plot, st.session_state[f"plot_{plot}"],
        list(DATA.all_plots))


def _set_plots(selected: list[str]) -> None:
    _sync_checkbox_keys("plot", list(DATA.all_plots), selected)
    st.session_state.plots = selected


def _toggle_period(period: str) -> None:
    st.session_state.treatment_periods = _apply_toggle(
        st.session_state.treatment_periods, period,
        st.session_state[f"per_{period}"], list(core.TREATMENT_GROUP_CHOICES))


def _set_periods(selected: list[str]) -> None:
    _sync_checkbox_keys("per", list(core.TREATMENT_GROUP_CHOICES), selected)
    st.session_state.treatment_periods = selected


def _toggle_ttype(comp: str) -> None:
    st.session_state.treatment_components = _apply_toggle(
        st.session_state.treatment_components, comp,
        st.session_state[f"tt_{comp}"], list(DATA.treatment_components))


def _set_ttypes(selected: list[str]) -> None:
    _sync_checkbox_keys("tt", list(DATA.treatment_components), selected)
    st.session_state.treatment_components = selected


_SET_ALL.update({
    "preserves": lambda v: _set_preserves(v),
    "plots": lambda v: _set_plots(v),
    "treatment_periods": lambda v: _set_periods(v),
    "treatment_components": lambda v: _set_ttypes(v),
})


# ------------------------------------------------------------------- widgets

def group_head(title: str, first: bool = False) -> None:
    if not first:
        st.markdown('<div class="v2-grouprule"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="v2-group">{title}</div>', unsafe_allow_html=True)


def ctl_label(name: str, value: str) -> None:
    st.markdown(
        f'<div class="v2-ctl"><span class="v2-ctl-name">{name}</span>'
        f'<span class="v2-ctl-val">{value}</span></div>',
        unsafe_allow_html=True,
    )


def chip_row(items: list[tuple[str, str]], selected: list[str], key_prefix: str,
             field: str, ordering: list, per_row: int = 4,
             tips: dict | None = None, disabled: set | None = None) -> None:
    """
    A wrapping strip of toggle chips.

    Streamlit has no chip widget, so these are buttons laid out in columns and
    coloured by `type`: primary when on, secondary when off. Species chips are
    additionally tinted their own colour by theme_v2.species_chip_css.
    """
    on = set(selected)
    off = disabled or set()
    for start in range(0, len(items), per_row):
        row = items[start:start + per_row]
        cols = st.columns(per_row)
        for col, (value, label) in zip(cols, row):
            with col:
                st.button(
                    label,
                    key=f"{key_prefix}_{value}",
                    type="primary" if value in on else "secondary",
                    on_click=_toggle_chip,
                    args=(field, value, ordering),
                    use_container_width=True,
                    # A four-letter code is not a name. The tooltip carries the
                    # common and scientific ones without widening the chip.
                    help=(tips or {}).get(value),
                    disabled=value in off,
                )


def _bulk_list(field: str, ordering: list) -> None:
    """All or nothing, and push the result onto the checkbox widgets."""
    want = ([] if len(st.session_state[field]) >= len(ordering)
            else list(ordering))
    _SET_ALL[field](want)


def checklist_dropdown(label: str, options: list[tuple[str, str]],
                       selected: list[str], key_prefix: str, on_toggle,
                       field: str, ordering: list,
                       available: set | None = None) -> None:
    """
    A multi-select dropdown: a full-width trigger showing the count, opening a
    checkbox list under one Clear / Select all action.

    st.multiselect was tried here and rejected — its chips grow the control as
    you pick, so the panel reflows and a dozen preserves become a tall stack of
    tags. This keeps the control one fixed row whatever is selected, which is
    what the first dashboard did.

    One toggling action rather than a pair, matching Season and Species: with
    both buttons present, one of the two was always the no-op.
    """
    # The count is out of what is actually available under the current time
    # and treatment filters, not out of the whole network. Narrowing to 2022
    # leaves 20 of the 40 plots with nothing recorded, and a control that
    # still says '40' invites a selection that silently returns nothing.
    live = available if available is not None else {v for v, _ in options}
    n_live = sum(1 for v, _ in options if v in live)
    n_sel = sum(1 for v in selected if v in live)
    trigger = f"{label} ({n_sel}/{n_live})"
    with st.popover(trigger, use_container_width=True):
        st.button("Clear All" if n_sel >= n_live else "Select All",
                  key=f"{key_prefix}__bulk", on_click=_bulk_list,
                  args=(field, ordering))
        st.markdown('<div class="luc-rule" style="margin:8px 0"></div>',
                    unsafe_allow_html=True)
        for value, text in options:
            key = f"{key_prefix}_{value}"
            if key not in st.session_state:
                st.session_state[key] = value in selected
            off = value not in live
            st.checkbox(text, key=key, on_change=on_toggle, args=(value,),
                        disabled=off,
                        help="No recordings under the current Year Range, "
                             "Season or Treatment filters" if off else None)


def panel_head(title: str, note: str, sub: str = "") -> None:
    """
    Title, then the scope note beneath it on the left, then the rule.

    The note used to sit at the right end of the title row, where a wrapping
    title pushed it into its own corner and it read as unrelated. Under the
    title it reads as a subtitle of it.
    """
    st.markdown(
        f'<div class="v2-panelhead"><h2 class="v2-panelh2">{title}</h2>'
        f'<span class="v2-panelnote">{note}</span></div>'
        + (f'<div class="v2-panelsub">{sub}</div>' if sub else ""),
        unsafe_allow_html=True,
    )


def species_key(codes: list[str]) -> None:
    colors = core.species_colors_by_rank(DATA)
    items = "".join(
        f'<div class="v2-key-item">'
        f'<span class="v2-key-dot" style="background:{colors.get(c, core.ACCENT)}">'
        f'</span>{c}</div>'
        for c in codes
    )
    st.markdown(f'<div class="v2-key">{items}</div>', unsafe_allow_html=True)


def tick_row(labels: list[str]) -> None:
    """
    The slider's scale — a mark per step with its label beneath, as designed.

    Positioned by percentage so each mark sits on the value the thumb snaps
    to. The end labels are nudged inward, since a centred label at 0% and 100%
    would hang off both edges of the sidebar.
    """
    n = len(labels)
    out = []
    for i, v in enumerate(labels):
        pct = 0.0 if n == 1 else i / (n - 1) * 100
        shift = "0" if i == 0 else ("-100%" if i == n - 1 else "-50%")
        out.append(f'<span class="v2-tick-mark" style="left:{pct:.4f}%"></span>')
        out.append(f'<span class="v2-tick" style="left:{pct:.4f}%;'
                   f'transform:translateX({shift})">{v}</span>')
    st.markdown(f'<div class="v2-ticks">{"".join(out)}</div>',
                unsafe_allow_html=True)


def section_gap() -> None:
    st.markdown('<div class="v2-sectiongap"></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------- sidebar

# The filters as they stand entering this run, used only to work out which
# preserves and plots have anything to show. The page's own `f` is read after
# the sidebar, once every control has been drawn.
_avail_f = current_filters()

with st.sidebar:
    st.markdown(
        '<div class="v2-brand"><div class="v2-kicker">LUC Bioacoustics</div>'
        '<div class="v2-brandtitle">Filters</div></div>',
        unsafe_allow_html=True,
    )

    group_head("Time", first=True)
    # Driven by `value` with no key, and the label drawn afterwards into a
    # reserved slot. st.select_slider decides single-vs-range from `value`
    # alone: seeding session_state with a tuple and omitting `value` handed a
    # single-value slider a pair, which crashes in the browser.
    _year_slot = st.empty()
    _d = core.default_filters(DATA)
    if "year_range" not in st.session_state:
        st.session_state.year_range = (_d.year_from, _d.year_to)
    # Keyed, so the widget owns its state and a drag registers on the first
    # try. Without the key its identity changed every time the value did,
    # which made Streamlit rebuild it mid-drag and drop the change. `value` is
    # still passed because st.select_slider reads single-versus-range mode
    # from it, and a tuple in session state alone is not enough.
    y0, y1 = st.select_slider(
        "Year range", options=DATA.years, key="year_range",
        value=st.session_state.year_range,
        label_visibility="collapsed")
    tick_row([str(y) for y in DATA.years])
    _year_slot.markdown(
        f'<div class="v2-ctl"><span class="v2-ctl-name">Year Range</span>'
        f'<span class="v2-ctl-val">{y0} – {y1}</span></div>'
        if y0 != y1 else
        f'<div class="v2-ctl"><span class="v2-ctl-name">Year Range</span>'
        f'<span class="v2-ctl-val">{y0}</span></div>',
        unsafe_allow_html=True)

    ctl_label("Season", f"{len(st.session_state.seasons)}/{len(DATA.seasons)}")
    st.button(
        "Clear All" if len(st.session_state.seasons) >= len(DATA.seasons)
        else "Select All",
        key="v2_bulk_seas", on_click=_bulk, args=("seasons", list(DATA.seasons)),
    )
    # All four seasons are shown, two by two, with any the dataset has no
    # recordings for greyed out rather than absent. A missing button reads as
    # a season nobody thought about; a disabled one says the fieldwork has not
    # covered it yet.
    chip_row([(s, s) for s in SEASON_ORDER], st.session_state.seasons,
             "v2seas", "seasons", list(DATA.seasons), per_row=2,
             tips={s: f"No {s.lower()} recordings yet"
                  for s in SEASON_ORDER if s not in DATA.seasons},
             disabled={s for s in SEASON_ORDER if s not in DATA.seasons})

    group_head("Detection Quality")
    ctl_label("Confidence Threshold", f"≥ {st.session_state.confidence:.2f}")
    # A slider over the four cached thresholds rather than a continuous track:
    # the cache stores one pre-aggregated table per threshold, so a value
    # between them has no data behind it.
    st.select_slider("Confidence", options=DATA.meta["thresholds"],
                     key="confidence", format_func=lambda v: f"{v:.1f}",
                     label_visibility="collapsed")
    tick_row([f"{v:.1f}" for v in DATA.meta["thresholds"]])
    # No value on the right here: the radio below already shows which unit
    # is selected, so the blue readout repeated it.
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Detection Unit</span></div>', unsafe_allow_html=True)
    st.radio("Detection unit", list(core.METRIC_LABELS), key="metric",
             format_func=lambda v: core.METRIC_UNIT_LABELS[v],
             label_visibility="collapsed", horizontal=True)

    group_head("Location")
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Preserve</span>'
                '</div>', unsafe_allow_html=True)
    _live_pres = core.preserves_with_effort(DATA, _avail_f)
    checklist_dropdown(
        "Preserve", [(p, p) for p in DATA.preserves],
        st.session_state.preserves, "pres", _toggle_preserve,
        "preserves", list(DATA.preserves), available=_live_pres)
    _avail_plots = _plots_for(list(st.session_state.preserves))
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Plot</span>'
                '</div>', unsafe_allow_html=True)
    checklist_dropdown(
        "Plot",
        [(r.plot, f"{r.plot} · {r.preserve} · {r.treatment_group}")
         for r in DATA.plots.itertuples() if r.plot in set(_avail_plots)],
        st.session_state.plots, "plot", _toggle_plot,
        "plots", list(_avail_plots),
        available=core.plots_with_effort(DATA, _avail_f))

    group_head("Species")
    ctl_label("Species",
              f"{len(st.session_state.species)}/{len(DATA.species_codes)}")
    st.button(
        "Clear All" if len(st.session_state.species) >= len(DATA.species_codes)
        else "Select All",
        key="v2_bulk_sp", on_click=_bulk,
        args=("species", list(DATA.species_codes)),
    )
    # Five to a row rather than four: the codes are four characters whatever
    # the species, so the chips can be narrow, and the list is expected to grow
    # past twenty.
    chip_row([(c, c) for c in DATA.species_codes], st.session_state.species,
             "v2sp", "species", list(DATA.species_codes), per_row=5,
             tips={c: f"{c}: {DATA.species_names.get(c, c)}, "
                     f"{DATA.species_scientific.get(c, '')}"
                  for c in DATA.species_codes})

    group_head("Treatments")
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Treatment Group'
                '</span></div>', unsafe_allow_html=True)
    checklist_dropdown(
        "Group", [(g, g) for g in core.TREATMENT_GROUP_CHOICES],
        st.session_state.treatment_periods, "per", _toggle_period,
        "treatment_periods", list(core.TREATMENT_GROUP_CHOICES))
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Treatment '
                'Activity</span></div>', unsafe_allow_html=True)
    checklist_dropdown(
        "Activity", [(c, c) for c in DATA.treatment_components],
        st.session_state.treatment_components, "tt", _toggle_ttype,
        "treatment_components", list(DATA.treatment_components))

    st.markdown('<div class="v2-grouprule"></div>', unsafe_allow_html=True)
    st.button("Reset all filters", key="v2_reset", on_click=_reset,
              use_container_width=True)


# ------------------------------------------------- keep the panel's scroll
# Dragging the sidebar divider makes Streamlit re-render the panel, and the
# element that scrolls is replaced in the process, so its scrollTop resets and
# the filters jump back to the brand block. Nothing in the Python API reaches
# that element, so the position is held from the page itself: note where the
# panel is scrolled to when a drag starts on the divider, then put it back on
# every frame until the drag ends.
#
# This runs through components.html because st.markdown strips <script>. The
# component's own iframe is same-origin, which is what lets it reach the app's
# DOM through window.parent; it renders nothing and takes no height.
components.html(
    """
<script>
(function () {
  const doc = window.parent.document;

  // The scrolling element is not always the same node across Streamlit
  // versions, so find whichever ancestor actually overflows.
  function scroller() {
    const sb = doc.querySelector('section[data-testid="stSidebar"]');
    if (!sb) return null;
    let el = sb.querySelector('[data-testid="stSidebarUserContent"]') || sb;
    while (el && el !== sb && el.scrollHeight <= el.clientHeight + 1) {
      el = el.parentElement;
    }
    return el || sb;
  }

  let held = 0;
  let dragging = false;

  doc.addEventListener('pointerdown', function (e) {
    const sb = doc.querySelector('section[data-testid="stSidebar"]');
    if (!sb) return;
    // A drag on the divider starts within a few pixels of the panel's right
    // edge; anything further in is an ordinary click on a control.
    const edge = sb.getBoundingClientRect().right;
    if (Math.abs(e.clientX - edge) > 14) return;

    const el = scroller();
    if (!el) return;
    held = el.scrollTop;
    dragging = true;

    (function keep() {
      const s = scroller();
      if (s) s.scrollTop = held;
      if (dragging) requestAnimationFrame(keep);
    })();

    doc.addEventListener('pointerup', function () {
      // A beat past the release, so the re-render that follows the drag is
      // covered too.
      setTimeout(function () {
        const s = scroller();
        if (s) s.scrollTop = held;
        dragging = false;
      }, 250);
    }, { once: true });
  }, true);

  // ── Testing 1: no text selection while dragging the divider ────────────
  // The pointer is on a resize handle, but the browser still treats the drag
  // as a text selection and highlights the whole panel. Suppressed for the
  // duration of the drag only, so ordinary selection still works.
  doc.addEventListener('pointerdown', function (e) {
    const sb = doc.querySelector('section[data-testid="stSidebar"]');
    if (!sb) return;
    if (Math.abs(e.clientX - sb.getBoundingClientRect().right) > 14) return;
    doc.body.style.userSelect = 'none';
    doc.addEventListener('pointerup', function () {
      doc.body.style.userSelect = '';
    }, { once: true });
  }, true);

  // ── hold the reading position across a rerun ───────────────────────────
  // Changing a filter resizes the charts above wherever you are reading, and
  // the browser keeps the scroll offset rather than the content, so a
  // different section slides into view. CSS scroll anchoring was tried first
  // and did not take here. This remembers which section heading was nearest
  // the top of the viewport and where it sat, then puts it back once the
  // rerun's DOM changes have settled.
  //
  // The heading is remembered by its id, not by holding the node. Streamlit
  // replaces the DOM on every rerun, so a stored element reference is
  // detached by the time the restore runs and silently does nothing, which is
  // exactly how this failed the first time. Streamlit derives the id from the
  // heading text, so it survives the rerun.
  let anchorId = null;    // which section heading the reader is under
  let anchorTop = 0;      // and where it sat in the viewport
  let restoring = false;  // true while we are the ones moving the page

  function headings() {
    return doc.querySelectorAll('.stMainBlockContainer h2[id]');
  }

  function noteAnchor() {
    let best = null;
    headings().forEach(function (h) {
      const top = h.getBoundingClientRect().top;
      // The heading at or just above the top of the viewport is the one the
      // reader is under.
      if (top < 140 && (!best || top > best.top)) best = { id: h.id, top: top };
    });
    if (best) {
      anchorId = best.id;
      anchorTop = best.top;
    }
  }

  function restoreAnchor() {
    if (!anchorId) return;
    const el = doc.getElementById(anchorId);
    if (!el) return;
    const delta = el.getBoundingClientRect().top - anchorTop;
    if (Math.abs(delta) > 4) scroller2().scrollBy(0, delta);
  }

  function scroller2() {
    const main = doc.querySelector('section[data-testid="stMain"]');
    if (main && main.scrollHeight > main.clientHeight + 1) return main;
    return doc.scrollingElement || doc.documentElement;
  }

  noteAnchor();
  window.parent.addEventListener('scroll', function () {
    if (!restoring) noteAnchor();
  }, true);

  // ── keep the two top panels level ──────────────────────────────────────
  // Their headings wrap to different numbers of lines, which pushed each
  // column's rule, subtitle and chart to a different height. A CSS min-height
  // cannot fix it: the number of lines depends on the width, so any fixed
  // reserve is either too small at one size or wasteful at another. Measuring
  // the pair and levelling them up to the taller one works at every width.
  function level(selector) {
    const els = doc.querySelectorAll(
      'div[data-testid="stColumn"] ' + selector);
    if (els.length < 2) return;
    els.forEach(function (el) { el.style.minHeight = ''; });
    let tallest = 0;
    els.forEach(function (el) {
      tallest = Math.max(tallest, el.getBoundingClientRect().height);
    });
    els.forEach(function (el) { el.style.minHeight = tallest + 'px'; });
  }

  function levelAll() {
    level('.v2-panelhead');
    level('.v2-panelsub');
  }

  // On load, on resize, and whenever Streamlit rerenders the page. Debounced:
  // Plotly mutates the DOM heavily while a chart draws, and levelling on every
  // one of those was enough work to compete with dragging a slider.
  let pending = null;
  function levelSoon() {
    if (pending) window.parent.clearTimeout(pending);
    pending = window.parent.setTimeout(function () {
      pending = null;
      levelAll();
      // Once the rerun has finished redrawing, put the reader back where they
      // were. Flagged so the scroll it causes is not mistaken for the reader
      // moving and used to re-record the anchor.
      // Plotly keeps resizing for a while after Streamlit has finished, so
      // one restore lands early and the page drifts again. Repeated over the
      // next second, then the flag is cleared.
      restoring = true;
      restoreAnchor();
      [150, 400, 800].forEach(function (ms) {
        window.parent.setTimeout(restoreAnchor, ms);
      });
      window.parent.setTimeout(function () { restoring = false; }, 900);
    }, 120);
  }
  levelAll();
  window.parent.addEventListener('resize', levelSoon);
  new window.parent.MutationObserver(levelSoon)
    .observe(doc.body, { childList: true, subtree: true });
})();
</script>
""",
    height=0,
)


# -------------------------------------------------------------------- header

f = current_filters()
rows = core.apply_filters(DATA, f)
kpis = core.compute_kpis(DATA, f, rows)

st.markdown(
    f'<h1 class="v2-title">LUC Species Detection Explorer</h1>'
    f'<div class="v2-scope">{core.subtitle_text(DATA, f)}</div>'
    f'<div class="v2-headrule"></div>',
    unsafe_allow_html=True,
)


def kpi(label: str, value: str, note: str) -> str:
    """One card. The note is a chip, as the design draws it."""
    return (f'<div class="v2-kpi"><div class="v2-kpi-label">{label}</div>'
            f'<div class="v2-kpi-value">{value}</div>'
            f'<div class="v2-kpi-sub">{note}</div></div>')


def kpi_pair(a_label: str, a_value: str, a_note: str,
             b_label: str, b_value: str, b_note: str) -> str:
    """
    Two figures in one card, side by side.

    Preserves and Plots answer one question, how much of the network the
    current selection reaches, so they share a card. They keep their own
    labels and counts rather than being run together as '12 / 40', which read
    as a fraction of one thing.
    """
    half = ('<div class="v2-kpi-half"><div class="v2-kpi-label">{l}</div>'
            '<div class="v2-kpi-value">{v}</div>'
            '<div class="v2-kpi-sub">{n}</div></div>')
    return ('<div class="v2-kpi v2-kpi-split">'
            + half.format(l=a_label, v=a_value, n=a_note)
            + half.format(l=b_label, v=b_value, n=b_note)
            + '</div>')


# Four cards, per the design. Recordings folded into Species Presence as its
# denominator, where it says something rather than sitting alone.
#
# Hours Recorded does follow the filters: selecting Burley shows 80, not 2,983.
# The chip names the whole-project total so the filtered number has something
# to be read against, rounded because a tenth of an hour is noise here.
st.markdown(
    '<div class="v2-kpis">'
    + kpi(core.METRIC_LABELS[f.metric], f"{kpis.total_detections:,}",
          f"detections from {kpis.n_recordings:,} 10-min recordings")
    + kpi("Hours Recorded", f"{kpis.hours_recorded:,.0f}",
          f"out of {DATA.meta.get('total_audio_hours', 0):,.0f} total hours")
    + kpi("Species Richness", f"{kpis.richness}",
          f"out of {kpis.n_species_tracked} tracked")
    + kpi_pair("Preserves", f"{kpis.n_preserves}",
               f"out of {len(DATA.preserves)}",
               "Plots", f"{kpis.active_plots}",
               f"out of {len(DATA.all_plots)}")
    + "</div>",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------- charts

def line_chart(series: list[dict], buckets: list[str], decimals: int = 0,
               scope: str = "", full_labels: dict | None = None) -> go.Figure:
    fig = go.Figure()
    fmt = f",.{decimals}f"
    # The season spelled out, so the hover does not repeat the axis's own
    # abbreviation back at the reader.
    names = [(full_labels or {}).get(b, b) for b in buckets]
    for s in series:
        fig.add_trace(
            go.Scatter(
                x=buckets,
                y=s["values"],
                mode="lines+markers",
                name=s["label"],
                line=dict(color=s["color"], width=2.5, shape="linear"),
                # A point larger than the line, so a single selected season
                # still reads as a value rather than as a dot on an axis.
                marker=dict(size=8, color=s["color"],
                            line=dict(color="#ffffff", width=1.5)),
                fill="tozeroy",
                fillcolor=core.rgba(s["color"], 0.08),
                customdata=names,
                hovertemplate=(
                    "<b>%{customdata}</b><br>"
                    f"{s['label']}: %{{y:{fmt}}}"
                    + (f"<br><span style='font-size:11px'>{scope}</span>"
                       if scope else "")
                    + "<extra></extra>"
                ),
            )
        )
    fig.update_layout(**theme.plotly_layout())
    fig.update_xaxes(title=dict(text="Season-Year",
                                font=dict(size=12, color=core.NEUTRAL_600)))
    fig.update_yaxes(title=dict(text="Count",
                                font=dict(size=12, color=core.NEUTRAL_600)),
                     rangemode="tozero")
    return fig


def bar_chart(bars: pd.DataFrame, decimals: int = 0, unit: str = "detections",
              scope: str = "") -> go.Figure:
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
            # Code, common name and scientific name together: the four-letter
            # code is what the axis shows and what people search for, but it
            # is not what most readers recognise.
            customdata=[
                [f"{r.species_code}: {r.name}",
                 DATA.species_scientific.get(r.species_code, "")]
                for r in bars.itertuples()
            ],
            hovertemplate=(
                "<b>%{customdata[0]}</b>"
                "<br><i>%{customdata[1]}</i>"
                f"<br>%{{y:{fmt}}} {unit}"
                + (f"<br><span style='font-size:11px'>{scope}</span>"
                   if scope else "")
                + "<extra></extra>"
            ),
        )
    )
    fig.update_layout(**theme.plotly_layout())
    fig.update_xaxes(title=dict(text="Species Code",
                                font=dict(size=12, color=core.NEUTRAL_600)))
    fig.update_yaxes(title=dict(text="Count",
                                font=dict(size=12, color=core.NEUTRAL_600)),
                     rangemode="tozero")
    fig.update_traces(width=0.56)
    return fig


def hourly_chart(curves: pd.DataFrame, facets: list, facet_label: str,
                 codes: list[str]) -> go.Figure:
    """
    One small-multiple panel per facet value, a line per species.

    Every panel carries its own hour labels, but all panels share one hour
    range and one y-scale: the point is comparing the shape of the dawn curve
    between years or preserves, and letting each panel autoscale would stretch
    a short recording window across the same width as a long one, and make a
    quiet year look like a busy one.
    """
    n = len(facets)
    ncols = 1 if n == 1 else (2 if n <= 4 else 3)
    nrows = math.ceil(n / ncols)
    # 'Split by Plot' asks for 40 panels; at the height a four-panel grid uses
    # that is a page and a half of scrolling, so the rows get shorter and the
    # lines thinner rather than the grid simply growing.
    dense = n > 12
    # A third-width panel cannot take six rotated hour labels without the
    # labels reaching into the next row's title, whatever the gap. Three
    # across is the threshold, not twelve panels: an eight-panel preserve grid
    # is just as narrow as a forty-panel plot grid.
    tight = ncols == 3
    row_h = 190 if dense else 270
    total_h = row_h * nrows + 90

    # Spacing is a fraction of the *whole figure*, not of a row, so it is
    # specified in pixels and converted. The gap has to clear the panel's hour
    # labels and the following panel's title. Dense grids need less: their
    # labels lie flat and only every second hour is drawn.
    gap_px = 62 if tight else 78
    v_gap = min(gap_px / total_h, 0.8 / max(nrows - 1, 1))
    h_gap = min(0.035, 0.8 / max(ncols - 1, 1))
    fig = make_subplots(
        rows=nrows, cols=ncols, shared_xaxes=False, shared_yaxes=True,
        subplot_titles=[str(v) for v in facets],
        # Tighter on the tall grids. Every panel prints its own hour
        # labels, so the gap has to clear those plus the next panel's
        # title, but at 0.13 a twelve-preserve grid spent more height on
        # gaps than on lines.
        vertical_spacing=v_gap,
        # Tighter across than down: the panels share a y-scale, so the gap
        # only has to clear the leftmost column's tick labels.
        horizontal_spacing=h_gap,
    )
    rank_colors = core.species_colors_by_rank(DATA)

    for i, value in enumerate(facets):
        r, c = divmod(i, ncols)
        sub = curves[curves["facet"] == value]
        for code in codes:
            line = sub[sub["species_code"] == code].sort_values("hour")
            if line.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=line["hour"], y=line["pct"],
                    mode="lines+markers", name=code,
                    legendgroup=code,
                    showlegend=(i == 0),   # one legend entry per species
                    line=dict(color=rank_colors.get(code, core.ACCENT),
                              width=1.2 if dense else 2),
                    marker=dict(size=3 if dense else 5),
                    customdata=line[["days_detected", "days_sampled"]],
                    hovertemplate=(
                        f"<b>{code}: {DATA.species_names.get(code, code)}</b>"
                        f"<br><i>{DATA.species_scientific.get(code, '')}</i>"
                        f"<br>{value} · %{{x}}:00 · %{{y:.1f}}%"
                        "<br>%{customdata[0]:,.0f} of %{customdata[1]:,.0f} "
                        "recorder-days<extra></extra>"
                    ),
                ),
                row=r + 1, col=c + 1,
            )

    fig.update_layout(**theme.plotly_layout())
    fig.update_layout(
        height=total_h,
        legend=dict(orientation="h", yanchor="bottom", y=1.04,
                    xanchor="left", x=0, font=dict(size=11)),
        margin=dict(l=10, r=10, t=70, b=40),
    )
    hours = DATA.hours
    # Range is pinned rather than left to autoscale: shared_xaxes is off so
    # each panel prints its own labels, which also unlinks the ranges, and a
    # preserve recorded over fewer hours would otherwise be drawn wider.
    shown = [h for h in hours if h in set(curves["hour"])] or list(hours)
    # Six labels do not fit across a third-width panel, so on the dense grids
    # every second hour is labelled and the text lies flat. Rotated labels
    # were what pushed the panels into each other.
    ticks = hours[::2] if tight else hours
    fig.update_xaxes(tickmode="array", tickvals=ticks,
                     ticktext=[f"{h}:00" for h in ticks],
                     tickangle=0 if tight else -45,
                     range=[min(shown) - 0.4, max(shown) + 0.4],
                     title=None, showgrid=True)
    # Quartiles, not just the thirds Plotly picks: 25 and 75 are the readings
    # people actually want off an occupancy curve.
    fig.update_yaxes(range=[0, 105], ticksuffix="%", title=None,
                     tickmode="array", tickvals=[0, 25, 50, 75, 100])
    # No 'Hour' title at all. Every panel already prints 4:00 to 9:00 beneath
    # itself, so the word was restating the labels while pushing the next
    # panel's title into them. '% Occupancy' stays, but only down the left:
    # the y-scale is shared, so repeating it mid-grid labelled an axis with no
    # ticks beside it.
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None)
    fig.update_yaxes(title=dict(text="% Occupancy",
                                font=dict(size=10, color=core.NEUTRAL_600)),
                     col=1)
    for ann in fig.layout.annotations:    # subplot titles
        ann.font.size = 12 if dense else 15
    # One species at a time, picked up anywhere along its line rather than
    # only on the 5px marker. 'x unified' was tried and was wrong: it answers
    # "what was every species doing at 7:00", which buries the one line the
    # pointer is actually on under seven others. 'closest' answers "what is
    # this line doing here", and the generous hover distance means the line
    # itself is the target, not the dot. Readings still land on whole hours,
    # because that is where the data is; hovering at 7:30 reports 7:00 or
    # 8:00, whichever is nearer.
    fig.update_layout(hovermode="closest", hoverdistance=25)
    return fig


def _readable_on(hex_bg: str) -> str:
    """Black or white text, whichever contrasts better with the cell colour."""
    h = hex_bg.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    # Perceived luminance (ITU-R BT.601).
    return core.INK if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


def _roster_text(names: list[str], n_plots: int) -> str:
    """
    Say which plots a grid covers, without printing forty codes.

    Forty comma-separated codes read as decoration rather than information, and
    nothing on screen said what they were. The whole network is named as such,
    a long subset is counted by preserve, which is the unit people think in,
    and only a short selection is listed code by code. The full list stays on
    the element's tooltip either way.
    """
    if n_plots <= 1:
        return ""
    if n_plots == len(DATA.all_plots):
        return (f"all {n_plots} plots across "
                f"{DATA.plots['preserve'].nunique()} preserves")
    if n_plots <= 8:
        return ", ".join(names)
    by_preserve = (DATA.plots[DATA.plots["plot"].isin(set(names))]
                   .groupby("preserve")["plot"].size()
                   .sort_values(ascending=False))
    return (f"{n_plots} plots · "
            + " · ".join(f"{pv} ({n})" for pv, n in by_preserve.items()))


def _panel_treatment_html(names: list[str], f: core.Filters) -> str:
    """
    The treatment periods and activities for one panel's own plots.

    The strip at the top of the section pools every selected plot, which is
    the right summary for a single grid but wrong once By Treatment splits the
    page: GCP-D and GCP-G can have had different work done, and reading one
    plot's grid against the other's activities is worse than having none.
    """
    rows = []
    for t in core.treatment_summary(DATA, core.replace(f, plots=tuple(names))):
        label = t["display"] or t["period"].capitalize()
        types = (f'<details class="luc-treatmore"><summary>{t["types"]}'
                 f'</summary>{t["types_full"]}</details>'
                 if t["truncated"] else f'<span>{t["types"]}</span>')
        rows.append(f'<span class="luc-treatitem">'
                    f'<span class="luc-treatkey">{label}</span>'
                    f'<span class="luc-treattype">{types}</span></span>')
    return (f'<div class="luc-treatbar luc-treatbar-panel">{"".join(rows)}</div>'
            if rows else "")


def occupancy_html(panel: dict, effort_label: str,
                   rate_mode: bool = False, scope: str = "",
                   filters: core.Filters | None = None) -> str:
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
    roster = _roster_text(names, n_plots)

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
        out.append(f'<div class="luc-occ-roster" title="{", ".join(names)}">'
                   f'<span class="luc-occ-rosterkey">Plots</span>{roster}</div>')
    # Only on a grouped panel: on a single grid this would repeat the strip
    # already sitting above the section.
    if panel["label"] and filters is not None and names:
        out.append(_panel_treatment_html(names, filters))

    # No divider between periods: the colour ramp already distinguishes them,
    # and a rule would imply the columns are not one continuous timeline.
    def edge(ci: int) -> str:
        return ""

    out.append(f'<div class="luc-occ" style="grid-template-columns:{cols}">')
    # The corner cell was empty while the column beneath it held four-letter
    # codes with nothing saying what they were.
    out.append('<div class="luc-occ-corner">Species code<br>'
               '<span class="luc-occ-cornerx">by season-year &#8594;</span>'
               '</div>')
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
            season_full = core.bucket_full_label(DATA, col["bucket"])
            if rate_mode:
                # Counts are unbounded, so the ramp is scaled to the largest
                # value on screen rather than to 100.
                bg = core.ramp_color(col["ramp"], v / vmax)
                days = float(sampling.get(ci, 0))
                per = f" · {v / days:,.1f} per sampling day" if days else ""
                out.append(
                    f'<div class="luc-occ-cell" style="background:{bg};'
                    f'color:{_readable_on(bg)};{edge(ci)}" '
                    f'title="{code} — {name}&#10;{season_full}&#10;'
                    f'{v:,.0f} recordings over {days:,.0f} sampling days{per}'
                    f'&#10;{scope}">{v:,.0f}</div>'
                )
            else:
                bg = core.ramp_color(col["ramp"], v / 100)
                out.append(
                    f'<div class="luc-occ-cell" style="background:{bg};'
                    f'color:{_readable_on(bg)};{edge(ci)}" '
                    f'title="{code} — {name}&#10;{season_full}&#10;'
                    f'{v:.1f}% occupancy&#10;{scope}">{v:.0f}</div>'
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


def region_map(nodes: pd.DataFrame, sites: pd.DataFrame, codes: list[str],
               effort_label: str, scope: str = "") -> go.Figure:
    """
    Real basemap from the dataset's plot coordinates, one bubble per species.

    Static, unlike v1's: the season scrubber is gone because the sidebar's Year
    range and Season chips already say which slice to draw, and two controls
    for one question is one too many. The map shows the current filter
    selection, pooled.

    No Plotly legend either. Anchored above the plotting area it was drawn over
    the 2px rule under the section heading, and its translucent white panel hid
    all of that rule except the stub past its last entry. The species key is
    page markup now, which also lets it match the design.

    Species are their own traces so one can be isolated by click, and stay
    translucent because they are fanned tightly around a shared coordinate and
    will overlap when zoomed out.
    """
    fig = go.Figure()

    # The AudioMoth's actual position, drawn first so the fanned species
    # bubbles sit over it. Opaque and small: a reference point, not a value.
    fig.add_trace(
        _MAP_TRACE(
            lat=sites["latitude"], lon=sites["longitude"], mode="markers",
            name="AudioMoth",
            marker=dict(size=5, color=core.RECORDER_DOT, allowoverlap=True),
            customdata=sites[["plot", "preserve"]],
            hovertemplate=("<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
                           "AudioMoth position<extra></extra>"),
        )
    )

    rank_colors = core.species_colors_by_rank(DATA)
    for code in codes:
        pts = _species_points(nodes, code)
        fig.add_trace(
            _MAP_TRACE(
                lat=pts["lat"], lon=pts["lon"], mode="markers", name=code,
                marker=dict(
                    size=pts["marker"]["size"],
                    color=core.rgba(rank_colors.get(code, core.ACCENT), 0.85),
                    allowoverlap=True,
                ),
                customdata=pts["customdata"],
                hovertemplate=(
                    f"<b>{code}: {DATA.species_names.get(code, code)}</b>"
                    f"<br><i>{DATA.species_scientific.get(code, '')}</i>"
                    "<br>%{customdata[0]} · %{customdata[1]}"
                    "<br>%{customdata[3]:.1f}% occupancy over "
                    "%{customdata[4]:,.0f} " + effort_label.lower()
                    + (f"<br><span style='font-size:11px'>{scope}</span>"
                       if scope else "")
                    + "<extra></extra>"
                ),
            )
        )

    lat, lon = sites["latitude"], sites["longitude"]
    fig.update_layout(
        height=520,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Archivo, sans-serif", size=12, color=core.INK),
        hoverlabel=dict(bgcolor=core.INK, bordercolor=core.INK,
                        font=dict(family="Archivo", size=12, color="#ffffff")),
        showlegend=False,
        # Constant across reruns, so a filter change elsewhere does not reframe
        # a map the user has panned.
        uirevision="v2-region",
        **{
            _MAP_LAYOUT_KEY: dict(
                style="open-street-map",
                center=dict(lat=float(lat.mean()), lon=float(lon.mean())),
                zoom=8.2,
                uirevision="v2-region",
            )
        },
    )
    return fig



# ------------------------------------------------------------------ sections

NO_DATA = (not kpis.has_data) or rows.empty
PLOT_CFG = {"displayModeBar": False}


def empty_note(msg: str = "No detections match the current filters. Widen the "
                          "selection or lower the confidence threshold.") -> None:
    st.markdown(f'<div class="luc-empty">{msg}</div>', unsafe_allow_html=True)


def _toggle_section(key: str) -> None:
    st.session_state[key] = not st.session_state[key]


def collapsible_head(title: str, key: str, ratio=(3, 1.5)):
    """
    Section heading with a disclosure arrow, and a slot for its own control.

    The three big sections run to several screens each, so reaching the map
    means scrolling past forty line charts. Collapsing is cheaper than
    scrolling and cheaper than paging: the sections stay on one page, in one
    order, and a shut one costs a single row.

    Returns (open, control_slot). The control is only drawn when the section
    is open, since a mode toggle for something you cannot see is noise.
    """
    st.session_state.setdefault(key, True)
    is_open = st.session_state[key]
    c_arrow, c_title, c_ctl = st.columns(
        [0.28, ratio[0], ratio[1]], vertical_alignment="center")
    with c_arrow:
        st.button("▾" if is_open else "▸", key=f"{key}__toggle",
                  on_click=_toggle_section, args=(key,),
                  help="Hide this section" if is_open else "Show this section")
    with c_title:
        st.markdown(f'<h2 class="v2-panelh2">{title}</h2>',
                    unsafe_allow_html=True)
    return is_open, c_ctl


def head_row(title: str, ratio=(3, 1.5)):
    """Heading with room for a control on the right, then the 2px ink rule."""
    left, right = st.columns(ratio, vertical_alignment="center")
    with left:
        st.markdown(f'<h2 class="v2-panelh2">{title}</h2>', unsafe_allow_html=True)
    return right


def head_rule(sub: str = "") -> None:
    st.markdown('<div class="v2-panelrule"></div>'
                + (f'<div class="v2-panelsub">{sub}</div>' if sub else ""),
                unsafe_allow_html=True)


# ── the two summary charts, side by side as in the mockup ──────────────────
col_time, col_species = st.columns(2)

with col_time:
    panel_head(
        "Total Detections Over Time", "Per season over time",
        "Total raw count of species detections per season, over the years. "
        "NOT corrected for variability in survey effort (days recorded and "
        "number of devices).")
    if NO_DATA:
        empty_note()
    else:
        series, buckets = core.build_series(
            DATA, core.replace(f, graph_type="trends"), rows, "detections")
        st.plotly_chart(
            line_chart(series, buckets,
                       scope=core.hover_scope(DATA, f, seasons=False),
                       full_labels={b: core.bucket_full_label(DATA, b)
                                    for b in buckets}),
            use_container_width=True, config=PLOT_CFG, key="v2_trends")

with col_species:
    panel_head(
        "Total Detections By Species", "Aggregated &amp; ranked",
        "Aggregated and ranked total raw counts per species. NOT corrected "
        "for variability in survey effort (days recorded and number of "
        "devices).")
    if NO_DATA:
        empty_note()
    else:
        st.plotly_chart(
            bar_chart(core.species_bars(DATA, f, rows),
                      unit=core.metric_phrase(DATA, f),
                      scope=core.hover_scope(DATA, f)),
            use_container_width=True, config=PLOT_CFG, key="v2_species")

section_gap()


# ── occupancy heatmap ─────────────────────────────────────────────────────
_occ_open, _occ_slot = collapsible_head(core.panel_copy(DATA, f)[0],
                                       "v2_open_occ")
with _occ_slot:
    if _occ_open:
        st.segmented_control(
            "Granularity", list(V2_OCC_MODES), key="occ_granularity",
            label_visibility="collapsed",
            format_func=lambda v: V2_OCC_MODES[v],
            help="Daily and Hourly % are occupancy: the share of surveyed "
                 "days, or surveyed hours, a species was detected in. Count "
                 "is the number of recordings containing it, which keeps "
                 "separating species after occupancy has saturated. By "
                 "Treatment splits the daily grid into control, "
                 "pre-treatment and post-treatment.",
        )
# The toggle above may have changed the mode, so the filters are re-read
# before anything is drawn from them.
f = current_filters()
# 'By Treatment' is a grouping, not a counting unit: it draws the daily grid
# split by treatment period. Everything downstream reads occ_granularity, so
# the mode is translated here rather than taught to each of them.
f_occ = (core.replace(f, occ_granularity="daily",
                      compare_by="treatment_group")
         if f.occ_granularity == "treatment" else f)
head_rule(core.panel_copy(DATA, f_occ)[1] if _occ_open else "")

if not _occ_open:
    pass
elif NO_DATA:
    empty_note()
else:
    # Treatment context, as plain text. It briefly carried a colour swatch per
    # period, keyed to that period's ramp, but each ramp runs light to dark
    # within itself, so a pale cell in the post-treatment grid looked like the
    # pale pre-treatment swatch. Each grid is titled with its own period
    # instead, which says the same thing without inviting that reading.
    _items = []
    for t in core.treatment_summary(DATA, f_occ):
        label = t["display"] or t["period"].capitalize()
        # A '+8 more' that cannot be opened just says information is being
        # withheld, so the full list is one click away in a native disclosure.
        types = (f'<details class="luc-treatmore"><summary>{t["types"]}'
                 f'</summary>{t["types_full"]}</details>'
                 if t["truncated"] else f'<span>{t["types"]}</span>')
        _items.append(f'<span class="luc-treatitem">'
                      f'<span class="luc-treatkey">{label}</span>'
                      f'<span class="luc-treattype">{types}</span></span>')
    st.markdown(f'<div class="luc-treatbar">{"".join(_items)}</div>',
                unsafe_allow_html=True)

    _panels = core.occupancy_panels(DATA, f_occ, rows)
    if not _panels:
        empty_note("No groups to compare under the current filters.")
    else:
        _effort = core.OCC_EFFORT_LABELS[f_occ.occ_granularity]
        for i, panel in enumerate(_panels):
            if i:
                st.markdown('<div class="luc-occ-spacer"></div>',
                            unsafe_allow_html=True)
            st.markdown(occupancy_html(panel, _effort,
                                       core.is_rate_mode(f_occ),
                                       scope=core.hover_scope(DATA, f_occ),
                                       filters=f_occ),
                        unsafe_allow_html=True)
    st.markdown(
        f'<div class="luc-occ-note">{core.occupancy_note(DATA, f_occ)}</div>',
        unsafe_allow_html=True)

section_gap()


# ── occupancy rate by hour ────────────────────────────────────────────────
_hour_open, _hour_slot = collapsible_head(
    "Occupancy Rate By Hour (%)", "v2_open_hour", ratio=(2, 1.5))
with _hour_slot:
    if _hour_open:
        # A dropdown rather than a button row: six facets will not fit as
        # segments at any sensible width, and more may follow.
        st.selectbox(
            "Split by", list(core.HOUR_FACETS), key="hour_facet",
            format_func=lambda v: core.HOUR_FACETS[v],
            label_visibility="collapsed",
            help="One panel per year, season, preserve, plot, treatment group "
                 "or treatment activity.",
        )
f = current_filters()
head_rule("For each hour of the morning, the share of recorder-days on which "
          "a species was heard in that hour." if _hour_open else "")

_codes = [c for c in core.species_rank(DATA) if c in set(f.species)]
if not _hour_open:
    pass
elif NO_DATA or not _codes:
    empty_note()
else:
    _curves = core.hourly_curves(DATA, f, f.hour_facet)
    _facets = core.hourly_facet_values(DATA, f, f.hour_facet)
    if _curves.empty or not _facets:
        empty_note("No recordings match the current filters.")
    else:
        species_key(_codes)
        st.plotly_chart(hourly_chart(_curves, _facets, f.hour_facet, _codes),
                        use_container_width=True, config=PLOT_CFG,
                        key="v2_hourly")
        st.markdown(
            '<div class="luc-occ-note"><b>Occupancy Rate By Hour</b> = '
            'recorder-days a species was detected in that clock hour ÷ '
            'recorder-days recorded in that hour.<br>'
            'One recorder-day is one plot on one date, so a morning covered '
            'by eight recorders counts eight times as much listening as one '
            'covered by a single recorder. This is deliberately not the '
            'sampling-days rule the heatmap above uses: pooled over many '
            'plots that rule sits above 90% for common species and the daily '
            'rhythm disappears. A line stops where the fieldwork did, so an '
            'hour that was never recorded draws no point rather than a '
            'zero.</div>',
            unsafe_allow_html=True)

section_gap()


# ── map ───────────────────────────────────────────────────────────────────
_map_open, _ = collapsible_head("Species Presence By Plot", "v2_open_map")
head_rule(
    "Where the recorders are, and how often each species was detected at each "
    "of them. Bubble size is the occupancy rate: the share of surveyed days "
    "that species was heard on at that plot, so plots recorded for very "
    "different lengths of time can be compared." if _map_open else "")

_sites = core.region_sites(DATA, f)
if not _map_open:
    pass
elif _sites.empty or NO_DATA or not _codes:
    empty_note("No plots selected.")
else:
    _daily = core.OCC_EFFORT_LABELS["daily"]
    # One slice, matching the sidebar's Year range and Season selection. The
    # in-figure season scrubber this used to carry is gone: the filter panel
    # already answers "which seasons", and two controls for one question left
    # it ambiguous which was in charge.
    _nodes = core.region_species_nodes(DATA, f, rows)
    species_key(_codes)
    st.plotly_chart(
        region_map(_nodes, _sites, _codes, _daily,
                   scope=core.hover_scope(DATA, f)),
        use_container_width=True, key="v2_map", config=PLOT_CFG)
    # Attribution is required by OpenStreetMap. The basemap's built-in control
    # is hidden in theme_v2 — it sat inside the frame at a size that fought the
    # map — and re-stated here, flush to the bottom right.
    st.markdown(
        '<div class="v2-mapcredit">© '
        '<a href="https://www.openstreetmap.org/copyright" target="_blank" '
        'rel="noopener">OpenStreetMap</a> contributors</div>',
        unsafe_allow_html=True)
    st.caption(
        f"{len(_sites)} plots across {_sites['preserve'].nunique()} preserves, "
        f"pooled over the selected seasons. Black dots are the AudioMoths' "
        f"true positions; species bubbles are fanned around them so they do "
        f"not stack, and the commonest species is drawn underneath."
    )


# ------------------------------------------------------------- methodology

# v2 carries its own methodology rather than calling core.methodology(),
# which v1 still uses. The two pages offer different controls, so a shared
# text would document buttons that are not on screen.
V2_METHODOLOGY = [
    ("Detection unit: what counts as one detection", [
        ("Detection vs No Detection",
         "A species is counted as detected if BirdNET scores it at or above "
         "the selected confidence threshold. It is counted as not detected "
         "below that value. A species may be truly present but counted as not "
         "detected, depending on the threshold."),
        ("Species Presence",
         "At least one species detection in one 10-min recording, counted "
         "0/1, depending on the confidence threshold setting. A bird heard "
         "forty times in a ten-minute file counts once; a file holding three "
         "species contributes three."),
        ("Raw 10-min Detections",
         "The number of 10-minute recordings a species was detected in. This "
         "is the unit behind most of the charts here, including the Count "
         "heatmap and the two totals at the top of the page."),
        ("Raw 3-sec BirdNET-Analyzer Detections",
         "Every three-second window BirdNET scored above the threshold, "
         "counted separately. Roughly twelve times higher than presence, and "
         "it favours persistent singers over widespread ones."),
    ]),
    ("Occupancy", [
        ("Sampling Days",
         "Distinct dates where recording occurred at a selected plot. The "
         "union across plots, not the sum: five recorders over the same "
         "sixteen dates is sixteen days."),
        ("Days Detected",
         "Distinct dates the species was detected at a selected plot."),
        ("Daily Occupancy Rate (%)",
         "Days detected ÷ sampling days. Example: Grovers in Summer 2022, "
         "BEWR on 14 of 16 dates, so 87.5%."),
        ("Hourly Occupancy Rate (%)",
         "Hours detected ÷ sampling hours. A sampling hour is a distinct date "
         "and clock-hour on which a selected plot recorded, so a morning "
         "covered from 5:00 to 9:00 contributes five sampling hours. It "
         "answers how much of the recorded morning a species was audible in, "
         "where the daily rate answers on how many mornings it was audible "
         "at all."),
        ("NA versus 0%",
         "0% means no species detections at that confidence threshold. NA "
         "means no sampling effort, so no recordings, during that time."),
    ]),
    ("Confidence threshold", [
        ("Confidence Threshold",
         "Keeps only detections scoring at or above the chosen value. A "
         "higher threshold keeps only high-confidence detections, which tends "
         "to reduce false positives (raising precision) but also discards "
         "some true positives that scored low (lowering recall)."),
    ]),
    ("Effort and coverage", [
        ("Number of Recordings",
         "Audio files across the selected plots and dates. Files containing "
         "no detection at all still count as effort."),
        ("Hours Recorded",
         "Hours of actual audio, derived from file size rather than from the "
         "recording schedule, since files run slightly short."),
        ("Time of Day",
         "Recording runs in a dawn-chorus window rather than a full day, so "
         "every hourly chart covers the morning only."),
        ("Species Richness",
         "How many of the tracked species were detected at least once under "
         "the current filters. Never divided by effort, but it does rise with "
         "effort, since more listening finds more species."),
        ("Preserves and Plots",
         "The preserves and plots the current filters are looking at."),
    ]),
    ("Treatment group and treatment type", [
        ("Control",
         "Plots never scheduled for treatment. A reference condition rather "
         "than a point on the before-and-after timeline."),
        ("Pre-Treatment",
         "A treatment plot, in the seasons before its treatment date."),
        ("Post-Treatment",
         "The same plot, in the seasons after its treatment date. A plot "
         "treated partway through monitoring contributes to both, which is "
         "why the group is worked out per date rather than fixed per plot."),
        ("Treatment Type",
         "The type of work done at the different treatment plots, where "
         "applicable. It changes with the treatment date too, so a plot reads "
         "'none' beforehand and its actual activities afterwards."),
    ]),
    ("Reading the charts", [
        ("Total Detections Over Time",
         "Raw counts per season-year, not corrected for effort. Seasons "
         "differ in days recorded and plots deployed, and no plot ran in "
         "every season, so part of any change here is fieldwork rather than "
         "birds."),
        ("Total Detections By Species",
         "The same raw counts, aggregated over everything selected and ranked. "
         "Species are not equally detectable, so read it as what BirdNET "
         "heard most, not what is most abundant."),
        ("Seasonal Occupancy Rate, Daily %",
         "For each species and season, the share of surveyed days it was "
         "detected on. Effort-corrected, so seasons of very different lengths "
         "are comparable."),
        ("Seasonal Occupancy Rate, Hourly %",
         "The same, counting distinct date-and-hour slots instead of dates. "
         "Finer grained, and it separates species that are present on most "
         "days but audible only briefly."),
        ("Total Detections heatmap (Count)",
         "The raw number of 10-min recordings containing each species. Not "
         "effort-corrected, so read it against the grey sampling-days row, "
         "but unlike occupancy it does not saturate at 100%."),
        ("Seasonal Occupancy Rate, By Treatment",
         "The daily grid split into control, pre-treatment and post-treatment, "
         "each with its own colour ramp, so a plot's before and after can be "
         "compared against a control that was never treated."),
        ("Occupancy Rate By Hour (%)",
         "For each hour of the morning, the share of recorder-days a species "
         "was heard in that hour. Split by year, season, preserve, plot, "
         "treatment group or treatment activity."),
        ("Species Presence By Plot",
         "The map. Black dots are the recorders; bubble size is each species' "
         "occupancy rate at that plot over the selected seasons."),
        ("The four header cards",
         "Detections, hours, richness and network coverage for the current "
         "selection. All four follow the filters."),
    ]),
]


def _meth_rows(entries) -> str:
    return ('<div class="luc-meth">'
            + "".join(
                f'<div class="luc-methrow"><div class="luc-methterm">{term}</div>'
                f'<div class="luc-methdef">{definition}</div></div>'
                for term, definition in entries)
            + "</div>")


with st.expander("Methodology: what each control and measure means"):
    for heading, entries in V2_METHODOLOGY:
        st.markdown(f'<div class="luc-methhead">{heading}</div>',
                    unsafe_allow_html=True)
        st.markdown(_meth_rows(entries), unsafe_allow_html=True)
    st.markdown(
        '<div class="luc-methnote">Full derivations, source-table joins and '
        'the verification suite are documented in DATA_METHODS.md.</div>',
        unsafe_allow_html=True,
    )
