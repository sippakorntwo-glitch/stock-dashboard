"""Guarded source review of financial edge cases; no upstream data rewriting."""
from pathlib import Path

def edit(path,old,new):
    p=Path(path);s=p.read_text()
    if s.count(old)!=1:raise RuntimeError(f'{path}: missing or ambiguous edge-case anchor')
    p.write_text(s.replace(old,new))

edit('company_research.py',"annual=[p for p in annual if isinstance(p,dict) and p.get('end') and p['end']<=current.date().isoformat()]", "annual=[p for p in annual if isinstance(p,dict) and p.get('end') and p['end']<=current.date().isoformat() and p.get('filed') and p['filed']<=current.date().isoformat()]")
edit('company_research.py',"            if spec.key in RATIOS_POSITIVE and value<=0:status='not_meaningful'", "            if spec.key in RATIOS_POSITIVE and value<=0:status='not_meaningful'\n            if spec.key=='de' and value<0:\n                status='not_meaningful';note='A negative debt/equity ratio is not low leverage; investigate non-positive equity or source inconsistency.'")
edit('financial_statements.py',"    if isinstance(cik,bool) or int(payload.get('cik',0))!=int(cik):raise ValueError('Company facts CIK mismatch')", "    if isinstance(cik,bool) or isinstance(payload.get('cik'),bool) or int(payload.get('cik',0))!=int(cik):raise ValueError('Company facts CIK mismatch')")
edit('company_metrics.py',"REIT ต้องดู FFO/AFFO แทนกำไร GAAP'),", "REIT ต้องดู FFO/AFFO แทนกำไร GAAP',True),")
Path(__file__).unlink()
