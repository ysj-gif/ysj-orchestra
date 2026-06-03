# StockAgent

**파일:** `agents/stock.py`  
**명령어:** `/stock <종목명 또는 코드>`  
**의존 패키지:** `FinanceDataReader`, `difflib` (표준 라이브러리)

KRX(한국거래소) 상장 종목 및 해외 주식의 현재 시세를 조회한다.  
종목명이 정확하지 않아도 4단계 퍼지 매칭으로 자동 해석한다.

---

## 클래스 속성

| 속성 | 값 |
|------|----|
| `name` | `"stock"` |
| `description` | 주식 시세 조회. 종목명 또는 티커 코드로 현재 주가를 알려준다. |
| `input_schema` | `query` 필드 1개. LLM 이 약칭·오타를 KRX 등재명 또는 해외 티커로 정규화해 전달하도록 설명이 포함되어 있다. |

---

## 인스턴스 변수

| 변수 | 타입 | 설명 |
|------|------|------|
| `_krx_map` | `dict[str, str] \| None` | KRX 전체 종목의 `종목명 → 6자리 코드` 매핑. 최초 조회 시 `_ensure_listing()` 이 로드하고 이후 재사용(캐시). `None` 이면 아직 로드 전. |

---

## 메서드

### `_ensure_listing() -> None`

```python
def _ensure_listing(self) -> None
```

`_krx_map` 이 `None` 인 경우 `fdr.StockListing("KRX")` 를 호출해 매핑을 초기화한다.  
- `Name` 컬럼을 키, `Code`(없으면 `Symbol`) 컬럼을 값으로 사용.  
- 코드는 `zfill(6)` 으로 6자리를 보장한다.  
- 네트워크 오류 등 예외 발생 시 빈 딕셔너리로 폴백 — 직접 코드/티커 입력은 계속 동작한다.

---

### `_resolve(query: str) -> str`

```python
def _resolve(self, query: str) -> str
```

사용자 입력을 FinanceDataReader 가 이해할 수 있는 심볼로 변환한다.  
`_ensure_listing()` 을 내부에서 호출하므로 별도 초기화 불필요.

**매칭 우선순위:**

| 순서 | 방법 | 예시 |
|------|------|------|
| 1 | 정확 일치 | `"삼성전자"` → `"005930"` |
| 2 | 대소문자 무시 | `"naver"` → `"NAVER"` → `"035420"` |
| 3 | 부분 문자열 포함 (가장 짧은 이름 선택) | `"삼성"` 이 포함된 종목 중 이름이 가장 짧은 것 |
| 4 | `difflib.get_close_matches` 퍼지 매칭 (cutoff=0.6) | 오타·약칭 |

KRX 맵에서 찾지 못하면 입력값 그대로 반환(해외 티커 직접 전달용).

---

### `_fetch(query: str) -> str`

```python
def _fetch(self, query: str) -> str
```

**동기(blocking) 함수.** `handle()` 에서 `asyncio.to_thread()` 를 통해 별도 스레드로 실행된다.

1. `_resolve(query)` 로 심볼 확정
2. 오늘 기준 최근 10일 범위로 `fdr.DataReader(symbol, start, end)` 호출
3. `Close` 컬럼 기준 마지막 거래일 종가 추출
4. 전일 종가와 비교해 등락폭·등락률 계산

**반환 형식 예시:**
```
📈 삼성전자  (005930)
종가: 74,000
전일대비: ▲ 1,200 (+1.65%)
기준일: 2026-06-03
```

데이터가 없거나 비어있는 경우 오류 메시지 문자열 반환.

---

### `handle(args: list[str]) -> str`

```python
async def handle(self, args: list[str]) -> str
```

`Agent` 추상 메서드 구현. 봇과 Orchestrator 양쪽에서 호출되는 공개 진입점.

| 상황 | 동작 |
|------|------|
| `args` 가 비어있음 | `"종목을 입력하세요. 예: /stock 삼성전자"` 반환 |
| 정상 입력 | `" ".join(args)` 를 query 로 `_fetch()` 를 `asyncio.to_thread()` 로 실행 |
| 예외 발생 | `"조회 중 오류가 발생했습니다: {e}"` 반환 |

---

## 사용 예시

```
/stock 삼성전자       → 005930 조회
/stock 005930         → 코드 직접 조회
/stock AAPL           → 애플 해외 주식 조회
삼성 주가 알려줘      → LLM 이 "삼성전자" 로 정규화 후 조회
네이버 얼마야?        → LLM 이 "NAVER" 로 정규화 후 조회
```

---

## 데이터 소스 교체

`_fetch()` 내부의 `fdr.DataReader(...)` 호출부만 교체하면 다른 API 로 변경 가능.  
`_ensure_listing()` / `_resolve()` 는 KRX 종목명 해석용이므로 국내 주식을 유지한다면 그대로 사용한다.
