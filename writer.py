"""
Google Sheets 데이터 적재 모듈.

5개 데이터 시트 + run_log 시트에 수집 결과를 기록한다.

upsert 전략:
  price_index, jeonse_ratio: period(주차) 기준으로 기존 행 삭제 후 append
  interest_rate, unsold:     period(월) 기준으로 기존 행 삭제 후 append
  apt_trade:                 deal_ym(월) 기준으로 기존 행 삭제 후 append
  run_log:                   항상 append
"""

import time
from dataclasses import dataclass
from typing import Any

from googleapiclient.errors import HttpError
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from transform import (
    CollectResult,
    PriceIndexRow, JeonseRatioRow, InterestRateRow, AptTradeRow, UnsoldRow,
)

BATCH_SIZE = 500


@dataclass
class RunLogRow:
    run_at: str
    status: str           # success | partial | failed
    total_rows: int
    error_count: int
    sources_used: str     # 쉼표 구분 소스 목록
    duration_sec: float

    def to_row(self) -> list[Any]:
        return [
            self.run_at, self.status, self.total_rows,
            self.error_count, self.sources_used, round(self.duration_sec, 1),
        ]

    @classmethod
    def headers(cls) -> list[str]:
        return ["run_at", "status", "total_rows", "error_count", "sources_used", "duration_sec"]


class SheetsWriter:
    def __init__(self, service, spreadsheet_id: str):
        self._svc = service
        self._sid = spreadsheet_id
        self._sheet_id_cache: dict[str, int] = {}

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(HttpError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _values_get(self, range_name: str) -> list[list]:
        resp = (
            self._svc.spreadsheets().values()
            .get(spreadsheetId=self._sid, range=range_name)
            .execute()
        )
        return resp.get("values", [])

    @retry(
        retry=retry_if_exception_type(HttpError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _values_append(self, range_name: str, rows: list[list]):
        if not rows:
            return
        self._svc.spreadsheets().values().append(
            spreadsheetId=self._sid,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

    def _get_sheet_id(self, sheet_name: str) -> int:
        if sheet_name not in self._sheet_id_cache:
            meta = self._svc.spreadsheets().get(spreadsheetId=self._sid).execute()
            for s in meta["sheets"]:
                title = s["properties"]["title"]
                self._sheet_id_cache[title] = s["properties"]["sheetId"]
        return self._sheet_id_cache[sheet_name]

    def _delete_rows_by_key(self, sheet_name: str, key_value: str, key_col: int):
        """key_col 열의 값이 key_value와 일치하는 행을 모두 삭제한다."""
        all_values = self._values_get(f"{sheet_name}!A:Z")
        indices = [
            i - 1
            for i, row in enumerate(all_values[1:], start=1)
            if len(row) > key_col and row[key_col] == key_value
        ]
        if not indices:
            return

        sheet_id = self._get_sheet_id(sheet_name)
        requests = []
        for idx in sorted(indices, reverse=True):
            requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": idx + 1,
                        "endIndex": idx + 2,
                    }
                }
            })
            if len(requests) >= 50:
                self._svc.spreadsheets().batchUpdate(
                    spreadsheetId=self._sid, body={"requests": requests}
                ).execute()
                requests = []
        if requests:
            self._svc.spreadsheets().batchUpdate(
                spreadsheetId=self._sid, body={"requests": requests}
            ).execute()

    def _upsert(self, sheet_name: str, rows: list[list], key_value: str, key_col: int):
        """key_col=key_value인 기존 행을 지우고 새 행을 append한다."""
        if not rows:
            return
        logger.info("[writer] {} upsert key={}", sheet_name, key_value)
        self._delete_rows_by_key(sheet_name, key_value, key_col)
        for i in range(0, len(rows), BATCH_SIZE):
            self._values_append(f"{sheet_name}!A1", rows[i: i + BATCH_SIZE])
            if i + BATCH_SIZE < len(rows):
                time.sleep(0.5)
        logger.info("  → {} 행 적재", len(rows))

    # ── 공개 메서드 ────────────────────────────────────────────────────────────

    def upsert_price_index(self, rows: list[PriceIndexRow], period: str):
        """period(YYYYWW) 기준 upsert. key_col=1 (period 열)."""
        self._upsert("price_index", [r.to_row() for r in rows], period, key_col=1)

    def upsert_jeonse_ratio(self, rows: list[JeonseRatioRow], period: str):
        self._upsert("jeonse_ratio", [r.to_row() for r in rows], period, key_col=1)

    def upsert_interest_rate(self, rows: list[InterestRateRow], period: str):
        self._upsert("interest_rate", [r.to_row() for r in rows], period, key_col=1)

    def upsert_apt_trade(self, rows: list[AptTradeRow], deal_ym: str):
        """deal_ym(YYYYMM) 기준 upsert. key_col=1 (deal_ym 열)."""
        self._upsert("apt_trade", [r.to_row() for r in rows], deal_ym, key_col=1)

    def upsert_unsold(self, rows: list[UnsoldRow], deal_ym: str):
        self._upsert("unsold", [r.to_row() for r in rows], deal_ym, key_col=1)

    def append_run_log(self, log_row: RunLogRow):
        self._values_append("run_log!A1", [log_row.to_row()])
        logger.info("[writer] run_log: status={}", log_row.status)

    def write(self, result: CollectResult, run_log: RunLogRow):
        """수집 결과 전체를 Sheets에 기록한다."""
        # price_index / jeonse_ratio: 주차(period) 기준으로 그룹화하여 upsert
        if result.price_index_rows:
            for period in sorted({r.period for r in result.price_index_rows}):
                subset = [r for r in result.price_index_rows if r.period == period]
                self.upsert_price_index(subset, period)

        if result.jeonse_ratio_rows:
            for period in sorted({r.period for r in result.jeonse_ratio_rows}):
                subset = [r for r in result.jeonse_ratio_rows if r.period == period]
                self.upsert_jeonse_ratio(subset, period)

        # interest_rate: 월(period) 기준
        if result.interest_rate_rows:
            for period in sorted({r.period for r in result.interest_rate_rows}):
                subset = [r for r in result.interest_rate_rows if r.period == period]
                self.upsert_interest_rate(subset, period)

        # apt_trade: 거래년월(deal_ym) 기준
        if result.apt_trade_rows:
            for deal_ym in sorted({r.deal_ym for r in result.apt_trade_rows}):
                subset = [r for r in result.apt_trade_rows if r.deal_ym == deal_ym]
                self.upsert_apt_trade(subset, deal_ym)

        # unsold: 거래년월 기준
        if result.unsold_rows:
            for deal_ym in sorted({r.deal_ym for r in result.unsold_rows}):
                subset = [r for r in result.unsold_rows if r.deal_ym == deal_ym]
                self.upsert_unsold(subset, deal_ym)

        self.append_run_log(run_log)
