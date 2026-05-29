"""라이브 대시보드 첫 페이지 자동 캡쳐 — README 미리보기용.

비밀번호 게이트 통과 후 메인 대시보드 상단 영역(헤더 + 7개 기관 카드 + KPI strip + 검색바)
스크린샷을 docs/dashboard_preview.png 로 저장.

사용:
    python -m playwright install chromium     # 최초 1회
    python scripts/capture_dashboard.py

향후 UI 변경 시 재실행하면 README 이미지 자동 갱신.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://yellowcornsalad.github.io/RFP-Targeter/"
PASSWORD = "enki2026"
# README 의 ![Dashboard](docs/screenshots/dashboard.png) 가 참조하는 경로
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots" / "dashboard.png"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,  # retina 품질
            locale="ko-KR",
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")

        # 비밀번호 게이트 처리
        try:
            page.fill("#auth-pw", PASSWORD, timeout=5000)
            page.click("#auth-btn")
            page.wait_for_selector("#agency-grid", timeout=10000)
        except Exception:
            # 이미 인증된 세션이거나 게이트 없음 — 그대로 진행
            pass

        # 데이터 로드 완료 대기 (카드 1개 이상 렌더링)
        page.wait_for_selector("#cards .card, .agency-card", timeout=15000)
        page.wait_for_timeout(800)  # 차트/스타일 안정화

        # 상단 viewport 만 캡쳐 (full_page=False)
        page.screenshot(path=str(OUT), full_page=False)
        browser.close()
    print(f"[OK] saved: {OUT}")
    print(f"     size: {OUT.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
