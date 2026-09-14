# Financial completeness and source reconciliation

The catalog audit visits every security, separately counting companies and funds.
A missing raw cell is not proof of an error: issuers do not all report inventory,
gross profit, repurchases, or the same banking/insurance statement structure.
Reported zero, an absent source value, a calculation with missing inputs, and an
inapplicable ratio remain distinct states. No job invents amounts to fill a table.

The Yahoo collector refreshes company statements independently of prices. An
incomplete response retains previously collected dated values and their original
fetch times. Failure and rate-limit cooldowns survive interrupted publication.
Routine collection runs four times daily, up to 400 due companies per batch,
with a two-day successful refresh target and oldest-attempt-first scheduling.
At 4,200 companies the configured maximum throughput covers a sweep in about
three days; provider delays, runner queues and cooldowns can extend that time.
New fiscal periods appear when the source publishes them, not automatically on
the first day of a calendar quarter/year. No annual version/date edit is needed.

The SEC reconciliation collector verifies the ticker through submissions and the
CIK in Company Facts. It fills only an existing dated cell in the same reporting
currency, using unambiguous directly reported US GAAP facts. Annual durations,
direct quarters and point-in-time balances remain distinct; six/nine-month YTD
cash flows are not treated as quarters. It does not infer reporting currency from
the trading currency, construct absent statement periods, convert ADR shares,
or substitute EBITDA for EBIT. Companies outside this coverage retain explicit
missing states.

Each recovered cell records its SEC concept, filing accession, filing date,
period start/end, currency and retrieval time. Tables and downloads preserve
source information. Source disagreements retain both reported amounts for
review; a verified disagreement in total liabilities excludes that amount from
the canonical liability ratio until reconciled. In particular, temporary or
convertible preferred equity is not automatically treated as a liability.
An SEC-owned fallback cell can follow a later verified filing for the exact
same reporting context; its revision records the prior amount and provenance.
Ambiguous SEC revisions are withheld from calculations while their original
raw amounts remain inspectable. Recovered cells stay in the refresh queue.

Collection is bounded, uses the shared SEC access circuit, and runs outside the
interactive page. A denial or rate limit stops requests and records a 24-hour
pause. The source check never bypasses that pause. Prepared snapshots publish
atomically under the same writer lock used by price collection.
SEC reconciliation is scheduled every two hours. The public browser suite and
whole-catalog audit run daily; known provider failures preserve the last good
snapshot and retry after their cooldown. A failed code regression is recorded
as a failure, not silently reclassified as a successful health check.

Actions preserve a per-security CSV with raw missing cells, missing calculated
metrics and SEC disagreements. `reports/company-fundamentals-v28.json` records
Yahoo refresh/audit progress; `reports/sec-financials-reconciliation.json` records
SEC checks and actual filled-cell counts. These are separate from browser test
results and do not assert every issuer filing has been manually verified.

Primary reference: [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
