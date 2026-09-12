"""Return math and English UI contracts; deterministic fixtures only."""
import math
import numpy as np
import pandas as pd
import pytest
from return_periods import (RETURN_FIELDS,RETURN_LABELS,TABLE_FIELDS,table_returns,
                           period_observation,daily_closes,return_help,export_watchlist)


def history(values, dates=None):
    index=pd.to_datetime(dates) if dates else pd.bdate_range(end='2026-09-10',periods=len(values))
    c=np.asarray(values,dtype=float)
    return pd.DataFrame({'Close':c,'Open':c,'High':c+1,'Low':c-1,'Volume':1000.},index=index)


def test_requested_order_and_consistent_english_labels():
    assert list(RETURN_LABELS.values())==['1 Day (%)','3 Days (%)','7 Days (%)','1 Month (%)','6 Months (%)','1 Year (%)','3 Years (%)','5 Years (%)']
    assert 'Return_2Y' not in TABLE_FIELDS and 'Return_3M' not in TABLE_FIELDS
    assert tuple(TABLE_FIELDS[7:15])==RETURN_FIELDS
    for field in RETURN_FIELDS:
        assert 'cumulative adjusted return' in return_help(field) and return_help('price.'+field)==return_help(field)


@pytest.mark.parametrize('sessions,field',[(1,'Return_1D'),(3,'Return_3D'),(7,'Return_7D')])
def test_daily_return_counts_changes_not_number_of_included_bars(sessions,field):
    f=history([100,102,99,105,110,108,112,120])
    r=table_returns(f)
    assert r[field]==pytest.approx((120/f.Close.iloc[-sessions-1]-1)*100)
    assert table_returns(f.tail(sessions))[field] is None


def test_weekend_and_market_holiday_not_counted_as_observed_sessions():
    f=history([100,105,110,120],['2026-09-03','2026-09-04','2026-09-08','2026-09-09'])
    assert table_returns(f)['Return_3D']==pytest.approx(20)


def test_calendar_month_uses_boundary_not_21_rows():
    f=history(np.arange(100,150))
    r=period_observation(daily_closes(f),months=1)
    cutoff=f.index[-1]-pd.DateOffset(months=1)
    window=f.loc[f.index<=cutoff]
    assert r['start']==str(window.index[-1].date())
    assert r['value']==pytest.approx((f.Close.iloc[-1]/window.Close.iloc[-1]-1)*100)


def test_calendar_weekend_first_session_and_leap_date():
    f=history([100,110,120,150],['2024-02-28','2024-02-29','2024-03-01','2025-02-28'])
    assert period_observation(daily_closes(f),months=12)['value']==pytest.approx(50)
    f=history([100,105,120],['2021-09-10','2021-09-13','2026-09-12'])
    assert period_observation(daily_closes(f),months=60)['value']==pytest.approx((120/100-1)*100)


def test_full_five_year_history_required_even_if_1260_observations_present():
    f=history(np.linspace(100,200,1260))
    assert table_returns(f)['Return_5Y'] is None
    full=history(np.linspace(100,200,1700))
    assert math.isfinite(table_returns(full)['Return_5Y'])


@pytest.mark.parametrize('bad',[0,-1,np.nan,np.inf])
def test_invalid_endpoint_does_not_shift_baseline(bad):
    f=history([100,101,102,103,bad,105,106,110])
    assert table_returns(f)['Return_3D'] is None
    f.iloc[-1,f.columns.get_loc('Close')]=bad
    assert all(value is None for value in table_returns(f).values())


def test_true_zero_return_is_zero_not_missing():
    r=table_returns(history([100]*1700))
    assert all(value==0 for value in r.values())


def test_input_unchanged_and_duplicate_dates_last_wins():
    f=history([90,100,110],['2026-09-09','2026-09-09','2026-09-10']);before=f.copy(deep=True)
    assert table_returns(f)['Return_1D']==pytest.approx(10)
    pd.testing.assert_frame_equal(f,before)


def test_csv_matches_eight_periods_with_numeric_values():
    f=pd.DataFrame([{'Ticker':'AAPL',**dict.fromkeys(RETURN_FIELDS,12.34),'Return_2Y':999,'Return_3M':999}])
    out=export_watchlist(f)
    assert list(out.columns[7:15])==list(RETURN_LABELS.values())
    assert 'Return_2Y' not in out and 'Return_3M' not in out
    assert out['3 Days (%)'].iloc[0]==12.34


def test_core_snapshot_and_quality_include_new_fields():
    import dashboard_runtime as a
    from data_quality import BARS_REQUIRED,MONTHS_REQUIRED
    f=history(np.linspace(100,200,1700))
    row=a.scan_snapshot_row('AAPL',f,'2026-09-11T10:00:00Z')
    assert row['Metric_Calc_Version']==a.METRIC_VERSION==3
    assert a.HISTORY_YEARS>=6
    for field,value in table_returns(a.completed_daily_history(f)).items():assert row[field]==pytest.approx(value)
    assert BARS_REQUIRED['Return_3D']==4 and BARS_REQUIRED['Return_7D']==8
    assert MONTHS_REQUIRED['Return_5Y']==60


def test_six_year_request_is_explicit_and_does_not_mutate_meta():
    import dashboard_runtime as a
    meta={'years':5};before=meta.copy()
    request=a.history_request(None,meta,years=a.HISTORY_YEARS)
    assert request['_full_window'] is True and 'start' in request and 'period' not in request
    assert meta==before
