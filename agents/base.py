"""모든 하부 에이전트의 공통 인터페이스.

새 에이전트 추가 = 이 클래스를 상속해 name / description / handle 만 구현하고
orchestrator 에 register 하면 끝. 이것이 확장성의 핵심이다.
"""
from abc import ABC, abstractmethod


class Agent(ABC):
    #: 텔레그램 명령어 이름 (예: "stock" -> /stock 으로 호출)
    name: str = ""
    #: /help 에 표시될 한 줄 설명
    description: str = ""
    #: Claude tool_use 에 넘길 JSON Schema — 서브클래스에서 오버라이드
    input_schema: dict = {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    async def handle(self, args: list[str]) -> str:
        """명령 인자를 받아 텔레그램으로 보낼 응답 문자열을 반환한다."""
        raise NotImplementedError
