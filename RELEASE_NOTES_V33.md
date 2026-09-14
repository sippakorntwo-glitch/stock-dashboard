# Research workspace 2026-09-14.33

Users can screen companies but previously could not see their active fundamental criteria in the results. Research required reading separate snapshot tables, and personal settings disappeared between visits. This release connects screening, historical financials, peers and explicit price assumptions in the existing single-page workflow.

- Result views show active filter columns, their units and source dates. Individual conditions can be removed with exact counts of restored results. The default eight return periods, 500-row paging and full filtered CSV remain.
- An evidence-led summary and three research views organize the same sections. A selected-symbol navigation strip preserves context while scrolling. Data coverage is separate from investment quality.
- FY, quarterly and validated TTM charts connect revenue, margins, cash flow, debt and shareholder changes. Missing values remain missing. New share-count/issuance source fields populate on statement refresh; historical cash repurchases are not inferred share-count changes.
- Same-industry peers have dated observations, source/period/currency exclusion reasons and medians only with at least three comparable peers. Provider ratios without fiscal dates are visible but unranked.
- Bear/base/bull terminal-price scenarios expose growth, margins, multiples, dilution, horizon and required price return. They are not DCF or guaranteed fair values, exclude interim dividends, and require matching currency/share units for market comparisons. Financials and REITs use verified user-supplied BVPS/FFO inputs.
- Named workspaces persist privately in browser storage, with JSON import/export. Notes, tracking thresholds and dated comparison baselines persist as a browser-local draft. No private research is published to GitHub or a shared database. Clearing browser storage removes local saves; exports provide portability.
- A bounded ETF collector prepares fees, holdings and sector weights, retaining the last valid response. The page shows coverage and unknown source dates explicitly. CSV imports support dated issuer holdings; partial or differently dated portfolios cannot be described as complete current overlap. Price comparisons are not NAV tracking error.
- Refresh keeps the existing bounded quote service and coherent SQLite read snapshots. Peers and ETF comparisons join the page dependency set before data is read.

## Verification

Run `python -m pytest -q tests` with `requirements-dev.txt`. New tests cover period/FX mismatches, missing observations, actual Streamlit callbacks, scenario mathematics, browser-storage message handling and isolation, ETF source schemas, stale selections, and exact filter counts.

CI and deployed-browser verification exercise visible research modes, historical period controls, price assumptions and browser-local save/load, in addition to existing chart, volume, financial labels, filters, selection and refresh checks. The dated production report identifies the exact deployed version, target and tested commit; do not interpret a local/CI result as proof of production deployment.

Data availability depends on provider reports and collection schedules. Statements and fund holdings do not update with every market-price tick. Estimates, missing fields and source disagreements remain labelled; no synthetic observations are used to complete a table.
