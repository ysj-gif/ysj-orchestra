"""환경변수에서 설정을 읽어오는 모듈. .env 파일을 사용한다."""
import os

from dotenv import load_dotenv

load_dotenv()


def _to_int(value, default: int = 0) -> int:
    """숫자가 아니면(빈 값·플레이스홀더 등) default 를 반환한다."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID: int = _to_int(os.getenv("ALLOWED_CHAT_ID"), 0)
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "여기에_봇토큰":
    raise RuntimeError("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다 (.env 확인)")

# ALLOWED_CHAT_ID 가 0 이면 bot.py 가 '설정 모드'로 떠서 chat_id 를 알려준다.
