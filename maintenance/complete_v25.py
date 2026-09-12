"""One-time reviewed completion of v25; applied only on its feature branch."""
from pathlib import Path


def edit(path, old, new):
    p=Path(path);s=p.read_text(encoding='utf-8')
    if s.count(old)!=1:raise RuntimeError(f'{path}: expected one reviewed anchor: {old[:100]}')
    p.write_text(s.replace(old,new),encoding='utf-8')

# Absence of a reported P/E with known non-positive EPS is not an unattempted fetch.
edit('asset_semantics.py',"    raw=info.get(field)\n    if raw is None", "    if not fund and field in ('forwardPE','trailingPE'):\n        eps=number(info.get('forwardEps' if field=='forwardPE' else 'trailingEps'))\n        if eps is not None and eps<=0:return 'not_meaningful'\n    raw=info.get(field)\n    if raw is None")
# Validate calculation inputs too, not just the text in the new table.
edit('dashboard_runtime.py',"core.WATCHLIST_NUMERIC_COLUMNS = list(dict.fromkeys",'''# Preserve original functions once; the coherent release loader replaces this
# module together with core, so wrappers never stack across releases.
_base_decision_context = core.decision_context
_base_criteria_score = core.criteria_score
_base_build_entry_plan = core.build_entry_plan
_base_build_analysis = core.build_analysis


def decision_context(history, info, benchmark=None, now=None):
    from asset_semantics import safe_numeric_profile
    safe=safe_numeric_profile(info, str(info.get('symbol') or ''), info.get('quoteType')=='ETF')
    return _base_decision_context(history,safe,benchmark,now)


def criteria_score(ctx, info, is_etf):
    from asset_semantics import safe_numeric_profile
    return _base_criteria_score(ctx,safe_numeric_profile(info,str(info.get('symbol') or ''),is_etf),is_etf)


def build_entry_plan(ctx, info, scored, is_etf, min_rr=2.0, now=None):
    from asset_semantics import safe_numeric_profile
    return _base_build_entry_plan(ctx,safe_numeric_profile(info,str(info.get('symbol') or ''),is_etf),scored,is_etf,min_rr,now)


def build_analysis(snapshot, selected_row, info):
    from asset_semantics import safe_numeric_profile
    ticker=str(selected_row.get('Ticker') or info.get('symbol') or '')
    safe=safe_numeric_profile(info,ticker,core.asset_is_etf(ticker,selected_row,info))
    return _base_build_analysis(snapshot,selected_row,safe)


core.decision_context=decision_context
core.criteria_score=criteria_score
core.build_entry_plan=build_entry_plan
core.build_analysis=build_analysis
core.WATCHLIST_NUMERIC_COLUMNS = list(dict.fromkeys''')
edit('screening.py',"        row={field:str(info[key]).strip()", "        from asset_semantics import safe_numeric_profile\n        info=safe_numeric_profile(info,ticker,info.get('quoteType')=='ETF')\n        row={field:str(info[key]).strip()")
# Declare the application/contact as required by SEC fair-access policy. Never
# impersonate a browser, rotate proxies, or retry another endpoint after 403/429.
edit('sec_reference.py','import json\nimport re','import json\nimport os\nimport re')
edit('sec_reference.py','    def __init__(self,session=None,max_requests=90):','    def __init__(self,session=None,max_requests=90,user_agent=None):')
edit('sec_reference.py','        self.max_requests=max_requests;self.calls=0;self.last=0.;self.blocked=False', '''        self.max_requests=max_requests;self.calls=0;self.last=0.;self.blocked=False
        self.user_agent=user_agent or os.environ.get('SEC_USER_AGENT','StockResearchWorkspace contact https://github.com/sippakorntwo-glitch/stock-dashboard')
        if '\\n' in self.user_agent or '\\r' in self.user_agent or len(self.user_agent)>250:
            raise ValueError('Invalid declared SEC User-Agent')''')
edit('sec_reference.py',"headers={'User-Agent':'StockResearchWorkspace/25 contact https://github.com/sippakorntwo-glitch/stock-dashboard',", "headers={'User-Agent':self.user_agent,")
edit('sec_reference.py',"            if response.status_code in (403,429):self.blocked=True",'''            if response.status_code in (403,429):self.blocked=True
            if response.status_code!=200:
                self.evidence.append({'url':url,'received_at':datetime.now(timezone.utc).isoformat(),
                                      'http_status':response.status_code})''')
# Preserve last-good mappings if a scheduled refresh is unavailable. A global
# persistent circuit prevents later runs from hammering a denied source.
edit('asset_data_audit.py',"    raw,meta=cache.get('external:sec-ticker-map',request_remote=False)",'''    raw,meta=cache.get('external:sec-ticker-map',request_remote=False)
    circuit,_=cache.get('external:sec-circuit',request_remote=False)
    if isinstance(circuit,dict) and timestamp(circuit.get('next_attempt_after'))>datetime.now(timezone.utc).timestamp():
        client.blocked=True
        report['cooldown_until']=circuit.get('next_attempt_after')''')
edit('asset_data_audit.py',"        index={}\n    references={}","        try:index=ticker_index(raw) if raw else {}\n        except (ValueError,TypeError):index={}\n    references={}")
edit('asset_data_audit.py',"    report.update(provider_requests=client.calls,blocked=client.blocked,reference_records=len(references),http_evidence=client.evidence)",'''    if client.blocked and client.calls:
        from datetime import timedelta
        until=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()
        cache.put('external:sec-circuit',{'next_attempt_after':until,'reason':'access denied or rate limit'},
                  {'fetched_at':stamp})
        report['cooldown_until']=until
    report.update(provider_requests=client.calls,blocked=client.blocked,reference_records=len(references),http_evidence=client.evidence)
    report['automatic_financials_status']='available' if report['financial_reports'] else 'unavailable; primary observations retained' ''')
# Give unrecoverable optional fields honest states; do not claim external source
# success just because the arithmetic audit passed.
edit('asset_data_audit.py',"parser.add_argument('--publish',action='store_true')", "parser.add_argument('--publish',action='store_true');parser.add_argument('--repair',action='store_true')")
edit('asset_data_audit.py',"    if args.enrich:report['external_sources']=enrich",'''    if args.repair:
        from repair_profile_validation import repair_invalid_profiles
        report['primary_repair']=repair_invalid_profiles(cache,universe,set(a.ETF_NAMES),profiles)
        before_references,rows,profiles=profile_audit(cache,universe,set(a.ETF_NAMES))
    if args.enrich:report['external_sources']=enrich''')
# Missing fields never become zeros in the exported/screened profiles either.
edit('asset_data_audit.py',"    report.update(finished_at=utc_now(),result='passed',", "    report.update(finished_at=utc_now(),result='passed',data_complete=not after['counts'].get('with_missing_applicable_fields',0) and not after['counts'].get('with_invalid_fields',0),")
# Avoid losing a just-opened choice to a queued full-page render in the browser
# tests: wait on the actual page receipt rather than increasing guessed sleeps.
edit('screener_smoke.py',"def choose(app,label,value,multi=False):\n    testid=", "def choose(app,label,value,multi=False):\n    from production_smoke import wait_page_ready\n    wait_page_ready(app)\n    testid=")
Path(__file__).unlink()
print('Completed input validation, explicit non-applicability, polite external access and audit scope.')
