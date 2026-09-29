"""Current five-instrument LINE briefing, with attributed evidence and plain Thai.

News retrieval never changes the entry checklist. Factual company metrics,
provider headlines and conditional reading guides are separate fields. An
unavailable feed cannot become a statement that there is no adverse news.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from market_pulse import _number, _safe_url, _stamp, _text, normalize_news
from ranking_policy import POLICY, entry_checks, is_entry

MODEL = 'existing-100-point-pullback-v1'
RECENT_NEWS_SECONDS = 7 * 86400
CONTEXT_NEWS_SECONDS = 30 * 86400
EQUITIES = {'Stock', 'Common Stock', 'EQUITY'}
SYMBOL = re.compile(r'[A-Z0-9][A-Z0-9.\-^=_]{0,29}')
AMBIGUOUS_NAMES = {'gap', 'info'}
RSS_ENDPOINT = 'https://finance.yahoo.com/rss/headline'
MAX_RSS_BYTES = 1024 * 1024
RSS_HEADERS = {'User-Agent': 'stock-dashboard-news/1.0',
               'Accept': 'application/rss+xml, application/xml, text/xml'}


class NewsFeedError(ValueError):
    """Only fixed diagnostic codes are carried into public job metadata."""


def _valid_rss_url(url, ticker):
    if not isinstance(url, str) or any(char.isspace() for char in url) or '\\' in url:
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in ('finance.yahoo.com', 'feeds.finance.yahoo.com')
                or parsed.path not in ('/rss/headline', '/rss/2.0/headline')
                or parsed.username or parsed.password or parsed.port is not None or parsed.fragment):
            return False
        fields = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
        values = dict(fields)
        return (len(fields) == len(values) and values.get('s') == ticker
                and set(values) <= {'s', 'lang', 'region'}
                and values.get('lang', 'en-US') == 'en-US' and values.get('region', 'US') == 'US')
    except (ValueError, TypeError):
        return False


class _RSSCanonicalRedirect(urllib.request.HTTPRedirectHandler):
    """One public canonical RSS hop, retaining the original ten-second budget."""
    def __init__(self, ticker, deadline=None):
        super().__init__()
        self.ticker, self.count = ticker, 0
        self.deadline = time.monotonic() + 10 if deadline is None else deadline

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.count or not _valid_rss_url(newurl, self.ticker):
            raise NewsFeedError('rss_redirect_rejected')
        if time.monotonic() >= self.deadline:
            raise TimeoutError('RSS deadline reached')
        self.count += 1
        return urllib.request.Request(newurl, headers=RSS_HEADERS)

    def http_error_302(self, req, fp, code, msg, headers):
        location = headers.get('Location') or headers.get('URI')
        try:
            if not isinstance(location, str):
                raise NewsFeedError('rss_redirect_rejected')
            newurl = urllib.parse.urljoin(req.full_url, location)
            new = self.redirect_request(req, fp, code, msg, headers, newurl)
        finally:
            # Do not consume an unbounded redirect response body.
            fp.close()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('RSS deadline reached')
        return self.parent.open(new, timeout=remaining)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _http_status(exc):
    response = getattr(exc, 'response', None)
    value = getattr(exc, 'code', None) or getattr(response, 'status_code', None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _blocked_news_access(exc):
    if _http_status(exc) in {401, 403, 407, 429}:
        return True
    # Inspect for an explicit denial, but never return/log the error text.
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()[:2000]
    return ('ratelimit' in name or any(word in message for word in
            ('captcha', 'access denied', 'accessdenied', 'unauthorized', 'forbidden',
             'too many requests', 'rate limit', 'bot detection', 'bot blocked')))


def _safe_news_error(exc):
    status = _http_status(exc)
    if status is not None and 100 <= status <= 599:
        return f'HTTP_{status}'
    if _blocked_news_access(exc):
        return 'access_or_rate_blocked'
    if isinstance(exc, NewsFeedError):
        allowed = {'invalid_rss_xml', 'invalid_rss_envelope', 'rss_too_large',
                   'rss_unsafe_xml', 'invalid_news_list', 'invalid_rss_date',
                   'invalid_rss_response', 'no_valid_rss_items', 'rss_redirect_rejected'}
        return str(exc) if str(exc) in allowed else 'invalid_feed'
    # Class names are allowlisted; provider responses and their exception text
    # can contain request parameters and never belong in public diagnostics.
    name = type(exc).__name__
    return name if name in {'TimeoutError', 'ConnectionError', 'URLError', 'HTTPError',
                            'JSONDecodeError', 'ValueError', 'TypeError', 'ImportError',
                            'ModuleNotFoundError', 'AttributeError', 'RequestException',
                            'ReadTimeout', 'ConnectTimeout', 'Timeout'} else 'provider_error'


def parse_news_rss(xml, ticker, now):
    """Parse bounded RSS metadata; a requested ticker is not identity evidence."""
    if not isinstance(ticker, str) or not SYMBOL.fullmatch(ticker):
        raise ValueError('Invalid news symbol')
    current = _stamp(now)
    if current is None:
        raise ValueError('Invalid news clock')
    if not isinstance(xml, bytes) or len(xml) > MAX_RSS_BYTES:
        raise NewsFeedError('rss_too_large')
    # No DTD or entities: feeds do not need either and cannot reference files/network.
    # Reject NUL bytes too, preventing an alternate XML encoding from hiding tokens.
    if b'\x00' in xml or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', xml, re.I):
        raise NewsFeedError('rss_unsafe_xml')
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise NewsFeedError('invalid_rss_xml') from exc
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None:
        raise NewsFeedError('invalid_rss_envelope')
    raw_items = channel.findall('item')[:20]
    result = []
    seen = set()
    for item in raw_items:
        title = _text(item.findtext('title'))
        url = _safe_url(item.findtext('link'))
        value = item.findtext('pubDate')
        try:
            published = parsedate_to_datetime(value) if isinstance(value, str) else None
        except (TypeError, ValueError, OverflowError):
            published = None
        stamp = _stamp(published)
        if not title or not url or stamp is None or stamp > current or url in seen:
            continue
        source = _text(item.findtext('source'), 100)
        publisher = source or 'Yahoo Finance RSS (ฟีดรวบรวมข่าว)'
        result.append({'title': title, 'publisher': publisher, 'link': url,
                       'providerPublishTime': stamp.isoformat(),
                       'association': 'rss-request-context', 'requestedTicker': ticker})
        seen.add(url)
    if raw_items and not result:
        raise NewsFeedError('no_valid_rss_items')
    return result


def fetch_news_rss(ticker, now):
    """Public RSS plus at most one validated canonical redirect; no credentials."""
    if not isinstance(ticker, str) or not SYMBOL.fullmatch(ticker):
        raise ValueError('Invalid news symbol')
    url = RSS_ENDPOINT + '?' + urllib.parse.urlencode({'s': ticker})
    request = urllib.request.Request(url, headers=RSS_HEADERS)
    opener = urllib.request.build_opener(_RSSCanonicalRedirect(ticker))
    with opener.open(request, timeout=10) as response:
        if response.status != 200 or not _valid_rss_url(response.geturl(), ticker):
            raise NewsFeedError('invalid_rss_response')
        length = response.headers.get('Content-Length')
        if length and length.isdigit() and int(length) > MAX_RSS_BYTES:
            raise NewsFeedError('rss_too_large')
        xml = response.read(MAX_RSS_BYTES + 1)
    return parse_news_rss(xml, ticker, now)


def fetch_alert_news(ticker, now, primary_fetcher=None, rss_fetcher=None):
    """Try RSS only after a non-denial primary failure; never bypass a block."""
    result = {'items': None, 'source': None, 'primary_error': None, 'fallback_error': None}
    try:
        if primary_fetcher is None:
            from market_pulse_service import fetch_news
            raw = fetch_news(ticker, count=10)
        else:
            raw = primary_fetcher(ticker)
        if not isinstance(raw, list):
            raise NewsFeedError('invalid_news_list')
        result.update(items=raw, source='yahoo_primary')
        return result
    except Exception as exc:
        result['primary_error'] = _safe_news_error(exc)
        if _blocked_news_access(exc):
            result['fallback_error'] = 'not_attempted_access_or_rate_blocked'
            return result
    try:
        raw = (rss_fetcher or fetch_news_rss)(ticker, now)
        if not isinstance(raw, list):
            raise NewsFeedError('invalid_news_list')
        result.update(items=raw, source='yahoo_rss')
    except Exception as exc:
        result['fallback_error'] = _safe_news_error(exc)
    return result


def _fresh(value, now, seconds):
    parsed = _stamp(value)
    return parsed is not None and 0 <= (now - parsed).total_seconds() <= seconds


def _number_or_none(value, positive=False):
    result = _number(value)
    return result if result is not None and (not positive or result > 0) else None


def _validate_payload(payload):
    if (not isinstance(payload, dict) or payload.get('schema') != 1
            or payload.get('model') != MODEL or payload.get('entry_policy') != POLICY
            or not isinstance(payload.get('items'), list) or len(payload['items']) > 10):
        raise ValueError('Unsupported ranking payload')
    seen = set()
    for row in payload['items']:
        if not isinstance(row, dict):
            raise ValueError('Invalid ranking row')
        ticker = row.get('ticker')
        score, coverage = _number(row.get('score')), _number(row.get('coverage'))
        if (not isinstance(ticker, str) or not SYMBOL.fullmatch(ticker) or ticker in seen
                or score is None or coverage is None or not 0 <= score <= coverage <= 100
                or type(row.get('qualified')) is not bool
                or type(row.get('ready_at_calculation')) is not bool):
            raise ValueError('Invalid ranking identity, score or readiness')
        seen.add(ticker)


def select_rows(payload, preferred_tickers=(), limit=5):
    """Include alert-triggering instruments, then ranked equities, then ETFs.

    Within each group the published ranking order is retained. Unknown asset
    types and duplicate/malformed identities never enter the briefing.
    """
    _validate_payload(payload)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
        raise ValueError('Briefing limit must be between one and five')
    if not isinstance(preferred_tickers, (tuple, list, set, frozenset)):
        raise ValueError('Invalid preferred instruments')
    wanted = set(preferred_tickers)
    if any(not isinstance(x, str) or not SYMBOL.fullmatch(x) for x in wanted):
        raise ValueError('Invalid preferred instruments')
    rows = [row for row in payload['items'] if row.get('asset_type') in EQUITIES | {'ETF'}]
    selected = [row for row in rows if row['ticker'] in wanted]
    selected.extend(row for row in rows if row['ticker'] not in wanted and row['asset_type'] in EQUITIES)
    selected.extend(row for row in rows if row['ticker'] not in wanted and row['asset_type'] == 'ETF')
    return selected[:limit]


def _aliases(row):
    info = row.get('info') if isinstance(row.get('info'), dict) else {}
    names = [row.get('name'), info.get('longName'), info.get('shortName')]
    aliases = []
    for name in names:
        name = _text(name, 120)
        original_name = name
        name = re.sub(r'\(The\)', '', name, flags=re.I).strip()
        name = re.sub(r'^The\s+', '', name, flags=re.I)
        name = re.sub(r'[, .]+(?:Inc(?:orporated)?|Corp(?:oration)?|Ltd|PLC|Limited|Company|Holdings?)\.?$', '', name, flags=re.I)
        name = name.strip(' ,.')
        if name.casefold() in AMBIGUOUS_NAMES:
            # A capitalized English word ("Gap Between Bond Yields") is not
            # company identification. Preserve its corporate name if supplied.
            if original_name.casefold() not in AMBIGUOUS_NAMES:
                aliases.append(original_name)
        elif len(name) >= 3:
            aliases.append(name)
    return aliases


def _company_relevance(article, raw_item, row):
    title, ticker = article['title'], row['ticker']
    # Bare one-word tickers such as GAP/INFO are English words, not proof of identity.
    if re.search(r'(?:\$|\b(?:NASDAQ|NYSE|AMEX)\s*:\s*)' + re.escape(ticker) + r'\b', title, re.I):
        return 'ระบุสัญลักษณ์หุ้นในหัวข้อ'
    if re.search(r'\(' + re.escape(ticker) + r'\)', title):
        return 'ระบุสัญลักษณ์หุ้นในหัวข้อ'
    for name in _aliases(row):
        # Short single-word names require original casing to reject e.g. a price "gap".
        flags = 0 if ' ' not in name and len(name) <= 5 else re.I
        if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', title, flags):
            return 'ระบุชื่อบริษัทในหัวข้อ'
    content = raw_item.get('content', raw_item) if isinstance(raw_item, dict) else {}
    related = content.get('relatedTickers', raw_item.get('relatedTickers')) if isinstance(content, dict) else None
    if isinstance(related, list) and related == [ticker]:
        return 'ต้นทางเชื่อมโยงข่าวกับหุ้นนี้โดยเฉพาะ'
    return ''


def _topic_guide(title):
    """A topic-specific question/conditional effect, never headline sentiment."""
    topics = [
        (r'\b(?:earnings?|revenue|profit|eps|guidance|quarterly results)\b', 'ผลประกอบการ',
         'เทียบรายได้/กำไรกับที่ตลาดคาด: สูงกว่าคาดอาจหนุนราคา ต่ำกว่าคาดอาจกดดัน'),
        (r'\b(?:lawsuit|litigation|investigation|recall|regulat\w*|fda|approval)\b', 'กฎเกณฑ์/คดี/การดำเนินงาน',
         'ตรวจผลต่อรายได้ ต้นทุน และวันที่มีผล; การเปิดสอบสวนกับผลตัดสินเป็นคนละขั้นตอน'),
        (r'\b(?:acquisit\w*|merger|acquir\w*|agreement|contract|partnership)\b', 'ข้อตกลง/การซื้อกิจการ',
         'ดูรายได้เพิ่มเทียบเงินลงทุน/หนี้ใหม่ และข้อตกลงปิดจริงแล้วหรือยัง'),
        (r'\b(?:dividend\w*|buyback|repurchase)\b', 'การคืนเงินผู้ถือหุ้น',
         'ดูจำนวนเงิน วันมีผล และเงินสดรองรับ; แผนซื้อหุ้นคืนต่างจากยอดที่ซื้อจริง'),
        (r'\b(?:price target|upgrade\w*|downgrade\w*|valuat\w*)\b', 'มุมมองมูลค่าจากบทวิเคราะห์',
         'เทียบสมมติฐานกำไรและระยะเวลาของเป้าราคา; เป็นมุมมองผู้วิเคราะห์'),
        (r'\b(?:launch\w*|product\w*|production|factory|deliveries)\b', 'สินค้า/กำลังผลิต',
         'ดูยอดขายหรือกำลังผลิตที่เกิดขึ้นจริงเทียบต้นทุนและกำหนดส่งมอบ'),
    ]
    for pattern, topic, context in topics:
        if re.search(pattern, title, re.I):
            return topic, context
    return 'ข่าวบริษัท', 'อ่านเหตุการณ์และตัวเลขในต้นฉบับเพื่อแยกผลต่อรายได้ ต้นทุน และกระแสเงินสด'


def _news_age(stamp, now):
    age = (now - stamp).total_seconds()
    return ('ข่าวใน 7 วัน' if age <= RECENT_NEWS_SECONDS else
            'บริบทเก่า ' + stamp.tz_convert('Asia/Bangkok').strftime('%d/%m/%Y'))


def _curated_articles(values, row, now):
    """Accept separately reviewed source summaries; never infer one from a title."""
    articles = []
    for value in values[:10] if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        source_date = value.get('published_at')
        day_precision = value.get('date_precision') == 'day'
        if day_precision and isinstance(source_date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', source_date):
            # Midnight is solely an age-comparison convention; display the date without an invented hour.
            source_date += 'T00:00:00+00:00'
        published, reviewed = _stamp(source_date), _stamp(value.get('reviewed_at'))
        title, publisher = _text(value.get('title')), _text(value.get('publisher'), 80)
        relevance = _text(value.get('company_relevance'), 160)
        summary = _text(value.get('summary_th'), 400)
        url = _safe_url(value.get('url'))
        if (not all((published is not None, reviewed is not None, title, publisher, relevance, summary, url))
                or not _fresh(published, now, CONTEXT_NEWS_SECONDS)
                or not _fresh(reviewed, now, 7 * 86400) or reviewed < published):
            continue
        topic, context = _topic_guide(title)
        articles.append({'title': title, 'publisher': publisher, 'url': url,
                         'published_at': published.isoformat(), 'reviewed_at': reviewed.isoformat(),
                         'date_precision': 'day' if day_precision else 'second',
                         'topic': topic, 'context': _text(value.get('context'), 240) or context,
                         'company_relevance': relevance, 'age_label': _news_age(published, now),
                         'summary_th': summary, 'positive_th': _text(value.get('positive_th'), 240),
                         'negative_th': _text(value.get('negative_th'), 240),
                         'evidence_type': 'reviewed_source', 'direction': 'source_reviewed'})
    return articles


def fetch_company_news(row, now, news_fetcher=None, verified_news=None):
    """At most a primary request plus one permitted RSS fallback per stock."""
    ticker = row['ticker']
    result = {'state': 'unavailable', 'checked_at': now.isoformat(), 'items': [],
              'feed_status': 'unavailable',
              'feed_diagnostics': {'source': None, 'primary_error': None, 'fallback_error': None},
              'source': 'Yahoo Finance + แหล่งข่าวตามลิงก์',
              'note': 'ดึงข่าวไม่ได้ จึงยังประเมินข่าวบวก/ลบของรอบนี้ไม่ได้'}
    curated = _curated_articles((verified_news or {}).get(ticker, []), row, now)
    candidates = list(curated)
    successful = False
    try:
        if news_fetcher is None:
            fetched = fetch_alert_news(ticker, now)
            raw = fetched['items']
            result['feed_diagnostics'] = {key: fetched[key] for key in ('source', 'primary_error', 'fallback_error')}
        else:
            raw = news_fetcher(ticker)
        if not isinstance(raw, list):
            raise ValueError('Invalid news feed')
        successful = not raw
        for raw_item in raw[:20]:
            # Normalize individually so irrelevant early headlines cannot hide later relevant ones.
            normalized = normalize_news([raw_item], ticker, now)
            successful = successful or normalized['state'] == 'available'
            for article in normalized['items']:
                published = _stamp(article['published_at'])
                relevance = _company_relevance(article, raw_item, row)
                if not relevance or not _fresh(published, now, CONTEXT_NEWS_SECONDS):
                    continue
                topic, context = _topic_guide(article['title'])
                candidates.append({**article, 'company_relevance': relevance,
                                   'topic': topic, 'context': context, 'age_label': _news_age(published, now),
                                   'summary_th': '', 'positive_th': '', 'negative_th': '',
                                   'evidence_type': 'provider_headline', 'direction': 'unassessed',
                                   'date_precision': 'second'})
    except Exception as exc:
        # Never include provider errors, URLs with credentials or raw response bodies in CI output.
        if not any(result['feed_diagnostics'].values()):
            result['feed_diagnostics']['primary_error'] = _safe_news_error(exc)
    result['feed_status'] = 'available' if successful else 'unavailable'
    candidates.sort(key=lambda x: (x['evidence_type'] != 'reviewed_source',
                                   -_stamp(x['published_at']).timestamp()))
    recent = [article for article in candidates if _fresh(article['published_at'], now, RECENT_NEWS_SECONDS)]
    chosen = recent or candidates
    seen = set()
    for article in chosen:
        if article['url'] not in seen:
            result['items'].append(article)
            seen.add(article['url'])
        if len(result['items']) == 2:
            break
    if result['items']:
        result['state'] = 'available'
        if not successful:
            result['note'] = 'ฟีดข่าวรอบนี้ดึงไม่ได้; แสดงข่าวที่ตรวจไว้ตามวันตรวจที่ระบุ'
        else:
            result['note'] = ('ข่าวตรงบริษัทใน 7 วัน; เวลาเป็นเวลาเผยแพร่ต้นทาง' if recent else
                              'ไม่พบข่าวตรงบริษัทใน 7 วันในข้อมูลที่อ่านได้; แสดงบริบทเก่าไม่เกิน 30 วัน')
    elif successful:
        result['state'] = 'empty'
        result['note'] = 'ฟีดรอบนี้ไม่พบข่าวตรงบริษัทใน 30 วัน ยังสรุปว่าไม่มีข่าวร้ายไม่ได้'
    return result


def _money(value):
    return '—' if value is None else f'${value:,.2f}'


def _millions(value):
    return f'{value / 1_000_000:,.1f} ล้าน'


def _fundamental_factors(row, now):
    info = row.get('info') if isinstance(row.get('info'), dict) else {}
    positive, risk = [], []
    currency = _text(info.get('financialCurrency'), 10) or 'สกุลเงินต้นทาง'
    if not _fresh(row.get('info_fetched_at'), now, 7 * 86400):
        return [], ['ข้อมูลบริษัทเกิน 7 วันหรือไม่ทราบเวลาดึง ต้องอัปเดตก่อนประเมินพื้นฐาน']
    if row['asset_type'] == 'ETF':
        category, assets = _text(info.get('category'), 60), _number(info.get('totalAssets'))
        if category and assets is not None and assets > 0:
            positive.append(f'กองทุนหมวด {category}; สินทรัพย์ {_millions(assets)} {currency}')
        else:
            risk.append('ข้อมูลหมวด/สินทรัพย์กองทุนยังไม่ครบ')
        risk.append('ผลตอบแทนขึ้นกับสินทรัพย์ในกองทุน ต้องดูสัดส่วนถือครองและค่าธรรมเนียม')
        return positive, risk
    growth, margin = _number(info.get('revenueGrowth')), _number(info.get('profitMargins'))
    ocf, fcf = _number(info.get('operatingCashflow')), _number(info.get('freeCashflow'))
    if growth is not None:
        (positive if growth >= 0 else risk).append(f'รายได้ {growth * 100:+.1f}% ตามงวดที่ผู้ให้ข้อมูลรายงาน')
    else:
        risk.append('ยังไม่ทราบการเติบโตของรายได้')
    if margin is not None:
        (positive if margin > 0 else risk).append(f'กำไรสุทธิคิดเป็น {margin * 100:.1f}% ของรายได้')
    if ocf is not None and fcf is not None and ocf > 0 and fcf > 0:
        positive.append(f'เงินสดจากธุรกิจ {_millions(ocf)}; เงินสดอิสระ {_millions(fcf)} {currency}')
    else:
        for number, label in ((ocf, 'เงินสดจากธุรกิจ'), (fcf, 'เงินสดอิสระ')):
            if number is None:
                risk.append(f'ยังไม่ทราบ{label}')
            elif number <= 0:
                risk.append(f'{label} {_millions(number)} {currency}')
    debt, cash = _number(info.get('totalDebt')), _number(info.get('totalCash'))
    if all(value is not None and value >= 0 for value in (debt, cash)) and ocf is not None and ocf > 0:
        ratio = max(0, debt - cash) / ocf
        (positive if ratio <= 5 else risk).append(f'หนี้สุทธิ/เงินสดจากธุรกิจ {ratio:.1f} เท่า (เกณฑ์ ≤5)')
    return positive[:3], risk[:3]


def _card(row, payload, now, news_fetcher, verified_news):
    info = row.get('info') if isinstance(row.get('info'), dict) else {}
    q, low, high, stop, target = (_number_or_none(row.get(key), True)
                                 for key in ('quote', 'zone_low', 'zone_high', 'stop', 'target'))
    quote_current = _fresh(row.get('quote_time'), now, 900)
    ready = quote_current and _fresh(row.get('info_fetched_at'), now, 7 * 86400) and is_entry(row, payload, now)
    plan_valid = all(x is not None for x in (q, stop, target)) and stop < q < target
    rr = (target - q) / (q - stop) if plan_valid else None
    upside = (target / q - 1) * 100 if plan_valid else None
    downside = (1 - stop / q) * 100 if plan_valid else None
    checks = entry_checks(row, now)['checks']
    blockers = [x['check'] for x in checks if not x['passed']]
    if not quote_current and 'เวลาตลาดและ quote' not in blockers:
        blockers.insert(0, 'ราคาเกิน 15 นาทีหรือเวลาไม่ถูกต้อง')
    if not ready and not blockers:
        blockers.append('รอการยืนยันพร้อมเข้าจากรอบจัดอันดับ')
    bid, ask = _number(info.get('bid')), _number(info.get('ask'))
    spread_known = bid is not None and ask is not None and 0 < bid <= ask
    simple_blockers = {
        'เวลาตลาดและ quote': ('รอราคาที่อัปเดตไม่เกิน 15 นาที' if not quote_current else 'รอช่วงซื้อขายปกติสหรัฐ'),
        'คะแนนและข้อมูล': 'รอคะแนนอย่างน้อย 80 และข้อมูลให้คะแนนครบ',
        'ราคาตรงโซนและ R:R ปัจจุบัน': 'รอราคาเข้าโซนและกำไรเป้าอย่างน้อย 2 เท่าของขาดทุนถึง Stop',
        'พื้นฐานอัปเดต': 'อัปเดตข้อมูลบริษัทให้ใหม่ไม่เกิน 7 วัน',
        'ส่วนต่าง Bid/Ask': ('รอส่วนต่างราคาฝั่งซื้อ/ขายไม่เกิน 0.5%' if spread_known else 'รอข้อมูลราคาฝั่งซื้อและขาย'),
        'กำไรต่อหุ้นย้อนหลัง': 'ตรวจให้กำไรต่อหุ้นย้อนหลังเป็นบวก',
        'อัตรากำไรสุทธิ': 'ตรวจให้ธุรกิจมีกำไรสุทธิ',
        'กระแสเงินสดจากการดำเนินงาน': 'ตรวจให้ธุรกิจสร้างเงินสดได้เป็นบวก',
        'กระแสเงินสดอิสระ': 'ตรวจให้เงินสดหลังลงทุนเป็นบวก',
        'รายได้ไม่หดตัว': 'ตรวจให้รายได้ไม่ลดลงจากงวดเทียบ',
        'ภาระหนี้สุทธิ': 'ตรวจหนี้สุทธิไม่เกิน 5 เท่าของเงินสดจากธุรกิจ',
        'ธุรกิจในขอบเขตเกณฑ์กระแสเงินสด': 'โมเดลนี้ยังไม่รองรับงบกลุ่มการเงิน/อสังหาริมทรัพย์',
        'ช่วงประกาศกำไร': 'ตรวจวันประกาศกำไร และเว้นช่วงก่อน 3 วัน/หลัง 1 วัน',
        'ข้อมูลกองทุน': 'ตรวจหมวดและสินทรัพย์กองทุนให้ครบ',
    }
    blocker_details = [simple_blockers.get(value, value) for value in blockers]
    if q is None:
        situation = 'ยังไม่มีราคาที่ใช้ได้ในรอบนี้'
    elif not quote_current:
        situation = 'ราคาเกิน 15 นาทีหรือไม่ทราบเวลา จึงยังยืนยันจังหวะปัจจุบันไม่ได้'
    elif low is not None and high is not None and low <= high:
        if q > high:
            situation = f'ราคาสูงกว่าโซนเข้า {(q / high - 1) * 100:.1f}% รอราคาย่อลงมา'
        elif q < low:
            situation = f'ราคาต่ำกว่าโซนเข้า {(1 - q / low) * 100:.1f}% รอเห็นการกลับเข้าโซน'
        else:
            situation = 'ราคาอยู่ในโซนเข้า' + (' และผ่านรายการตรวจครบ' if ready else ' แต่ยังมีเงื่อนไขค้าง')
    else:
        situation = 'ยังไม่มีโซนเข้าที่ใช้ได้ ต้องรอคำนวณแผนใหม่'
    positive, risks = _fundamental_factors(row, now)
    if rr is not None and rr < 2:
        risks.insert(0, f'R:R {rr:.2f} ต่ำกว่า 2 — ผลตอบแทนเป้าเทียบความเสี่ยงยังไม่ถึงเกณฑ์')
    if downside is not None:
        risks.append(f'ถ้าราคาถึง Stop จะห่างจากราคานี้ {downside:.1f}% ต่อหุ้น')
    next_step = ('เช็กราคาหน้าส่งคำสั่งให้อยู่ในโซน และกำหนดจำนวนหุ้นจากเงินที่ยอมเสียได้' if ready else
                 'ขั้นถัดไป: ' + '; '.join(blocker_details[:3]))
    quote_time = _stamp(row.get('quote_time'))
    news = fetch_company_news(row, now, news_fetcher, verified_news)
    is_reit = 'reit' in str(info.get('industry') or row.get('industry') or '').casefold()
    reviewed_story = next((item for item in news['items'] if item['evidence_type'] == 'reviewed_source'), {})
    return {
        'ticker': row['ticker'], 'name': _text(row.get('name'), 100) or row['ticker'],
        'asset_type': 'ETF' if row['asset_type'] == 'ETF' else ('REIT' if is_reit else 'หุ้น'),
        'business': reviewed_story.get('company_relevance') or _text(info.get('industry') or row.get('industry'), 100),
        'score': _number(row['score']), 'coverage': _number(row['coverage']),
        'status': 'entry' if ready else 'watch',
        'status_label': 'ผ่านเกณฑ์เข้าซื้อ' if ready else 'เฝ้าดู / รอเงื่อนไข',
        'quote': q, 'quote_time': quote_time.isoformat() if quote_time is not None else None,
        'quote_fresh': quote_current, 'currency': _text(info.get('currency'), 10) or 'USD',
        'zone_low': low, 'zone_high': high, 'stop': stop, 'target': target, 'rr': rr,
        'upside_pct': upside, 'downside_pct': downside, 'situation': situation,
        'positive_factors': positive, 'risk_factors': risks[:3], 'blockers': blockers,
        'blocker_details': blocker_details,
        'fundamentals_asof': row.get('info_fetched_at'),
        'fundamentals_period': info.get('mostRecentQuarter'),
        'factor_basis': 'ปัจจัยจากตัวเลขบริษัทใน Yahoo Finance; แยกจากผลวิเคราะห์ข่าว',
        'news': news, 'next_step': next_step,
    }


def build_briefing(payload, now=None, news_fetcher=None, limit=5, preferred_tickers=(), verified_news=None):
    now = _stamp(datetime.now(timezone.utc) if now is None else now)
    if now is None:
        raise ValueError('Invalid briefing clock')
    rows = select_rows(payload, preferred_tickers, limit)
    if not _fresh(payload.get('computed_at'), now, 35 * 60):
        raise ValueError('Ranking is stale or future-dated')
    local = now.tz_convert('America/New_York')
    market_window = local.weekday() < 5 and 570 <= local.hour * 60 + local.minute < 960
    cards = [_card(row, payload, now, news_fetcher, verified_news) for row in rows]
    return {
        'schema': 1, 'generated_at': now.isoformat(), 'computed_at': payload['computed_at'],
        'requested_count': limit, 'actual_count': len(cards), 'cards': cards,
        'market_status': 'ช่วงเวลาซื้อขายปกติสหรัฐ' if market_window else 'นอกช่วงเวลาซื้อขายปกติสหรัฐ',
        'entry_count': sum(card['status'] == 'entry' for card in cards),
        'selection_note': 'หุ้นที่กระตุ้นแจ้งเตือนและหุ้นอันดับถัดไป; แยกสถานะผ่านเกณฑ์กับเฝ้าดูทุกตัว',
        'glossary': [
            'กรอบราคาอิงแผนจากกราฟรายวัน; เป้าเป็นระดับอ้างอิงของแผน ไม่ได้กำหนดว่าจะถึงภายในวันนี้',
            'โซนเข้า = ช่วงราคาที่แผนรอซื้อ; ถ้าราคาเกินโซนให้รอ',
            'Stop = ราคาที่แผนใช้ตัดขาดทุน; เป้า = ราคาที่แผนใช้ทำกำไร',
            'R:R = กำไรถึงเป้า ÷ ขาดทุนถึง Stop; 2 เท่า = เสี่ยง 1 เพื่อเป้า 2',
            'จำนวนหุ้น = เงินที่ยอมเสียต่อครั้ง ÷ (ราคาซื้อ − Stop); แปลงเป็นสกุลเดียวกันก่อน',
        ],
    }


def format_briefing_text(briefing):
    """Beginner-readable text; LINE integration splits messages at card boundaries."""
    clock = _stamp(briefing['generated_at']).tz_convert('Asia/Bangkok').strftime('%d/%m/%Y %H:%M')
    lines = [f"สรุปหุ้น {briefing['actual_count']} ตัว · {clock} น. ไทย",
             f"ผ่านเกณฑ์ {briefing['entry_count']} ตัว · {briefing['market_status']}"]
    for index, card in enumerate(briefing['cards'], 1):
        quote_clock = _stamp(card['quote_time'])
        quote_clock = quote_clock.tz_convert('Asia/Bangkok').strftime('%d/%m %H:%M') if quote_clock is not None else 'ไม่ทราบเวลา'
        lines.extend(['', f"{index}. {card['ticker']} · {card['asset_type']} · {card['status_label']} · {card['score']:g}/100",
                      _text(card.get('business'), 80),
                      card['situation'],
                      f"ราคา {_money(card['quote'])} ณ {quote_clock} น. ไทย",
                      f"โซนเข้า {_money(card['zone_low'])}–{_money(card['zone_high'])}",
                      f"Stop {_money(card['stop'])} | เป้า {_money(card['target'])} | R:R " +
                      (f"{card['rr']:.2f}" if card['rr'] is not None else 'ยังคำนวณไม่ได้')])
        if card['upside_pct'] is not None:
            lines.append(f"ถึงเป้า +{card['upside_pct']:.1f}% | ถึง Stop −{card['downside_pct']:.1f}%")
        if card['positive_factors']:
            lines.append('ปัจจัยหนุนจากงบ: ' + '; '.join(card['positive_factors'][:2]))
        if card['risk_factors']:
            lines.append('จุดระวัง: ' + card['risk_factors'][0])
        for article in card['news']['items'][:1]:
            lines.extend(['ข่าว: ' + (article['summary_th'] or article['title']),
                          article['age_label'] + ' · ' + _stamp(article['published_at']).strftime('%d/%m/%Y') +
                          ' · ' + article['publisher']])
            if article.get('reviewed_at'):
                reviewed = _stamp(article['reviewed_at']).tz_convert('Asia/Bangkok').strftime('%d/%m %H:%M')
                lines.append('ตรวจข่าว ' + reviewed + ' น. ไทย')
            if card['news'].get('feed_status') == 'unavailable':
                lines.append('ฟีดข่าวรอบนี้ดึงไม่ได้ ใช้ข่าวที่ตรวจไว้')
            if article['positive_th']:
                lines.append('ด้านบวกของข่าว: ' + article['positive_th'])
            if article['negative_th']:
                lines.append('ด้านลบ/จุดติดตาม: ' + article['negative_th'])
            if not article['positive_th'] and not article['negative_th']:
                lines.append('ประเมินผลข่าว: ' + article['context'])
            lines.append(article['url'])
        if not card['news']['items']:
            lines.append('ข่าว: ' + card['news']['note'])
        lines.append(card['next_step'])
    lines.extend(['', 'อ่านแผนแบบมือใหม่', *briefing['glossary'],
                  'งบ/ตัวเลข: Yahoo Finance ตามเวลาที่ดึงในแดชบอร์ด; ข่าว: แหล่งต้นฉบับตามลิงก์'])
    return '\n'.join(lines)
