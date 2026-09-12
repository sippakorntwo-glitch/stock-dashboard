# Company Financial Review — 2026-09-13.28

## What is displayed

The company-specific 360-degree review is organized into Income Statement,
Profitability & Capital Efficiency, Growth, Balance Sheet & Leverage, Liquidity,
Cash Flow & Earnings Quality, Valuation, Shareholder Distributions, and Analyst
Expectations. Market/technical indicators follow separately. Fund observations
retain their existing asset-aware view; company profit/debt ratios are not
manufactured for gold, bond or other funds. The duplicate company-number table
in the lower fundamentals section is removed; business context, official filing
links and distributions remain.

Each metric shows a value/unit, an illustrative screening reference, an
assessment with explanation, and the actual basis. The metric name alone has a
keyboard-focusable tooltip covering definition, formula, inputs, filing period,
source and limitations. A mobile glossary, CSV export and fiscal-year history
are included. The audit stays in the backend; raw JSON/status panels are not
reintroduced on the public page.

## Ratio definitions and cautions

- D/E uses **interest-bearing debt / equity**, not total liabilities / equity.
  The latter is separately labeled. The provider debtToEquity percentage is
  divided by 100 to display times. Source raw observations are preserved.
- ROE/ROA use average beginning/end equity/assets when calculated from filings.
  No average is inferred when the opening balance is absent. Non-positive equity
  or ratio denominators do not produce a favorable ratio.
- EBIT = consolidated pretax earnings + interest expense. Operating Income is
  separate. EBITDA = EBIT + reported D&A is a disclosed proxy, not adjusted
  management EBITDA. Gross Profit is reported or same-context revenue minus cost.
- FCF = operating cash flow minus PP&E capital expenditure; unreported capital
  spending is not treated as zero. This definition does not claim to include
  every acquisition or intangible investment.
- ROIC = NOPAT / average(equity + interest-bearing debt - cash). NOPAT uses
  operating income times one minus the reported effective tax rate. Effective
  tax requires positive pretax earnings and a rate between 0 and 1. All debt
  components and both balance dates must be observed. Goodwill/R&D/leases are
  not additionally adjusted. No WACC is invented: the optional WACC input is a
  user assumption, and the interface labels any comparison accordingly.
- P/B (P/BV) is the standard Price/Book label used for the requested P/BE field.
  A discount to book is not proof of undervaluation or company quality.

Screening ranges are transparent, illustrative configuration, not universal
financial standards or investment recommendations. Financial-services/real-
estate/unknown-sector industrial ratios are flagged for sector-specific review.
Absolute monetary amounts have no universal ideal. High yields, margins, ROE,
low multiples or buybacks are not by themselves buy signals. Nothing here
changes the existing trading score, entry policy, chart formulas or Top 10.

## Data provenance and alignment

The official SEC companyfacts bulk archive is used to add up to four fiscal
years for every mapped company supported by standard consolidated US-GAAP tags.
It avoids thousands of API calls on page loads. Identity is matched using the
SEC ticker-to-CIK map; individual archive members must match that CIK. Response
size/time, member size, TLS host and declared project contact are bounded.
403/429 stops further work and opens the existing 24-hour source circuit.
Periodic enrichment uses the existing single-writer publication lock and checks
that the previous snapshot did not change before publishing a new generation.

Computed statement ratios use the same filing accession, currency and fiscal
period. Comparative opening balances must be in the same filing. Fiscal years
are not silently relabeled as TTM; provider trailing/forward figures retain
separate labels and unknown field dates are stated. No FX conversion, segment
mixing, ADR/share conversion, loss-base growth percentage or pre-inception data
is invented. Source amounts and provider originals are not overwritten.

A full audit checks every catalog member against every defined metric, including
N/A, missing, N/M, invalid and available states. An independent arithmetic
checker recalculates displayed values from their declared inputs. This is not
an independent certification of every original issuer/provider figure. Custom
XBRL tags, IFRS-only filings, special investment vehicles and unreported inputs
can remain unavailable. A successful job is not a claim of 100% field coverage.

## Sources

Definitions and context:
- SEC: https://www.sec.gov/about/reports-publications/beginners-guide-financial-statements
- SEC API and bulk format: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- ROIC/WACC discussion: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/articles/ROICrules.html

The ratio thresholds are the app's disclosed screening assumptions, not
thresholds asserted by these sources. Dated backend reports and per-company CSV
coverage distinguish tested software, collected source data and missing fields.
