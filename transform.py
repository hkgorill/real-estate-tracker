"""
수집 결과 정규화 및 집계 모듈.

scrapers에서 반환된 결과를 ARD 스키마(raw_data, summary)에 맞게 변환한다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))

TRADE_TYPES = ["매매", "전세", "월세"]


@dataclass
class RawRow:
    """raw_data 시트 한 행."""
    collected_at: str     # ISO datetime KST
    date: str             # YYYY-MM-DD KST
    region_level1: str
    region_level2: str
    trade_type: str       # 매매 | 전세 | 월세
    listing_count: int
    source: str           # zigbang | naver | zigbang_error | naver_error
    status: str           # ok | error
    error_msg: str = ""

    def to_row(self) -> list[Any]:
        return [
            self.collected_at,
            self.date,
            self.region_level1,
            self.region_level2,
            self.trade_type,
            self.listing_count,
            self.source,
            self.status,
            self.error_msg,
        ]

    @classmethod
    def headers(cls) -> list[str]:
        return [
            "collected_at", "date", "region_level1", "region_level2",
            "trade_type", "listing_count", "source", "status", "error_msg",
        ]


@dataclass
class SummaryRow:
    """summary 시트 한 행."""
    date: str
    region_level1: str
    region_level2: str
    sale_count: int = 0
    jeonse_count: int = 0
    monthly_count: int = 0
    total_count: int = 0

    def to_row(self) -> list[Any]:
        return [
            self.date,
            self.region_level1,
            self.region_level2,
            self.sale_count,
            self.jeonse_count,
            self.monthly_count,
            self.total_count,
        ]

    @classmethod
    def headers(cls) -> list[str]:
        return [
            "date", "region_level1", "region_level2",
            "sale_count", "jeonse_count", "monthly_count", "total_count",
        ]


@dataclass
class TransformResult:
    raw_rows: list[RawRow] = field(default_factory=list)
    summary_rows: list[SummaryRow] = field(default_factory=list)
    collected_at: str = ""
    date: str = ""
    error_count: int = 0
    total_rows: int = 0


def _now_kst() -> datetime:
    return datetime.now(KST)


def normalize(scraper_results: list[Any], collected_at: datetime | None = None) -> TransformResult:
    """
    zigbang / naver scraper 결과 목록을 raw_rows + summary_rows로 변환한다.

    scraper_results: ZigbangResult 또는 NaverResult 리스트
    """
    if collected_at is None:
        collected_at = _now_kst()

    collected_at_str = collected_at.strftime("%Y-%m-%d %H:%M:%S")
    date_str = collected_at.strftime("%Y-%m-%d")

    raw_rows: list[RawRow] = []
    error_count = 0

    for r in scraper_results:
        is_error = r.listing_count < 0 or "error" in r.source
        raw_rows.append(
            RawRow(
                collected_at=collected_at_str,
                date=date_str,
                region_level1=r.region_level1,
                region_level2=r.region_level2,
                trade_type=r.trade_type,
                listing_count=max(r.listing_count, 0),
                source=r.source,
                status="error" if is_error else "ok",
                error_msg="수집 실패" if is_error else "",
            )
        )
        if is_error:
            error_count += 1

    summary_rows = _build_summary(raw_rows, date_str)

    return TransformResult(
        raw_rows=raw_rows,
        summary_rows=summary_rows,
        collected_at=collected_at_str,
        date=date_str,
        error_count=error_count,
        total_rows=len(raw_rows),
    )


def _build_summary(raw_rows: list[RawRow], date_str: str) -> list[SummaryRow]:
    """raw_rows를 지역×날짜 단위로 집계하여 summary_rows를 생성한다."""
    index: dict[tuple[str, str], SummaryRow] = {}

    for row in raw_rows:
        if row.status == "error":
            continue
        key = (row.region_level1, row.region_level2)
        if key not in index:
            index[key] = SummaryRow(
                date=date_str,
                region_level1=row.region_level1,
                region_level2=row.region_level2,
            )
        s = index[key]
        if row.trade_type == "매매":
            s.sale_count = row.listing_count
        elif row.trade_type == "전세":
            s.jeonse_count = row.listing_count
        elif row.trade_type == "월세":
            s.monthly_count = row.listing_count

    for s in index.values():
        s.total_count = s.sale_count + s.jeonse_count + s.monthly_count

    return list(index.values())


def to_csv_rows(result: TransformResult) -> dict[str, list[list[Any]]]:
    """TransformResult를 CSV 딕셔너리로 변환한다. (로컬 디버그용)"""
    return {
        "raw_data": [RawRow.headers()] + [r.to_row() for r in result.raw_rows],
        "summary": [SummaryRow.headers()] + [r.to_row() for r in result.summary_rows],
    }
