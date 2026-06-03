# Orchestrator

**파일:** `orchestrator.py`  
**의존:** `anthropic`, `config`, `agents.base.Agent`

에이전트 레지스트리와 라우팅을 담당한다.  
명령어 기반 직접 호출(`bot.py` → `agent.handle()`)과 LLM 기반 자유 텍스트 라우팅(`llm_dispatch`) 두 경로를 지원한다.

---

## 모듈 상수

### `_SYSTEM`

```python
_SYSTEM: str
```

`llm_dispatch()` 에서 Claude API 에 전달하는 시스템 프롬프트.  
LLM 에게 다음을 지시한다:
- 사용자 메시지에서 의도를 파악해 **반드시** 도구를 호출할 것
- 주식 종목명을 KRX 등재명 또는 해외 티커로 정규화할 것
- 정규화 예시 포함: `'네이버' → 'NAVER'`, `'애플' → 'AAPL'` 등

---

## 클래스: `Orchestrator`

### `__init__()`

```python
def __init__(self) -> None
```

| 내부 변수 | 타입 | 설명 |
|-----------|------|------|
| `_agents` | `dict[str, Agent]` | `에이전트명 → 인스턴스` 매핑. `register()` 로 추가된다. |
| `_client` | `anthropic.AsyncAnthropic \| None` | Claude API 클라이언트. 최초 `llm_dispatch()` 호출 시 지연 초기화된다. |

---

### `register(agent: Agent) -> None`

```python
def register(self, agent: Agent) -> None
```

에이전트를 레지스트리에 등록한다.

| 예외 조건 | 예외 |
|-----------|------|
| `agent.name` 이 빈 문자열 | `ValueError` |
| 동일 이름이 이미 등록됨 | `ValueError` |

---

### `get(name: str) -> Agent | None`

```python
def get(self, name: str) -> Agent | None
```

이름으로 에이전트 인스턴스를 조회한다. 없으면 `None` 반환.  
`llm_dispatch()` 가 tool_use 결과에서 에이전트를 찾을 때 내부적으로 사용한다.

---

### `all() -> list[Agent]`

```python
def all(self) -> list[Agent]
```

등록된 모든 에이전트 목록을 반환한다.  
`bot.py` 가 `CommandHandler` 를 동적으로 등록할 때와 `/help` 응답을 구성할 때 사용한다.

---

### `_get_client() -> anthropic.AsyncAnthropic`

```python
def _get_client(self) -> anthropic.AsyncAnthropic
```

`AsyncAnthropic` 클라이언트를 지연 생성한다.  
`config.ANTHROPIC_API_KEY` 를 사용하며, 한 번 생성된 인스턴스를 재사용한다.

---

### `_tools() -> list[dict]`

```python
def _tools(self) -> list[dict]
```

등록된 모든 에이전트를 Claude API `tools` 파라미터 형식으로 변환해 반환한다.

```python
# 반환 형식 예시
[
    {
        "name": "stock",
        "description": "주식 시세 조회...",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", ...}},
            "required": ["query"]
        }
    }
]
```

에이전트가 추가될수록 이 목록이 자동으로 늘어나므로 라우팅 코드를 수정할 필요가 없다.

---

### `llm_dispatch(text: str) -> str`

```python
async def llm_dispatch(self, text: str) -> str
```

자유 텍스트를 Claude Haiku 로 분류하고 적절한 에이전트에 위임한다.

**처리 흐름:**

```
text
 │
 ├─ ANTHROPIC_API_KEY 없음 → 오류 메시지 반환
 │
 ▼
Claude API (model: claude-haiku-4-5-20251001)
 │  system: _SYSTEM
 │  tools:  _tools()
 │  messages: [{"role": "user", "content": text}]
 │
 ├─ response에 tool_use 블록 있음
 │   ├─ block.name 으로 에이전트 조회
 │   ├─ block.input.values() → args 리스트 변환
 │   └─ agent.handle(args) 호출 후 결과 반환
 │
 ├─ tool_use 없이 텍스트 응답만 있음
 │   └─ 텍스트 그대로 반환
 │
 └─ 아무 것도 없음 → "이해하지 못했습니다..." 반환
```

| 파라미터 | 설명 |
|----------|------|
| `text` | 사용자가 보낸 자유 텍스트 메시지 |

**사용 모델:** `claude-haiku-4-5-20251001` — 빠르고 저렴한 라우팅 전용.  
**max_tokens:** `256` — 라우팅 결과만 받으면 되므로 최소값 사용.

---

## 라우팅 흐름 전체 비교

| 입력 방식 | 경로 | 에이전트 호출 방식 |
|-----------|------|--------------------|
| `/stock 삼성전자` | `bot.py` → `CommandHandler` → `make_handler(agent)` → `agent.handle(["삼성전자"])` | 직접 |
| `"삼성 주가 알려줘"` | `bot.py` → `MessageHandler` → `chat_msg()` → `llm_dispatch(text)` → Claude tool_use → `agent.handle(["삼성전자"])` | LLM 경유 |
