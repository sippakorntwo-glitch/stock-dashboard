"""Missing-data browser expectations must follow checked source observations."""
import gzip
import hashlib
import json

import pytest
import quality_smoke


@pytest.mark.parametrize('bundle', [None, {'annual':{},'quarterly':{}},
    {'annual':{'income':[{'end':'2025-12-31','values':{'revenue':7}}]},'quarterly':{}}])
def test_statement_expectations_preserve_absent_empty_and_partial_sources(monkeypatch,bundle):
    generation='generations/20260913T150000Z-aaaaaaaa'
    slot=str(int(hashlib.sha256(b'AESP').hexdigest()[:8],16)%128)
    records=[['OTHER','financials:OTHER',{'annual':{'income':[{'end':'2025-12-31'}]}},{}]]
    if bundle is not None:
        records.append(['AESP','financials:AESP',bundle,{}])
    raw=gzip.compress('\n'.join(json.dumps(row) for row in records).encode())
    manifest={'generation':generation,'details':{slot:{'key':generation+f'/details/{slot}.jsonl.gz',
                                                    'sha256':hashlib.sha256(raw).hexdigest()}}}
    calls=[]
    def fetch(url):
        calls.append(url)
        assert '/dashboard-data-20260913T150000Z-aaaaaaaa/' in url
        return json.dumps(manifest).encode() if url.endswith('/manifest.json') else raw
    monkeypatch.setattr(quality_smoke,'fetch_public',fetch)
    assert quality_smoke.financials_for_generation(generation,'AESP')==bundle
    assert len(calls)==2
    manifest['details'][slot]['sha256']='0'*64
    with pytest.raises(AssertionError):
        quality_smoke.financials_for_generation(generation,'AESP')
