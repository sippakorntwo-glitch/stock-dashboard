# Auditable adjusted-close returns — v22

The eight periods remain 1 Day, 3 Days, 7 Days, 1 Month, 6 Months, 1 Year,
3 Years and 5 Years (%). Price As Of is immediately before the return columns.

Default cumulative return = (ending adjusted close / starting adjusted close - 1) * 100.
Day horizons count completed observed daily-session changes: N changes require
N+1 closes. Calendar horizons use the LAST observed close ON OR BEFORE the
calendar boundary. No 21/252-session approximation. A boundary gap exceeding
seven calendar days or an invalid endpoint is unavailable, not a shifted baseline.
Six years of source history are requested; pre-inception history is never made up.

Return Calculation Details exposes requested and actual starting dates, the end
date, both adjusted prices, calculation status and snapshot reconciliation.
Its end-date control can select a past date (including the external site's month end).

Cumulative (Adjusted Close) is the default. Annualized (3Y / 5Y only) changes only
the displayed/screened 3Y and 5Y values to ((end/start)^(12/months)-1)*100. The
corresponding CSV headers explicitly say Annualized. Daily trading scores do not
change when switching display modes. Nested audited inputs survive the cache,
frame and export pipeline. Method version 3 distinguishes the prior-boundary rule.

These are provider-adjusted market-price return proxies, not certified fund NAV
returns, distribution yields, revenue growth or investor returns after fees,
taxes or currency conversion. External fund pages may show NAV, price-only,
month-end or annualized results. Match definitions and dates before comparing.

Daily snapshots conservatively exclude the acquisition day's candle. A previously
partial candle cannot be promoted by recalculating it after midnight. The minute
price card and 5-minute chart have separate timestamps and are display-only;
they do not overwrite the completed daily close, return inputs or scoring data.
