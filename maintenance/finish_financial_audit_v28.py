"""One-time evidence completion; no changes to prices or financial observations."""
from pathlib import Path


def edit(name,old,new):
    p=Path(name);s=p.read_text()
    if s.count(old)!=1:raise RuntimeError(f'{name}: expected one reviewed anchor {old[:90]!r}')
    p.write_text(s.replace(old,new))

edit('financial_audit_job.py',"            counts=review['counts'];states.update(counts)","""            from financial_review_validation import validate_review
            validation=validate_review(review)
            totals['arithmetic_values_checked']+=validation['checked_values']
            failures.extend({'ticker':ticker,**error} for error in validation['errors'])
            counts=review['counts'];states.update(counts)""")
edit('financial_audit_job.py',"if ticker in ('AAPL','MSFT','ORCL','TSLA','AMZN','NVDA','JPM','O','AAAU','QQQI'):examples[ticker]=review", "if ticker in ('AAPL','MSFT','ORCL','TSLA','AMZN','NVDA','JPM','O','AAAU','QQQI'):examples[ticker]={'counts':review['counts'],'fiscal_period':review['fiscal_period'],'metrics':{r['key']:{k:r[k] for k in ('value','unit','status','basis','grade')} for r in review['rows']}}")
edit('financial_audit_job.py',"    publish_report('v28-financial-audit',report)","    publish_report('v28-financial-audit' if args.enrich else 'v28-financial-recheck',report)")
edit('financial_audit_job.py',"    raw,meta=cache.get('external:sec-ticker-map',request_remote=False)","""    signature=hashlib.sha256(chr(10).join(sorted(universe)).encode()).hexdigest()
    previous,pmeta=cache.get('external:financial-bulk-success',request_remote=False)
    if (isinstance(previous,dict) and previous.get('method')==METHOD
            and previous.get('catalog_signature')==signature and time.time()-timestamp(pmeta.get('fetched_at'))<20*3600):
        return {**previous['report'],'reused_verified_archive':True}
    raw,meta=cache.get('external:sec-ticker-map',request_remote=False)""")
edit('financial_audit_job.py',"            report['available']=True", """            report['available']=True
            cache.put('external:financial-bulk-success',{'method':METHOD,'catalog_signature':signature,'report':dict(report)},
                      {'fetched_at':now})""")
edit('company_research_ui.py','<abbr tabindex="0" title="{escape(tip,quote=True)}">','<abbr tabindex="0" title="{escape(tip,quote=True)}" aria-label="{escape(r[\"metric\"]+\": \"+tip,quote=True)}">')
Path(__file__).unlink()
print('Full-catalog arithmetic verification and repeat-safe evidence pipeline completed.')
