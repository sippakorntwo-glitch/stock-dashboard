"""Regress equivalent industry joins and duplicate automatic refresh requests."""
from __future__ import annotations
import threading
import pandas as pd
import pytest
from ui_stability import merge_classifications, claim_refresh, page_receipt


def reference_join(frame, records):
    frame=frame.copy()
    for ticker, row in records.items():
        if ticker not in frame.index or not row.get('Industry'):continue
        old=pd.to_datetime(frame.at[ticker,'Industry_Time'],utc=True,errors='coerce')
        new=pd.to_datetime(row.get('Industry_Time'),utc=True,errors='coerce')
        if pd.notna(old) and (pd.isna(new) or old>new):continue
        for field in ('Industry','Industry_Source','Industry_Time'):
            frame.at[ticker,field]=row.get(field,'')
    return frame


@pytest.mark.parametrize('old',[None,'','bad','2026-09-10','2026-09-10T11:00:00Z','2026-09-10T12:00:00+02:00'])
@pytest.mark.parametrize('new',[None,'','bad','2026-09-09T11:00:00Z','2026-09-10T11:00:00Z','2026-09-11T11:00:00Z'])
def test_classification_timestamp_order_and_unknowns_are_unchanged(old,new):
    frame=pd.DataFrame({'Industry':['Original','Untouched'],'Industry_Source':['old','old'],'Industry_Time':[old,old]},index=['A','B']).astype(object)
    records={'A':{'Industry':'Updated','Industry_Source':None,'Industry_Time':new},
             'B':{'Industry':None,'Industry_Time':new},'OUTSIDE':{'Industry':'Ignore'}}
    expected=reference_join(frame,records)
    result=merge_classifications(frame.copy(),records)
    pd.testing.assert_frame_equal(result,expected,check_dtype=False)


def test_join_does_not_touch_price_return_or_stock_selection_order():
    frame=pd.DataFrame({'Industry':[None,None],'Industry_Source':['',''],'Industry_Time':['',''],
                        'Return_1D':[1.,None],'Close':[10.,20.]},index=['B','A'])
    result=merge_classifications(frame.copy(),{'A':{'Industry':'Verified'}})
    assert result.index.tolist()==['B','A']
    pd.testing.assert_frame_equal(result[['Return_1D','Close']],frame[['Return_1D','Close']])
    assert result.at['B','Industry'] is None
    assert result.at['A','Industry']=='Verified'


def test_same_changed_revision_requests_only_one_full_page_rerun():
    state={};rendered=('v23',1,0,None);updated=('v23',2,0,None)
    assert claim_refresh(state,updated,rendered)
    assert all(not claim_refresh(state,updated,rendered) for _ in range(100))
    assert not claim_refresh(state,updated,updated)
    assert claim_refresh(state,('v23',3,0,None),updated)
    assert claim_refresh({},updated,rendered)


def test_new_version_or_initial_chart_can_request_its_own_refresh():
    state={};old=('v22',1,0,None);new=('v23',1,0,None)
    assert claim_refresh(state,new,old)
    assert claim_refresh(state,('v23',1,0,4),('v23',1,0,3))
    assert not claim_refresh(state,('v23',1,0,4),('v23',1,0,3))


def test_receipt_does_not_render_untrusted_query_as_markup():
    output=page_receipt('v23','AAPL','"><script>alert(1)</script>',1.23456)
    assert '<script>' not in output
    assert '&lt;script&gt;' in output
    assert 'data-render-seconds="1.235"' in output


def test_unchanged_detail_shard_does_not_refresh_every_viewer():
    from data_sync import SnapshotReader, shard_number
    class Cache:
        def __init__(self):
            self._lock=threading.RLock()
            self.rows={'info:AAPL':({'shortName':'TEST FIXTURE'}, {'fetched_at':'2026-09-10T00:00:00Z'})}
        def get(self,key,**kwargs):return self.rows.get(key,(None,{}))
        def put(self,key,value,meta):self.rows[key]=(value,meta)
    cache=Cache();reader=SnapshotReader(object(),cache)
    slot=str(shard_number('AAPL'));reader.manifest={'generation':'fixture','details':{slot:{}}}
    reader.shards[slot]={'AAPL':[('info:AAPL',{'shortName':'TEST FIXTURE'},{'fetched_at':'2026-09-10T00:00:00Z'})]}
    reader._details('AAPL');assert reader.revision==0
    reader.shards[slot]['AAPL'][0][2]['fetched_at']='2026-09-11T00:00:00Z'
    reader._details('AAPL');assert reader.revision==1
    reader._details('AAPL');assert reader.revision==1
