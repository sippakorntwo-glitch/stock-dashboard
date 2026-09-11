"""Regressions for requested-period growth and deliberately reduced table help."""
from copy import deepcopy
import json
import math
import numpy as np
import pandas as pd
import pytest
from bs4 import BeautifulSoup
from chart_performance import period_performance, format_return, performance_card, with_performance


def payload(closes, start=0, full=True):
    return {'records': [{'time': f'2026-01-{i+1:02d}', 'close': c} for i,c in enumerate(closes)],
            'visibleStart': start, 'full_window': full, 'period': '7 วัน', 'precision': 2, 'demo': False}


@pytest.mark.parametrize('closes,expected', [([100,120],20),([100,75],-25),([100,100],0),([.001,.004],300)])
def test_gains_losses_flat_small_prices(closes,expected):
    p=payload(closes); before=deepcopy(p)
    result=period_performance(p)
    assert result['percent']==pytest.approx(expected)
    assert result['amount']==pytest.approx(closes[-1]-closes[0])
    assert result['observations']==2 and result['basis']=='first-visible-close-to-last-close'
    assert p==before
    json.dumps(result,allow_nan=False)


def test_ignores_warmup_bars_and_last_bar_only_change():
    p=payload([1,2,100,105,120],start=2)
    result=period_performance(p)
    assert result['percent']==pytest.approx(20)
    assert result['start_price']==100 and result['end_price']==120
    assert result['percent']!=pytest.approx((120/105-1)*100)
    assert result['start_time']=='2026-01-03'


@pytest.mark.parametrize('closes', [[],[100],[0,100],[-5,100],[None,100],[100,None],[math.nan,100],[100,math.inf],[True,100],[1e-308,1e308]])
def test_invalid_or_single_observation_never_fakes_zero(closes):
    result=period_performance(payload(closes))
    assert result['percent'] is None and result['amount'] is None
    json.dumps(result,allow_nan=False)
    assert '—' in performance_card(payload(closes))


@pytest.mark.parametrize('start',[-1,2,999,True,1.5,None])
def test_invalid_range_not_clamped_into_a_different_period(start):
    assert period_performance(payload([100,110],start))['percent'] is None


def test_duplicate_time_and_demo_are_not_real_returns():
    p=payload([100,110]);p['records'][-1]['time']=p['records'][0]['time']
    assert period_performance(p)['percent'] is None
    p=payload([100,110]);p['demo']=True
    assert period_performance(p)['percent'] is None


def test_partial_period_label_and_missing_distinguished_from_flat():
    p=payload([100,120],full=False);p['period']='10 ปี'
    html=performance_card(p)
    assert 'ผลตอบแทนข้อมูลที่มี' in html and 'ประวัติไม่ครบช่วง' in html
    assert '+20.00%' in html
    assert format_return(None)=='—' and format_return(0)=='0.00%'
    assert format_return(-.000001)=='0.00%' and format_return(1250)=='+1,250.00%'


def test_html_escape_and_chart_header_insert_preserves_existing_change():
    import dashboard_runtime as a
    p=payload([100,120]);p['period']='<script>alert(1)</script>'
    card=performance_card(p)
    assert '<script>' not in card and '&lt;script&gt;' in card
    out=with_performance(a.build_chart_html(p),p)
    soup=BeautifulSoup(out,'html.parser')
    assert len(soup.select('#range-return-value'))==1
    assert soup.select_one('#range-return-value').text=='+20.00%'
    assert soup.select_one('#price') is not None and soup.select_one('#change') is not None
    assert json.loads(soup.select_one('#payload').text)==p
    with pytest.raises(ValueError):with_performance('<html>no header</html>',p)


def test_intraday_dates_use_exchange_timezone():
    times=pd.date_range('2026-09-10 09:30',periods=2,freq='5min',tz='America/New_York')
    p=payload([100,101]);p['timezone']='America/New_York'
    for record,t in zip(p['records'],times):record['time']=int(t.timestamp())
    card=performance_card(p)
    assert '2026-09-10 09:30 EDT' in card and '2026-09-10 09:35 EDT' in card


@pytest.mark.parametrize('period',['1 วัน','3 วัน','7 วัน','1 เดือน','1 ปี','5 ปี','10 ปี'])
def test_integrated_payload_uses_exact_selected_candles(period):
    from chart_ranges import range_payload
    if period.endswith('วัน'):
        index=pd.DatetimeIndex([t for d in pd.bdate_range('2026-08-24',periods=12)
            for t in pd.date_range(str(d.date())+' 09:30',periods=78,freq='5min',tz='America/New_York')])
        interval='5m'
    else:
        index=pd.bdate_range('2014-01-01','2026-09-10');interval='1d'
    close=np.linspace(80,200,len(index))
    f=pd.DataFrame({'Open':close,'High':close+1,'Low':close-1,'Close':close,'Volume':1000},index=index)
    p=range_payload(f,'TEST',period,interval)
    result=p['periodReturn'];first=p['records'][p['visibleStart']];last=p['records'][-1]
    assert result['percent']==pytest.approx((last['close']/first['close']-1)*100)
    assert result['start_time']==p['range_first'] and result['end_time']==p['range_last']
    assert result['full_window']==p['full_window'] and result['observations']==len(p['records'])-p['visibleStart']


@pytest.mark.parametrize('frame,label',[
    (pd.DataFrame({'หมวด':['แนวโน้ม'],'เกณฑ์':['ราคา > EMA20 > EMA50'],'ค่าปัจจุบัน':['326 > 317 > 313'],'ช่วง / คะแนน':['20; อื่น ๆ 0'],'คะแนน':[20],'เต็ม':[20],'ผล':['เต็ม'],'ข้อมูลอ้างอิง':['แท่งรายวันก่อนปัจจุบัน']}),'เกณฑ์'),
    (pd.DataFrame({'หมวด':['พื้นฐาน'],'ปัจจัย':['Forward P/E'],'ค่าล่าสุด':['33.43x'],'การแปลผล':['อยู่ในช่วง 25–40'],'แหล่งข้อมูล':['Yahoo Finance']}),'ปัจจัย'),
    (pd.DataFrame({'มิติ':['Revenue growth'],'ค่า':['16.40%'],'ฟิลด์ต้นทาง':['revenueGrowth']}),'มิติ'),
    (pd.DataFrame({'ช่วงคะแนน':['80–100'],'ความหมาย':['ผ่านระดับคะแนน แต่ต้องรอเงื่อนไข']}),None),
])
def test_only_metric_names_keep_tooltips(frame,label):
    from dashboard_help import table_html
    soup=BeautifulSoup(table_html(frame),'html.parser')
    table=soup.select_one('.workspace-help-table')
    assert table.select('thead abbr, thead [title]')==[]
    for row in table.select('tbody tr'):
        for col,cell in zip(frame.columns,row.select('td')):
            if col==label:
                assert len(cell.select('abbr[title]'))==1
            else:
                assert cell.select('abbr, [title]')==[]
                assert 'ⓘ' not in cell.text
    assert int(table['data-tooltip-column'])==(list(frame.columns).index(label) if label else -1)
