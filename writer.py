"""
Google Sheets 데이터 적재 모듈.

raw_data, summary, run_log 시트에 수집 결과를 기록한다.

upsert 전략:
- raw_data: 같은 date의 기존 행을 모두 삭제 후 새 행 append
  (당일 재실행 시 중복 없이 덮어씀)
- summary: 같은 date의 기존 행을 모두 삭제 후 새 행 append
- run_log: 항상 append (실행 이력 누적)
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from googleapiclient.errors import HttpError
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from transform import TransformResult, RawRow, SummaryRow

KST = timezone(timedelta(hours=9))

# Sheets API batchUpdate 한 번에 최대 행 수 (할당량 초과 방지)
BATCH_SIZE = 500


@dataclass
class RunLogRow:
    run_at: str
    status: str          # success | partial | failed
    total_rows: int
    error_count: int
    source_used: str
    duration_sec: float

    def to_row(self) -> list:
        return [
            self.run_at,
            self.status,
            self.total_rows,
            self.error_count,
            self.source_used,
            round(self.duration_sec, 1),
        ]


class SheetsWriter:
    def __init__(self, service, spreadsheet_id: str):
        self._svc = service
        self._sid = spreadsheet_id

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(HttpError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _values_get(self, range_name: str) -> list[list]:
        resp = (
            self._svc.spreadsheets()
            .values()
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
        body = {"values": rows}
        self._svc.spreadsheets().values().append(
            spreadsheetId=self._sid,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()

    @retry(
        retry=retry_if_exception_type(HttpError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _batch_delete_rows(self, sheet_id: int, row_indices: list[int]):
        """지정한 행 인덱스(0-based, 헤더 제외)를 역순으로 삭제한다."""
        if not row_indices:
            return
        requests = []
        for idx in sorted(row_indices, reverse=True):
            # +1 offset: 헤더가 row 0이므로 데이터는 row 1부터
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
            # batchUpdate는 요청 수 제한이 있으므로 50개씩 나눠 전송
            if len(requests) >= 50:
                self._svc.spreadsheets().batchUpdate(
                    spreadsheetId=self._sid, body={"requests": requests}
                ).execute()
                requests = []
        if requests:
            self._svc.spreadsheets().batchUpdate(
                spreadsheetId=self._sid, body={"requests": requests}
            ).execute()

    def _get_sheet_id(self, sheet_name: str) -> int:
        meta = self._svc.spreadsheets().get(spreadsheetId=self._sid).execute()
        for s in meta["sheets"]:
            if s["properties"]["title"] == sheet_name:
                return s["properties"]["sheetId"]
        raise ValueError(f"시트를 찾을 수 없습니다: {sheet_name}")

    def _find_rows_by_date(self, sheet_name: str, date_str: str, date_col: int = 1) -> list[int]:
        """date_col 기준으로 date_str과 일치하는 행의 0-based 인덱스 목록을 반환한다."""
        all_values = self._values_get(f"{sheet_name}!A:Z")
        # row 0은 헤더이므로 1부터 탐색
        return [
            i - 1  # 헤더 제외한 데이터 인덱스
            for i, row in enumerate(all_values[1:], start=1)
            if len(row) > date_col and row[date_col] == date_str
        ]

    # ── 공개 메서드 ────────────────────────────────────────────────────

    def upsert_raw_data(self, result: TransformResult):
        """raw_data 시트에 당일 데이터를 upsert한다 (date 컬럼=인덱스 1 기준)."""
        sheet_name = "raw_data"
        logger.info("[writer] raw_data upsert: {}", result.date)

        existing_indices = self._find_rows_by_date(sheet_name, result.date, date_col=1)
        if existing_indices:
            logger.info("  기존 {} 행 삭제 (date={})", len(existing_indices), result.date)
            sheet_id = self._get_sheet_id(sheet_name)
            self._batch_delete_rows(sheet_id, existing_indices)

        rows = [r.to_row() for r in result.raw_rows]
        for i in range(0, len(rows), BATCH_SIZE):
            self._values_append(f"{sheet_name}!A1", rows[i : i + BATCH_SIZE])
            if i + BATCH_SIZE < len(rows):
                time.sleep(0.5)  # Sheets API 할당량 여유

        logger.info("  → {} 행 적재 완료", len(rows))

    def upsert_summary(self, result: TransformResult):
        """summary 시트에 당일 데이터를 upsert한다 (date 컬럼=인덱스 0 기준)."""
        sheet_name = "summary"
        logger.info("[writer] summary upsert: {}", result.date)

        existing_indices = self._find_rows_by_date(sheet_name, result.date, date_col=0)
        if existing_indices:
            logger.info("  기존 {} 행 삭제 (date={})", len(existing_indices), result.date)
            sheet_id = self._get_sheet_id(sheet_name)
            self._batch_delete_rows(sheet_id, existing_indices)

        rows = [r.to_row() for r in result.summary_rows]
        for i in range(0, len(rows), BATCH_SIZE):
            self._values_append(f"{sheet_name}!A1", rows[i : i + BATCH_SIZE])

        logger.info("  → {} 행 적재 완료", len(rows))

    def append_run_log(self, log_row: RunLogRow):
        """run_log 시트에 실행 이력을 append한다."""
        self._values_append("run_log!A1", [log_row.to_row()])
        logger.info("[writer] run_log append: status={}", log_row.status)

    def write(self, result: TransformResult, run_log: RunLogRow):
        """raw_data, summary, run_log를 한 번에 기록한다."""
        self.upsert_raw_data(result)
        self.upsert_summary(result)
        self.append_run_log(run_log)
