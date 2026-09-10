"""Read public AAPL history into a separate cold cache, without Yahoo calls."""
import faulthandler
import json
import time
import dashboard_runtime as a


def main():
    started=time.monotonic()
    reader,error=a.get_remote_reader()
    if error or reader is None:
        raise RuntimeError(error or 'No reader')
    cache=a.get_data_cache()
    assert reader.cache is cache
    reader.refresh()
    for _ in range(90):
        if reader.status()['manifest']: break
        time.sleep(1)
    assert reader.status()['manifest'], reader.status()
    cache.history('AAPL')
    for _ in range(90):
        state=reader.status()
        history,meta=cache.history('AAPL')
        info,_=cache.get('info:AAPL')
        if history is not None and len(history)>60 and info:
            print('PUBLIC_COLD_READ_OK:',json.dumps({'seconds':round(time.monotonic()-started,2),'bars':len(history),'fetched_at':meta.get('fetched_at'),'generation':state['manifest']['generation']}),flush=True)
            return
        if state.get('error') and not state['busy']: break
        time.sleep(1)
    print('READER_STATE:',json.dumps(reader.status(),ensure_ascii=False),flush=True)
    faulthandler.dump_traceback()
    raise RuntimeError('Public cold history read failed')


if __name__=='__main__': main()
