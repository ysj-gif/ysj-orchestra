"""Anthropic API 토큰 사용량 조회 에이전트."""
import usage_tracker
from agents.base import Agent


class UsageAgent(Agent):
    name = "usage"
    description = (
        "Anthropic API 토큰 사용량 조회. "
        "오늘 및 누적 입출력 토큰 수와 추정 비용(USD)을 보고한다."
    )
    input_schema = {"type": "object", "properties": {}, "required": []}

    async def handle(self, args: list[str]) -> str:
        s = usage_tracker.get_stats()
        td = s["today"]
        tt = s["total"]
        last = s["last_call"] or "없음"

        if tt["calls"] == 0:
            return "아직 기록된 API 사용량이 없습니다."

        def fmt(n: int) -> str:
            return f"{n:,}"

        def fmt_cost(c: float) -> str:
            return f"≈ ${c:.5f}"

        lines = [
            "🔢 Anthropic API 토큰 사용량",
            "",
            f"📅 오늘 ({td['date']},  {td['calls']}회 호출)",
            f"  입력        {fmt(td['input'])} 토큰",
            f"  출력        {fmt(td['output'])} 토큰",
            f"  캐시 쓰기   {fmt(td['cache_write'])} 토큰",
            f"  캐시 읽기   {fmt(td['cache_read'])} 토큰",
            f"  추정 비용   {fmt_cost(td['cost_usd'])} USD",
            "",
            f"📊 누적 전체 ({tt['calls']}회 호출)",
            f"  입력        {fmt(tt['input'])} 토큰",
            f"  출력        {fmt(tt['output'])} 토큰",
            f"  캐시 쓰기   {fmt(tt['cache_write'])} 토큰",
            f"  캐시 읽기   {fmt(tt['cache_read'])} 토큰",
            f"  추정 비용   {fmt_cost(tt['cost_usd'])} USD",
            "",
            f"🕐 마지막 호출: {last}",
            "",
            "💡 잔여 크레딧 확인: console.anthropic.com",
            "   (잔여 크레딧은 Anthropic API에서 미제공)",
        ]
        return "\n".join(lines)
