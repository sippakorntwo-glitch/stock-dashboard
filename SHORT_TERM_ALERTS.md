# Short-term LINE reports

The scheduled LINE report uses `news-volume-intraday-v1`. The dashboard's
100-point daily pullback board remains daily research and does not select these
short-term plans. Legacy manual `scan`/`preview` commands retain their old model;
the automatic workflow uses only the scheduled short-term report.

## Selection

1. From the verified full stock catalog, retain at most 200 of the most liquid
   USD common stocks: price at least $10, average completed 20-session turnover
   at least $50 million and one million shares. No ETF padding. The baseline
   must end on the actual previous NYSE trading session.
2. Read fresh quotes, reject stale/future/delayed observations, and prioritize
   positive active movers. Inspect news for at most 16 and charts for at most 8
   each round, within a 150-second provider-work budget. This is bounded
   coverage, not a live scan of every listed stock.
3. Require a company-specific event headline published within 36 hours. Exclude
   earnings-call schedules, generic valuation/purchase opinions and price-only
   stories. A headline is labelled as such; it is not a reviewed article,
   verified positive sentiment, or proof that the event occurred that day.
4. Use closed 5-minute bars. Session VWAP resets at the start of pre-market or
   regular trading. Cumulative relative volume compares the same clock interval
   in at least 10 prior sessions. Require 1.5x regular / 2x pre-market, $10m / $5m
   session turnover, and 200,000 shares pre-market. No regular-volume substitute
   for missing pre-market observations. Traded volume is not net buying.
5. Require positive price/VWAP/EMA alignment and strength relative to SPY. Form
   a conditional break of recent resistance, a maximum limit price and swing/
   volatility stop. Reject chasing, unsuitable stops, or an estimated net 2R
   target outside the average daily range budget/known previous-day resistance.
6. Refresh quotes after scanning. Quotes must be <=3 minutes old; last completed
   bar <=6 minutes old. Plans expire after 15 minutes, at the opening for a
   pre-market plan, or before the close. Close the planned trade the same day;
   next-session candidates are rescanned instead of carrying today's levels.

## Execution and costs

All cards say **conditional plan**. The free source does not timestamp bid/ask
separately, so it cannot authenticate an executable spread. The user checks the
current Dime book (spread <=0.20%), the trigger close, limit price, order support
and availability of the ticker. Nothing submits or manages an order.

The gross target is derived from a net 2R requirement, not an analyst price
target or a predicted price. 0.61% round-trip cost allowance includes normal paid
Dime commissions, a 0.20% spread budget, 0.10% slippage allowance and minor fees.
It is a modelling allowance in USD before taxes/FX, not the user's actual bill.
Net R:R assumes all shares exit at target 2. Splitting exits at target 1 changes
the realised ratio. Stops are planning levels; a gap can trade through them.

Fee source checked 2026-10-02: https://dime.co.th/th/invest/stock-us
Time-matched-volume reference:
https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/RTA-Methodology.pdf
Data API: https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html

## Delivery, evidence and evaluation

Send zero to five candidates, never manufacture five. An empty/data-failure
summary is sent at most once per pre-market/regular session. Continue checking
later planned slots for qualified plans. LINE's monthly allowance remains a
hard ceiling, not a requirement to spend quota on weak ideas. Existing durable
reservation, retry UUID, quota ledger, calendar/DST and expiry checks remain.

Each prepared report is preserved as an immutable commit on `line-alert-media`
and as a short-lived workflow artifact. This is an audit trail, not actual
trades or realised P&L. This strategy version starts without forward performance
evidence. Before changing size or claiming an edge, review at least 30–50
independent filled paper/actual setups with their original publication times,
trigger/limit validity, missed fills, adverse gaps, costs, wins/losses, average
net gain/loss and expectancy. Never count an unfilled target hit as a win or use
later news to justify an earlier signal. An ambiguous bar that touches both
stop and target cannot establish which happened first.

The numeric thresholds are initial engineering choices. They have not been
optimised or validated as profitable by a historical or forward study.
