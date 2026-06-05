"""한화이글스 야구 정보 에이전트.

Google News RSS 에서 한화이글스 관련 최신 기사를 수집하고
Claude API 로 전일 경기결과·금일 라인업·1군 엔트리 변동을 정리한다.
결과는 30분간 캐시한다.
"""
import asyncio
import datetime
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import httpx
import anthropic

import config
import usage_tracker
from agents.base import Agent

# ─── RSS 쿼리 ─────────────────────────────────────────────────────────────────
# (검색어, 날짜 필터)  qdr:d = 1일, qdr:d2 = 2일
_RSS_QUERIES: list[tuple[str, str]] = [
    ("KBO 한화",              "qdr:d2"),   # 경기 결과·종합
    ("한화이글스 라인업",       "qdr:d2"),   # 선발 라인업
    ("한화이글스 1군 등록 말소", "qdr:d3"),   # 엔트리 변동 (3일 범위)
    ("한화이글스 선발투수",      "qdr:d2"),   # 선발 투수 정보
]
_BASE = "https://news.google.com/rss/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
_MAX_PER_QUERY = 15
_CACHE_TTL     = 1800  # 30분

_SYSTEM = """\
당신은 한화이글스 야구 전문 분석가입니다.
제공된 최신 뉴스 기사 제목들을 분석하여 아래 세 섹션으로 정리해 주세요.
기사 제목에서 확인되는 사실만 기술하고, 불분명한 내용은 추측하지 마세요.

[응답 형식 — 정확히 따를 것]

⚾ 한화이글스 야구 정보

━━━━━━━━━━━━━━━━━━
📅 전일 경기 결과
(경기 없으면: "경기 없음")
상대팀: [팀명]
최종 스코어: 한화 X - Y [상대팀]  (승/패/무)
선발 투수: [이름] — [이닝]이닝 [자책점]자책 / 결과(승·패·무·ND)
주요 활약: [타자 성적, 핵심 이벤트]
경기 요약: (2-3문장)

━━━━━━━━━━━━━━━━━━
📋 금일 예정 경기
(예정 경기 없으면: "경기 없음 (휴식일)")
상대팀: [팀명] | 장소: [경기장]
선발 투수: [이름] — 시즌 [승]승 [패]패 / ERA [ERA]
(알 수 없으면 "선발 미정" 표기)
선발 라인업:
  1번 [포지션] [이름]
  2번 [포지션] [이름]
  ...
(라인업 정보가 부족하면 알려진 선수만 표기 후 "일부 정보만 확인됨" 표기)

━━━━━━━━━━━━━━━━━━
📋 1군 엔트리 변동
(오늘 기준 변동 정보가 없으면 이 섹션 전체 생략)
등록: [이름] ([이유/특이사항])
말소: [이름] ([이유: 부상·전략적 교체 등])
"""


# ─── 캐시 ─────────────────────────────────────────────────────────────────────
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


# ─── RSS 파싱 ──────────────────────────────────────────────────────────────────
def _parse_rss(content: str, max_items: int) -> list[dict]:
    """RSS XML 파싱 → [{title, source, pub}] 반환."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    items = root.findall(".//item")
    result = []
    for item in items[:max_items]:
        title  = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        pub    = (item.findtext("pubDate") or "").strip()
        if title:
            result.append({"title": title, "source": source, "pub": pub[:22]})
    return result


async def _fetch_rss(
    client: httpx.AsyncClient, query: str, tbs: str
) -> list[dict]:
    enc = urllib.parse.quote(query)
    url = f"{_BASE}?q={enc}&hl=ko&gl=KR&ceid=KR:ko&tbs={tbs}"
    try:
        r = await client.get(url, timeout=10)
        r.raise_for_status()
        return _parse_rss(r.text, _MAX_PER_QUERY)
    except Exception:
        return []


async def _fetch_all_news() -> list[dict]:
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as c:
        batches = await asyncio.gather(
            *[_fetch_rss(c, q, tbs) for q, tbs in _RSS_QUERIES]
        )
    # 중복 제거 (제목 기준)
    seen: set[str] = set()
    merged: list[dict] = []
    for batch in batches:
        for item in batch:
            key = item["title"][:40]
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


# ─── 에이전트 ──────────────────────────────────────────────────────────────────
class BaseballAgent(Agent):
    name = "baseball"
    description = (
        "한화이글스 야구 정보. "
        "전일 경기 결과·금일 예정 경기 선발 라인업·투수·1군 엔트리 변동을 요약한다."
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
            return "ANTHROPIC_API_KEY가 설정되지 않아 야구 정보를 사용할 수 없습니다."

        cached = _cached()
        if cached:
            return cached + "\n\n⚡ 캐시된 결과 (30분 이내)"

        # 뉴스 수집
        articles = await _fetch_all_news()
        if not articles:
            return "야구 뉴스를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."

        # Claude 프롬프트 구성
        today    = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        prompt_lines = [
            f"오늘 날짜: {today.strftime('%Y년 %m월 %d일 (%A)')} KST",
            f"어제 날짜: {yesterday.strftime('%Y년 %m월 %d일')}",
            f"\n최근 한화이글스 관련 뉴스 기사 {len(articles)}건:\n",
        ]
        for i, a in enumerate(articles, 1):
            prompt_lines.append(f"{i}. [{a['pub']}] {a['title']}  ({a['source']})")

        prompt_lines.append(
            "\n위 기사들을 바탕으로 지정된 형식으로 정리해 주세요. "
            "오늘 아직 경기가 시작되지 않았다면 '금일 예정 경기' 섹션에 라인업을 표기하고, "
            "이미 경기가 끝났다면 그 결과를 '전일 경기 결과' 또는 '금일 경기 결과'로 표기하세요."
        )

        _MODEL = "claude-sonnet-4-6"
        try:
            response = await self._get_client().messages.create(
                model=_MODEL,
                max_tokens=1500,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
            )
            u = response.usage
            usage_tracker.record(
                model=_MODEL,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
                cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                purpose="baseball",
            )
            result = response.content[0].text
        except Exception as e:
            return f"야구 정보 요약 중 오류가 발생했습니다: {e}"

        _set_cache(result)
        return result
