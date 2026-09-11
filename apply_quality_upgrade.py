"""One-shot guarded source assembly; removed after the validated feature commit."""
from pathlib import Path
import re

def replace(path,old,new):
    p=Path(path);s=p.read_text()
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected exactly one anchor {old[:70]!r}, got {s.count(old)}')
    p.write_text(s.replace(old,new,1))

for path in ['app.py','dashboard_runtime.py']:
    p=Path(path);s=p.read_text()
    if '2026-09-11.18' not in s:raise RuntimeError('Unexpected release in '+path)
    p.write_text(s.replace('2026-09-11.18','2026-09-11.19'))
replace('dashboard_runtime.py','base_build_frame = core.build_universe_frame','base_build_frame = core.build_universe_frame\nbase_select_universe = core.select_universe')
p=Path('dashboard_runtime.py');s=p.read_text()
start=s.index('    def save_classification(self, ticker, info):')
end=s.index('\n\ndef scan_snapshot_row',start)
s=s[:start]+'''    def put(self, key, value, meta):
        from data_quality import industry_value, timestamp, VERSION
        meta = dict(meta)
        if key.startswith('info:') and isinstance(value, dict):
            old, oldmeta = self.get(key, request_remote=False)
            stamp = meta.get('fetched_at') or value.get('_Fetched_At_UTC')
            if old and timestamp(oldmeta.get('fetched_at')) > timestamp(stamp):
                return
            ticker = key.split(':', 1)[1]
            meta.update(quality_version=VERSION, classification_available=industry_value(value, ticker in core.ETF_NAMES or value.get('quoteType')=='ETF') is not None)
            super().put(key, value, meta)
            self.save_classification(ticker, {**value, '_Fetched_At_UTC':stamp or ''})
            return
        return super().put(key, value, meta)

    def save_classification(self, ticker, info):
        from data_quality import industry_value, timestamp
        is_etf = ticker in core.ETF_NAMES or info.get('quoteType') == 'ETF'
        value = industry_value(info, is_etf)
        if value is None:
            return
        import json
        with self._lock:
            old = self._fallback_classifications.get(ticker, {})
            if not self.error:
                with self.connect() as db:
                    saved = db.execute('SELECT body FROM classifications WHERE ticker=?', (ticker,)).fetchone()
                    if saved: old = json.loads(saved[0])
            if timestamp(old.get('Industry_Time')) > timestamp(info.get('_Fetched_At_UTC')):
                return
            normalized = {**info, 'category' if is_etf else 'industry':value}
            super().save_classification(ticker, normalized)


def select_universe(csv_frame=None):
    # Empty/default callers (including tests and rankers) use the same deployed CSV
    # as the dashboard, not a different truncated 4,200-stock alphabetical pool.
    if csv_frame is None or csv_frame.empty:
        if core.WATCHLIST_FILE.exists():
            csv_frame = pd.read_csv(core.WATCHLIST_FILE, usecols=['Ticker'], dtype=str)
        else:
            csv_frame = pd.DataFrame(columns=['Ticker'])
    return base_select_universe(csv_frame)
''' +s[end:]
p.write_text(s)
replace('dashboard_runtime.py','core.build_universe_frame = build_universe_frame','core.build_universe_frame = build_universe_frame\ncore.select_universe = select_universe')
replace('data_sync.py','    cache.put("remote:watchlist", summary.get("watchlist_csv"), {"fetched_at": utc_now()})','    cache.put("remote:watchlist", summary.get("watchlist_csv"), {"fetched_at": utc_now()})\n    cache.put("remote:universe", summary.get("universe", []), {"fetched_at": utc_now()})\n    cache.put("remote:quality", summary.get("quality", {}), {"fetched_at": utc_now()})')
replace('update_data.py','    generation = "generations/" + time.strftime','    from data_quality import prepare_cached_metadata, make_quality\n    prepare_cached_metadata(cache, universe, app.ETF_NAMES)\n    quality = make_quality(cache, universe, etfs=app.ETF_NAMES)\n    generation = "generations/" + time.strftime')
replace('update_data.py','"universe": list(universe), "watchlist_csv": watchlist_csv}','"universe": list(universe), "watchlist_csv": watchlist_csv, "quality": quality}')
replace('update_data.py','"coverage": coverage, "report": report,','"coverage": coverage, "quality_counts": quality["counts"], "report": report,')
replace('update_data.py','            if f"{kind}:{ticker}" not in metadata:\n                missing.append(kind)','            if f"{kind}:{ticker}" not in metadata:\n                missing.append(kind)\n            elif kind == "info" and metadata[f"info:{ticker}"].get("classification_available") is False:\n                missing.append(kind)')
replace('update_data.py','            due.extend(retry_due(metadata, kind, ticker) for kind in missing)','            due.extend(max(retry_due(metadata, kind, ticker),\n                stamp_seconds(metadata.get(f"info:{ticker}", {}).get("fetched_at")) + 86400\n                if kind == "info" and metadata.get(f"info:{ticker}", {}).get("classification_available") is False else 0) for kind in missing)')
p=Path('update_data.py');s=p.read_text();start=s.index('    metadata = object_metadata(cache)\n    jobs = []');end=s.index('    report["finished_at"] = utc_now()',start)
s=s[:start]+'''    from metadata_repair import collect_metadata
    collect_metadata(cache, universe, mode, metadata_minutes, metadata_limit, report,
                     app=app, get_metadata=object_metadata, record_attempt=record_attempt)
'''+s[end:];p.write_text(s)
# Ranking must use the exact verified snapshot membership, even if a future source CSV changes.
replace('ranking_job.py','        universe = a.select_universe(pd.DataFrame(columns=[\'Ticker\']))',"        from data_sync import read_checked\n        from data_quality import checked_universe\n        import gzip\n        summary=json.loads(gzip.decompress(read_checked(store,manifest['summary'])))\n        universe=checked_universe(summary)")
replace('dashboard_views.py',"def overview(frame, selectable=False, prepared=None):","def overview(frame, selectable=False, prepared=None):")
replace('dashboard_views.py',"    styled = shown.style.format", "    from quality_views import industry_display, snapshot_quality, placeholder_options\n    shown = industry_display(shown, snapshot_quality(a.get_data_cache()))\n    styled = shown.style.format")
replace('dashboard_views.py','column_config=config,**options,**a.width_options(st.dataframe))','column_config=config,**options,**placeholder_options(),**a.width_options(st.dataframe))')
replace('dashboard_views.py',"    records=[]\n    for label,key,pct in fields:","    from quality_views import profile_value, profile_field_state, profile_unit\n    records=[]\n    for label,key,pct in fields:")
replace('dashboard_views.py',"else raw if isinstance(raw,str) else 'ไม่มีข้อมูล'","else profile_value(raw,info)")
replace('dashboard_views.py',"records.append({'มิติ':label,'ค่า':value,'ฟิลด์ต้นทาง':key})","records.append({'มิติ':label,'ค่า':value,'หน่วย': '%' if pct else profile_unit(info,key),'สถานะข้อมูล':profile_field_state(info,key),'ฟิลด์ต้นทาง':key})")
replace('dashboard_views.py',"    st.link_button('เปิด GitHub Actions'", "    from quality_views import render_quality_report\n    render_quality_report(cache,frame)\n    st.link_button('เปิด GitHub Actions'")
replace('dashboard_views.py',"    table(pd.DataFrame(rows))\n    if not result['correlation'].empty:","    table(pd.DataFrame(rows))\n    if 'SPY' not in result['prices']:st.caption('Beta vs SPY: ต้องเลือก SPY ในชุดเปรียบเทียบก่อน จึงมี benchmark ให้คำนวณ ไม่ใช่ค่า Beta เท่ากับศูนย์')\n    if not result['correlation'].empty:")
replace('dashboard_ui.py',"LAYOUT = 'single-page'","from quality_views import render_family_counts, render_symbol_quality\n\nLAYOUT = 'single-page'")
replace('dashboard_ui.py',"        with st.container(key='overview_controls'):","        render_family_counts(cache)\n        with st.container(key='overview_controls'):")
replace('dashboard_ui.py','        # Render once per selected symbol, not once per row in the catalog.','        render_symbol_quality(ticker,cache,history,info)\n        # Render once per selected symbol, not once per row in the catalog.')
replace('dashboard_help.py','    return st.dataframe(data,height=height,hide_index=hide_index,',"    kwargs.setdefault('placeholder','—')\n    return st.dataframe(data,height=height,hide_index=hide_index,")
replace('dashboard_help.py',"    return str(value)\n\n\ndef table_html", "    return '—' if str(value).strip().casefold() in ('none','nan','null','n/a','') else str(value)\n\n\ndef table_html")
replace('dashboard_core.py','ยังไม่มีประวัติปันผล กดโหลด/อัปเดตหุ้นที่เลือก','ยังรอประวัติปันผลจากงานเก็บข้อมูลอัตโนมัติ ตรวจรายละเอียดในหัวข้อข้อมูลที่ขาด')
replace('workspace_boot.py',"'ranking_engine'","'ranking_engine', 'ranking_policy', 'data_quality', 'metadata_repair', 'quality_views'")
p=Path('README.md');p.write_text(p.read_text()+'''\n\n## v19 — Data completeness repair\n\nThe market checkpoint, UI and Top 10 use the same deployed catalog. The ranking job validates and reads the snapshot's exact universe rather than re-deriving a different truncated list from an empty CSV. Metadata queues rotate stocks, ETFs, profiles and dividends; failed requests respect retry timestamps. Missing classifications in an otherwise successful profile are retried daily, not suppressed indefinitely by the existence of an info object.\n\nEvery snapshot contains field-level availability and per-symbol diagnostics. Tables use an explicit missing-value placeholder, with distinct pending/failed/not-reported/short-history/no-payment states. A successful empty dividend history is not confused with an unattempted request. Missing analyst forecasts or short IPO histories are never filled with invented zeros. Existing scoring, 500-row selection, cumulative returns, chart point inspector, Top 10 schedules and security remain unchanged.\n\n`audit_dashboard.py` verifies the public checkpoint read-only. `data_repair_job.py --publish` is restricted to an owner GitHub workflow with the same public repository and concurrency lock; it records before/after coverage and keeps valid observations on failure. Quality counts indicate availability, not comprehensive investment analysis or a guarantee that every field exists for every security.\n''')
print('V19_GUARDED_SOURCE_APPLIED')
