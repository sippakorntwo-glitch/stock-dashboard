"""Headline evidence must stay attributed, bounded, and distinct from prediction."""
from copy import deepcopy

import pandas as pd
import pytest

from stock_news_analysis import analyze_stock_news, normalize_stock_news

NOW = '2026-09-24T14:00:00Z'


def article(title='Company reports quarterly earnings', **changes):
    content = {'title':title, 'provider':{'displayName':'Example News'},
               'canonicalUrl':{'url':'https://news.example.com/story'},
               'pubDate':'2026-09-24T12:00:00Z'}
    content.update(changes)
    return {'content':content}


def analyze(raw=None, **kwargs):
    return analyze_stock_news(normalize_stock_news([article()] if raw is None else raw, 'SCHD', NOW),
                              'SCHD', now=NOW, **kwargs)


def test_optional_provider_excerpt_is_literal_bounded_and_not_an_invented_summary():
    raw = [article(summary='<p>' + ' '.join(f'word{i}' for i in range(60))
                   + '<script>secret unsafe content</script></p>')]
    before = deepcopy(raw)
    feed = normalize_stock_news(raw, 'SCHD', NOW)
    item = feed['items'][0]
    assert raw == before
    assert len(item['source_excerpt'].split()) == 25
    assert '<' not in item['source_excerpt'] and 'secret' not in item['source_excerpt']
    assert item['source_excerpt'].endswith('…')
    assert item['body_state'] == 'provider_excerpt'
    assert 'ตัดทอน' in item['excerpt_label']
    assert item['published_at'] != feed['checked_at']


def test_html_entities_hidden_elements_and_markdown_links_are_cleaned():
    raw = [article(summary='&lt;script&gt;hidden&lt;/script&gt;'
                   '<style>bad</style><p>Actual &amp; public</p>'
                   ' [source](javascript:alert) ![tracker](https://bad.example/x)')]
    item = normalize_stock_news(raw, 'SCHD', NOW)['items'][0]
    assert item['source_excerpt'] == 'Actual & public source tracker'


@pytest.mark.parametrize('summary', [None, '', {}, 123, '<script>hidden</script>'])
def test_missing_or_invalid_body_stays_missing(summary):
    value = analyze([article(summary=summary)])['recent_items'][0]
    assert value['source_excerpt'] == '' and value['body_state'] == 'missing'
    assert 'ไม่ได้ส่ง' in value['excerpt_label']
    assert value['direction'] == 'unassessed'
    assert 'ไม่ใช่' in value['analysis_basis']


def test_description_fallback_and_legacy_feed_are_supported_without_network():
    legacy = {'title':'Company announces dividend', 'publisher':'Example News',
              'link':'https://news.example.com/legacy',
              'providerPublishTime':pd.Timestamp('2026-09-24T13:00:00Z').timestamp(),
              'description':'<p>Board declared a cash distribution.</p>', 'relatedTickers':['SCHD']}
    feed = normalize_stock_news([legacy], 'SCHD', NOW)
    assert feed['state'] == 'available'
    assert feed['items'][0]['association'] == 'explicit-related-ticker'
    assert feed['items'][0]['source_excerpt'] == 'Board declared a cash distribution.'
    analyzed = analyze_stock_news(feed, 'SCHD', NOW)['recent_items'][0]
    assert analyzed['category'] == 'dividends'
    assert analyzed['association'] == 'explicit-related-ticker'


def test_canonical_url_can_fall_back_to_safe_provider_clickthrough():
    feed = normalize_stock_news([article(canonicalUrl=None,
                        clickThroughUrl={'url':'https://finance.example.com/story'})], 'SCHD', NOW)
    assert feed['items'][0]['url'] == 'https://finance.example.com/story'


@pytest.mark.parametrize('changes', [
    {'pubDate':'2026-09-24T14:00:01Z'}, {'pubDate':'2026-09-24T13:00:00'},
    {'pubDate':None}, {'provider':{}}, {'title':''}, {'relatedTickers':['OTHER']},
    {'canonicalUrl':{'url':'javascript:alert(1)'}},
    {'canonicalUrl':{'url':'http://news.example.com/story'}},
    {'canonicalUrl':{'url':'https://127.0.0.1/story'}},
    {'canonicalUrl':{'url':'https://news.internal/story'}},
    {'canonicalUrl':{'url':'https://user:secret@news.example.com/story'}},
])
def test_unverified_metadata_never_becomes_selected_stock_evidence(changes):
    assert normalize_stock_news([article(**changes)], 'SCHD', NOW)['state'] == 'unavailable'


def test_newest_duplicates_removed_with_tracking_parameters_and_same_publisher_title():
    raw = [article(pubDate='2026-09-24T10:00:00Z'),
           article('Same story new metadata', canonicalUrl={'url':'https://news.example.com/story?utm_source=x#fragment'}),
           article('Unique headline', canonicalUrl={'url':'https://news.example.com/a'}),
           article('Unique headline', canonicalUrl={'url':'https://news.example.com/b'})]
    feed = normalize_stock_news(raw, 'SCHD', NOW)
    assert len(feed['items']) == 2
    assert feed['items'][0]['title'] == 'Same story new metadata'


def test_semantic_query_ids_do_not_dedupe_unrelated_articles_and_ten_items_maximum():
    raw = [article(f'Article {i}', canonicalUrl={'url':f'https://news.example.com/story?id={i}'}) for i in range(15)]
    feed = normalize_stock_news(raw, 'SCHD', NOW)
    assert len(feed['items']) == 10
    assert len({value['url'] for value in feed['items']}) == 10


def test_empty_unavailable_and_stale_feeds_are_distinct_without_clock_relabelling():
    empty, malformed = normalize_stock_news([], 'SCHD', NOW), normalize_stock_news(None, 'SCHD', NOW)
    assert analyze_stock_news(empty, 'SCHD', NOW)['state'] == 'empty'
    assert analyze_stock_news(malformed, 'SCHD', NOW)['state'] == 'unavailable'
    feed = normalize_stock_news([article()], 'SCHD', NOW)
    before = deepcopy(feed)
    later = analyze_stock_news(feed, 'SCHD', '2026-09-24T14:15:01Z')
    assert later['state'] == 'stale'
    assert later['checked_at'] == feed['checked_at'] and feed == before
    assert later['recent_items'][0]['published_at'] == feed['items'][0]['published_at']


def test_invalid_calculation_time_future_receipt_and_wrong_ticker_are_unavailable():
    feed = normalize_stock_news([article()], 'SCHD', NOW)
    for value, ticker, current in [(feed, 'OTHER', NOW), (feed, 'SCHD', 'invalid'),
                                    (feed, 'SCHD', '2026-09-24T13:59:59Z')]:
        result = analyze_stock_news(value, ticker, current)
        assert result['state'] == 'unavailable' and not result['recent_items']


def test_exact_24hour_and_7day_age_boundaries_and_older_articles():
    stamps = ['2026-09-23T14:00:00Z', '2026-09-23T13:59:59Z',
              '2026-09-17T14:00:00Z', '2026-09-17T13:59:59Z']
    raw = [article(f'Story {i}', pubDate=stamp,
                   canonicalUrl={'url':f'https://news.example.com/story{i}'}) for i, stamp in enumerate(stamps)]
    result = analyze(raw)
    assert result['recent_count'] == 1 and result['week_count'] == 2 and result['older_count'] == 1
    assert result['recent_items'][0]['age_group'] == '24h'
    assert all(row['age_group'] == '7d' for row in result['week_items'])


@pytest.mark.parametrize('title,category', [
    ('Company reports quarterly earnings', 'earnings'),
    ('SEC probe of company operations', 'regulation'),
    ('Company announces acquisition agreement', 'deal'),
    ('Fund declares dividend distribution', 'dividends'),
    ('ETF inflows hit record', 'fund_flows'),
    ('Federal Reserve considers interest rate cuts', 'macro'),
    ('Company launches new product', 'product'),
    ('Analyst raises price target', 'valuation'),
    ('Should You Invest $1,000 in SCHD Right Now?', 'opinion'),
    ('Company meets community members', 'general'),
])
def test_topics_are_explained_without_assigning_price_direction(title, category):
    result = analyze([article(title)])['recent_items'][0]
    assert result['category'] == category
    assert result['direction'] == 'unassessed'
    assert result['impact_factors'] and result['topic'].startswith('ประเด็นจากหัวข้อ:')


@pytest.mark.parametrize('title', [
    'The Schwab U.S. Dividend Equity ETF Is Near Its All-Time High: Is It Still a Good Buy?',
    'Should You Invest $1,000 in SCHD Right Now?',
    "Here's Exactly How Much You'd Need to Invest in SCHD to Build $500 Per Month in Passive Dividend Income",
])
def test_screenshot_style_opinions_remain_opinions_not_confirmed_positive_catalysts(title):
    item = analyze([article(title, provider={'displayName':'The Motley Fool'})], is_etf=True)['recent_items'][0]
    assert item['article_type'] == 'opinion' and item['direction'] == 'unassessed'
    assert not any(key in item for key in ('buy', 'sentiment_score', 'probability', 'target_price'))


def test_publisher_alone_does_not_turn_a_report_into_an_opinion():
    item = analyze([article('Company reports revenue', provider={'displayName':'The Motley Fool'})])['recent_items'][0]
    assert item['article_type'] == 'provider_article'


def test_etf_earnings_and_distributions_use_portfolio_context_without_invented_figures():
    fund = analyze(is_etf=True)
    stock = analyze(is_etf=False)
    assert fund['asset_type'] == 'ETF' and stock['asset_type'] == 'stock'
    assert 'น้ำหนัก' in ' '.join(fund['recent_items'][0]['impact_factors'])
    assert 'งบ' in ' '.join(stock['recent_items'][0]['impact_factors'])
    dividend = analyze([article('Fund dividend distribution')], is_etf=True)
    assert 'เงินจ่ายต่อหน่วย' in ' '.join(dividend['recent_items'][0]['impact_factors'])
    assert all(value not in repr(fund) for value in ('22.89%', '3%', '9%'))


def test_hype_or_negative_headlines_cannot_promote_or_demote_entry_decisions():
    for headline in ['Stock rockets with massive gains', 'Stock crashes and could go to zero']:
        result = analyze([article(headline)])
        assert result['recent_items'][0]['direction'] == 'unassessed'
        assert not any(key in result for key in ('score', 'qualified', 'ready_at_calculation'))


def test_existing_normalized_pulse_feed_can_be_read_without_fabricating_absent_body():
    feed = {'ticker':'SCHD', 'state':'available', 'checked_at':NOW,
            'items':[{'title':'Company reports earnings', 'publisher':'Example News',
                      'url':'https://news.example.com/story', 'published_at':'2026-09-24T13:00:00Z'}]}
    item = analyze_stock_news(feed, 'SCHD', NOW)['recent_items'][0]
    assert item['body_state'] == 'missing' and item['source_excerpt'] == ''
