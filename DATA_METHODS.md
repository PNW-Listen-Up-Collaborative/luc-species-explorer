# Data Methods — LUC Species Detection Explorer

Every transformation between the source CSVs and what the dashboard displays.
All numbers below are reproduced from the actual data, not illustrative.

---

## 1. What a row means in each source file

This is the crux of the 287,399 vs 23,394 question.

### `Combined_BirdNET_Results.csv` — 287,399 rows

One row = **one 3-second BirdNET detection window**. Not one bird, not one
recording. BirdNET slides a 3-second window across each audio file and emits a
row every time it scores a species above 0.3 confidence.

```
rec                                species_code  confidence  start_s  end_s
Burley_BCNO_20220712_053000.wav    SWTH          0.4383      72.0     75.0
Burley_BCNO_20220712_053000.wav    SWTH          0.3489      78.0     81.0
Burley_BCNO_20220712_053000.wav    SWTH          0.3419      111.0    114.0
```

Those three rows are almost certainly **the same thrush**, singing repeatedly in
one recording.

The extreme case in your data: recording `Grovers_GCP-D_20220801_091000.wav`
contains **182 rows** for Spotted Towhee — one towhee singing near-continuously
through the clip, detected in 182 separate 3-second windows.

### `BirdNET_Recording_Species_Summary.csv` — 145,688 rows

One row = **one recording × one species**, including species that were *not*
heard. 18,211 recordings × 8 species = 145,688. This file carries the `detected`
0/1 flag and is the authoritative record of what was *sampled* (a recording with
zero detections exists here but cannot exist in the detection-level file).

---

## 2. Why 287,399 collapses to 23,394

At confidence ≥ 0.3:

| Quantity | Value |
|---|---|
| Raw detection windows | 287,399 |
| Distinct (recording × species) pairs with ≥1 detection | 23,394 |
| Mean raw detections per present pair | **12.3** |

Distribution of raw detections within a single present pair:

| | detections |
|---|---|
| min | 1 |
| 25th percentile | 2 |
| median | 5 |
| 75th percentile | 14 |
| max | 182 |

5,696 pairs have exactly one detection; 1,234 pairs have more than fifty.

So 23,394 is not a subset of 287,399 — it is the same data **counted in a
different unit**. 287,399 counts vocalization windows; 23,394 counts
"this species was present in this recording."

---

## 3. The two metrics — both selectable in the app

The **Detection unit** control switches between them; the KPI card and every
chart subtitle name the active unit.

| Threshold | Raw detections (`n_detections`) | Presence (`recs_detected`) | Days detected | Recording-hours detected |
|---|---|---|---|---|
| ≥ 0.3 | 287,399 | 23,394 | 4,399 | 10,053 |
| ≥ 0.5 | 182,773 | 17,130 | 3,681 | 7,989 |
| ≥ 0.7 | 113,153 | 12,068 | 3,046 | 6,059 |
| ≥ 0.9 | 49,558 | 6,435 | 2,041 | 3,615 |

The left column is the table you sent me — select **Raw detections** to see it.
**Presence** is the default.

### Why presence is the default (and why it's arguable)

- The design file's chart subtitle reads *"Summed 0/1 detections per season."*
- Your summary CSV ships a `detected` 0/1 column, implying it's the intended unit.
- Raw counts are dominated by vocal behavior, not abundance or occupancy: one
  chatty towhee contributes 182 to the raw total and 1 to presence.

**This choice changes conclusions.** Species ranking at conf ≥ 0.5:

| Species | Raw | Presence | Raw per presence |
|---|---|---|---|
| SWTH Swainson's Thrush | 59,284 | 4,182 | 14.2 |
| PAWR Pacific Wren | 56,025 | 3,613 | 15.5 |
| SPTO Spotted Towhee | 21,601 | 2,380 | 9.1 |
| CBCH Chestnut-backed Chickadee | 20,686 | 2,832 | 7.3 |
| WIWA Wilson's Warbler | 10,303 | 1,632 | 6.3 |
| BEWR Bewick's Wren | 7,703 | 813 | 9.5 |
| BRCR Brown Creeper | 6,770 | 1,539 | 4.4 |
| DOWO Downy Woodpecker | 401 | 139 | 2.9 |

Ranks **swap** between the two metrics: SPTO outranks CBCH on raw counts but
CBCH outranks SPTO on presence; likewise BEWR vs BRCR. Chickadees and creepers
call in short bursts; towhees and wrens sing persistently. Raw counts measure
"how much singing," presence measures "how widespread."

---

## 4. Confidence thresholds

The design mockup faked thresholding by scaling a fixed count
(`tf = {0.3: 1, 0.5: 0.7, 0.7: 0.42, 0.9: 0.2}`). The app does **not** do this.

For each threshold *t* ∈ {0.3, 0.5, 0.7, 0.9}, `build_cache.py` filters the raw
detection table with `confidence >= t` and re-aggregates from scratch. Four
independent passes.

Validation against the source's own precomputed columns:

| Threshold | App total | `sum(detected@t)` in summary CSV | Match |
|---|---|---|---|
| 0.3 | 23,394 | 23,394 | ✓ |
| 0.5 | 17,130 | 17,130 | ✓ |
| 0.7 | 12,068 | 12,068 | ✓ |
| 0.9 | 6,435 | `sum(max_confidence ≥ 0.9)` = 6,435 | ✓ |

0.9 has no precomputed column in your data — it's derived entirely from the raw
detection rows, which is why the raw file was needed.

---

## 5. Time buckets

Nine season-buckets. The subtlety: winter spans a year boundary, and your data
assigns `2022-2023 Winter` a `season_period_year` of **2023** (the end year).
A naive sort on that column places it *after* 2023 Summer, which is wrong.

Sort key = `season_period_year × 10 + season_rank`, where
`Winter=0, Spring=1, Summer=2` — matching the source's own `_season_ord`.

| Label | sort key | season | period year | source `year_season` |
|---|---|---|---|---|
| Su'22 | 20222 | Summer | 2022 | 2022 Summer |
| Wi'22-23 | 20230 | Winter | 2023 | 2022-2023 Winter |
| Sp'23 | 20231 | Spring | 2023 | 2023 Spring |
| Su'23 | 20232 | Summer | 2023 | 2023 Summer |
| Sp'24 | 20241 | Spring | 2024 | 2024 Spring |
| Su'24 | 20242 | Summer | 2024 | 2024 Summer |
| Wi'24-25 | 20250 | Winter | 2025 | 2024-2025 Winter |
| Sp'25 | 20251 | Spring | 2025 | 2025 Spring |
| Su'25 | 20252 | Summer | 2025 | 2025 Summer |

The Year range filter operates on `season_period_year`, so selecting 2025 yields
Wi'24-25, Sp'25, Su'25.

---

## 6. The cached tables

### `detections.csv.gz` — 2,434 rows

Grain: **bucket × plot × species × threshold**.

| Column | Meaning |
|---|---|
| `n_detections` | count of raw 3-second detection windows |
| `recs_detected` | distinct recordings containing ≥1 detection |
| `days_detected` | distinct calendar dates with ≥1 detection |
| `rec_hours_detected` | distinct (date, hour) pairs with ≥1 detection |
| `max_confidence` | highest confidence observed |
| `preserve`, `treatment_group`, `treatment_type`, `guild` | joined from plot metadata |

### `effort.csv.gz` — 117 rows

Grain: **bucket × plot**. Built from the recording inventory plus the manifest,
so it counts everything recorded, including silence.

| Column | Meaning |
|---|---|
| `recs_sampled` | distinct recordings |
| `days_sampled` | distinct dates recorded |
| `hours_sampled` | distinct clock hours (recordings only span 04:00–09:00) |
| `rec_hours_sampled` | distinct (date, hour) pairs recorded |
| `audio_seconds` | true audio duration, from manifest `file_size_bytes` |

### `plots.csv.gz` — 40 rows

Plot → preserve, treatment group, treatment type, comma-split components,
latitude, longitude. Verified 1:1 — no plot code appears under two preserves,
and each has exactly one coordinate pair.

---

## 7. Filter logic

Applied to the detection table as a single boolean mask:

```
threshold == selected confidence
season_period_year between year_from and year_to
season          in selected seasons
species_code    in selected species
preserve        in selected preserves
plot            in selected plots
plot's treatment components  intersects selected components
treatment_group per the rule below
```

**Treatment group** is a per-plot attribute in your data (not a year cutoff as in
the mockup):

- `control` / `pretreat` / `posttreat` → exact match
- `treat` → `pretreat OR posttreat`
- `all` → no restriction

**Treatment type components.** Real values are comma-joined phrases, split into
atomic components; a plot matches if *any* component is selected.

| Source value | Components | Plots |
|---|---|---|
| none | none | 30 |
| future invasive control | future invasive control | 2 |
| reforestation | reforestation | 2 |
| snags, cwd | snags, cwd | 2 |
| invasives control | invasives control | 1 |
| thinning | thinning | 1 |
| patch cut, thinning, snags, cwd | patch cut, thinning, snags, cwd | 1 |
| planting, invasive/brush control | planting, invasive/brush control | 1 |

Note 30 of 40 plots are `none` — deselecting that component alone drops the app
to 10 plots.

**Preserve ↔ Plot cascade.** Deselecting a preserve removes its plots;
reselecting adds all of them back. Manual plot deselections survive unrelated
preserve toggles.

**Numerator/denominator parity.** A single function, `eligible_plots()`,
determines which plots survive the filters, and *both* the detection counts and
the sampling-effort denominators derive from it. This was previously a bug: the
occupancy denominator ignored the treatment filters, so restricting to control
plots still divided by all 40 plots' sampling days, deflating every occupancy
cell. Now filtering to control gives 9 plots on both sides:

| Treatment group | Plots | Recordings | Hours | Detections @0.5 |
|---|---|---|---|---|
| all | 40 | 18,211 | 2,983.2 | 17,130 |
| control | 9 | 4,913 | 804.5 | 5,236 |
| pretreat | 21 | 9,214 | 1,509.7 | 8,854 |
| posttreat | 10 | 4,084 | 669.1 | 3,040 |

---

## 8. KPI formulas

At defaults (conf ≥ 0.5, presence, everything selected):

| KPI | Formula | Value |
|---|---|---|
| Presence / Raw detections | `sum(metric column)` over filtered rows | 17,130 |
| Species richness | count of species with detections | 8 |
| Active plots | distinct plots with detections | 40 |
| Detections / plot | 17,130 ÷ 40 | 428 |
| Recordings | `sum(recs_sampled)` over eligible plots × visible buckets | 18,211 |
| Hours recorded | `sum(audio_seconds) ÷ 3600` | 2,983.2 |

"Detections / plot" divides by **active** plots, not selected plots. With all 40
active these coincide; under a restrictive filter they won't.

### Recording length and Hours recorded

The recorder runs a **10-minute duty cycle** but captures **590 s** and sleeps
10 s. So "a 10-minute recording" is nominal — the audio is 9 m 50 s. Evidence:

- 18,193 of 18,211 files are 590.006 s ± 0.01 s, computed from `file_size_bytes`
  as `(bytes − 44) ÷ 96,000` (48 kHz, 16-bit, mono, 44-byte RIFF header). The
  modal file is exactly 56,640,488 bytes = 590.0 s.
- BirdNET's furthest detection window ends at exactly **590.0 s**, confirming it
  scored the full file and nothing was clipped.
- Consecutive recordings at a plot are 600 s apart — the cycle, not the duration.

**Hours recorded uses true audio duration**, summed per file:

| Definition | Value |
|---|---|
| Actual audio duration (**used**) | **2,983.2 h** |
| Nominal 10 min × 18,211 recordings | 3,035.2 h |
| 590 s × 18,211 recordings | 2,984.6 h |

The nominal figure overstates real audio by 51.9 h (1.7%).

**18 files are truncated** (4 s to 559 s — battery or card failures, mostly
Burley BCNO and the Grovers January 2025 deployment). They are kept as
recordings and contribute their true short durations, so effort stays honest.

> Note: the notebook's `n_hrs_recorded` is a *different quantity* — distinct
> clock-hour bins (745 globally, 4,040 plot-hours), inherited from the Task 2
> effort table. It is a bin count, not a duration. The dashboard's
> "Hours recorded" is audio duration.

### Which recordings count

`Recordings` counts every file in `BirdNET_Recording_Manifest.csv` that passes
the current filters — **including files where nothing was detected at any
confidence**. The manifest is the record of what was recorded; the detection
table can only show files where something was heard. This is why a file below
0.3 confidence is still known to have been sampled.

Manifest and summary cover an identical set of 18,211 recordings (verified:
symmetric difference is empty).

---

## 9. Chart aggregations

**Trends** — group by bucket, sum `recs_detected`:

```
Su'22 3,188 · Wi'22-23 1,467 · Sp'23 2,347 · Su'23 1,188 · Sp'24 976
Su'24 2,275 · Wi'24-25 841 · Sp'25 1,264 · Su'25 3,584      (sums to 17,130)
```

**Diversity** — group by bucket, count distinct species with `recs_detected > 0`:

```
Su'22 8 · Wi'22-23 7 · Sp'23 8 · Su'23 8 · Sp'24 8
Su'24 8 · Wi'24-25 7 · Sp'25 8 · Su'25 8
```

Winter drops to 7 — Swainson's Thrush is entirely absent, as expected for a
neotropical migrant.

**Species** — total per species, sorted descending.

**Compare by** splits either line chart into disjoint series that sum to the
same total. Treatment group uses fixed colors (control = neutral gray,
pretreat = light accent, posttreat = accent) in fixed order; other groupings are
alphabetical with a cycled palette.

**Occupancy** — the default view, and the only chart that is effort-corrected
by construction.

```
daily  cell = 100 x sum(days_detected)      / sum(days_sampled)
hourly cell = 100 x sum(rec_hours_detected) / sum(rec_hours_sampled)
```

summed over the plots in the panel, within the bucket. The effort row is
labelled **Sampling days** or **Recording hours** to match the active
granularity.

**A bucket with zero sampling effort renders NA, not 0.** Those seasons were
never surveyed at the selected plots; printing 0% would read as "species
absent" when the truth is "not looked for". Example — Grovers / GCP-A was not
sampled in Su'23, Sp'24 or Sp'25, so 24 of its 72 cells are NA. Exports write
these as empty strings rather than zeros.

**Compare by** splits the heatmap into one stacked panel per group, each with
its own colour ramp, following the notebook's dual-period figures:

| Group | Ramp | Source |
|---|---|---|
| pretreat | purple `#faf5f8` → `#6b1f4a` | Nb3 `CMAP_PRETREAT` |
| posttreat | blue `#f4f7fb` → `#2d5080` | Nb3 `CMAP_POSTTREAT` |
| control | neutral gray | not in the notebook's dual-period plots; gray matches control elsewhere in the dashboard |
| forage guild / preserve / treatment type | cycled teal, orange, green, wine | — |

Denominators are **group-specific for plot-level groupings** (treatment group,
treatment type, preserve), which genuinely partition the plots — control 9,
pretreat 21, posttreat 10. Forage guild partitions *species*, not plots, so
every guild panel shares the same sampling effort and differs only in which
species rows it shows.

**Region** — per plot, distinct species detected, plotted at the plot's recorded
GPS coordinates, marker shaded and sized by richness ÷ number of selected
species.

---

## 9a. Effort correction (Scale → Per day)

Sampling effort is badly unbalanced: 35 days in Sp'24 against 244 in Su'25.
Reading raw totals across seasons therefore partly compares *survey effort*
rather than birds.

```
per-day value = Σ detections ÷ Σ days_sampled
```

summed over the plots behind that series, within the bucket. This applies to
Trends and Species. Richness is a species count and is never normalised;
Occupancy is already a rate.

**This inverts the seasonal story.** Raw detections, all plots:

| Bucket | Total | Days sampled | Per day |
|---|---|---|---|
| Su'22 | 27,925 | 148 | 188.68 |
| Wi'22-23 | 12,817 | 232 | 55.25 |
| Sp'23 | 20,115 | 79 | 254.62 |
| **Su'23** | 20,609 | **44** | **468.39** |
| Sp'24 | 15,769 | 35 | 450.54 |
| Su'24 | 31,174 | 72 | 432.97 |
| Wi'24-25 | 6,611 | 74 | 89.34 |
| Sp'25 | 10,282 | 165 | 62.32 |
| **Su'25** | **37,471** | 244 | 153.57 |

Su'25 has the **largest total** but a middling rate — it simply had the most
recording days. Su'23 has a modest total but the **highest detection rate**, on
only 44 days. The peak bucket changes depending on which you read.

Denominators are **group-scoped**: with Compare by = Treatment group, each
series divides by its own plots' sampling days (control 9 plots, pretreat 21,
posttreat 10), so the series remain comparable to each other. Effort is drawn
from the summary file, so plots that recorded silence still count toward the
denominator — deriving it from detection rows alone would understate effort and
inflate the rates.

---

## 10. Integration audit

Cache reconciled against the raw sources:

| Check | Cache | Raw | |
|---|---|---|---|
| Raw detection rows @ 0.3 | 287,399 | 287,399 | ✓ |
| Recording × species pairs @ 0.3 | 23,394 | 23,394 | ✓ |
| Plots | 40 | 40 | ✓ |
| Preserves | 12 | 12 | ✓ |
| Species | 8 | 8 | ✓ |
| Buckets | 9 | 9 | ✓ |
| Recordings in effort table | 18,211 | 18,211 | ✓ |
| Per-preserve detections @ 0.5 | all 12 preserves | | ✓ |

`test_explorer.py` runs 55 further assertions, each recomputing the expected
value independently from the raw CSVs.

---

## 11. Known limitations

- **Presence ignores call intensity.** A plot where one wren sings all morning
  and a plot where twelve wrens each call once both score 1 presence per
  recording. Raw counts have the opposite bias.
- **BirdNET confidence is not probability of correctness.** Thresholds filter
  score, not verified accuracy; no manual validation is incorporated.
- **Unequal sampling effort across buckets.** Days sampled range 35 → 244. Use
  the **Scale → Per day** control (see §9a) rather than reading raw totals
  across seasons.
- **`hours_sampled` is capped at 6.** Recordings only span 04:00–09:00, so the
  hourly metric measures within-morning consistency, not full-day activity.
- **Hours recorded is inferred from file size**, not read from audio headers.
  The arithmetic is exact for uncompressed 48 kHz/16-bit/mono WAV and matches
  BirdNET's 590 s window extent, but it would be wrong if any file were stereo
  or a different sample rate.
- **Guild codes (BI, LUHI, TFI) are shown verbatim.** I did not invent
  expansions for them.
