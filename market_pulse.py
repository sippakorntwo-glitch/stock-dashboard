"""Pure, timestamped market context; never changes ranking scores or entry policy.

The three thresholds below are transparent watch heuristics, not a calibrated
probability of making a profit. News is provider-linked reading context only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import math
import re
from urllib.parse import urlsplit

import pandas as pd

QUOTE_MAX_AGE_SECONDS = 180
BENCHMARK_MAX_SKEW_SECONDS = 120
NEWS_RECENT_SECONDS = 24 * 3600
NEWS_CHECK_MAX_AGE_SECONDS = 15 * 60
RANKING_MAX_AGE_SECONDS = 35 * 60
CHANGE_THRESHOLD_PCT = 2.0
RELATIVE_THRESHOLD_PP = 1.0
VOLUME_THRESHOLD = 1.5
SOURCE = 'Yahoo Finance'


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value):
    value = _number(value)
    return value if value is not None and value > 0 else None


def _stamp(value):
    """Require a real source timezone; never guess one for an unzoned string."""
    if value is None or isinstance(value, bool):
        return None
    try:
        stamp = (pd.Timestamp(value, unit='s', tz='UTC')
                 if isinstance(value, (float, int)) else pd.Timestamp(value))
        if pd.isna(stamp) or stamp.tzinfo is None or stamp.year < 1970:
            return None
        return stamp.tz_convert('UTC')
    except (TypeError, ValueError, OverflowError):
        return None


def _fresh(value, now, seconds):
    stamp = _stamp(value)
    return stamp is not None and now is not None and 0 <= (now-stamp).total_seconds() <= seconds


def _text(value, limit=240):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'\s+', ' ', ''.join(c for c in value if c.isprintable() or c.isspace())).strip()
    return value if len(value) <= limit else value[:limit-1].rstrip()+'…'


def _safe_url(value):
    if (not isinstance(value, str) or len(value) > 2048
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
        return ''
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        if (url.scheme != 'https' or not host or '.' not in host or url.username
                or url.password or url.port not in (None, 443) or '\\' in value
                or host.endswith(('.local', '.localhost', '.internal'))):
            return ''
        try:
            ipaddress.ip_address(host)
            return ''
        except ValueError:
            return value
    except (TypeError, ValueError):
        return ''


def normalize_quotes(raw, symbols, fetched_at):
    """Normalize one Yahoo batch response, retaining only requested exact symbols.

    Extended-session changes use that session's reported percentage (relative
    to the regular close). Regular-session changes use the previous close.
    Cumulative volume always belongs to the regular session, even when the
    displayed price is a pre/post-market observation.
    """
    fetched = _stamp(fetched_at)
    if fetched is None:
        return {}
    requested = set(symbols) if isinstance(symbols, (tuple, list, set)) else set()
    if isinstance(raw, dict):
        response = raw.get('quoteResponse')
        raw = response.get('result') if isinstance(response, dict) else None
    if not isinstance(raw, list):
        return {}
    result, duplicates = {}, set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        ticker = item.get('symbol')
        if not isinstance(ticker, str) or ticker not in requested:
            continue
        if ticker in result:
            duplicates.add(ticker)
            continue
        market_state = str(item.get('marketState') or '').upper()
        session = {'PRE':'pre', 'POST':'post'}.get(market_state, 'regular')
        prefix = {'pre':'preMarket', 'post':'postMarket', 'regular':'regularMarket'}[session]
        price, stamp = _positive(item.get(prefix+'Price')), _stamp(item.get(prefix+'Time'))
        # An absent extended-hours quote must not be relabelled as a live one.
        if price is None or stamp is None or stamp > fetched:
            continue
        previous = _positive(item.get('regularMarketPreviousClose' if session == 'regular' else 'regularMarketPrice'))
        change = _number(item.get(prefix+'ChangePercent'))
        if previous is not None:
            change = _number((price/previous-1)*100)
        volume = _number(item.get('regularMarketVolume'))
        volume = volume if volume is not None and volume >= 0 else None
        average = _positive(item.get('averageDailyVolume3Month'))
        if average is None:
            average = _positive(item.get('averageDailyVolume10Day'))
            average_basis = 'ค่าเฉลี่ยเต็มวัน 10 วัน' if average is not None else 'ไม่มีค่าเฉลี่ยปริมาณที่ยืนยันได้'
        else:
            average_basis = 'ค่าเฉลี่ยเต็มวัน 3 เดือน'
        delay = _number(item.get('exchangeDataDelayedBy'))
        result[ticker] = {
            'ticker':ticker, 'price':price, 'quote_time':stamp.isoformat(),
            'fetched_at':fetched.isoformat(), 'currency':_text(item.get('currency'), 12),
            'change_pct':change, 'previous_close':previous,
            'change_basis':'previous regular close' if session == 'regular' else 'latest regular close',
            'market_state':market_state, 'session':session, 'volume':volume,
            'average_volume':average, 'average_volume_basis':average_basis,
            'volume_session':'regular', 'delay_minutes':delay if delay is not None and delay >= 0 else None,
            'source':SOURCE,
        }
    for ticker in duplicates:
        result.pop(ticker, None)
    return result


def normalize_news(raw, ticker, fetched_at):
    """Validate feed metadata without treating provider association as sentiment."""
    fetched = _stamp(fetched_at)
    result = {'ticker':ticker, 'items':[],
              'checked_at':fetched.isoformat() if fetched is not None else None,
              'source':SOURCE, 'state':'unavailable', 'association':'provider-linked'}
    if fetched is None or not isinstance(raw, list):
        return result
    if not raw:
        result['state'] = 'empty'
        return result
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = item.get('content', item)
        if not isinstance(content, dict):
            continue
        title = _text(content.get('title'))
        provider = content.get('provider')
        publisher = _text(provider.get('displayName') if isinstance(provider, dict) else content.get('publisher'), 100)
        canonical = content.get('canonicalUrl')
        url = _safe_url(canonical.get('url') if isinstance(canonical, dict) else content.get('link'))
        stamp = _stamp(content.get('pubDate') or content.get('providerPublishTime'))
        if not title or not publisher or not url or stamp is None or stamp > fetched:
            continue
        # Legacy feeds sometimes list explicit associations. Respect them when
        # present; modern get_news responses may expose no relatedTicker field.
        related = content.get('relatedTickers', item.get('relatedTickers'))
        if isinstance(related, list) and ticker not in related:
            continue
        if url in seen:
            continue
        seen.add(url)
        result['items'].append({'title':title, 'publisher':publisher, 'url':url,
                                'published_at':stamp.isoformat()})
    result['items'].sort(key=lambda row:row['published_at'], reverse=True)
    result['items'] = result['items'][:5]
    result['state'] = 'available' if result['items'] else 'unavailable'
    return result


def _quote_valid(quote, ticker, now):
    if (not isinstance(ticker, str) or not ticker
            or not isinstance(quote, dict) or quote.get('ticker') != ticker):
        return False
    expected = {'regular':'REGULAR', 'pre':'PRE', 'post':'POST'}.get(quote.get('session'))
    delay = _number(quote.get('delay_minutes'))
    return bool(expected and quote.get('market_state') == expected
                and _positive(quote.get('price')) is not None
                and _fresh(quote.get('quote_time'), now, QUOTE_MAX_AGE_SECONDS)
                and (delay is None or 0 <= delay <= QUOTE_MAX_AGE_SECONDS/60)
                and isinstance(quote.get('currency'), str) and quote['currency'].strip())


def _news_context(news, ticker, now):
    note = 'ข่าวที่ผู้ให้ข้อมูลเชื่อมโยงกับหุ้น อาจเป็นข่าวตลาดกว้าง; ไม่ใช้หัวข้อข่าวตัดสินว่าราคาจะขึ้น'
    result = {'state':'unavailable', 'items':[], 'recent_count':0, 'checked_at':None, 'note':note}
    if not isinstance(news, dict) or news.get('ticker') != ticker:
        return result
    result['checked_at'] = news.get('checked_at')
    raw_items = news.get('items')
    if not isinstance(raw_items, list):
        return result
    for article in raw_items[:5]:
        if not isinstance(article, dict):
            continue
        stamp = _stamp(article.get('published_at'))
        if (stamp is None or now is None or stamp > now or not _safe_url(article.get('url'))
                or not _text(article.get('title')) or not _text(article.get('publisher'))):
            continue
        if _fresh(stamp, now, NEWS_RECENT_SECONDS):
            result['items'].append(dict(article))
    result['recent_count'] = len(result['items'])
    if news.get('state') == 'unavailable':
        return result
    if not _fresh(news.get('checked_at'), now, NEWS_CHECK_MAX_AGE_SECONDS):
        result['state'] = 'stale'
    else:
        result['state'] = 'available' if result['items'] else 'empty'
    return result


def assess_pulse(row, quote, market, news, now=None, snapshot_at=None):
    """Explain three watch criteria, with missing/stale inputs kept unknown."""
    now = _stamp(datetime.now(timezone.utc) if now is None else now)
    row = row if isinstance(row, dict) else {}
    ticker = row.get('ticker')
    quote = quote if isinstance(quote, dict) else {}
    market = market if isinstance(market, dict) else {}
    spy = market.get('SPY') or {}
    fresh = _quote_valid(quote, ticker, now)
    change = _number(quote.get('change_pct')) if fresh else None
    currency = quote.get('currency')
    benchmark_ok = (_quote_valid(spy, 'SPY', now) and fresh
                    and quote.get('session') == spy.get('session')
                    and currency == spy.get('currency'))
    if benchmark_ok:
        benchmark_ok = abs((_stamp(quote['quote_time'])-_stamp(spy['quote_time'])).total_seconds()) <= BENCHMARK_MAX_SKEW_SECONDS
    spy_change = _number(spy.get('change_pct')) if benchmark_ok else None
    relative = _number(change-spy_change) if change is not None and spy_change is not None else None
    volume, average = _number(quote.get('volume')), _positive(quote.get('average_volume'))
    ratio = (_number(volume/average) if fresh and quote.get('session') == 'regular'
             and quote.get('volume_session') == 'regular' and volume is not None and volume >= 0
             and average is not None else None)
    criteria = []
    def criterion(key, label, value, threshold, detail):
        # Absorb binary floating-point noise at the exact boundary, without
        # rounding a near-miss such as 1.999% into a 2% signal.
        passed = value is not None and (value >= threshold or math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12))
        criteria.append({'key':key, 'label':label, 'value':value, 'threshold':threshold,
                         'known':value is not None, 'met':passed,
                         'detail':detail})
    criterion('change', 'ราคาเพิ่มขึ้นอย่างน้อย 2%', change, CHANGE_THRESHOLD_PCT,
              'เทียบราคาปิดอ้างอิงของช่วงซื้อขายเดียวกันที่ผู้ให้ข้อมูลรายงาน')
    criterion('relative_spy', 'แข็งกว่าตลาด SPY อย่างน้อย 1 จุดเปอร์เซ็นต์', relative, RELATIVE_THRESHOLD_PP,
              'ราคาและ SPY ต้องเป็นช่วงซื้อขายเดียวกัน อายุไม่เกิน 3 นาที และเวลาห่างกันไม่เกิน 2 นาที')
    criterion('volume', 'ปริมาณวันนี้อย่างน้อย 1.5 เท่าของค่าเฉลี่ยเต็มวัน', ratio, VOLUME_THRESHOLD,
              'ใช้ปริมาณสะสมช่วงตลาดปกติเทียบค่าเฉลี่ยเต็มวัน ไม่ใช่ RVOL ณ เวลาเดียวกัน และไม่คาดการณ์ปริมาณสิ้นวัน')
    known = sum(item['known'] for item in criteria)
    met = sum(item['met'] for item in criteria)
    state = 'unknown' if known < len(criteria) else 'strong' if met == len(criteria) else 'watch'
    labels = {'strong':'แรงส่งเด่นตามเกณฑ์เฝ้าดู', 'watch':'เฝ้าดู — แรงส่งยังไม่ครบเกณฑ์',
              'unknown':'ยังประเมินแรงส่งไม่ได้ — ข้อมูลไม่ครบหรือไม่สด'}
    reasons = [item['label'] for item in criteria if item['met']]
    cautions = []
    if not fresh:
        cautions.append('รอราคาที่มีเวลาไม่เกิน 3 นาทีและสถานะช่วงซื้อขายที่ยืนยันได้; เวลาโหลดไม่ใช่เวลาราคา')
    delay = _number(quote.get('delay_minutes'))
    if delay is not None and delay > QUOTE_MAX_AGE_SECONDS/60:
        cautions.append(f'ผู้ให้ข้อมูลระบุราคาล่าช้า {delay:g} นาที จึงยังไม่ใช้ยืนยันแรงส่งสด แม้เวลา quote ดูใหม่')
    if relative is None:
        cautions.append('ยังเปรียบเทียบกับ SPY ไม่ได้: ต้องมีราคา สกุลเงิน ช่วงซื้อขาย และเวลาที่ตรงกัน')
    if ratio is None:
        cautions.append('ปริมาณซื้อขายยังประเมินไม่ได้; ไม่ใช้ปริมาณตลาดปกติมายืนยันแรงส่งช่วง pre/post-market')
    if quote.get('session') in ('pre', 'post'):
        cautions.append('เป็นราคา pre/post-market ซึ่งสภาพคล่องและสเปรดอาจต่างจากตลาดปกติ')
    if spy_change is not None and spy_change < 0:
        cautions.append('SPY ติดลบในช่วงราคาเดียวกัน แม้หุ้นแข็งกว่าตลาดก็ยังมีความเสี่ยงจากตลาดโดยรวม')
    snapshot_fresh = _fresh(snapshot_at, now, RANKING_MAX_AGE_SECONDS)
    rsi = _number(row.get('rsi'))
    if snapshot_fresh and rsi is not None and rsi >= 70:
        cautions.append('RSI รายวันจากอันดับรอบล่าสุด ≥70: ระวังไล่ราคา; ไม่ใช่ RSI สด')
    price = _positive(quote.get('price'))
    stop, target = _positive(row.get('stop')), _positive(row.get('target'))
    rr = (_number((target-price)/(price-stop)) if fresh and snapshot_fresh and currency == 'USD'
          and stop is not None and target is not None and stop < price < target else None)
    return {
        'label':labels[state], 'state':state, 'reasons':reasons, 'cautions':cautions,
        'metrics':{'price':price, 'change_pct':change, 'relative_spy_pp':relative,
                   'volume_ratio':ratio, 'volume_basis':quote.get('average_volume_basis') or 'ค่าเฉลี่ยเต็มวัน',
                   'current_rr':rr, 'quote_time':quote.get('quote_time'), 'session':quote.get('session'),
                   'currency':currency, 'met_count':met, 'known_count':known,
                   'criteria_count':len(criteria), 'criteria':criteria},
        'news_context':_news_context(news, ticker, now),
        'calculated_at':now.isoformat() if now is not None else None,
        'ranking_snapshot_at':snapshot_at,
        'note':'เกณฑ์เฝ้าดูเพิ่มเติม ไม่ใช่โอกาสกำไรเป็นเปอร์เซ็นต์ และไม่เปลี่ยนคะแนนหรือเงื่อนไขเข้าซื้อเดิม',
    }
