"""Real SQLite WAL reads stay coherent while a second thread commits new data."""
import threading
import json
import pandas as pd
import pytest
import dashboard_runtime as a
from read_view import consistent_read, scoped_cache

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
