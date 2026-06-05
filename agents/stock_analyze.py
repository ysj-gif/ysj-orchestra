"""주식 AI 분석 에이전트.

FinanceDataReader 로 3개월치 가격·거래량 데이터를 수집한 뒤
Claude API 로 기술적 분석 및 투자 인사이트를 생성한다.
"""
import asyncio
import datetime as dt

import anthropic
import FinanceDataReader as fdr

import config
import usage_tracker
from agents.stock import StockAgent

_ANALYST_SYSTEM = (
    "당신은 주식 시장 전문 애널리스트입니다. "
    "제공된 주가 데이터를 바탕으로 명확하고 실용적인 분석을 제공하세요. "
    "분석은 한국어로, 간결하고 핵심 위주로 작성하세요. "
    "섹션별로 구분하고 이모지를 적절히 활용해 가독성을 높이세요. "
    "마지막에 반드시 '⚠️ 본 분석은 투자 권유가 아니며 참고 목적으로만 활용하세요.'를 붙이세요."
)


class StockAnalyzeAgent(StockAgent):
    name = "analyze"
    description = (
        "AI 주식 분석. 가격 추이·이동평균·거래량·52주 포지션을 종합해 "
        "기술적 분석 및 투자 인사이트를 제공한다. "
        "단순 시세 조회가 아닌 '분석', '전망', '추세' 등이 포함된 요청에 사용."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "분석할 종목명 또는 코드. "
                    "KRX 예: '삼성전자', 'SK하이닉스'. "
                    "해외 예: 'AAPL', 'TSLA', 'NVDA'."
                ),
            }
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        super().__init__()
        self._ai_client: anthropic.AsyncAnthropic | None = None

    def _get_ai_client(self) -> anthropic.AsyncAnthropic:
        if self._ai_client is None:
            self._ai_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._ai_client

    def _collect_data(self, query: str) -> dict:
        symbol = self._resolve(query)
        today = dt.date.today()

        df = fdr.DataReader(symbol, today - dt.timedelta(days=90), today)
        if df is None or df.empty:
            raise ValueError(f"'{query}' 시세를 찾지 못했습니다. 종목명이나 코드를 확인해 주세요.")
        df = df.dropna(subset=["Close"])
        if len(df) < 5:
            raise ValueError(f"'{query}' 유효 데이터가 부족합니다.")

        close = df["Close"].astype(float)
        current = close.iloc[-1]
        prev_day  = close.iloc[-2]  if len(close) >= 2  else current
        week_ago  = close.iloc[-6]  if len(close) >= 6  else current
        month_ago = close.iloc[-22] if len(close) >= 22 else current

        ma5  = close.tail(5).mean()
        ma20 = close.tail(20).mean() if len(close) >= 20 else None
        ma60 = close.tail(60).mean() if len(close) >= 60 else None

        # 52주 고저 — 별도 조회, 실패 시 현재 데이터 범위로 대체
        try:
            df_52w = fdr.DataReader(symbol, today - dt.timedelta(days=365), today)
            high_52w = float(df_52w["High"].max())
            low_52w  = float(df_52w["Low"].min())
        except Exception:
            high_52w = float(df["High"].max())
            low_52w  = float(df["Low"].min())

        # 거래량 (컬럼명 방어적 처리)
        vol_col = next((c for c in df.columns if c.lower() == "volume"), None)
        vol_data: dict = {}
        if vol_col:
            vol = df[vol_col].astype(float)
            vol_data = {
                "avg_20d":    float(vol.tail(20).mean() if len(vol) >= 20 else vol.mean()),
                "recent_5d":  float(vol.tail(5).mean()),
            }

        return {
            "symbol":      symbol,
            "name":        query,
            "date":        df.index[-1].strftime("%Y-%m-%d"),
            "current":     float(current),
            "day_chg":     (float(current) - float(prev_day))  / float(prev_day)  * 100,
            "week_chg":    (float(current) - float(week_ago))  / float(week_ago)  * 100,
            "month_chg":   (float(current) - float(month_ago)) / float(month_ago) * 100,
            "ma5":         float(ma5),
            "ma20":        float(ma20) if ma20 is not None else None,
            "ma60":        float(ma60) if ma60 is not None else None,
            "high_52w":    high_52w,
            "low_52w":     low_52w,
            "vol":         vol_data,
            "closes_20d":  [float(x) for x in close.tail(20).tolist()],
        }

    @staticmethod
    def _build_prompt(d: dict) -> str:
        pos_52w = (
            (d["current"] - d["low_52w"]) / (d["high_52w"] - d["low_52w"]) * 100
            if d["high_52w"] != d["low_52w"] else 50.0
        )

        lines = [
            f"종목: {d['name']} ({d['symbol']})",
            f"기준일: {d['date']}",
            f"현재가: {d['current']:,.0f}",
            f"전일대비: {d['day_chg']:+.2f}%",
            f"1주 수익률: {d['week_chg']:+.2f}%",
            f"1개월 수익률: {d['month_chg']:+.2f}%",
            f"52주 고/저: {d['high_52w']:,.0f} / {d['low_52w']:,.0f}  (현재 위치: {pos_52w:.1f}%)",
            f"MA5: {d['ma5']:,.0f}",
        ]
        if d["ma20"]:
            lines.append(f"MA20: {d['ma20']:,.0f}")
        if d["ma60"]:
            lines.append(f"MA60: {d['ma60']:,.0f}")
        if d["vol"]:
            ratio = (
                d["vol"]["recent_5d"] / d["vol"]["avg_20d"] * 100
                if d["vol"]["avg_20d"] else 100.0
            )
            lines.append(f"거래량: 최근 5일 평균이 20일 평균 대비 {ratio:.0f}%")

        lines.append(
            f"\n최근 20일 종가 (오래된 순): "
            + ", ".join(f"{p:,.0f}" for p in d["closes_20d"])
        )
        lines.append(
            "\n위 데이터를 바탕으로 다음 항목을 분석해주세요:\n"
            "1. 단기 추세 (상승/하락/횡보 및 모멘텀)\n"
            "2. 이동평균선 분석 (골든/데드크로스, 지지/저항)\n"
            "3. 52주 포지션 시사점\n"
            "4. 거래량 신호\n"
            "5. 종합 의견"
        )
        return "\n".join(lines)

    async def handle(self, args: list[str]) -> str:
        if not args:
            return "분석할 종목을 입력하세요. 예: /analyze 삼성전자"
        if not config.ANTHROPIC_API_KEY:
            return "ANTHROPIC_API_KEY가 설정되지 않아 AI 분석을 사용할 수 없습니다."

        query = " ".join(str(a) for a in args).strip()

        try:
            data = await asyncio.to_thread(self._collect_data, query)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"데이터 조회 중 오류가 발생했습니다: {e}"

        prompt = self._build_prompt(data)

        _MODEL = "claude-haiku-4-5-20251001"
        try:
            response = await self._get_ai_client().messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": _ANALYST_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
            u = response.usage
            usage_tracker.record(
                model=_MODEL,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
                cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                purpose="analyze",
            )
            analysis = response.content[0].text
            return (
                f"📊 {query} ({data['symbol']}) AI 분석\n"
                f"기준일: {data['date']}\n\n"
                f"{analysis}"
            )
        except Exception as e:
            return f"AI 분석 중 오류가 발생했습니다: {e}"
