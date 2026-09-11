# Research Workspace 2026-09-12.22

## Coverage and filtering

The original 4,200-company selection is retained. The dated Nasdaq Trader ETF
directory expands the configured universe to 5,676 ETF/ETP directory entries / 9,876 total members,
including QQQI and SPYI. This is a dated US-listed directory, not all worldwide
funds, an AUM ranking or a guarantee that every provider field exists.

Advanced Filters supports multiple Industry / ETF Category, Sector, Country,
Fund Family, Exchange and Currency selections; return minimum/maximum bounds;
price, liquidity, volatility and reported fundamental metrics; data age,
required returns, technical conditions and session favourites. Conditions are
AND across fields, OR inside a category. Active filters exclude missing numeric
inputs unless explicitly opted in. No missing value is converted to zero. Profile
As Of is separate from Price As Of. No implicit currency conversion is performed.

## Freshness without bulk page-load calls

The selected-symbol Minute Price card checks Yahoo one-minute observations about
every 60 seconds during weekdays 04:00-20:00 America/New_York, with 30-minute
polling outside that request window. This is not an exchange-holiday calendar or
a guarantee that the market is open. The provider may delay observations. The
card identifies its bar-start time, acquisition time and observed age and
includes extended hours when available. A second acquisition is checked by the
browser verifier, rather than just updating a cosmetic clock.

One background quote worker, four queued symbols, 64 retained price records,
120 requests/hour/server, per-symbol TTL and a 15-minute rate-limit circuit
breaker protect the application. Old observations retain their real timestamps
on failure. There is no extra account or paid provider integration.

The selected 5-minute chart checks for updates about once per minute while its
fragment is active, retaining the existing 60 chart requests/hour/server ceiling.
It does not rebuild all 9,876 rows on chart-only refreshes. Long chart history
remains cached for 24 hours. All-catalog daily histories and incrementally refreshed profiles
remain scheduled, incremental, bounded Actions jobs, not an intraday stream of
the entire market. Top 10 remains a separate 30-minute board with its original
entry safeguards. Minute observations do not turn stale scores into buy signals.

## Interface and safety

Navy/cyan/violet styling, colored metric accents, visible focus outlines, section
navigation, responsive layout and unchanged signed gain/loss colors. Uploads
remain limited to 5 MB, usage telemetry stays disabled, and uploaded personal
CSV data is not published to GitHub. The public reader receives no writing token.

## Verification

Unit/AppTest, Python 3.12/3.14 validation, independent return arithmetic and the
strict browser checks cover all research sections, table and Top 10 selection,
QQQI, combined filters, annualized exports, empty/invalid filters, real minute
refresh, chart ranges/inspector, data-quality downloads and mobile dimensions.
Dated reports on verify/v22-results distinguish local CI from production and
show source SHA, target URL and actual results. A green collection job alone
is not evidence of full market-data completeness. Consult the published counts.

The Nasdaq ETF flag also includes exchange-traded notes; these are identified in their security names and are not legally the same as investment funds. First-time chart requests wake the page as soon as the background load finishes, while routine intraday refreshes remain confined to the chart fragment.

Applied filter receipts expose the exact completed filter state and result count. CSV export uses that displayed result without triggering an unrelated page rerun. Browser checks wait for the actual applied state before downloading, not for a guessed sleep interval. Metadata queues retain stock/ETF and profile/dividend fairness while prioritizing missing and then oldest observations.
