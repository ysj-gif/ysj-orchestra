"""주요 뉴스 요약 에이전트.

AI·테크·경제·국제정세 RSS 피드를 병렬 수집하고
Claude API 로 오늘의 Top 10 뉴스를 선정·한국어 요약한다.
결과는 30분간 캐시해 반복 API 호출을 방지한다.
"""
import asyncio
import datetime
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
import anthropic

import config
import usage_tracker
from agents.base import Agent

# ─── 피드 정의 ───────────────────────────────────────────────────────────────
# (소스명, URL, 카테고리)  — 순서가 우선순위 힌트가 됨
_FEEDS: list[tuple[str, str, str]] = [
    ("TechCrunch",    "https://techcrunch.com/feed/",                                  "AI/테크"),
    ("VentureBeat",   "https://venturebeat.com/feed/",                                 "AI/테크"),
    ("Ars Technica",  "https://feeds.arstechnica.com/arstechnica/index",               "AI/테크"),
    ("The Verge",     "https://www.theverge.com/rss/index.xml",                        "AI/테크"),
    ("NYT Tech",      "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",   "AI/테크"),
    ("NYT Business",  "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",     "경제"),
    ("NYT World",     "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",        "국제"),
    ("BBC World",     "https://feeds.bbci.co.uk/news/world/rss.xml",                   "국제"),
    ("Yonhap (EN)",   "https://en.yna.co.kr/RSS/news.xml",                             "국내/아시아"),
]

_HEADERS = {"User-Agent": "Mozilla/5.0 TelebotNewsBot/1.0"}
_MAX_PER_FEED = 6        # 피드당 최대 기사 수
_CACHE_TTL    = 1800     # 30분 (초)

_SYSTEM = """\
당신은 전문 뉴스 에디터입니다.
제공된 뉴스 기사 목록에서 오늘 가장 중요하고 이슈가 되는 기사 10개를 선정하고
각각을 한국어로 요약해 주세요.

[선정 우선순위]
1순위: AI·LLM·생성형 AI·반도체 관련
2순위: 빅테크·스타트업·사이버보안
3순위: 글로벌 경제·금융시장·주식·가상자산
4순위: 국제 정세·외교·분쟁·지정학
5순위: 그 외 주목할 사건·사고

[응답 형식 — 정확히 따를 것, 마크다운 없이]
📰 {오늘 날짜} 주요 뉴스 Top 10

1. [카테고리] 제목
출처: 소스명
▶ 핵심 내용을 2~3문장으로 한국어 요약.

(2~10번 동일 형식)

---
마지막 줄: 수집 피드 수와 분석 기사 수 간단히 표기.
예) 📡 9개 피드 / 42개 기사 분석
"""


@dataclass
class _Article:
    title:  str
    source: str
    cat:    str
    desc:   str


# ─── 캐시 ────────────────────────────────────────────────────────────────────
_cache: dict = {"ts": 0.0, "date": "", "text": ""}


def _cached() -> str | None:
    today = datetime.date.today().isoformat()
    if _cache["date"] == today and (time.monotonic() - _cache["ts"]) < _CACHE_TTL:
        return _cache["text"]
    return None


def _set_cache(text: str) -> None:
    _cache["ts"]   = time.monotonic()
    _cache["date"] = datetime.date.today().isoformat()
    _cache["text"] = text


# ─── RSS 파싱 ────────────────────────────────────────────────────────────────
_HTML_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _HTML_RE.sub("", s).strip()


def _parse_feed(content: str, source: str, cat: str) -> list[_Article]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    # RSS 2.0: <item>, Atom: <entry>
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    articles: list[_Article] = []
    for item in items[:_MAX_PER_FEED]:
        title = (
            item.findtext("title")
            or item.findtext("{http://www.w3.org/2005/Atom}title")
            or ""
        ).strip()
        desc = (
            item.findtext("description")
            or item.findtext("{http://www.w3.org/2005/Atom}summary")
            or ""
        )
        desc = _strip_html(desc)[:200]

        if title:
            articles.append(_Article(title=title, source=source, cat=cat, desc=desc))
    return articles


async def _fetch_one(
    client: httpx.AsyncClient, source: str, url: str, cat: str
) -> list[_Article]:
    try:
        r = await client.get(url, timeout=10)
        r.raise_for_status()
        return _parse_feed(r.text, source, cat)
    except Exception:
        return []


async def _fetch_all() -> list[_Article]:
    async with httpx.AsyncClient(
        headers=_HEADERS, follow_redirects=True
    ) as client:
        results = await asyncio.gather(
            *[_fetch_one(client, src, url, cat) for src, url, cat in _FEEDS]
        )
    all_articles: list[_Article] = []
    for batch in results:
        all_articles.extend(batch)
    return all_articles


# ─── 에이전트 ─────────────────────────────────────────────────────────────────
class NewsAgent(Agent):
    name = "news"
    description = (
        "오늘의 주요 뉴스 Top 10 요약. "
        "AI·테크·경제·국제정세를 우선순위로 가장 이슈가 되는 뉴스를 한국어로 요약한다."
    )
    input_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    async def handle(self, args: list[str]) -> str:
        if not config.ANTHROPIC_API_KEY:
            return "ANTHROPIC_API_KEY가 설정되지 않아 뉴스 요약을 사용할 수 없습니다."

        # 캐시 히트
        cached = _cached()
        if cached:
            return cached + "\n\n⚡ 캐시된 결과 (30분 이내)"

        # RSS 병렬 수집
        articles = await _fetch_all()
        if not articles:
            return "뉴스를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."

        # Claude 프롬프트 구성
        today = datetime.date.today().strftime("%Y년 %m월 %d일")
        lines = [f"오늘 날짜: {today}", f"수집된 기사 총 {len(articles)}개\n"]
        for i, a in enumerate(articles, 1):
            lines.append(f"{i}. [{a.cat}] {a.title}")
            lines.append(f"   출처: {a.source}")
            if a.desc:
                lines.append(f"   내용: {a.desc}")
            lines.append("")
        prompt = "\n".join(lines)

        _MODEL = "claude-sonnet-4-6"
        try:
            response = await self._get_client().messages.create(
                model=_MODEL,
                max_tokens=2048,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
            u = response.usage
            usage_tracker.record(
                model=_MODEL,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
                cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                purpose="news",
            )
            result = response.content[0].text
        except Exception as e:
            return f"뉴스 요약 중 오류가 발생했습니다: {e}"

        _set_cache(result)
        return result
