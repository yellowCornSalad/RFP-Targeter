"""IITP (data.go.kr API) 단발성 호출 + 검증.

키 활성화 지연 시 1~2시간 후 이 스크립트로 검증:
    python scripts/iitp_retry.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from urllib.parse import unquote

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfp_targeter.config import secrets  # noqa: E402


def main() -> int:
    sec = secrets().get("data_go_kr", {})
    key = sec.get("service_key")
    endpoint = sec.get("endpoint",
                       "https://apis.data.go.kr/1721000/msitannouncementinfo/businessAnnouncMentList")
    if not key or key == "???":
        print("[FAIL] secrets.yaml 의 service_key 미설정")
        return 1

    sk = unquote(key)
    params = {"serviceKey": sk, "pageNo": 1, "numOfRows": 5, "type": "json"}
    print(f"[..] GET {endpoint}")
    r = requests.get(endpoint, params=params, timeout=30)
    print(f"     status={r.status_code}  content-type={r.headers.get('content-type','')[:60]}")
    print(f"     body (first 1000 chars):\n{r.text[:1000]}")

    if r.status_code == 401:
        print("\n[STILL UNAUTHORIZED] 키 활성화 지연 또는 키 오류")
        print("- data.go.kr 발급 직후 1~24시간 활성화 지연 흔함")
        print("- 마이페이지 > 오픈API 에서 키 상태 확인")
        return 1
    if r.status_code != 200:
        print(f"\n[HTTP {r.status_code}] 비정상 응답")
        return 1

    # JSON 시도
    try:
        data = r.json()
        print("\n[OK] JSON parse success")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
    except Exception:
        print("\n[INFO] JSON parse 실패 - XML 가능성")

    print("\n[NEXT] 정상이면 다음 명령:")
    print("  python scripts/run_once.py")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
