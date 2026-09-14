"""SEC recovery identity, accounting meaning, periods and conflict boundaries."""
from copy import deepcopy

import pytest

from sec_financials import historical_facts, merge_missing

CIK = 1774857
STAMP = '2026-09-14T08:00:00+00:00'
AS_OF = '2026-09-14'
SUBMISSION = {'cik': str(CIK), 'tickers': ['AARD'], 'name': 'Aardvark Therapeutics'}


def fact(value, *, start='2025-01-01', end='2025-12-31', filed='2026-03-23',
         form='10-K', accession='0001193125-26-119770'):
    row = {'val': value, 'end': end, 'filed': filed, 'form': form, 'accn': accession}
    if start is not None:
        row['start'] = start
    return row


def document(rows, currency='USD'):
    return {'cik': CIK, 'facts': {'us-gaap': {
        tag: {'units': {currency: values}} for tag, values in rows.items()}}}


def bundle():
    return {'schema': 1, 'ticker': 'AARD', 'currency': 'USD', 'source': 'Yahoo Finance financial statements',
            'fetched_at': '2026-09-13T00:00:00Z', 'observations': {}, 'errors': [],
            'annual': {
                'income': [{'end': '2025-12-31', 'values': {'revenue': 0}}],
                'balance': [{'end': '2024-12-31', 'values': {'totalAssets': 77507000,
                             'totalLiabilities': 132150000, 'stockholdersEquity': -54643000}}],
                'cashflow': [{'end': '2025-12-31', 'values': {'operatingCashflow': -50}}]},
            'quarterly': {
                'income': [{'end': '2026-06-30', 'values': {'revenue': 0}}],
                'balance': [],
                'cashflow': [{'end': '2026-06-30', 'values': {'operatingCashflow': -10}}]}}


def merge(source, data=None, submission=None, **kwargs):
    return merge_missing(data or bundle(), source, submission or SUBMISSION, cik=CIK,
                         fetched_at=STAMP, as_of=AS_OF, **kwargs)


def test_missing_values_fill_with_dated_evidence_without_mutating_input_or_inventing_periods():
    old = bundle(); before = deepcopy(old)
    source = document({'GrossProfit': [fact(120), fact(140, end='2024-12-31', start='2024-01-01')],
                       'OperatingIncomeLoss': [fact(-62725000)]})
    merged, report = merge(source, old)
    assert old == before
    row = merged['annual']['income'][0]
    assert row['values'] == {'revenue': 0, 'grossProfit': 120, 'operatingIncome': -62725000}
    assert len(merged['annual']['income']) == 1
    assert report['filled_count'] == 2
    provenance = row['field_provenance']['grossProfit']
    assert provenance == {'source': 'SEC EDGAR', 'tag': 'GrossProfit',
        'accession': '0001193125-26-119770', 'filed': '2026-03-23',
        'start': '2025-01-01', 'end': '2025-12-31', 'currency': 'USD',
        'url': 'https://www.sec.gov/Archives/edgar/data/1774857/000119312526119770/',
        'fetched_at': STAMP, 'form': '10-K'}
    assert row['field_fetched_at']['grossProfit'] == STAMP
    assert 'revenue' not in row['field_provenance']
    # Caller recomputes derived observations after integrating provenance.
    assert merged['observations'] == old['observations']


@pytest.mark.parametrize('change', [{'cik': 320193}, {'tickers': ['OTHER']}])
def test_both_submission_cik_and_ticker_identity_must_match(change):
    with pytest.raises(ValueError, match='mismatch|identity'):
        merge(document({'GrossProfit': [fact(120)]}), submission={**SUBMISSION, **change})


def test_company_facts_cik_must_match_even_when_submission_matches():
    with pytest.raises(ValueError, match='Company Facts CIK mismatch'):
        merge({'cik': 320193, 'facts': {}})


@pytest.mark.parametrize('currency', [None, '', 'usd', 'USD/shares'])
def test_missing_or_invalid_reporting_currency_is_never_guessed(currency):
    data = bundle(); data['currency'] = currency
    with pytest.raises(ValueError, match='financial currency'):
        merge(document({'GrossProfit': [fact(120)]}), data)


def test_other_currency_and_per_share_units_are_not_substituted():
    for unit in ('EUR', 'USD/shares', 'shares'):
        merged, report = merge(document({'GrossProfit': [fact(120)]}, currency=unit))
        assert merged == bundle() and report['filled_count'] == 0


def test_direct_quarter_is_accepted_but_ytd_and_annual_never_become_quarters():
    source = document({'GrossProfit': [fact(30, start='2026-04-01', end='2026-06-30',
                            filed='2026-08-14', form='10-Q')],
        'NetIncomeLoss': [fact(-60, start='2026-01-01', end='2026-06-30', filed='2026-08-14', form='10-Q')],
        'NetCashProvidedByUsedInOperatingActivities': [fact(-100, start='2025-07-01', end='2026-06-30',
                            filed='2026-08-14', form='10-K')]})
    merged, report = merge(source)
    assert merged['quarterly']['income'][0]['values'] == {'revenue': 0, 'grossProfit': 30}
    assert merged['quarterly']['cashflow'][0]['values'] == {'operatingCashflow': -10}
    assert report['filled_count'] == 1


@pytest.mark.parametrize('change', [
    {'filed': '2026-09-15'}, {'end': '2027-12-31'}, {'filed': '2025-12-30'},
    {'start': 'bad'}, {'form': '8-K'}, {'accn': 'invalid'}, {'val': True},
    {'val': float('nan')}, {'val': float('inf')}, {'form': '10-Q'},
])
def test_invalid_future_or_non_annual_context_is_not_recovered(change):
    source = document({'GrossProfit': [{**fact(120), **change}]})
    assert historical_facts(source, CIK, 'USD', AS_OF) == []


def test_instant_facts_require_exact_existing_date_and_no_duration():
    source = document({'AssetsCurrent': [fact(74137000, start=None, end='2024-12-31')],
        'LiabilitiesCurrent': [fact(4927000, start=None, end='2024-12-30')],
        'InventoryNet': [fact(999, start='2024-01-01', end='2024-12-31')]})
    merged, report = merge(source)
    values = merged['annual']['balance'][0]['values']
    assert values['currentAssets'] == 74137000
    assert 'currentLiabilities' not in values and 'inventory' not in values
    assert report['filled_count'] == 1


@pytest.mark.parametrize('second', [fact(121), fact(120, start='2025-01-02'),
                                  fact(120, accession='0001193125-26-119771')])
def test_ambiguous_latest_context_is_rejected_even_if_tag_or_value_looks_plausible(second):
    source = document({'GrossProfit': [fact(120), second]})
    merged, report = merge(source)
    assert merged == bundle() and report['filled_count'] == 0
    assert report['ambiguous'][0]['field'] == 'grossProfit'


def test_conflicting_revenue_aliases_do_not_use_priority_to_choose_a_value():
    source = document({'Revenues': [fact(100)],
                       'RevenueFromContractWithCustomerExcludingAssessedTax': [fact(120)]})
    assert historical_facts(source, CIK, 'USD', AS_OF) == []


def test_latest_filed_unambiguous_amendment_wins_for_missing_cell_only():
    source = document({'GrossProfit': [fact(120), fact(125, filed='2026-04-01', form='10-K/A')],
                       'Revenues': [fact(125, filed='2026-04-01', form='10-K/A')]})
    merged, report = merge(source)
    assert merged['annual']['income'][0]['values'] == {'revenue': 0, 'grossProfit': 125}
    assert report['conflicts'][0]['provider_value'] == 0
    assert report['conflicts'][0]['sec_value'] == 125


def test_reported_zero_is_preserved_and_absent_gross_profit_is_not_created():
    merged, report = merge(document({'OperatingIncomeLoss': [fact(-62725000)]}))
    values = merged['annual']['income'][0]['values']
    assert values['revenue'] == 0 and 'grossProfit' not in values
    assert report['filled_count'] == 1


def test_aard_liabilities_remain_unchanged_and_preferred_equity_difference_is_explained():
    source = document({'Liabilities': [fact(5394000, start=None, end='2024-12-31')],
        'RedeemableConvertiblePreferredStockCarryingAmount': [fact(126756000, start=None, end='2024-12-31')]})
    merged, report = merge(source)
    assert merged == bundle()
    conflict = report['conflicts'][0]
    assert conflict['provider_value'] == 132150000 and conflict['sec_value'] == 5394000
    assert conflict['preferred_equity_reconciliation']['value'] == 126756000
    assert report['filled_count'] == 0


def test_preferred_equity_difference_requires_same_filing_and_exact_reconciliation():
    for preferred in (fact(126756000, start=None, end='2024-12-31', accession='0001193125-26-000001'),
                      fact(126000000, start=None, end='2024-12-31')):
        _, report = merge(document({'Liabilities': [fact(5394000, start=None, end='2024-12-31')],
            'RedeemableConvertiblePreferredStockCarryingAmount': [preferred]}))
        assert 'preferred_equity_reconciliation' not in report['conflicts'][0]


def test_sec_payment_signs_become_canonical_outflows_and_negative_payment_tags_are_rejected():
    source = document({'PaymentsToAcquirePropertyPlantAndEquipment': [fact(10)],
                       'PaymentsOfDividends': [fact(-7)]})
    merged, report = merge(source)
    assert merged['annual']['cashflow'][0]['values'] == {'operatingCashflow': -50, 'capitalExpenditure': -10}
    assert report['filled_count'] == 1


def test_existing_explicit_period_start_prevents_incompatible_fill():
    data = bundle(); data['annual']['income'][0]['start'] = '2025-01-02'
    merged, report = merge(document({'GrossProfit': [fact(120)]}), data)
    assert merged == data and report['rejected_alignment'][0]['field'] == 'grossProfit'


def test_incompatible_starts_across_sec_fields_in_the_same_statement_are_not_combined():
    source = document({'GrossProfit': [fact(120)],
                       'OperatingIncomeLoss': [fact(-10, start='2025-01-02')]})
    merged, report = merge(source)
    assert merged['annual']['income'][0]['values'] == {'revenue': 0, 'grossProfit': 120}
    assert report['rejected_alignment'][0]['field'] == 'operatingIncome'


def test_identical_duplicates_are_harmless_and_recovery_is_idempotent():
    source = document({'GrossProfit': [fact(120), fact(120)]})
    merged, report = merge(source)
    again, repeated = merge(source, merged)
    assert report['filled_count'] == 1 and repeated['filled_count'] == 0
    assert merged == again


def test_duplicate_provider_dates_are_not_merged_arbitrarily():
    data = bundle(); data['annual']['income'].append(deepcopy(data['annual']['income'][0]))
    merged, report = merge(document({'GrossProfit': [fact(120)]}), data)
    assert merged == data and report['filled_count'] == 0


def test_similar_but_incompatible_metrics_are_not_fallbacks():
    source = document({'CashAndCashEquivalentsAtCarryingValue': [fact(10, start=None, end='2024-12-31')],
        'LongTermDebtCurrent': [fact(20, start=None, end='2024-12-31')],
        'EarningsPerShareDiluted': [fact(5)],
        'PaymentsForRepurchaseOfCommonStock': [fact(100)]})
    merged, report = merge(source)
    assert merged == bundle() and report['filled_count'] == 0


def test_verified_later_filing_revises_sec_owned_cell_and_records_original_evidence():
    first, _ = merge(document({'GrossProfit': [fact(120)]}))
    old = deepcopy(first)
    revised_fact = fact(125, filed='2026-08-01', accession='0001774857-26-000099')
    revised, report = merge(document({'GrossProfit': [revised_fact]}), first)
    assert first == old
    row = revised['annual']['income'][0]
    assert row['values']['grossProfit'] == 125
    assert row['field_provenance']['grossProfit']['accession'] == revised_fact['accn']
    assert report['filled_count'] == report['conflict_count'] == 0
    assert report['revised_count'] == 1
    assert report['revised'][0]['previous_value'] == 120
    assert report['revised'][0]['previous_provenance'] == first['annual']['income'][0]['field_provenance']['grossProfit']
    repeated, again = merge(document({'GrossProfit': [revised_fact]}), revised)
    assert repeated == revised and again['revised_count'] == 0


@pytest.mark.parametrize('changed', [
    {'source': 'Yahoo Finance financial statements'},
    {'url': 'https://www.sec.gov/Archives/edgar/data/123456/000119312526119770/'},
    {'currency': 'EUR'}, {'end': '2024-12-31'}, {'start': '2025-02-01'},
    {'accession': 'not-an-accession'}, {'filed': 'not-a-date'},
    {'tag': 'Assets'}, {'form': '8-K'},
])
def test_source_label_does_not_authorize_revisions_without_verified_same_context(changed):
    first, _ = merge(document({'GrossProfit': [fact(120)]}))
    first['annual']['income'][0]['field_provenance']['grossProfit'].update(changed)
    revised, report = merge(document({'GrossProfit': [fact(125, filed='2026-08-01')]}), first)
    assert revised['annual']['income'][0]['values']['grossProfit'] == 120
    assert report['revised_count'] == 0


@pytest.mark.parametrize('filed', ['2026-03-23', '2026-02-01'])
def test_same_date_or_older_conflicting_sec_value_is_retained_and_quarantined(filed):
    first, _ = merge(document({'GrossProfit': [fact(120)]}))
    revised, report = merge(document({'GrossProfit': [fact(125, filed=filed)]}), first)
    assert revised == first and report['revised_count'] == 0
    conflict = report['conflicts'][0]
    assert conflict['existing_source'] == 'SEC EDGAR'
    assert conflict['requires_review'] is True
    assert conflict['provider_value'] == 120 and conflict['sec_value'] == 125
    assert conflict['existing_provenance'] == first['annual']['income'][0]['field_provenance']['grossProfit']


def test_ambiguous_latest_filing_quarantines_previous_sec_value_without_selecting_a_candidate():
    first, _ = merge(document({'GrossProfit': [fact(120)]}))
    revised, report = merge(document({'GrossProfit': [fact(125, filed='2026-08-01'),
        fact(130, filed='2026-08-01')]}), first)
    assert revised == first and report['revised_count'] == 0
    conflict = report['conflicts'][0]
    assert conflict['ambiguous'] is True and conflict['sec_value'] is None
    assert conflict['provider_value'] == 120 and conflict['existing_source'] == 'SEC EDGAR'


def test_later_sec_filing_does_not_replace_an_existing_yahoo_cell():
    first = bundle()
    first['annual']['income'][0]['values']['grossProfit'] = 120
    revised, report = merge(document({'GrossProfit': [fact(125, filed='2026-08-01')]}), first)
    assert revised == first and report['revised_count'] == 0
    assert report['conflicts'][0]['provider_value'] == 120
    assert 'existing_source' not in report['conflicts'][0]
