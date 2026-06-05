# 텔레그램 오케스트라 봇

Claude AI를 중추로 하는 개인용 텔레그램 봇입니다.
명령어 기반 에이전트와 자유 텍스트 LLM 라우팅을 결합해, 주식·뉴스·야구·API 사용량 조회를 하나의 채팅 인터페이스에서 처리합니다.

---

## 전체 구조

```
Telegram 메시지
  │
  ├─ /명령어 인자  ──────────────────────────────────────────────────────────────────┐
  │                                                                                  │
  └─ 자유 텍스트  →  Orchestrator (Claude Haiku, tool_use)  →  에이전트 선택 및 위임 ┘
                                                                       │
                                          ┌────────────────────────────┤
                                          ▼                            ▼
                                  에이전트 실행                  usage_tracker.record()
                                  (결과 문자열 반환)              (usage_log.json 누적)
                                          │
                                          ▼
                                  Telegram 답장
```

자유 텍스트를 보내면 Orchestrator가 Claude Haiku를 라우터로 사용해 어떤 에이전트를 호출할지 결정합니다.  
`/명령어`를 직접 입력하면 해당 에이전트가 즉시 실행됩니다.

---

## 에이전트 목록

### `/stock` — 주식 현재가 조회
종목명 또는 티커로 현재가와 전일 대비 등락을 조회합니다.

```
/stock 삼성전자
/stock AAPL
/stock TSLA
```

- 한글 종목명 → KRX 코드 자동 변환 (퍼지 매칭 포함)
- KRX 상장 종목 목록은 최초 조회 시 캐시
- 데이터 소스: `FinanceDataReader` (KRX, Yahoo Finance)

**출력 예시**
```
📈 삼성전자 (005930)
종가: 329,000
전일대비: ▼ 22,500 (-6.40%)
기준일: 2026-06-05
```

---

### `/analyze` — AI 주식 기술적 분석
3개월 가격 데이터를 수집하고 Claude가 5개 항목을 분석합니다.

```
/analyze 삼성전자
/analyze NVDA
"테슬라 추세 분석해줘"  → 자유 텍스트로도 호출 가능
```

**분석 항목**
1. 단기 추세 (상승/하락/횡보 및 모멘텀)
2. 이동평균선 분석 (MA5/20/60, 골든/데드크로스)
3. 52주 포지션 시사점
4. 거래량 신호
5. 종합 의견

- `StockAnalyzeAgent`는 `StockAgent`를 상속 → 종목 해석 로직 재사용
- 데이터: 90일 가격·거래량 + 52주 고/저 별도 조회
- 모델: Claude Haiku (system prompt 캐싱 적용)

---

### `/news` — 오늘의 주요 뉴스 Top 10
9개 RSS 피드를 병렬 수집하고 Claude Sonnet이 중요도 순으로 10개를 선정·한국어 요약합니다.

```
/news
"오늘 뉴스 요약해줘"  → 자유 텍스트로도 호출 가능
```

**수집 피드 및 우선순위**

| 우선순위 | 카테고리 | 출처 |
|---|---|---|
| 1 | AI / 테크 | TechCrunch, VentureBeat, Ars Technica, The Verge, NYT Tech |
| 2 | 경제 | NYT Business |
| 3 | 국제 | BBC World, NYT World |
| 4 | 국내/아시아 | Yonhap (EN) |

- 결과는 30분간 캐시 (반복 호출 시 API 재사용 없음)
- 모델: Claude Sonnet

---

### `/baseball` — 한화이글스 야구 정보
Google News RSS 4개 쿼리를 병렬 수집하고 Claude Sonnet이 구조화된 형태로 정리합니다.

```
/baseball
"한화 오늘 경기 결과?"  → 자유 텍스트로도 호출 가능
```

**제공 정보**

- **전일(또는 금일) 경기 결과**: 상대팀, 스코어, 선발 투수 성적, 주요 타자 활약, 경기 요약
- **금일 예정 경기**: 상대팀, 경기장, 선발 투수 시즌 성적, 타선 라인업 (기사에 공개된 범위)
- **1군 엔트리 변동**: 당일 등록/말소 선수 및 사유 (정보 없으면 섹션 생략)

- 결과는 30분간 캐시
- 모델: Claude Sonnet

---

### `/usage` — Anthropic API 사용량 조회
모든 Claude API 호출을 로컬 파일(`usage_log.json`)에 누적하고 통계를 보고합니다.

```
/usage
```

**제공 정보**
- 오늘 / 누적 전체: 입력·출력·캐시 쓰기/읽기 토큰 수
- 추정 비용 (USD, 공개 가격표 기반 참고치)
- 마지막 호출 시각
- 잔여 크레딧 확인 링크: `console.anthropic.com` (API 미제공)

---

## 설치 및 실행

### 사전 준비

| 항목 | 취득 방법 |
|---|---|
| Telegram Bot Token | [@BotFather](https://t.me/BotFather) → `/newbot` |
| Anthropic API Key | [console.anthropic.com](https://console.anthropic.com) |
| Python 3.11 이상 | python.org |

### 설치

```bash
# 가상환경 생성 및 활성화 (Windows)
python -m venv venv
venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 환경 설정

프로젝트 루트에 `.env` 파일을 생성합니다.

```env
TELEGRAM_BOT_TOKEN=여기에_봇토큰
ALLOWED_CHAT_ID=0
ANTHROPIC_API_KEY=여기에_anthropic_키
```

`ALLOWED_CHAT_ID=0`으로 설정하면 **설정 모드**로 실행됩니다.  
봇에게 아무 메시지나 보내면 자신의 chat_id를 알려주므로, 그 숫자를 다시 입력합니다.

```env
ALLOWED_CHAT_ID=123456789   # 본인 chat_id로 교체
```

### 실행

```bash
python bot.py
```

---

## 파일 구조

```
telegram_orchestra/
├── bot.py               # 진입점 — 에이전트 등록, 핸들러 연결
├── orchestrator.py      # 에이전트 레지스트리 + LLM 자유 텍스트 라우팅
├── usage_tracker.py     # API 토큰 사용량 기록 (usage_log.json)
├── config.py            # .env 로드
├── requirements.txt
├── agents/
│   ├── base.py          # Agent 추상 베이스 클래스
│   ├── stock.py         # /stock  — 주식 현재가
│   ├── stock_analyze.py # /analyze — AI 기술적 분석
│   ├── news.py          # /news   — 뉴스 Top 10
│   ├── baseball.py      # /baseball — 한화이글스
│   └── usage.py         # /usage  — API 사용량
└── usage_log.json       # 자동 생성 — API 호출 누적 기록
```

---

## 새 에이전트 추가

1. `agents/<이름>.py` 생성, `Agent` 클래스 상속

```python
from agents.base import Agent

class MyAgent(Agent):
    name = "myagent"           # /myagent 명령어로 자동 등록
    description = "한 줄 설명"  # /help 및 LLM 라우팅에 노출
    input_schema = {           # Claude tool_use 스키마
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "..."}
        },
        "required": ["query"],
    }

    async def handle(self, args: list[str]) -> str:
        query = " ".join(str(a) for a in args).strip()
        # 블로킹 I/O는 반드시 asyncio.to_thread 사용
        return "결과 문자열"
```

2. Claude API를 호출하는 경우 `usage_tracker.record(...)` 추가

```python
import usage_tracker
# messages.create 직후
u = response.usage
usage_tracker.record(
    model=_MODEL,
    input_tokens=u.input_tokens,
    output_tokens=u.output_tokens,
    cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
    cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
    purpose="myagent",
)
```

3. `bot.py`에 한 줄 추가

```python
from agents.myagent import MyAgent
orchestra.register(MyAgent())
```

---

## 자유 텍스트 라우팅 동작 방식

명령어 없이 일반 메시지를 보내면 Orchestrator가 Claude Haiku를 **라우터**로 사용합니다.  
등록된 모든 에이전트의 `name`, `description`, `input_schema`가 Claude의 tool 목록으로 전달되고,  
Claude가 의도에 맞는 tool을 선택해 호출하면 해당 에이전트가 실행됩니다.

```
사용자: "삼성전자 분석해줘"
  → Claude가 analyze 도구 선택, query="삼성전자" 전달
  → StockAnalyzeAgent.handle(["삼성전자"]) 실행
  → AI 기술적 분석 결과 반환
```

```
사용자: "애플 주가 얼마야?"
  → Claude가 stock 도구 선택, query="AAPL" 정규화하여 전달
  → StockAgent.handle(["AAPL"]) 실행
  → 현재가 반환
```

---

## 의존성

| 패키지 | 버전 | 용도 |
|---|---|---|
| `python-telegram-bot` | ≥21.0 | Telegram Bot API (비동기) |
| `anthropic` | ≥0.40.0 | Claude API (tool_use, 프롬프트 캐싱) |
| `finance-datareader` | ≥0.9.50 | 주가 데이터 (KRX, Yahoo Finance) |
| `httpx` | ≥0.27.0 | RSS 피드 비동기 수집 |
| `python-dotenv` | ≥1.0 | `.env` 로드 |
