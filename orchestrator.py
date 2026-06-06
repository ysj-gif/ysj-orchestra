"""명령어 -> 에이전트 라우팅 + 에이전트 레지스트리.

- command_dispatch : /stock 처럼 명령어가 명확할 때 직접 에이전트 호출
- llm_dispatch     : 자유 텍스트 입력을 Cerebras(gpt-oss-120b)로 의도 분류해 에이전트 호출
"""
import json

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
        self._client = None

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

    def _get_client(self):
        if self._client is None:
            from cerebras.cloud.sdk import AsyncCerebras
            self._client = AsyncCerebras(api_key=config.CEREBRAS_API_KEY)
        return self._client

    def _tools(self) -> list[dict]:
        """에이전트 목록을 OpenAI 호환 tool 정의로 변환."""
        return [
            {
                "type": "function",
                "function": {
                    "name": a.name,
                    "description": a.description,
                    "parameters": a.input_schema,
                },
            }
            for a in self._agents.values()
        ]

    async def llm_dispatch(self, text: str) -> str:
        """사용자 자유 입력을 Cerebras LLM으로 의도 분류해 적절한 에이전트에 위임."""
        if not config.CEREBRAS_API_KEY:
            return "CEREBRAS_API_KEY가 설정되지 않아 LLM 라우팅을 사용할 수 없습니다."

        # 앞 모델이 deprecated되면 다음 모델로 자동 전환
        _MODELS = ["gpt-oss-120b", "zai-glm-4.7", "qwen-3-235b-a22b-instruct-2507"]

        response = None
        used_model = None
        for model in _MODELS:
            try:
                response = await self._get_client().chat.completions.create(
                    model=model,
                    max_tokens=256,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": text},
                    ],
                    tools=self._tools(),
                    tool_choice="auto",
                )
                used_model = model
                break
            except Exception as e:
                err = str(e)
                if "model_not_found" in err or "does not exist" in err:
                    continue  # 다음 백업 모델 시도
                return f"라우팅 중 오류가 발생했습니다: {e}"

        if response is None:
            return "사용 가능한 라우팅 모델이 없습니다. Cerebras 모델 목록을 확인해 주세요."

        u = response.usage
        usage_tracker.record(
            model=used_model,
            input_tokens=u.prompt_tokens,
            output_tokens=u.completion_tokens,
            cache_write=0,
            cache_read=0,
            purpose="dispatch",
        )

        message = response.choices[0].message

        # 도구 호출이 있는 경우
        if message.tool_calls:
            for tool_call in message.tool_calls:
                agent = self.get(tool_call.function.name)
                if agent:
                    args_dict = json.loads(tool_call.function.arguments)
                    args = list(args_dict.values())
                    return await agent.handle(args)

        # 도구 호출 없이 텍스트 응답만 온 경우
        if message.content:
            return message.content

        return "이해하지 못했습니다. /help 로 사용 가능한 명령을 확인하세요."
