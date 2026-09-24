"""Mathematical window boundaries and actual client line behavior; no provider calls."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import re
import shutil
import subprocess
import pytest
from chart_levels import reference_levels, with_levels, _SCRIPT
from chart_commentary import summarize_chart, commentary_html
from chart_performance import with_performance
from chart_inspector import with_inspector
import dashboard_runtime as a


def payload(count=30):
    rows=[]
    for i in range(count):
        rows.append(dict(time=(datetime(2026, 1, 1)+timedelta(days=i)).strftime('%Y-%m-%d'),
                         open=100., close=100., low=90.+i/10, high=110.+i/10, volume=1000,
                         ema20=None, ema50=None, sma200=None, rsi=None, macd=None, signal=None, hist=None))
    return dict(records=rows, visibleStart=0, ticker='TEST', period='1 ปี', interval='1d', precision=2,
                full_window=True, timezone='UTC', demo=False)


def test_levels_exclude_latest_and_warmup_match_commentary_without_mutating():
    p=payload();p['visibleStart']=20
    p['records'][0].update(low=.01, high=9000)
    p['records'][-1].update(low=1, high=999)
    before=deepcopy(p);r=reference_levels(p)
    assert r['support']==92 and r['resistance']==112.8 and r['bars']==9
    assert r['support_distance_pct']==pytest.approx(-8)
    assert r['resistance_distance_pct']==pytest.approx(12.8)
    assert r['start_time']==p['records'][20]['time'] and r['end_time']==p['records'][-2]['time']
    assert r==summarize_chart(p)['levels'] and p==before
    assert 'แนวรับอ้างอิง 92.00 (-8.00%)' in commentary_html(p)
    assert 'แนวต้านอ้างอิง 112.80 (+12.80%)' in commentary_html(p)


def test_window_caps_at_twenty_and_requires_five_prior_bars():
    p=payload();assert reference_levels(p)['bars']==20
    p['visibleStart']=len(p['records'])-5
    assert reference_levels(p)['support'] is None
    p['visibleStart']-=1
    assert reference_levels(p)['bars']==5 and reference_levels(p)['support'] is not None


@pytest.mark.parametrize('close,state,phrase',[(130,'breakout','แนวต้านเดิม (ทะลุแล้ว)'),(80,'breakdown','แนวรับเดิม (หลุดแล้ว)'),(110,'inside','แนวรับอ้างอิง')])
def test_breached_levels_remain_old_reference_not_assumed_role_reversal(close,state,phrase):
    p=payload();p['records'][-1]['close']=close
    levels=reference_levels(p)
    assert levels['state']==state and levels['support']==90.9 and levels['resistance']==112.8
    assert phrase in commentary_html(p)
    if state!='inside':
        assert 'ยังไม่ยืนยันว่า' in commentary_html(p)


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(demo=True),lambda p:p.update(visibleStart=True),lambda p:p.update(visibleStart=-1),
    lambda p:p.update(interval='1h'),lambda p:p['records'].reverse(),
    lambda p:p['records'][-2].update(high=None),lambda p:p['records'][-2].update(low=500),
    lambda p:p['records'][-2].update(low=float('nan')),lambda p:p['records'][-1].update(close=0),
    lambda p:p['records'][-1].update(close=True),lambda p:p['records'][-1].update(time=p['records'][-2]['time'])])
def test_bad_data_never_produces_lines_or_zero_substitutes(mutation):
    p=payload();mutation(p);levels=reference_levels(p)
    assert levels['support'] is None and levels['resistance'] is None and levels['state']=='unknown'
    json.dumps(levels,allow_nan=False)


def test_integration_preserves_payload_and_existing_controls_with_safe_json():
    p=payload();p['ticker']='</script><img src=x onerror=alert(1)>'
    original=with_inspector(with_performance(a.build_chart_html(p),p))
    html=with_levels(original,p)
    extract=lambda source:re.search(r'<script type="application/json" id="payload">(.*?)</script>',source,re.S).group(1)
    assert extract(original)==extract(html)
    assert html.count('id="levels-toggle"')==1 and html.count('id="reference-levels-data"')==1
    assert '<img src=x' not in html
    for control in ['ema20','ema50','sma200','volume','rsi','macd','log','reset','inspect-toggle']:
        assert f'id="{control}"' in html
    assert 'fetch(' not in _SCRIPT and 'innerHTML' not in _SCRIPT
    with pytest.raises(ValueError):with_levels(html,p)
    with pytest.raises(ValueError):with_levels('<html></html>',p)


@pytest.mark.skipif(shutil.which('node') is None,reason='Node required for JavaScript controller check')
def test_client_toggle_changes_only_line_options_and_rebuild_restores_setting(tmp_path):
    p=payload()
    html=with_levels(with_inspector(with_performance(a.build_chart_html(p),p)),p)
    script=html.split('<script>')[-1].split('</script>')[0]
    path=tmp_path/'levels.js';path.write_text(script)
    subprocess.run(['node','--check',str(path)],check=True,capture_output=True)
    # Execute the actual isolated controller against the chart API contract.
    # A toggle must never call chart.create/reset/change data or indicator state.
    harness=r'''
const elements={};const el=id=>elements[id]||(elements[id]={dataset:{},setAttribute(k,v){this[k]=v}});
el('reference-levels-data').textContent=JSON.stringify({support:90,resistance:110,state:'inside'});
const storage={};const sessionStorage={getItem:k=>storage[k],setItem:(k,v)=>storage[k]=v};
const created=[];const L={LineStyle:{Dashed:2}};
const candles={createPriceLine(options){let current={...options};const line={options:()=>({...current}),applyOptions:v=>Object.assign(current,v)};created.push(line);return line;}};
'''
    after=r'''
attachReferenceLevels();
const first=JSON.parse(el('chart-levels').dataset.renderedLines);
el('levels-toggle').onclick();
const hidden=JSON.parse(el('chart-levels').dataset.renderedLines);
attachReferenceLevels();
const rebuilt=JSON.parse(el('chart-levels').dataset.renderedLines);
el('levels-toggle').onclick();
console.log(JSON.stringify({first,hidden,rebuilt,shown:JSON.parse(el('chart-levels').dataset.renderedLines),created:created.length}));
'''
    result=subprocess.run(['node','-e',harness+_SCRIPT+after],check=True,text=True,capture_output=True)
    data=json.loads(result.stdout)
    for phase in ('first','hidden','rebuilt','shown'):
        assert [x['price'] for x in data[phase]]==[90,110]
        assert all(x['visible']==(phase in ('first','shown')) for x in data[phase])
        assert all(x['axisLabelVisible']==x['visible'] for x in data[phase])
    assert data['created']==4
