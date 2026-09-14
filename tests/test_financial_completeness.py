"""Financial refresh loss and full-catalog revision regression tests."""
from copy import deepcopy
from datetime import datetime, timezone
import pytest
from financial_completeness import preserve_refresh, statement_gaps
from company_financials_job import due_symbols


def bundle():
    return {'schema':1, 'ticker':'TEST', 'currency':'USD', 'errors':[],
            'fetched_at':'2026-09-01T00:00:00Z',
            'annual':{'income':[{'end':'2025-12-31','values':{'revenue':100, 'grossProfit':40}}]},
            'quarterly':{}}


def test_silent_success_omissions_preserve_history_and_dated_values():
    before=bundle(); incoming=deepcopy(before)
    incoming['fetched_at']='2026-09-14T00:00:00Z'
    incoming['annual']['income'][0]['values']={'revenue':110, 'netIncome':10}
    result=preserve_refresh(before, incoming)
    row=result['annual']['income'][0]
    assert row['values']=={'revenue':110, 'grossProfit':40, 'netIncome':10}
    assert row['field_fetched_at']['grossProfit']==before['fetched_at']
    assert row['field_fetched_at']['revenue']==incoming['fetched_at']
    assert before['annual']['income'][0]['values']=={'revenue':100,'grossProfit':40}
    empty=deepcopy(incoming); empty['annual']={}
    restored=preserve_refresh(result, empty)
    assert restored['annual']['income'][0]['values']==row['values']


def test_partial_refresh_can_add_missing_fields_without_revising_existing_values():
    before=bundle(); incoming=deepcopy(before)
    incoming['errors']=[{'statement':'quarterly.balance','error':'TimeoutError'}]
    incoming['annual']['income'][0]['values']={'revenue':999,'netIncome':0}
    result=preserve_refresh(before,incoming)
    assert result['annual']['income'][0]['values']=={'revenue':100,'grossProfit':40,'netIncome':0}
    assert result['errors']==incoming['errors']


@pytest.mark.parametrize('key,value',[('currency','EUR'),('currency',None),('ticker','OTHER'),('schema',999)])
def test_never_merge_currency_or_identity_changes(key,value):
    incoming=bundle(); incoming[key]=value
    with pytest.raises(ValueError):
        preserve_refresh(bundle(),incoming)


def test_zero_is_available_and_absence_is_not_zero():
    value=bundle(); value['annual']['income'][0]['values']={'revenue':0}
    gaps=statement_gaps(value)
    row=next(r for r in gaps if r['period']=='annual' and r['statement']=='income')
    assert 'revenue' not in row['missing'] and 'grossProfit' in row['missing']
    assert any(r['statement']=='cashflow' and r['end'] is None for r in gaps)


def test_new_collection_revision_rechecks_recent_success_but_not_failure_cooldown():
    now=datetime(2026,9,14,tzinfo=timezone.utc).timestamp()
    profiles={'info:TEST':({'financialCurrency':'USD'}, {})}
    stored={'financials:TEST':(bundle(),{'fetched_at':'2026-09-13T00:00:00Z','available':True})}
    attempt={'attempt:financials:TEST':({}, {'success':True,'retry_after':'2026-09-20T00:00:00Z'})}
    assert due_symbols(['TEST'],profiles,stored,attempt,set(),now=now,only_missing=True)==['TEST']
    attempt['attempt:financials:TEST'][1]['success']=False
    assert due_symbols(['TEST'],profiles,stored,attempt,set(),now=now,only_missing=True)==[]
    stored['financials:TEST'][0]['collection_revision']=2
    attempt['attempt:financials:TEST'][1]['success']=True
    assert due_symbols(['TEST'],profiles,stored,attempt,set(),now=now,only_missing=True)==[]
