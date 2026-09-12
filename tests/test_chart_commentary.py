"""Synthetic fixtures only: narrative arithmetic and HTML safety, no providers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from html import unescape
import re
import pytest
from chart_commentary import summarize_chart, commentary_html, atr14

NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


def sample(size=230, trend='up', interval='1d'):
    rows=[]
    for i in range(size):
        c=100+i if trend=='up' else 400-i if trend=='down' else 100
        sign=1 if trend=='up' else -1 if trend=='down' else 0
        stamp=(datetime(2026,1,1)+timedelta(days=i)).strftime('%Y-%m-%d') if interval=='1d' else int((datetime(2026,9,11,14,tzinfo=timezone.utc)+timedelta(minutes=5*i)).timestamp())
        rows.append({'time':stamp,'open':c-.5,'high':c+2,'low':c-2,'close':c,'volume':1000,
                     'ema20':c-sign*4 if i>=19 else None,'ema50':c-sign*8 if i>=49 else None,
                     'sma200':c-sign*20 if i>=199 else None,'rsi':60 if sign>=0 else 40,
                     'macd':sign*2.,'signal':sign*1.,'hist':float(sign)})
    return {'ticker':'TEST','period':'1 ปี' if interval=='1d' else '3 วัน','interval':interval,
            'timezone':'America/New_York' if interval=='5m' else 'UTC','precision':2,
            'visibleStart':max(0,size-70),'records':rows,'fetchedAt':NOW.isoformat(),
            'full_window':True,'demo':False}


@pytest.mark.parametrize('trend,direction,regime',[('up','uptrend','above'),('down','downtrend','below'),('flat','mixed','at')])
def test_trend_requires_price_order_and_both_ema_slopes(trend,direction,regime):
    p=sample(trend=trend);before=deepcopy(p);r=summarize_chart(p,now=NOW)
    assert r['trend']==direction and r['regime']==regime
    assert p==before
    json.dumps(r,allow_nan=False)
    if trend=='up':
        p['records'][-6]['ema50']=p['records'][-1]['ema50']+5
        assert summarize_chart(p,now=NOW)['trend']=='mixed'


def test_whole_window_return_can_disagree_with_latest_trend():
    p=sample(trend='up');p['records'][p['visibleStart']]['close']=500
    result=summarize_chart(p,now=NOW)
    assert result['return_window']['percent']<0 and result['trend']=='uptrend'
    assert 'สองมิตินี้ออกจากกัน' in commentary_html(p,now=NOW)


def test_warmup_bars_do_not_enter_selected_window_support_or_return():
    p=sample();p['visibleStart']=len(p['records'])-10
    p['records'][0].update(high=9999,low=.001,close=5000)
    r=summarize_chart(p,now=NOW)
    prior=p['records'][-10:-1]
    assert r['levels']['bars']==9
    assert r['levels']['support']==min(x['low'] for x in prior)
    assert r['levels']['resistance']==max(x['high'] for x in prior)
    assert r['return_window']['percent']==pytest.approx((p['records'][-1]['close']/p['records'][-10]['close']-1)*100)


@pytest.mark.parametrize('breakout,expected',[(True,'breakout'),(False,'breakdown')])
def test_breakout_reference_excludes_current_bar(breakout,expected):
    p=sample();p['records'][-1].update(close=350 if breakout else 200, high=351 if breakout else 201, low=349 if breakout else 199,open=350 if breakout else 200)
    r=summarize_chart(p,now=NOW)
    assert r['levels']['state']==expected
    assert r['levels']['resistance']==max(x['high'] for x in p['records'][-21:-1])


def test_inadequate_volume_does_not_mean_zero_or_a_strong_confirmation():
    p=sample();p['records'][-1]['volume']=2000
    assert summarize_chart(p,now=NOW)['volume_ratio']==2
    p['records'][-2]['volume']=None
    assert summarize_chart(p,now=NOW)['volume_ratio'] is None
    p=sample()
    for row in p['records'][-21:-1]:row['volume']=0
    assert summarize_chart(p,now=NOW)['volume_ratio'] is None
    p=sample();p['records'][-1]['volume']=0
    assert summarize_chart(p,now=NOW)['volume_ratio']==0


def test_equal_volume_is_not_described_as_below_average():
    assert 'เท่าค่าเฉลี่ย ปริมาณซื้อขาย' in commentary_html(sample(),now=NOW)


def test_atr_wilder_seed_and_recurrence_are_not_replaced_with_a_simple_mean():
    rows=[]
    for i in range(30):
        spread=i+1
        rows.append({'open':100.,'close':100.,'low':100-spread/2,'high':100+spread/2})
    expected=sum(range(1,15))/14
    for spread in range(15,31):expected=(expected*13+spread)/14
    assert atr14(rows)==pytest.approx(expected)
    assert atr14(rows[:13]) is None
    rows[-1]['high']=0
    assert atr14(rows) is None


def test_one_bar_and_short_histories_do_not_invent_indicators():
    p=sample(1);p['records'][0].update(ema20=5,ema50=4,sma200=3,rsi=99,macd=5,signal=4,hist=1)
    r=summarize_chart(p,now=NOW)
    assert r['available'] and r['trend']=='insufficient'
    assert all(v is None for v in r['metrics'].values())
    assert r['levels']['state']=='unknown' and r['return_window']['percent'] is None
    assert r['atr14'] is None and r['volume_ratio'] is None


@pytest.mark.parametrize('bad',[None,[],{},True,'bad',0,-1,float('nan'),float('inf')])
def test_invalid_last_price_fails_closed(bad):
    p=sample();p['records'][-1]['close']=bad
    assert not summarize_chart(p,now=NOW)['available']
    assert 'ไม่เติมข้อสรุป' in commentary_html(p,now=NOW)


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(visibleStart=-1),lambda p:p.update(visibleStart=True),
    lambda p:p.update(records=[]),lambda p:p.update(demo=True),
    lambda p:p.update(interval='1h'),lambda p:p['records'].reverse(),
    lambda p:p['records'][-1].update(time=p['records'][-2]['time']),
    lambda p:p['records'].__setitem__(-1,None),
])
def test_malformed_payloads_are_never_repaired_into_unobserved_charts(mutation):
    p=sample();mutation(p)
    assert not summarize_chart(p,now=NOW)['available']


def test_forming_intraday_bar_and_stale_quote_are_explicit():
    p=sample(80,interval='5m');last=datetime.fromtimestamp(p['records'][-1]['time'],timezone.utc)
    p['fetchedAt']=(last+timedelta(minutes=2)).isoformat()
    r=summarize_chart(p,now=last+timedelta(minutes=2))
    assert r['bar_state']=='provisional'
    assert any('5 นาที ไม่ใช่จำนวนวัน' in t for t in r['warnings'])
    assert any('ยังไม่ปิด' in t for t in r['warnings'])
    p['fetchedAt']=(last+timedelta(minutes=6)).isoformat()
    r=summarize_chart(p,now=last+timedelta(hours=2))
    assert r['bar_state']=='closed'
    assert any('เก่ากว่า 15 นาที' in t for t in r['warnings'])


def test_date_rollover_does_not_promote_a_partially_acquired_daily_bar():
    p=sample();p['records'][-1]['time']='2026-09-11';p['fetchedAt']='2026-09-11T15:00:00Z'
    assert summarize_chart(p,now=NOW)['bar_state']=='provisional'
    p['fetchedAt']='2026-09-12T05:00:00Z'
    assert summarize_chart(p,now=NOW)['bar_state']=='closed'
    p['fetchedAt']=''
    assert summarize_chart(p,now=NOW)['bar_state']=='unknown'


def test_insufficient_requested_range_is_never_presented_as_complete():
    p=sample();p['full_window']=False;p['period']='10 ปี'
    r=summarize_chart(p,now=NOW)
    assert not r['return_window']['full_window']
    assert any('ประวัติไม่ครบ' in x for x in r['warnings'])


def test_rsi_extremes_are_not_automatic_trades_and_hist_direction_is_signed():
    p=sample();p['records'][-1].update(rsi=75,hist=-.5,macd=-1,signal=-.5);p['records'][-2]['hist']=-1
    text=commentary_html(p,now=NOW)
    assert 'ไม่ใช่สัญญาณขายอัตโนมัติ' in text and 'สูงขึ้นจากแท่งก่อน' in text
    p['records'][-1]['rsi']=25
    assert 'ไม่ยืนยันว่าจะเด้ง' in commentary_html(p,now=NOW)
    p['records'][-1]['rsi']=150
    assert summarize_chart(p,now=NOW)['metrics']['rsi'] is None


def test_html_has_no_raw_debug_widgets_tables_or_script_execution():
    p=sample();p['ticker']='A<script>alert(1)</script>';p['period']='"><img src=x onerror=alert(2)>'
    text=commentary_html(p,now=NOW)
    assert '<script>' not in text and '<img' not in text
    assert 'alert(1)' in text and '&lt;script&gt;' in text
    assert '<table' not in text and '<abbr' not in text
    assert 'data-report=' in text and '<section class="chart-reading"' in text
    encoded=re.search(r'data-report="([^"]+)"',text).group(1)
    assert json.loads(unescape(encoded))['ticker']==p['ticker']


def test_summary_mounts_after_chart_and_is_part_of_coherent_release():
    from pathlib import Path
    source=Path('chart_ranges.py').read_text()
    assert source.index('commentary_html(payload)')>source.index('components.html(html,height=900,scrolling=False)')
    assert 'chart_commentary' in Path('workspace_boot.py').read_text()
    assert '2026-09-12.26' in Path('app.py').read_text()
    assert '2026-09-12.26' in Path('dashboard_runtime.py').read_text()
