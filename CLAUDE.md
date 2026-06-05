# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram Orchestra is a Python-based Telegram bot with an extensible, plugin-style agent architecture. The bot routes user commands to registered agents and also handles free-text messages via Claude API intent routing.

## Setup and Running

```bash
# Activate virtual environment (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py
```

Configure `.env` before running:
- `TELEGRAM_BOT_TOKEN` — BotFather token (required)
- `ALLOWED_CHAT_ID` — Telegram chat ID to authorize; set to `0` to enter **setup mode** where the bot replies to any message with the sender's chat ID
- `ANTHROPIC_API_KEY` — Required for `analyze`, `news`, `baseball`, `usage` agents and free-text LLM routing

There is no test suite. To test an agent interactively without running the full bot:

```bash
# Windows — must set UTF-8 encoding to handle Korean/emoji output
PYTHONIOENCODING=utf-8 python -c "
import asyncio, sys; sys.stdout.reconfigure(encoding='utf-8')
from agents.stock import StockAgent
async def t(): print(await StockAgent().handle(['삼성전자']))
asyncio.run(t())
"
```

Token usage is persisted to `usage_log.json` (gitignored). Delete it to reset counters.

## Architecture

### Request Flow

```
Telegram message
  ├─ /command args  →  bot.py (CommandHandler)  →  agent.handle(args)  →  reply
  └─ free text      →  bot.py (MessageHandler)  →  orchestrator.llm_dispatch(text)
                                                    │  Claude picks a tool
                                                    └─ agent.handle(args)  →  reply
```

### Key Modules

- **`bot.py`** — Entry point. Registers `/start`, `/help`, and one `CommandHandler` per agent (name comes from `agent.name`). Free text is routed to `orchestrator.llm_dispatch`. In setup mode (`ALLOWED_CHAT_ID=0`), ignores all routing and echoes the sender's chat ID.
- **`orchestrator.py`** — Agent registry and LLM dispatcher. `llm_dispatch` calls Claude Haiku with all registered agents exposed as tools; Claude picks the right one and returns the `query` argument. System prompt cached with `cache_control: ephemeral`. Also imports `usage_tracker` to record every dispatch call.
- **`usage_tracker.py`** — Thread-safe module that appends every `messages.create` response to `usage_log.json`. Call `usage_tracker.record(model, input_tokens, output_tokens, cache_write, cache_read, purpose)` immediately after any Claude API call. `get_stats()` returns today/total breakdowns with USD cost estimates.
- **`agents/base.py`** — Abstract `Agent` base class: `name` (str), `description` (str), `input_schema` (JSON Schema dict for Claude tool_use), and `async handle(args: list[str]) -> str`.
- **`config.py`** — Loads `.env` and exposes `BOT_TOKEN`, `ALLOWED_CHAT_ID`, `ANTHROPIC_API_KEY`. Raises `RuntimeError` on missing token.

### Agents

| Command | Class | Model | Data Source |
|---|---|---|---|
| `/stock` | `StockAgent` | — | FinanceDataReader (KRX + Yahoo) |
| `/analyze` | `StockAnalyzeAgent` | Haiku | FinanceDataReader → Claude analysis |
| `/news` | `NewsAgent` | Sonnet | 9 RSS feeds → Claude Top 10 |
| `/baseball` | `BaseballAgent` | Sonnet | Google News RSS → Claude summary |
| `/usage` | `UsageAgent` | — | `usage_log.json` (local) |

**`StockAnalyzeAgent`** inherits `StockAgent` to reuse `_resolve()` (KRX name→code fuzzy matching) and `_ensure_listing()` (cached KRX listing). It fetches 90 days of price history, computes MA5/20/60, 52-week high/low, volume ratios, then passes the data to Claude.

**`NewsAgent`** and **`BaseballAgent`** both use a module-level `_cache` dict (date + 30-min TTL) to avoid re-calling the Anthropic API on repeated `/news` or `/baseball` commands within the same half-hour window.

**`BaseballAgent`** collects data from 4 Google News RSS queries in parallel (`asyncio.gather`) and passes all article titles to Claude Sonnet. KBO's official API requires session auth and is not accessible without a browser session.

### Adding a New Agent

1. Create `agents/<name>.py` inheriting `Agent`; implement `name`, `description`, `input_schema`, `async handle(args)`
2. If the agent calls Claude API, call `usage_tracker.record(...)` immediately after `messages.create` and add `cache_control: ephemeral` to the system prompt
3. Wrap any blocking I/O (`FinanceDataReader`, file reads) with `await asyncio.to_thread(...)`
4. Register in `bot.py`: import the class and add `orchestra.register(YourAgent())`

The `/<name>` command is automatically created. The `input_schema` dict is forwarded to Claude as a tool definition for `llm_dispatch`; keep the `query` field description precise so Claude normalizes user input correctly (see `StockAgent.input_schema` for the pattern).

## Dependencies

| Package | Purpose |
|---|---|
| `python-telegram-bot>=21.0` | Telegram Bot API (async) |
| `python-dotenv>=1.0` | `.env` loading |
| `finance-datareader>=0.9.50` | Stock prices (Yahoo Finance, KRX) |
| `anthropic>=0.40.0` | Claude API (async client, tool use, prompt caching) |
| `httpx>=0.27.0` | Async HTTP for RSS feeds and news scraping |
