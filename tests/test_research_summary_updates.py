from copy import deepcopy

from research_updates import build_tracking_snapshot, tracking_changes
from research_summary import research_summary
from research_workspace import validate_research


def snapshot():
    bundle={'schema':1,'ticker':'A','currency':'USD','source':'Yahoo Finance financial statements',
            'annual':{'income':[{'end':'2025-12-31','values':{'revenue':100.,'netIncome':10.}}]},'quarterly':{}}
    return build_tracking_snapshot('A',{'currency':'USD','financialCurrency':'USD'}, {}, bundle)


def test_new_fetch_time_is_not_new_financial_information():
    old=snapshot();new=deepcopy(old)
    new['profile_asof']=new['financial_asof']='2026-09-14T12:00:00Z'
    assert tracking_changes(old,new)==[]
    validate_research({'baselines':{'A':new}})


def test_new_period_same_basis_and_currency_is_a_new_report():
    old=snapshot();new=deepcopy(old)
    new['revenue_period']='2026-12-31';new['revenue']=120.
    event=tracking_changes(old,new)[0]
    assert event['รายการ']=='รายได้' and event['หน่วย']=='USD'
    assert event['การเปลี่ยนแปลง']=='มีรอบงบใหม่ในชุดข้อมูล'


def test_unknown_or_changed_currency_basis_or_formula_never_imply_growth():
    old=snapshot()
    for suffix,value in [('_currency','EUR'),('_basis','TTM (4 reported quarters)'),('_source','Other'),('_formula','Changed')]:
        new=deepcopy(old);new['revenue']=120.;new['revenue_period']='2026-12-31';new['revenue'+suffix]=value
        assert tracking_changes(old,new)==[]
    assert tracking_changes({'ticker':'OTHER'},old)==[]


def test_summary_does_not_convert_missing_metrics_into_a_score():
    summary=research_summary('A',{})
    assert summary['available']==0 and summary['applicable']>0
    assert all(card['state']!='available' for card in summary['cards'])
    assert not summary['followups']
