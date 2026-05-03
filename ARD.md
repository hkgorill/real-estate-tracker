# ARD: 수도권 부동산 시장 지표 자동 수집 시스템

**작성일:** 2026-05-03  
**상태:** In Progress  
**담당:** aquas

---

## 1. 목표 및 범위

### 목표
수도권 아파트 시장의 가격 향방을 예측하기 위한 핵심 지표를 자동 수집·적재하여 시계열 데이터를 구축한다.

### 수집 지표 (4종)

| 소스 | 지표 | 수집 주기 | 단위 |
|------|------|---------|------|
| **한국부동산원 R-ONE** | 아파트 매매·전세 가격지수 | 주간 | 전국/수도권/시도 |
| **한국부동산원 R-ONE** | 아파트 전세가율 | 주간 | 전국/수도권/시도 |
| **한국은행 ECOS** | 기준금리, 주택담보대출 금리 | 월간 | 전국 |
| **국토교통부 MOLIT** | 아파트 매매 실거래가 | 월간 | 수도권 66개 시군구 |
| **국토교통부 MOLIT** | 미분양주택 현황 | 월간 | 시도 (서울/경기/인천) |

### 수도권 대상 지역
- 서울특별시 25개 자치구
- 경기도 37개 시군구
- 인천광역시 10개 구군

### 지표 선정 근거 (예측력 있는 선행지표)

```
전세가율(주간)    → 실수요자 매수전환 압력 신호. 전세가↑ → 매매수요↑ → 가격 선행 상승
거래량(실거래가)  → 가격 변화 1~3개월 선행. 거래량 증가 후 가격 상승 패턴
금리             → 구매력 직접 영향. 기준금리↑ → 주담대↑ → 수요 감소 → 가격 하방 압력
미분양           → 공급 과잉 신호. 미분양↑ → 신규 공급 압박 → 가격 하락 압력
가격지수         → 주간 단위 가격 변동 추이 직접 관측
```

---

## 2. 아키텍처

```
┌──────────────────────────────────────────────────────┐
│              GitHub Actions (매일 KST 04:00)           │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│                 collect.py (CLI)                       │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ R-ONE    │  │ ECOS     │  │ MOLIT            │   │
│  │ rbone.py │  │ ecos.py  │  │ molit.py         │   │
│  │ 가격지수  │  │ 기준금리 │  │ 실거래가 + 미분양 │   │
│  │ 전세가율  │  │ 주담대율 │  │                  │   │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘   │
│       └──────────────┴────────────────┘             │
│                       ▼                             │
│               transform.py (정규화)                   │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│                 Google Sheets                          │
│                                                      │
│  price_index │ jeonse_ratio │ interest_rate          │
│  apt_trade   │ unsold       │ run_log                │
└──────────────────────────────────────────────────────┘
```

---

## 3. 데이터 스키마

### Sheet 1: `price_index` (R-ONE 주간 가격지수)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| collected_at | DATETIME | 2025-05-03 04:00:00 |
| period | STRING | 202518 (2025년 18주차) |
| region | STRING | 서울특별시 |
| sale_index | FLOAT | 105.2 |
| jeonse_index | FLOAT | 103.0 |
| source | STRING | rbone |

### Sheet 2: `jeonse_ratio` (R-ONE 주간 전세가율)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| collected_at | DATETIME | 2025-05-03 04:00:00 |
| period | STRING | 202518 |
| region | STRING | 서울특별시 |
| jeonse_ratio | FLOAT | 55.2 (%) |
| source | STRING | rbone |

### Sheet 3: `interest_rate` (ECOS 월간 금리)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| collected_at | DATETIME | 2025-05-03 04:00:00 |
| period | STRING | 202503 |
| base_rate | FLOAT | 2.75 (%) |
| mortgage_rate | FLOAT | 4.10 (%) |
| source | STRING | ecos |

### Sheet 4: `apt_trade` (MOLIT 월간 실거래가)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| collected_at | DATETIME | 2025-05-03 04:00:00 |
| deal_ym | STRING | 202503 |
| deal_date | DATE | 2025-03-15 |
| region_level1 | STRING | 서울특별시 |
| region_level2 | STRING | 강남구 |
| dong | STRING | 역삼동 |
| apt_name | STRING | 래미안역삼 |
| area_sqm | FLOAT | 84.98 |
| floor | INTEGER | 12 |
| price_manwon | INTEGER | 85000 (만원) |
| build_year | INTEGER | 2010 |
| source | STRING | molit_trade |

### Sheet 5: `unsold` (MOLIT 월간 미분양)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| collected_at | DATETIME | 2025-05-03 04:00:00 |
| deal_ym | STRING | 202503 |
| region_level1 | STRING | 서울특별시 |
| unsold_total | INTEGER | 1234 |
| unsold_before | INTEGER | 800 (준공 전) |
| unsold_after | INTEGER | 434 (준공 후 악성) |
| source | STRING | molit_unsold |

### Sheet 6: `run_log` (실행 이력)

| 컬럼 | 타입 | 예시 |
|------|------|------|
| run_at | DATETIME | 2025-05-03 04:00:00 |
| status | STRING | success \| partial \| failed |
| total_rows | INTEGER | 1523 |
| error_count | INTEGER | 0 |
| sources_used | STRING | rbone,ecos,molit |
| duration_sec | FLOAT | 142.3 |

---

## 4. 파일 구조

```
estate_count_search/
├── ARD.md
├── README.md
├── requirements.txt
├── .env.example
│
├── data/
│   └── regions.json          # 수도권 66개 시군구 lawd_cd (MOLIT용)
│
├── scrapers/
│   ├── __init__.py
│   ├── rbone.py              # R-ONE 가격지수/전세가율
│   ├── ecos.py               # ECOS 금리
│   └── molit.py              # MOLIT 실거래가/미분양
│
├── collect.py                # 메인 수집 CLI
├── transform.py              # 데이터 정규화 (5종 Row 모델)
├── writer.py                 # Google Sheets 적재 (6시트)
├── setup_sheets.py           # Sheets 초기 스키마 생성
├── auth.py                   # Google 인증 (ADC/WIF)
│
├── tests/
│   ├── test_molit.py
│   ├── test_ecos.py
│   ├── test_rbone.py
│   └── test_transform.py
│
├── docs/
│   ├── api_key_setup.md      # API 키 발급 가이드
│   └── setup_workload_identity.md
│
└── .github/workflows/
    └── collect.yml
```

---

## 5. API 키 및 환경변수

| 환경변수 | 용도 | 발급처 |
|---------|------|--------|
| `DATA_GO_KR_API_KEY` | MOLIT 실거래가/미분양 | data.go.kr |
| `ECOS_API_KEY` | 한국은행 금리 | ecos.bok.or.kr |
| `RBONE_API_KEY` | 부동산원 가격지수 | reb.or.kr/r-one |
| `GOOGLE_SHEETS_ID` | 스프레드시트 ID | Google Sheets URL |
| `RBONE_SALE_IDX_CODE` | R-ONE 매매지수 통계코드 | R-ONE 포털 확인 |
| `RBONE_JEONSE_IDX_CODE` | R-ONE 전세지수 통계코드 | R-ONE 포털 확인 |
| `RBONE_JEONSE_RATIO_CODE` | R-ONE 전세가율 통계코드 | R-ONE 포털 확인 |

→ 상세 발급 절차: `docs/api_key_setup.md`

---

## 6. 실행 방법

```bash
# 전체 수집 (R-ONE + ECOS + MOLIT)
python collect.py

# 소스별 단독 실행
python collect.py --source rbone
python collect.py --source ecos
python collect.py --source molit --deal-ym 202503

# 지역 필터 (MOLIT)
python collect.py --source molit --region 강남구 --no-sheets --csv

# 수집 계획 확인
python collect.py --dry-run
```

---

## 7. Phase별 작업 현황

### ✅ Phase 1-3 완료
- [x] 스크래퍼 3종 구현 (rbone, ecos, molit)
- [x] transform / writer 구현 (5시트 스키마)
- [x] collect.py CLI 구현
- [x] Google Sheets 연동 (setup_sheets, auth)
- [x] GitHub Actions 워크플로
- [x] 테스트 31/31 통과
- [x] API 키 발급 가이드

### 🔲 Phase 4: 대시보드 시각화
- [ ] Google Sheets MCP 연동
- [ ] 전세가율 추이 차트 (지역별, 시계열)
- [ ] 금리-가격 상관관계 차트
- [ ] 실거래가 분포 히스토그램 (강남구 등 주요 지역)
- [ ] Claude 아티팩트 대시보드 프롬프트 작성

---

## 8. 리스크

| # | 리스크 | 대응 |
|---|--------|------|
| R1 | R-ONE 통계코드 미확인 | 포털 로그인 후 코드 확인 필수, `RBONE_*_CODE` 환경변수로 유연하게 설정 |
| R2 | MOLIT 미분양 API 엔드포인트 변경 | 응답 구조 변경 시 `scrapers/molit.py` `UNSOLD_URL` 수정 |
| R3 | 공공 API 일시 장애 | 소스별 독립 try/except, 부분 성공 시 run_log에 error_count 기록 |
| R4 | GitHub Actions 무료 플랜 한도 | 월 2,000분 이내 유지 (1회 실행 ~3분 예상) |
