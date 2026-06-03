"""봇 진입점.

- 텔레그램 polling (공유기 뒤 노트북에서도 공인 IP 불필요)
- ALLOWED_CHAT_ID 가 설정돼 있으면 본인 chat_id 에서 온 메시지만 처리
- ALLOWED_CHAT_ID 가 없으면 '설정 모드': 아무 메시지나 받으면 chat_id 를 답장
"""
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from agents.stock import StockAgent
from orchestrator import Orchestrator

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")

# --- 에이전트 등록 (새 에이전트는 여기에 한 줄씩 추가) ---
orchestra = Orchestrator()
orchestra.register(StockAgent())
# orchestra.register(YoutubeAgent())
# orchestra.register(LaptopAgent())


def make_handler(agent):
    """에이전트 하나를 텔레그램 명령 핸들러로 감싸 반환한다."""
    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        reply = await agent.handle(context.args)
        await update.message.reply_text(reply)
    return _handler


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "오케스트라 에이전트가 작동 중입니다. /help 로 사용 가능한 명령을 확인하세요."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["사용 가능한 명령:", "/start — 시작", "/help — 도움말"]
    for agent in orchestra.all():
        lines.append(f"/{agent.name} — {agent.description}")
    await update.message.reply_text("\n".join(lines))


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """설정 모드: 메시지를 보낸 사람에게 chat_id 를 알려준다."""
    chat = update.effective_chat
    cid = chat.id if chat else "?"
    logger.info("당신의 chat_id = %s", cid)
    await update.message.reply_text(
        f"당신의 chat_id 는 {cid} 입니다.\n"
        f".env 의 ALLOWED_CHAT_ID 에 이 숫자를 넣고 봇을 다시 실행하세요."
    )


async def chat_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """일반 텍스트 메시지 → LLM 라우팅."""
    text = (update.message.text or "").strip()
    if not text:
        return
    reply = await orchestra.llm_dispatch(text)
    await update.message.reply_text(reply)


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """허용되지 않은 chat_id 차단(로그만)."""
    chat = update.effective_chat
    logger.warning("허용되지 않은 접근 차단: chat_id=%s", chat.id if chat else "?")


def main() -> None:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # --- 설정 모드: chat_id 를 모를 때 ---
    if config.ALLOWED_CHAT_ID == 0:
        logger.warning("=" * 56)
        logger.warning(" 설정 모드: ALLOWED_CHAT_ID 가 없습니다.")
        logger.warning(" 봇에게 아무 메시지나 보내면 chat_id 를 알려줍니다.")
        logger.warning(" 그 숫자를 .env 에 넣고 봇을 다시 실행하세요.")
        logger.warning("=" * 56)
        app.add_handler(MessageHandler(filters.ALL, whoami))
        logger.info("봇 시작 (설정 모드, polling)...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        return

    # --- 정상 모드: 본인 chat_id 만 통과 ---
    allowed = filters.Chat(chat_id=config.ALLOWED_CHAT_ID)
    app.add_handler(CommandHandler("start", start_cmd, filters=allowed))
    app.add_handler(CommandHandler("help", help_cmd, filters=allowed))
    for agent in orchestra.all():
        app.add_handler(
            CommandHandler(agent.name, make_handler(agent), filters=allowed)
        )
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, chat_msg))
    app.add_handler(MessageHandler(~allowed, reject))

    logger.info("봇 시작 (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
