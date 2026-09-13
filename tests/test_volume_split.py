"""Financial visual estimates must conserve the reported volume and label uncertainty."""
import json
import math
import subprocess
import shutil
import pandas as pd
import pytest
from volume_split import split_volume, METHOD
import dashboard_core as core
from chart_inspector import with_inspector, _SCRIPT


def test_split_conserves_reported_volume_for_close_positions():
    for volume in (0, 0.125, 1000, 4990000):
        for close in (100, 101, 102.5, 105, 110):
            value = split_volume(volume, 110, 100, close)
            assert value['buy_volume_est'] == pytest.approx(volume*(close-100)/10)
            assert value['buy_volume_est'] + value['sell_volume_est'] == pytest.approx(volume)
            assert value['unclassified_volume'] == 0
            assert 0 <= value['buy_volume_est'] <= volume
    assert split_volume(1000, 110, 100, 100)['buy_volume_est'] == 0
    assert split_volume(1000, 110, 100, 110)['sell_volume_est'] == 0


def test_flat_missing_and_invalid_bars_do_not_invent_a_split():
    assert split_volume(1000, 10, 10, 10) == dict(buy_volume_est=None, sell_volume_est=None, unclassified_volume=1000)
    assert split_volume(0, 10, 10, 10) == dict(buy_volume_est=0, sell_volume_est=0, unclassified_volume=0)
    for args in ((None, 11, 10, 10), (-1, 11, 10, 10), (math.nan, 11, 10, 10),
                 (1000, 10, 11, 10), (1000, 11, 10, 12), (True, 11, 10, 10)):
        assert all(v is None for v in split_volume(*args).values())


def test_payload_keeps_actual_total_and_records_unknown_values():
    f=pd.DataFrame({'Open':[10,10,10], 'High':[20,10,12], 'Low':[0,10,9],
                    'Close':[15,10,11], 'Volume':[1000,25,None]}, index=pd.bdate_range('2026-01-01',periods=3))
    p=core.build_payload(f,'TEST','1 ปี','1d')
    assert p['volumeSplitMethod'] == METHOD
    first,flat,missing=p['records']
    assert first['volume'] == 1000 and first['buy_volume_est'] == 750 and first['sell_volume_est'] == 250
    assert flat['unclassified_volume'] == 25 and flat['buy_volume_est'] is None
    assert missing['volume'] is None and missing['sell_volume_est'] is None
    json.dumps(p,allow_nan=False)


@pytest.mark.skipif(shutil.which('node') is None,reason='Node required for chart JavaScript checks')
def test_chart_and_inspector_expose_estimate_only_when_selected(tmp_path):
    f=pd.DataFrame({'Open':[10], 'High':[20], 'Low':[0], 'Close':[15], 'Volume':[1000]},index=pd.bdate_range('2026-01-01',periods=1))
    html=with_inspector(core.build_chart_html(core.build_payload(f,'TEST','1 ปี','1d')))
    assert 'แยกซื้อ/ขาย (ประมาณ)' in html and 'ไม่ใช่ข้อมูลผู้เริ่มซื้อขายจริง' in html
    js=tmp_path/'chart.js';js.write_text(html.split('<script>')[-1].split('</script>')[0])
    subprocess.run(['node','--check',str(js)],check=True,capture_output=True)
    pure=_SCRIPT[_SCRIPT.index('const inspectionNames='):_SCRIPT.index('function inspectionSeries()')]
    setup="const p={precision:2};const rows=[{time:'2026-01-01',volume:1000,buy_volume_est:750,sell_volume_est:250,unclassified_volume:0}];const opts={volume:true,volumeSplit:true};"
    end="const on=inspectionFields(rows[0]);opts.volumeSplit=false;const off=inspectionFields(rows[0]);opts.volume=false;console.log(JSON.stringify({on,off,hidden:inspectionFields(rows[0])}));"
    result=json.loads(subprocess.run(['node','-e',setup+pure+end],check=True,capture_output=True,text=True).stdout)
    assert dict(result['on'])['buy_volume_est'] == 750
    assert 'buy_volume_est' not in dict(result['off'])
    assert 'volume' not in dict(result['hidden'])
