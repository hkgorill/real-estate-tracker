"""
API 응답 구조 진단 스크립트.

직방/네이버 API의 실제 응답 형식을 확인하여 파라미터 오류를 디버깅합니다.

사용:
  python debug_api.py           # 직방 + 네이버 모두 확인
  python debug_api.py --zigbang
  python debug_api.py --naver
"""

import argparse
import json
import sys
import httpx

# 강남구 기준으로 테스트
REGION = {
    "region_level1": "서울특별시",
    "region_level2": "강남구",
    "cortar_no": "1123000000",
    "center_lat": 37.5172,
    "center_lng": 127.0473,
}


# ── 직방 ──────────────────────────────────────────────────────────────────────

def debug_zigbang():
    import geohash2
    geohash = geohash2.encode(REGION["center_lat"], REGION["center_lng"], precision=5)
    print(f"\n{'='*60}")
    print(f"[직방] geohash={geohash}")
    print(f"{'='*60}")

    base_params = {
        "domain": "zigbang",
        "checkAnyItemWithoutFilter": "true",
        "geohash": geohash,
        "needSummary": "true",
        "isMapView": "false",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://www.zigbang.com",
        "Referer": "https://www.zigbang.com/",
    }

    # 테스트할 파라미터 조합
    variants = [
        {"tradetype": "SALE",                         "label": "v3/items tradetype=SALE"},
        {"tradetype": "SALE", "serviceType": "아파트",  "label": "v3/items tradetype=SALE serviceType=아파트"},
        {"tradetype": "SALE", "serviceType": "apt",    "label": "v3/items tradetype=SALE serviceType=apt"},
        {"tradetype": "SALE", "itemType": "아파트",     "label": "v3/items tradetype=SALE itemType=아파트"},
    ]

    for v in variants:
        label = v.pop("label")
        params = {**base_params, **v}
        try:
            resp = httpx.get(
                "https://apis.zigbang.com/v3/items",
                params=params, headers=headers, timeout=10
            )
            data = resp.json()
            items = data.get("items", [])
            item_count = len(items) if isinstance(items, list) else "dict형식"
            print(f"\n[{label}]")
            print(f"  status: {resp.status_code}")
            print(f"  items: {item_count}")
            print(f"  keys: {list(data.keys())}")
            if isinstance(items, dict):
                print(f"  items 구조: {list(items.keys())[:5]}")
            elif items:
                print(f"  첫 번째 item 키: {list(items[0].keys())[:8]}")
        except Exception as e:
            print(f"\n[{label}] 오류: {e}")

    # 직방 아파트 전용 엔드포인트 탐색
    extra_tests = [
        {
            "label": "v2/items/list (POST)",
            "method": "POST",
            "url": "https://apis.zigbang.com/v2/items/list",
            "json": {
                "domain": "zigbang", "geohash": geohash,
                "needSummary": True, "isMapView": False,
                "tradetype": "SALE", "serviceType": "아파트",
            },
        },
        {
            "label": "property/apartments by cortarNo",
            "method": "GET",
            "url": "https://apis.zigbang.com/property/apartments",
            "params": {"cortarNo": REGION["cortar_no"], "tradetype": "SALE", "page": 1},
        },
        {
            "label": "v2/search (주소 → OID 탐색)",
            "method": "GET",
            "url": "https://apis.zigbang.com/v2/search",
            "params": {"q": "강남구", "type": "address"},
        },
        {
            "label": "v3/items precision=4 geohash",
            "method": "GET",
            "url": "https://apis.zigbang.com/v3/items",
            "params": {
                "domain": "zigbang",
                "checkAnyItemWithoutFilter": "true",
                "geohash": geohash[:4],  # 더 넓은 범위
                "needSummary": "true",
                "tradetype": "SALE",
            },
        },
    ]
    for t in extra_tests:
        print(f"\n[{t['label']}]")
        try:
            if t.get("method") == "POST":
                resp = httpx.post(t["url"], json=t.get("json"), headers=headers, timeout=10)
            else:
                resp = httpx.get(t["url"], params=t.get("params"), headers=headers, timeout=10)
            print(f"  status: {resp.status_code}")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    items = data.get("items", [])
                    print(f"  keys: {list(data.keys())}")
                    print(f"  items 수: {len(items) if isinstance(items, list) else type(items).__name__}")
                    if isinstance(items, list) and items:
                        print(f"  첫 item 키: {list(items[0].keys())[:8]}")
                    print(f"  raw(200자): {resp.text[:200]}")
                except Exception:
                    print(f"  raw(300자): {resp.text[:300]}")
            else:
                print(f"  raw: {resp.text[:200]}")
        except Exception as e:
            print(f"  오류: {e}")


# ── 네이버 ────────────────────────────────────────────────────────────────────

def debug_naver():
    print(f"\n{'='*60}")
    print(f"[네이버 부동산] cortarNo={REGION['cortar_no']}")
    print(f"{'='*60}")

    headers_desktop = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://new.land.naver.com/",
    }
    headers_mobile = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://m.land.naver.com/",
        "X-Requested-With": "XMLHttpRequest",
    }

    tests = [
        {
            "label": "new API /api/articles",
            "url": "https://new.land.naver.com/api/articles",
            "params": {
                "cortarNo": REGION["cortar_no"],
                "realEstateType": "APT",
                "tradeType": "A1",
                "page": 1, "perPage": 1,
            },
            "headers": headers_desktop,
        },
        {
            "label": "new API /api/articles (tradTpCd)",
            "url": "https://new.land.naver.com/api/articles",
            "params": {
                "cortarNo": REGION["cortar_no"],
                "rletTypeCd": "A01",
                "tradTpCd": "A1",
                "page": 1, "pageSize": 1,
            },
            "headers": headers_desktop,
        },
        {
            "label": "mobile API articleList",
            "url": "https://m.land.naver.com/cluster/ajax/articleList",
            "params": {
                "rletTypeCd": "A01",
                "tradTpCd": "A1",
                "cortarNo": REGION["cortar_no"],
                "z": 12,
                "lat": REGION["center_lat"],
                "lng": REGION["center_lng"],
                "btm": REGION["center_lat"] - 0.08,
                "lft": REGION["center_lng"] - 0.10,
                "top": REGION["center_lat"] + 0.08,
                "rgt": REGION["center_lng"] + 0.10,
                "sort": "rank",
            },
            "headers": headers_mobile,
        },
        {
            "label": "new API /api/regions/complexes (아파트 단지 수 확인용)",
            "url": "https://new.land.naver.com/api/regions/complexes",
            "params": {
                "cortarNo": REGION["cortar_no"],
                "realEstateType": "APT",
                "order": "",
            },
            "headers": headers_desktop,
        },
    ]

    import time
    for t in tests:
        print(f"\n[{t['label']}]")
        try:
            resp = httpx.get(t["url"], params=t["params"], headers=t["headers"], timeout=12)
            print(f"  status: {resp.status_code}")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    print(f"  keys: {list(data.keys())[:10]}")
                    total = (
                        data.get("totalCount")
                        or data.get("total")
                        or (data.get("body") or {}).get("totalCount")
                        or (data.get("result") or {}).get("totalCount")
                    )
                    print(f"  totalCount 후보: {total}")
                    print(f"  raw(400자): {resp.text[:400]}")
                except Exception:
                    print(f"  (JSON 파싱 실패) raw(400자): {resp.text[:400]}")
            else:
                print(f"  raw: {resp.text[:200]}")
        except Exception as e:
            print(f"  오류: {e}")
        time.sleep(1.5)  # rate limit 방지


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--zigbang", action="store_true")
    parser.add_argument("--naver", action="store_true")
    args = parser.parse_args()

    run_all = not args.zigbang and not args.naver
    if args.zigbang or run_all:
        debug_zigbang()
    if args.naver or run_all:
        debug_naver()

    print("\n" + "="*60)
    print("진단 완료. 위 출력에서 totalCount > 0 인 응답을 scraper에 반영하세요.")
