# 수도권 부동산 시장 지표 자동 수집 — 개발 진행 내역

> 작성일: 2026-05-04  
> 저장소: https://github.com/hkgorill/real-estate-tracker

---

## 프로젝트 개요

수도권 부동산 시장의 주요 지표를 공식 API에서 자동 수집하여 Google Sheets에 적재하는 시스템.  
GitHub Actions로 주 1회(매주 월요일) 자동 실행.

### 데이터 소스 (4종)

| 소스 | 제공 데이터 | 주기 | API 키 |
|------|------------|------|--------|
| R-ONE (한국부동산원) | 아파트 매매·전세 가격지수 | 주간 | `RBONE_API_KEY` |
| ECOS (한국은행) | 기준금리, 주택담보대출금리 | 월간 | `ECOS_API_KEY` |
| MOLIT 실거래가 (국토부) | 아파트 매매 실거래 상세 | 월간 | `DATA_GO_KR_API_KEY` |
| MOLIT 미분양 (국토부) | 시도별 미분양주택 현황 | 월간 | `DATA_GO_KR_API_KEY` |

### Google Sheets 스키마 (5개 시트)

| 시트명 | 주요 컬럼 |
|--------|----------|
| `price_index` | period(YYYYWW), region, sale_index, jeonse_index, jeonse_idx_ratio |
| `interest_rate` | period(YYYYMM), base_rate, mortgage_rate |
| `apt_trade` | deal_date, region, apt_name, area_sqm, floor, price_manwon |
| `unsold` | period, region_level1, unsold_total, unsold_before, unsold_after |
| `run_log` | run_at, status, total_rows, error_count, sources_used, duration_sec |

---

## 개발 단계별 진행 내역

### Phase 1 — 초기 구축 (완료)

- **스크래퍼 구현**: 직방/네이버 부동산 웹 스크래핑 (매물 수 기반)
- **Sheets 연동**: Google Sheets API 인증 및 데이터 적재
- **GitHub Actions**: 자동화 워크플로 구성
- **테스트**: 29개 단위 테스트 통과

### Phase 2 — 공식 API 전환 (완료)

웹 스크래핑의 불안정성(HTML 구조 변경, 차단 위험)을 해소하기 위해  
전량 정부·공공기관 공식 OpenAPI로 전환.

#### 2-1. 데이터 소스 전환 (`80a2803`)

- 직방/네이버 스크래퍼 → R-ONE / ECOS / MOLIT API 스크래퍼로 교체
- `scrapers/rbone.py`, `scrapers/ecos.py`, `scrapers/molit.py` 신규 작성
- `transform.py`: 4종 데이터 → 5개 시트 스키마 정규화
- `writer.py`: Google Sheets 업서트(upsert) 로직
- `collect.py`: 전체 수집 파이프라인 메인 진입점

#### 2-2. jeonse_idx_ratio 파생 컬럼 통합 (`7327592`)

- 기존: `jeonse_ratio` 시트 별도 운영
- 변경: `price_index` 시트에 `jeonse_idx_ratio` 컬럼으로 통합
  - 산출 방식: `jeonse_index / sale_index × 100`
  - 주의: 절대값은 실제 전세가율과 다르나 추이 방향성은 일치
- `PriceIndexRow` 데이터클래스에 필드 추가 (7인자 생성자)

#### 2-3. README 전면 개편 (`4280913`)

- 프로젝트 구조, API 설정 방법, GitHub Secrets 목록 업데이트
- 5개 시트 스키마 및 CLI 사용법 문서화

#### 2-4. GitHub Actions 첫 실행 후 버그 수정

첫 실제 실행에서 3가지 오류 발견 및 수정:

**① MOLIT 결과코드 `000` 미처리** (`07316e0`)
```python
# 수정 전
if result_code not in ("00", "0000"):
# 수정 후
if result_code not in ("00", "000", "0000"):
```
MOLIT API가 성공 응답에 `"000"`을 반환하는데 오류로 처리되던 버그.

**② ECOS 데이터 공표 지연 처리** (`07316e0`)
```python
# 전월 데이터가 없으면 최대 4개월 전까지 소급 재시도
for attempt in range(4):
    rates = sc.get_interest_rates(target, target)
    if rates: break
    target = _prev_ym(target)
```
ECOS 월간 금리 데이터는 1~2개월 후 공표되므로 당월 조회 실패 시 소급.

**③ R-ONE API 엔드포인트 오류** (가장 큰 문제)  
→ 별도 섹션 참조.

---

### Phase 3 — R-ONE API 완전 재작성 (완료)

#### 문제 발견 경위

GitHub Actions 로그에서 R-ONE이 빈 응답 또는 `ERROR-310` 반환.  
`check_apis.py`로 디버깅한 결과 **엔드포인트 자체가 잘못됨**을 확인.

#### 기존 코드의 문제점

| 구분 | 기존 (잘못됨) | 올바른 값 |
|------|-------------|---------|
| 엔드포인트 | `SttsService.do` | `SttsApiTblData.do` |
| 통계코드 파라미터 | `statsCode` | `STATBL_ID` |
| 주기 파라미터 | `prdSe=W` | `DTACYCLE_CD=WK` |
| 기간 파라미터 | `startPrdDe` / `endPrdDe` | `WRTTIME_IDTFR_ID` (단일값) |
| 지역명 필드 | `regNm` | `CLS_NM` |
| 지수값 필드 | `wghtVal` | `DTA_VAL` |

#### R-ONE 엔드포인트 구조 (확인된 정보)

R-ONE OpenAPI는 3개의 독립 엔드포인트로 구성:
```
https://www.reb.or.kr/r-one/openapi/SttsApiTbl.do        # 통계표 목록
https://www.reb.or.kr/r-one/openapi/SttsApiTblItm.do     # 항목/지역 목록
https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do    # 실제 데이터
```

데이터 조회 파라미터:
```
apiKey           = {발급 API 키}
STATBL_ID        = T244183132827305   (매매가격지수)
                   T247713133046872   (전세가격지수)
DTACYCLE_CD      = WK                 (주간 고정)
WRTTIME_IDTFR_ID = 202518             (YYYYWW)
```

응답 XML 행 구조:
```xml
<row>
  <STATBL_ID>T244183132827305</STATBL_ID>
  <CLS_NM>전국</CLS_NM>       <!-- 지역명 -->
  <ITM_NM>지수</ITM_NM>       <!-- 항목명 (지수/변동률 등) -->
  <DTA_VAL>98.2771714576677</DTA_VAL>  <!-- 지수값 -->
  <WRTTIME_IDTFR_ID>202518</WRTTIME_IDTFR_ID>
  <WRTTIME_DESC>2025-04-28</WRTTIME_DESC>
</row>
```

#### 수정된 scrapers/rbone.py 핵심 로직

```python
def _fetch(self, statbl_id: str, period: str) -> list[dict]:
    params = {
        "apiKey":           self._api_key,
        "STATBL_ID":        statbl_id,
        "DTACYCLE_CD":      "WK",
        "WRTTIME_IDTFR_ID": period,
    }
    # XML 파싱 → INFO-200(데이터 없음) / ERROR-xxx 처리
    # 성공 시 <row> 목록 반환

def get_price_indices(self, period: str, regions=None) -> list[PriceIndexResult]:
    # CLS_NM → 지역명, DTA_VAL → 지수값
    def _region(row): return row.get("CLS_NM", "")
    def _val(row):
        for key in ("DTA_VAL", "WGHT_VAL", "DATA_VALUE"):
            if key in row and row[key]: return self._parse_float(row[key])
        return -1.0
```

#### 테스트 동기화

`tests/test_rbone.py` 전면 수정:
- 샘플 데이터: `regNm`/`wghtVal` → `CLS_NM`/`DTA_VAL`
- mock_fetch 시그니처: `(stats_code, prd_se, start, end)` → `(statbl_id, period)`
- `get_price_indices("202518", "202518")` → `get_price_indices("202518")`

---

## 현재 테스트 상태

```
37 passed in 44s
```

| 테스트 파일 | 항목 수 | 상태 |
|------------|--------|------|
| test_ecos.py | 6 | ✓ 전체 통과 |
| test_molit.py | 7 | ✓ 전체 통과 |
| test_rbone.py | 5 | ✓ 전체 통과 |
| test_transform.py | 11 | ✓ 전체 통과 |
| test_writer.py | 8 | ✓ 전체 통과 |

---

## GitHub Secrets 설정 목록

| Secret 이름 | 설명 |
|------------|------|
| `RBONE_API_KEY` | 한국부동산원 R-ONE API 키 |
| `RBONE_SALE_IDX_CODE` | 매매가격지수 통계표 ID (`T244183132827305`) |
| `RBONE_JEONSE_IDX_CODE` | 전세가격지수 통계표 ID (`T247713133046872`) |
| `ECOS_API_KEY` | 한국은행 ECOS API 키 |
| `DATA_GO_KR_API_KEY` | 공공데이터포털 API 키 (MOLIT) |
| `GOOGLE_SHEETS_ID` | 적재 대상 Google Sheets ID |
| `GCP_SA_KEY` | Google 서비스 계정 JSON (Workload Identity Federation 사용 시 불필요) |

---

## 남은 과제

- [ ] **ECOS API 키 활성화 확인**: 현재 과거 기간(202503)도 "데이터 없음" 반환 — 키 상태 재확인 필요
- [ ] **MOLIT 미분양 500 오류**: `UsrRtmsDataSvcUnsldRtclc` 서비스 별도 승인 필요 (data.go.kr)
- [ ] **R-ONE 데이터 미발표 주차 처리**: 현재 주차에 데이터가 없으면 전주 자동 소급하는 로직 추가 검토
- [ ] **R-ONE API 키 재발급**: 디버깅 중 브라우저 URL에 노출됨 — R-ONE 포털에서 재발급 권장
- [ ] **GitHub Actions 재실행**: 수정된 코드 push 후 실제 수집 결과 확인

---

## 파일 구조

```
estate_count_search/
├── scrapers/
│   ├── ecos.py          # 한국은행 ECOS API
│   ├── molit.py         # 국토부 실거래가·미분양 API
│   └── rbone.py         # R-ONE 가격지수 API (완전 재작성)
├── tests/
│   ├── test_ecos.py
│   ├── test_molit.py
│   ├── test_rbone.py    # 새 API 시그니처 반영
│   ├── test_transform.py
│   └── test_writer.py
├── data/
│   └── regions.json     # 수도권 시군구 LAWD_CD 목록
├── .github/workflows/
│   └── collect.yml      # GitHub Actions (매주 월요일)
├── auth.py              # Google 서비스 계정 인증
├── check_apis.py        # API 키·연결 검증 스크립트
├── collect.py           # 수집 메인 진입점
├── transform.py         # 데이터 정규화
└── writer.py            # Google Sheets 적재
```
