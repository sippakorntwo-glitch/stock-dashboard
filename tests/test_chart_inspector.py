"""Inspector-only regression tests. Synthetic prices are test fixtures, not UI data."""
import json
import re
import shutil
import subprocess
import numpy as np
import pandas as pd
import pytest
from chart_inspector import with_inspector, _SCRIPT
from chart_performance import with_performance
import dashboard_runtime as a


def fixture_payload():
    close = np.linspace(100, 160, 300)
    frame = pd.DataFrame({'Open':close, 'High':close+2, 'Low':close-2,
                          'Close':close, 'Volume':1000}, index=pd.bdate_range('2025-01-01', periods=300))
    p = a.build_payload(frame, 'TEST', '1 ปี', '1d')
    p['full_window'] = True
    return p


def test_inspector_preserves_payload_performance_and_chart_controls():
    p = fixture_payload()
    original = with_performance(a.build_chart_html(p), p)
    html = with_inspector(original)
    extract = lambda h: re.search(r'<script type="application/json" id="payload">(.*?)</script>', h, re.S).group(1)
    assert extract(original) == extract(html)
    assert 'range-return-value' in html and 'minBarSpacing:.05' in html
    assert html.count('id="inspect-toggle"') == 1
    assert 'attachInspector();' in html and 'subscribeClick' in html
    assert 'crosshairMarkerVisible:true' in html
    assert 'series.volume=s' in html and 'series.rsi=s' in html and 'series.hist=hist' in html
    assert 'series[f]=s' in html and 'inspectionTime(r.time)' in html
    assert 'new ResizeObserver' in html and 'pointer-events:none' in html
    for control in ['ema20','ema50','sma200','volume','rsi','macd','log','reset']:
        assert f'id="{control}"' in html


def test_inspector_rejects_changed_or_double_patched_template():
    with pytest.raises(ValueError):
        with_inspector('<html></html>')
    html = a.build_chart_html(fixture_payload())
    with pytest.raises(ValueError):
        with_inspector(with_inspector(html))


def test_no_new_network_or_unsafe_html_sinks():
    assert 'innerHTML' not in _SCRIPT
    assert '.textContent=' in _SCRIPT
    assert 'fetch(' not in _SCRIPT and 'XMLHttpRequest' not in _SCRIPT
    assert 'param.time===undefined' in _SCRIPT
    assert 'if(!r)return null' in _SCRIPT
    p = fixture_payload(); p['ticker'] = '</script><script>alert(1)</script>'
    html = with_inspector(a.build_chart_html(p))
    assert p['ticker'] not in html
    assert '\\u003c/script\\u003e' in html


@pytest.mark.skipif(shutil.which('node') is None, reason='Node required for actual JavaScript syntax/formatting regression')
def test_actual_javascript_fields_nulls_precision_dates_and_syntax(tmp_path):
    p = fixture_payload()
    html = with_inspector(a.build_chart_html(p))
    expanded = html.split('<script>')[-1].split('</script>')[0]
    path = tmp_path / 'expanded.js'; path.write_text(expanded)
    subprocess.run(['node', '--check', str(path)], check=True, capture_output=True)
    pure = _SCRIPT[_SCRIPT.index('const inspectionNames='):_SCRIPT.index('function inspectionSeries()')]
    before = "const p={precision:2,timezone:'America/New_York'};const opts={ema20:true,ema50:true,sma200:true,volume:true,rsi:true,macd:true};const rows=[{time:'2026-03-06',close:100},{time:'2026-03-09',close:110,open:109,high:111,low:108,volume:0,ema20:null,ema50:105,sma200:null,rsi:50,macd:-.012345,signal:0,hist:-.012345}];"
    after = """
const all=inspectionFields(rows[1]);
opts.ema50=false;opts.volume=false;opts.macd=false;
console.log(JSON.stringify({all,filtered:inspectionFields(rows[1]),missing:inspectionFormat('ema20',null),invalid:inspectionFormat('rsi',NaN),zero:inspectionFormat('volume',0),macd:inspectionFormat('macd',-.012345),key:inspectionKey({year:2026,month:3,day:9}),date:inspectionTime(1773063300),first:inspectionFields(rows[0])}));
"""
    raw = subprocess.run(['node','-e', before+pure+after], check=True, capture_output=True, text=True)
    data = json.loads(raw.stdout)
    assert data['missing'] == data['invalid'] == '—' and data['zero'] == '0'
    assert data['macd'] == '-0.0123' and data['key'] == '2026-03-09'
    assert 'America/New_York' in data['date'] and '2026-03-09' in data['date']
    all_fields = dict(data['all']); filtered = dict(data['filtered'])
    assert set(all_fields) == {'open','high','low','close','volume','ema20','ema50','sma200','rsi','macd','signal','hist','barChange'}
    assert all_fields['barChange'] == pytest.approx(10)
    assert all_fields['ema20'] is None and all_fields['volume'] == 0
    assert not {'ema50','volume','macd','signal','hist'} & set(filtered)
    assert dict(data['first'])['barChange'] is None
