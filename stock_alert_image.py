"""Render a precise Thai stock briefing as a single PNG, with a LINE preview.

Uses only supplied briefing facts: this module does not fetch prices or news.
Requires Pillow with libraqm and Noto Sans Thai (Ubuntu: fonts-noto-core).
Set STOCK_ALERT_FONT_DIR to a directory containing NotoSansThai-{Regular,Bold}.ttf
when the fonts aren't installed system-wide. All dollar figures are USD.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, features


WIDTH = 1600
MAX_CARDS = 5
CARD_H = 535
CARD_GAP = 20
NAVY = "#101F38"
INK = "#14253D"
MUTED = "#5A6C7D"
TEAL = "#057D70"
TEAL_LIGHT = "#E8F6F0"
AMBER = "#966109"
AMBER_LIGHT = "#FFF3D9"
RED = "#A1404A"
BG = "#F0F4F8"
LINE = "#DCE5EC"
BANGKOK = ZoneInfo("Asia/Bangkok")


def _clean(value, default="—") -> str:
    if value is None:
        return default
    # Headlines can contain arbitrary whitespace or control characters.
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "".join(c for c in text if unicodedata.category(c) != "Cc") or default


def _number(value, suffix="", digits=2) -> str:
    if isinstance(value, bool):
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    if not math.isfinite(num):
        return "—"
    return f"{num:,.{digits}f}{suffix}"


def _time(value, *, short=False) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return "ไม่ระบุเวลา"
        return dt.astimezone(BANGKOK).strftime("%H:%M น." if short else "%d/%m/%Y · %H:%M น.")
    except (TypeError, ValueError):
        return "ไม่ระบุเวลา"


def _news_date(item) -> str:
    try:
        value = str(item.get("published_at", ""))
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if item.get("date_precision") != "day" and dt.tzinfo:
            dt = dt.astimezone(BANGKOK)
        return dt.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return "ไม่ระบุวันที่"


def _font_path(filename: str, paths) -> Path:
    for root in paths:
        if root:
            candidate = Path(root) / filename
            if candidate.is_file():
                return candidate
    raise RuntimeError(f"Missing {filename}; install fonts-noto-core or set STOCK_ALERT_FONT_DIR")


class ThaiText:
    """A tiny mixed-script compositor: Noto Sans Thai doesn't contain Latin.

    Thai runs use RAQM shaping; Latin/digits use a companion sans face. Runs share
    a baseline, including when a Thai headline contains tickers or percentages.
    """

    def __init__(self, draw: ImageDraw.ImageDraw, font_dir=None):
        if not features.check_feature("raqm"):
            raise RuntimeError("Pillow must support libraqm to render Thai correctly")
        self.draw = draw
        roots = [font_dir, os.environ.get("STOCK_ALERT_FONT_DIR"),
                 "/usr/share/fonts/truetype/noto", "/usr/share/fonts/noto"]
        self.thai = {
            False: _font_path("NotoSansThai-Regular.ttf", roots),
            True: _font_path("NotoSansThai-Bold.ttf", roots),
        }
        latin_roots = roots + ["/usr/share/fonts/truetype/dejavu",
                              "/opt/codex/runtimes/codex-primary-runtime/dependencies/native/"
                              "libreoffice-headless/libreoffice/share/fonts/truetype"]
        self.latin = {}
        for bold, weight in ((False, "Regular"), (True, "Bold")):
            try:
                self.latin[bold] = _font_path(f"NotoSans-{weight}.ttf", latin_roots)
            except RuntimeError:
                name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
                self.latin[bold] = _font_path(name, latin_roots)
        self.cache = {}

    def font(self, thai: bool, size: int, bold: bool):
        key = (thai, size, bold)
        if key not in self.cache:
            path = (self.thai if thai else self.latin)[bold]
            self.cache[key] = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.RAQM)
        return self.cache[key]

    @staticmethod
    def runs(text):
        pieces = []
        for char in text:
            thai = "\u0e00" <= char <= "\u0e7f"
            if pieces and pieces[-1][0] == thai:
                pieces[-1] = (thai, pieces[-1][1] + char)
            else:
                pieces.append((thai, char))
        return pieces

    def width(self, text, size, bold=False):
        return sum(self.font(thai, size, bold).getlength(run)
                   for thai, run in self.runs(str(text)))

    def line(self, xy, text, size=25, color=INK, bold=False):
        # Coordinates are top-of-line; an explicit baseline keeps scripts aligned.
        x, y = xy
        baseline = y + size
        for thai, run in self.runs(_clean(text)):
            font = self.font(thai, size, bold)
            self.draw.text((x, baseline), run, font=font, fill=color, anchor="ls",
                           language="th" if thai else "en", direction="ltr")
            x += font.getlength(run)

    @staticmethod
    def clusters(text):
        # Never put a Thai combining vowel/tone on a new line. Leading vowels
        # are also kept with their following consonant. Prefer spaces below.
        clusters = []
        for char in text:
            if clusters and (unicodedata.category(char).startswith("M") or
                             clusters[-1][-1] in "เแโใไ"):
                clusters[-1] += char
            else:
                clusters.append(char)
        return clusters

    def fitted(self, text, width, size, bold=False):
        text = _clean(text)
        if self.width(text, size, bold) <= width:
            return text
        clusters = self.clusters(text)
        while clusters and self.width("".join(clusters) + "…", size, bold) > width:
            clusters.pop()
        return "".join(clusters).rstrip() + "…"

    def paragraph(self, xy, text, width, *, size=25, lines=2, color=INK,
                  bold=False, leading=None):
        """Draw bounded text, with visible ellipsis if the full detail is longer."""
        clusters = self.clusters(_clean(text))
        out = []
        while clusters and len(out) < lines:
            if len(out) == lines - 1:
                out.append(self.fitted("".join(clusters), width, size, bold))
                break
            line = []
            while clusters and self.width("".join(line) + clusters[0], size, bold) <= width:
                line.append(clusters.pop(0))
            if not line:
                line.append(clusters.pop(0))
            # English words and spaced Thai clauses should break at spaces.
            split = max((i for i, c in enumerate(line) if c.isspace()), default=-1)
            if clusters and split > len(line) * 0.65:
                clusters = line[split + 1:] + clusters
                line = line[:split]
            out.append("".join(line).strip())
            while clusters and clusters[0].isspace():
                clusters.pop(0)
        for i, line in enumerate(out):
            self.line((xy[0], xy[1] + i * (leading or size + 9)), line,
                      size=size, color=color, bold=bold)
        return len(out)


def _first(items, default):
    if isinstance(items, (list, tuple)) and items:
        return _clean(items[0], default)
    return default


def _card(draw, text, card, index, y):
    left, right = 56, WIDTH - 56
    draw.rounded_rectangle((left, y + 3, right, y + CARD_H + 3), radius=24, fill="#E4EAF0")
    draw.rounded_rectangle((left, y, right, y + CARD_H), radius=24, fill="white")
    ready = card.get("status") == "entry"
    accent, pale = (TEAL, TEAL_LIGHT) if ready else (AMBER, AMBER_LIGHT)
    draw.rounded_rectangle((left, y + 23, left + 6, y + 82), radius=3, fill=accent)
    x = left + 28
    ticker = _clean(card.get("ticker"), "N/A")
    text.line((x, y + 22), f"{index:02d}", 22, MUTED, True)
    text.line((x + 55, y + 14), ticker, 42, INK, True)
    ticker_end = x + 55 + text.width(ticker, 42, True) + 22
    text.paragraph((ticker_end, y + 29), card.get("name", ""), max(150, 880 - ticker_end),
                   size=23, lines=1, color=MUTED)
    score = _number(card.get("score"), digits=0)
    score_text = f"คะแนน {score}/100"
    text.line((920, y + 29), score_text, 25, INK, True)
    label = ("ผ่านเกณฑ์เข้า" if ready else "ก่อนเปิด / เข้าโซน" if card.get('status') == 'pre_candidate' else "เฝ้าดู / รอจังหวะ")
    draw.rounded_rectangle((1173, y + 21, right - 27, y + 69), radius=24, fill=pale)
    label_w = text.width(label, 24, True)
    text.line(((1173 + right - 27 - label_w) / 2, y + 29), label, 24, accent, True)

    text.paragraph((x, y + 79), card.get("situation", "รอรายละเอียดสถานการณ์ล่าสุด"),
                   right - x - 26, size=25, lines=1, color=INK)
    classification = 'หมวด ' + _clean(card.get('sector_th')) + '  |  อุตสาหกรรม ' + _clean(card.get('industry_th'))
    text.paragraph((x, y + 113), classification, right - x - 26, size=22, lines=1, color=TEAL)
    business = _clean(card.get("business"), "")
    meta = ((business + " · ") if business else "") + "ราคาบันทึก " + _time(card.get("quote_time")) + " (เวลาไทย)"
    text.paragraph((x, y + 147), meta, right - x - 26, size=20, lines=1, color=MUTED)

    # All quote-dependent numbers stay together. Unknowns are shown as dashes.
    strip_y = y + 180
    draw.rounded_rectangle((x, strip_y, right - 28, strip_y + 94), radius=15, fill="#F2F6FA")
    metrics = [
        ("Pre-market ($)" if card.get('quote_session') == 'pre' else "ราคาล่าสุด ($)" if card.get('quote_fresh') else "ราคาปกติล่าสุด ($)", _number(card.get("quote")), INK),
        ("โซนซื้อ ($)", f"{_number(card.get('zone_low'))}–{_number(card.get('zone_high'))}", INK),
        ("ตัดขาดทุน ($)", _number(card.get("stop")), RED),
        ("เป้าหมาย ($)", _number(card.get("target")), TEAL),
        ("คุ้มเสี่ยง (R/R)", _number(card.get("rr"), "x"), INK),
    ]
    widths = [250, 362, 265, 265, 232]
    mx = x
    for i, (label, value, color) in enumerate(metrics):
        if i:
            draw.line((mx, strip_y + 20, mx, strip_y + 74), fill=LINE, width=1)
        text.line((mx + 20, strip_y + 10), label, 22, MUTED)
        value_size = 31
        while text.width(value, value_size, True) > widths[i] - 32 and value_size > 20:
            value_size -= 1
        text.line((mx + 20, strip_y + 43), value, value_size, color, True)
        mx += widths[i]

    facts_y = y + 294
    col_w = 452
    first_good = _first(card.get("positive_factors"), "ยังไม่มีปัจจัยบวกที่ยืนยันได้")
    first_risk = _first(card.get("risk_factors"), _first(card.get("blockers"), "ตรวจสเปรดและจุดตัดขาดทุนก่อนเข้า"))
    news = card.get("news") if isinstance(card.get("news"), dict) else {}
    news_items = news.get("items") or []
    if news.get("state") == "available" and news_items:
        item = news_items[0]
        headline = _clean(item.get("summary_th") or ('ประเด็น: ' + str(item.get('topic', 'ข่าวบริษัท')) + ' · ' + str(item.get('context', ''))))
        publisher = _clean(item.get("publisher"), "แหล่งข่าว")
        news_label = ("บริบทเก่า " if str(item.get('age_label', '')).startswith('บริบทเก่า') else "ข่าว ") + _news_date(item) + " · " + publisher
    else:
        headline = _clean(news.get("note"), "ยังไม่มีข่าวล่าสุดที่ตรวจสอบได้")
        news_label = "ข่าวล่าสุด"
    for i, (label, value, color) in enumerate([
        ("ปัจจัยหนุน", first_good, TEAL),
        ("จุดที่ต้องระวัง", first_risk, RED),
        (news_label, headline, MUTED),
    ]):
        cx = x + i * 485
        draw.ellipse((cx, facts_y + 11, cx + 7, facts_y + 18), fill=color)
        text.paragraph((cx + 16, facts_y), label, col_w - 16, size=22, lines=1, color=color, bold=True)
        text.paragraph((cx, facts_y + 33), value, col_w, size=23, lines=2, color=INK, leading=31)

    tech = card.get('technical') or {}
    text.line((x, y + 397), 'กราฟรายวัน ณ ' + _clean(tech.get('asof')), 21, TEAL, True)
    technical_values = ('EMA20 $' + _number(tech.get('ema20')) + '  ·  EMA50 $' + _number(tech.get('ema50')) +
                        '  ·  EMA200 $' + _number(tech.get('ema200')) + '  ·  RSI14 ' + _number(tech.get('rsi14'), digits=1))
    text.paragraph((x, y + 429), technical_values, right - x - 26, size=23, lines=1, color=INK)
    text.paragraph((x, y + 461), tech.get('summary', 'รอข้อมูลกราฟรายวัน'), right - x - 26,
                   size=21, lines=1, color=MUTED)
    action_y = y + 493
    draw.rounded_rectangle((x, action_y - 5, right - 28, y + CARD_H - 15), radius=10, fill=pale)
    action_prefix = "ทำอย่างไรต่อ  "
    text.line((x + 14, action_y), action_prefix, 23, accent, True)
    offset = text.width(action_prefix, 23, True)
    text.paragraph((x + 14 + offset, action_y), card.get("next_step", "ตรวจข้อมูลในแดชบอร์ดก่อนตัดสินใจ"),
                   right - x - 58 - offset, size=23, lines=1, color=accent)


def render_briefing(briefing: dict, output_dir, *, font_dir=None, stem="stock-briefing") -> dict:
    """Return {original, preview, width, height}; paths reference PNG files.

    Accepts the schema produced by stock_alert_briefing.build_briefing. At most
    five actual cards are rendered; an empty or oversized payload is rejected.
    Files are deterministic for the same content and installed fonts.
    """
    cards = briefing.get("cards")
    if not isinstance(cards, list) or not 1 <= len(cards) <= MAX_CARDS:
        raise ValueError("A briefing image requires between one and five cards")
    if not all(isinstance(card, dict) for card in cards):
        raise ValueError("Every briefing card must be an object")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", stem):
        raise ValueError("Invalid image filename stem")
    height = 326 + len(cards) * CARD_H + (len(cards) - 1) * CARD_GAP + 176
    canvas = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    text = ThaiText(draw, font_dir=font_dir)
    draw.rectangle((0, 0, WIDTH, 266), fill=NAVY)
    draw.rounded_rectangle((56, 43, 245, 77), radius=17, fill="#214E60")
    text.line((72, 48), "STOCK BRIEFING", 18, "#B8E9E0", True)
    text.line((56, 91), f"{len(cards)} หุ้น · รู้ก่อนตัดสินใจ", 58, "white", True)
    text.line((58, 175), "ข้อมูลรอบ " + _time(briefing.get("computed_at") or briefing.get("generated_at")) + " · เวลาไทย", 25, "#D3DEE9")
    ready_count = sum(card.get("status") == "entry" for card in cards)
    status = f"ผ่านเกณฑ์เข้า {ready_count}  |  เฝ้าดู {len(cards) - ready_count}"
    if briefing.get('report_session') == 'pre':
        candidate_count = briefing.get('pre_candidate_count', 0)
        status = f"เข้าโซนก่อนเปิด {candidate_count}  |  เฝ้าดู {len(cards) - candidate_count}"
    text.line((58, 217), status, 25, "#92D9C8", True)
    market = briefing.get("market_status")
    if isinstance(market, dict):
        market = market.get("label") or market.get("status")
    market = {"open": "ตลาดสหรัฐเปิด", "closed": "ตลาดสหรัฐปิด"}.get(market, market)
    if market:
        market = text.fitted(_clean(market), 600, 25)
        text.line((WIDTH - 57 - text.width(market, 25), 217), market, 25, "#D3DEE9")
    text.line((58, 284), "อ่านสถานะก่อน · โซนซื้อ · จุดตัดขาดทุน · เป้าหมาย", 24, MUTED)

    for i, card in enumerate(cards):
        _card(draw, text, card, i + 1, 326 + i * (CARD_H + CARD_GAP))

    footer_y = height - 144
    text.line((58, footer_y), "อ่านตัวเลขให้เป็น", 25, INK, True)
    text.line((58, footer_y + 40), "โซนซื้อ = ช่วงราคาที่วางแผนเข้า  •  ตัดขาดทุน = จุดออกเมื่อแผนผิดทาง  •  เป้าหมาย = จุดพิจารณาขาย", 22, MUTED)
    text.line((58, footer_y + 75), "R/R = กำไรเป้าหมาย ÷ เงินที่เสี่ยง จากราคาล่าสุด  •  คะแนนสูงไม่ได้แปลว่าผ่านจังหวะเข้า", 22, MUTED)
    text.line((58, footer_y + 114), "STOCK DASHBOARD", 17, MUTED, True)
    text.line((1172, footer_y + 110), "รายละเอียดและแหล่งข่าวในข้อความ", 18, MUTED)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    original = output / f"{stem}.png"
    preview = output / f"{stem}-preview.png"
    canvas.save(original, optimize=True)
    small = canvas.resize((800, round(height / 2)), Image.Resampling.LANCZOS)
    small.save(preview, optimize=True)
    # LINE image limits are 10 MB original and 1 MB preview. Our text canvas is
    # much smaller, but retain a deterministic palette fallback if this changes.
    if preview.stat().st_size > 1_000_000:
        small.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(preview, optimize=True)
    if original.stat().st_size > 9_000_000 or preview.stat().st_size > 1_000_000:
        raise ValueError("Briefing image exceeds LINE image size limit")
    return {"original": str(original), "preview": str(preview),
            "original_path": str(original), "preview_path": str(preview),
            "width": WIDTH, "height": height}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("briefing", type=Path, help="Briefing JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("alert-images"))
    parser.add_argument("--font-dir", type=Path)
    parser.add_argument("--stem", default="stock-briefing")
    args = parser.parse_args()
    result = render_briefing(json.loads(args.briefing.read_text(encoding="utf-8")),
                            args.output_dir, font_dir=args.font_dir, stem=args.stem)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
