# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram Orchestra is a Python-based Telegram bot with an extensible, plugin-style agent architecture. The bot routes user commands to registered agents; currently only a stock price lookup agent is implemented, but the orchestrator is designed to support many agents.

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
- `ANTHROPIC_API_KEY` — Reserved for future LLM routing (unused currently)

There is no test suite yet.

## Architecture

### Request Flow

```
Telegram message → bot.py (handler) → orchestrator.py (route by command) → agent.handle(args) → reply
```

### Key Modules

- **`bot.py`** — Entry point. Registers `/start`, `/help`, and one handler per agent. Enforces `ALLOWED_CHAT_ID` filtering. In setup mode (`ALLOWED_CHAT_ID=0`), echoes the sender's chat ID for first-time config.
- **`orchestrator.py`** — Agent registry. Maps agent names to instances and dispatches calls. Designed to upgrade to LLM-based intent routing via Claude API (currently command-based).
- **`agents/base.py`** — Abstract `Agent` base class. Every agent must declare `name` (str), `description` (str), and an async `handle(args: list[str]) -> str` method.
- **`agents/stock.py`** — Stock price agent. Resolves Korean company names to KRX codes (cached on first call) and fetches prices via `finance-datareader`. Wraps the blocking DataReader call in `asyncio.to_thread`.
- **`config.py`** — Loads `.env` via `python-dotenv` and exposes `BOT_TOKEN`, `ALLOWED_CHAT_ID`, `ANTHROPIC_API_KEY`.

### Adding a New Agent

1. Create `agents/<name>.py` with a class inheriting `Agent`
2. Implement `name`, `description`, and `async handle(args)`
3. Wrap any blocking I/O with `await asyncio.to_thread(...)`
4. Register in `bot.py`: `orchestra.register(YourAgent())`

The new command (`/<name>`) is automatically wired up by `bot.py`.

## Dependencies

| Package | Purpose |
|---|---|
| `python-telegram-bot>=21.0` | Telegram Bot API (async) |
| `python-dotenv>=1.0` | `.env` loading |
| `finance-datareader>=0.9.50` | Stock prices (Yahoo Finance, KRX) |
