"""Real SQLite WAL reads stay coherent while a second thread commits new data."""
import threading
import json
import pandas as pd
import pytest
import dashboard_runtime as a
from read_view import consistent_read, scoped_cache, page_dependencies

def cache_with_data(tmp_path):
    cache=a.DashboardCache(tmp_path/'view.sqlite3')
    cache.put('remote:manifest',{'generation':'g1'},{})
    cache.put('info:AAPL',{'name':'old'},{'snapshot_generation':'g1'})
    cache.save_quotes(pd.DataFrame([{'Ticker':'AAPL','Close':100,'Data_Time':'2026-09-11T00:00:00Z'}]))
    return cache

def test_wal_view_does_not_block_writer_and_all_reads_keep_old_generation(tmp_path):
    cache=cache_with_data(tmp_path)
    with consistent_read(cache) as view:
        finished=threading.Event()
        def writer():
            cache.put('info:AAPL',{'name':'new'},{'snapshot_generation':'g2'})
            cache.put('remote:manifest',{'generation':'g2'},{})
            # Exercise WAL isolation independently of quote-quality merge rules.
            with cache.connect() as db:
                db.execute('UPDATE quotes SET body=? WHERE ticker=?',
                           (json.dumps({'Ticker':'AAPL','Close':200}),'AAPL'))
            finished.set()
        thread=threading.Thread(target=writer);thread.start()
        assert finished.wait(3),'render read transaction blocked a writer'
        thread.join()
        assert view.get('remote:manifest')[0]['generation']=='g1'
        assert view.get('info:AAPL')[0]['name']=='old'
        assert view.quotes()['AAPL']['Close']==100
        assert scoped_cache(cache) is view
    assert scoped_cache(cache) is cache
    assert view.get('remote:manifest')[0]['generation']=='g2'
    assert cache.quotes()['AAPL']['Close']==200

def test_cache_scope_is_thread_local_and_cleans_up_on_interrupted_render(tmp_path):
    cache=cache_with_data(tmp_path);observed=[]
    with pytest.raises(RuntimeError):
        with consistent_read(cache) as view:
            thread=threading.Thread(target=lambda:observed.append((scoped_cache(cache),view.active)))
            thread.start();thread.join()
            assert observed==[(cache,False)]
            raise RuntimeError('simulated rerun')
    assert scoped_cache(cache) is cache and view.closed

def test_read_transaction_is_read_only_and_nested_reads_do_not_release_it(tmp_path):
    cache=cache_with_data(tmp_path)
    with consistent_read(cache) as view:
        with view.connect() as db:
            assert db.execute('SELECT count(*) FROM objects').fetchone()[0]==2
        cache.put('info:AAPL',{'name':'later'},{})
        assert view.get('info:AAPL')[0]['name']=='old'
        import sqlite3
        with pytest.raises(sqlite3.OperationalError):
            with view.connect() as db:db.execute('DELETE FROM objects')

def test_fallback_view_copies_values_without_holding_shared_lock(tmp_path):
    cache=cache_with_data(tmp_path);cache.error='simulated disk failure'
    cache._fallback={'info:AAPL':({'name':'old'}, {})}
    with consistent_read(cache) as view:
        cache._fallback['info:AAPL'][0]['name']='new'
        value,_=view.get('info:AAPL');value['name']='mutated read'
        assert view.get('info:AAPL')[0]['name']=='old'


def test_page_dependencies_cover_comparisons_and_benchmark_with_fixed_bound():
    assert page_dependencies('AAPL', ['AAPL', 'QQQ', 'MSFT']) == ('AAPL', 'QQQ', 'MSFT', 'SPY')
    assert page_dependencies('SPY') == ('SPY', 'QQQ')
    assert page_dependencies('AAPL', []) == ('AAPL', 'SPY')
    assert len(page_dependencies('AAPL', [f'T{i}' for i in range(100)])) == 8
    assert page_dependencies('!', ['MSFT', None, 'invalid space']) == ('MSFT', 'SPY')


def test_comparison_completion_is_frozen_with_its_data_and_old_generation_is_hidden(tmp_path, monkeypatch):
    from data_sync import SnapshotReader, shard_number
    cache = cache_with_data(tmp_path)
    reader = SnapshotReader(object(), cache)
    cache.remote = reader
    monkeypatch.setattr(reader, '_start', lambda: None)
    reader.manifest = {'generation': 'g1', 'details': {}}
    cache.put('info:SPY', {'name': 'prior generation'},
              {'snapshot_generation': 'g0', 'snapshot_source': reader.source_id,
               'fetched_at': '2026-09-09T00:00:00Z'})
    cache.put('remote:detail:SPY', {'generation': 'g0'}, {})
    for symbol in ('AAPL', 'SPY'):
        reader.shards.setdefault(str(shard_number(symbol)), {})[symbol] = [
            ('info:' + symbol, {'name': symbol + ' current'},
             {'fetched_at': '2026-09-10T00:00:00Z'})]
    reader._details('AAPL')
    dependencies = page_dependencies('AAPL', ['AAPL', 'SPY'])
    with consistent_read(cache, 'AAPL', dependencies) as view:
        before = view.page_revision(dependencies)
        assert view.get('info:SPY')[0] is None
        done = threading.Event()
        def complete():
            reader._details('SPY')
            done.set()
        writer = threading.Thread(target=complete)
        writer.start()
        assert done.wait(3), 'a pinned page blocked comparison completion'
        writer.join()
        assert reader.page_status(dependencies)['page_revision'] != before
        assert view.page_revision(dependencies) == before
        assert view.get('info:SPY')[0] is None
        assert view.get('info:AAPL')[0]['name'] == 'AAPL current'
        # A widget can remove a no-longer-listed choice after the view starts;
        # the remaining revision still comes from this view, never live counters.
        assert view.page_revision(('SPY',)) == (before[0], (('SPY', 0),))
    with consistent_read(cache, 'AAPL', dependencies) as view:
        assert view.get('info:SPY')[0]['name'] == 'SPY current'
        assert view.page_revision(dependencies) == reader.page_status(dependencies)['page_revision']
