"""
Data layer for the LUC Species Detection Explorer.

Pure pandas, no Streamlit imports, so it can be tested and reused headlessly.
Everything operates on the small pre-aggregated tables written by build_cache.py.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------- tokens

ACCENT = "#138eec"          # project-level override of the Modernist accent
INK = "#201e1d"
NEUTRAL_600 = "#7d7979"
DIVIDER = "#e3e0e0"
GROUND = "#f3f2f2"
SURFACE = "#ffffff"


def shade(hex_color: str, pct: float) -> str:
    """Blend toward white (pct > 0) or black (pct < 0), matching the DC's shadeHex."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))

    def blend(c: int) -> int:
        v = round(c + (255 - c) * pct) if pct >= 0 else round(c * (1 + pct))
        return max(0, min(255, v))

    return "#" + "".join(f"{blend(c):02x}" for c in (r, g, b))


ACCENT_400 = shade(ACCENT, 0.55)    # light tint  ~ #8fcaf5
ACCENT_700 = shade(ACCENT, -0.40)   # dark shade  ~ #0b5599

PALETTE = [ACCENT, INK, NEUTRAL_600, ACCENT_400, ACCENT_700]

# Colours for Compare-by series. PALETTE was used here and holds five entries,
# four of them blues or greys, so 'By activity' (11 groups) and 'By preserve'
# (12) cycled it and drew several series in the same colour — unreadable on a
# line chart where colour is the only thing telling the lines apart.
#
# Twelve is the most any grouping needs. One per hue family, shades chosen by
# simulating protanopia, deuteranopia and tritanopia (worst pair dE 10.5 —
# lower than the eight-colour species set, which is the unavoidable cost of
# needing half again as many), and ordered so neighbours contrast, since groups
# are listed alphabetically and adjacent ones sit together in the legend.
GROUP_COLORS = [
    "#FF7F9E",   # pink
    "#0044CC",   # blue
    "#D40000",   # red
    "#5B2C9E",   # purple
    "#E36C09",   # orange
    "#1F2E63",   # navy
    "#F0B400",   # gold
    "#00B3C6",   # cyan
    "#A0522D",   # brown
    "#E5308F",   # magenta
    "#8C9440",   # olive
    "#1B8A3C",   # green
]

# Control is green, not gray, so it means the same thing in the Trends legend as
# it does in the occupancy heatmaps, and never collides with the gray used for
# sampling effort.
CONTROL = "#2f8f45"

TREATMENT_GROUP_COLORS = {
    "control": CONTROL,
    "pretreat": ACCENT_400,
    "posttreat": ACCENT,
}
TREATMENT_GROUP_ORDER = ["control", "pretreat", "posttreat"]

# Spelled out when the strip is read as prose rather than as a colour key.
PERIOD_DISPLAY = {
    "pretreat": "Pre-Treatment Type",
    "posttreat": "Post-Treatment Type",
}


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha:.3f})"


# --------------------------------------------------------------- heatmap ramps
# Taken from Nb3_BirdNET_Results_Exploration.ipynb so the dashboard's occupancy
# heatmaps match the notebook's dual-period figures: purple = pretreat,
# blue = posttreat. Control is not in the notebook's dual-period plots. It was
# gray, but gray is already the effort row (Sampling days / Recording hours) and
# the not-surveyed hatching, so control's cells read as chrome rather than data.
# Green separates it cleanly from both, and from pretreat and posttreat.
RAMPS: dict[str, list[str]] = {
    "accent":    ["#f2f8fe", "#c3e0f9", "#7cc0f2", ACCENT,    "#0b4c80"],
    "pretreat":  ["#faf5f8", "#e4c4d6", "#c47aa3", "#aa3377", "#6b1f4a"],
    "posttreat": ["#f4f7fb", "#c5d6e8", "#7ba3c4", "#4477aa", "#2d5080"],
    "control":   ["#f3f9f4", "#c9e5cd", "#85c491", "#2f8f45", "#145226"],
    "green":     ["#f3f9f4", "#c9e5cd", "#85c491", "#2f8f45", "#145226"],
    "orange":    ["#fef6f0", "#fbd9c0", "#f2a875", "#dd6b20", "#8a3c0a"],
    "teal":      ["#f2fafb", "#c9e9ee", "#7fc7d4", "#3a92a5", "#1b5566"],
    "wine":      ["#fbf4f6", "#ecc9d5", "#d086a0", "#a33355", "#5e1730"],
}

# Ramps cycled for groupings without a canonical colour (forage guild, preserve,
# treatment type). 'green' is left out: control grids sit on the same page as
# the per-preserve treatment grids in the faceted view, so reusing green there
# would put two different meanings in one colour on one screen.
RAMP_CYCLE = ["teal", "orange", "wine", "posttreat", "pretreat"]


def ramp_for(compare_by: str, key: str, idx: int) -> str:
    """Which named ramp a heatmap panel should use."""
    if compare_by == "none":
        return "accent"
    if compare_by == "treatment_group" and key in ("control", "pretreat", "posttreat"):
        return key
    return RAMP_CYCLE[idx % len(RAMP_CYCLE)]


def ramp_color(ramp: str, t: float) -> str:
    """Interpolate a 0-1 position through a named ramp's colour stops."""
    stops = RAMPS.get(ramp, RAMPS["accent"])
    t = max(0.0, min(1.0, float(t)))
    if t >= 1:
        return stops[-1]
    span = 1 / (len(stops) - 1)
    i = int(t / span)
    local = (t - i * span) / span
    a, b = stops[i].lstrip("#"), stops[i + 1].lstrip("#")
    out = []
    for j in (0, 2, 4):
        ca, cb = int(a[j:j + 2], 16), int(b[j:j + 2], 16)
        out.append(round(ca + (cb - ca) * local))
    return "#" + "".join(f"{c:02x}" for c in out)


def ramp_css(ramp: str) -> str:
    """CSS linear-gradient for the legend bar."""
    return "linear-gradient(to right, " + ", ".join(RAMPS.get(ramp, RAMPS["accent"])) + ")"


# ----------------------------------------------------------------- data model

@dataclass(frozen=True)
class Dataset:
    detections: pd.DataFrame
    effort: pd.DataFrame
    plots: pd.DataFrame
    meta: dict
    # Same numbers as detections/effort but retaining time of day, which only
    # the Region map slices on. Summing the time key out reproduces the main
    # tables. `hour_*` keeps clock hour; `solar_*` keeps hours relative to
    # sunrise, which is what the map actually uses — see solar_bins.
    hour_detections: pd.DataFrame
    hour_effort: pd.DataFrame
    solar_detections: pd.DataFrame
    solar_effort: pd.DataFrame
    # The (plot, date, hour) slots recorded, and the slots on which each species
    # was detected. Occupancy unions these across the selected plots — a species
    # counts for a day if it was heard anywhere that day — which cannot be
    # recovered from per-plot totals, so the slots themselves are kept.
    dates: pd.DataFrame
    species_dates: pd.DataFrame

    # --- convenience lookups -------------------------------------------------
    @property
    def species(self) -> list[dict]:
        return self.meta["species"]

    @property
    def species_codes(self) -> list[str]:
        return [s["code"] for s in self.species]

    @property
    def species_names(self) -> dict[str, str]:
        return {s["code"]: s["name"] for s in self.species}

    @property
    def preserves(self) -> list[str]:
        return list(self.meta["preserves"])

    @property
    def all_plots(self) -> list[str]:
        return list(self.plots["plot"])

    @property
    def years(self) -> list[int]:
        return [int(y) for y in self.meta["years"]]

    @property
    def seasons(self) -> list[str]:
        return list(self.meta["seasons"])

    @property
    def treatment_components(self) -> list[str]:
        return list(self.meta["treatment_components"])

    @property
    def buckets(self) -> pd.DataFrame:
        return pd.DataFrame(self.meta["buckets"])

    @property
    def hours(self) -> list[int]:
        """Start hours actually recorded — a dawn window, not a full 24."""
        return [int(h) for h in self.meta.get("hours", [])]

    @property
    def solar_bins(self) -> list[int]:
        """
        Hours relative to sunrise that were actually recorded; 0 is the hour
        beginning at sunrise, -1 the hour before it.

        This, not clock hour, is the Region map's time axis. The deployment
        schedule tracked dawn — summer recording starts at 04:15, winter at
        07:50 — so on a clock axis hours 4-6 are summer-only and 8-9 mostly
        winter, and "time of day" silently becomes "season". On this axis all
        three seasons overlap in the dawn window.
        """
        return [int(b) for b in self.meta.get("solar_bins", [])]

    @property
    def hour_stops(self) -> list[int]:
        """
        Clock positions for the time-of-day slider, as boundaries not buckets.

        Recordings are stamped by start hour, but each runs about ten minutes,
        so the last one of the day begins at 9:40 and ends at 9:50. An axis that
        stopped at 9 would appear to exclude audio it actually contains, so the
        axis carries one extra stop and a range reads as [start, end).
        """
        hrs = self.hours
        return hrs + [hrs[-1] + 1] if hrs else []

    def plots_for(self, preserves: list[str]) -> list[str]:
        sel = self.plots[self.plots["preserve"].isin(preserves)]
        return list(sel["plot"])


def load_dataset(data_dir: str | Path) -> Dataset:
    d = Path(data_dir)
    detections = pd.read_csv(d / "detections.csv.gz")
    effort = pd.read_csv(d / "effort.csv.gz")
    plots = pd.read_csv(d / "plots.csv.gz")
    plots["treatment_components"] = (
        plots["treatment_components"].fillna("").map(
            lambda s: [c for c in str(s).split("|") if c]
        )
    )
    meta = json.loads((d / "meta.json").read_text())
    return Dataset(
        detections=detections, effort=effort, plots=plots, meta=meta,
        hour_detections=pd.read_csv(d / "hour_detections.csv.gz"),
        hour_effort=pd.read_csv(d / "hour_effort.csv.gz"),
        solar_detections=pd.read_csv(d / "solar_detections.csv.gz"),
        solar_effort=pd.read_csv(d / "solar_effort.csv.gz"),
        dates=pd.read_csv(d / "dates.csv.gz"),
        species_dates=pd.read_csv(d / "species_dates.csv.gz"),
    )


# -------------------------------------------------------------------- filters

@dataclass(frozen=True)
class Filters:
    confidence: float = 0.5
    year_from: int = 0
    year_to: int = 9999
    seasons: tuple[str, ...] = ()
    species: tuple[str, ...] = ()
    preserves: tuple[str, ...] = ()
    plots: tuple[str, ...] = ()
    # Any subset of control/pretreat/posttreat. Multi-select rather than a
    # single choice: 'pretreat + posttreat' (treated plots, either era) and
    # 'control + posttreat' (the after-treatment comparison) are both real
    # questions that a single-choice control could not ask.
    treatment_periods: tuple[str, ...] = ()
    treatment_components: tuple[str, ...] = ()
    graph_type: str = "trends"
    compare_by: str = "none"
    occ_granularity: str = "daily"        # daily|hourly
    metric: str = "presence"              # presence|raw
    normalize: str = "total"              # total|per_day
    # Region map only. Empty means "every season" / "every hour"; the map's two
    # sliders narrow these without disturbing the other views' filters.
    region_bucket: str = ""
    region_hours: tuple[int, ...] = ()
    # Hours relative to sunrise, for the map's time scrubber. Empty means all.
    region_solar: tuple[int, ...] = ()


def default_filters(data: Dataset) -> Filters:
    return Filters(
        # 0.3 is BirdNET's own reporting floor and the notebook's
        # CONFIDENCE_THRESHOLD, so the app opens on the same basis as the report.
        confidence=0.3,
        year_from=min(data.years),
        year_to=max(data.years),
        seasons=tuple(data.seasons),
        species=tuple(data.species_codes),
        preserves=tuple(data.preserves),
        plots=tuple(data.all_plots),
        treatment_periods=tuple(TREATMENT_GROUP_ORDER),
        treatment_components=tuple(data.treatment_components),
        graph_type="occupancy",
        compare_by="none",
        occ_granularity="daily",
    )


def cascade_preserves(data: Dataset, prev: Filters, next_preserves: list[str]) -> Filters:
    """
    Keep the Preserve <-> Plot selections bidirectionally consistent.

    Turning a preserve off drops its plots; turning one on adds all of its plots.
    """
    prev_set, next_set = set(prev.preserves), set(next_preserves)
    kept = [p for p in prev.plots if p in set(data.plots_for(next_preserves))]
    added = [
        p for pv in (next_set - prev_set) for p in data.plots_for([pv])
    ]
    plots = list(dict.fromkeys(kept + added))
    order = {p: i for i, p in enumerate(data.all_plots)}
    plots.sort(key=lambda p: order.get(p, 1 << 30))
    return replace(prev, preserves=tuple(next_preserves), plots=tuple(plots))


def _bucket_year(bucket_sort: pd.Series) -> pd.Series:
    return bucket_sort // 10


def split_components(value) -> list[str]:
    """'patch cut, thinning' -> ['patch cut', 'thinning']."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def component_mask(series: pd.Series, wanted: set[str]) -> pd.Series:
    """Row mask for "this row's treatment type includes a selected component"."""
    # .astype(bool) matters: on an empty frame .map() yields an empty
    # object-dtype Series, which pandas would read as column labels, not a mask.
    return series.map(
        lambda v: bool(set(split_components(v)) & wanted)
    ).astype(bool)


def eligible_plots(data: Dataset, f: Filters) -> list[str]:
    """
    Plots surviving the plot-level filters, which are only preserve and plot.

    Neither treatment group nor treatment type belongs here. Both are date-aware:
    10 of the 40 plots are pretreat early and posttreat later, and those same
    plots carry treatment_type 'none' before treatment and their real activity
    (for example 'patch cut, thinning') after. Both are therefore properties of
    (plot, date) and are filtered per row via `period` and `period_type`.
    """
    sel = data.plots[
        data.plots["plot"].isin(f.plots)
        & data.plots["preserve"].isin(f.preserves)
    ]
    return list(sel["plot"])


# The Treatment period filter's options. Multi-select, so there is no 'all'
# entry: selecting every period is what 'all' meant, and a pooled 'treat'
# option is unnecessary now that pretreat and posttreat can be ticked together.
TREATMENT_GROUP_CHOICES = list(TREATMENT_GROUP_ORDER)


def allowed_periods(f: Filters) -> set[str] | None:
    """Treatment periods the filter admits, or None for no restriction."""
    chosen = set(f.treatment_periods)
    # Everything selected, or nothing yet, means no restriction — the same
    # rows either way, and returning a full set would only cost a merge.
    if not chosen or chosen >= set(TREATMENT_GROUP_ORDER):
        return None
    return chosen


def apply_filters(data: Dataset, f: Filters) -> pd.DataFrame:
    """Filter the pre-aggregated detection table down to the current selection."""
    d = data.detections
    season_of = {b["bucket"]: b["season"] for b in data.meta["buckets"]}
    mask = (
        (d["threshold"] == f.confidence)
        & _bucket_year(d["bucket_sort"]).between(f.year_from, f.year_to)
        & d["species_code"].isin(f.species)
        & d["plot"].isin(eligible_plots(data, f))
        & d["bucket"].map(season_of).isin(f.seasons)
    )
    periods = allowed_periods(f)
    if periods is not None:
        mask &= d["period"].isin(periods)
    mask &= component_mask(d["period_type"], set(f.treatment_components))
    return d[mask].copy()


def _hour_effort_rows(
    data: Dataset, f: Filters, plots: list[str], buckets: list[str],
    hours: list[int],
) -> pd.DataFrame:
    """Sampling effort for a season/hour slice, filtered exactly like effort_rows."""
    e = data.hour_effort
    sel = e[
        e["bucket"].isin(buckets)
        & e["plot"].isin(plots)
        & e["hour"].isin(hours)
    ]
    periods = allowed_periods(f)
    if periods is not None:
        sel = sel[sel["period"].isin(periods)]
    return sel[component_mask(sel["period_type"], set(f.treatment_components))]


def _hour_detection_rows(
    data: Dataset, f: Filters, plots: list[str], buckets: list[str],
    hours: list[int],
) -> pd.DataFrame:
    """Detections for a season/hour slice, filtered exactly like apply_filters."""
    d = data.hour_detections
    season_of = {b["bucket"]: b["season"] for b in data.meta["buckets"]}
    mask = (
        (d["threshold"] == f.confidence)
        & d["bucket"].isin(buckets)
        & d["hour"].isin(hours)
        & d["species_code"].isin(f.species)
        & d["plot"].isin(plots)
        & d["bucket"].map(season_of).isin(f.seasons)
    )
    periods = allowed_periods(f)
    if periods is not None:
        mask &= d["period"].isin(periods)
    mask &= component_mask(d["period_type"], set(f.treatment_components))
    return d[mask].copy()


def _solar_effort_rows(
    data: Dataset, f: Filters, plots: list[str], buckets: list[str],
    bins: list[int],
) -> pd.DataFrame:
    """Effort for a season/solar-hour slice, filtered exactly like effort_rows."""
    e = data.solar_effort
    sel = e[e["bucket"].isin(buckets) & e["plot"].isin(plots)
            & e["solar_bin"].isin(bins)]
    periods = allowed_periods(f)
    if periods is not None:
        sel = sel[sel["period"].isin(periods)]
    return sel[component_mask(sel["period_type"], set(f.treatment_components))]


def _solar_detection_rows(
    data: Dataset, f: Filters, plots: list[str], buckets: list[str],
    bins: list[int],
) -> pd.DataFrame:
    """Detections for a season/solar-hour slice, filtered like apply_filters."""
    d = data.solar_detections
    season_of = {b["bucket"]: b["season"] for b in data.meta["buckets"]}
    mask = (
        (d["threshold"] == f.confidence)
        & d["bucket"].isin(buckets)
        & d["solar_bin"].isin(bins)
        & d["species_code"].isin(f.species)
        & d["plot"].isin(plots)
        & d["bucket"].map(season_of).isin(f.seasons)
    )
    periods = allowed_periods(f)
    if periods is not None:
        mask &= d["period"].isin(periods)
    mask &= component_mask(d["period_type"], set(f.treatment_components))
    return d[mask].copy()


def _slot_key(hourly: bool) -> list[str]:
    """Occupancy's unit of observation: a calendar date, or a (date, hour)."""
    return ["date", "hour"] if hourly else ["date"]


def _filter_slots(
    df: pd.DataFrame, f: Filters, plots: list[str], buckets: list[str],
    periods: set[str] | None = None, period_types: set[str] | None = None,
) -> pd.DataFrame:
    """Shared plot/bucket/period/type filtering for the two slot tables."""
    sel = df[df["bucket"].isin(buckets) & df["plot"].isin(plots)]
    use = periods if periods is not None else allowed_periods(f)
    if use is not None:
        sel = sel[sel["period"].isin(use)]
    sel = sel[component_mask(sel["period_type"], set(f.treatment_components))]
    if period_types is not None:
        sel = sel[sel["period_type"].isin(period_types)]
    return sel


def sampling_days(
    data: Dataset, f: Filters, plots: list[str], buckets: list[str],
    periods: set[str] | None = None, period_types: set[str] | None = None,
    hourly: bool = False,
) -> pd.Series:
    """
    Distinct calendar dates on which *any* selected plot recorded, per bucket.

    The union across plots, not the sum. Five recorders all running on the same
    sixteen dates is sixteen days of fieldwork, not eighty: this is the number
    that makes survey effort comparable between seasons and years, and it is
    the denominator of occupancy.
    """
    key = _slot_key(hourly)
    sel = _filter_slots(data.dates, f, plots, buckets, periods, period_types)
    if sel.empty:
        return pd.Series([0] * len(buckets), index=buckets)
    n = sel.groupby("bucket")[key].nunique() if len(key) == 1 else (
        sel.drop_duplicates(["bucket", *key]).groupby("bucket").size())
    if isinstance(n, pd.DataFrame):
        n = n.iloc[:, 0]
    return pd.Series([int(n.get(b, 0)) for b in buckets], index=buckets)


def days_detected(
    data: Dataset, f: Filters, plots: list[str], buckets: list[str],
    codes: list[str], periods: set[str] | None = None,
    period_types: set[str] | None = None, hourly: bool = False,
) -> pd.Series:
    """
    Distinct dates on which each species was detected at *any* selected plot.

    Indexed by (species_code, bucket). The numerator to sampling_days'
    denominator, counted the same way: a species claims a date if it was heard
    somewhere in the selection that day, however many recordings caught it.
    """
    key = _slot_key(hourly)
    sd = data.species_dates
    sel = sd[(sd["threshold"] == f.confidence) & sd["species_code"].isin(codes)]
    sel = _filter_slots(sel, f, plots, buckets, periods, period_types)
    if sel.empty:
        return pd.Series(dtype=float)
    return (sel.drop_duplicates(["species_code", "bucket", *key])
            .groupby(["species_code", "bucket"]).size())


def effort_rows(
    data: Dataset,
    f: Filters,
    plots: list[str] | None = None,
    periods: set[str] | None = None,
    buckets: list[str] | None = None,
    period_types: set[str] | None = None,
) -> pd.DataFrame:
    """
    Sampling effort matching the filters, optionally narrowed further.

    Effort is keyed by (bucket, plot, period, period_type) so denominators can
    be restricted to a treatment period or exact treatment type the same way
    the detection numerator is. `period_types` is an exact-match restriction
    (used when grouping by Treat. type, where a plot's period_type changes
    over time) and is separate from the `treatment_components` filter, which
    matches on comma-split components rather than the full string.
    """
    e = data.effort
    sel = e[
        e["bucket"].isin(buckets if buckets is not None else visible_buckets(data, f))
        & e["plot"].isin(plots if plots is not None else eligible_plots(data, f))
    ]
    use = periods if periods is not None else allowed_periods(f)
    if use is not None:
        sel = sel[sel["period"].isin(use)]
    # The treatment-type filter is date-aware, so it applies to effort rows the
    # same way it applies to detection rows.
    sel = sel[component_mask(sel["period_type"], set(f.treatment_components))]
    if period_types is not None:
        sel = sel[sel["period_type"].isin(period_types)]
    return sel


def active_effort(data: Dataset, f: Filters) -> pd.DataFrame:
    """Sampling effort for exactly the buckets, plots and periods the filters allow."""
    return effort_rows(data, f)


def visible_buckets(data: Dataset, f: Filters) -> list[str]:
    b = data.buckets
    keep = b[
        b["bucket_sort"].floordiv(10).between(f.year_from, f.year_to)
        & b["season"].isin(f.seasons)
    ].sort_values("bucket_sort")
    return list(keep["bucket"])


# ----------------------------------------------------------------------- KPIs

# Two legitimate units for "a detection", both cached:
#   presence -> recs_detected : distinct recordings containing the species (0/1)
#   raw      -> n_detections  : every 3-second BirdNET detection window
# They disagree by ~12x overall and can even reorder species, because raw counts
# scale with how persistently a bird vocalises, not how widespread it is.
DETECTION_COL = "recs_detected"

METRIC_COLS = {"presence": "recs_detected", "raw": "n_detections"}
METRIC_LABELS = {"presence": "Species Presence", "raw": "Raw Detections"}
# "recordings with a detection" described the wrong quantity: presence sums a
# 0/1 flag per recording AND species, so a 10-minute file holding three species
# contributes three. At confidence 0.3 that is 23,394 against 12,837 distinct
# recordings with any detection at all — the label named the smaller number
# while the card showed the larger.
METRIC_UNITS = {
    "presence": "species detections in 10-min recordings",
    "raw": "3-second detection windows",
}


def metric_unit(data: Dataset, metric: str) -> str:
    """
    The active unit, with the length of a recording spelled out for presence.

    "Recordings with a detection" is only interpretable if you know how long a
    recording is — the same count would mean something very different over
    one-minute files. Raw detections already carry their window length, so only
    presence needs it. The figure is the scheduled cycle rather than the ~590 s
    of audio each file actually holds, because the schedule is what the survey
    was designed around; the methodology section carries that distinction.
    """
    if metric != "presence":
        return METRIC_UNITS[metric]
    minutes = int(data.meta.get("nominal_cycle_seconds", 600)) // 60
    return f"species detections in {minutes}-min recordings"


def metric_unit_short(data: Dataset, metric: str) -> str:
    """
    The same unit, trimmed for the KPI card.

    The card's own label already says Species Presence, so "with a detection"
    is repetition — and the long form wraps to a second line, which forces the
    six-card row to wrap to two rows.
    """
    if metric != "presence":
        return "3-sec detection windows"
    minutes = int(data.meta.get("nominal_cycle_seconds", 600)) // 60
    return f"species × {minutes}-min recording"


def detection_col(f: "Filters") -> str:
    return METRIC_COLS.get(f.metric, DETECTION_COL)


@dataclass
class Kpis:
    total_detections: int
    richness: int
    n_species_tracked: int
    active_plots: int
    n_preserves: int
    n_recordings: int
    hours_recorded: float
    top_code: str
    top_name: str
    has_data: bool


def compute_kpis(data: Dataset, f: Filters, rows: pd.DataFrame) -> Kpis:
    col = detection_col(f)
    total = int(rows[col].sum())
    per_species = (
        rows.groupby("species_code")[col].sum().sort_values(ascending=False)
    )
    per_species = per_species[per_species > 0]
    active = rows.loc[rows[col] > 0, "plot"]
    active_plots = int(active.nunique())
    # Preserves counted the same way as plots — those actually contributing a
    # detection, not those merely ticked in the filter. Reporting the selection
    # would leave the card unchanged while the map beneath it emptied out.
    n_preserves = int(
        data.plots.loc[data.plots["plot"].isin(set(active)), "preserve"].nunique()
    )
    top_code = per_species.index[0] if len(per_species) else "n/a"

    # Recording effort comes from the manifest-backed effort table, so it counts
    # every 10-minute file that was recorded — including files where nothing was
    # detected at any confidence. Hours are true audio duration, not
    # recordings x 10 min: the recorder captures 590 s per 600 s cycle, and 18
    # files are truncated.
    eff = active_effort(data, f)
    return Kpis(
        total_detections=total,
        richness=int(len(per_species)),
        n_species_tracked=len(data.species_codes),
        active_plots=active_plots,
        n_preserves=n_preserves,
        n_recordings=int(eff["recs_sampled"].sum()),
        hours_recorded=float(eff["audio_seconds"].sum()) / 3600,
        top_code=top_code,
        top_name=data.species_names.get(top_code, "n/a"),
        has_data=total > 0,
    )


# --------------------------------------------------------------- series build

def group_value(rows: pd.DataFrame, compare_by: str) -> pd.Series:
    if compare_by == "treatment_group":
        return rows["period"]          # date-aware, not the static plot label
    if compare_by == "treatment_type":
        return rows["period_type"]      # date-aware, not the static plot label
    if compare_by == "preserve":
        return rows["preserve"]
    if compare_by == "guild":
        return rows["guild"]
    return pd.Series("All selected", index=rows.index)


def group_color(compare_by: str, value: str, idx: int) -> str:
    """
    The line colour for one Compare-by series.

    Treatment period keeps its fixed control/pretreat/posttreat colours, which
    mean the same thing across every view. Everything else draws from
    GROUP_COLORS, which is long enough that no grouping has to reuse a colour.
    """
    if compare_by == "treatment_group":
        return TREATMENT_GROUP_COLORS.get(value, ACCENT)
    return GROUP_COLORS[idx % len(GROUP_COLORS)]


def group_order(rows: pd.DataFrame, compare_by: str) -> list[str]:
    if compare_by == "none":
        return ["All selected"]
    present = set(group_value(rows, compare_by).dropna())
    if compare_by == "treatment_group":
        return [g for g in TREATMENT_GROUP_ORDER if g in present]
    return sorted(present)


# Groupings that partition *plots*. treatment_group is absent on purpose: it is
# date-aware, so the same plot contributes to pretreat and posttreat in
# different seasons.
PLOT_ATTR_GROUPS = {
    "preserve": "preserve",
}


def group_plots(data: Dataset, f: Filters, key: str) -> list[str]:
    """
    Which selected plots belong to a comparison group.

    Needed for effort correction: the denominator must count every plot that was
    *sampled* in the group, including plots that recorded no detections at all.
    Deriving it from the detection rows alone would silently understate effort.
    Guild is a species attribute, not a plot attribute, so every selected plot
    contributes to a guild series.
    """
    sel = data.plots[data.plots["plot"].isin(eligible_plots(data, f))]
    attr = PLOT_ATTR_GROUPS.get(f.compare_by)
    if attr is None:
        return list(sel["plot"])
    return list(sel.loc[sel[attr] == key, "plot"])


def effort_denominator(
    data: Dataset,
    f: Filters,
    plots: list[str],
    buckets: list[str],
    periods: set[str] | None = None,
) -> pd.Series:
    """
    Sampling days per bucket for a set of plots, optionally one period only.

    The same distinct-dates union occupancy uses, so 'Per day' and the
    occupancy grids are normalised by one consistent notion of a survey day.
    """
    return sampling_days(data, f, plots, buckets, periods=periods).astype(float)


def build_series(
    data: Dataset, f: Filters, rows: pd.DataFrame, metric: str
) -> tuple[list[dict], list[str]]:
    """
    metric: 'detections' -> summed detection metric, 'richness' -> distinct species.

    With f.normalize == 'per_day', detection values are divided by the sampling
    days behind them, making buckets with very different survey effort
    comparable. Richness is a count of species and is never normalised.

    Returns (series, bucket_labels) where each series is
    {key, label, color, values, total}.
    """
    buckets = visible_buckets(data, f)
    col = detection_col(f)
    rows = rows.assign(_grp=group_value(rows, f.compare_by))
    keys = group_order(rows, f.compare_by)
    per_day = f.normalize == "per_day" and metric != "richness"

    series = []
    for i, key in enumerate(keys):
        sub = rows[rows["_grp"] == key] if f.compare_by != "none" else rows

        if metric == "richness":
            per_bucket = (
                sub[sub[col] > 0].groupby("bucket")["species_code"].nunique()
            )
            values = [float(per_bucket.get(b, 0)) for b in buckets]
            total_label = f"{int(max(values)) if values else 0} max"
        else:
            per_bucket = sub.groupby("bucket")[col].sum()
            raw = [float(per_bucket.get(b, 0)) for b in buckets]
            if per_day:
                denom = effort_denominator(
                    data, f, group_plots(data, f, key), buckets,
                    periods={key} if f.compare_by == "treatment_group" else None,
                )
                values = [
                    round(v / d, 2) if d else 0.0 for v, d in zip(raw, denom)
                ]
                tot_days = float(denom.sum())
                rate = (sum(raw) / tot_days) if tot_days else 0.0
                total_label = f"{rate:,.2f}/day"
            else:
                values = raw
                total_label = f"{int(sum(raw)):,}"

        series.append(
            {
                "key": key,
                "label": key,
                "color": group_color(f.compare_by, key, i),
                "values": values,
                "total": total_label,
            }
        )
    return series, buckets


def species_bars(data: Dataset, f: Filters, rows: pd.DataFrame) -> pd.DataFrame:
    col = detection_col(f)
    totals = rows.groupby("species_code")[col].sum()
    values = [float(totals.get(c, 0)) for c in data.species_codes]

    if f.normalize == "per_day":
        # Every species shares the same denominator here — total sampling days
        # across the selected plots and buckets — so this rescales rather than
        # reorders. It makes the magnitude readable as "detections per day".
        buckets = visible_buckets(data, f)
        days = float(
            effort_denominator(data, f, eligible_plots(data, f), buckets).sum()
        )
        values = [round(v / days, 2) if days else 0.0 for v in values]

    out = pd.DataFrame({"species_code": data.species_codes, "detections": values})
    out["name"] = out["species_code"].map(data.species_names)
    return out.sort_values("detections", ascending=False).reset_index(drop=True)


# The denominator each occupancy mode divides by. 'count' shares the daily
# denominator — it is the same sampling days, with a count of recordings on top
# instead of a count of days.
OCC_EFFORT_LABELS = {
    "daily": "Sampling days",
    "hourly": "Sampling hours",
    "count": "Sampling days",
}

# Occupancy saturates: a species only has to be heard at one plot to claim the
# day, so pooling plots pushes most cells to 100% and the grid stops
# discriminating. 'count' is the raw number of 10-minute recordings holding the
# species, which does not saturate — at Grovers in Summer 2022 four species
# share 100% occupancy while their counts run from 295 to 569.
OCC_MODES = ["daily", "hourly", "count"]
OCC_MODE_LABELS = {"daily": "Daily %", "hourly": "Hourly %", "count": "Count"}


def is_rate_mode(f: "Filters") -> bool:
    """Whether cells are an unbounded count rather than a bounded percentage."""
    return f.occ_granularity == "count"


def bucket_label_parts(data: Dataset) -> dict[str, tuple[str, str]]:
    """
    Season name and year(s) per bucket, for a two-line occupancy column header.

    "Su'22" compresses both facts into an abbreviation the reader has to decode;
    splitting it into "Summer" over "2022" reads directly. Winter spans a
    calendar boundary, so it keeps both years ("2024-25") rather than the single
    end-year the sort key uses internally.
    """
    parts: dict[str, tuple[str, str]] = {}
    for row in data.buckets.itertuples():
        season = str(row.season)
        years = str(row.year_season).replace(season, "").strip()
        if "-" in years:
            first, second = years.split("-", 1)
            years = f"{first}-{second[-2:]}"
        parts[row.bucket] = (season, years)
    return parts


def _occupancy_by_period(
    data: Dataset,
    f: Filters,
    rows: pd.DataFrame,
    codes: list[str],
    plots: list[str] | None = None,
) -> dict:
    """
    One grid whose columns are (bucket, period) pairs, ordered chronologically.

    This is the notebook's dual-period figure: a single heatmap divided into a
    pretreat section and a posttreat section, each with its own colour ramp,
    rather than two separate panels. Because treatment dates differ by plot, a
    season can appear under two periods when a multi-plot selection straddles
    the treatment; each such column is then shaded by its own period.

    `plots` lets a caller restrict this to a subset of the selection (e.g. one
    preserve at a time) while reusing the same chronological-column logic.
    """
    hourly = f.occ_granularity == "hourly"
    det_col = "rec_hours_detected" if hourly else "days_detected"
    eff_col = "rec_hours_sampled" if hourly else "days_sampled"

    buckets = visible_buckets(data, f)
    plots = plots if plots is not None else eligible_plots(data, f)
    effort = effort_rows(data, f, plots=plots, buckets=buckets)

    eff_by = effort.groupby(["bucket", "period"])[eff_col].sum()

    # Columns stay in chronological order and every visible season keeps a
    # column, so seasons with no sampling still show as NA rather than
    # disappearing. Colour alone carries the treatment period, which is why no
    # divider is needed. A season sampled under two periods (a multi-plot
    # selection straddling a treatment date) gets one column per period.
    columns = []
    for b in buckets:
        periods_here = [
            p for p in TREATMENT_GROUP_ORDER
            if (b, p) in eff_by.index and eff_by[(b, p)] > 0
        ]
        if not periods_here:
            columns.append({"bucket": b, "period": None, "label": b,
                            "ramp": "accent"})
            continue
        for p in periods_here:
            columns.append({
                "bucket": b,
                "period": p,
                "label": b,
                "ramp": p if p in RAMPS else "accent",
            })

    # Days detected and sampling days, both unioned across plots, per period.
    samp_by, det_by = {}, {}
    rate = is_rate_mode(f)
    if rate:
        by_period = rows.groupby(
            ["species_code", "bucket", "period"])["recs_detected"].sum()
    for p in {c["period"] for c in columns if c["period"]}:
        s = sampling_days(data, f, plots, buckets, periods={p}, hourly=hourly)
        for b in buckets:
            samp_by[(b, p)] = int(s[b])
        if rate:
            continue
        dd = days_detected(data, f, plots, buckets, codes, periods={p},
                           hourly=hourly)
        for (code, b), v in dd.items():
            det_by[(code, b, p)] = int(v)

    grid = pd.DataFrame(index=codes, columns=range(len(columns)), dtype=float)
    for ci, col in enumerate(columns):
        n = samp_by.get((col["bucket"], col["period"]), 0)
        for code in codes:
            key = (code, col["bucket"], col["period"])
            if n <= 0:
                grid.loc[code, ci] = float("nan")
            elif rate:
                grid.loc[code, ci] = float(by_period.get(key, 0.0))
            else:
                grid.loc[code, ci] = round(100 * det_by.get(key, 0) / n, 1)

    sampling = pd.Series(
        [float(samp_by.get((c["bucket"], c["period"]), 0)) for c in columns],
        index=range(len(columns)),
    )
    return {
        "key": "by_period",
        "label": None,
        "ramp": "accent",
        "columns": columns,
        "grid": grid,
        "sampling": sampling,
        "buckets": [c["label"] for c in columns],
        "n_plots": len(plots),
        "plot_names": sorted(plots),
        "split_by_period": True,
    }


def _occupancy_for(
    data: Dataset,
    f: Filters,
    rows: pd.DataFrame,
    plots: list[str],
    codes: list[str],
    period_types: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """
    Occupancy % for one set of plots and species.

    Days detected ÷ sampling days, both counted as distinct dates unioned over
    the selected plots — the definition used in the source notebook. A species
    claims a date if it was heard anywhere in the selection that day, and five
    recorders running the same sixteen dates is sixteen sampling days.

    A bucket with zero sampling effort yields NaN, not 0. Those are seasons that
    were never surveyed at the selected plots — reporting 0% there would read as
    "species absent" when the truth is "not looked for". `period_types`
    restricts the denominator to seasons actually recorded under an exact
    treatment type; without it, a plot's sampling days from every type it has
    ever carried would count toward each type's denominator, understating
    occupancy for periods that plot spent under a different type.
    """
    hourly = f.occ_granularity == "hourly"
    buckets = visible_buckets(data, f)

    denom = sampling_days(data, f, plots, buckets,
                          period_types=period_types, hourly=hourly)

    if is_rate_mode(f):
        # A plain count of 10-minute recordings containing the species, summed
        # over the selected plots. Not divided by anything — the sampling-days
        # row above the grid is what puts it in context.
        detected = rows.groupby(["species_code", "bucket"])["recs_detected"].sum()
    else:
        detected = days_detected(data, f, plots, buckets, codes,
                                 period_types=period_types, hourly=hourly)

    grid = pd.DataFrame(index=codes, columns=buckets, dtype=float)
    for code in codes:
        for b in buckets:
            n = int(denom.get(b, 0))
            if n <= 0:
                grid.loc[code, b] = float("nan")     # not surveyed
            elif is_rate_mode(f):
                grid.loc[code, b] = float(detected.get((code, b), 0))
            else:
                d = float(detected.get((code, b), 0))
                grid.loc[code, b] = round(100 * d / n, 1)

    sampling = pd.Series([float(denom.get(b, 0)) for b in buckets], index=buckets)
    return grid, sampling, buckets


def occupancy_grid(
    data: Dataset, f: Filters, rows: pd.DataFrame
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """
    Ungrouped occupancy.

    Daily  = sampling days a species was detected / days sampled.
    Hourly = recording-hours a species was detected / recording-hours sampled.
    """
    codes = [c for c in data.species_codes if c in set(f.species)]
    return _occupancy_for(data, f, rows, eligible_plots(data, f), codes)


def _occupancy_control_and_treatment(
    data: Dataset,
    f: Filters,
    rows: pd.DataFrame,
    codes: list[str],
    plots: list[str],
    preserve_label: str | None,
    treatment_ramp: str = "accent",
) -> list[dict]:
    """
    Split one plot set into up to two occupancy grids: control plots and
    treatment plots (pretreat/posttreat).

    Control isn't a treatment *period* the way pretreat/posttreat are — it's a
    permanently untreated reference plot, never scheduled for treatment.
    Folding its columns into the same chronological grid as pretreat/posttreat
    implied a timeline relationship between control and treatment that doesn't
    exist, so it gets its own grid instead.
    """
    buckets = visible_buckets(data, f)
    effort_all = effort_rows(data, f, plots=plots, buckets=buckets)
    plot_periods = effort_all.groupby("plot")["period"].apply(set)
    control_plots = sorted(p for p, s in plot_periods.items() if "control" in s)
    treat_plots = sorted(p for p, s in plot_periods.items() if s - {"control"})

    panels = []
    if treat_plots:
        sub_rows = rows[rows["plot"].isin(treat_plots)]
        panel = _occupancy_by_period(data, f, sub_rows, codes, plots=treat_plots)
        if panel["columns"]:
            panel["key"] = preserve_label or "treatment"
            panel["label"] = preserve_label
            panel["ramp"] = treatment_ramp
            panels.append(panel)

    if control_plots:
        sub_rows = rows[rows["plot"].isin(control_plots)]
        grid, sampling, blist = _occupancy_for(data, f, sub_rows, control_plots, codes)
        if blist:
            panels.append({
                "key": f"{preserve_label or 'all'}-control",
                "label": f"{preserve_label} · Control" if preserve_label else "Control",
                "ramp": "control",
                "columns": [
                    {"bucket": b, "period": "control", "label": b, "ramp": "control"}
                    for b in blist
                ],
                "grid": grid.set_axis(range(len(blist)), axis=1),
                "sampling": pd.Series(list(sampling), index=range(len(blist))),
                "buckets": blist,
                "n_plots": len(control_plots),
                "plot_names": sorted(control_plots),
                "split_by_period": False,
            })
    return panels


def occupancy_panels(
    data: Dataset, f: Filters, rows: pd.DataFrame
) -> list[dict]:
    """
    One heatmap panel per Compare-by group (a single panel when compare is off).

    Denominators are group-specific for plot-level groupings (treatment group,
    treatment type, preserve), because those genuinely partition the plots.
    Forage guild partitions *species*, not plots, so every guild panel shares the
    same sampling effort and differs only in which species rows it shows.
    """
    all_codes = [c for c in data.species_codes if c in set(f.species)]

    if f.compare_by == "none":
        sel_plots = eligible_plots(data, f)

        def _panel(grid, sampling, buckets, label, plots_in, key=None):
            return {
                "key": key, "label": label, "ramp": "accent",
                "columns": [{"bucket": b, "period": None, "label": b,
                             "ramp": "accent"} for b in buckets],
                "grid": grid.set_axis(range(len(buckets)), axis=1),
                "sampling": pd.Series(list(sampling), index=range(len(buckets))),
                "buckets": buckets,
                "n_plots": len(plots_in),
                "plot_names": sorted(plots_in),
                "split_by_period": False,
            }

        # Per-plot grids only once the selection has been narrowed. On the
        # default view — every preserve, every plot — they would be 40 grids
        # nobody asked for, below a combined grid that is the point of that
        # view. Choosing preserves or plots is the signal that someone wants
        # to look plot by plot.
        #
        # A single plot is excluded at the other end: the combined grid already
        # is that plot, so a second copy would say nothing new.
        narrowed = 1 < len(sel_plots) < len(data.all_plots)

        grid, sampling, buckets = occupancy_grid(data, f, rows)
        # Only headed when per-plot grids follow it; on its own it needs no
        # label, because the panel title above already names the selection.
        panels = [_panel(grid, sampling, buckets,
                         "All selected plots combined" if narrowed else None,
                         sel_plots)]

        # The combined grid unions dates across plots, so it saturates — a
        # species claims a day if any plot heard it, and most cells sit at
        # 100%. The per-plot grids are where the variation actually lives.
        if narrowed:
            preserve_of = dict(zip(data.plots["plot"], data.plots["preserve"]))
            codes = [c for c in data.species_codes if c in set(f.species)]
            for plot in sorted(sel_plots):
                sub = rows[rows["plot"] == plot]
                g1, s1, b1 = _occupancy_for(data, f, sub, [plot], codes)
                if not b1:
                    continue
                panels.append(_panel(
                    g1, s1, b1,
                    f"{preserve_of.get(plot, '')} / {plot}".lstrip(" /"),
                    [plot], key=plot))
        return panels

    # Treatment group divides the columns of one grid by era, matching the
    # notebook, instead of producing separate panels.
    #
    # Which plots share a grid is the question. Pooling them hides the thing
    # the comparison exists to show: treatment dates differ by plot, so a
    # pooled pretreat column mixes plots that were treated years apart, and a
    # plot's own before/after is exactly what a reader wants to line up. So
    # once the selection is narrowed, every plot gets its own dual-period grid
    # — control plots included, which then show a single control-coloured run
    # because they have no other era.
    #
    # The unnarrowed case keeps the per-preserve faceting: 40 individual grids
    # is not a view anyone asked for, and the preserve-level split at least
    # stays readable.
    if f.compare_by == "treatment_group":
        all_plots = eligible_plots(data, f)
        preserve_of = dict(zip(data.plots["plot"], data.plots["preserve"]))

        if len(all_plots) < len(data.all_plots):
            panels = []
            for plot in sorted(all_plots):
                sub = rows[rows["plot"] == plot]
                panel = _occupancy_by_period(data, f, sub, all_codes,
                                             plots=[plot])
                if not panel["columns"]:
                    continue
                panel["key"] = plot
                panel["label"] = (
                    f"{preserve_of.get(plot, '')} / {plot}".lstrip(" /")
                    if len(all_plots) > 1 else None)
                panels.append(panel)
            return panels

        preserves = sorted({preserve_of.get(p, "") for p in all_plots})
        panels = []
        for i, preserve in enumerate(preserves):
            plot_list = list(data.plots.loc[
                data.plots["plot"].isin(all_plots)
                & (data.plots["preserve"] == preserve),
                "plot",
            ])
            sub_rows = rows[rows["preserve"] == preserve]
            panels.extend(_occupancy_control_and_treatment(
                data, f, sub_rows, all_codes, plot_list,
                preserve_label=preserve,
                treatment_ramp=ramp_for("preserve", preserve, i),
            ))
        return panels

    grouped = rows.assign(_grp=group_value(rows, f.compare_by))
    keys = group_order(rows, f.compare_by)
    all_codes = [c for c in data.species_codes if c in set(f.species)]

    panels = []
    for i, key in enumerate(keys):
        sub = grouped[grouped["_grp"] == key]
        period_types = None
        if f.compare_by in PLOT_ATTR_GROUPS:
            plots = group_plots(data, f, key)
            codes = all_codes
        elif f.compare_by == "treatment_type":
            # Treatment type, like treatment group, is date-aware: a plot's
            # rows can carry different period_type values over time. The
            # denominator for one type must only count sampling days actually
            # recorded under that exact type, otherwise seasons a plot spent
            # under a different type read as "detected 0%" instead of the
            # true "not sampled under this type" (NA).
            plots = eligible_plots(data, f)
            codes = all_codes
            period_types = {key}
        else:
            plots = eligible_plots(data, f)
            codes = [c for c in all_codes if c in set(sub["species_code"])]
        if not codes or not plots:
            continue
        grid, sampling, buckets = _occupancy_for(
            data, f, sub, plots, codes, period_types=period_types
        )
        ramp = ramp_for(f.compare_by, str(key), i)
        group_names = sorted(plots)
        if period_types is not None:
            # Treatment type is date-aware, so a panel's plots are those that
            # actually recorded under that type, not the whole selection.
            group_names = sorted(effort_rows(
                data, f, plots=plots, buckets=buckets, period_types=period_types
            )["plot"].unique())
        n_plots = len(group_names)

        # A blank cell has two different meanings in a treatment-type panel and
        # they must not look alike. Outside this type's era the season belongs
        # to a *different* panel (GCP-A's pre-treatment seasons live in the
        # 'none' grid), so there is nothing to report here at all. Inside the
        # era, a blank means the season genuinely was not surveyed — that is
        # NA, and it sits alongside real 0% cells where the species was looked
        # for and not found. The era spans the first through last season this
        # type was actually recorded, so unsurveyed seasons in between stay NA.
        in_era = [True] * len(buckets)
        if period_types is not None:
            sampled = [ci for ci in range(len(buckets)) if float(sampling.iloc[ci]) > 0]
            if sampled:
                first, last = sampled[0], sampled[-1]
                in_era = [first <= ci <= last for ci in range(len(buckets))]

        panels.append({
            "key": key,
            "label": str(key),
            "ramp": ramp,
            "columns": [{"bucket": b, "period": None, "label": b, "ramp": ramp,
                         "in_era": in_era[ci]}
                        for ci, b in enumerate(buckets)],
            "grid": grid.set_axis(range(len(buckets)), axis=1),
            "sampling": pd.Series(list(sampling), index=range(len(buckets))),
            "buckets": buckets,
            "n_plots": n_plots,
            "plot_names": group_names,
            "split_by_period": False,
        })
    return panels



def region_nodes(data: Dataset, f: Filters, rows: pd.DataFrame) -> pd.DataFrame:
    """One row per selected plot: coordinates plus species richness at that plot."""
    rich = (
        rows[rows[detection_col(f)] > 0]
        .groupby("plot")["species_code"]
        .nunique()
    )
    det = rows.groupby("plot")[detection_col(f)].sum()
    sel = data.plots[data.plots["plot"].isin(eligible_plots(data, f))].copy()
    sel["richness"] = sel["plot"].map(rich).fillna(0).astype(int)
    sel["detections"] = sel["plot"].map(det).fillna(0).astype(int)
    sel["n_selected_species"] = max(1, len(f.species))
    sel["share"] = sel["richness"] / sel["n_selected_species"]
    return sel.reset_index(drop=True)


# Distinct hues for per-species map bubbles. Every one is dark enough to hold
# its own against the basemap's roads and labels — the earlier yellow washed out
# completely over pale terrain — and they stay clear of the occupancy period
# ramps so a colour never means two things at once across views.
# One colour per hue family — red, blue, gold, magenta, purple, orange, cyan,
# brown — so every species reads as a nameable primary or secondary rather than
# a shade someone has to match against a key.
#
# Two families are excluded outright. Green, because the basemap is full of it
# (the Olympic National Forest fills a quarter of the frame) and a green bubble
# competes with the terrain rather than sitting on it. And anything dark or
# desaturated enough to read as grey or near-black, because that is the
# AudioMoth dot: every colour here is at least dE 60 from black.
#
# Those constraints cost some separation (worst pair dE 14.3, against 17.7 when
# navy and green were allowed) but a colour the eye cannot find on the map is
# worse than one it can only just tell from its neighbour.
#
# The exact shade within each family is not arbitrary: it is chosen by
# simulating protanopia, deuteranopia and tritanopia and maximising the closest
# pair across all three plus normal vision (worst pair dE 17.7). Naive full
# saturation is much worse — a textbook primary set collapses to dE 6.3, where
# blue and purple are indistinguishable to a protanope. Forcing hue variety and
# then optimising the shades keeps both properties.
#
# Ordered so neighbours are the furthest apart (dE 42.5): species take these in
# alphabetical order and so land side by side in the legend and in the sorted
# bar chart, where confusable neighbours would be the most misleading.
SPECIES_COLORS = [
    "#CC2200",   # red
    "#0044CC",   # blue
    "#F0B400",   # gold
    "#E5308F",   # magenta
    "#7B3FBF",   # purple
    "#E36C09",   # orange
    "#00A5B5",   # cyan
    "#A0522D",   # brown
]

# Drawn at the AudioMoth's true position, under the fanned species bubbles.
RECORDER_DOT = "#000000"


def species_color(idx: int) -> str:
    return SPECIES_COLORS[idx % len(SPECIES_COLORS)]


def species_rank(data: Dataset) -> list[str]:
    """
    Species ordered by total detections across the whole dataset, commonest
    first.

    Colours and map draw order both key off this rather than off the
    alphabetical species list. Alphabetically, WIWA came last and so was
    painted over everything else — on the map it looked like the dominant
    species when it is only the fifth most detected.

    Deliberately computed from the full dataset rather than from the current
    filters: a species must not change colour when a filter moves, and the map
    frames must keep one fixed trace order or Plotly cannot hold the zoom.
    """
    d = data.detections
    if d.empty:
        return list(data.species_codes)
    base = d[d["threshold"] == min(data.meta["thresholds"])]
    totals = base.groupby("species_code")["recs_detected"].sum()
    return sorted(data.species_codes,
                  key=lambda c: (-float(totals.get(c, 0)), c))


def species_colors_by_rank(data: Dataset) -> dict[str, str]:
    """Map each species to its colour, commonest species taking the first."""
    return {code: species_color(i) for i, code in enumerate(species_rank(data))}


METERS_PER_DEG_LAT = 111_320.0


def _dispersal_radius_m(plots: pd.DataFrame) -> float:
    """
    How far to fan a plot's species bubbles from the recorder's true position.

    Every species at a plot shares one coordinate — the recorder's — so drawn
    honestly they stack into a single dot. Fanning them apart has to stay small
    enough that a plot's ring can never be mistaken for its neighbour's, so the
    radius is a quarter of the closest spacing between any two plots in the
    dataset (92 m apart at the tightest, GCP-C/GCP-D) rather than a fixed guess.
    """
    pts = plots[["latitude", "longitude"]].dropna().to_numpy(dtype=float)
    if len(pts) < 2:
        return 20.0
    best = float("inf")
    for i in range(len(pts)):
        lat_i, lon_i = pts[i]
        scale = math.cos(math.radians(lat_i))
        for j in range(i + 1, len(pts)):
            lat_j, lon_j = pts[j]
            dy = (lat_j - lat_i) * METERS_PER_DEG_LAT
            dx = (lon_j - lon_i) * METERS_PER_DEG_LAT * scale
            best = min(best, math.hypot(dx, dy))
    return max(5.0, min(25.0, 0.25 * best))


def region_sites(data: Dataset, f: Filters) -> pd.DataFrame:
    """
    Every selected plot's recorder position, regardless of the map's slicers.

    Deliberately independent of the season and hour sliders: these anchor the
    map's framing and its AudioMoth dots, so a season with no recordings shows
    an unchanged map with no bubbles rather than an empty panel. Recomputing
    this per slice would also make the figure's shape change under the user and
    throw away their zoom.
    """
    sel = data.plots[data.plots["plot"].isin(eligible_plots(data, f))]
    return sel[["plot", "preserve", "latitude", "longitude"]].reset_index(drop=True)


def region_species_nodes(
    data: Dataset, f: Filters, rows: pd.DataFrame
) -> pd.DataFrame:
    """
    One row per (plot, species): coordinates plus that species' occupancy at
    that plot over the selected year range.

    Occupancy is used rather than a detection count for the same reason the
    heatmaps use it — sampling effort varies several-fold between plots, so raw
    counts would size the bubbles by how long a recorder ran rather than by how
    consistently the bird was there. A plot with no sampling in range yields no
    rows at all instead of a zero-radius bubble.

    The definition comes from sampling_days/days_detected, the same pair the
    heatmap uses, so there is one definition of occupancy in one place. Each
    bubble is a single plot, so the union those functions take across plots
    collapses to that plot's own dates — which is why the map's numbers were
    already right before the heatmap was corrected, and why they do not move
    now. Seasons are pooled here rather than split into columns.
    """
    plots = eligible_plots(data, f)
    buckets = visible_buckets(data, f)
    if f.region_bucket:
        buckets = [b for b in buckets if b == f.region_bucket]

    hours = list(f.region_hours) or data.hours
    solar = list(f.region_solar)
    hourly = (f.occ_granularity == "hourly" or bool(f.region_hours)
              or bool(solar))

    codes = [c for c in data.species_codes if c in set(f.species)]

    if solar or f.region_hours:
        # A time-of-day slice needs the time-keyed tables, which carry the same
        # slots keyed by hour; counting distinct rows there is the same union.
        if solar:
            eff_tbl = _solar_effort_rows(data, f, plots, buckets, solar)
            det_tbl = _solar_detection_rows(data, f, plots, buckets, solar)
        else:
            eff_tbl = _hour_effort_rows(data, f, plots, buckets, hours)
            det_tbl = _hour_detection_rows(data, f, plots, buckets, hours)
        eff_col = "rec_hours_sampled" if hourly else "days_sampled"
        det_col = "rec_hours_detected" if hourly else "days_detected"
        denom = eff_tbl.groupby("plot")[eff_col].sum()
        detected = det_tbl.groupby(["plot", "species_code"])[det_col].sum()
    else:
        denom_by, det_by = {}, {}
        for p in plots:
            denom_by[p] = float(
                sampling_days(data, f, [p], buckets, hourly=hourly).sum())
            # Accumulate rather than comprehend: a species appears once per
            # bucket, and the map pools buckets, so the per-bucket counts must
            # be summed instead of overwriting each other.
            for (c, _b), v in days_detected(data, f, [p], buckets, codes,
                                            hourly=hourly).items():
                det_by[(p, c)] = det_by.get((p, c), 0) + int(v)
        denom = pd.Series(denom_by, dtype=float)
        detected = pd.Series(det_by, dtype=float)
    coords = data.plots.set_index("plot")

    # Fan the species evenly around the recorder's position. The angle depends
    # only on the species' index, so a species keeps the same clock position at
    # every plot and the eye can track it across the map.
    radius_m = _dispersal_radius_m(data.plots)
    n_codes = max(1, len(codes))
    rank_colors = species_colors_by_rank(data)

    recs = []
    for plot in plots:
        n = float(denom.get(plot, 0.0))
        if n <= 0 or plot not in coords.index:
            continue                      # not surveyed in range: nothing to plot
        row = coords.loc[plot]
        lat0, lon0 = float(row["latitude"]), float(row["longitude"])
        lon_scale = METERS_PER_DEG_LAT * max(0.1, math.cos(math.radians(lat0)))
        for i, code in enumerate(codes):
            if n_codes == 1:
                dlat = dlon = 0.0  # nothing to fan against
            else:
                angle = 2 * math.pi * i / n_codes
                dlat = radius_m * math.sin(angle) / METERS_PER_DEG_LAT
                dlon = radius_m * math.cos(angle) / lon_scale
            d = float(detected.get((plot, code), 0.0))
            recs.append({
                "plot": plot,
                "preserve": row["preserve"],
                "latitude": lat0 + dlat,
                "longitude": lon0 + dlon,
                "plot_latitude": lat0,
                "plot_longitude": lon0,
                "species_code": code,
                "name": data.species_names.get(code, code),
                "color": rank_colors.get(code, species_color(i)),
                "occupancy_pct": round(100 * d / n, 1),
                "effort_sampled": n,
            })
    return pd.DataFrame(recs, columns=[
        "plot", "preserve", "latitude", "longitude",
        "plot_latitude", "plot_longitude", "species_code", "name",
        "color", "occupancy_pct", "effort_sampled",
    ])


# --------------------------------------------------------------------- export

# Exports mirror Combined_BirdNET_Results.csv: same column names, same order —
# site block, then time block, then species block, then the measures. The point
# is that a downloaded file drops into whatever already reads the source table,
# and that a reader does not have to learn a second vocabulary.
#
# Two columns from the source are deliberately absent. `rec`, `datetime`,
# `birdnet_start_s` and the like are properties of one 3-second detection,
# whereas these rows are seasonal aggregates over many. And `confidence` is a
# per-detection score; the threshold that produced the aggregate is carried as
# `confidence_threshold` instead.
SITE_FIELDS = ["preserve", "plot", "treatment_group", "treatment_type",
               "latitude", "longitude", "elevation"]
TIME_FIELDS = ["season_period_year", "season", "year_season"]
SPECIES_FIELDS = ["species", "species_code", "forage_guilds"]
SCOPE_FIELDS = ["n_plots", "preserves_included", "plots_included"]
LOCATION_FIELDS = SITE_FIELDS + SCOPE_FIELDS


def location_columns(data: Dataset, plots: list[str],
                     bucket: str | None = None) -> dict:
    """
    The site block for a row, in the source table's column names.

    Fields that are only meaningful for one site are filled only for one site:
    a mean latitude across plots is a place no recorder ever stood, and a
    pooled row has no single treatment. `plots_included` always carries the
    full membership, so nothing is lost to those blanks.
    """
    plots = sorted(plots)
    tbl = data.plots.set_index("plot")
    preserves = sorted({
        p for p in data.plots.loc[data.plots["plot"].isin(plots), "preserve"]
    })
    one = plots[0] if len(plots) == 1 and plots[0] in tbl.index else ""

    group = ptype = ""
    if one and bucket:
        # Treatment is date-aware, so it is read for this plot in this season
        # rather than from the plot's static label.
        d = data.dates
        sub = d[(d["plot"] == one) & (d["bucket"] == bucket)]
        if not sub.empty:
            gs = sorted(set(sub["period"].dropna()))
            ts = sorted(set(sub["period_type"].dropna()))
            group = gs[0] if len(gs) == 1 else "|".join(gs)
            ptype = ts[0] if len(ts) == 1 else "|".join(ts)

    return {
        "preserve": preserves[0] if len(preserves) == 1 else "",
        "plot": one,
        "treatment_group": group,
        "treatment_type": ptype,
        "latitude": float(tbl.loc[one, "latitude"]) if one else "",
        "longitude": float(tbl.loc[one, "longitude"]) if one else "",
        "elevation": (float(tbl.loc[one, "elevation"])
                      if one and "elevation" in tbl.columns else ""),
        "n_plots": len(plots),
        "preserves_included": "|".join(preserves),
        "plots_included": "|".join(plots),
    }


def time_columns(data: Dataset, bucket: str) -> dict:
    """The time block for a bucket, named as the source table names it."""
    for b in data.meta["buckets"]:
        if b["bucket"] == bucket:
            return {"season_period_year": b["season_period_year"],
                    "season": b["season"], "year_season": b["year_season"]}
    return {"season_period_year": "", "season": "", "year_season": bucket}


def species_columns(data: Dataset, code: str) -> dict:
    """The species block: scientific name, code and guild, as in the source."""
    for s in data.species:
        if s["code"] == code:
            return {"species": s.get("scientific", ""), "species_code": code,
                    "forage_guilds": s.get("guild", "")}
    return {"species": "", "species_code": code, "forage_guilds": ""}


def export_csv(data: Dataset, f: Filters, rows: pd.DataFrame) -> bytes:
    """Export exactly what the active view shows, matching the design's shapes."""
    buf = io.StringIO()
    view = f.graph_type
    where = location_columns(data, eligible_plots(data, f))

    # Exports carry the unit so a downloaded file is never ambiguous about
    # whether its numbers are raw windows, presence, or a per-day rate.
    unit = f"{f.metric}_per_day" if f.normalize == "per_day" else f.metric

    head = SITE_FIELDS + TIME_FIELDS + SPECIES_FIELDS + SCOPE_FIELDS

    if view == "trends":
        # No species dimension: the series is a total over the selection, so
        # the species block is left empty rather than invented.
        series, buckets = build_series(data, f, rows, "detections")
        recs = [
            {**where, **time_columns(data, b),
             "species": "", "species_code": "", "forage_guilds": "",
             "group": s["label"], "detections": v, "unit": unit,
             "confidence_threshold": f.confidence}
            for s in series
            for b, v in zip(buckets, s["values"])
        ]
        pd.DataFrame(recs, columns=head + ["group", "detections", "unit",
                                           "confidence_threshold"]
                     ).to_csv(buf, index=False)
    elif view == "species":
        # Ranked over the whole selected range, so the time block spans it.
        span = {"season_period_year": "", "season": "|".join(f.seasons),
                "year_season": f"{f.year_from}-{f.year_to}"}
        recs = [
            {**where, **span, **species_columns(data, r.species_code),
             "detections": r.detections, "unit": unit,
             "confidence_threshold": f.confidence}
            for r in species_bars(data, f, rows).itertuples()
        ]
        pd.DataFrame(recs, columns=head + ["detections", "unit",
                                           "confidence_threshold"]
                     ).to_csv(buf, index=False)
    elif view == "occupancy":
        rate = is_rate_mode(f)
        eff_name = ("sampling_hours" if f.occ_granularity == "hourly"
                    else "sampling_days")
        recs = []
        for panel in occupancy_panels(data, f, rows):
            grid, sampling = panel["grid"], panel["sampling"]
            panel_plots = panel.get("plot_names") or eligible_plots(data, f)
            for code in grid.index:
                sp = species_columns(data, code)
                for ci, col in enumerate(panel["columns"]):
                    v = grid.loc[code, ci]
                    eff = int(sampling.get(ci, 0))
                    blank = pd.isna(v)
                    recs.append({
                        # Each grid names its own site, so a per-plot panel
                        # exports that plot's coordinates and its treatment in
                        # that season, while a pooled one lists its members.
                        **location_columns(data, panel_plots, col["bucket"]),
                        **time_columns(data, col["bucket"]),
                        **sp,
                        "group": panel["label"] or "All selected",
                        "period": col["period"] or "",
                        # Empty rather than 0 so "not surveyed" survives export.
                        "detections": ("" if blank or not rate else int(v)),
                        "days_detected": ("" if blank or rate
                                          else int(round(v * eff / 100))),
                        eff_name: eff,
                        "occupancy_pct": "" if blank or rate else v,
                        "measure": "detections" if rate else "occupancy_pct",
                        "confidence_threshold": f.confidence,
                    })
        pd.DataFrame(recs, columns=head + [
            "group", "period", "detections", "days_detected", eff_name,
            "occupancy_pct", "measure", "confidence_threshold"]
        ).to_csv(buf, index=False)
    else:
        # Matches the map: one row per bubble, carrying the occupancy that sized
        # it and the effort behind that occupancy.
        nodes = region_species_nodes(data, f, rows)
        tbl = data.plots.set_index("plot")
        span = {"season_period_year": "",
                "season": f.region_bucket or "|".join(f.seasons),
                "year_season": f.region_bucket or f"{f.year_from}-{f.year_to}"}
        eff_name = ("sampling_hours" if f.occ_granularity == "hourly"
                    else "sampling_days")
        recs = []
        for r in nodes.itertuples():
            recs.append({
                # One row per plot already, so the site block is fully
                # determined. Coordinates are the recorder's real position,
                # not the fanned-out drawing position used on the map.
                "preserve": r.preserve, "plot": r.plot,
                "treatment_group": tbl.loc[r.plot, "treatment_group"],
                "treatment_type": tbl.loc[r.plot, "treatment_type"],
                "latitude": r.plot_latitude, "longitude": r.plot_longitude,
                "elevation": (float(tbl.loc[r.plot, "elevation"])
                              if "elevation" in tbl.columns else ""),
                **span,
                **species_columns(data, r.species_code),
                "n_plots": 1, "preserves_included": r.preserve,
                "plots_included": r.plot,
                "occupancy_pct": r.occupancy_pct,
                eff_name: r.effort_sampled,
                "confidence_threshold": f.confidence,
            })
        pd.DataFrame(recs, columns=head + [
            "occupancy_pct", eff_name, "confidence_threshold"]
        ).to_csv(buf, index=False)

    return buf.getvalue().encode("utf-8")


def methodology(data: Dataset) -> list[tuple[str, list[tuple[str, str]]]]:
    """
    Definitions for every control and derived number in the dashboard.

    Built from the dataset and the same constants the charts use, rather than
    written out by hand, so the page cannot drift from what the code computes:
    the counts below are recomputed on load.
    """
    raw_by_t, pres_by_t = {}, {}
    for t in data.meta["thresholds"]:
        sub = data.detections[data.detections["threshold"] == t]
        raw_by_t[t] = int(sub["n_detections"].sum())
        pres_by_t[t] = int(sub["recs_detected"].sum())

    t0 = 0.3 if 0.3 in raw_by_t else data.meta["thresholds"][0]
    ratio = raw_by_t[t0] / max(pres_by_t[t0], 1)
    distinct_by_t = {float(k): int(v) for k, v in
                     data.meta.get("recordings_with_detection", {}).items()}

    days = data.effort.groupby("bucket")["days_sampled"].sum()
    n_both = len(data.meta.get("plots_with_both_periods", []))
    nominal = data.meta.get("nominal_cycle_seconds", 600)
    typical = data.meta.get("typical_recording_seconds", 590)
    hrs = data.hours

    return [
        ("Detection unit — what counts as one detection", [
            (
                "Species Presence",
                "One species detected in one recording, counted 0/1. A bird "
                "heard forty times in a ten-minute file counts once — but a "
                "file holding three species contributes three, because the "
                "flag is per recording AND species. At confidence "
                f"{t0} this totals {pres_by_t[t0]:,}. It is the default, "
                "because it measures how widespread a species is rather than "
                "how much it sang.",
            ),
            (
                "Not the same as recordings with a detection",
                f"{pres_by_t[t0]:,} species detections come from "
                f"{distinct_by_t.get(t0, 0):,} distinct recordings — about "
                f"{pres_by_t[t0] / max(distinct_by_t.get(t0, 1), 1):.1f} "
                "species per recording that has any detection at all. If you "
                "want 'how many of my files caught something', that is the "
                "smaller number; the card reports the larger because occupancy "
                "and the species ranking are both per species.",
            ),
            (
                "Raw detections",
                "Every three-second BirdNET detection window, counted "
                f"separately — {raw_by_t[t0]:,} at confidence {t0}, about "
                f"{ratio:.0f}x the presence figure. It scales with how "
                "persistently a bird vocalises, not how widely it occurs, so "
                "it can reorder the species ranking. Useful for calling "
                "intensity; misleading as a measure of distribution.",
            ),
        ]),
        ("Scale — whether the count is divided by effort", [
            (
                "Total",
                "The summed count over whatever is selected, uncorrected. "
                "Seasons were surveyed for very different numbers of days, so "
                "a total is comparable only where effort is comparable — "
                "otherwise it partly measures how long the recorders ran.",
            ),
            (
                "Per day",
                "The same count divided by the sampling days behind it, which "
                "removes that. Species richness is never normalised, being a "
                "count of species rather than of detections.",
            ),
            (
                "Where it applies",
                "Trends and Species only. Occupancy is a ratio already, so it "
                "is effort-corrected whatever this is set to, and the Region "
                "map sizes its bubbles the same way.",
            ),
        ]),
        ("Occupancy — the effort-corrected measure used by the heatmaps and maps", [
            (
                "Sampling days",
                "Distinct calendar dates on which any selected plot recorded. "
                "The union across plots, not the sum: five recorders running "
                "the same sixteen dates is sixteen sampling days. This is what "
                "makes effort comparable between seasons and years, which vary "
                "several-fold in how long they were surveyed.",
            ),
            (
                "Days detected",
                "Distinct calendar dates on which the species was flagged at "
                "any selected plot. Counted the same way as the denominator: a "
                "species claims a date if it was heard somewhere in the "
                "selection, however many recordings caught it.",
            ),
            (
                "Daily occupancy (%)",
                "Days detected ÷ sampling days × 100. Grovers in Summer 2022: "
                "BEWR was heard on 14 of the 16 dates surveyed, so 87.5%.",
            ),
            (
                "Hourly occupancy (%)",
                "The same, with the unit a distinct (date, clock-hour) rather "
                "than a date. Finer-grained, and the basis for the "
                "sunrise-relative analysis.",
            ),
            (
                "It rises as you add plots",
                "A species only has to be heard at one plot to claim the day, "
                "so pooling more plots pushes occupancy up — most species read "
                "100% across all 40. Compare like with like: one plot against "
                "itself over time, or one preserve against another.",
            ),
            (
                "Why occupancy rather than counts",
                "Both are ratios, so a plot recorded for nine days and one "
                "recorded for ninety are directly comparable. This is why the "
                "map sizes bubbles by occupancy rather than detections.",
            ),
            (
                "NA versus 0%",
                "0% means the species was looked for and not found. NA means "
                "there was no sampling effort at all — the two are shaded "
                "differently and never conflated. In the Treat. type panels a "
                "third, flatter shade marks seasons belonging to a different "
                "treatment period entirely.",
            ),
        ]),
        ("Confidence threshold", [
            (
                "What it does",
                "Keeps only BirdNET detections scoring at or above the chosen "
                "value, recomputed per row from the raw detection table rather "
                "than read from a precomputed flag. Raising it trades recall "
                "for precision: "
                + ", ".join(
                    f"{t} gives {pres_by_t[t]:,} presence detections"
                    for t in sorted(raw_by_t)
                )
                + ".",
            ),
            (
                "Default of 0.3",
                "BirdNET's own reporting floor and the threshold used in the "
                "source notebook, so the dashboard opens on the same basis as "
                "the written analysis.",
            ),
        ]),
        ("Header figures — effort and coverage", [
            (
                "Number of recordings",
                f"{data.meta['n_recordings']:,} audio files across "
                f"{len(data.all_plots)} plots and {len(data.preserves)} "
                "preserves, counted from the recording manifest so files "
                "containing no detection at all are still counted as effort.",
            ),
            (
                "What the effort cards respond to",
                "Recordings and Hours recorded follow the plot, preserve, "
                "season, year and treatment filters, but deliberately not "
                "species or confidence: a recorder ran for the same time "
                "whichever species you later ask about. They are also the "
                "denominator every occupancy figure divides by, so shrinking "
                "them per species would make occupancy meaningless. For "
                "'recordings containing this species', read Species Presence.",
            ),
            (
                "Hours recorded",
                f"{data.meta.get('total_audio_hours', 0):,} hours of actual "
                f"audio. Recorders were scheduled on a {nominal // 60}-minute "
                f"cycle but each file is about {typical} seconds, so duration "
                "is derived from file size rather than assumed "
                f"({data.meta.get('n_truncated_recordings', 0)} files are "
                "shorter still and are counted at their true length).",
            ),
            (
                "Time of day",
                "Recording runs "
                + (f"{hrs[0]}:00–{hrs[-1] + 1}:00" if hrs else "n/a")
                + " Pacific, a dawn-chorus window rather than a full day. A "
                "file stamped 9:40 ends about 9:50, which is why the clock "
                "axis extends one hour past the last start time.",
            ),
            (
                "Hours from sunrise",
                "The Region map's time scrubber is measured from sunrise, not "
                "from the clock. Sunrise is computed for each plot on each "
                "date from its latitude and longitude, so bin 0 means the hour "
                "beginning at dawn wherever and whenever it falls. Clock hour "
                "cannot be compared across seasons here: dawn moves nearly "
                "three hours between June and December and the recorders "
                "followed it, so on a clock axis 4-6 AM is summer-only and "
                "8-9 AM mostly winter — 'time of day' would quietly mean "
                "'season'. On the sunrise axis all three seasons overlap.",
            ),
            (
                "Species richness",
                f"How many of the {len(data.species_codes)} tracked species "
                "were detected at least once under the current filters. A "
                "count of species, so it is never normalised by effort — but "
                "it does rise with effort, since more listening finds more "
                "species.",
            ),
            (
                "Preserves and Plots",
                f"How much of the {len(data.preserves)}-preserve, "
                f"{len(data.all_plots)}-plot network actually produced a "
                "detection under the current filters — not how much is ticked "
                "in the sidebar. Raising the confidence threshold or narrowing "
                "to one species will drop silent plots out of these counts, "
                "which is the point: they show reach, not selection.",
            ),
        ]),
        ("Treatment group and treatment type", [
            (
                "Both are date-aware",
                "A plot is pre-treatment before its treatment date and "
                "post-treatment after it, so the same plot contributes to both "
                f"periods in different seasons. {n_both} plots were treated "
                "partway through monitoring. Treatment type changes with it — "
                "'none' beforehand, the actual activities afterwards. Static "
                "per-plot labels would misattribute both.",
            ),
            (
                "Control",
                "Plots never scheduled for treatment. Control is a reference "
                "condition, not a point on the pre/post timeline, so it is "
                "drawn as its own grid rather than as a third era.",
            ),
        ]),
    ]


def export_filename(data: Dataset, f: Filters) -> str:
    """
    A filename that says what the export actually contains.

    Every download used to be 'birdnet_occupancy_export.csv', so a folder of
    them was indistinguishable and the browser appended (1), (2), (3). This
    names the view, the scope and the threshold.
    """
    parts = ["birdnet", f.graph_type]
    if f.graph_type == "occupancy":
        parts.append(f.occ_granularity)

    plots = eligible_plots(data, f)
    preserves = sorted({
        p for p in data.plots.loc[data.plots["plot"].isin(plots), "preserve"]
    })
    if len(plots) == 1:
        parts.append(plots[0])
    elif len(plots) == len(data.all_plots):
        parts.append("all-plots")
    elif len(preserves) == 1:
        parts.append(preserves[0])
    else:
        parts.append(f"{len(plots)}plots")

    # Time scope, but only when narrowed — otherwise every name carries the
    # full year range and the useful part gets lost in it.
    if f.year_from == f.year_to:
        parts.append(str(f.year_from))
    elif (f.year_from, f.year_to) != (min(data.years), max(data.years)):
        parts.append(f"{f.year_from}-{f.year_to}")
    if len(f.seasons) < len(data.seasons):
        parts.append("-".join(s[:2] for s in f.seasons))

    if len(f.species) == 1:
        parts.append(f.species[0])
    parts.append(f"conf{f.confidence}")

    safe = "_".join(str(p).replace(" ", "-").replace("/", "-") for p in parts)
    return f"{safe}.csv"


def view_state_json(f: Filters) -> str:
    """
    The current view as JSON.

    Nothing in the app calls this: it backed a 'Copy view link' button that
    printed the state but could not restore it. Kept because it is the natural
    starting point for a real shareable view — serialise this into
    st.query_params on change, parse it back on load — and because it is the
    one place that enumerates every field a saved view would need.
    """
    return json.dumps(
        {
            "graphType": f.graph_type,
            "compareBy": f.compare_by,
            "confidence": f.confidence,
            "yearFrom": f.year_from,
            "yearTo": f.year_to,
            "seasons": list(f.seasons),
            "species": list(f.species),
            "preserves": list(f.preserves),
            "plots": list(f.plots),
            "treatmentPeriods": list(f.treatment_periods),
            "treatmentComponents": list(f.treatment_components),
            "occGranularity": f.occ_granularity,
            "metric": f.metric,
            "normalize": f.normalize,
            "regionBucket": f.region_bucket,
            "regionSolar": list(f.region_solar),
        },
        indent=2,
    )


def subtitle_text(data: Dataset, f: Filters) -> str:
    unit = METRIC_LABELS[f.metric] + ("/day" if f.normalize == "per_day" else "")
    return (
        f"Conf ≥ {f.confidence} · {f.year_from}–{f.year_to} · "
        f"{len(f.preserves)}/{len(data.preserves)} preserves · "
        f"{len(f.plots)} plots · {unit}"
    )


def metric_phrase(data: Dataset, f: Filters) -> str:
    """Human-readable description of the active unit, for chart subtitles."""
    unit = metric_unit(data, f.metric)
    return f"{unit} per sampling day" if f.normalize == "per_day" else unit


def selection_label(data: Dataset, f: Filters) -> str:
    """
    'Grovers / GCP-A' style description of what is currently selected.

    Names the preserve and plot when the selection is that specific, and falls
    back to counts as it widens, so the heading always says what you're looking
    at rather than silently showing an aggregate.
    """
    # Use the plots that survive every filter, not the raw plot selection: with
    # a treatment filter active the heading would otherwise claim more plots
    # than the grid actually shows.
    plots = eligible_plots(data, f)
    pres = [p for p in data.preserves
            if p in set(data.plots.loc[data.plots["plot"].isin(plots), "preserve"])]
    if not pres or not plots:
        return "No selection"

    all_pres = len(pres) == len(data.preserves)
    if all_pres and len(plots) == len(data.all_plots):
        return f"All Preserves · {len(plots)} plots"

    if len(pres) == 1:
        in_preserve = data.plots_for(pres)
        if len(plots) == 1:
            return f"{pres[0]} / {plots[0]}"
        if len(plots) == len(in_preserve):
            return f"{pres[0]} · all {len(plots)} plots"
        return f"{pres[0]} · {len(plots)} of {len(in_preserve)} plots"

    if len(plots) <= 3:
        return " · ".join(plots)
    head = ", ".join(pres[:2])
    more = f" +{len(pres) - 2}" if len(pres) > 2 else ""
    return f"{head}{more} · {len(plots)} plots"


def occupancy_note(data: Dataset, f: Filters) -> str:
    """Plain-language statement of exactly how the displayed cells were computed."""
    if is_rate_mode(f):
        return (
            "Count = the number of 10-minute recordings containing the "
            f"species, at confidence ≥ {f.confidence}, summed across the "
            "selected plots. One recording counts once however many times the "
            "bird sings in it. This is a raw total, not corrected for effort — "
            "read it against the sampling-days row above, since a season with "
            "twice the survey days will tend to show twice the detections. "
            "Unlike occupancy it does not saturate, so it still separates "
            "species that are present every day but heard at very different "
            "rates. <b>NA</b> means the season had no sampling effort at the "
            "selected plots, not that the species was absent."
        )
    if f.occ_granularity == "hourly":
        formula = ("Hourly occupancy = hours detected ÷ sampling hours.")
        unit = ("sampling hour is a distinct (date, clock-hour) on which any "
                "selected plot recorded")
    else:
        formula = ("Daily occupancy = days detected ÷ sampling days.")
        unit = ("sampling day is a distinct calendar date on which any "
                "selected plot recorded")
    return (
        f"{formula} A detection counts when BirdNET scores the species at "
        f"confidence ≥ {f.confidence} anywhere in a recording; one {unit}, and "
        "a species claims that date if it was heard at any selected plot. "
        "Both sides are distinct dates, so five recorders running the same "
        "sixteen dates is sixteen sampling days, not eighty. "
        "Cells are shaded 0–100%. <b>NA</b> means the season had no sampling "
        "effort at the selected plots, not that the species was absent."
    )


def treatment_summary(data: Dataset, f: Filters) -> list[dict]:
    """
    Treatment period and its activities for whatever is currently selected.

    Returned per period, because both the group and the type are date-aware: a
    plot can be pretreat with type 'none' early on and posttreat with
    'patch cut, thinning' later. Reporting a single treatment type for such a
    plot would be wrong, which is exactly what the static labels did.
    """
    eff = effort_rows(data, f)
    if eff.empty:
        return []

    out = []
    for period in TREATMENT_GROUP_ORDER:
        sub = eff[eff["period"] == period]
        if sub.empty:
            continue
        types = sorted({t for t in sub["period_type"].dropna().unique()})
        if len(types) > 3:
            label = f"{' · '.join(types[:2])} +{len(types) - 2} more"
        else:
            label = " · ".join(types) if types else "unknown"
        out.append({
            "period": period,
            "display": PERIOD_DISPLAY.get(period),
            "ramp": period if period in RAMPS else "accent",
            "color": ramp_color(period if period in RAMPS else "accent", 0.85),
            "types": label,
            "n_plots": int(sub["plot"].nunique()),
        })
    return out


def period_colors_in_use(f: Filters) -> bool:
    """
    Whether the period ramps actually appear in the current chart.

    The treatment strip only shows swatches when the colours mean something on
    screen; otherwise it still reports the treatment types, just without a key
    to a colour scheme that isn't being used.
    """
    return f.compare_by == "treatment_group"


def panel_copy(data: Dataset, f: Filters) -> tuple[str, str]:
    if f.graph_type == "occupancy":
        if is_rate_mode(f):
            return ("Detections",
                    "10-min recordings containing a species, per season")
        if f.occ_granularity == "hourly":
            return ("Hourly Occupancy (%)",
                    "Share of recorded hours a species was detected")
        return ("Daily Occupancy (%)",
                "Share of sampling days a species was detected")
    if f.graph_type == "region":
        return ("Species Presence By Plot",
                "Occupancy per species at each recorder")

    rate = f.normalize == "per_day"
    if f.graph_type == "trends":
        return (
            "Detection Rate Over Time" if rate else "Detections Over Time",
            f"{metric_phrase(data, f)}, per season",
        )
    return (
        "Detection Rate By Species" if rate else "Detections By Species",
        f"{metric_phrase(data, f)}, ranked across the selected range",
    )
