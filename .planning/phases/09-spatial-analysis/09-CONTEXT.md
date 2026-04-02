# Phase 9: Spatial Analysis - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous workflow)

<domain>
## Phase Boundary

Moran's I spatial autocorrelation test on regression residuals, CUDS choropleth map of all municipalities, regional disparity analysis across 5 macro-regions, and LCoGS indicator heatmaps. All publication-ready at 300 DPI.

</domain>

<decisions>
## Implementation Decisions

### Moran's I
- Test on fixed-effects residuals from Phase 7 regressions
- At least primary regression outcome (LCoGS-3 surgical volume)
- Result logged to results/spatial/morans_i.csv with interpretation

### CUDS Choropleth
- All 5,571 municipalities rendered at 300 DPI minimum
- Colorblind-safe diverging palette
- State borders visible, legend included
- geopandas + matplotlib for rendering

### Regional Disparity
- Summary statistics (mean, median, IQR) for CUDS and each LCoGS indicator
- Across 5 macro-regions: Norte, Nordeste, Centro-Oeste, Sudeste, Sul
- Saved as results/tables/regional_disparity.csv

### LCoGS Heatmaps
- Temporal trends by region (2015-2023)
- Publication-ready figures

### Claude's Discretion
- Spatial weights matrix construction (queen contiguity vs k-nearest neighbors)
- Which shapefile source (geobr vs IBGE direct)
- Heatmap layout (seaborn heatmap vs custom matplotlib)
- Whether to use PySAL/libpysal or esda for Moran's I

</decisions>

<code_context>
## Existing Code Insights

- geopandas already pinned in pyproject.toml
- analysis/run_regressions.py produces residuals
- analysis/compute_dimensions.py produces CUDS scores
- extract_lcogs1.py has existing geospatial mapping patterns
- SciencePlots for publication-quality matplotlib styling

</code_context>

<specifics>
## Specific Ideas

- geobr Python package can provide municipality shapefiles
- PySAL/esda for Moran's I computation
- May need to add libpysal/esda to pyproject.toml

</specifics>

<deferred>
## Deferred Ideas

None — all SPAT requirements in scope.

</deferred>
