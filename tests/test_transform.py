"""transform.py 단위 테스트."""

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

import pytest

from transform import normalize, to_csv_rows, RawRow, SummaryRow, TransformResult

KST = timezone(timedelta(hours=9))
FIXED_DT = datetime(2026, 5, 3, 4, 0, 0, tzinfo=KST)


@dataclass
class FakeResult:
    region_level1: str
    region_level2: str
    trade_type: str
    listing_count: int
    source: str = "zigbang"


def make_region_results(region1="서울특별시", region2="강남구", counts=(100, 50, 30)):
    return [
        FakeResult(region1, region2, "매매", counts[0]),
        FakeResult(region1, region2, "전세", counts[1]),
        FakeResult(region1, region2, "월세", counts[2]),
    ]


class TestNormalize:
    def test_basic_ok_rows(self):
        inputs = make_region_results()
        result = normalize(inputs, collected_at=FIXED_DT)

        assert result.total_rows == 3
        assert result.error_count == 0
        assert result.date == "2026-05-03"
        assert result.collected_at == "2026-05-03 04:00:00"

    def test_raw_rows_status_ok(self):
        inputs = make_region_results()
        result = normalize(inputs, collected_at=FIXED_DT)

        for row in result.raw_rows:
            assert row.status == "ok"
            assert row.error_msg == ""
            assert row.listing_count >= 0

    def test_error_result_flagged(self):
        inputs = [
            FakeResult("서울특별시", "강남구", "매매", -1, source="zigbang_error"),
            FakeResult("서울특별시", "강남구", "전세", 50),
        ]
        result = normalize(inputs, collected_at=FIXED_DT)

        assert result.error_count == 1
        error_row = next(r for r in result.raw_rows if r.trade_type == "매매")
        assert error_row.status == "error"
        assert error_row.listing_count == 0

    def test_summary_aggregation(self):
        inputs = make_region_results(counts=(100, 50, 30))
        result = normalize(inputs, collected_at=FIXED_DT)

        assert len(result.summary_rows) == 1
        s = result.summary_rows[0]
        assert s.sale_count == 100
        assert s.jeonse_count == 50
        assert s.monthly_count == 30
        assert s.total_count == 180

    def test_summary_multiple_regions(self):
        inputs = (
            make_region_results("서울특별시", "강남구", (100, 50, 30))
            + make_region_results("서울특별시", "강북구", (80, 40, 20))
        )
        result = normalize(inputs, collected_at=FIXED_DT)

        assert len(result.summary_rows) == 2
        region_names = {s.region_level2 for s in result.summary_rows}
        assert region_names == {"강남구", "강북구"}

    def test_summary_excludes_error_rows(self):
        inputs = [
            FakeResult("서울특별시", "강남구", "매매", -1, source="zigbang_error"),
            FakeResult("서울특별시", "강남구", "전세", 50),
            FakeResult("서울특별시", "강남구", "월세", 30),
        ]
        result = normalize(inputs, collected_at=FIXED_DT)

        s = result.summary_rows[0]
        # 에러인 매매는 0으로 처리되어 summary에서 제외됨
        assert s.sale_count == 0
        assert s.jeonse_count == 50
        assert s.monthly_count == 30
        assert s.total_count == 80

    def test_empty_input(self):
        result = normalize([], collected_at=FIXED_DT)
        assert result.total_rows == 0
        assert result.error_count == 0
        assert result.raw_rows == []
        assert result.summary_rows == []


class TestToCsvRows:
    def test_headers_present(self):
        inputs = make_region_results()
        result = normalize(inputs, collected_at=FIXED_DT)
        tables = to_csv_rows(result)

        assert "raw_data" in tables
        assert "summary" in tables
        assert tables["raw_data"][0] == RawRow.headers()
        assert tables["summary"][0] == SummaryRow.headers()

    def test_row_count(self):
        inputs = make_region_results()
        result = normalize(inputs, collected_at=FIXED_DT)
        tables = to_csv_rows(result)

        # header + 3 rows
        assert len(tables["raw_data"]) == 4
        # header + 1 summary row
        assert len(tables["summary"]) == 2

    def test_raw_row_values(self):
        inputs = [FakeResult("서울특별시", "강남구", "매매", 100)]
        result = normalize(inputs, collected_at=FIXED_DT)
        tables = to_csv_rows(result)

        row = tables["raw_data"][1]
        assert row[2] == "서울특별시"
        assert row[3] == "강남구"
        assert row[4] == "매매"
        assert row[5] == 100
        assert row[7] == "ok"


class TestRegionsJson:
    """regions.json 스키마 검증."""

    def test_regions_json_loadable(self):
        import json
        from pathlib import Path
        path = Path(__file__).parent.parent / "data" / "regions.json"
        assert path.exists(), "data/regions.json 파일이 없습니다"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "regions" in data

    def test_all_regions_have_required_fields(self):
        import json
        from pathlib import Path
        data = json.loads(
            (Path(__file__).parent.parent / "data" / "regions.json")
            .read_text(encoding="utf-8")
        )
        required = {"region_level1", "region_level2", "cortar_no", "center_lat", "center_lng"}
        for r in data["regions"]:
            missing = required - r.keys()
            assert not missing, f"{r['region_level2']} 누락 필드: {missing}"

    def test_cortar_no_format(self):
        import json
        from pathlib import Path
        data = json.loads(
            (Path(__file__).parent.parent / "data" / "regions.json")
            .read_text(encoding="utf-8")
        )
        for r in data["regions"]:
            cortar_no = r["cortar_no"]
            assert len(cortar_no) == 10, f"{r['region_level2']} cortarNo 길이 오류: {cortar_no}"
            assert cortar_no.isdigit(), f"{r['region_level2']} cortarNo 숫자 아님: {cortar_no}"

    def test_seoul_has_25_districts(self):
        import json
        from pathlib import Path
        data = json.loads(
            (Path(__file__).parent.parent / "data" / "regions.json")
            .read_text(encoding="utf-8")
        )
        seoul = [r for r in data["regions"] if r["region_level1"] == "서울특별시"]
        assert len(seoul) == 25, f"서울 자치구 수: {len(seoul)} (기대: 25)"

    def test_coordinates_in_valid_range(self):
        import json
        from pathlib import Path
        data = json.loads(
            (Path(__file__).parent.parent / "data" / "regions.json")
            .read_text(encoding="utf-8")
        )
        for r in data["regions"]:
            lat = r["center_lat"]
            lng = r["center_lng"]
            assert 35.0 <= lat <= 39.0, f"{r['region_level2']} 위도 범위 오류: {lat}"
            assert 125.0 <= lng <= 130.0, f"{r['region_level2']} 경도 범위 오류: {lng}"
