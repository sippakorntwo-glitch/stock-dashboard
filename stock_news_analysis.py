"""Bounded provider evidence and conditional reading guides for one instrument.

No network, sentiment score, buy signal, or invented article summary is produced
here. Titles and short provider excerpts remain attributed source text; the Thai
topic and impact factors are explicit rule-based reading guides.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from market_pulse import NEWS_CHECK_MAX_AGE_SECONDS, SOURCE, _safe_url, _stamp

MAX_ITEMS = 10
RECENT_SECONDS = 24 * 3600
WEEK_SECONDS = 7 * RECENT_SECONDS
MAX_EXCERPT_WORDS = 25


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'iframe', 'object'}:
            self.hidden += 1
        elif not self.hidden:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'iframe', 'object'}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _plain(value, limit=240):
    if not isinstance(value, str):
        return ''
    parser = _PlainText()
    # Bound provider input before parsing, including malformed fragments.
    parser.feed(unescape(value[:12_000]))
    text = ' '.join(parser.parts)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\s+', ' ', ''.join(c for c in text if c.isprintable() or c.isspace())).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _excerpt(value):
    text = _plain(value, 600)
    words = text.split()
    if len(words) > MAX_EXCERPT_WORDS:
        return ' '.join(words[:MAX_EXCERPT_WORDS]).rstrip('…') + '…'
    return text


def _article_key(url):
    parsed = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid', 'guccounter'}]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/'),
                       urlencode(sorted(query)), ''))


def normalize_stock_news(raw, ticker, fetched_at):
    """Normalize raw yfinance news metadata and optional provider abstracts.

    A successful empty list is distinct from malformed/unavailable data. Source
    publication times never advance just because the feed was checked again.
    """
    fetched = _stamp(fetched_at)
    result = {'ticker':ticker, 'items':[],
              'checked_at':fetched.isoformat() if fetched is not None else None,
              'source':SOURCE, 'state':'unavailable', 'association':'provider-linked'}
    if fetched is None or not isinstance(ticker, str) or not ticker or not isinstance(raw, list):
        return result
    if not raw:
        result['state'] = 'empty'
        return result
    candidates = []
    for item in raw[:100]:
        if not isinstance(item, dict) or item.get('ad'):
            continue
        content = item.get('content', item)
        if not isinstance(content, dict):
            continue
        title = _plain(content.get('title'))
        provider = content.get('provider')
        publisher = _plain(provider.get('displayName') if isinstance(provider, dict)
                           else content.get('publisher'), 100)
        canonical = content.get('canonicalUrl')
        clickthrough = content.get('clickThroughUrl')
        url = (_safe_url(canonical.get('url')) if isinstance(canonical, dict) else '')
        url = url or _safe_url(content.get('link') or content.get('url'))
        url = url or (_safe_url(clickthrough.get('url')) if isinstance(clickthrough, dict) else '')
        published = _stamp(content.get('pubDate') or content.get('providerPublishTime') or content.get('published_at'))
        if not title or not publisher or not url or published is None or published > fetched:
            continue
        related = content.get('relatedTickers', item.get('relatedTickers'))
        if isinstance(related, list) and ticker not in related:
            continue
        excerpt = (_excerpt(content.get('summary')) or _excerpt(content.get('description'))
                   or _excerpt(content.get('source_excerpt')))
        candidates.append({
            'title':title, 'publisher':publisher, 'url':url, 'published_at':published.isoformat(),
            'source_excerpt':excerpt, 'body_state':'provider_excerpt' if excerpt else 'missing',
            'excerpt_label':'ข้อความย่อจากผู้ให้ข้อมูล (ตัดทอน)' if excerpt else 'ต้นทางไม่ได้ส่งเนื้อหาหรือบทคัดย่อ',
            'association':('explicit-related-ticker' if isinstance(related, list)
                           or content.get('association') == 'explicit-related-ticker' else 'provider-linked'),
        })
    candidates.sort(key=lambda value:value['published_at'], reverse=True)
    seen_urls, seen_titles = set(), set()
    for article in candidates:
        url_key = _article_key(article['url'])
        title_key = (article['publisher'].casefold(), article['title'].casefold())
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        result['items'].append(article)
        if len(result['items']) >= MAX_ITEMS:
            break
    result['state'] = 'available' if result['items'] else 'unavailable'
    return result


_OPINION = re.compile(
    r"\b(?:should (?:you|investors|i|we)|is (?:it|[a-z0-9 .&'-]+) (?:still )?(?:a (?:(?:good|smart) )?buy|worth buying)|"
    r"best (?:\w+ ){0,3}(?:stocks?|etfs?|funds?)|top \d+ |here['’]s (?:exactly )?(?:how|why)|"
    r"why .{0,90}\b(?:could|may|might)|opinion\b|analysis:|what if\b)"
    r"|ควร(?:ซื้อ|ลงทุน)|น่าลงทุน|บทวิเคราะห์|ความเห็น", re.I)

_TOPICS = (
    ('earnings', 'ผลประกอบการ / ประมาณการ', r'\b(?:earnings?|revenue|profit|eps|guidance|quarterly results)\b|ผลประกอบการ|รายได้|กำไรสุทธิ'),
    ('regulation', 'กฎเกณฑ์ / คดี / การอนุมัติ', r'\b(?:regulat\w*|lawsuit|litigation|antitrust|fda|sec probe|investigation|approval|approved)\b|คดี|กฎเกณฑ์|อนุมัติ'),
    ('deal', 'การซื้อกิจการ / ข้อตกลง', r'\b(?:acquisit\w*|acquir\w*|merger|takeover|partnership|agreement|contract)\b|ซื้อกิจการ|ควบรวม|สัญญา'),
    ('dividends', 'เงินปันผล / การจ่ายเงิน', r'\b(?:dividend\w*|distribution|payout|passive income)\b|ปันผล|จ่ายเงิน'),
    ('fund_flows', 'เงินไหลเข้าออก / โครงสร้างกองทุน', r'\b(?:inflows?|outflows?|fund flows?|rebalanc\w*|holdings?|expense ratio|fund launch)\b|เงินไหล|ปรับพอร์ต|ค่าธรรมเนียมกองทุน'),
    ('macro', 'เศรษฐกิจ / ตลาดโดยรวม', r'\b(?:inflation|federal reserve|interest rates?|rate cuts?|tariffs?|recession|oil prices?|treasury yields?|central bank)\b|เงินเฟ้อ|ดอกเบี้ย|เศรษฐกิจ|ภาษีศุลกากร'),
    ('product', 'สินค้า / บริการ / การดำเนินงาน', r'\b(?:launch\w*|product\w*|deliveries|production|factory|recall|outage)\b|สินค้า|ผลิตภัณฑ์|โรงงาน|เรียกคืน'),
    ('valuation', 'มูลค่า / ราคาเป้าหมาย', r'\b(?:valuat\w*|price target|upgrade\w*|downgrade\w*|p/e|all.time high)\b|มูลค่า|ราคาเป้าหมาย'),
)


def _reading_guide(article, is_etf):
    # A headline classifies what to investigate; it cannot establish causality
    # or whether an event beats expectations already priced into the market.
    headline = article['title']
    opinion = bool(_OPINION.search(headline))
    category, label = ('opinion', 'บทวิเคราะห์ / ความเห็น') if opinion else ('general', 'ข่าวทั่วไป / ต้องอ่านรายละเอียด')
    for key, candidate_label, pattern in _TOPICS:
        if re.search(pattern, headline, re.I):
            category, label = key, candidate_label
            break
    guides = {
        'earnings':[
            'ถ้าผลจริงและประมาณการสูงกว่าที่ตลาดคาด อาจหนุนราคา; ถ้าต่ำกว่าคาดอาจกดดัน ต้องตรวจตัวเลขและช่วงงบก่อน',
            'สำหรับ ETF ให้ตรวจว่าข่าวกล่าวถึงหุ้นที่กองทุนถือและมีน้ำหนักเท่าใด; กำไรบริษัทไม่ใช่กำไรของกองทุน' if is_etf
            else 'เทียบรายได้ กำไร กระแสเงินสด และคำชี้แจงกับงบหรือประกาศบริษัทในงวดเดียวกัน',
        ],
        'regulation':[
            'ถ้าข่าวเปลี่ยนต้นทุน ข้อจำกัด หรือสิทธิในการดำเนินงาน อาจเปลี่ยนมูลค่าได้ทั้งสองทิศทาง; ตรวจขอบเขตและวันที่มีผล',
            'ตรวจประกาศหน่วยงานหรือเอกสารคดี; หัวข้อข่าวเพียงอย่างเดียวยังไม่ยืนยันผลลัพธ์',
        ],
        'deal':[
            'ถ้าข้อตกลงเพิ่มผลประโยชน์มากกว่าต้นทุนอาจหนุนมูลค่า; ราคาเข้าซื้อ หนี้เพิ่ม หรือเงื่อนไขอนุมัติอาจกดดัน',
            'ตรวจว่าข้อตกลงเป็นข้อเสนอ ลงนามแล้ว หรือปิดธุรกรรมแล้ว และเกี่ยวข้องกับสินทรัพย์นี้โดยตรงหรือไม่',
        ],
        'dividends':[
            'ตรวจจำนวนจ่ายจริง วันขึ้นเครื่องหมาย และที่มาของเงิน; อัตราปันผลสูงเพียงอย่างเดียวไม่ยืนยันผลตอบแทนรวม',
            'สำหรับ ETF ต้องแยกเงินจ่ายต่อหน่วยของกองทุนออกจากปันผลของหุ้นในพอร์ต และตรวจเอกสารผู้จัดการกองทุน' if is_etf
            else 'ถ้าการจ่ายมีเงินสดรองรับอาจช่วยมุมมองรายได้; ถ้าจ่ายเกินความสามารถอาจเพิ่มความเสี่ยง',
        ],
        'fund_flows':[
            'ถ้าเงินไหลหรือการปรับน้ำหนักมีนัยสำคัญ อาจกระทบสภาพคล่องและการถือครอง; ไม่ได้ยืนยันทิศทางราคาด้วยตัวเอง',
            'ตรวจองค์ประกอบพอร์ต ค่าธรรมเนียม และดัชนีอ้างอิงจากผู้จัดการกองทุน' if is_etf
            else 'ตรวจขนาดกระแสเงินและน้ำหนักหุ้นที่เกี่ยวข้องก่อนเชื่อมโยงกับราคาหุ้น',
        ],
        'macro':[
            'ถ้าดอกเบี้ย เงินเฟ้อ หรือต้นทุนเปลี่ยน อาจกระทบแต่ละอุตสาหกรรมต่างกัน; ต้องดูการรับความเสี่ยงของสินทรัพย์นี้',
            'สำหรับ ETF ให้พิจารณาสัดส่วนอุตสาหกรรม ประเทศ และสินทรัพย์ในพอร์ต' if is_etf
            else 'เทียบผลต่อต้นทุน รายได้ หนี้ และค่าเงินของบริษัทกับตลาดโดยรวม',
        ],
        'product':[
            'ถ้าการเปลี่ยนแปลงเพิ่มยอดขายหรือประสิทธิภาพจริงอาจหนุนมูลค่า; หากมีต้นทุนหรือความล่าช้าอาจกดดัน',
            'ตรวจขนาดผลกระทบและหลักฐานการดำเนินงาน; การประกาศเปิดตัวไม่ใช่รายได้ที่รับรู้แล้ว',
        ],
        'valuation':[
            'ถ้าราคาเป้าหมายหรือสมมติฐานเปลี่ยน ต้องเทียบกับราคาปัจจุบันและวิธีประเมิน; เป้าหมายเป็นความเห็น ไม่ใช่ราคาที่รับประกัน',
            'สำหรับ ETF ค่า P/E ของพอร์ตและ NAV ต่างจากกำไรต่อหุ้นของบริษัทหนึ่งแห่ง' if is_etf
            else 'ตรวจสมมติฐานกำไร ตัวคูณมูลค่า และระยะเวลาของราคาเป้าหมาย',
        ],
        'opinion':[
            'ใช้บทความเป็นประเด็นให้ตรวจต่อ; คำว่า “น่าซื้อ” หรือแบบจำลองรายได้ไม่ใช่เหตุการณ์ที่ยืนยันแรงซื้อจริง',
            'เทียบสมมติฐานกับเอกสารกองทุนและข้อมูลตลาดล่าสุดก่อนใช้กับแผนลงทุน' if is_etf
            else 'เทียบสมมติฐานกับงบ ประกาศบริษัท และข้อมูลตลาดล่าสุดก่อนใช้กับแผนลงทุน',
        ],
        'general':[
            'ยังไม่มีรายละเอียดเพียงพอระบุปัจจัยหนุนหรือกดดัน ต้องอ่านต้นฉบับและตรวจว่าเกี่ยวข้องกับสินทรัพย์นี้อย่างไร',
        ],
    }
    factors = list(guides[category])
    if opinion and category != 'opinion':
        factors.append('หัวข้อมีลักษณะบทวิเคราะห์หรือคำถามเชิงลงทุน; ความเห็นผู้เขียนไม่ใช่การยืนยันผลกระทบต่อราคา')
    return {
        'category':category, 'category_label':label,
        'article_type':'opinion' if opinion else 'provider_article',
        'article_type_label':'บทวิเคราะห์ / ความเห็นจากลักษณะหัวข้อ' if opinion else 'บทความจากผู้ให้ข้อมูล',
        'topic':'ประเด็นจากหัวข้อ: ' + label,
        'analysis_basis':'จัดหมวดตามคำในหัวข้อ ไม่ใช่คำแปลหรือสรุปเนื้อหาฉบับเต็ม',
        'direction':'unassessed', 'direction_label':'ยังไม่ยืนยันทิศทางผลกระทบต่อราคา',
        'impact_factors':factors,
    }


def analyze_stock_news(feed, ticker, now=None, is_etf=False):
    """Group valid evidence by publication age without refreshing source clocks."""
    current = _stamp(datetime.now(timezone.utc) if now is None else now)
    result = {
        'ticker':ticker, 'state':'unavailable', 'recent_items':[], 'week_items':[],
        'recent_count':0, 'week_count':0, 'older_count':0, 'checked_at':None,
        'calculated_at':current.isoformat() if current is not None else None,
        'asset_type':'ETF' if is_etf else 'stock',
        'notes':[
            'ผู้ให้ข้อมูลเป็นผู้เชื่อมโยงข่าวกับหลักทรัพย์ บางเรื่องอาจเป็นข่าวตลาดกว้าง',
            'แยกเวลาเผยแพร่ข่าวออกจากเวลาตรวจฟีด; ข่าวไม่เปลี่ยนคะแนนหรือเงื่อนไขเข้าซื้อโดยอัตโนมัติ',
            'เงินจ่ายและมูลค่าของ ETF ต้องอ้างอิงข้อมูลกองทุน ไม่ใช้ตัวเลขบริษัทแทน' if is_etf
            else 'ตรวจข้อมูลบริษัทและราคาจากช่วงเวลาที่ตรงกันก่อนใช้ข่าวประกอบแผน',
        ],
    }
    if current is None or not isinstance(feed, dict) or feed.get('ticker') != ticker:
        return result
    checked = _stamp(feed.get('checked_at'))
    result['checked_at'] = checked.isoformat() if checked is not None else None
    if checked is None or checked > current or not isinstance(feed.get('items'), list):
        return result
    normalized = normalize_stock_news(feed['items'], ticker, checked)
    for article in normalized['items']:
        age = (current - _stamp(article['published_at'])).total_seconds()
        if age < 0:
            continue
        if age > WEEK_SECONDS:
            result['older_count'] += 1
            continue
        value = {**article, **_reading_guide(article, bool(is_etf)), 'age_seconds':age,
                 'age_group':'24h' if age <= RECENT_SECONDS else '7d'}
        result['recent_items' if age <= RECENT_SECONDS else 'week_items'].append(value)
    result['recent_count'], result['week_count'] = len(result['recent_items']), len(result['week_items'])
    if feed.get('state') not in {'available', 'empty'}:
        return result
    if feed['items'] and normalized['state'] == 'unavailable':
        return result
    age = (current - checked).total_seconds()
    result['state'] = ('stale' if age > NEWS_CHECK_MAX_AGE_SECONDS else
                       'available' if result['recent_count'] + result['week_count'] else 'empty')
    return result
