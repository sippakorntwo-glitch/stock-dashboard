"""Display the actual return inputs; do not silently compare different dates/bases."""
from __future__ import annotations
import math
import pandas as pd
import streamlit as st
from return_periods import RETURN_SPECS,return_observations,daily_closes,RETURN_CAPTION


def render_return_audit(ticker,history,row):
    with st.expander('Return Calculation Details — '+ticker,expanded=False):
        st.caption(RETURN_CAPTION)
        if history is None or history.empty:
            st.info('Daily history has not been prepared for this security yet.');return
        close=daily_closes(history)
        if close.empty:st.info('No usable daily dates.');return
        asof=pd.to_datetime(row.get('Price_AsOf'),errors='coerce')
        if pd.isna(asof):
            import dashboard_runtime as a
            completed=a.completed_daily_history(history)
            if completed.empty:st.info('No completed daily session yet.');return
            asof=pd.Timestamp(completed.index[-1]).tz_localize(None).normalize()
        else:asof=pd.Timestamp(asof).tz_localize(None).normalize()
        default=min(asof,close.index[-1])
        first=close.index[0]
        if default<first:st.info('Snapshot date is earlier than the local history; waiting for synchronized data.');return
        date_key='return_audit_date_'+ticker
        existing=st.session_state.get(date_key)
        if existing is not None and not first.date() <= existing <= default.date():
            st.session_state[date_key]=default.date()
        selected=st.date_input('Return As Of',value=default.date(),min_value=first.date(),max_value=default.date(),
                               key='return_audit_date_'+ticker,
                               help='Choose the same end date as the external site, for example its month-end date. Weekends use the last available daily close before that date. This does not change trading scores.')
        data=close.loc[close.index<=pd.Timestamp(selected)].to_frame('Close')
        observations=return_observations(data);records=[]
        for field,label,days,months in RETURN_SPECS:
            o=observations[field]
            expected=(o['end_price']/o['start_price']-1)*100 if o['start_price'] and o['end_price'] else None
            stored=row.get(field)
            same_end=o.get('end')==str(row.get('Price_AsOf'))[:10]
            check='Not the snapshot date'
            if same_end and stored is not None and not pd.isna(stored) and expected is not None:
                check='Matches snapshot' if math.isclose(float(stored),expected,abs_tol=.001) else 'Snapshot/history differ — refresh required'
            elif same_end:check=o['state'].replace('_',' ')
            records.append({'Period':label,'Count Convention':f'{days} trading sessions' if days else 'Calendar period / previous trading close',
                'Requested Start':o.get('requested_start'),'Actual Start':o.get('start'),'Actual End':o.get('end'),
                'Start Adjusted Close':o.get('start_price'),'End Adjusted Close':o.get('end_price'),
                'Cumulative Return (%)':o['value'],'Annualized Return (%)':o.get('annualized'),
                'Data Status':o['state'].replace('_',' '),'Snapshot Check':check})
        table=pd.DataFrame(records)
        st.dataframe(table,hide_index=True,width='stretch',column_config={
            'Start Adjusted Close':st.column_config.NumberColumn(format='%.6f'),
            'End Adjusted Close':st.column_config.NumberColumn(format='%.6f'),
            'Cumulative Return (%)':st.column_config.NumberColumn(format='%+.4f%%'),
            'Annualized Return (%)':st.column_config.NumberColumn(format='%+.4f%%')})
        st.caption('Annualized = ((end / start)^(12 / calendar months) − 1) × 100, shown only for horizons of at least 1 year. '
                   'The screener annualizes only 3Y and 5Y when that mode is selected. '
                   'A fund distribution rate / SEC yield is not its price return. NAV returns can differ from market-close returns. '
                   'Yahoo dividend-adjusted prices are a return proxy, not a certified fund total-return record. '
                   'The chart header measures first-to-last candle of the selected preset period (not the current zoom); intraday charts are not the same daily-session baseline as this table.')
        st.download_button('Download Return Calculation Details',table.to_csv(index=False).encode('utf-8-sig'),
                           ticker+'_return_calculation.csv','text/csv',key='download_return_audit_'+ticker)
