"""주식 시세 조회 에이전트.

FinanceDataReader 로 국내/해외 시세를 조회한다.
- 한국 종목명("삼성전자")이면 6자리 코드로 변환 후 조회
- 코드/티커("005930", "AAPL")는 그대로 조회

데이터 소스를 바꾸고 싶으면 _fetch 안의 fdr 호출부만 교체하면 된다.
"""
import asyncio
import datetime as dt
import difflib

import FinanceDataReader as fdr

from agents.base import Agent


class StockAgent(Agent):
    name = "stock"
    description = "주식 시세 조회. 종목명(삼성전자, 현대차 등) 또는 티커 코드(005930, AAPL)로 현재 주가를 알려준다."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "조회할 종목명 또는 코드. 약칭·오타가 있으면 KRX 등재명 또는 해외 티커로 정규화해서 전달. "
                    "KRX 한글 등재 예: '삼성' → '삼성전자', '현대' → '현대차', '카카오뱅크'. "
                    "KRX 영문 등재 예: '네이버' → 'NAVER', '카카오' → 'KAKAO', 'SK하이닉스' → 'SK하이닉스'. "
                    "해외 티커 예: '애플' → 'AAPL', '테슬라' → 'TSLA', '엔비디아' → 'NVDA'."
                ),
            }
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        # 종목명 -> 코드 매핑. 최초 조회 시 한 번만 로드하여 캐시.
        self._krx_map: dict[str, str] | None = None

    def _ensure_listing(self) -> None:
        if self._krx_map is not None:
            return
        try:
            df = fdr.StockListing("KRX")
            # 컬럼명은 버전에 따라 다를 수 있으므로 방어적으로 처리
            name_col = "Name" if "Name" in df.columns else df.columns[1]
            code_col = "Code" if "Code" in df.columns else "Symbol"
            self._krx_map = {
                str(row[name_col]): str(row[code_col]).zfill(6)
                for _, row in df.iterrows()
            }
        except Exception:
            # 실패해도 코드 직접 입력 방식은 계속 동작하도록 빈 맵으로 둔다
            self._krx_map = {}

    def _resolve(self, query: str) -> str:
        """종목명이면 코드로 변환, 아니면 입력 그대로(코드/티커) 반환.

        매칭 순서:
        1. 정확 일치
        2. 대소문자 무시 일치  (예: 'naver' → 'NAVER')
        3. 부분 문자열 포함    (예: '네이버' 포함 종목 중 가장 짧은 이름)
        4. difflib 퍼지 매칭   (예: 오타·약칭)
        """
        self._ensure_listing()
        if not self._krx_map:
            return query

        # 1. 정확 일치
        if query in self._krx_map:
            return self._krx_map[query]

        # 2. 대소문자 무시
        q_lower = query.lower()
        for name, code in self._krx_map.items():
            if name.lower() == q_lower:
                return code

        # 3. 부분 문자열 (query가 종목명에 포함되는 경우)
        sub = [(name, code) for name, code in self._krx_map.items() if query in name]
        if sub:
            # 가장 짧은 이름 = 가장 근접한 매칭
            return min(sub, key=lambda x: len(x[0]))[1]

        # 4. 퍼지 매칭
        close = difflib.get_close_matches(query, self._krx_map.keys(), n=1, cutoff=0.6)
        if close:
            return self._krx_map[close[0]]

        return query

    def _fetch(self, query: str) -> str:
        symbol = self._resolve(query)
        end = dt.date.today()
        start = end - dt.timedelta(days=10)

        df = fdr.DataReader(symbol, start, end)
        if df is None or df.empty:
            return f"'{query}' 시세를 찾지 못했습니다. 종목명이나 코드를 확인해 주세요."

        df = df.dropna(subset=["Close"])
        if df.empty:
            return f"'{query}' 의 유효한 종가 데이터가 없습니다."

        close = float(df.iloc[-1]["Close"])
        if len(df) >= 2:
            prev = float(df.iloc[-2]["Close"])
            diff = close - prev
            pct = (diff / prev * 100) if prev else 0.0
            arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "−")
            change = f"{arrow} {abs(diff):,.0f} ({pct:+.2f}%)"
        else:
            change = "전일 데이터 없음"

        date_str = df.index[-1].strftime("%Y-%m-%d")
        return (
            f"📈 {query}  ({symbol})\n"
            f"종가: {close:,.0f}\n"
            f"전일대비: {change}\n"
            f"기준일: {date_str}"
        )

    async def handle(self, args: list[str]) -> str:
        if not args:
            return "종목을 입력하세요. 예: /stock 삼성전자"
        query = " ".join(args).strip()
        # FinanceDataReader 는 동기(blocking) 라서 별도 스레드에서 실행
        try:
            return await asyncio.to_thread(self._fetch, query)
        except Exception as e:
            return f"조회 중 오류가 발생했습니다: {e}"
