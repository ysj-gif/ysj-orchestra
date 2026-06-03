# bot.py

**파일:** `bot.py`  
**실행:** `python bot.py`  
**의존:** `python-telegram-bot`, `config`, `orchestrator`, `agents.stock`

봇의 진입점. Telegram polling 루프를 시작하고, 모든 핸들러를 등록한다.

---

## 에이전트 등록

```python
orchestra = Orchestrator()
orchestra.register(StockAgent())
# orchestra.register(YoutubeAgent())   # 추후 추가 예정
# orchestra.register(LaptopAgent())    # 추후 추가 예정
```

새 에이전트는 이 블록에 `orchestra.register(...)` 한 줄만 추가하면 된다.  
`CommandHandler` 등록, `/help` 목록 반영, LLM 라우팅 도구 목록 추가가 모두 자동 처리된다.

---

## 핸들러 함수

### `make_handler(agent) -> Callable`

```python
def make_handler(agent: Agent)
```

에이전트 인스턴스를 받아 `python-telegram-bot` 의 `CommandHandler` 에 등록 가능한 async 함수를 반환하는 팩토리.  
`context.args` (명령어 뒤 인자 목록)를 `agent.handle()` 에 그대로 전달한다.

---

### `start_cmd(update, context)`

```python
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None
```

`/start` 핸들러. 봇이 동작 중임을 알리고 `/help` 안내 메시지를 반환한다.

---

### `help_cmd(update, context)`

```python
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None
```

`/help` 핸들러. `orchestra.all()` 을 순회해 등록된 에이전트의 `name` 과 `description` 으로 명령 목록을 동적으로 구성한다.

**출력 예시:**
```
사용 가능한 명령:
/start — 시작
/help — 도움말
/stock — 주식 시세 조회. 종목명 또는 티커 코드로 현재 주가를 알려준다.
```

---

### `whoami(update, context)`

```python
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None
```

**설정 모드 전용.** `ALLOWED_CHAT_ID=0` 일 때만 활성화된다.  
메시지를 보낸 사람의 `chat_id` 를 알려준다. 처음 봇을 설정할 때 본인 chat_id 를 확인하는 용도.

---

### `chat_msg(update, context)`

```python
async def chat_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None
```

명령어(`/`)가 아닌 일반 텍스트 메시지 핸들러.  
`orchestra.llm_dispatch(text)` 를 호출해 Claude 가 의도를 분류하고 적절한 에이전트로 라우팅하도록 위임한다.

---

### `reject(update, context)`

```python
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None
```

`ALLOWED_CHAT_ID` 와 다른 chat_id 에서 온 메시지를 경고 로그만 남기고 무시한다. 응답하지 않아 봇의 존재를 노출하지 않는다.

---

## `main()` 함수

봇 전체 초기화 및 실행 흐름.

### 설정 모드 (`ALLOWED_CHAT_ID == 0`)

```
MessageHandler(filters.ALL) → whoami
```

모든 메시지에 대해 `whoami` 를 실행해 `chat_id` 를 알려준다.  
`.env` 에 `ALLOWED_CHAT_ID` 를 넣고 재시작하면 정상 모드로 전환된다.

### 정상 모드

핸들러 등록 순서:

| 우선순위 | 핸들러 | 조건 |
|----------|--------|------|
| 1 | `start_cmd` | `allowed` + `/start` 명령 |
| 2 | `help_cmd` | `allowed` + `/help` 명령 |
| 3 | `make_handler(agent)` × N | `allowed` + `/<agent.name>` 명령 (에이전트 수만큼) |
| 4 | `chat_msg` | `allowed` + 일반 텍스트 (명령어 아님) |
| 5 | `reject` | `allowed` 아닌 모든 메시지 |

`allowed = filters.Chat(chat_id=config.ALLOWED_CHAT_ID)` 로 본인 chat_id 만 통과.

---

## 동작 모드 요약

```
ALLOWED_CHAT_ID=0    →  설정 모드: 아무 메시지 → chat_id 안내
ALLOWED_CHAT_ID=123  →  정상 모드: /stock, 자유문장 모두 처리
```
