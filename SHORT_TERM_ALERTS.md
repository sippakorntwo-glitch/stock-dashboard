# Market events and short-term LINE reports

The automatic event monitor uses `news-events-intraday-v2`. The daily 100-point
pullback ranking is independent. The complete dashboard catalog includes stocks
and funds; the event pool uses verified USD common stocks only. Legacy manual
`scan`/`preview` commands retain their previous daily-research model.

## Discovery and evidence

- Include all validated eligible USD common stocks from the catalog, subject to
  a technical maximum of 5,000, ranked by average completed 20-session dollar
  turnover. The previous version retained only 1,000. Require $5m average dollar
  turnover and 250,000 average daily shares. The baseline must end on the
  previous NYSE trading session. There is no $10 filter or price floor for
  watching events. Funds and other security types remain in the dashboard's
  searchable catalog but are not silently treated as common-stock scan coverage.
- Read quotes in batches of 100 and reject stale, future or declared-delayed
  observations. Prioritize absolute day/gap/from-open movement and volume;
  reserve news checks for both negative and positive movers. Rotate quote order
  between 10-minute slots, so a provider time limit does not repeatedly exclude
  the same suffix. Inspect news for at most 20 stocks (12 strongest plus 8
  rotating candidates), and 5-minute charts for at most 10 (six priority plus
  four rotating places among the remaining news candidates) within a 240-second
  provider-work budget. This is bounded coverage, not continuous monitoring or
  full news/chart analysis of every listed stock.
- Require a relevant event headline published within 36 hours with publisher,
  URL and source time. Include results, contracts, guidance, regulation, supply,
  production capacity and other defined material events. Exclude generic stock
  opinions, retirement articles and call schedules. An unreadable feed means
  missing evidence, not no news and not a positive/negative interpretation.
- An explicit Toshiba + HDD + capacity/production expansion relationship can
  link competitor news to WDC/STX even without provider ticker association.
  Mark that relationship and pricing/supply explanation as an inference. Do not
  claim future capacity is already operating or that a headline proves the
  entire cause of a price move. Other news still needs company relevance.
- Verified news and a fresh sharp decline appear as `recovery_watch` even if
  technical data are missing. No invented entry/stop/target is attached. Prices
  below $1 are visible as news watches but cannot generate a purchase plan.

## Conditional plans

Use closed 5-minute bars, session VWAP and time-matched cumulative RVOL against
at least 10 prior sessions. Regular/pre-market minimum RVOL is 1.5x/2x, session
dollar turnover $10m/$5m; pre-market also needs 200,000 shares. Below $5 require
RVOL 2x, one million session shares and $20m regular/$10m pre-market turnover.
Regular-session volume is never substituted for missing pre-market volume.

Require price above VWAP with EMA alignment, valid market context, and a
conditional break of recent resistance. A day or opening gap below -3% needs
two closes above VWAP, three rising lows and at least +1% in the last 30 minutes
before a recovery plan can qualify. A large fall alone is not an entry condition.
Reject chasing, unsuitable stops and net 2R targets beyond the available daily
range budget or known previous-day resistance.

After screening, refresh prices. Quotes must be at most 3 minutes old and the
last closed bar at most 6 minutes old. Delivery expires with the quote. Plans
have a maximum 15-minute validity and end before opening/closing boundaries.
Rescan next-session opportunities rather than carrying today's levels forward.

## Costs and execution

Dime's normal paid commission is $0.01/share per side below $6.67 and 0.15% per
side from $6.67. The model adds a 0.20% spread allowance, 0.10% slippage and minor
fees. It does not assume the user's first monthly transaction is free. Estimated
round-trip costs are about 0.61% at $10, 0.71% at $5 and above 1.3% at $2; exact
model output depends on the maximum entry price. Targets must clear these costs.

Source checked 2026-10-02: https://dime.co.th/th/invest/stock-us
RVOL method: https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/RTA-Methodology.pdf
Bars API: https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html

These are conditional long plans in USD before personal tax/FX, not executable
broker quotes or submitted orders. The free source lacks separately timed bid/
ask observations. Check the current Dime spread (<=0.20%), limit price, supported
order types and ticker availability before acting. A stop is a planning level;
gaps can pass it. The stated net R:R assumes the whole position exits at target
2; partial exits at target 1 reduce the combined result.

## Dashboard and LINE

The workflow is scheduled every 10 minutes during the possible US pre-market/
regular window; the exchange calendar filters holidays and DST. GitHub may start
runs late. Publish `line-alert-media/event-board.json`; the dashboard checks this
file every 30 seconds and shows source timestamps and a warning after 15 minutes.
Dashboard refresh does not mean prices stream every 30 seconds.

The coverage panel separates the last observed scan from the latest published
pool. For example, 999/1,000 means 999 usable quotes out of that report's
1,000-stock pool, not 999 out of the complete catalog. Quote observations can
be missing, stale, delayed or otherwise invalid; the difference is not a count
of failed HTTP requests. New reports separately record quote attempts, usable
quotes, unattempted symbols, news checks, passing news and chart checks.

The latest configured pool is read through the dashboard's existing asynchronous
ranking cache. A newer pool can be displayed while the last market report still
uses the old 1,000-stock pool. Its count never replaces the historical report's
denominator or pretends a closed-market scan occurred. Metadata distinguishes
catalog security types, preliminary candidates, validated eligible candidates
and exclusions caused by the technical cap. Preliminary candidates have not
passed full validation and are not advertised as eligible scan coverage.
If cached daily history has not reached the required `baseline_day`, the panel
shows the affected count and that US-market reference date. An empty prepared
pool while history awaits refresh is not presented as an empty market or a new
live scan; the last report retains its original denominator and visible events.

The dashboard shows up to 20 news-qualified choices, with numbered details and
chart controls for each. LINE still selects up to five; the first five dashboard
positions follow the same ordering. Missing qualifying events are not padded.

Existing quota-planned summaries continue before and during market hours. A
new event with absolute day move >=7%, RVOL >=2 and session turnover >=$5m, or a
new qualified plan, may use an extra alert. Extra alerts are capped at two per
trading day and 20% of the monthly allowance (60 when the allowance is 300),
sharing the same overall monthly quota ledger. Never send repeatedly merely
because the same story's price changed. Distinguish an event notice from its
later plan transition. Reserve a durable body, quota charge and retry UUID
before pushing; an uncertain retry uses exactly the same request.

Each LINE round has up to five combined plan/event cards, explanations and a
one-page PNG. No padding to five. Empty summaries are limited to once per
pre-market/regular session; previously delivered event-only summaries are
deduplicated. Full reports and rejection counts are auditable. A new model has
no measured forward profitability; assess actual filled setups and net costs,
not subsequent highs or unfilled targets, when evaluating it.


## Numbered Thai decision reports (2026-10-03)

The same ordered list supplies LINE text, PNG and the first five dashboard
positions; additional event rows extend the dashboard to at most 20, each with
its own details. Each stock has company/industry, dated revenue growth and net margin
when the statements support them, up to two translated headlines with original
source links, business implications, price trend, and a conditional plan or
reasons to wait. Each stock shows its current USD price next to explicitly labeled SMA20/50/200 prices. Definitions are omitted from the compact reports.

Daily SMA20/50/200 use completed sessions only; fewer than the required bars
leave a value missing. Extreme differences between the latest daily price and
SMA20 suspend the displayed averages pending a price-basis review (for example
an incompletely restated corporate action). This is separate from intraday
VWAP, which approximates session VWAP from 5-minute typical prices and volume.
Company statements keep their actual fiscal periods and source; undated profile
ratios cannot support growth claims. Business directions are conditional
mechanisms, not invented management forecasts.

The complete pool travels as bounded gzip/base64 data in pool version 3 so the
ranking remains below the provider's 1 MB limit. Its authoritative `count` is
available without decompression; an empty outer `items` array does not mean the
pool is empty. Company evidence and daily averages retain their validated ticker
association. The scanner checks encoding, decompression bounds, counts and
symbol identity before selecting stocks. Version 2 context-only compressed
pools remain readable during the transition.

Thai translation runs offline before the final quote refresh. Public original
headlines and opening company descriptions are the only model inputs. The CPU
model is official Qwen3-4B Q4_K_M (Apache-2.0), pinned at bc640142c66e1fdd12af0bd68f40445458f3869b;
the official llama.cpp runtime is b11349 (MIT). Downloads are SHA-256 checked.
Exact-source translations are cached, reviewed finance translations have
priority, and automatic results are checked for numbers, negation and selected
financial terms. The model has no tools or credentials and cannot change a
trade signal. Missing/failed translations display a short Thai pending label
and the original source link, rather than an untranslated English headline.
Source: https://huggingface.co/Qwen/Qwen3-4B-GGUF
Runtime: https://github.com/ggml-org/llama.cpp

The requested format-update sample has a durable, recipient-scoped version key.
It shares the same monthly quota and two-extra-round daily cap; reruns cannot
send the sample again. Scheduled invocations remain in monitor mode.


The compact revision removes the glossary from LINE, the PNG footer and the
event panel. News sources are links only, without publisher/date captions or
repeated English headlines. English headlines go through the Thai translator;
proper names are protected with reversible placeholders. If validation fails,
show a short Thai pending label with the source link, never fabricated news.
The most recent reviewed headlines also resolve at render time, so a repaired
translation can appear immediately without changing its original market time.
