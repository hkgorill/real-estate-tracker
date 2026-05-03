"""
MOLIT 스크래퍼 단위 테스트.

실제 API 호출 없이 XML 파싱 로직과 데이터 변환을 검증한다.
"""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

from scrapers.molit import MolitScraper, AptTradeItem, UnsoldItem


SAMPLE_TRADE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
  <body>
    <items>
      <item>
        <거래금액>  85,000</거래금액>
        <건축년도>2010</건축년도>
        <년>2025</년>
        <법정동>역삼동</법정동>
        <아파트>래미안역삼</아파트>
        <월>3</월>
        <일>15</일>
        <전용면적>84.98</전용면적>
        <층>12</층>
      </item>
      <item>
        <거래금액> 120,000</거래금액>
        <건축년도>2018</건축년도>
        <년>2025</년>
        <법정동>삼성동</법정동>
        <아파트>아이파크삼성</아파트>
        <월>3</월>
        <일>22</일>
        <전용면적>130.50</전용면적>
        <층>25</층>
      </item>
    </items>
    <totalCount>2</totalCount>
  </body>
</response>"""

SAMPLE_UNSOLD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
  <body>
    <items>
      <item>
        <시도명>서울특별시</시도명>
        <미분양합계>1234</미분양합계>
        <준공전>800</준공전>
        <준공후>434</준공후>
      </item>
      <item>
        <시도명>경기도</시도명>
        <미분양합계>5678</미분양합계>
        <준공전>4000</준공전>
        <준공후>1678</준공후>
      </item>
      <item>
        <시도명>부산광역시</시도명>
        <미분양합계>999</미분양합계>
        <준공전>600</준공전>
        <준공후>399</준공후>
      </item>
    </items>
    <totalCount>3</totalCount>
  </body>
</response>"""


def make_scraper() -> MolitScraper:
    return MolitScraper(api_key="test_key", request_delay_min=0, request_delay_max=0)


class TestAptTradeXmlParsing:
    def test_parse_price(self):
        sc = make_scraper()
        root = ET.fromstring(SAMPLE_TRADE_XML)
        items = root.findall(".//item")
        price = sc._parse_int(items[0].findtext("거래금액"))
        assert price == 85000

    def test_parse_area(self):
        sc = make_scraper()
        root = ET.fromstring(SAMPLE_TRADE_XML)
        items = root.findall(".//item")
        area = sc._parse_float(items[1].findtext("전용면적"))
        assert area == pytest.approx(130.50)

    def test_parse_floor(self):
        sc = make_scraper()
        root = ET.fromstring(SAMPLE_TRADE_XML)
        items = root.findall(".//item")
        floor = sc._parse_int(items[1].findtext("층"))
        assert floor == 25

    def test_parse_build_year(self):
        sc = make_scraper()
        root = ET.fromstring(SAMPLE_TRADE_XML)
        items = root.findall(".//item")
        year = sc._parse_int(items[0].findtext("건축년도"))
        assert year == 2010


class TestGetAptTrades:
    def test_returns_two_items(self):
        sc = make_scraper()
        with patch.object(sc, "_get_xml", return_value=ET.fromstring(SAMPLE_TRADE_XML)):
            results = sc.get_apt_trades("서울특별시", "강남구", "11680", "202503")
        assert len(results) == 2

    def test_item_fields(self):
        sc = make_scraper()
        with patch.object(sc, "_get_xml", return_value=ET.fromstring(SAMPLE_TRADE_XML)):
            results = sc.get_apt_trades("서울특별시", "강남구", "11680", "202503")
        item = results[0]
        assert item.apt_name == "래미안역삼"
        assert item.price_manwon == 85000
        assert item.floor == 12
        assert item.dong == "역삼동"
        assert item.region_level2 == "강남구"
        assert item.deal_ym == "202503"
        assert item.source == "molit_trade"


class TestGetUnsold:
    def test_filters_to_sudogwon(self):
        sc = make_scraper()
        with patch.object(sc, "_get_xml", return_value=ET.fromstring(SAMPLE_UNSOLD_XML)):
            results = sc.get_unsold("202503")
        # 부산은 제외, 서울+경기만 반환
        assert len(results) == 2
        regions = {r.region_level1 for r in results}
        assert regions == {"서울특별시", "경기도"}

    def test_unsold_values(self):
        sc = make_scraper()
        with patch.object(sc, "_get_xml", return_value=ET.fromstring(SAMPLE_UNSOLD_XML)):
            results = sc.get_unsold("202503")
        seoul = next(r for r in results if r.region_level1 == "서울특별시")
        assert seoul.unsold_total == 1234
        assert seoul.unsold_before == 800
        assert seoul.unsold_after == 434
        assert seoul.deal_ym == "202503"
        assert seoul.source == "molit_unsold"

    def test_api_error_raises(self):
        error_xml = """<response>
          <header><resultCode>99</resultCode><resultMsg>SERVICE_ERROR</resultMsg></header>
        </response>"""
        sc = make_scraper()
        with patch.object(sc, "_get_xml", side_effect=RuntimeError("API 오류 99")):
            results = sc.get_unsold("202503")
        assert results == []
