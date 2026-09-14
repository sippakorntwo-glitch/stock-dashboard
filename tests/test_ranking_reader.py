"""Blocked provider and publication-order regressions; unit fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
import threading

import pytest

import ranking_board as board


REPO='sippakorntwo-glitch/stock-dashboard'


def publication(stamp='2026-09-11T14:00:00Z'):
    return {'schema':board.SCHEMA,'model':board.MODEL,'computed_at':stamp,
            'counts':{'total':1,'scanned':1,'evaluated':0},'items':[]}


def finish(reader):
    reader.thread.join(timeout=3)
    assert not reader.thread.is_alive()


def test_blocked_ranking_download_never_blocks_readers_or_duplicates_request():
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def fetch(repo):
        calls.append(repo)
        entered.set()
        assert release.wait(10)
        return publication(),''
    reader=board.RankingReader(REPO,fetcher=fetch)
    try:
        assert reader.read()==(None,'',True)
        assert entered.wait(2)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:reader.read(),range(32)))
        assert all(value==(None,'',True) for value in results)
        assert calls==[REPO]
    finally:
        release.set()
        finish(reader)
    payload,error,busy=reader.read()
    assert payload==publication() and not error and not busy
    assert calls==[REPO]


def test_failures_and_older_publications_retain_original_source_time_and_retry_cadence():
    now=[0.]
    good=publication()
    replies=[(good,''),(None,board.READ_ERROR),
             (publication('2026-09-11T13:30:00Z'),''),
             ({**good,'items':'corrupt'},''),
             (publication('2026-09-11T14:30:00Z'),'')]
    calls=[]
    def fetch(repo):
        calls.append(repo)
        return replies.pop(0)
    reader=board.RankingReader(REPO,fetcher=fetch,clock=lambda:now[0])
    reader.read();finish(reader)
    payload,error,busy=reader.read()
    payload['computed_at']='local mutation must not affect shared state'
    assert reader.read()[0]==good
    for n in range(1,5):
        now[0]=n*60-1
        assert not reader.read()[2] and len(calls)==n
        now[0]=n*60
        reader.read();finish(reader)
        payload,error,busy=reader.read()
        assert not busy and len(calls)==n+1
        if n<4:
            assert payload==good and error
        else:
            assert payload==publication('2026-09-11T14:30:00Z') and not error


def test_unexpected_download_exception_releases_worker_and_retains_data():
    now=[0.]
    count=[0]
    def fetch(repo):
        count[0]+=1
        if count[0]>1:raise RuntimeError('private diagnostic details')
        return publication(),''
    reader=board.RankingReader(REPO,fetcher=fetch,clock=lambda:now[0])
    reader.read();finish(reader)
    now[0]=60
    reader.read();finish(reader)
    payload,error,busy=reader.read()
    assert payload==publication() and error==board.READ_ERROR and not busy
    assert 'private' not in error


@pytest.mark.skipif(os.environ.get('DASHBOARD_OFFLINE_TEST_STUBS')=='1',reason='Requires actual Streamlit')
def test_render_and_other_widgets_remain_usable_while_ranking_fetch_is_blocked(monkeypatch):
    from streamlit.testing.v1 import AppTest
    entered,release=threading.Event(),threading.Event()
    previous=publication()
    def fetch(repo):
        entered.set()
        assert release.wait(15)
        return None,board.READ_ERROR
    reader=board.RankingReader(REPO,fetcher=fetch)
    class Cache:
        writes=[]
        def get(self,*args,**kwargs):
            return deepcopy(previous),{'fetched_at':'2026-09-11T14:01:00Z'}
        def put(self,*args):self.writes.append(args)
    cache=Cache()
    monkeypatch.delenv('DASHBOARD_RANKING_FILE')
    monkeypatch.setattr(board,'ranking_reader',lambda *args:reader)
    monkeypatch.setattr(board.a,'settings',lambda:{'DASHBOARD_DATA_REPO':REPO})
    monkeypatch.setattr(board.a,'get_data_cache',lambda:cache)
    try:
        at=AppTest.from_string('''
import streamlit as st
import dashboard_runtime as a
from ranking_board import render_board
render_board(a.get_data_cache())
st.checkbox('Independent filter',key='diagnostic_filter')
''',default_timeout=5).run()
        assert entered.wait(2) and not at.exception,str(at.exception)
        assert any('กำลังตรวจอันดับ' in item.value for item in at.caption)
        assert any('จัดอันดับ' in item.value for item in at.caption)
        at.checkbox(key='diagnostic_filter').check().run()
        assert not at.exception,str(at.exception)
        assert at.checkbox(key='diagnostic_filter').value
        assert cache.writes==[]  # no new timestamp assigned to the cached source
    finally:
        release.set()
        finish(reader)
    at.run()
    assert not at.exception,str(at.exception)
    assert any(board.READ_ERROR in item.value for item in at.warning)
    assert any('จัดอันดับ' in item.value for item in at.caption)
