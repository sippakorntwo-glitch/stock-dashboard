"""Browser evidence for selected-stock briefing without waiting for providers."""
from __future__ import annotations

from datetime import datetime
import ipaddress
from urllib.parse import urlsplit

from playwright.sync_api import expect


def _stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    assert parsed.tzinfo is not None, 'Source timestamp must specify its timezone'
    return parsed


def _safe_source_link(value):
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    assert parsed.scheme == 'https' and '.' in host and not parsed.username and not parsed.password, value
    assert parsed.port in (None, 443) and not host.endswith(('.local', '.localhost', '.internal')), value
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return
    raise AssertionError('Article source must not point at an IP address')


def verify_stock_brief(app, payload):
    """Check rendered evidence while allowing missing/stale/rate-limited feeds."""
    ticker, period = payload['ticker'], payload['period']
    app.wait_for_function("""([ticker, period]) => {
      const nodes = [...document.querySelectorAll('.stock-brief-receipt')]
        .filter(e => !e.closest('[data-stale="true"]'));
      return nodes.length === 1 && nodes[0].dataset.ticker === ticker
        && nodes[0].dataset.chartPeriod === period;
    }""", arg=[ticker, period], timeout=30000)
    card = app.locator('.st-key-stock_brief_panel')
    receipt = card.locator('.stock-brief-receipt')
    expect(card).to_have_count(1)
    expect(receipt).to_have_count(1)
    expect(card.get_by_role('heading', name='ราคาและข่าวประกอบการวิเคราะห์ · '+ticker, exact=True)).to_be_visible()
    expect(receipt).to_have_attribute('data-ticker', ticker)
    expect(receipt).to_have_attribute('data-chart-period', period)
    assert receipt.get_attribute('data-quote-seconds') == '60'
    assert receipt.get_attribute('data-news-seconds') == '300'
    rendered = _stamp(receipt.get_attribute('data-rendered-at'))
    text = card.inner_text()
    for heading in ('ตลาดปกติ', 'อ่านข่าวคู่กับกราฟ', 'ข่าวและประเด็นที่ควรตรวจ'):
        assert heading in text, heading
    assert 'EMA20/EMA50, SMA200 และ RSI' in text
    assert 'ฐานราคาและเวลาจึงอาจต่างกัน' in text
    source_quotes = []
    kinds = []
    for quote in card.locator('.brief-quote').all():
        kind, state = quote.get_attribute('data-kind'), quote.get_attribute('data-state')
        assert kind in ('regular', 'extended') and state in ('recent', 'stale', 'unknown')
        assert quote.get_attribute('data-ticker') == ticker
        stamp = quote.get_attribute('data-quote-time')
        source = _stamp(stamp)
        assert source <= rendered, (stamp, rendered.isoformat())
        if state == 'recent':
            assert 0 <= (rendered-source).total_seconds() <= 181, (stamp, rendered.isoformat())
        session = quote.get_attribute('data-session')
        assert session == 'regular' if kind == 'regular' else session in ('pre', 'post')
        source_quotes.append({'kind':kind, 'state':state, 'session':session, 'quote_time':stamp})
        kinds.append(kind)
    assert len(kinds) == len(set(kinds)), kinds
    if source_quotes:
        assert 'เวลาราคาต้นทาง:' in text
    else:
        assert 'ยังไม่มีราคาช่วงนี้ที่ตรวจสอบได้' in text
    checked = receipt.get_attribute('data-news-checked-at')
    if checked:
        assert _stamp(checked) <= rendered
        assert 'ตรวจข่าวสำเร็จ:' in text
    links = card.get_by_role('link', include_hidden=True)
    source_links = list(dict.fromkeys(links.evaluate_all('els => els.map(e => e.href).filter(Boolean)')))
    assert len(source_links) <= 10
    for href in source_links:
        _safe_source_link(href)
    if source_links:
        assert checked and 'เผยแพร่' in text
        assert 'ผลต่อราคา: ยังไม่ยืนยันจากข้อมูลข่าวที่มี' in text
    else:
        # Data may arrive on the next fragment run; absence is evidence of
        # provider availability, never evidence that this stock has no news.
        assert 'ยังไม่มีข่าวในช่วง 7 วัน' in text
    return {
        'ticker':ticker, 'chart_period':period, 'state':receipt.get_attribute('data-state'),
        'quote_refresh_seconds':60, 'news_refresh_seconds':300,
        'source_quotes':source_quotes, 'news_checked_at':checked or None,
        'source_links':source_links, 'source_link_count':len(source_links),
        'quote_and_news_clocks_preserved':True, 'same_selected_chart':True,
    }
