from copy import deepcopy
from datetime import datetime, timezone
from asset_data_audit import reference_queue

NOW=datetime(2026,9,12,12,tzinfo=timezone.utc)


def test_unchecked_symbols_precede_old_head_and_recent_failures_wait():
    references={
        'A':{'cik':1,'checked_at':'2026-09-01T12:00:00Z'},
        'B':{'cik':2},
        'C':{'cik':3,'last_attempt_at':'2026-09-12T11:00:00Z'},
        'D':{'cik':4,'checked_at':'2026-09-11T12:00:00Z'},
        'E':{'cik':5,'last_attempt_at':'2026-09-02T12:00:00Z'},
    }
    before=deepcopy(references)
    assert reference_queue(['A','B','C','D','E','B'],references,NOW)==['B','A','E']
    assert references==before


def test_stable_initial_priority_and_invalid_identity_do_not_receive_requests():
    references={'AAAU':{'cik':1708646},'FIRST':{'cik':7},'BAD':{'cik':True},'ZERO':{'cik':0},'TEXT':{'cik':'8'}}
    assert reference_queue(['AAAU','FIRST','BAD','ZERO','TEXT','UNKNOWN'],references,NOW)==['AAAU','FIRST']
