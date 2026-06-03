# Agent (추상 기반 클래스)

**파일:** `agents/base.py`

모든 에이전트가 반드시 상속해야 하는 공통 인터페이스. 새 에이전트를 추가할 때는 이 클래스를 상속하고 세 가지 멤버만 구현하면 된다.

---

## 클래스 속성

| 속성 | 타입 | 설명 |
|------|------|------|
| `name` | `str` | 텔레그램 명령어 이름. `"stock"` 이면 `/stock` 으로 호출된다. `bot.py` 가 이 값으로 `CommandHandler` 를 자동 등록한다. |
| `description` | `str` | `/help` 응답에 표시될 한 줄 설명. |
| `input_schema` | `dict` | Claude API `tool_use` 에 넘길 JSON Schema. `Orchestrator.llm_dispatch()` 가 이 스키마를 Claude 에게 전달해 인자를 추출하도록 한다. 기본값은 빈 스키마(`properties: {}`)이므로, 인자가 필요한 에이전트는 반드시 오버라이드해야 한다. |

---

## 추상 메서드

### `handle(args: list[str]) -> str`

```python
@abstractmethod
async def handle(self, args: list[str]) -> str: ...
```

| 매개변수 | 설명 |
|----------|------|
| `args` | 명령어 뒤에 오는 공백 구분 인자 목록. `/stock 삼성전자` 이면 `["삼성전자"]`. LLM 라우팅 경유 시에는 `Orchestrator` 가 `tool_use` 결과에서 추출한 값을 리스트로 변환해 전달한다. |

**반환값:** 텔레그램으로 전송할 응답 문자열.

---

## 새 에이전트 추가 방법

```python
# agents/example.py
from agents.base import Agent

class ExampleAgent(Agent):
    name = "example"
    description = "예제 에이전트"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "검색어"}
        },
        "required": ["query"],
    }

    async def handle(self, args: list[str]) -> str:
        query = " ".join(args)
        return f"입력: {query}"
```

```python
# bot.py 에 한 줄 추가
from agents.example import ExampleAgent
orchestra.register(ExampleAgent())
```

이후 `/example <검색어>` 또는 자유 텍스트로 호출 가능.
