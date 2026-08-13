"""
Pre-aggregate the raw BirdNET outputs into small compressed CSV caches for the
LUC Species Detection Explorer Streamlit app.

Run once (or whenever the source CSVs change):

    python build_cache.py

Inputs (same folder):
  - Combined_BirdNET_Results.csv          detection-level rows, confidence >= 0.3
  - BirdNET_Recording_Species_Summary.csv full recording x species grid (incl. zeros)

Outputs (./data/):
  - detections.csv.gz   bucket x plot x species x threshold -> detection metrics
  - effort.csv.gz       bucket x plot -> sampling effort (recs / days / hours)
  - plots.csv.gz        plot -> preserve, treatment group/type, lat/lon
  - meta.json            buckets, species, guilds, treatment components, thresholds

Confidence thresholds are computed as genuine per-row filters on the raw
detection table, so 0.9 is as real as 0.3.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"

# --------------------------------------------------------------- solar time
# Clock hour is not comparable across seasons here: sunrise on the Kitsap
# Peninsula moves about two and three-quarter hours between June and December,
# so 5 AM is well after dawn in summer and well before it in winter. Binning by
# hours relative to sunrise makes "the first hour after dawn" mean the same
# thing in every season.
#
# Timestamps are Pacific wall-clock time (the source subset was filtered to
# 4-10 AM Pacific), so the UTC offset is -7 under daylight saving and -8
# otherwise. The DST rule is inlined rather than taken from zoneinfo, which on
# Windows needs the separate tzdata package and would fail at build time.
SOLAR_BIN_MIN, SOLAR_BIN_MAX = -2, 5


def _us_dst(d: dt.date) -> bool:
    """US daylight saving: second Sunday in March to first Sunday in November."""
    mar = dt.date(d.year, 3, 8)
    mar += dt.timedelta(days=(6 - mar.weekday()) % 7)
    nov = dt.date(d.year, 11, 1)
    nov += dt.timedelta(days=(6 - nov.weekday()) % 7)
    return mar <= d < nov


def sunrise_local_hour(lat: float, lon: float, d: dt.date) -> float | None:
    """
    Sunrise as a local Pacific decimal hour, via the standard NOAA algorithm.

    Accurate to a few minutes against published tables for this latitude, which
    is far finer than the 10-minute recording grid it gets compared against.
    The -0.833 degree altitude accounts for atmospheric refraction and the
    apparent radius of the solar disc, matching the usual definition.
    """
    n = d.toordinal() - dt.date(2000, 1, 1).toordinal() + 0.0009
    J = n - lon / 360.0
    M = (357.5291 + 0.98560028 * J) % 360
    Mr = math.radians(M)
    C = 1.9148 * math.sin(Mr) + 0.02 * math.sin(2 * Mr) + 0.0003 * math.sin(3 * Mr)
    L = (M + C + 180 + 102.9372) % 360
    Lr = math.radians(L)
    Jt = 2451545.0 + J + 0.0053 * math.sin(Mr) - 0.0069 * math.sin(2 * Lr)
    decl = math.asin(math.sin(Lr) * math.sin(math.radians(23.4397)))
    latr = math.radians(lat)
    cos_w = ((math.sin(math.radians(-0.833)) - math.sin(latr) * math.sin(decl))
             / (math.cos(latr) * math.cos(decl)))
    if abs(cos_w) > 1:
        return None                        # no sunrise/sunset at this latitude
    w = math.degrees(math.acos(cos_w))
    utc_hour = ((Jt - w / 360.0) - 2451545.0 + 0.5) % 1.0 * 24.0
    return utc_hour + (-7 if _us_dst(d) else -8)

COMBINED = HERE / "Combined_BirdNET_Results.csv"
SUMMARY = HERE / "BirdNET_Recording_Species_Summary.csv"
MANIFEST = HERE / "BirdNET_Recording_Manifest.csv"
GPC_METADATA = HERE / "GPC_Metadata.csv"

# AudioMoth WAVs are 48 kHz, 16-bit, mono => 96,000 bytes of audio per second,
# after a 44-byte RIFF header. Verified against the data: the modal file is
# 56,640,488 bytes = exactly 590.0 s.
WAV_BYTES_PER_SECOND = 48_000 * 2 * 1
WAV_HEADER_BYTES = 44

# The recorder runs a 10-minute duty cycle but captures 590 s and sleeps 10 s,
# so "a 10-minute recording" is nominal. Durations below are the real ones.
NOMINAL_CYCLE_SECONDS = 600
TYPICAL_RECORDING_SECONDS = 590

THRESHOLDS = [0.3, 0.5, 0.7, 0.9]

# Season ordering within a season_period_year. The winter season spans a year
# boundary ("2022-2023 Winter") and the source data assigns it the *end* year as
# its season_period_year, so within a period-year winter comes first, then
# spring, then summer. This matches the source's own `_season_ord` column.
SEASON_RANK = {"Winter": 0, "Spring": 1, "Summer": 2}
SEASON_ABBR = {"Spring": "Sp", "Summer": "Su", "Winter": "Wi"}

SPECIES_NAMES = {
    "BEWR": "Bewick's Wren",
    "BRCR": "Brown Creeper",
    "CBCH": "Chestnut-backed Chickadee",
    "DOWO": "Downy Woodpecker",
    "PAWR": "Pacific Wren",
    "SPTO": "Spotted Towhee",
    "SWTH": "Swainson's Thrush",
    "WIWA": "Wilson's Warbler",
}

SPECIES_SCI = {
    "BEWR": "Thryomanes bewickii",
    "BRCR": "Certhia americana",
    "CBCH": "Poecile rufescens",
    "DOWO": "Dryobates pubescens",
    "PAWR": "Troglodytes pacificus",
    "SPTO": "Pipilo maculatus",
    "SWTH": "Catharus ustulatus",
    "WIWA": "Cardellina pusilla",
}

# Foraging guild codes present in the source data.
GUILD_NAMES = {
    "BI": "Bark insectivore",
    "LUHI": "Lower/understory insectivore",
    "TFI": "Tree foliage insectivore",
}


def bucket_label(season_period_year: int, season: str) -> str:
    """'Su'22' style short axis label; winter shows both years it spans."""
    yy = str(season_period_year)[2:]
    if season == "Winter":
        prev = str(int(season_period_year) - 1)[2:]
        return f"Wi'{prev}-{yy}"
    return f"{SEASON_ABBR[season]}'{yy}"


def bucket_sort(season_period_year: int, season: str) -> int:
    return int(season_period_year) * 10 + SEASON_RANK[season]


def load_treatment_periods() -> pd.DataFrame:
    """
    Date-aware treatment group per (plot, date), from Task 1 GPC metadata.

    The manifest carries only a *static* per-plot treatment_group. For the 15
    plots that were treated partway through monitoring, that static label
    mislabels every recording on the other side of the treatment date. The
    notebook calls this `treatment_group_by_date` and recommends it for any
    before/after analysis, so it is what the dashboard uses.
    """
    meta = pd.read_csv(
        GPC_METADATA,
        low_memory=False,
        usecols=["plot", "datetime", "treatment_group", "treatment_type"],
        parse_dates=["datetime"],
    )
    meta["date"] = meta["datetime"].dt.date
    return (
        meta.drop_duplicates(subset=["plot", "date"])[
            ["plot", "date", "treatment_group", "treatment_type"]
        ].rename(columns={"treatment_group": "period",
                          "treatment_type": "period_type"})
    )


def attach_period(df: pd.DataFrame, periods: pd.DataFrame,
                  static_col: str = "treatment_group") -> pd.DataFrame:
    """Merge the date-aware period on, falling back to the static label."""
    out = df.merge(periods, on=["plot", "date"], how="left")
    out["period"] = out["period"].fillna(out[static_col])
    if "treatment_type" in out.columns:
        out["period_type"] = out["period_type"].fillna(out["treatment_type"])
    return out


def split_treatment_types(value: str) -> list[str]:
    """Real treatment_type values are comma-joined phrases; split into components."""
    if pd.isna(value):
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ effort
    # The summary grid is the authoritative recording inventory: it contains a
    # row per (recording, species) including recordings where nothing was heard,
    # which the detection-level table by definition cannot show.
    summary = pd.read_csv(
        SUMMARY,
        low_memory=False,
        usecols=[
            "rec", "preserve", "plot", "treatment_group", "treatment_type",
            "latitude", "longitude", "elevation", "datetime", "season", "year",
            "year_season", "season_period_year", "species_code",
        ],
    )

    summary["season"] = summary["season"].astype(str).str.strip().str.capitalize()

    recs = summary.drop_duplicates("rec").copy()

    # Join true audio duration from the manifest. The manifest is the record of
    # what was *recorded* (a file with no detection at any confidence still
    # appears there), and it is the only source of file size.
    manifest = pd.read_csv(
        MANIFEST, low_memory=False, usecols=["filename", "file_size_bytes"]
    )
    manifest["audio_seconds"] = (
        (manifest["file_size_bytes"] - WAV_HEADER_BYTES) / WAV_BYTES_PER_SECOND
    ).clip(lower=0)

    missing = set(recs["rec"]) - set(manifest["filename"])
    if missing:
        print(f"WARNING: {len(missing)} recordings absent from the manifest; "
              f"their duration falls back to {TYPICAL_RECORDING_SECONDS}s")
    recs = recs.merge(
        manifest[["filename", "audio_seconds"]],
        left_on="rec", right_on="filename", how="left",
    )
    recs["audio_seconds"] = recs["audio_seconds"].fillna(TYPICAL_RECORDING_SECONDS)

    periods = load_treatment_periods()

    recs["datetime"] = pd.to_datetime(recs["datetime"], errors="coerce")
    recs["date"] = recs["datetime"].dt.date
    recs = attach_period(recs, periods)
    recs["hour"] = recs["datetime"].dt.hour
    recs["bucket_sort"] = [
        bucket_sort(y, s) for y, s in zip(recs["season_period_year"], recs["season"])
    ]
    recs["bucket"] = [
        bucket_label(y, s) for y, s in zip(recs["season_period_year"], recs["season"])
    ]

    # Sunrise depends only on (rounded position, date), and there are ~40 plots
    # over ~600 dates, so memoise rather than recomputing per recording.
    plot_pos = (recs.drop_duplicates("plot")
                .set_index("plot")[["latitude", "longitude"]].to_dict("index"))
    _sr_cache: dict[tuple, float | None] = {}

    def solar_offset(plot: str, date, hod: float) -> float:
        pos = plot_pos.get(plot)
        if pos is None or pd.isna(hod):
            return float("nan")
        key = (plot, date)
        if key not in _sr_cache:
            _sr_cache[key] = sunrise_local_hour(pos["latitude"], pos["longitude"], date)
        sr = _sr_cache[key]
        return float("nan") if sr is None else hod - sr

    def attach_solar(df: pd.DataFrame) -> pd.DataFrame:
        hod = df["datetime"].dt.hour + df["datetime"].dt.minute / 60.0
        off = [solar_offset(p, d, h)
               for p, d, h in zip(df["plot"], df["date"], hod)]
        df = df.assign(solar_offset=off)
        # Floor to whole hours: bin 0 is "sunrise to one hour after", bin -1 is
        # "the hour before sunrise". Clipped so a stray outlier cannot open a
        # near-empty bin at the end of the axis.
        b = df["solar_offset"].apply(
            lambda v: float("nan") if pd.isna(v) else math.floor(v))
        df["solar_bin"] = b.clip(SOLAR_BIN_MIN, SOLAR_BIN_MAX)
        return df

    recs = attach_solar(recs)

    effort = (
        recs.groupby(["bucket", "bucket_sort", "plot", "period", "period_type"],
                     as_index=False)
        .agg(
            recs_sampled=("rec", "nunique"),
            days_sampled=("date", "nunique"),
            hours_sampled=("hour", "nunique"),
            audio_seconds=("audio_seconds", "sum"),
        )
    )
    # Recording-hours: distinct (date, hour) pairs actually recorded.
    rec_hours = (
        recs.assign(date_hour=recs["date"].astype(str) + "T" + recs["hour"].astype(str))
        .groupby(["bucket", "plot", "period"], as_index=False)
        .agg(rec_hours_sampled=("date_hour", "nunique"))
    )
    effort = effort.merge(rec_hours, on=["bucket", "plot", "period"], how="left")

    # ------------------------------------------------------------- plot lookup
    plots = (
        summary.drop_duplicates("plot")[
            # Elevation is carried so exports can mirror the source table's
            # site block rather than a subset of it.
            ["plot", "preserve", "treatment_group", "treatment_type",
             "latitude", "longitude", "elevation"]
        ]
        .sort_values(["preserve", "plot"])
        .reset_index(drop=True)
    )
    plots["treatment_components"] = plots["treatment_type"].map(split_treatment_types)

    # -------------------------------------------------------------- detections
    combined = pd.read_csv(
        COMBINED,
        low_memory=False,
        usecols=[
            "rec", "plot", "preserve", "species_code", "confidence",
            "season", "season_period_year", "datetime", "forage_guilds",
        ],
    )
    combined["season"] = combined["season"].astype(str).str.strip().str.capitalize()
    combined["datetime"] = pd.to_datetime(combined["datetime"], errors="coerce")
    combined["date"] = combined["datetime"].dt.date
    combined["hour"] = combined["datetime"].dt.hour
    combined["date_hour"] = (
        combined["date"].astype(str) + "T" + combined["hour"].astype(str)
    )
    combined = combined.merge(
        plots[["plot", "treatment_group", "treatment_type"]], on="plot", how="left"
    )
    combined = attach_period(combined, periods)
    combined = attach_solar(combined)
    combined["bucket"] = [
        bucket_label(y, s)
        for y, s in zip(combined["season_period_year"], combined["season"])
    ]
    combined["bucket_sort"] = [
        bucket_sort(y, s)
        for y, s in zip(combined["season_period_year"], combined["season"])
    ]

    keys = ["bucket", "bucket_sort", "plot", "species_code", "period",
            "period_type"]
    frames = []
    for t in THRESHOLDS:
        sub = combined[combined["confidence"] >= t]
        agg = (
            sub.groupby(keys, as_index=False)
            .agg(
                n_detections=("confidence", "size"),
                recs_detected=("rec", "nunique"),
                days_detected=("date", "nunique"),
                rec_hours_detected=("date_hour", "nunique"),
                max_confidence=("confidence", "max"),
            )
        )
        agg["threshold"] = t
        frames.append(agg)

    detections = pd.concat(frames, ignore_index=True)
    detections = detections.merge(
        plots[["plot", "preserve", "treatment_group", "treatment_type"]],
        on="plot", how="left", suffixes=("", "_dup"),
    )
    detections = detections.drop(
        columns=[c for c in detections.columns if c.endswith("_dup")]
    )

    guild_by_species = (
        combined.drop_duplicates("species_code")
        .set_index("species_code")["forage_guilds"]
        .to_dict()
    )
    detections["guild"] = detections["species_code"].map(guild_by_species)

    # ------------------------------------------------------- calendar dates
    # The effort row sums recorder-days across plots, which is the right
    # denominator for occupancy but is not what anyone means by "how many days
    # did we record". Fifteen recorders over thirty dates is 148 recorder-days
    # and 30 calendar days. Distinct dates cannot be recovered by summing the
    # effort table, so the (plot, date) pairs are shipped directly — about 1,100
    # rows — and the union is taken at query time for whatever plots are chosen.
    # Hour is carried so the hourly toggle can union (date, hour) slots the same
    # way the daily one unions dates.
    dates = (
        recs[["bucket", "bucket_sort", "plot", "period", "period_type",
              "date", "hour"]]
        .drop_duplicates()
        .sort_values(["bucket_sort", "plot", "date", "hour"])
        .reset_index(drop=True)
    )

    # And the matching numerator: the (plot, date, hour) slots on which each
    # species was detected. Occupancy is the union of dates across the selected
    # plots over the union of dates sampled — a species counts for a date if it
    # was heard anywhere that day — which cannot be reconstructed from
    # per-plot totals, so the slots themselves are kept. ~28k rows.
    species_dates = []
    for t in THRESHOLDS:
        sub = combined[combined["confidence"] >= t]
        agg = (
            sub[["bucket", "bucket_sort", "plot", "period", "period_type",
                 "species_code", "date", "hour"]]
            .drop_duplicates()
        )
        agg["threshold"] = t
        species_dates.append(agg)
    species_dates = pd.concat(species_dates, ignore_index=True)

    # ------------------------------------------- hour-of-day slices (Region map)
    # The main tables collapse time of day away, but the Region map slices by it.
    # Kept as separate narrow tables rather than adding an `hour` key to the main
    # ones: every other view would then have to sum the hour out again on every
    # query, for a dimension only one view uses.
    #
    # At a fixed hour, a "recording-hour" is just a distinct date recorded in
    # that hour, so days and recording-hours coincide here by construction.
    hour_effort = (
        recs.groupby(["bucket", "bucket_sort", "plot", "period", "period_type",
                      "hour"], as_index=False)
        .agg(
            recs_sampled=("rec", "nunique"),
            days_sampled=("date", "nunique"),
            rec_hours_sampled=("date", "nunique"),
        )
    )

    hour_keys = ["bucket", "bucket_sort", "plot", "species_code", "period",
                 "period_type", "hour"]
    hour_frames = []
    for t in THRESHOLDS:
        sub = combined[combined["confidence"] >= t]
        agg = (
            sub.groupby(hour_keys, as_index=False)
            .agg(
                n_detections=("confidence", "size"),
                recs_detected=("rec", "nunique"),
                days_detected=("date", "nunique"),
                rec_hours_detected=("date", "nunique"),
            )
        )
        agg["threshold"] = t
        hour_frames.append(agg)
    hour_detections = pd.concat(hour_frames, ignore_index=True)

    # The same split again, but keyed by hours-relative-to-sunrise instead of
    # clock hour. This is what the Region map's time scrubber steps through:
    # the clock-hour axis is confounded with season, because the deployment
    # schedule itself tracked dawn (summer recording starts at 04:15, winter at
    # 07:50), so hours 4-5 exist only in summer and 8-9 mostly in winter.
    solar_effort = (
        recs.dropna(subset=["solar_bin"])
        .groupby(["bucket", "bucket_sort", "plot", "period", "period_type",
                  "solar_bin"], as_index=False)
        .agg(
            recs_sampled=("rec", "nunique"),
            days_sampled=("date", "nunique"),
            rec_hours_sampled=("date", "nunique"),
        )
    )
    solar_keys = ["bucket", "bucket_sort", "plot", "species_code", "period",
                  "period_type", "solar_bin"]
    solar_frames = []
    for t in THRESHOLDS:
        sub = combined[(combined["confidence"] >= t)
                       & combined["solar_bin"].notna()]
        agg = (
            sub.groupby(solar_keys, as_index=False)
            .agg(
                n_detections=("confidence", "size"),
                recs_detected=("rec", "nunique"),
                days_detected=("date", "nunique"),
                rec_hours_detected=("date", "nunique"),
            )
        )
        agg["threshold"] = t
        solar_frames.append(agg)
    solar_detections = pd.concat(solar_frames, ignore_index=True)

    _sa = int(solar_detections.loc[
        solar_detections["threshold"] == THRESHOLDS[0], "n_detections"].sum())
    _sb = int(detections.loc[
        detections["threshold"] == THRESHOLDS[0], "n_detections"].sum())
    assert _sa == _sb, f"solar split lost detections: {_sa} vs {_sb}"
    _sc = int(solar_effort["recs_sampled"].sum())
    assert _sc == int(effort["recs_sampled"].sum()), "solar split lost recordings"

    # Summing the hour dimension back out must reproduce the main tables exactly,
    # or the map would quietly disagree with the occupancy grids.
    _chk_a = int(hour_detections.loc[
        hour_detections["threshold"] == THRESHOLDS[0], "n_detections"].sum())
    _chk_b = int(detections.loc[
        detections["threshold"] == THRESHOLDS[0], "n_detections"].sum())
    assert _chk_a == _chk_b, f"hour split lost detections: {_chk_a} vs {_chk_b}"
    _chk_c = int(hour_effort["recs_sampled"].sum())
    _chk_d = int(effort["recs_sampled"].sum())
    assert _chk_c == _chk_d, f"hour split lost recordings: {_chk_c} vs {_chk_d}"

    # ------------------------------------------------------------------- meta
    buckets = (
        recs[["bucket", "bucket_sort", "season", "season_period_year", "year_season"]]
        .drop_duplicates()
        .sort_values("bucket_sort")
        .reset_index(drop=True)
    )

    all_types = set(effort["period_type"].dropna()) | set(
        detections["period_type"].dropna()
    )
    components = sorted(
        {c for t in all_types for c in split_treatment_types(t)}
    )

    species_codes = sorted(summary["species_code"].dropna().unique())

    meta = {
        "thresholds": THRESHOLDS,
        "buckets": buckets.to_dict("records"),
        "years": sorted(int(y) for y in recs["season_period_year"].unique()),
        "seasons": [s for s in ["Spring", "Summer", "Winter"]
                    if s in set(recs["season"])],
        "species": [
            {
                "code": c,
                "name": SPECIES_NAMES.get(c, c),
                "scientific": SPECIES_SCI.get(c, ""),
                "guild": guild_by_species.get(c, ""),
            }
            for c in species_codes
        ],
        "guild_names": GUILD_NAMES,
        "preserves": sorted(plots["preserve"].unique()),
        "treatment_groups": sorted(plots["treatment_group"].dropna().unique()),
        "treatment_components": components,
        "n_recordings": int(recs["rec"].nunique()),
        "n_summary_rows": int(len(summary)),
        "n_detection_rows": int(len(combined)),
        "total_audio_hours": round(float(recs["audio_seconds"].sum()) / 3600, 1),
        "nominal_cycle_seconds": NOMINAL_CYCLE_SECONDS,
        "typical_recording_seconds": TYPICAL_RECORDING_SECONDS,
        "periods": sorted(recs["period"].dropna().unique().tolist()),
        "plots_with_both_periods": sorted(
            recs.groupby("plot")["period"]
            .apply(lambda s: {"pretreat", "posttreat"}.issubset(set(s)))
            .loc[lambda x: x].index.tolist()
        ),
        "n_truncated_recordings": int(
            (recs["audio_seconds"] < TYPICAL_RECORDING_SECONDS - 10).sum()
        ),
        # Survey design is a dawn-chorus window, so this is a short contiguous
        # run of hours rather than a full 24.
        # Distinct recordings holding at least one detection of any species, per
        # threshold. Cannot be recovered from the aggregated tables: those sum a
        # per-species flag, so a file with three species counts three times.
        "recordings_with_detection": {
            str(t): int(combined.loc[combined["confidence"] >= t, "rec"].nunique())
            for t in THRESHOLDS
        },
        "hours": sorted(int(h) for h in recs["hour"].dropna().unique()),
        # Hours relative to sunrise. Negative is before dawn.
        "solar_bins": sorted(int(b) for b in recs["solar_bin"].dropna().unique()),
        "sunrise_note": (
            "Timestamps are Pacific wall-clock time; the source subset was "
            "filtered to 4-10 AM Pacific. Sunrise is computed per plot per "
            "date from latitude and longitude (NOAA algorithm), with the US "
            "daylight-saving rule applied."
        ),
    }

    # ------------------------------------------------------------------ write
    detections.to_csv(OUT / "detections.csv.gz", index=False, compression="gzip")
    effort.to_csv(OUT / "effort.csv.gz", index=False, compression="gzip")
    hour_detections.to_csv(OUT / "hour_detections.csv.gz", index=False,
                           compression="gzip")
    hour_effort.to_csv(OUT / "hour_effort.csv.gz", index=False, compression="gzip")
    solar_detections.to_csv(OUT / "solar_detections.csv.gz", index=False,
                            compression="gzip")
    solar_effort.to_csv(OUT / "solar_effort.csv.gz", index=False, compression="gzip")
    dates.to_csv(OUT / "dates.csv.gz", index=False, compression="gzip")
    species_dates.to_csv(OUT / "species_dates.csv.gz", index=False,
                         compression="gzip")
    plots.assign(
        treatment_components=plots["treatment_components"].map(lambda x: "|".join(x))
    ).to_csv(OUT / "plots.csv.gz", index=False, compression="gzip")
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2, default=str))

    print(f"detections.csv.gz  {detections.shape}")
    print(f"effort.csv.gz      {effort.shape}")
    print(f"hour_detections    {hour_detections.shape}")
    print(f"hour_effort        {hour_effort.shape}")
    print(f"plots.csv.gz       {plots.shape}")
    print(f"dates.csv.gz       {dates.shape}  "
          f"({dates['date'].nunique()} distinct calendar dates)")
    print(f"species_dates      {species_dates.shape}")
    print(f"solar_detections   {solar_detections.shape}")
    print(f"solar_effort       {solar_effort.shape}")
    print(f"hours               {meta['hours']}")
    print(f"solar bins          {meta['solar_bins']}")
    print(f"buckets             {list(buckets['bucket'])}")
    print(f"treatment comps     {components}")


if __name__ == "__main__":
    main()
