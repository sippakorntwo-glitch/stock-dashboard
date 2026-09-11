"""Final packaging on the feature branch; all application behavior remains tested."""
from pathlib import Path

def edit(path,old,new):
    p=Path(path);s=p.read_text()
    if old not in s and new in s:return
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected one anchor: {old[:80]}')
    p.write_text(s.replace(old,new),encoding='utf-8')

edit('deployment_seed.py',"'GLD','TLT')","'GLD','TLT','QQQI','SPYI')")
edit('deployment_seed.py','    if needs_publication(previous,report):',"    from catalog_extension import fingerprint\n    if needs_publication(previous,report) or (previous or {}).get('catalog_fingerprint') != fingerprint(universe):")
edit('backfill_returns.py','expected=table_returns(app.completed_daily_history(h)) if h is not None else {}',"expected=table_returns(app.completed_daily_history(h,now=meta.get('fetched_at') or rows.get(t,{}).get('Data_Time'))) if h is not None else {}")
edit('return_audit_ui.py',"        selected=st.date_input('Return As Of'", "        date_key='return_audit_date_'+ticker\n        existing=st.session_state.get(date_key)\n        if existing is not None and not first.date() <= existing <= default.date():\n            st.session_state[date_key]=default.date()\n        selected=st.date_input('Return As Of'")
edit('return_audit_ui.py','first-visible-candle to last-visible-candle','first-to-last candle of the selected preset period (not the current zoom)')
edit('ranking_board.py','ไม่ใช่ราคาใหม่ทั้ง 4,900 ตัวทุก 30 นาที',"ไม่ใช่ราคาใหม่ทั้ง {counts.get('total',0):,} ตัวทุก 30 นาที")
edit('.github/workflows/deploy_verify.yml','python -m pip install playwright==1.55.0','python -m pip install playwright==1.55.0 requests==2.34.2')
edit('.github/workflows/deploy_verify.yml','  browser:\n    needs: [seed, ranking]','  browser:\n    permissions:\n      contents: write\n    needs: [seed, ranking]')
edit('.github/workflows/deploy_verify.yml',"          PYTHONUNBUFFERED: '1'\n        run: python production_smoke.py", "          PYTHONUNBUFFERED: '1'\n          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n        run: python verify_workspace.py --production")
Path('RETURN_PERIODS.md').write_text('''# Auditable adjusted-close returns — v22

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
''',encoding='utf-8')
Path('RELEASE_NOTES_V22.md').write_text('''# Research Workspace 2026-09-12.22

## Coverage and filtering

The original 4,200-company selection is retained. The dated Nasdaq Trader ETF
directory expands the configured universe to 5,676 ETFs / 9,876 total members,
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
remains cached for 24 hours. All-catalog daily histories and weekly profiles
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
''',encoding='utf-8')
for name in ('assemble_screener_v21.py','.github/workflows/assemble_screener.yml','finish_release.py','finish_polish.py','.github/workflows/finish_release.yml','tidy_release.py'):
    Path(name).unlink(missing_ok=True)
print('Production packaging complete; no settings, private files or market observations deleted.')
