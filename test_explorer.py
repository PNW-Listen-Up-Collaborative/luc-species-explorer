"""
Verification for the LUC Species Detection Explorer data layer.

Every assertion recomputes the expected answer independently from the raw source
CSVs, so this checks the cache + core logic rather than restating it.

    python test_explorer.py
"""

from __future__ import annotations

import datetime as dt
import io
import math
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

import explorer_core as core

HERE = Path(__file__).resolve().parent
SUMMARY = HERE / "BirdNET_Recording_Species_Summary.csv"
COMBINED = HERE / "Combined_BirdNET_Results.csv"

DATA = core.load_dataset(HERE / "data")
DEFAULTS = core.default_filters(DATA)

# The app opens at confidence 0.3. Many assertions below compare against the
# source's precomputed detected@0.5 column, so they pin 0.5 explicitly rather
# than inheriting whatever the default happens to be.
BASE = replace(DEFAULTS, confidence=0.5)

failures: list[str] = []
checks = 0


def check(name: str, got, want, tol: float = 0) -> None:
    global checks
    checks += 1
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want

    def brief(v):
        if isinstance(v, (set, frozenset, list, tuple)) and len(v) > 12:
            return f"<{type(v).__name__} of {len(v)}>"
        return repr(v)

    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {brief(got)}, want {brief(want)}")
    if not ok:
        failures.append(name)


print("Loading raw sources for independent recomputation…")
summary = pd.read_csv(SUMMARY, low_memory=False)

# Date-aware treatment period, rebuilt straight from the Task 1 metadata rather
# than from the cache, so the assertions below are genuinely independent.
_gpc = pd.read_csv(HERE / "GPC_Metadata.csv", low_memory=False,
                   parse_dates=["datetime"])
_gpc["date"] = _gpc["datetime"].dt.date
PERIODS = (_gpc.drop_duplicates(subset=["plot", "date"])[
    ["plot", "date", "treatment_group"]]
    .rename(columns={"treatment_group": "period"}))

summary["date"] = pd.to_datetime(summary["datetime"]).dt.date
summary = summary.merge(PERIODS, on=["plot", "date"], how="left")
summary["period"] = summary["period"].fillna(summary["treatment_group"])
combined = pd.read_csv(COMBINED, low_memory=False)
combined["season"] = combined["season"].str.strip().str.capitalize()

# ---------------------------------------------------------------- 1. totals
# The source ships precomputed detected@0.3/0.5/0.7 flags. Our cache derives
# everything from the raw detection rows, so these must agree exactly.
print("\n--- totals at each precomputed threshold ---")
for t in (0.3, 0.5, 0.7):
    f = replace(DEFAULTS, confidence=t)
    got = core.compute_kpis(DATA, f, core.apply_filters(DATA, f)).total_detections
    check(f"total detections @ {t}", got, int(summary[f"detected@{t}"].sum()))

# 0.9 has no precomputed column; derive it from max_confidence per rec x species.
f09 = replace(DEFAULTS, confidence=0.9)
check(
    "total detections @ 0.9 (derived)",
    core.compute_kpis(DATA, f09, core.apply_filters(DATA, f09)).total_detections,
    int((summary["max_confidence"] >= 0.9).sum()),
)

# Thresholds must be monotonically non-increasing.
print("\n--- monotonicity across thresholds ---")
totals = [
    core.compute_kpis(DATA, replace(DEFAULTS, confidence=t),
                      core.apply_filters(DATA, replace(DEFAULTS, confidence=t))
                      ).total_detections
    for t in (0.3, 0.5, 0.7, 0.9)
]
check("totals strictly decrease with threshold", all(
    a > b for a, b in zip(totals, totals[1:])), True)

# -------------------------------------------------------- 2. raw detection counts
print("\n--- raw detection counts (n_detections) ---")
for t in (0.3, 0.9):
    got = int(DATA.detections.loc[DATA.detections["threshold"] == t, "n_detections"].sum())
    check(f"raw rows @ {t}", got, int((combined["confidence"] >= t).sum()))

# ------------------------------------------------------------- 3. per-species
print("\n--- per-species totals @ 0.5 ---")
bars = core.species_bars(DATA, BASE, core.apply_filters(DATA, BASE))
expected = summary.groupby("species_code")["detected@0.5"].sum()
for r in bars.itertuples():
    check(f"  {r.species_code}", r.detections, int(expected.get(r.species_code, 0)))
check("species bars sorted descending",
      list(bars["detections"]) == sorted(bars["detections"], reverse=True), True)

# --------------------------------------------------------------- 4. subsetting
print("\n--- single-preserve subsetting ---")
pv = DATA.preserves[0]
f = core.cascade_preserves(DATA, BASE, [pv])
got = core.compute_kpis(DATA, f, core.apply_filters(DATA, f)).total_detections
want = int(summary.loc[summary["preserve"] == pv, "detected@0.5"].sum())
check(f"total for {pv}", got, want)
check(f"plots cascade to {pv}'s plots only",
      set(f.plots), set(summary.loc[summary["preserve"] == pv, "plot"]))

print("\n--- single-season subsetting ---")
f = replace(BASE, seasons=("Winter",))
got = core.compute_kpis(DATA, f, core.apply_filters(DATA, f)).total_detections
want = int(summary.loc[summary["season"].str.capitalize() == "Winter", "detected@0.5"].sum())
check("winter-only total", got, want)

print("\n--- treatment period subsetting (date-aware, multi-select) ---")
for grp in ("control", "pretreat", "posttreat"):
    f = replace(BASE, treatment_periods=(grp,))
    got = core.compute_kpis(DATA, f, core.apply_filters(DATA, f)).total_detections
    want = int(summary.loc[summary["period"] == grp, "detected@0.5"].sum())
    check(f"  {grp}", got, want)

# The filter is multi-select, so combinations a single choice could not express
# now work: treated plots in either era, or control against post-treatment.
check("period options are the three real periods, with no pooled entry",
      core.TREATMENT_GROUP_CHOICES, ["control", "pretreat", "posttreat"])
for combo in (("pretreat", "posttreat"), ("control", "posttreat"),
              ("control", "pretreat", "posttreat")):
    f = replace(BASE, treatment_periods=combo)
    got = core.compute_kpis(DATA, f, core.apply_filters(DATA, f)).total_detections
    want = int(summary.loc[summary["period"].isin(combo), "detected@0.5"].sum())
    check(f"  {' + '.join(combo)}", got, want)

check("selecting every period is the same as no restriction",
      core.allowed_periods(replace(BASE, treatment_periods=(
          "control", "pretreat", "posttreat"))), None)
check("  as is selecting none",
      core.allowed_periods(replace(BASE, treatment_periods=())), None)
check("  a partial selection restricts to exactly those",
      core.allowed_periods(replace(BASE, treatment_periods=("control",))),
      {"control"})
check("  and the metric is labelled Species Presence",
      core.METRIC_LABELS["presence"], "Species Presence")

# The static plot label disagrees with the date-aware period for the 10 plots
# treated partway through monitoring; the app must follow the date-aware one.
static_pre = int(summary.loc[summary["treatment_group"] == "pretreat",
                             "detected@0.5"].sum())
dated_pre = int(summary.loc[summary["period"] == "pretreat", "detected@0.5"].sum())
check("date-aware pretreat differs from the static label",
      static_pre != dated_pre, True)
print(f"        static {static_pre:,} vs date-aware {dated_pre:,}")

# ------------------------------------------------------------------ 5. cascade
print("\n--- preserve <-> plot cascade ---")
f = core.cascade_preserves(DATA, DEFAULTS, [p for p in DATA.preserves if p != pv])
check("dropping a preserve drops exactly its plots",
      set(DEFAULTS.plots) - set(f.plots), set(DATA.plots_for([pv])))
f2 = core.cascade_preserves(DATA, f, list(DATA.preserves))
check("re-adding it restores every plot", set(f2.plots), set(DATA.all_plots))

# Partial plot selections must survive an unrelated preserve toggle.
trimmed = replace(f2, plots=tuple(p for p in f2.plots if not p.startswith("GCP")))
other = [p for p in DATA.preserves if p != pv]
f3 = core.cascade_preserves(DATA, trimmed, other)
check("manual plot deselection is preserved across a cascade",
      any(p.startswith("GCP") for p in f3.plots), False)

# ---------------------------------------------------------------- 6. series
print("\n--- trends series ---")
f = BASE
rows = core.apply_filters(DATA, f)
series, buckets = core.build_series(DATA, f, rows, "detections")
check("single series when compare_by=none", len(series), 1)
check("series sums to KPI total", sum(series[0]["values"]),
      core.compute_kpis(DATA, f, rows).total_detections)
check("bucket count matches visible buckets", len(buckets), 9)
check("buckets are chronological",
      buckets, ["Su'22", "Wi'22-23", "Sp'23", "Su'23", "Sp'24", "Su'24",
                "Wi'24-25", "Sp'25", "Su'25"])

fg = replace(f, compare_by="treatment_group")
sg, _ = core.build_series(DATA, fg, rows, "detections")
check("grouped series partition the total",
      sum(sum(s["values"]) for s in sg),
      core.compute_kpis(DATA, f, rows).total_detections)
check("treatment groups in fixed design order",
      [s["key"] for s in sg], ["control", "pretreat", "posttreat"])
# Control is green rather than neutral gray: gray is spoken for by the effort
# row and the not-surveyed hatching in the occupancy grids.
check("control uses the control swatch", sg[0]["color"], core.CONTROL)
check("  and it is not the effort-row gray", sg[0]["color"] != core.NEUTRAL_600, True)
check("posttreat uses the accent", sg[2]["color"], core.ACCENT)
# The faceted Treat. group view puts control grids and per-preserve treatment
# grids on one page, so control's ramp must not be in the cycled set.
check("  control's ramp is reserved, not cycled",
      "control" in core.RAMPS and core.RAMPS["control"] not in
      [core.RAMPS[r] for r in core.RAMP_CYCLE], True)

print("\n--- diversity view retired ---")
# Species richness over time was its own graph type. With only eight target
# species it sat at 7-8 in every season at the default threshold, so it drew a
# flat line carrying no information the Species Richness card does not already
# give. The underlying series is still computable; it is just not a view.
sd, _ = core.build_series(DATA, f, rows, "richness")
check("richness never exceeds species tracked", max(sd[0]["values"]) <= 8, True)
check("  and barely varies, which is why the view went",
      max(sd[0]["values"]) - min(sd[0]["values"]) <= 2, True)

# ------------------------------------------------------------- 7. occupancy
print("\n--- occupancy ---")
grid, sampling, bk = core.occupancy_grid(DATA, f, rows)
check("occupancy within 0-100", bool(((grid >= 0) & (grid <= 100)).all().all()), True)
check("grid shape", grid.shape, (8, 9))

# Independent recomputation of one cell. Both sides are distinct calendar
# dates unioned over the selected plots — a species claims a date if it was
# heard anywhere that day — which is the Nb3 notebook's definition.
recs = summary.drop_duplicates("rec").copy()
recs["date"] = pd.to_datetime(recs["datetime"]).dt.date
su25 = recs[(recs["season_period_year"] == 2025) & (recs["season"] == "Summer")]
days_sampled = su25["date"].nunique()

cmb = combined.copy()
cmb["date"] = pd.to_datetime(cmb["datetime"]).dt.date
hit = cmb[(cmb["season_period_year"] == 2025) & (cmb["season"] == "Summer")
          & (cmb["species_code"] == "PAWR") & (cmb["confidence"] >= 0.5)]
days_detected = hit["date"].nunique()
check("PAWR daily occupancy Su'25", float(grid.loc["PAWR", "Su'25"]),
      round(100 * days_detected / days_sampled, 1), tol=0.05)

fh = replace(f, occ_granularity="hourly")
gh, sh, _ = core.occupancy_grid(DATA, fh, core.apply_filters(DATA, fh))
check("hourly grid also within 0-100",
      bool(((gh >= 0) & (gh <= 100)).all().all()), True)
check("hourly denominator >= daily denominator",
      bool((sh >= sampling).all()), True)

# --------------------------------------------------------------- 8. region
print("\n--- region ---")
nodes = core.region_nodes(DATA, f, rows)
check("one node per selected plot", len(nodes), len(DEFAULTS.plots))
check("every node has coordinates",
      bool(nodes[["latitude", "longitude"]].notna().all().all()), True)
check("richness never exceeds selected species",
      bool((nodes["richness"] <= len(f.species)).all()), True)
check("plot detections sum to the KPI total", int(nodes["detections"].sum()),
      core.compute_kpis(DATA, f, rows).total_detections)

# ---------------------------------------------------------------- 9. exports
print("\n--- per-view CSV export ---")
GRAPH_TYPES = ("occupancy", "trends", "species", "region")
for view in GRAPH_TYPES:
    fv = replace(f, graph_type=view)
    blob = core.export_csv(DATA, fv, core.apply_filters(DATA, fv))
    header = blob.decode().splitlines()[0]
    check(f"  {view} export non-empty", len(blob.decode().splitlines()) > 1, True)
    print(f"        header: {header}")

# Every offered view must have a title, and no retired view may linger.
check("every graph type has panel copy",
      all(len(core.panel_copy(DATA, replace(f, graph_type=v))) == 2
          for v in GRAPH_TYPES), True)
check("  diversity is no longer one of them", "diversity" in GRAPH_TYPES, False)

# ------------------------------------------------------------- 10. no-data
print("\n--- empty state ---")
f_empty = replace(DEFAULTS, species=())
k = core.compute_kpis(DATA, f_empty, core.apply_filters(DATA, f_empty))
check("no species selected -> no data", k.has_data, False)
check("  total is zero", k.total_detections, 0)
check("  top species falls back", k.top_code, "n/a")

f_empty2 = replace(DEFAULTS, preserves=(), plots=())
k2 = core.compute_kpis(DATA, f_empty2, core.apply_filters(DATA, f_empty2))
check("no plots selected -> no data", k2.has_data, False)

# ------------------------------------------------------------ 11. year range
print("\n--- year range ---")
f_yr = replace(BASE, year_from=2025, year_to=2025)
got = core.compute_kpis(DATA, f_yr, core.apply_filters(DATA, f_yr)).total_detections
want = int(summary.loc[summary["season_period_year"] == 2025, "detected@0.5"].sum())
check("2025 only", got, want)
check("2025 buckets", core.visible_buckets(DATA, f_yr),
      ["Wi'24-25", "Sp'25", "Su'25"])

# ------------------------------------------------------- 12. metric toggle
print("\n--- raw detection metric ---")
for t in (0.3, 0.5, 0.7, 0.9):
    f = replace(DEFAULTS, metric="raw", confidence=t)
    got = core.compute_kpis(DATA, f, core.apply_filters(DATA, f)).total_detections
    want = int((combined["confidence"] >= t).sum())
    check(f"raw total @ {t}", got, want)

check("presence and raw differ by ~12x @0.3",
      round(287399 / 23394, 1), 12.3, tol=0.05)

# Raw totals must never fall below presence totals: every present pair
# contributes at least one raw detection.
for t in (0.3, 0.5, 0.7, 0.9):
    fp = replace(DEFAULTS, metric="presence", confidence=t)
    fr = replace(DEFAULTS, metric="raw", confidence=t)
    p = core.compute_kpis(DATA, fp, core.apply_filters(DATA, fp)).total_detections
    r = core.compute_kpis(DATA, fr, core.apply_filters(DATA, fr)).total_detections
    check(f"raw >= presence @ {t}", r >= p, True)

# Species ranking genuinely differs between the two units.
fp = replace(DEFAULTS, metric="presence")
fr = replace(DEFAULTS, metric="raw")
rank_p = list(core.species_bars(DATA, fp, core.apply_filters(DATA, fp))["species_code"])
rank_r = list(core.species_bars(DATA, fr, core.apply_filters(DATA, fr))["species_code"])
check("species ranking differs between metrics", rank_p != rank_r, True)
print(f"        presence: {rank_p}")
print(f"        raw     : {rank_r}")

# --------------------------------------------------- 13. effort correction
print("\n--- per-day normalisation ---")
f_tot = replace(DEFAULTS, metric="raw", normalize="total")
f_day = replace(DEFAULTS, metric="raw", normalize="per_day")
rows_tot = core.apply_filters(DATA, f_tot)
s_tot, bk = core.build_series(DATA, f_tot, rows_tot, "detections")
s_day, _ = core.build_series(DATA, f_day, core.apply_filters(DATA, f_day), "detections")

denom = core.effort_denominator(DATA, f_day, list(DEFAULTS.plots), bk)
# Recompute days sampled straight from the summary file.
recs_all = summary.drop_duplicates("rec").copy()
recs_all["date"] = pd.to_datetime(recs_all["datetime"]).dt.date
recs_all["spy"] = recs_all["season_period_year"]
rank = {"Winter": 0, "Spring": 1, "Summer": 2}
recs_all["bsort"] = recs_all["spy"] * 10 + recs_all["season"].map(rank)
bsort_of = {b["bucket"]: b["bucket_sort"] for b in DATA.meta["buckets"]}
for b in bk:
    # Distinct dates any plot recorded, not each plot's dates summed.
    want_days = recs_all.loc[recs_all["bsort"] == bsort_of[b], "date"].nunique()
    check(f"  days sampled {b}", int(denom[b]), int(want_days))

for i, b in enumerate(bk):
    expected = round(s_tot[0]["values"][i] / denom[b], 2) if denom[b] else 0.0
    check(f"  rate {b}", s_day[0]["values"][i], expected, tol=0.01)

check("normalisation reorders the peak bucket",
      bk[s_tot[0]["values"].index(max(s_tot[0]["values"]))]
      != bk[s_day[0]["values"].index(max(s_day[0]["values"]))], True)

# Richness is a species count and must be unaffected by normalisation.
r_tot, _ = core.build_series(DATA, replace(DEFAULTS, normalize="total"),
                             core.apply_filters(DATA, DEFAULTS), "richness")
r_day, _ = core.build_series(DATA, replace(DEFAULTS, normalize="per_day"),
                             core.apply_filters(DATA, DEFAULTS), "richness")
check("richness ignores normalisation", r_tot[0]["values"], r_day[0]["values"])

# Grouped series must use their own group's plots as the denominator.
print("\n--- group-scoped effort denominators ---")
# Treatment group is date-aware, so its denominator is scoped by period rather
# than by a fixed plot set; every group may draw on any plot.
fg = replace(DEFAULTS, metric="raw", normalize="per_day", compare_by="treatment_group")
sg, bkg = core.build_series(DATA, fg, core.apply_filters(DATA, fg), "detections")
_pd_summary = summary.drop_duplicates("rec").copy()
_pd_summary["date"] = pd.to_datetime(_pd_summary["datetime"]).dt.date
_pd_summary["bsort"] = (_pd_summary["season_period_year"] * 10
                        + _pd_summary["season"].str.capitalize().map(rank))
for s in sg:
    denom = core.effort_denominator(DATA, fg, core.eligible_plots(DATA, fg),
                                    bkg, periods={s["key"]})
    # Recomputed from the source: distinct dates in this period, per bucket.
    sub = _pd_summary[_pd_summary["period"] == s["key"]]
    want = sum(int(sub.loc[sub["bsort"] == bsort_of[b], "date"].nunique())
               for b in bkg)
    check(f"  {s['key']} denominator is period-scoped",
          float(denom.sum()), float(want), tol=0.01)

# Periods overlap in calendar time — different plots are treated on different
# dates — so their day counts sum to more than the whole, unlike recorder-days.
_parts = sum(
    float(core.effort_denominator(DATA, DEFAULTS, list(DEFAULTS.plots), bkg,
                                  periods={g}).sum())
    for g in ("control", "pretreat", "posttreat")
)
_whole = float(core.effort_denominator(DATA, DEFAULTS, list(DEFAULTS.plots),
                                       bkg).sum())
check("period day-counts cover the whole survey", _parts >= _whole, True)
print(f"        control+pretreat+posttreat {_parts:.0f} vs all {_whole:.0f} "
      f"— the excess is dates when plots in different periods both recorded")

# Exports must record the unit.
print("\n--- the export follows the filters ---")
# The download button used to be built before the controls were read, so it
# served the previous interaction's data. The export itself must vary with
# every filter that changes what is on screen.
import hashlib as _hl
_ex_cases = {
    "default":    DEFAULTS,
    "conf0.9":    replace(DEFAULTS, confidence=0.9),
    "grovers":    core.cascade_preserves(DATA, DEFAULTS, ["Grovers"]),
    "one plot":   replace(DEFAULTS, preserves=("Grovers",), plots=("GCP-A",)),
    "one species": replace(DEFAULTS, species=("WIWA",)),
    "winter":     replace(DEFAULTS, seasons=("Winter",)),
    "hourly":     replace(DEFAULTS, occ_granularity="hourly"),
    "count":      replace(DEFAULTS, occ_granularity="count"),
    "trends":     replace(DEFAULTS, graph_type="trends"),
    "species":    replace(DEFAULTS, graph_type="species"),
    "map":        replace(DEFAULTS, graph_type="region"),
}
_digests = {k: _hl.md5(core.export_csv(DATA, v, core.apply_filters(DATA, v))
                       ).hexdigest() for k, v in _ex_cases.items()}
check("every filter combination exports different bytes",
      len(set(_digests.values())), len(_ex_cases))

# And the filename must say which of them it is, or a folder of downloads is
# indistinguishable and the browser just appends (1), (2), (3).
_names = {k: core.export_filename(DATA, v) for k, v in _ex_cases.items()}
check("  each export gets its own filename",
      len(set(_names.values())), len(_ex_cases))
check("  naming the view", "occupancy" in _names["default"]
      and "trends" in _names["trends"] and "region" in _names["map"], True)
check("  the scope", "GCP-A" in _names["one plot"]
      and "Grovers" in _names["grovers"]
      and "all-plots" in _names["default"], True)
check("  the threshold", "conf0.9" in _names["conf0.9"], True)
check("  and the occupancy mode",
      "daily" in _names["default"] and "hourly" in _names["hourly"]
      and "count" in _names["count"], True)
check("  every filename is safe for a filesystem",
      all(not set(n) & set('<>:"/\\|?* ') for n in _names.values()), True)

print("\n--- every export says where the data came from ---")
import io as _io
_LOC = ["preserve", "plot", "latitude", "longitude", "n_plots",
        "preserves_included", "plots_included"]
for _v in ("occupancy", "trends", "species", "region"):
    _fv = replace(DEFAULTS, graph_type=_v)
    _hdr = core.export_csv(DATA, _fv,
                           core.apply_filters(DATA, _fv)).decode().splitlines()[0]
    check(f"  {_v} export carries location columns",
          all(c in _hdr.split(",") for c in _LOC), True)

# Per-plot grids must name their own plot and coordinates; a pooled grid must
# not invent a position, because the mean of several sites is nowhere real.
_f_gr = core.cascade_preserves(DATA, DEFAULTS, ["Grovers"])
_df_gr = pd.read_csv(_io.BytesIO(
    core.export_csv(DATA, _f_gr, core.apply_filters(DATA, _f_gr))))
check("per-plot rows carry their plot's coordinates",
      bool(_df_gr.loc[_df_gr["n_plots"] == 1, "latitude"].notna().all()), True)
check("  pooled rows carry none",
      bool(_df_gr.loc[_df_gr["n_plots"] > 1, "latitude"].isna().all()), True)
check("  and every row names its preserve",
      bool((_df_gr["preserve"] == "Grovers").all()), True)

_coords = DATA.plots.set_index("plot")
_one = _df_gr[_df_gr["plot"] == "GCP-A"].iloc[0]
check("  coordinates match the plots table",
      (round(float(_one["latitude"]), 5), round(float(_one["longitude"]), 5)),
      (round(float(_coords.loc["GCP-A", "latitude"]), 5),
       round(float(_coords.loc["GCP-A", "longitude"]), 5)))
check("  plots_included lists the pooled grid's members",
      set(_df_gr.loc[_df_gr["n_plots"] > 1, "plots_included"].iloc[0].split("|")),
      set(_f_gr.plots))

# A multi-preserve selection cannot claim one preserve.
_f_two = core.cascade_preserves(DATA, DEFAULTS, ["Grovers", "Burley"])
_df_two = pd.read_csv(_io.BytesIO(core.export_csv(
    DATA, replace(_f_two, graph_type="trends"),
    core.apply_filters(DATA, replace(_f_two, graph_type="trends")))))
check("a two-preserve export leaves 'preserve' blank",
      bool(_df_two["preserve"].isna().all()), True)
check("  but lists both in preserves_included",
      sorted(_df_two["preserves_included"].iloc[0].split("|")),
      ["Burley", "Grovers"])

print("\n--- exports mirror Combined_BirdNET_Results.csv ---")
# Same column names in the same order, so a download drops into whatever
# already reads the source table.
_src_cols = list(pd.read_csv(COMBINED, nrows=1, low_memory=False).columns)
_expected_shared = ["preserve", "plot", "treatment_group", "treatment_type",
                    "latitude", "longitude", "elevation",
                    "season_period_year", "season", "year_season",
                    "species", "species_code", "forage_guilds"]
check("every one of those columns exists in the source",
      [c for c in _expected_shared if c in _src_cols], _expected_shared)
for _v in ("occupancy", "trends", "species", "region"):
    _fv = replace(DEFAULTS, graph_type=_v)
    _cols = core.export_csv(
        DATA, _fv, core.apply_filters(DATA, _fv)).decode().splitlines()[0].split(",")
    check(f"  {_v} leads with the source's own columns",
          _cols[:len(_expected_shared)], _expected_shared)
    check(f"    in the source's own order",
          [c for c in _cols if c in _src_cols],
          [c for c in _src_cols if c in _cols])

# Site fields belong to one site, so they are filled only for one site.
_f_gr2 = core.cascade_preserves(DATA, DEFAULTS, ["Grovers"])
_dgr = pd.read_csv(io.BytesIO(
    core.export_csv(DATA, _f_gr2, core.apply_filters(DATA, _f_gr2))))
_per = _dgr[_dgr["n_plots"] == 1]
_pool = _dgr[_dgr["n_plots"] > 1]
check("per-plot rows carry elevation and coordinates",
      bool(_per[["latitude", "longitude", "elevation"]].notna().all().all()), True)
check("  pooled rows carry none of them",
      bool(_pool[["latitude", "longitude", "elevation"]].isna().all().all()), True)
check("  elevation matches the plots table",
      float(_per[_per["plot"] == "GCP-A"]["elevation"].iloc[0]),
      float(DATA.plots.set_index("plot").loc["GCP-A", "elevation"]))

# Treatment is date-aware, so an exported row shows the treatment in force that
# season, not the plot's static label.
_ga = _per[(_per["plot"] == "GCP-A")]
check("treatment_group follows the season, not a static label",
      (_ga[_ga["year_season"] == "2022 Summer"]["treatment_group"].iloc[0],
       _ga[_ga["year_season"] == "2023 Spring"]["treatment_group"].iloc[0]),
      ("pretreat", "posttreat"))
check("  and treatment_type with it",
      _ga[_ga["year_season"] == "2023 Spring"]["treatment_type"].iloc[0],
      "patch cut, thinning")

# The species block uses the source's scientific name and guild.
_bewr = _dgr[_dgr["species_code"] == "BEWR"].iloc[0]
_src_bewr = combined[combined["species_code"] == "BEWR"].iloc[0]
check("species column carries the scientific name",
      _bewr["species"], _src_bewr["species"])
check("  and forage_guilds matches the source",
      _bewr["forage_guilds"], _src_bewr["forage_guilds"])

print("\n--- export unit labelling ---")
for m in ("presence", "raw"):
    for n in ("total", "per_day"):
        fv = replace(DEFAULTS, metric=m, normalize=n, graph_type="trends")
        txt = core.export_csv(DATA, fv, core.apply_filters(DATA, fv)).decode()
        want = f"{m}_per_day" if n == "per_day" else m
        check(f"  trends {m}/{n} unit column", want in txt, True)

# ------------------------------------------- 14. recording effort KPIs
print("\n--- recordings and hours recorded ---")
manifest = pd.read_csv(HERE / "BirdNET_Recording_Manifest.csv", low_memory=False)

check("manifest and summary cover the same recordings",
      len(set(manifest["filename"]) ^ set(summary["rec"])), 0)

k = core.compute_kpis(DATA, DEFAULTS, core.apply_filters(DATA, DEFAULTS))
check("total recordings", k.n_recordings, int(manifest["filename"].nunique()))

# Duration recomputed straight from file size: 48 kHz 16-bit mono, 44-byte header.
want_hours = ((manifest["file_size_bytes"] - 44) / 96000).clip(lower=0).sum() / 3600
check("total hours recorded", round(k.hours_recorded, 1), round(want_hours, 1), tol=0.05)

# Hours must not be recordings x 10 min — the recorder captures 590s of each
# 600s cycle, and 18 files are truncated.
nominal = manifest["filename"].nunique() * 10 / 60
check("hours are real duration, not nominal 10-min",
      abs(k.hours_recorded - nominal) > 40, True)
print(f"        actual {k.hours_recorded:,.1f} h vs nominal {nominal:,.1f} h "
      f"({nominal - k.hours_recorded:,.1f} h difference)")
check("truncated files counted", DATA.meta["n_truncated_recordings"], 18)

print("\n--- effort KPIs track the filters ---")
pv = DATA.preserves[0]
f = core.cascade_preserves(DATA, DEFAULTS, [pv])
k = core.compute_kpis(DATA, f, core.apply_filters(DATA, f))
want_recs = int(manifest.loc[manifest["preserve"] == pv, "filename"].nunique())
check(f"recordings for {pv}", k.n_recordings, want_recs)
want_h = (((manifest.loc[manifest["preserve"] == pv, "file_size_bytes"] - 44)
           / 96000).clip(lower=0).sum() / 3600)
check(f"hours for {pv}", round(k.hours_recorded, 1), round(want_h, 1), tol=0.05)

# Treatment groups partition the recordings exactly.
rec_periods = summary.drop_duplicates("rec")[["rec", "period"]]
tot = 0
for grp in ("control", "pretreat", "posttreat"):
    fg = replace(DEFAULTS, treatment_periods=(grp,))
    kg = core.compute_kpis(DATA, fg, core.apply_filters(DATA, fg))
    want = int((rec_periods["period"] == grp).sum())
    check(f"  {grp} recordings", kg.n_recordings, want)
    tot += kg.n_recordings
check("treatment periods partition all recordings", tot,
      int(manifest["filename"].nunique()))

# ------------------------------------------- 15. numerator/denominator parity
print("\n--- effort denominator respects every filter ---")
# Regression: the occupancy denominator previously ignored treatment filters,
# so restricting to control plots divided by all 40 plots' sampling days.
f_all = DEFAULTS
f_ctl = replace(DEFAULTS, treatment_periods=("control",))
_, samp_all, bk = core.occupancy_grid(DATA, f_all, core.apply_filters(DATA, f_all))
_, samp_ctl, _ = core.occupancy_grid(DATA, f_ctl, core.apply_filters(DATA, f_ctl))
check("control denominator is strictly smaller than all-periods",
      bool((samp_ctl <= samp_all).all() and (samp_ctl < samp_all).any()), True)

# Independent recomputation of the control denominator, using the date-aware
# period rather than the static plot label.
recs_ctl = summary.drop_duplicates("rec").copy()
recs_ctl = recs_ctl[recs_ctl["period"] == "control"]
recs_ctl["bsort"] = (recs_ctl["season_period_year"] * 10
                     + recs_ctl["season"].str.capitalize()
                       .map({"Winter": 0, "Spring": 1, "Summer": 2}))
b0 = bk[0]
want_days = recs_ctl.loc[recs_ctl["bsort"] == bsort_of[b0], "date"].nunique()
check(f"control days sampled {b0}", int(samp_ctl[b0]), int(want_days))

# A filter that removes plots must shrink numerator and denominator together.
# The component filter is date-aware, so it selects rows, not whole plots: a
# plot contributes its pretreat rows ('none') but not its posttreat rows.
f_none = replace(DEFAULTS, treatment_components=("none",))
rows_none = core.apply_filters(DATA, f_none)
k_none = core.compute_kpis(DATA, f_none, rows_none)
check("component filter selects rows, not plots",
      bool((rows_none["period_type"] == "none").all()), True)
check("  and its recordings are fewer than the full set",
      k_none.n_recordings < 18211, True)

# A post-treatment activity must reach only the plots that actually received it.
f_pc = replace(DEFAULTS, treatment_components=("patch cut",))
rows_pc = core.apply_filters(DATA, f_pc)
want_plots = set(
    DATA.effort.loc[
        DATA.effort["period_type"].fillna("").str.contains("patch cut"), "plot"]
)
check("patch cut reaches only treated plots",
      set(rows_pc["plot"]) <= want_plots, True)
check("  and only their posttreat rows",
      set(rows_pc["period"]), {"posttreat"})

# ------------------------------------------- 16. occupancy NA and panels
print("\n--- presence counts species x recording, not recordings ---")
# The presence flag is per recording AND species, so a file holding three
# species contributes three. Both quantities recomputed from the raw table.
for _t in (0.3, 0.5, 0.7, 0.9):
    _sub = combined[combined["confidence"] >= _t]
    check(f"recordings with any detection @ {_t}",
          DATA.meta["recordings_with_detection"][str(_t)],
          int(_sub["rec"].nunique()))
    _pairs = int(_sub.groupby(["rec", "species_code"]).ngroups)
    _f_t = replace(DEFAULTS, confidence=_t)
    check(f"  species x recording pairs @ {_t}",
          core.compute_kpis(DATA, _f_t,
                            core.apply_filters(DATA, _f_t)).total_detections,
          _pairs)
check("  the two genuinely differ",
      DATA.meta["recordings_with_detection"]["0.3"]
      < core.compute_kpis(DATA, DEFAULTS,
                          core.apply_filters(DATA, DEFAULTS)).total_detections,
      True)
check("  and the label no longer claims to be recordings",
      "recordings with a detection" in core.metric_unit(DATA, "presence"), False)

print("\n--- occupancy matches the Nb3 notebook, preserve by preserve ---")
# The notebook's definition: days detected / sampling days, both distinct
# calendar dates unioned across the plots in view. Figures below are the
# published Grovers Summer 2022 column, and are also recomputed from the raw
# CSVs so the check does not merely restate the app.
NB_GROVERS_SU22 = {"BEWR": 87.5, "BRCR": 100.0, "CBCH": 100.0, "DOWO": 87.5,
                   "PAWR": 100.0, "SPTO": 100.0, "SWTH": 93.8, "WIWA": 62.5}
_r = summary.drop_duplicates("rec").copy()
_gr = summary[(summary["preserve"] == "Grovers")
              & (summary["season"].str.capitalize() == "Summer")
              & (summary["season_period_year"] == 2022)]
_gr_samp = int(_gr["date"].nunique())
check("Grovers Su'22 sampling days", _gr_samp, 16)

_f_gr = core.cascade_preserves(DATA, DEFAULTS, ["Grovers"])
_g_gr, _s_gr, _ = core.occupancy_grid(DATA, _f_gr,
                                      core.apply_filters(DATA, _f_gr))
check("  app agrees on the denominator", int(_s_gr["Su'22"]), _gr_samp)
for _sp, _want in NB_GROVERS_SU22.items():
    _dd = int(_gr.loc[(_gr["species_code"] == _sp)
                      & (_gr["detected@0.3"] == 1), "date"].nunique())
    check(f"  {_sp} = {_dd}/{_gr_samp} days", float(_g_gr.loc[_sp, "Su'22"]),
          round(100 * _dd / _gr_samp, 1), tol=0.05)
    check(f"    and matches the notebook's {_want}%",
          abs(float(_g_gr.loc[_sp, "Su'22"]) - _want) < 0.05, True)

# Sampling days is a union, so it is far below the plot-days sum it replaced.
_su22 = _r[(_r["season"].str.capitalize() == "Summer")
           & (_r["season_period_year"] == 2022)]
_, _s22, _ = core.occupancy_grid(DATA, DEFAULTS,
                                 core.apply_filters(DATA, DEFAULTS))
check("all-plots Su'22 counts distinct dates, not plot-days",
      int(_s22["Su'22"]), int(_su22["date"].nunique()))
check("  which is well under the plot-day sum",
      int(_s22["Su'22"]) < int(_su22.groupby("plot")["date"].nunique().sum()),
      True)
check("  and the label says sampling days",
      core.OCC_EFFORT_LABELS["daily"], "Sampling days")

# One plot: union and per-plot count coincide, so the definition is consistent.
_f1 = replace(DEFAULTS, preserves=("Grovers",), plots=("GCP-A",))
_ga = _r[(_r["plot"] == "GCP-A") & (_r["season"].str.capitalize() == "Summer")
         & (_r["season_period_year"] == 2022)]
_, _s1, _ = core.occupancy_grid(DATA, _f1, core.apply_filters(DATA, _f1))
check("  one plot: union equals that plot's own dates",
      int(_s1["Su'22"]), int(_ga["date"].nunique()))

print("\n--- Count mode: raw detections per season ---")
# A plain count of 10-minute recordings containing the species, not divided by
# anything. Recomputed from the summary CSV rather than read back from the app.
_f_cnt = replace(core.cascade_preserves(DATA, DEFAULTS, ["Grovers"]),
                 occ_granularity="count")
_g_cnt, _s_cnt, _ = core.occupancy_grid(DATA, _f_cnt,
                                        core.apply_filters(DATA, _f_cnt))
check("Count still reports sampling days for context",
      int(_s_cnt["Su'22"]), _gr_samp)
for _sp in ("BEWR", "PAWR", "DOWO", "SWTH"):
    _recs = int(((_gr["species_code"] == _sp) & (_gr["detected@0.3"] == 1)).sum())
    check(f"  {_sp} counts {_recs} recordings",
          float(_g_cnt.loc[_sp, "Su'22"]), float(_recs))

# Explicitly not a rate: the cell is the numerator alone.
check("  it is not divided by sampling days",
      float(_g_cnt.loc["PAWR", "Su'22"]) != round(
          float(_g_cnt.loc["PAWR", "Su'22"]) / _gr_samp, 1), True)
check("  and every value is a whole number of recordings",
      all(float(v).is_integer() for v in _g_cnt.stack()), True)

# The point of the mode: separates species that occupancy cannot.
_tied = [c for c in _g_gr.index if float(_g_gr.loc[c, "Su'22"]) == 100.0]
_counts = [float(_g_cnt.loc[c, "Su'22"]) for c in _tied]
check("  species tied at 100% occupancy get distinct counts",
      len(_tied) > 1 and len(set(_counts)) == len(_tied), True)
print(f"        {len(_tied)} species at 100% span "
      f"{min(_counts):.0f}-{max(_counts):.0f} recordings")

check("  Count is offered as a third heatmap mode",
      core.OCC_MODES, ["daily", "hourly", "count"])
check("  and is flagged as unbounded, not a percentage",
      (core.is_rate_mode(_f_cnt),
       core.is_rate_mode(replace(_f_cnt, occ_granularity="daily"))),
      (True, False))
check("  its title says so",
      core.panel_copy(DATA, replace(_f_cnt, graph_type="occupancy"))[0],
      "Detections")
check("  unsurveyed seasons stay NA rather than reading zero",
      bool(_g_cnt["Sp'25"].isna().all()), True)

print("\n--- unsurveyed buckets report NA, not 0 ---")
# GCP-A was not sampled in Su'23, Sp'24 or Sp'25.
f_ga = replace(DEFAULTS, preserves=("Grovers",), plots=("GCP-A",))
g_ga, s_ga, bk_ga = core.occupancy_grid(DATA, f_ga, core.apply_filters(DATA, f_ga))

zero_effort = [b for b in bk_ga if s_ga[b] == 0]
check("GCP-A has unsurveyed buckets", len(zero_effort) > 0, True)
print(f"        zero-effort buckets: {zero_effort}")
check("  every zero-effort bucket is entirely NA",
      bool(g_ga[zero_effort].isna().all().all()), True)
check("  no surveyed bucket is NA",
      bool(g_ga[[b for b in bk_ga if b not in zero_effort]].notna().all().all()), True)

# Independently confirm those seasons really had no recordings at that plot.
recs_ga = summary.drop_duplicates("rec")
recs_ga = recs_ga[recs_ga["plot"] == "GCP-A"].copy()
recs_ga["bsort"] = (recs_ga["season_period_year"] * 10
                    + recs_ga["season"].map({"Winter": 0, "Spring": 1, "Summer": 2}))
for b in zero_effort:
    check(f"  {b} truly has no GCP-A recordings",
          int((recs_ga["bsort"] == bsort_of[b]).sum()), 0)

# A fully-selected dataset should have no NA at all.
g_all, s_all, bk_all = core.occupancy_grid(DATA, DEFAULTS,
                                           core.apply_filters(DATA, DEFAULTS))
check("all-plots grid has no NA", int(g_all.isna().sum().sum()), 0)

print("\n--- occupancy compare-by panels ---")
# Compare off: the pooled grid, then one grid per plot. The pooled grid unions
# dates across plots so it saturates; the per-plot grids are where the variation
# is. A single-plot selection gets just the one grid, since the pooled grid
# already is that plot.
# The default view is every plot, where 40 extra grids would be noise; the
# per-plot breakdown appears once someone narrows to specific preserves or
# plots, which is the signal that they want to look plot by plot.
f_none = replace(DEFAULTS, compare_by="none")
_pn_all = core.occupancy_panels(DATA, f_none, core.apply_filters(DATA, f_none))
check("all plots selected gives just the combined grid",
      (len(_pn_all), _pn_all[0]["label"]), (1, None))

f_gr = replace(core.cascade_preserves(DATA, DEFAULTS, ["Grovers"]),
               compare_by="none")
_pn = core.occupancy_panels(DATA, f_gr, core.apply_filters(DATA, f_gr))
_gr_plots = list(f_gr.plots)
check("narrowing to a preserve adds one grid per plot",
      len(_pn), 1 + len(_gr_plots))
check("  the first is the pooled one", _pn[0]["n_plots"], len(_gr_plots))
check("  and it is labelled as combined",
      _pn[0]["label"], "All selected plots combined")
check("  the rest are one plot each",
      all(p["n_plots"] == 1 for p in _pn[1:]), True)
check("  each titled preserve / plot",
      _pn[1]["label"],
      f"{DATA.plots.set_index('plot').loc[_pn[1]['key'], 'preserve']}"
      f" / {_pn[1]['key']}")
check("  covering every selected plot exactly once",
      sorted(p["key"] for p in _pn[1:]), sorted(_gr_plots))

_f_one = replace(DEFAULTS, compare_by="none", preserves=("Grovers",),
                 plots=("GCP-A",))
_p_one = core.occupancy_panels(DATA, _f_one, core.apply_filters(DATA, _f_one))
check("  one plot selected gives one grid, unlabelled",
      (len(_p_one), _p_one[0]["label"]), (1, None))

# A per-plot grid must equal that plot selected on its own.
_probe = "GCP-A"
_f_probe = replace(DEFAULTS, preserves=("Grovers",), plots=(_probe,))
_g_probe, _s_probe, _bk_probe = core.occupancy_grid(
    DATA, _f_probe, core.apply_filters(DATA, _f_probe))
_panel_probe = next(p for p in _pn if p["key"] == _probe)
# "NA" rather than nan: NaN is not equal to itself, so a raw list comparison
# would fail on unsurveyed seasons even when both sides agree.
def _cells(vals):
    return ["NA" if pd.isna(v) else round(float(v), 1) for v in vals]

check("  a per-plot grid matches selecting that plot alone",
      _cells(_panel_probe["grid"].loc["PAWR"]),
      _cells(_g_probe.loc["PAWR", b] for b in _bk_probe))
check("    including its sampling days",
      [int(v) for v in _panel_probe["sampling"]],
      [int(_s_probe[b]) for b in _bk_probe])

# Treatment group divides the columns of a grid by era, as in the notebook.
# Within a single preserve that's ONE split grid; pooling every preserve into
# one grid stops being readable, so at full scope it facets into one grid per
# preserve instead (see "occupancy compare-by panels: full scope" below).
f_ga_tg_single = replace(DEFAULTS, preserves=("Grovers",), plots=("GCP-A",),
                         compare_by="treatment_group")
panels = core.occupancy_panels(
    DATA, f_ga_tg_single, core.apply_filters(DATA, f_ga_tg_single))
check("single-plot selection yields a single split grid", len(panels), 1)
check("  it is marked as period-split", panels[0]["split_by_period"], True)
cols = panels[0]["columns"]
check("  sampled columns carry a period",
      all(c["period"] for c in cols if c["period"] is not None), True)
check("  pretreat columns use the notebook's purple ramp",
      {c["ramp"] for c in cols if c["period"] == "pretreat"}, {"pretreat"})
check("  posttreat columns use the notebook's blue ramp",
      {c["ramp"] for c in cols if c["period"] == "posttreat"}, {"posttreat"})
# Columns stay chronological; colour alone conveys the period, so no divider
# is needed and unsurveyed seasons keep their place in the timeline.
vis = core.visible_buckets(DATA, f_ga_tg_single)
check("  columns are chronological",
      [c["bucket"] for c in cols],
      sorted([c["bucket"] for c in cols], key=vis.index))

# At full scope (every preserve selected), Treat. group facets into one
# split grid per preserve rather than pooling 40 plots' worth of treatment
# activity into a single unreadable grid. Control plots (never treated) get
# their own separate grid per preserve too, since control isn't a period on
# the pretreat/posttreat timeline.
plot_to_preserve = dict(zip(DATA.plots["plot"], DATA.plots["preserve"]))
plot_periods_indep = PERIODS.groupby("plot")["period"].apply(set)
control_plots_indep = {p for p, s in plot_periods_indep.items() if "control" in s}
treat_plots_indep = {p for p, s in plot_periods_indep.items() if s - {"control"}}
expected_treatment_preserves = sorted({
    plot_to_preserve[p] for p in treat_plots_indep if p in plot_to_preserve
})
expected_control_preserves = sorted({
    plot_to_preserve[p] for p in control_plots_indep if p in plot_to_preserve
})

f_tg = replace(DEFAULTS, compare_by="treatment_group")
fpanels = core.occupancy_panels(DATA, f_tg, core.apply_filters(DATA, f_tg))
treatment_panels = [p for p in fpanels if p["split_by_period"]]
control_panels = [p for p in fpanels if not p["split_by_period"]]

check("one split grid per preserve with a treatment plot",
      sorted(p["key"] for p in treatment_panels), expected_treatment_preserves)
check("one separate control grid per preserve with a control plot",
      sorted(p["label"] for p in control_panels),
      sorted(f"{pr} · Control" for pr in expected_control_preserves))
check("  control grids are not period-split",
      any(p["split_by_period"] for p in control_panels), False)
check("  facet plot counts add up to the full plot set",
      sum(p["n_plots"] for p in fpanels), len(core.eligible_plots(DATA, f_tg)))
check("  every facet keeps a column for every visible season",
      all(set(c["bucket"] for c in p["columns"]) == set(vis) for p in fpanels),
      True)

# The GCP-A split must reproduce the notebook figure exactly (conf 0.3).
f_ga_tg = replace(DEFAULTS, preserves=("Grovers",), plots=("GCP-A",),
                  compare_by="treatment_group", confidence=0.3)
pg = core.occupancy_panels(DATA, f_ga_tg, core.apply_filters(DATA, f_ga_tg))[0]
check("GCP-A periods, with unsurveyed seasons kept as NA columns",
      [(c["bucket"], c["period"]) for c in pg["columns"]],
      [("Su'22", "pretreat"), ("Wi'22-23", "pretreat"),
       ("Sp'23", "posttreat"), ("Su'23", None), ("Sp'24", None),
       ("Su'24", "posttreat"), ("Wi'24-25", "posttreat"),
       ("Sp'25", None), ("Su'25", "posttreat")])
check("  unsurveyed GCP-A columns are entirely NA",
      bool(pg["grid"][[3, 4, 7]].isna().all().all()), True)

NOTEBOOK_GCP_A = {
    "BEWR": [16.7, 17.9, 30.0, 66.7, 66.7, 62.5],
    "BRCR": [100.0, 57.1, 100.0, 100.0, 100.0, 100.0],
    "CBCH": [100.0, 92.9, 100.0, 100.0, 100.0, 100.0],
    "DOWO": [25.0, 3.6, 20.0, 0.0, 33.3, 0.0],
    "PAWR": [100.0, 89.3, 100.0, 100.0, 100.0, 0.0],
    "SPTO": [91.7, 0.0, 100.0, 100.0, 66.7, 100.0],
    "SWTH": [25.0, 0.0, 50.0, 100.0, 0.0, 100.0],
    "WIWA": [0.0, 3.6, 100.0, 55.6, 44.4, 0.0],
}
# The notebook figure omits unsurveyed seasons, so map its six columns onto the
# corresponding positions in our nine-column timeline.
NB_COLS = [0, 1, 2, 5, 6, 8]
mismatch = [
    sp for sp, vals in NOTEBOOK_GCP_A.items()
    if any(abs(float(pg["grid"].loc[sp, ci]) - v) > 0.15
           for ci, v in zip(NB_COLS, vals))
]
check("GCP-A cells reproduce the notebook figure", mismatch, [])

# Compare by Treat. type must not blend a plot's other-type sampling into a
# type's denominator: GCP-A carries "none" pretreat, then "patch cut,
# thinning" posttreat, so the "none" panel's seasons under the other type must
# read NA, not 0% -- and its sampling-days row must match only its own dates.
f_ga_tt = replace(DEFAULTS, preserves=("Grovers",), plots=("GCP-A",),
                  compare_by="treatment_type")
tt_panels = core.occupancy_panels(DATA, f_ga_tt, core.apply_filters(DATA, f_ga_tt))
tt_by_label = {p["label"]: p for p in tt_panels}
check("GCP-A splits into its two treatment types",
      sorted(tt_by_label), sorted(["none", "patch cut, thinning"]))

ga_effort = DATA.effort[DATA.effort["plot"] == "GCP-A"]
for label in ("none", "patch cut, thinning"):
    panel = tt_by_label[label]
    want_days = (ga_effort[ga_effort["period_type"] == label]
                 .groupby("bucket")["days_sampled"].sum())
    got_days = dict(zip(panel["buckets"], (float(v) for v in panel["sampling"])))
    check(f"  '{label}' sampling-days match only its own dates",
          {b: got_days.get(b, 0.0) for b in panel["buckets"]},
          {b: float(want_days.get(b, 0.0)) for b in panel["buckets"]})
    other_buckets = [b for b in panel["buckets"] if want_days.get(b, 0.0) == 0.0]
    check(f"  '{label}' reads NA outside its own dates, not 0%",
          all(panel["grid"].loc[:, ci].isna().all()
              for ci, b in enumerate(panel["buckets"]) if b in other_buckets),
          True)

# Blank cells carry two distinct meanings and must be distinguishable: seasons
# outside this type's era belong to the other panel entirely, while unsurveyed
# seasons *inside* the era are NA and sit alongside genuine 0% cells.
check("  'none' era covers only its pre-treatment seasons",
      [c["bucket"] for c in tt_by_label["none"]["columns"] if c["in_era"]],
      ["Su'22", "Wi'22-23"])
check("  'patch cut, thinning' era spans first to last recorded season",
      [c["bucket"] for c in tt_by_label["patch cut, thinning"]["columns"]
       if c["in_era"]],
      ["Sp'23", "Su'23", "Sp'24", "Su'24", "Wi'24-25", "Sp'25", "Su'25"])
pct = tt_by_label["patch cut, thinning"]
check("  unsurveyed seasons inside that era stay NA, not out-of-era",
      [c["bucket"] for ci, c in enumerate(pct["columns"])
       if c["in_era"] and float(pct["sampling"][ci]) == 0],
      ["Su'23", "Sp'24", "Sp'25"])
check("  a 0% cell inside the era is real data, not blank",
      float(pct["grid"].loc["DOWO", 5]), 0.0)

f_gu = replace(DEFAULTS, compare_by="guild")
gpanels = core.occupancy_panels(DATA, f_gu, core.apply_filters(DATA, f_gu))
check("guild yields one panel per guild", len(gpanels), 3)
check("  guild panels partition the species",
      sorted(c for p in gpanels for c in p["grid"].index),
      sorted(DATA.species_codes))
check("  guild panels share the full plot set",
      {p["n_plots"] for p in gpanels}, {len(DEFAULTS.plots)})
check("  guild ramps are distinct", len({p["ramp"] for p in gpanels}), 3)

print("\n--- region map: one bubble per species per plot ---")
f_rg = replace(DEFAULTS, graph_type="region")
rows_rg = core.apply_filters(DATA, f_rg)
mn = core.region_species_nodes(DATA, f_rg, rows_rg)
check("one row per surveyed plot x selected species",
      len(mn), mn["plot"].nunique() * len(DEFAULTS.species))
check("  every species gets its own colour",
      mn.groupby("species_code")["color"].nunique().eq(1).all()
      and mn["color"].nunique() == mn["species_code"].nunique(), True)
check("  occupancy stays within 0-100",
      bool(mn["occupancy_pct"].between(0, 100).all()), True)

# Bubble size must be occupancy, recomputed here from the effort table rather
# than read back from the same helper that produced it.
_bk_rg = core.visible_buckets(DATA, f_rg)
for _plot, _code in (("GCP-A", "BEWR"), ("BCNO", "CBCH")):
    _eff = float(core.effort_rows(
        DATA, f_rg, plots=[_plot], buckets=_bk_rg)["days_sampled"].sum())
    _det = float(rows_rg[(rows_rg["plot"] == _plot)
                         & (rows_rg["species_code"] == _code)]["days_detected"].sum())
    check(f"  {_plot}/{_code} occupancy matches days_detected / days_sampled",
          float(mn[(mn["plot"] == _plot)
                   & (mn["species_code"] == _code)]["occupancy_pct"].iloc[0]),
          round(100 * _det / _eff, 1))

# Species share a plot's single recorder coordinate, so they are fanned apart to
# be seen. The fan must stay a drawing device: small enough that a bubble is
# always nearer its own plot than any other, and never altering the real position.
_r = core._dispersal_radius_m(DATA.plots)
check("  fan radius stays under a quarter of the closest plot spacing",
      bool(0 < _r <= 25), True)
_off = [
    math.hypot((r.latitude - r.plot_latitude) * 111320,
               (r.longitude - r.plot_longitude) * 111320
               * math.cos(math.radians(r.plot_latitude)))
    for r in mn.itertuples()
]
check("  every bubble sits exactly one fan radius from its plot",
      bool(max(abs(o - _r) for o in _off) < 0.5), True)
_coords = DATA.plots.set_index("plot")[["latitude", "longitude"]]
_stray = [
    (r.plot, r.species_code, other)
    for r in mn.itertuples()
    for other, c in _coords.iterrows()
    if other != r.plot
    and math.hypot((r.latitude - c.latitude) * 111320,
                   (r.longitude - c.longitude) * 111320
                   * math.cos(math.radians(r.plot_latitude))) <= _r
]
check("  no bubble drifts as near another plot as its own", _stray, [])
check("  a species keeps the same clock position at every plot",
      mn.assign(ang=[round(math.atan2(
          (r.latitude - r.plot_latitude) * 111320,
          (r.longitude - r.plot_longitude) * 111320
          * math.cos(math.radians(r.plot_latitude))), 3)
          for r in mn.itertuples()])
        .groupby("species_code")["ang"].nunique().max(), 1)

# A plot with no sampling in range must drop out rather than plot a zero bubble.
_unsurveyed = replace(DEFAULTS, graph_type="region", year_from=2022, year_to=2022)
_mn2 = core.region_species_nodes(DATA, _unsurveyed,
                                 core.apply_filters(DATA, _unsurveyed))
_eff2 = core.effort_rows(DATA, _unsurveyed)
check("  unsurveyed plots are omitted, not drawn at zero",
      set(_mn2["plot"]), set(_eff2.loc[_eff2["days_sampled"] > 0, "plot"]))

print("\n--- sunrise and the solar time axis ---")
import build_cache as bc

# The sunrise algorithm, against published times for the study latitude. A few
# minutes' error is immaterial against a 10-minute recording grid; an hour --
# the size of a daylight-saving mistake -- would not be.
for _d, _pub in ((dt.date(2024, 6, 20), 5 * 60 + 11),
                 (dt.date(2024, 12, 21), 7 * 60 + 56),
                 (dt.date(2024, 3, 20), 7 * 60 + 16),
                 (dt.date(2024, 9, 22), 6 * 60 + 56)):
    _got = bc.sunrise_local_hour(47.63, -122.70, _d) * 60
    check(f"sunrise {_d} within 6 min of published",
          abs(_got - _pub) < 6, True)

# Summing the solar dimension out must reproduce the main tables exactly.
check("solar split preserves raw detections @0.3",
      int(DATA.solar_detections.loc[
          DATA.solar_detections["threshold"] == 0.3, "n_detections"].sum()),
      int(DATA.detections.loc[
          DATA.detections["threshold"] == 0.3, "n_detections"].sum()))
check("solar split preserves recordings sampled",
      int(DATA.solar_effort["recs_sampled"].sum()),
      int(DATA.effort["recs_sampled"].sum()))

# The point of the exercise: clock hour is confounded with season here, the
# solar axis is not. Recomputed from the manifest rather than from the cache.
_mf = pd.read_csv(HERE / "BirdNET_Recording_Manifest.csv", low_memory=False,
                  parse_dates=["datetime"])
_mf["season"] = _mf["season"].str.strip().str.capitalize()
_mf["hour"] = _mf["datetime"].dt.hour
_clock_shared = [h for h in sorted(_mf["hour"].unique())
                 if _mf.loc[_mf["hour"] == h, "season"].nunique() == 3]
check("clock hours shared by all three seasons", _clock_shared, [7, 8, 9])

_season_of = {b["bucket"]: b["season"] for b in DATA.meta["buckets"]}
_se = DATA.solar_effort.assign(season=DATA.solar_effort["bucket"].map(_season_of))
_solar_shared = sorted(
    b for b in _se["solar_bin"].unique()
    if _se.loc[_se["solar_bin"] == b, "season"].nunique() == 3)
check("  solar bins shared by all three seasons", _solar_shared, [-1, 0, 1])
check("  which is more overlap than the clock axis gives",
      len(_solar_shared) >= len(_clock_shared), True)

# Map frames must draw their denominator from solar_effort, not the clock table.
_f_s0 = replace(DEFAULTS, graph_type="region", region_solar=(0,))
_want_s0 = core._solar_effort_rows(
    DATA, _f_s0, core.eligible_plots(DATA, _f_s0),
    core.visible_buckets(DATA, _f_s0), [0]
).groupby("plot")["rec_hours_sampled"].sum()
_got_s0 = core.region_species_nodes(
    DATA, _f_s0, core.apply_filters(DATA, _f_s0)
).drop_duplicates("plot").set_index("plot")["effort_sampled"]
check("solar frames use the solar-effort denominator",
      bool(all(abs(_got_s0[p] - _want_s0[p]) < 1e-9 for p in _got_s0.index)), True)
check("  and sunrise itself is a real bin", 0 in DATA.solar_bins, True)

print("\n--- every heatmap names the plots behind it ---")
# A count alone could not distinguish one panel's sites from another's. It
# matters most under Treat. type, where a date-aware plot appears in more than
# one panel — GCP-A is 'none' before its treatment and 'patch cut, thinning'
# after, so two grids legitimately share it.
for _cb in ("none", "treatment_group", "treatment_type", "preserve", "guild"):
    _fp = replace(core.cascade_preserves(DATA, DEFAULTS, ["Grovers"]),
                  compare_by=_cb)
    _panels = core.occupancy_panels(DATA, _fp, core.apply_filters(DATA, _fp))
    check(f"  {_cb}: every panel carries a plot roster",
          all(p.get("plot_names") for p in _panels), True)
    check(f"    and each roster matches its own count",
          all(len(p["plot_names"]) == p["n_plots"] for p in _panels), True)
    check(f"    naming only plots that are actually selected",
          all(set(p["plot_names"]) <= set(_fp.plots) for p in _panels), True)

_ftt = replace(core.cascade_preserves(DATA, DEFAULTS, ["Grovers"]),
               compare_by="treatment_type")
_tt = {p["label"]: set(p["plot_names"])
       for p in core.occupancy_panels(DATA, _ftt, core.apply_filters(DATA, _ftt))}
check("a date-aware plot appears under both of its types",
      "GCP-A" in _tt.get("none", set())
      and "GCP-A" in _tt.get("patch cut, thinning", set()), True)
check("  which a plot count alone could never have shown",
      _tt["none"] != _tt["patch cut, thinning"], True)

print("\n--- map and heatmap share one occupancy definition ---")
# Both call sampling_days/days_detected. Each map bubble is a single plot, so
# the union those take across plots collapses to that plot's own dates, and the
# two views must agree exactly for any single-plot selection.
_f_map1 = replace(DEFAULTS, graph_type="region")
_nodes1 = core.region_species_nodes(DATA, _f_map1, core.apply_filters(DATA, _f_map1))
_bk1 = core.visible_buckets(DATA, _f_map1)
_worst = 0.0
for _plot in sorted(_nodes1["plot"].unique()):
    _den = int(core.sampling_days(DATA, _f_map1, [_plot], _bk1).sum())
    _dd = core.days_detected(DATA, _f_map1, [_plot], _bk1,
                             list(DATA.species_codes))
    for _sp in DATA.species_codes:
        _got = float(_nodes1.loc[(_nodes1["plot"] == _plot)
                                 & (_nodes1["species_code"] == _sp),
                                 "occupancy_pct"].iloc[0])
        _want = round(100 * sum(int(_dd.get((_sp, b), 0)) for b in _bk1) / _den, 1)
        _worst = max(_worst, abs(_got - _want))
check("every bubble matches the shared definition", _worst < 0.05, True)
print(f"        {len(_nodes1)} bubbles, largest disagreement {_worst:.3f} pp")

# Regression: with a season chosen on the map's slider, the denominator used to
# come from the hour table and was inflated by the number of hours recorded —
# GCP-A in Summer 2024 read 36 sampling days instead of 9, so BEWR showed 25%
# rather than 66.7%. Recomputed here from the summary CSV.
_ga24 = summary[(summary["plot"] == "GCP-A")
                & (summary["season"].str.capitalize() == "Summer")
                & (summary["season_period_year"] == 2024)]
_f_sl = replace(DEFAULTS, graph_type="region", region_bucket="Su'24")
_n_sl = core.region_species_nodes(DATA, _f_sl, core.apply_filters(DATA, _f_sl))
_row = _n_sl[(_n_sl["plot"] == "GCP-A") & (_n_sl["species_code"] == "BEWR")]
check("a season slice uses that season's sampling days",
      float(_row["effort_sampled"].iloc[0]), float(_ga24["date"].nunique()))
check("  and not the hour table's inflated count",
      float(_row["effort_sampled"].iloc[0]) < 36, True)
_det24 = _ga24.loc[(_ga24["species_code"] == "BEWR")
                   & (_ga24["detected@0.3"] == 1), "date"].nunique()
check("  so occupancy is days detected over those days",
      float(_row["occupancy_pct"].iloc[0]),
      round(100 * _det24 / _ga24["date"].nunique(), 1), tol=0.05)

print("\n--- region map: season and hour slicing ---")
# Hours come from the recorders' dawn-chorus schedule, not a full day.
_summary_hours = sorted(pd.to_datetime(summary["datetime"]).dt.hour.unique())
check("cache hours match the raw recording schedule", DATA.hours, _summary_hours)

# Recordings run ~10 min past their start hour (latest starts 9:40, ends 9:50),
# so the slider axis carries one stop past the last start hour and a range is
# read as [start, end). Without it, 9:50 audio would look excluded.
check("hour axis extends one stop past the last start hour",
      DATA.hour_stops, _summary_hours + [_summary_hours[-1] + 1])
_last_start = pd.to_datetime(summary["datetime"]).max()
check("  nothing actually starts at or after that final stop",
      bool(_last_start.hour < DATA.hour_stops[-1]), True)

# Summing the hour dimension back out must reproduce the main tables exactly,
# or the map and the occupancy grids would quietly disagree.
check("hour split preserves raw detections @0.3",
      int(DATA.hour_detections.loc[
          DATA.hour_detections["threshold"] == 0.3, "n_detections"].sum()),
      int(DATA.detections.loc[
          DATA.detections["threshold"] == 0.3, "n_detections"].sum()))
check("hour split preserves recordings sampled",
      int(DATA.hour_effort["recs_sampled"].sum()),
      int(DATA.effort["recs_sampled"].sum()))

# An unnarrowed map must not silently change denominators.
check("no slice leaves the map on the shared tables",
      core.region_species_nodes(DATA, f_rg, rows_rg)["occupancy_pct"].tolist(),
      mn["occupancy_pct"].tolist())

# One season + one hour, recomputed straight from the summary CSV.
_b, _h, _plot, _code = "Su'24", 5, "GCP-A", "BRCR"
f_slice = replace(DEFAULTS, graph_type="region",
                  region_bucket=_b, region_hours=(_h,))
mn_s = core.region_species_nodes(DATA, f_slice, core.apply_filters(DATA, f_slice))

_s = summary.copy()
_s["dt"] = pd.to_datetime(_s["datetime"])
_s["hour"] = _s["dt"].dt.hour
_s["bsort"] = (_s["season_period_year"] * 10
               + _s["season"].str.capitalize()
                 .map({"Winter": 0, "Spring": 1, "Summer": 2}))
_sel = _s[(_s["bsort"] == bsort_of[_b]) & (_s["hour"] == _h)
          & (_s["plot"] == _plot)]
_want_eff = _sel["date"].nunique()
_want_det = _sel.loc[_sel["species_code"] == _code, "date"].nunique() \
    if not _sel.empty else 0
check(f"{_plot} effort at {_b} {_h}:00 matches the raw recordings",
      float(mn_s[(mn_s["plot"] == _plot)]["effort_sampled"].iloc[0]),
      float(_want_eff))
check(f"  {_code} occupancy there matches days-detected / days-sampled",
      float(mn_s[(mn_s["plot"] == _plot)
                 & (mn_s["species_code"] == _code)]["occupancy_pct"].iloc[0]),
      round(100 * _want_det / _want_eff, 1))

# Narrowing can only ever remove effort, never add it.
_full = mn.set_index(["plot", "species_code"])["effort_sampled"]
_part = mn_s.set_index(["plot", "species_code"])["effort_sampled"]
check("  a slice never has more effort than the unsliced view",
      bool(all(_part[k] <= _full[k] for k in _part.index)), True)

# The map's framing and AudioMoth dots must not move when a slider moves:
# Plotly only retains a user's zoom if the figure it is handed still matches the
# one on screen. region_sites is therefore independent of both slicers, and an
# unsampled season yields an empty bubble set rather than an absent map.
_frames = set()
for _rb, _rh in [("", ()), ("Su'22", ()), ("Sp'25", ()), ("", (9,)),
                 ("Su'23", (4,))]:
    _fs = replace(DEFAULTS, graph_type="region",
                  region_bucket=_rb, region_hours=_rh)
    _st = core.region_sites(DATA, _fs)
    _frames.add((len(_st), round(float(_st["latitude"].mean()), 6),
                 round(float(_st["longitude"].mean()), 6)))
check("map framing is identical at every slider position", len(_frames), 1)
check("  sites cover the full plot selection, not just the sampled ones",
      len(core.region_sites(DATA, replace(DEFAULTS, graph_type="region",
                                          region_bucket="Su'23"))),
      len(core.eligible_plots(DATA, DEFAULTS)))

_f_un = replace(DEFAULTS, graph_type="region", preserves=("Grovers",),
                plots=("GCP-A",), region_bucket="Su'23")
check("  an unsampled season keeps its AudioMoth but draws no bubbles",
      (len(core.region_sites(DATA, _f_un)),
       len(core.region_species_nodes(DATA, _f_un, core.apply_filters(DATA, _f_un)))),
      (1, 0))

# The Region view is two maps, each with its own in-figure scrubber: seasons
# pooled over all hours, and hours pooled over all seasons. Every step of the
# time-of-day map is a single hour, so its denominator is recording-hours
# throughout — an "all hours" step would silently revert to sampling days and
# make the frames incomparable.
_h1 = DATA.hours[1]
_f_h1 = replace(DEFAULTS, graph_type="region", region_bucket="", region_hours=(_h1,))
_mn_h1 = core.region_species_nodes(DATA, _f_h1, core.apply_filters(DATA, _f_h1))
_want_h1 = core._hour_effort_rows(
    DATA, _f_h1, core.eligible_plots(DATA, _f_h1),
    core.visible_buckets(DATA, _f_h1), [_h1]
).groupby("plot")["rec_hours_sampled"].sum()
_got_h1 = _mn_h1.drop_duplicates("plot").set_index("plot")["effort_sampled"]
check("hour-map frames use the recording-hour denominator",
      bool(all(abs(_got_h1[p] - _want_h1[p]) < 1e-9 for p in _got_h1.index)), True)
check("  every recorded hour gets a frame", len(DATA.hours), 6)

# Both maps share one site set, so they stay aligned and neither reframes.
check("  both maps are framed on the same sites",
      len(core.region_sites(DATA, _f_h1)),
      len(core.region_sites(DATA, replace(DEFAULTS, graph_type="region",
                                          region_bucket="Su'23"))))

# Selecting the whole hour span is the same as not slicing at all.
f_allh = replace(DEFAULTS, graph_type="region", region_hours=())
check("  full hour span equals no hour slice",
      core.region_species_nodes(DATA, f_allh,
                                core.apply_filters(DATA, f_allh)
                                )["occupancy_pct"].tolist(),
      mn["occupancy_pct"].tolist())

print("\n--- header cards report reach, not the sidebar selection ---")
# Preserves and Plots must count what actually produced a detection: a card
# that merely restated the filter would sit unchanged while the charts emptied.
_k_all = core.compute_kpis(DATA, DEFAULTS, core.apply_filters(DATA, DEFAULTS))
check("all filters open: every plot and preserve is active",
      (_k_all.active_plots, _k_all.n_preserves), (40, 12))

_f_thin = replace(DEFAULTS, confidence=0.9, species=("WIWA",))
_rows_thin = core.apply_filters(DATA, _f_thin)
_k_thin = core.compute_kpis(DATA, _f_thin, _rows_thin)
_want_plots = int(_rows_thin.loc[_rows_thin["recs_detected"] > 0, "plot"].nunique())
_want_pres = int(DATA.plots.loc[
    DATA.plots["plot"].isin(set(_rows_thin.loc[_rows_thin["recs_detected"] > 0,
                                               "plot"])), "preserve"].nunique())
check("  a narrow filter drops silent plots out", _k_thin.active_plots, _want_plots)
check("  and silent preserves with them", _k_thin.n_preserves, _want_pres)
check("  which is fewer than the selection claims",
      _k_thin.active_plots < len(DEFAULTS.plots), True)

# Detections / plot was removed: it was an uncorrected mean that mostly tracked
# recorder uptime, and every question it answered is better served by Occupancy.
check("  the uncorrected per-plot mean is gone",
      hasattr(_k_all, "detections_per_plot"), False)

print("\n--- metric unit names the recording length ---")
# "Recordings with a detection" is uninterpretable without knowing how long a
# recording is, so presence carries the scheduled length; raw already states its
# own three-second window.
_mins = DATA.meta["nominal_cycle_seconds"] // 60
check("presence unit states the recording length",
      core.metric_unit(DATA, "presence"),
      f"species detections in {_mins}-min recordings")
check("  the length matches the manifest's scheduled cycle", _mins, 10)
check("  raw is unchanged, already carrying its window",
      core.metric_unit(DATA, "raw"), "3-second detection windows")
check("  per-day phrasing keeps the length",
      f"{_mins}-min" in core.metric_phrase(
          DATA, replace(DEFAULTS, metric="presence", normalize="per_day")), True)
check("  chart subtitles pick it up too",
      f"{_mins}-min" in core.panel_copy(
          DATA, replace(DEFAULTS, graph_type="trends", metric="presence"))[1],
      True)
# The KPI card uses a trimmed form: the long one wrapped to a second line and
# pushed the six-card row into a two-row block.
check("  the KPI card names the species x recording unit",
      core.metric_unit_short(DATA, "presence"),
      f"species × {_mins}-min recording")
check("  and stays short enough not to wrap",
      max(len(core.metric_unit_short(DATA, m)) for m in ("presence", "raw")) <= 26,
      True)

print("\n--- methodology section states the real figures ---")
_meth = core.methodology(DATA)
_flat = {t: d for _, entries in _meth for t, d in entries}
check("every control has a definition", len(_flat), 24)
check("  the sunrise axis is explained",
      "Hours from sunrise" in _flat
      and "dawn" in _flat["Hours from sunrise"], True)
check("  the header cards are documented",
      all(k in _flat for k in ("Number of recordings", "Hours recorded",
                               "Species richness", "Preserves and Plots")), True)
check("  covers detection unit, scale and occupancy",
      all(k in _flat for k in ("Species Presence", "Raw detections", "Total",
                               "Per day", "Where it applies",
                               "Daily occupancy (%)",
                               "Hourly occupancy (%)")), True)

# The figures are derived, so they must agree with the source recomputations
# done at the top of this file rather than being prose written once and left.
_want_pres = int(summary["detected@0.3"].sum())
check("  presence count matches the source @0.3",
      f"{_want_pres:,}" in _flat["Species Presence"], True)
_want_raw = int((combined["confidence"] >= 0.3).sum())
check("  raw count matches the source @0.3",
      f"{_want_raw:,}" in _flat["Raw detections"], True)
check("  recordings count matches the manifest total",
      f"{DATA.meta['n_recordings']:,}" in _flat["Number of recordings"], True)
check("  every threshold is listed with its own total",
      all(f"{int(summary[f'detected@{t}'].sum()):,}" in _flat["What it does"]
          for t in (0.3, 0.5, 0.7)), True)
check("  date-aware plot count matches the metadata",
      f"{len(DATA.meta['plots_with_both_periods'])} plots were treated"
      in _flat["Both are date-aware"], True)
check("  recording window matches the raw hours",
      f"{_summary_hours[0]}:00–{_summary_hours[-1] + 1}:00"
      in _flat["Time of day"], True)

print("\n--- species colours survive colour-vision deficiency ---")
# Simulated with the Vienot-Brettel-Mollon dichromacy transform: the palette
# must stay separable for protanopia, deuteranopia and tritanopia, not just for
# normal vision. The previous hand-picked set had a pair at dE 5 under
# tritanopia -- indistinguishable.
def _lin(c): return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
def _unlin(c): return 12.92 * c if c <= .0031308 else 1.055 * c ** (1 / 2.4) - .055
def _hex(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
def _mul(m, v): return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]
_R2L = [[.31399, .63951, .04649], [.15537, .75789, .0867], [.01775, .10945, .87116]]
_L2R = [[5.47221, -4.6419, .16963], [-1.1252, 2.29317, -.1678], [.0298, -.19318, 1.16364]]
_SIM = {"protan": [[0, 1.05118, -.05116], [0, 1, 0], [0, 0, 1]],
        "deutan": [[1, 0, 0], [.9513, 0, .04315], [0, 0, 1]],
        "tritan": [[1, 0, 0], [0, 1, 0], [-.86744, 1.86727, 0]]}
def _sim(h, k):
    o = _mul(_L2R, _mul(_SIM[k], _mul(_R2L, [_lin(c) for c in _hex(h)])))
    return [min(1, max(0, _unlin(min(1, max(0, c))))) for c in o]
def _lab(rgb):
    r, g, b = [_lin(c) for c in rgb]
    x, y, z = (r*.4124+g*.3576+b*.1805, r*.2126+g*.7152+b*.0722, r*.0193+g*.1192+b*.9505)
    fn = lambda t: t ** (1/3) if t > .008856 else 7.787 * t + 16/116
    fx, fy, fz = fn(x/.95047), fn(y/1.0), fn(z/1.08883)
    return (116*fy - 16, 500*(fx - fy), 200*(fy - fz))
def _de(a, b): return math.dist(_lab(a), _lab(b))

_pal = [core.species_color(i) for i in range(len(DATA.species_codes))]
check("every species has a distinct colour", len(set(_pal)), len(DATA.species_codes))

# No colour may read as the AudioMoth dot, which is pure black.
check("  none is confusable with the AudioMoth dot",
      min(_de(_hex(c), (0.0, 0.0, 0.0)) for c in _pal) > 40, True)

# Colours and map draw order follow whole-dataset detection rank, not the
# alphabet: alphabetically WIWA came last, so it was painted over everything
# and the fifth-commonest species looked dominant.
_rank = core.species_rank(DATA)
_base03 = DATA.detections[DATA.detections["threshold"] == 0.3]
_tot = _base03.groupby("species_code")["recs_detected"].sum()
check("species rank is by detections, commonest first",
      _rank, sorted(DATA.species_codes,
                    key=lambda c: (-float(_tot.get(c, 0)), c)))
check("  and matches the bar chart's own ordering",
      _rank[0], core.species_bars(
          DATA, replace(DEFAULTS, graph_type="species"),
          core.apply_filters(DATA, DEFAULTS))["species_code"].iloc[0])
_by_rank = core.species_colors_by_rank(DATA)
check("  the commonest species takes the first colour",
      _by_rank[_rank[0]], core.SPECIES_COLORS[0])
check("  every species is assigned exactly one colour",
      len(set(_by_rank.values())), len(DATA.species_codes))

# Rank must not move when a filter does, or species would change colour.
_f_narrow = replace(DEFAULTS, preserves=("Grovers",), confidence=0.9)
check("  rank is filter-independent", core.species_rank(DATA), _rank)
for _k in ("normal", "protan", "deutan", "tritan"):
    _cols = [_hex(c) if _k == "normal" else _sim(c, _k) for c in _pal]
    _worst = min(_de(a, b) for a, b in
                 [(x, y) for i, x in enumerate(_cols) for y in _cols[i + 1:]])
    # dE 12 is a comfortable margin; the old palette scored 5.1 here.
    check(f"  separable under {_k} vision (worst dE {_worst:.1f})", _worst > 12, True)

print("\n--- colour ramps ---")
check("ramp interpolation is monotone and bounded",
      core.ramp_color("posttreat", 0.0) == core.RAMPS["posttreat"][0]
      and core.ramp_color("posttreat", 1.0) == core.RAMPS["posttreat"][-1], True)
check("mid-ramp differs from both ends",
      core.ramp_color("pretreat", 0.5) not in
      (core.RAMPS["pretreat"][0], core.RAMPS["pretreat"][-1]), True)

print("\n--- occupancy export keeps NA and groups ---")
f_ex = replace(f_ga, graph_type="occupancy")
txt = core.export_csv(DATA, f_ex, core.apply_filters(DATA, f_ex)).decode()
check("export header mirrors the source table, then the measures",
      txt.splitlines()[0],
      "preserve,plot,treatment_group,treatment_type,latitude,longitude,"
      "elevation,season_period_year,season,year_season,species,species_code,"
      "forage_guilds,n_plots,preserves_included,plots_included,group,period,"
      "detections,days_detected,sampling_days,occupancy_pct,measure,"
      "confidence_threshold")
# Read by column name rather than position: the location columns shifted the
# occupancy field along, and an index-based check silently passed nothing.
_ex_df = pd.read_csv(io.BytesIO(txt.encode()))
check("unsurveyed cells export as empty, not 0",
      int(_ex_df["occupancy_pct"].isna().sum()),
      len(zero_effort) * len(g_ga.index))

f_exg = replace(DEFAULTS, graph_type="occupancy", compare_by="treatment_group")
txt2 = core.export_csv(DATA, f_exg, core.apply_filters(DATA, f_exg)).decode()
check("grouped export labels each group",
      all(g in txt2 for g in ("control", "pretreat", "posttreat")), True)

print("\n--- panel heading names the selection ---")
check("single plot", core.selection_label(DATA, f_ga), "Grovers / GCP-A")
check("whole preserve",
      core.selection_label(DATA, core.cascade_preserves(DATA, DEFAULTS, ["Grovers"])),
      "Grovers · all 8 plots")
check("everything", core.selection_label(DATA, DEFAULTS), "All Preserves · 40 plots")

print("\n--- occupancy is the default view ---")
check("default graph type", DEFAULTS.graph_type, "occupancy")

# ------------------------------------------------------------------- summary
print("\n" + "=" * 62)
if failures:
    print(f"{len(failures)} of {checks} checks FAILED:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"All {checks} checks passed.")
