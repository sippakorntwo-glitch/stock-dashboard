"""ETF financial units, partial coverage, dated overlap and collector retention."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from etf_research import (concentration, from_funds_data, holdings_observation, overlap,
                          parse_holdings_csv, price_comparison, retain_last_valid)
from etf_research_job import collect_batch, due_symbols


def positions(rows=None, **kwargs):
    return holdings_observation(rows or [{'symbol':'AAPL', 'weight':.1}, {'symbol':'MSFT', 'weight':.2}], **kwargs)


def bundle(ticker='SPY'):
    return {'schema':1, 'ticker':ticker, 'available':True, 'errors':[],
            'fetched_at':'2026-01-01T00:00:00+00:00', 'holdings':positions(),
            'expense_ratio':.0009, 'turnover':.03, 'net_assets':1000000,
            'sectors':{'technology':.4}, 'asset_classes':{'stockPosition':1}}


def test_public_yfinance_fund_schema_preserves_fractional_fee_and_holdings():
    # Exercise yfinance's installed parser contract without making HTTP requests.
    from yfinance.scrapers.funds import FundsData
    funds = FundsData(None, 'SPY')
    funds._parse_top_holdings({'holdings':[{'symbol':'AAPL','holdingName':'Apple','holdingPercent':.07}],
                              'sectorWeightings':[{'technology':.3}], 'stockPosition':1.0})
    funds._parse_fund_profile({'feesExpensesInvestment':{'annualReportExpenseRatio':.0009},
                              'feesExpensesInvestmentCat':{'annualReportExpenseRatio':.002}})
    result = from_funds_data('SPY', funds, fetched_at='2026-09-14T00:00:00+00:00')
    assert result['expense_ratio'] == .0009  # Display 0.09%, not 9% or 0.0009%.
    assert result['holdings']['coverage'] == .07
    assert result['category_expense_ratio'] == .002
    assert result['source_asof'] is None and result['holdings']['source_asof'] is None
    assert result['holdings']['complete'] is False


@pytest.mark.parametrize('weight', [-.1, 1.1, float('nan'), float('inf'), None, True])
def test_invalid_position_weight_is_not_coerced_or_renormalized(weight):
    with pytest.raises(ValueError):
        holdings_observation([{'symbol':'AAPL', 'weight':weight}])


def test_duplicate_and_oversized_positions_rejected():
    with pytest.raises(ValueError, match='ซ้ำ'):
        holdings_observation([{'symbol':'AAPL','weight':.1}, {'symbol':'AAPL','weight':.2}])
    with pytest.raises(ValueError, match='เกิน 100'):
        holdings_observation([{'symbol':'AAPL','weight':.7}, {'symbol':'MSFT','weight':.4}])


def test_partial_coverage_not_full_portfolio_or_zero_for_unknown():
    result = concentration(positions())
    assert result['coverage'] == pytest.approx(.3)
    assert result['top1'] == .2 and result['top5'] == pytest.approx(.3)
    assert result['complete'] is False
    assert concentration({})['coverage'] is None
    assert overlap(positions(), {})['weight'] is None


def test_csv_units_dates_and_source_declaration():
    result = parse_holdings_csv(b'symbol,name,weight_pct\nAAPL,Apple,0.5\nMSFT,Microsoft,99.5\n',
            source_url='https://issuer.example/fund/holdings.csv', source_asof='2026-09-10', full_portfolio=True)
    assert result['coverage'] == 1 and result['complete'] is True
    assert next(row for row in result['rows'] if row['symbol'] == 'AAPL')['weight'] == .005
    assert result['source_kind'] == 'user_import'


@pytest.mark.parametrize('kwargs', [
    {'source_asof':'2099-01-01'}, {'source_asof':None},
    {'source_url':'javascript:alert(1)'}, {'source_url':'https://user:pass@issuer.example/file'},
    {'full_portfolio':True},
])
def test_csv_cannot_claim_future_undated_or_incomplete_complete_portfolio(kwargs):
    defaults = {'source_url':'https://issuer.example/holdings', 'source_asof':'2026-09-10'}
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        parse_holdings_csv(b'symbol,weight_pct\nAAPL,20\n', **defaults)


def test_csv_rejects_ambiguous_weight_header_and_duplicate_columns():
    for data in (b'symbol,weight\nAAPL,1\n', b'symbol,weight_pct,weight_pct\nAAPL,1,2\n'):
        with pytest.raises(ValueError):
            parse_holdings_csv(data, source_url='https://issuer.example/file', source_asof='2026-09-10')


def test_overlap_partial_and_unmatched_dates_never_marked_complete():
    left = positions(source_asof='2026-09-10')
    right = positions([{'symbol':'AAPL','weight':.05}, {'symbol':'GOOG','weight':.2}], source_asof='2026-09-11')
    result = overlap(left, right)
    assert result['weight'] == .05 and len(result['rows']) == 1
    assert result['date_state'] == 'different_dates' and result['complete'] is False
    right['source_asof'] = '2026-09-10'
    result = overlap(left, right)
    assert result['date_state'] == 'aligned' and result['complete'] is False


def test_same_date_complete_files_allow_full_overlap_without_normalizing():
    left = positions([{'symbol':'AAPL','weight':.6}, {'symbol':'MSFT','weight':.4}],
                     source_asof='2026-09-10', full_portfolio=True)
    right = positions([{'symbol':'AAPL','weight':.2}, {'symbol':'GOOG','weight':.8}],
                      source_asof='2026-09-10', full_portfolio=True)
    assert overlap(left, right)['weight'] == .2
    assert overlap(left, right)['complete'] is True
    right['source_asof'] = None
    assert overlap(left, right)['complete'] is False


def test_empty_failed_or_partial_refresh_preserves_last_good_and_its_stamp():
    previous = bundle()
    assert retain_last_valid(previous, None) is previous
    for field in ('expense_ratio','net_assets','turnover','holdings','sectors'):
        candidate = deepcopy(previous)
        candidate['fetched_at'] = '2026-09-14T00:00:00+00:00'
        candidate[field] = {} if field in ('holdings','sectors') else None
        assert retain_last_valid(previous, candidate) is previous
    fresh = deepcopy(previous)
    fresh['expense_ratio'] = .0005
    assert retain_last_valid(previous, fresh) is fresh


def test_provider_missing_fee_stays_missing_but_explicit_zero_is_allowed():
    funds = SimpleNamespace(top_holdings=pd.DataFrame(), fund_operations=pd.DataFrame(),
            fund_overview={}, sector_weightings={}, asset_classes={})
    assert from_funds_data('ZERO', funds)['expense_ratio'] is None
    funds.fund_operations = pd.DataFrame({'ZERO':[0.]}, index=['Annual Report Expense Ratio'])
    result = from_funds_data('ZERO', funds)
    assert result['expense_ratio'] == 0 and result['available'] is True


def test_invalid_provider_weights_are_withheld_as_a_section():
    funds = SimpleNamespace(top_holdings=pd.DataFrame({'Name':['A'], 'Holding Percent':[3]}, index=['AAPL']),
        fund_operations=pd.DataFrame({'SPY':[.001]}, index=['Annual Report Expense Ratio']),
        fund_overview={}, sector_weightings={'technology':.9,'energy':.4}, asset_classes={})
    result = from_funds_data('SPY', funds)
    assert result['holdings']['rows'] == [] and result['sectors'] == {}
    assert result['expense_ratio'] == .001 and len(result['errors']) == 2


def test_price_comparison_uses_shared_dates_and_blocks_unknown_currency():
    index = pd.date_range('2026-01-01', periods=30, freq='D')
    left = pd.DataFrame({'Close':range(100,130)}, index=index)
    right = pd.DataFrame({'Close':range(200,228)}, index=index[2:])
    result = price_comparison(left, right, currency='USD', benchmark_currency='USD')
    assert result['start'] == '2026-01-03' and result['observations'] == 28
    assert list(result['data'].iloc[0]) == [100., 100.]
    assert result['fund_return'] == pytest.approx(129/102-1)
    assert 'tracking_error' not in result
    assert price_comparison(left, right, currency='USD')['state'] == 'currency_mismatch'


def test_due_queue_reaches_unattempted_symbols_before_repeated_empty_responses():
    names = ['SPY','NEW','COMPANY','PAUSED']
    profiles = {'info:'+symbol:({'quoteType':'ETF' if symbol != 'COMPANY' else 'EQUITY'}, {}) for symbol in names}
    attempts = {'attempt:etf_research:SPY':({}, {'fetched_at':'2026-01-01T00:00:00+00:00'}),
                'attempt:etf_research:PAUSED':({}, {'retry_after':'2027-01-01T00:00:00+00:00'})}
    now = datetime(2026,9,14,tzinfo=timezone.utc).timestamp()
    assert due_symbols(names, profiles, {}, attempts, set(), now=now) == ['NEW','SPY']


def test_collector_retains_good_data_on_partial_failure_and_cooldown(tmp_path):
    from dashboard_runtime import DashboardCache
    cache = DashboardCache(tmp_path/'etf.sqlite3')
    for ticker in ('SPY','QQQ'):
        cache.put('info:'+ticker, {'quoteType':'ETF'}, {})
    previous = bundle()
    cache.put('etf_research:SPY', previous, {'fetched_at':previous['fetched_at']})
    candidate = deepcopy(previous)
    candidate.update(expense_ratio=None, errors=['fee:missing'])
    report = collect_batch(cache, ['SPY'], set(), collector=lambda _:candidate, pause=0)
    assert report['retained'] == 1
    assert cache.get('etf_research:SPY')[0] == previous
    calls = []
    def limited(ticker):
        calls.append(ticker)
        raise RuntimeError('429 Too Many Requests')
    report = collect_batch(cache, ['QQQ'], set(), collector=limited, pause=0)
    assert report['failed'] == 1 and report['cooldown_until']
    report = collect_batch(cache, ['QQQ'], set(), collector=limited, pause=0)
    assert report['attempted'] == 0 and calls == ['QQQ']
    assert cache.get('etf_research:QQQ')[0] is None
