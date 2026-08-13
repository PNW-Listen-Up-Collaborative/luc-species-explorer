# LUC Species Detection Explorer

Streamlit implementation of the `BirdNET Detection Explorer` design handoff,
wired to the real BirdNET acoustic dataset instead of the mockup's synthetic
rows.

## Run

```bash
pip install -r requirements.txt
python build_cache.py      # once — builds ./data from the source CSVs
streamlit run app.py
```

`build_cache.py` reads `Combined_BirdNET_Results.csv` (287k detection rows) and
`BirdNET_Recording_Species_Summary.csv` (145k recording × species rows) and
writes three small compressed CSVs plus a `meta.json` into `./data`. The whole
cache is ~33 KB, so every filter change is an in-memory pandas filter.

Verify the data layer at any time:

```bash
python test_explorer.py    # 55 checks, each recomputed from the raw CSVs
```

## Files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit UI — toolbar, KPIs, five chart views |
| `explorer_core.py` | Pure-pandas data layer and design tokens (no Streamlit import) |
| `theme.py` | Modernist tokens as injected CSS + shared Plotly layout |
| `build_cache.py` | One-time pre-aggregation of the source CSVs |
| `test_explorer.py` | Independent verification against the raw data |
| `data/` | Generated cache (safe to delete and rebuild) |

The data layer is deliberately free of Streamlit imports so it can be tested
headlessly and reused from a notebook.

## How the real data differs from the mockup

The design file runs on seeded synthetic data with a fixed shape. The real
dataset differs substantially, and the app follows the real data:

| | Mockup | Real data |
| --- | --- | --- |
| Preserves | 3 | 12 |
| Plots | 12 | 40 |
| Species | 8 eastern US codes | 8 Pacific NW codes |
| Treatment types | Burn / Graze / Mow / Reference | 8 comma-joined management phrases |
| Seasons | Spring / Summer / Winter | same |
| Buckets | 15 (2022–2026) | 9 (Su'22 → Su'25) |
| Guilds | 5 | 3 (BI, LUHI, TFI) |

### Decisions taken

**Confidence thresholds are genuine per-row filters.** The mockup fakes the
threshold by scaling a precomputed count (`tf = {0.3: 1, 0.5: 0.7, …}`). Here
each of 0.3 / 0.5 / 0.7 / 0.9 is computed by actually filtering the raw
detection table on `confidence >= t`. The 0.3/0.5/0.7 totals reproduce the
source's own precomputed `detected@…` columns exactly; 0.9 has no precomputed
column and is derived from the raw rows.

**Region is a real basemap.** The dataset carries per-plot latitude/longitude,
so the schematic dashed-box layout was replaced with an OpenStreetMap scatter
map, markers shaded and sized by species richness at that plot. The handoff
explicitly called for this swap once GPS was available.

**Treatment type pills are split on commas.** `patch cut, thinning, snags, cwd`
becomes four independently selectable components, so the pill group stays
compact and a plot matches if any of its components is selected.

**Winter buckets are labelled across both years.** The source assigns
`2022-2023 Winter` a `season_period_year` of 2023, so within a period-year the
order is Winter → Spring → Summer. Winter renders as `Wi'22-23` rather than an
ambiguous `Wi'23`.

**Treatment group is a plot attribute, not a year cutoff.** The mockup derives
pretreat/posttreat from a `treatYear` constant; the real data has an explicit
per-plot `treatment_group`, which is used directly.

### Deviations from the design worth noting

- **Detection metric.** "Total detections" is the summed 0/1 presence flag per
  recording × species, matching the design's own subtitle ("Summed 0/1
  detections per season"). The raw per-clip detection count is also cached as
  `n_detections` if you'd rather chart that instead.
- **Copy view link** writes the view state to a code block with Streamlit's
  built-in copy button. Streamlit can't write to the system clipboard directly,
  so the "Copied ✓" label reverts on the next interaction rather than after
  1.6s.
- **Segmented controls** are Streamlit's `st.segmented_control` restyled to
  square, joined, accent-filled segments. They are close but not pixel-identical
  to the design's flush-left custom control.
- **Season and Treatment type are checklist popovers, not pill groups.** The
  design uses multi-select chips for these two. Streamlit's `st.pills` did not
  reliably show its selected state under the restyle, so they use the same
  button-opens-checkbox-popover pattern as Species/Preserve/Plot. This also
  keeps the toolbar to two rows — the 10 treatment components needed a
  full-width row of their own as chips.
- **Occupancy** is rendered as a CSS grid rather than a Plotly heatmap, which
  matches the design's 2px-gap cells, `SAMP.` effort row, and gradient legend
  precisely. Hourly granularity uses distinct recorded (date, hour) pairs;
  recordings only span hours 04–09, so hourly denominators are small.

## Verification

`test_explorer.py` recomputes every expected value independently from the raw
CSVs rather than restating the app's own logic. It covers threshold totals and
monotonicity, per-species totals, preserve/season/treatment-group subsetting,
the preserve↔plot cascade (including that manual plot deselections survive an
unrelated preserve toggle), series partitioning, occupancy cell math, region
node totals, all five CSV export shapes, empty states, and year-range filtering.

A useful sanity signal beyond the assertions: the two neotropical migrants in
the species set, Swainson's Thrush and Wilson's Warbler, drop to ~0% winter
occupancy while the resident Pacific Wren and Chestnut-backed Chickadee stay
high year-round.
