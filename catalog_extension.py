"""Dated Nasdaq symbol-directory expansion. No network access on page render.

Preserve legacy ETF names and the existing stock catalog. New official ETF
symbols colliding with the stock catalog are reported for explicit review.
This is a listing universe, not an AUM ranking or a claim of complete data.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

PATH=Path(__file__).with_name('etf_directory.json')


def load_directory(path=PATH):
    if not Path(path).is_file():return {'funds':{},'sources':[],'fetched_at':None}
    result=json.loads(Path(path).read_text(encoding='utf-8'))
    funds=result.get('funds')
    if not isinstance(funds,dict) or not 700<=len(funds)<=20000 or 'QQQI' not in funds:
        raise ValueError('Invalid official ETF directory; refusing silent truncation')
    for t,r in funds.items():
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}',t) or not isinstance(r,dict) or not r.get('name'):
            raise ValueError('Malformed ETF record')
    return result


def install(core):
    directory=load_directory()
    core.ETF_DIRECTORY_AS_OF=directory.get('fetched_at')
    core.ETF_DIRECTORY_SOURCES=directory.get('sources',[])
    conflicts=sorted(set(directory['funds']) & set(core.STOCK_NAMES))
    core.ETF_DIRECTORY_CONFLICTS=conflicts
    additions={t:r['name'] for t,r in directory['funds'].items() if t not in core.STOCK_NAMES}
    old=dict(core.ETF_NAMES)
    core.ETF_NAMES={**old,**additions}
    priority=['QQQI','SPYI','JEPQ','JEPI','SCHD','DIVO','GPIX','GPIQ']
    core.ETF_POOL=tuple(dict.fromkeys([*(t for t in priority if t in core.ETF_NAMES),*old,*core.ETF_NAMES]))
    core.ETF_LIMIT=len(core.ETF_POOL)
    core.DEFAULT_ETFS=core.ETF_POOL
    core.CATALOG_SIZE=core.COMMON_STOCK_LIMIT+core.ETF_LIMIT


def fingerprint(universe):
    return hashlib.sha256('\n'.join(universe).encode()).hexdigest()
