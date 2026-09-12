"""Compact optional research sources; not a system status/debug panel."""
from __future__ import annotations
from urllib.parse import quote,urlsplit
import pandas as pd
import streamlit as st
from asset_semantics import REVIEWED_INSTRUMENTS,kind_for


def trusted_link(url):
    try:
        part=urlsplit(str(url))
        return part.scheme=='https' and part.hostname in ('www.sec.gov','data.sec.gov','www.gsam.com','am.gs.com','neosfunds.com') and not part.username and not part.password and part.port in (None,443)
    except ValueError:return False


def render_references(ticker,info,is_etf,cache):
    kind=kind_for(ticker,info,is_etf)
    if kind=='physical_gold':
        st.info('AAAU holds physical gold, not operating-company shares. P/E and corporate analyst targets are N/A, not a loading error. Review gold exposure, fund assets, NAV, sponsor fee and liquidity instead.')
    elif kind=='non_equity_fund':
        st.caption('This fund has non-equity exposure according to its reported category. Corporate P/E and analyst targets are not applicable; missing fund-specific figures remain Not reported.')
    elif is_etf:
        st.caption('For equity funds, portfolio P/E describes underlying holdings, not company earnings per ETF unit. N/A means not applicable; Not reported means the source did not supply a meaningful field.')
    reference,_=cache.get('reference:'+ticker,request_remote=False)
    reference=reference if isinstance(reference,dict) else {}
    curated=REVIEWED_INSTRUMENTS.get(ticker,{})
    with st.expander('Official sources & filed financials',expanded=False):
        cik=reference.get('cik') or curated.get('cik')
        url=f'https://www.sec.gov/edgar/browse/?CIK={int(cik):010d}&owner=exclude' if isinstance(cik,int) and 0<cik<10**10 else 'https://www.sec.gov/edgar/search/#/q='+quote(ticker,safe='')
        st.link_button('SEC filings',url)
        if curated and trusted_link(curated.get('issuer_url')):st.link_button('Official fund page',curated['issuer_url'])
        if ticker in ('QQQI','SPYI'):st.link_button('Official fund page','https://neosfunds.com/'+ticker.lower()+'/')
        if curated:
            st.write(curated['description'])
            st.write(f"Annual sponsor fee: {curated['sponsor_fee_pct']:.2f}% — annual filing as of {curated['source_as_of']}; reviewed {curated['reviewed_at']}. Not a live NAV or price.")
            st.link_button('Gold trust annual report',curated['filing_url'])
        if reference.get('sic_description'):
            st.caption('SEC SIC '+str(reference.get('sic'))+' — '+str(reference['sic_description'])+' (different taxonomy from the provider Industry field)')
        facts=reference.get('facts',[])
        if facts:
            rows=[{'Metric':r['metric'],'Value':r['value'],'Unit':r['currency'],
                   'Period Start':r.get('period_start') or 'Point-in-time','Period End':r['period_end'],
                   'Filed':r['filed']} for r in facts]
            st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
            st.caption('SEC reported fiscal-year or point-in-time figures, NOT TTM estimates. Calculated margin/FCF use the same filing, period and currency. They are supplementary and do not overwrite market prices, forward P/E, target prices or trading scores.')
            links={r['url'] for r in facts if trusted_link(r.get('url'))}
            for i,link in enumerate(sorted(links)[:3]):st.link_button('Open supporting filing '+str(i+1),link)
        if reference.get('checked_at'):st.caption('SEC reference received: '+str(reference['checked_at']))
        st.caption('External sources can report different dates, accounting periods and definitions. No averaging of conflicting values or zero-filling of absent data. SEC filings are not an intraday price feed; proprietary estimates may require a licensed provider.')
