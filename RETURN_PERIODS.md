# Watchlist cumulative returns

The table, sort choices, return tooltips and filtered CSV use one period registry:

| Label | Stored key | Starting observation |
|---|---|---|
| 1 Day (%) | Return_1D | One completed trading-session change |
| 3 Days (%) | Return_3D | Three completed trading-session changes |
| 7 Days (%) | Return_7D | Seven completed trading-session changes |
| 1 Month (%) | Return_1M | Calendar month boundary |
| 6 Months (%) | Return_6M | Six-calendar-month boundary |
| 1 Year (%) | Historical_Return | Twelve-calendar-month boundary |
| 3 Years (%) | Return_3Y | Thirty-six-calendar-month boundary |
| 5 Years (%) | Return_5Y | Sixty-calendar-month boundary |

Return (%) = (ending adjusted close / starting adjusted close - 1) × 100.

Day windows use completed daily observations, not calendar days. N daily changes
require N + 1 daily closes. Month/year windows use the first observed close on or
after the calendar boundary, matching the existing table convention. Stored
history must reach back to that boundary. A gap greater than seven calendar days
at the starting boundary is not silently treated as a full window. Six years of
history are requested so ordinary long-listed securities have a true five-year
starting close rather than an almost-five-year series.

No substitution of 21 sessions for a month or 252 sessions for a year. Invalid
endpoint prices and insufficient histories remain unavailable, not 0%. Existing
3-month and 2-year internal fields remain available to legacy analytics but are
not shown among the eight requested table columns. The scoring model is unchanged.

The intraday chart is a different data frequency: its range return starts at the
first intraday bar within the displayed sessions, whereas the watchlist measures
completed daily close-to-close changes. Neither is CAGR, a revenue growth rate,
or guaranteed portfolio performance. Prices are provider-adjusted; no fees,
taxes or currency conversion are applied.

`backfill_returns.py` restores the checksum-verified checkpoint, recalculates the
whole canonical universe, extends real price history with paced requests, and
atomically publishes the new summary/details/checkpoint. Calculation-only
refreshes do not rewrite the original observation timestamp. The dated report
is stored at `dashboard-data/dashboard/returns-backfill-latest.json`. The normal
price update pipeline also computes the eight fields on subsequent updates.
