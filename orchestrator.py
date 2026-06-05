"""명령어 -> 에이전트 라우팅 + 에이전트 레지스트리.

- command_dispatch : /stock 처럼 명령어가 명확할 때 직접 에이전트 호출
- llm_dispatch     : 자유 텍스트 입력을 Claude로 의도 분류해 에이전트 호출
"""
import anthropic

import config
import usage_tracker
from agents.base import Agent

_SYSTEM = (
    "당신은 텔레그램 봇의 라우터입니다. "
    "사용자 메시지에서 의도를 파악해 적절한 도구를 반드시 호출하세요.\n\n"
    "도구 선택 기준:\n"
    "- stock: 단순 현재가·시세 조회 ('얼마야?', '주가 알려줘' 등)\n"
    "- analyze: 분석·전망·추세·이평선·거래량 등 심층 정보 요청 ('분석해줘', '전망이 어때?', '추세 좀 봐줘' 등)\n\n"
    "종목명 정규화:\n"
    "KRX 한글 예: '삼성' → '삼성전자', '현대' → '현대차', '카카오뱅크'.\n"
    "KRX 영문 예: '네이버' → 'NAVER', '카카오' → 'KAKAO', 'SK하이닉스'.\n"
    "해외 티커 예: '애플' → 'AAPL', '테슬라' → 'TSLA', '엔비디아' → 'NVDA'."
)


class Orchestrator:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._client: anthropic.AsyncAnthropic | None = None

    def register(self, agent: Agent) -> None:
        if not agent.name:
            raise ValueError("에이전트에 name이 없습니다")
        if agent.name in self._agents:
            raise ValueError(f"이미 등록된 에이전트: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def all(self) -> list[Agent]:
        return list(self._agents.values())

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    def _tools(self) -> list[dict]:
        return [
            {
                "name": a.name,
                "description": a.description,
                "input_schema": a.input_schema,
            }
            for a in self._agents.values()
        ]

    async def llm_dispatch(self, text: str) -> str:
        """사용자 자유 입력을 LLM으로 의도 분류해 적절한 에이전트에 위임."""
        if not config.ANTHROPIC_API_KEY:
            return "ANTHROPIC_API_KEY가 설정되지 않아 LLM 라우팅을 사용할 수 없습니다."

        _MODEL = "claude-haiku-4-5-20251001"
        response = await self._get_client().messages.create(
            model=_MODEL,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=self._tools(),
            messages=[{"role": "user", "content": text}],
        )

        u = response.usage
        usage_tracker.record(
            model=_MODEL,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            purpose="dispatch",
        )

        for block in response.content:
            if block.type == "tool_use":
                agent = self.get(block.name)
                if agent:
                    args = list(block.input.values())
                    return await agent.handle(args)

        # 도구 호출 없이 텍스트 응답만 온 경우
        for block in response.content:
            if hasattr(block, "text"):
                return block.text

        return "이해하지 못했습니다. /help 로 사용 가능한 명령을 확인하세요."
