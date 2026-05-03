# ARD: 수도권 아파트 잔여 매물 자동 수집 및 시각화 시스템

**작성일:** 2026-05-03  
**상태:** In Progress  
**담당:** aquas

---

## 1. 목표 및 범위

### 목표
수도권 아파트 매매/전세/월세 잔여 매물 건수를 매일 자동 수집하여 시계열 데이터를 구축하고, 대시보드로 시각화한다.

### 수집 대상 지역 (수도권)
| 광역 | 포함 시/군 |
|------|-----------|
| 서울특별시 | 25개 자치구 전체 |
| 경기도 | 수원, 성남, 고양, 용인, 부천, 안산, 안양, 남양주, 화성, 평택, 의정부, 시흥, 파주, 광명, 김포, 군포, 광주, 이천, 양주, 오산, 구리, 안성, 포천, 의왕, 하남, 여주, 양평, 동두천, 과천, 가평, 연천 |
| 인천광역시 | 8개 군·구 전체 |

### 수집 항목
- 거래 유형: 매매 / 전세 / 월세
- 지표: 잔여 매물 건수 (기준시점 기준 활성 매물 수)
- 수집 단위: 시/구 레벨

### 범위 외
- 오피스텔, 빌라, 단독주택 (아파트만 대상)
- 실거래가 데이터 (잔여 매물 건수만 대상)
- 해외 또는 수도권 외 지역

---

## 2. 아키텍처 다이어그램

```
┌──────────────────────────────────────────────────────────────┐
│                    GitHub Actions (cron)                      │
│                  매일 UTC 19:00 (KST 04:00)                   │
└────────────────────────┬─────────────────────────────────────┘
                         │ trigger
                         ▼
┌──────────────────────────────────────────────────────────────┐
│               Python Scraper (collect.py)                     │
│                                                              │
│  ┌─────────────────────────┐   ┌──────────────────────────┐  │
│  │  직방 비공식 API (Primary) │   │  네이버부동산 (Fallback)   │  │
│  │  - /v2/items/           │   │  - 랜드마크 API           │  │
│  │  - /v2/complex/         │   │  - 지역별 매물 조회        │  │
│  └────────────┬────────────┘   └─────────────┬────────────┘  │
│               └──────────────┬───────────────┘               │
│                              ▼                               │
│                    Data Transformer                          │
│              (정규화 / 유효성 검사 / 집계)                       │
└────────────────────────┬─────────────────────────────────────┘
                         │ append rows
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                   Google Sheets                               │
│                                                              │
│   Sheet: raw_data          Sheet: summary                    │
│   (수집 원본 로그)             (지역×거래유형 피벗)               │
└────────────────────────┬─────────────────────────────────────┘
                         │ read via MCP
                         ▼
┌──────────────────────────────────────────────────────────────┐
│            Claude + Anthropic API + Google Sheets MCP        │
│                                                              │
│   - 데이터 조회 및 분석                                         │
│   - Claude 아티팩트 대시보드 생성                                │
│     (시계열 차트 / 지역별 히트맵 / 거래유형 비교)                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 데이터 스키마

### Sheet 1: `raw_data` (수집 원본)

| 컬럼명 | 타입 | 예시 | 설명 |
|--------|------|------|------|
| `collected_at` | DATETIME | 2026-05-03 04:01:23 | 수집 시각 (KST) |
| `date` | DATE | 2026-05-03 | 수집 날짜 (KST) |
| `region_level1` | STRING | 서울특별시 | 광역 시/도 |
| `region_level2` | STRING | 강남구 | 시/군/구 |
| `trade_type` | STRING | 매매 \| 전세 \| 월세 | 거래 유형 |
| `listing_count` | INTEGER | 1432 | 잔여 매물 건수 |
| `source` | STRING | zigbang \| naver | 데이터 출처 |
| `status` | STRING | ok \| error | 수집 상태 |
| `error_msg` | STRING | (nullable) | 오류 메시지 |

### Sheet 2: `summary` (일별 지역 요약)

| 컬럼명 | 타입 | 예시 | 설명 |
|--------|------|------|------|
| `date` | DATE | 2026-05-03 | 날짜 |
| `region_level1` | STRING | 경기도 | 광역 시/도 |
| `region_level2` | STRING | 수원시 | 시/군/구 |
| `sale_count` | INTEGER | 2341 | 매매 매물 수 |
| `jeonse_count` | INTEGER | 1102 | 전세 매물 수 |
| `monthly_count` | INTEGER | 487 | 월세 매물 수 |
| `total_count` | INTEGER | 3930 | 전체 매물 수 |

### Sheet 3: `run_log` (실행 로그)

| 컬럼명 | 타입 | 예시 | 설명 |
|--------|------|------|------|
| `run_at` | DATETIME | 2026-05-03 04:00:00 | 실행 시각 (KST) |
| `status` | STRING | success \| partial \| failed | 전체 실행 상태 |
| `total_rows` | INTEGER | 183 | 수집된 행 수 |
| `error_count` | INTEGER | 2 | 오류 발생 건수 |
| `source_used` | STRING | zigbang | 주 데이터 소스 |
| `duration_sec` | FLOAT | 47.3 | 실행 소요 시간(초) |

---

## 4. Phase별 작업 목록

### Phase 1: 스크래퍼 개발 (현재)
- [ ] 직방 비공식 API 분석 및 수집 모듈 구현 (`scrapers/zigbang.py`)
- [ ] 네이버부동산 fallback 수집 모듈 구현 (`scrapers/naver.py`)
- [ ] 데이터 정규화 및 집계 로직 (`transform.py`)
- [ ] 수도권 지역 코드 매핑 테이블 (`data/regions.json`)
- [ ] 단위 테스트 (`tests/`)
- [ ] 로컬 실행 검증 (CSV 출력)

### Phase 2: Google Sheets 연동
- [ ] Google Sheets API 인증 설정 (Service Account)
- [ ] Sheets 스키마 초기화 스크립트 (`setup_sheets.py`)
- [ ] `raw_data` / `summary` / `run_log` 적재 모듈 (`writer.py`)
- [ ] 중복 날짜 upsert 로직 (재실행 안전성)
- [ ] 연동 E2E 테스트

### Phase 3: GitHub Actions 자동화
- [ ] `collect.yml` workflow 작성 (cron: `0 19 * * *`)
- [ ] Secrets 설정 (Google SA JSON, Sheets ID)
- [ ] 실패 시 알림 (GitHub Actions 이메일 또는 Slack webhook)
- [ ] 수동 트리거(`workflow_dispatch`) 지원
- [ ] 실행 로그 아카이빙

### Phase 4: Claude 대시보드 시각화
- [ ] Google Sheets MCP 연동 설정
- [ ] 시계열 트렌드 차트 (지역별 매물 추이)
- [ ] 지역별 히트맵 (현재 매물 밀도)
- [ ] 거래유형별 비교 차트
- [ ] 대시보드 프롬프트 템플릿 작성
- [ ] 아티팩트 HTML/React 컴포넌트 완성

---

## 5. 파일/디렉토리 구조

```
estate_count_search/
├── ARD.md                      # 이 문서
├── README.md                   # 프로젝트 소개 및 실행 방법
├── pyproject.toml              # Python 프로젝트 메타데이터 및 의존성
├── .env.example                # 환경변수 템플릿
│
├── data/
│   └── regions.json            # 수도권 지역 코드 매핑 (zigbang / naver 코드)
│
├── scrapers/
│   ├── __init__.py
│   ├── zigbang.py              # 직방 비공식 API 수집 모듈
│   └── naver.py                # 네이버부동산 fallback 수집 모듈
│
├── collect.py                  # 메인 수집 진입점 (CLI)
├── transform.py                # 데이터 정규화 / 집계
├── writer.py                   # Google Sheets 적재
├── setup_sheets.py             # Sheets 초기 스키마 생성
│
├── tests/
│   ├── test_zigbang.py
│   ├── test_naver.py
│   └── test_transform.py
│
└── .github/
    └── workflows/
        └── collect.yml         # GitHub Actions cron 워크플로우
```

---

## 6. 리스크 및 대응방안

| # | 리스크 | 가능성 | 영향 | 대응방안 |
|---|--------|--------|------|----------|
| R1 | 직방 API 스펙 변경 / 차단 | 중 | 高 | 네이버부동산 fallback 즉시 전환, User-Agent 로테이션 |
| R2 | 네이버부동산 IP 차단 | 중 | 高 | GitHub Actions IP 범위 다양화, 요청 간격 랜덤화 |
| R3 | Google Sheets API 할당량 초과 | 낮 | 中 | 배치 쓰기(batchUpdate), 일일 1회 수집으로 최소화 |
| R4 | GitHub Actions 무료 플랜 한도 | 낮 | 低 | 월 2,000분 이내 유지 (1회 실행 ~5분 예상) |
| R5 | 지역 코드 매핑 불일치 | 중 | 中 | regions.json 버전 관리, 수집 시 미매핑 지역 경고 로그 |
| R6 | 수집 중 부분 실패 | 중 | 中 | 지역별 독립 try/except, 부분 성공 시 수집된 데이터 저장 후 run_log에 error_count 기록 |

---

## 7. 완료 기준 (Definition of Done)

### Phase 1
- [ ] 수도권 전체 지역 + 3개 거래유형 = 183건 이상 행 정상 수집
- [ ] CSV 출력 파일로 스키마 검증 통과
- [ ] 단위 테스트 통과율 100%

### Phase 2
- [ ] Google Sheets `raw_data` 시트에 수집 데이터 자동 적재 확인
- [ ] `summary` 시트 피벗 데이터 정확성 검증
- [ ] 같은 날짜 재실행 시 중복 없이 upsert 동작

### Phase 3
- [ ] GitHub Actions cron 5회 연속 성공 실행
- [ ] 실패 시 알림 수신 확인
- [ ] Secrets 노출 없이 안전하게 인증 동작

### Phase 4
- [ ] 30일 이상 누적 데이터로 시계열 차트 렌더링 성공
- [ ] Claude 아티팩트에서 지역 필터링 인터랙션 동작
- [ ] 대시보드 프롬프트 1회 실행으로 최신 데이터 시각화 완료

---

## 부록: 주요 API 참고

### 직방 비공식 API (탐색 필요)
- Base URL: `https://apis.zigbang.com`
- 매물 목록: `GET /v2/items/list` (추정)
- 인증: 불필요 (공개 API)

### 네이버부동산 (Fallback)
- Base URL: `https://land.naver.com`
- 지역 코드 기반 매물 조회

### Google Sheets API
- 인증: Service Account (JSON 키)
- 스코프: `https://www.googleapis.com/auth/spreadsheets`
