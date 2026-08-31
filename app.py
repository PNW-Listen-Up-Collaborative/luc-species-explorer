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
    for key, valid in {"occ_granularity": list(core.OCC_MODES),
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
    """All or nothing, on the same button — whichever the current state isn't."""
    st.session_state[field] = [] if st.session_state[field] else list(ordering)


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
             field: str, ordering: list, per_row: int = 4) -> None:
    """
    A wrapping strip of toggle chips.

    Streamlit has no chip widget, so these are buttons laid out in columns and
    coloured by `type`: primary when on, secondary when off. Species chips are
    additionally tinted their own colour by theme_v2.species_chip_css.
    """
    on = set(selected)
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
                )


def _bulk_list(field: str, ordering: list) -> None:
    """All or nothing, and push the result onto the checkbox widgets."""
    want = [] if st.session_state[field] else list(ordering)
    _SET_ALL[field](want)


def checklist_dropdown(label: str, options: list[tuple[str, str]],
                       selected: list[str], key_prefix: str, on_toggle,
                       field: str, ordering: list) -> None:
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
    trigger = f"{label} ({len(selected)}/{len(options)})"
    with st.popover(trigger, use_container_width=True):
        st.button("Clear" if selected else "Select all",
                  key=f"{key_prefix}__bulk", on_click=_bulk_list,
                  args=(field, ordering))
        st.markdown('<div class="luc-rule" style="margin:8px 0"></div>',
                    unsafe_allow_html=True)
        for value, text in options:
            key = f"{key_prefix}_{value}"
            if key not in st.session_state:
                st.session_state[key] = value in selected
            st.checkbox(text, key=key, on_change=on_toggle, args=(value,))


def panel_head(title: str, note: str, sub: str = "") -> None:
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
    y0, y1 = st.select_slider(
        "Year range", options=DATA.years,
        value=st.session_state.get("year_range", (_d.year_from, _d.year_to)),
        label_visibility="collapsed")
    st.session_state.year_range = (y0, y1)
    tick_row([str(y) for y in DATA.years])
    _year_slot.markdown(
        f'<div class="v2-ctl"><span class="v2-ctl-name">Year range</span>'
        f'<span class="v2-ctl-val">{y0} – {y1}</span></div>'
        if y0 != y1 else
        f'<div class="v2-ctl"><span class="v2-ctl-name">Year range</span>'
        f'<span class="v2-ctl-val">{y0}</span></div>',
        unsafe_allow_html=True)

    ctl_label("Season", f"{len(st.session_state.seasons)}/{len(DATA.seasons)}")
    st.button(
        "Select all" if len(st.session_state.seasons) < len(DATA.seasons)
        else "Clear",
        key="v2_bulk_seas", on_click=_bulk, args=("seasons", list(DATA.seasons)),
    )
    chip_row([(s, s) for s in DATA.seasons], st.session_state.seasons,
             "v2seas", "seasons", list(DATA.seasons), per_row=3)

    group_head("Detection quality")
    ctl_label("Confidence threshold", f"≥ {st.session_state.confidence:.2f}")
    # A slider over the four cached thresholds rather than a continuous track:
    # the cache stores one pre-aggregated table per threshold, so a value
    # between them has no data behind it.
    st.select_slider("Confidence", options=DATA.meta["thresholds"],
                     key="confidence", format_func=lambda v: f"{v:.1f}",
                     label_visibility="collapsed")
    tick_row([f"{v:.1f}" for v in DATA.meta["thresholds"]])
    # No value on the right here: the radio below already shows which unit
    # is selected, so the blue readout repeated it.
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Detection unit</span></div>', unsafe_allow_html=True)
    st.radio("Detection unit", list(core.METRIC_LABELS), key="metric",
             format_func=lambda v: core.METRIC_LABELS[v],
             label_visibility="collapsed", horizontal=True)

    group_head("Location")
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Preserve</span>'
                '</div>', unsafe_allow_html=True)
    checklist_dropdown(
        "Preserve", [(p, p) for p in DATA.preserves],
        st.session_state.preserves, "pres", _toggle_preserve,
        "preserves", list(DATA.preserves))
    _avail_plots = _plots_for(list(st.session_state.preserves))
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Plot</span>'
                '</div>', unsafe_allow_html=True)
    checklist_dropdown(
        "Plot",
        [(r.plot, f"{r.plot} · {r.preserve} · {r.treatment_group}")
         for r in DATA.plots.itertuples() if r.plot in set(_avail_plots)],
        st.session_state.plots, "plot", _toggle_plot,
        "plots", list(_avail_plots))

    group_head("Species")
    ctl_label("Species",
              f"{len(st.session_state.species)}/{len(DATA.species_codes)}")
    st.button(
        "Select all" if len(st.session_state.species) < len(DATA.species_codes)
        else "Clear",
        key="v2_bulk_sp", on_click=_bulk,
        args=("species", list(DATA.species_codes)),
    )
    # Five to a row rather than four: the codes are four characters whatever
    # the species, so the chips can be narrow, and the list is expected to grow
    # past twenty.
    chip_row([(c, c) for c in DATA.species_codes], st.session_state.species,
             "v2sp", "species", list(DATA.species_codes), per_row=5)

    group_head("Treatments")
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Treatment group'
                '</span></div>', unsafe_allow_html=True)
    checklist_dropdown(
        "Group", [(g, g) for g in core.TREATMENT_GROUP_CHOICES],
        st.session_state.treatment_periods, "per", _toggle_period,
        "treatment_periods", list(core.TREATMENT_GROUP_CHOICES))
    st.markdown('<div class="v2-ctl"><span class="v2-ctl-name">Treatment '
                'activity</span></div>', unsafe_allow_html=True)
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


def kpi(label: str, value: str, sub: str) -> str:
    return (f'<div class="v2-kpi"><div class="v2-kpi-label">{label}</div>'
            f'<div class="v2-kpi-value">{value}</div>'
            f'<div class="v2-kpi-sub">{sub}</div></div>')


st.markdown(
    '<div class="v2-kpis">'
    + kpi(core.METRIC_LABELS[f.metric], f"{kpis.total_detections:,}",
          f"{core.metric_unit_short(DATA, f.metric)} · conf ≥ {f.confidence}")
    + kpi("Recordings", f"{kpis.n_recordings:,}", "at selected plots &amp; dates")
    + kpi("Hours recorded", f"{kpis.hours_recorded:,.0f}", "true audio, same scope")
    + kpi("Species richness", f"{kpis.richness}",
          f"of {kpis.n_species_tracked} tracked")
    + kpi("Preserves", f"{kpis.n_preserves}", f"of {len(DATA.preserves)} detected")
    + kpi("Plots", f"{kpis.active_plots}", f"of {len(DATA.all_plots)} detected")
    + "</div>",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------- charts
#
# Copied verbatim from app.py so v1 keeps working untouched while the two
# layouts are compared. Whichever version survives, the loser's copy goes
# and these move to a shared charts module.

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
    fig = make_subplots(
        rows=nrows, cols=ncols, shared_xaxes=False, shared_yaxes=True,
        subplot_titles=[str(v) for v in facets],
        # Tighter on the tall grids. Every panel prints its own hour labels,
        # so the gap has to clear those plus the next panel's title — but at
        # 0.13 a twelve-preserve grid spent more height on gaps than on lines.
        vertical_spacing=0.085 if nrows > 2 else 0.16,
        horizontal_spacing=0.06,
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
                    line=dict(color=rank_colors.get(code, core.ACCENT), width=2),
                    marker=dict(size=5),
                    customdata=line[["days_detected", "days_sampled"]],
                    hovertemplate=(
                        f"<b>{code}</b> · {value}<br>%{{x}}:00 · %{{y:.1f}}%"
                        "<br>%{customdata[0]:,.0f} of %{customdata[1]:,.0f} "
                        "plot-days<extra></extra>"
                    ),
                ),
                row=r + 1, col=c + 1,
            )

    fig.update_layout(**theme.plotly_layout())
    fig.update_layout(
        height=270 * nrows + 90,
        legend=dict(orientation="h", yanchor="bottom", y=1.04,
                    xanchor="left", x=0, font=dict(size=11)),
        margin=dict(l=10, r=10, t=70, b=40),
    )
    hours = DATA.hours
    # Range is pinned rather than left to autoscale: shared_xaxes is off so
    # each panel prints its own labels, which also unlinks the ranges, and a
    # preserve recorded over fewer hours would otherwise be drawn wider.
    shown = [h for h in hours if h in set(curves["hour"])] or list(hours)
    fig.update_xaxes(tickmode="array", tickvals=hours,
                     ticktext=[f"{h}:00" for h in hours],
                     range=[min(shown) - 0.4, max(shown) + 0.4],
                     title=None, showgrid=True)
    fig.update_yaxes(range=[0, 105], ticksuffix="%", title=None)
    for a in fig.layout.annotations:      # subplot titles
        a.font.size = 13
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

    Forty comma-separated codes is a wall of text that reads as decoration
    rather than information, and nothing on screen said what they were. So:
    the whole network is named as such, a long subset is counted by preserve —
    which is the unit people actually think in — and only a short selection is
    listed code by code. The full list stays on the element's tooltip either
    way.
    """
    if n_plots <= 1:
        # A single-plot grid is already titled with that plot.
        return ""
    if n_plots == len(DATA.all_plots):
        n_preserves = DATA.plots["preserve"].nunique()
        return f"all {n_plots} plots across {n_preserves} preserves"
    if n_plots <= 8:
        return ", ".join(names)

    chosen = set(names)
    by_preserve = (DATA.plots[DATA.plots["plot"].isin(chosen)]
                   .groupby("preserve")["plot"].size().sort_values(ascending=False))
    parts = [f"{pv} ({n})" for pv, n in by_preserve.items()]
    return f"{n_plots} plots · " + " · ".join(parts)


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


def region_map(nodes: pd.DataFrame, sites: pd.DataFrame, codes: list[str],
               effort_label: str) -> go.Figure:
    """
    Real basemap from the dataset's plot coordinates, one bubble per species.

    Static, unlike v1's: the season scrubber is gone because the sidebar's Year
    range and Season chips already say which slice to draw, and two controls
    for one question is one too many. What the map shows is simply the current
    filter selection, pooled.

    No Plotly legend either. Anchored above the plotting area it was drawn over
    the 2px rule under the section heading, and its translucent white panel hid
    all of that rule except the stub past its last entry — the stray dark line.
    The species key is page markup now, which also lets it match the design.

    Species are their own traces so one can be isolated by click, and stay
    translucent because they are fanned tightly around a shared coordinate and
    will overlap when zoomed out.
    """
    fig = go.Figure()

    # The AudioMoth's actual position, drawn first so the fanned species
    # bubbles sit over it. Fully opaque and small: a reference point, not a
    # value.
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
        pts = _species_points(nodes, code)
        fig.add_trace(
            _MAP_TRACE(
                lat=pts["lat"],
                lon=pts["lon"],
                mode="markers",
                name=code,
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
        # the map the user has panned.
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
        "Total Detections Over Time", "Per season",
        f"{core.metric_phrase(DATA, f).capitalize()}, raw count per season. "
        f"Not corrected for survey effort.")
    if NO_DATA:
        empty_note()
    else:
        series, buckets = core.build_series(
            DATA, core.replace(f, graph_type="trends"), rows, "detections")
        st.plotly_chart(line_chart(series, buckets), use_container_width=True,
                        config=PLOT_CFG, key="v2_trends")

with col_species:
    panel_head("Total Detections By Species", "Ranked",
               "Ranked across the selected range. Not corrected for survey "
               "effort.")
    if NO_DATA:
        empty_note()
    else:
        st.plotly_chart(
            bar_chart(core.species_bars(DATA, f, rows),
                      unit=core.metric_phrase(DATA, f)),
            use_container_width=True, config=PLOT_CFG, key="v2_species")

section_gap()


# ── occupancy heatmap ─────────────────────────────────────────────────────
_occ_slot = head_row(core.panel_copy(DATA, f)[0])
with _occ_slot:
    st.segmented_control(
        "Granularity", core.OCC_MODES, key="occ_granularity",
        label_visibility="collapsed",
        format_func=lambda v: core.OCC_MODE_LABELS[v],
        help="Daily/Hourly % are occupancy, the share of sampling days a "
             "species was detected on. Count is recordings containing it, "
             "which keeps separating species after occupancy saturates.",
    )
# The toggle above may have changed the mode, so the filters are re-read
# before anything is drawn from them.
f = current_filters()
head_rule(core.panel_copy(DATA, f)[1])

if NO_DATA:
    empty_note()
else:
    # Treatment context, as plain text: with no Compare by in v2 the period
    # ramps are never on screen, so a colour key would point at nothing.
    _items = "".join(
        f'<span class="luc-treatitem">'
        f'<span class="luc-treatkey">{t["display"]}</span>'
        f'<span class="luc-treattype">{t["types"]}</span></span>'
        for t in core.treatment_summary(DATA, f) if t["display"]
    )
    st.markdown(f'<div class="luc-treatbar">{_items}</div>',
                unsafe_allow_html=True)

    _panels = core.occupancy_panels(DATA, f, rows)
    if not _panels:
        empty_note("No groups to compare under the current filters.")
    else:
        _effort = core.OCC_EFFORT_LABELS[f.occ_granularity]
        for i, panel in enumerate(_panels):
            if i:
                st.markdown('<div class="luc-occ-spacer"></div>',
                            unsafe_allow_html=True)
            st.markdown(occupancy_html(panel, _effort, core.is_rate_mode(f)),
                        unsafe_allow_html=True)
    st.markdown(f'<div class="luc-occ-note">{core.occupancy_note(DATA, f)}</div>',
                unsafe_allow_html=True)

section_gap()


# ── occupancy rate by hour ────────────────────────────────────────────────
_hour_slot = head_row("Occupancy Rate By Hour")
with _hour_slot:
    st.segmented_control(
        "Facet", list(core.HOUR_FACETS), key="hour_facet",
        label_visibility="collapsed",
        format_func=lambda v: core.HOUR_FACETS[v],
        help="Which grid the hours are split into: one panel per year, per "
             "season, or per preserve.",
    )
f = current_filters()
head_rule("Plot-days detected ÷ plot-days sampled, at each clock hour")

_codes = [c for c in core.species_rank(DATA) if c in set(f.species)]
if NO_DATA or not _codes:
    empty_note()
else:
    _curves = core.hourly_curves(DATA, f, f.hour_facet)
    _facets = core.hourly_facet_values(DATA, f, f.hour_facet)
    if _curves.empty or not _facets:
        empty_note("No recordings match the current filters.")
    else:
        st.plotly_chart(hourly_chart(_curves, _facets, f.hour_facet, _codes),
                        use_container_width=True, config=PLOT_CFG,
                        key="v2_hourly")

section_gap()


# ── map ───────────────────────────────────────────────────────────────────
panel_head("Species Presence By Plot", "Occupancy per species")

_sites = core.region_sites(DATA, f)
if _sites.empty or NO_DATA or not _codes:
    empty_note("No plots selected.")
else:
    _daily = core.OCC_EFFORT_LABELS["daily"]
    # One slice, matching the sidebar's Year range and Season selection. The
    # in-figure season scrubber this used to carry is gone: the filter panel
    # already answers "which seasons", and two controls for one question left
    # it ambiguous which was in charge.
    _nodes = core.region_species_nodes(DATA, f, rows)
    species_key(_codes)
    st.plotly_chart(region_map(_nodes, _sites, _codes, _daily),
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
        f"{len(_sites)} plots across {_sites['preserve'].nunique()} preserves. "
        f"Bubble size is occupancy over the selected seasons."
    )


# ------------------------------------------------------------- methodology

st.markdown(
    f'<div class="luc-footnote">'
    f'{DATA.meta["n_detection_rows"]:,} raw detections across '
    f'{DATA.meta["n_recordings"]:,} recordings · confidence thresholds computed '
    f'per-row from the source table · detection metric is summed 0/1 presence '
    f'per recording × species.</div>',
    unsafe_allow_html=True,
)

# Only the chart-reading notes live here; everything else comes from
# core.methodology(), which v1 shares. These four were captions under the
# charts and crowded the page.
READING_THE_CHARTS = [
    ("The two top charts",
     "Raw counts, not corrected for effort. Seasons differ in days recorded "
     "and plots deployed, and no plot ran in every season."),
    ("The species ranking",
     "Species are not equally detectable. Read it as what BirdNET heard most, "
     "not what is most abundant."),
    ("Occupancy Rate By Hour",
     "Plot-days detected ÷ plot-days sampled, where a plot-day is one "
     "recorder on one date. Not the union rule above."),
    ("Species Presence By Plot",
     "Bubble size is occupancy. Black dots are the AudioMoths; species are "
     "fanned around them so they do not stack."),
]


def _meth_rows(entries) -> str:
    return ('<div class="luc-meth">'
            + "".join(
                f'<div class="luc-methrow"><div class="luc-methterm">{term}</div>'
                f'<div class="luc-methdef">{definition}</div></div>'
                for term, definition in entries)
            + "</div>")


# Skipped rather than deleted from core.methodology(), which v1 shares and
# where every one of these is still correct.
#
# The section and the first entry document controls v2 does not have: the
# Total/Per day toggle is gone from this page, and so is the map's
# sunrise scrubber. Documenting a button that is not on screen is worse than
# verbose. The rest answer questions this page does not raise: reconciling the
# presence count against another tally, justifying occupancy over counts, and
# the provenance of the 0.3 default, which is in DATA_METHODS.md.
_SKIP_SECTIONS = {"Scale: whether the count is divided by effort"}
_SKIP_ENTRIES = {
    "Hours from sunrise",
    "Not the same as recordings with a detection",
    "Why occupancy rather than counts",
    "Default of 0.3",
}

with st.expander("Methodology: what each control and measure means"):
    for heading, entries in core.methodology(DATA):
        if heading in _SKIP_SECTIONS:
            continue
        kept = [e for e in entries if e[0] not in _SKIP_ENTRIES]
        if not kept:
            continue
        st.markdown(f'<div class="luc-methhead">{heading}</div>',
                    unsafe_allow_html=True)
        st.markdown(_meth_rows(kept), unsafe_allow_html=True)
    st.markdown('<div class="luc-methhead">Reading the charts</div>',
                unsafe_allow_html=True)
    st.markdown(_meth_rows(READING_THE_CHARTS), unsafe_allow_html=True)
    st.markdown(
        '<div class="luc-methnote">Full derivations, source-table joins and '
        'the verification suite are documented in DATA_METHODS.md.</div>',
        unsafe_allow_html=True,
    )
