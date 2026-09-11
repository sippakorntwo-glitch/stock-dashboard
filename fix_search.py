"""One-time exact-ticker search integration, removed after successful packaging."""
from pathlib import Path

p=Path('screening.py');s=p.read_text()
assert 'def search_frame(' not in s
s += '''

def search_frame(frame, query):
    """Prefer an exact symbol; otherwise literal company/industry search.

    A query such as MSFT must select the company, not the many funds whose
    names contain MSFT. Prefix name: to deliberately search all name matches.
    """
    query = str(query or '').strip()
    if not query:
        return frame.copy()
    names_only = query.casefold().startswith('name:')
    text = query[5:].strip() if names_only else query
    if not text:
        return frame.copy()
    if not names_only:
        symbols = frame['Ticker'].fillna('').astype(str).str.upper()
        exact = symbols.eq(text.upper())
        if not exact.any():
            exact = symbols.eq(text.upper().replace('.', '-'))
        if exact.any():
            return frame.loc[exact].copy()
    mask = pd.Series(False, index=frame.index)
    fields = ('Security_Name',) if names_only else ('Ticker','Security_Name','Industry')
    for field in fields:
        values = frame.get(field, pd.Series(index=frame.index, dtype=object))
        mask |= values.fillna('').astype(str).str.contains(text, case=False, regex=False)
    return frame.loc[mask].copy()
'''
p.write_text(s)
p=Path('filters_ui.py');s=p.read_text()
old="""    if query:
        mask=pd.Series(False,index=work.index)
        for field in ['Ticker','Security_Name','Industry']:
            mask |= work[field].fillna('').astype(str).str.contains(query,case=False,regex=False)
        work=work.loc[mask]
"""
assert s.count(old)==1
s=s.replace(old,"    from screening import search_frame\n    work=search_frame(work,query)\n")
s=s.replace("st.text_input('Search Ticker / Company / Industry',key='stock_search')", "st.text_input('Search Ticker / Company / Industry',key='stock_search', help='Exact ticker matches take priority. Use name:MSFT to find every fund or company name containing MSFT.')")
p.write_text(s)
Path('fix_search.py').unlink()
