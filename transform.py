"""
수집 결과 정규화 및 시트별 행 변환 모듈.

4종 데이터 소스 → 5개 시트 스키마로 변환:
  R-ONE    → price_index, jeonse_ratio
  ECOS     → interest_rate
  MOLIT    → apt_trade, unsold
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from scrapers.rbone import PriceIndexResult
from scrapers.ecos import InterestRateResult
from scrapers.molit import AptTradeItem, UnsoldItem

KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


# ── 시트별 Row 모델 ────────────────────────────────────────────────────────────

@dataclass
class PriceIndexRow:
    """price_index 시트 한 행.

    jeonse_idx_ratio = jeonse_index / sale_index × 100
      → 두 지수가 같은 기준시점을 공유하므로 비율의 방향성은 실제 전세가율 추이와 일치.
         단, 절대값은 실제 전세가율(전세실거래가/매매실거래가)과 다름.
    """
    collected_at: str
    period: str              # YYYYWW
    region: str
    sale_index: float
    jeonse_index: float
    jeonse_idx_ratio: float  # 전세/매매 지수 비율 (파생값)
    source: str

    def to_row(self) -> list[Any]:
        return [self.collected_at, self.period, self.region,
                self.sale_index, self.jeonse_index,
                round(self.jeonse_idx_ratio, 2), self.source]

    @classmethod
    def headers(cls) -> list[str]:
        return ["collected_at", "period", "region",
                "sale_index", "jeonse_index", "jeonse_idx_ratio", "source"]


@dataclass
class InterestRateRow:
    """interest_rate 시트 한 행."""
    collected_at: str
    period: str         # YYYYMM
    base_rate: float
    mortgage_rate: float
    source: str

    def to_row(self) -> list[Any]:
        return [self.collected_at, self.period, self.base_rate, self.mortgage_rate, self.source]

    @classmethod
    def headers(cls) -> list[str]:
        return ["collected_at", "period", "base_rate", "mortgage_rate", "source"]


@dataclass
class AptTradeRow:
    """apt_trade 시트 한 행."""
    collected_at: str
    deal_ym: str            # YYYYMM
    deal_date: str          # YYYY-MM-DD
    region_level1: str
    region_level2: str
    dong: str
    apt_name: str
    area_sqm: float
    floor: int
    price_manwon: int
    build_year: int
    source: str

    def to_row(self) -> list[Any]:
        return [
            self.collected_at, self.deal_ym, self.deal_date,
            self.region_level1, self.region_level2, self.dong,
            self.apt_name, self.area_sqm, self.floor,
            self.price_manwon, self.build_year, self.source,
        ]

    @classmethod
    def headers(cls) -> list[str]:
        return [
            "collected_at", "deal_ym", "deal_date",
            "region_level1", "region_level2", "dong",
            "apt_name", "area_sqm", "floor",
            "price_manwon", "build_year", "source",
        ]


@dataclass
class UnsoldRow:
    """unsold 시트 한 행."""
    collected_at: str
    deal_ym: str            # YYYYMM
    region_level1: str
    unsold_total: int
    unsold_before: int      # 준공 전 미분양
    unsold_after: int       # 준공 후 미분양 (악성)
    source: str

    def to_row(self) -> list[Any]:
        return [
            self.collected_at, self.deal_ym, self.region_level1,
            self.unsold_total, self.unsold_before, self.unsold_after, self.source,
        ]

    @classmethod
    def headers(cls) -> list[str]:
        return [
            "collected_at", "deal_ym", "region_level1",
            "unsold_total", "unsold_before", "unsold_after", "source",
        ]


# ── 수집 결과 컨테이너 ─────────────────────────────────────────────────────────

@dataclass
class CollectResult:
    collected_at: str = ""
    price_index_rows: list[PriceIndexRow] = field(default_factory=list)
    interest_rate_rows: list[InterestRateRow] = field(default_factory=list)
    apt_trade_rows: list[AptTradeRow] = field(default_factory=list)
    unsold_rows: list[UnsoldRow] = field(default_factory=list)
    error_count: int = 0
    total_rows: int = 0
    sources_used: list[str] = field(default_factory=list)

    def recount(self):
        self.total_rows = (
            len(self.price_index_rows)
            + len(self.interest_rate_rows)
            + len(self.apt_trade_rows)
            + len(self.unsold_rows)
        )


# ── 변환 함수 ──────────────────────────────────────────────────────────────────

def normalize_price_index(
    results: list[PriceIndexResult],
    collected_at: datetime | None = None,
) -> list[PriceIndexRow]:
    if collected_at is None:
        collected_at = _now_kst()
    ts = collected_at.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in results:
        # 두 지수 모두 유효할 때만 비율 계산 (음수는 수집 실패를 의미)
        if r.sale_index > 0 and r.jeonse_index > 0:
            ratio = r.jeonse_index / r.sale_index * 100
        else:
            ratio = -1.0
        rows.append(PriceIndexRow(
            collected_at=ts,
            period=r.period,
            region=r.region,
            sale_index=r.sale_index,
            jeonse_index=r.jeonse_index,
            jeonse_idx_ratio=ratio,
            source=r.source,
        ))
    return rows


def normalize_interest_rate(
    results: list[InterestRateResult],
    collected_at: datetime | None = None,
) -> list[InterestRateRow]:
    if collected_at is None:
        collected_at = _now_kst()
    ts = collected_at.strftime("%Y-%m-%d %H:%M:%S")
    return [
        InterestRateRow(
            collected_at=ts,
            period=r.period,
            base_rate=r.base_rate,
            mortgage_rate=r.mortgage_rate,
            source=r.source,
        )
        for r in results
    ]


def normalize_apt_trade(
    items: list[AptTradeItem],
    collected_at: datetime | None = None,
) -> list[AptTradeRow]:
    if collected_at is None:
        collected_at = _now_kst()
    ts = collected_at.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for item in items:
        day = item.deal_day.strip().zfill(2) if item.deal_day.strip() else "01"
        ym = item.deal_ym  # YYYYMM
        deal_date = f"{ym[:4]}-{ym[4:6]}-{day}"
        rows.append(AptTradeRow(
            collected_at=ts,
            deal_ym=item.deal_ym,
            deal_date=deal_date,
            region_level1=item.region_level1,
            region_level2=item.region_level2,
            dong=item.dong,
            apt_name=item.apt_name,
            area_sqm=item.area_sqm,
            floor=item.floor,
            price_manwon=item.price_manwon,
            build_year=item.build_year,
            source=item.source,
        ))
    return rows


def normalize_unsold(
    items: list[UnsoldItem],
    collected_at: datetime | None = None,
) -> list[UnsoldRow]:
    if collected_at is None:
        collected_at = _now_kst()
    ts = collected_at.strftime("%Y-%m-%d %H:%M:%S")
    return [
        UnsoldRow(
            collected_at=ts,
            deal_ym=item.deal_ym,
            region_level1=item.region_level1,
            unsold_total=item.unsold_total,
            unsold_before=item.unsold_before,
            unsold_after=item.unsold_after,
            source=item.source,
        )
        for item in items
    ]


def to_csv_rows(result: CollectResult) -> dict[str, list[list[Any]]]:
    """CollectResult를 CSV 딕셔너리로 변환한다. (로컬 디버그용)"""
    return {
        "price_index":   [PriceIndexRow.headers()]   + [r.to_row() for r in result.price_index_rows],
        "interest_rate": [InterestRateRow.headers()]  + [r.to_row() for r in result.interest_rate_rows],
        "apt_trade":     [AptTradeRow.headers()]      + [r.to_row() for r in result.apt_trade_rows],
        "unsold":        [UnsoldRow.headers()]         + [r.to_row() for r in result.unsold_rows],
    }
