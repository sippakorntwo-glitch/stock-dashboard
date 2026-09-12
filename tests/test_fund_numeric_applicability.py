"""A fund's corporate placeholder zero must not pass a profit filter."""
from copy import deepcopy
import pandas as pd
import pytest
from screening import enrich_frame, filter_frame


def test_corporate_metrics_are_na_for_funds_without_mutating_source_records():
    frame=pd.DataFrame({'Ticker':['FUND','COMPANY'],'Asset_Type':['ETF','Common Stock']})
    raw={'FUND':{'Fund_Assets':2_000_000,'Market_Cap':100,'Profit_Margin':0.,'Revenue_Growth':0.,'ROE':0.,'Free_Cash_Flow':0.},
         'COMPANY':{'Market_Cap':3_000_000,'Fund_Assets':100,'Profit_Margin':0.,'Revenue_Growth':-2.,'ROE':-1.,'Free_Cash_Flow':-100.}}
    before=deepcopy(raw);result=enrich_frame(frame,raw);indexed=result.set_index('Ticker')
    assert raw==before
    for field in ('Market_Cap','Profit_Margin','Revenue_Growth','ROE','Free_Cash_Flow'):
        assert pd.isna(indexed.loc['FUND',field])
    assert pd.isna(indexed.loc['COMPANY','Fund_Assets'])
    assert indexed.loc['FUND','Size_Millions']==2. and indexed.loc['COMPANY','Size_Millions']==3.
    assert indexed.loc['COMPANY','Profit_Margin']==0.
    assert indexed.loc['COMPANY','Free_Cash_Flow']==-100.
    assert filter_frame(result,bounds={'Profit_Margin':(0.,None)}).Ticker.tolist()==['COMPANY']
    assert filter_frame(result,bounds={'Profit_Margin':(0.,None)},include_missing=True).Ticker.tolist()==['FUND','COMPANY']


def test_empty_catalog_stays_valid_with_applicability_masks():
    result=enrich_frame(pd.DataFrame(columns=['Ticker','Asset_Type']),{})
    assert result.empty and 'Size_Millions' in result
