"""IRIS (범부처 통합연구지원시스템) 사업공고 크롤러.

소스: https://www.iris.go.kr — 범부처 R&D 통합 플랫폼.
  · 과학기술정보통신부 · 산업통상부 · 중소벤처기업부 · 해양수산부
  · 행정안전부 · 국토교통부 · 환경부 · 농림축산식품부 등 모든 부처

목록 API (JSON, POST):
  /contents/retrieveBsnsAncmBtinSituList.do
  Request: form-encoded (pageIndex, ancmSttArr, pbofrTpArr, blngGovdSeArr, sorgnIdArr)
  Response: {listBsnsAncmBtinSitu: [...], paginationInfo: {...}}

상세 페이지:
  /contents/retrieveBsnsAncmView.do?ancmId={id}&ancmPrg=ancmPre

회사 관점: 기존 IITP(과기정통부 only)·MSS(중기부) 가 못 잡는 부처들
  (산업부 KEIT, 행안부, 해수부 등) 의 R&D 공고를 추가로 흡수.
  단 IITP 와 일부 공고가 중복될 수 있음 (과기정통부 공고가 양쪽에 노출) —
  중복 처리는 별도 task.
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

from bs4 import BeautifulSoup

from rfp_targeter.crawlers.base import BaseCrawler
from rfp_targeter.db.models import Announcement

log = logging.getLogger(__name__)


BASE = "https://www.iris.go.kr"
LIST_URL = f"{BASE}/contents/retrieveBsnsAncmBtinSituList.do"
DETAIL_URL = f"{BASE}/contents/retrieveBsnsAncmView.do"


# IRIS 자체 키워드 화이트리스트 — 제목·summary 에 하나라도 매칭되어야 yield.
# [2026-06-18 사용자 결정] IRIS 는 범부처라 환경·복지·해양 등 보안 비관련 R&D 가 많아
# keywords.yaml 의 광범위 사전(사업공고·공모·연구개발 등) 만으로는 노이즈가 큼.
# 회사 본업 = 사이버보안 + AI 보안 + 인증/검증 + 개인정보.
# 너무 좁히면 인접 분야 놓치므로 보안 인접까지 포함 (블록체인·암호·프라이버시).
IRIS_KEYWORD_WHITELIST = (
    # 보안 코어
    "정보보호", "정보보안", "보안", "사이버", "security", "cyber",
    "침해", "취약점", "해킹", "모의해킹", "모의침투", "침투", "위협",
    "침입", "멀웨어", "랜섬", "악성코드",
    # AI / ML — 회사 본업의 OFFen·AI 제품 라인
    "인공지능", "AI", "머신러닝", "딥러닝",
    # 인증 / 검증
    "인증", "ISMS", "ISO27", "신원",
    # 데이터 / 암호 / 블록체인
    "암호", "블록체인", "개인정보", "프라이버시",
    # 기관·표준
    "KISA",
)


def _matches_whitelist(*texts: str | None) -> bool:
    """텍스트 중 하나라도 화이트리스트 키워드와 매칭되면 True. 대소문자 무시."""
    hay = " ".join(t for t in texts if t).lower()
    if not hay:
        return False
    return any(kw.lower() in hay for kw in IRIS_KEYWORD_WHITELIST)


# 본문 매칭용 엄격 키워드 셋 — 제목/요약은 짧아 단일어("AI", "보안") 로 잡지만,
# 본문은 길어 일반어 한 번 등장으로 통과시키면 노이즈 큼 (광범위 R&D 본문에 흔히 등장).
# → 본문 전용은 합성어/고유어/약어만 (사이버보안·AI 보안·모의해킹·ISMS 등).
IRIS_BODY_WHITELIST = (
    # 보안 합성어
    "정보보호", "정보보안", "사이버보안", "사이버 보안", "사이버위협", "사이버 위협",
    "침해대응", "침해 대응", "침투시험", "모의해킹", "모의 해킹",
    "악성코드", "멀웨어", "랜섬웨어", "공격표면", "공급망 보안", "공급망보안",
    "취약점 분석", "취약점 검증", "보안성 검증", "보안 자동화",
    # 도메인 합성어
    "클라우드 보안", "클라우드보안", "OT 보안", "OT보안", "ICS 보안",
    "IoT 보안", "IoT보안", "AI 보안", "AI보안", "차량 보안", "모빌리티 보안",
    "5G 보안", "6G 보안", "블록체인 보안", "핀테크 보안", "금융보안",
    # 암호·인증 합성어 (단, "전자서명"은 신청서 절차 안내에 흔히 등장 → 제외)
    "양자내성암호", "동형암호", "양자 키 분배", "QKD",
    "디지털 신원", "디지털신원", "PKI",
    "제로트러스트", "Zero Trust",
    # 약어·표준
    "ISMS", "ISO27001", "ISO 27001", "CVSS", "CWSS", "OVAL", "STIX",
    "EDR", "XDR", "NDR", "SOC", "SIEM", "SOAR", "DLP", "SBOM",
    "APT", "DDoS",
    # 영문
    "cybersecurity", "cyber security", "information security",
    "penetration test", "threat intelligence",
    # 기관
    "KISA",
)


def _matches_body(*texts: str | None) -> bool:
    """본문 매칭용 엄격 화이트리스트."""
    hay = " ".join(t for t in texts if t).lower()
    if not hay:
        return False
    return any(kw.lower() in hay for kw in IRIS_BODY_WHITELIST)


def _to_iso_date(s: str | None) -> str | None:
    """IRIS 날짜 (예: "2026.06.17" 또는 "2026-06-17") → "2026-06-17"."""
    if not s:
        return None
    m = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s.strip())
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


class IRISCrawler(BaseCrawler):
    source = "iris"
    display_name = "IRIS (범부처)"

    def list_announcements(self) -> Iterator[Announcement]:
        rows_per_page = 10
        # 화이트리스트로 거르면 매 페이지당 통과율이 낮을 수 있어 페이지 한도를 넉넉히.
        # 보호 상한: max_per_source × 5 페이지 (예: 30개 목표 시 최대 50페이지=500건 스캔)
        # 정부 사이트 부하 고려해 5배로 제한.
        max_pages = max(1, self.max_per_source * 5 // rows_per_page)
        seen = 0
        scanned = 0

        # 세션 워밍업: 첫 GET 으로 쿠키 받기 (일부 정부 사이트는 referer 등 필요)
        try:
            self.fetch(f"{BASE}/contents/retrieveBsnsAncmBtinSituListView.do")
        except Exception as e:
            log.debug("iris warmup failed (계속 진행): %s", e)

        for page in range(1, max_pages + 1):
            try:
                # base.py fetch 는 GET 이라 직접 POST 사용
                r = self.session.post(
                    LIST_URL,
                    data={
                        "pageIndex": page,
                        "ancmSttArr": "",
                        "pbofrTpArr": "",
                        "blngGovdSeArr": "",
                        "sorgnIdArr": "",
                    },
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": f"{BASE}/contents/retrieveBsnsAncmBtinSituListView.do",
                    },
                    timeout=self.timeout,
                )
                r.raise_for_status()
            except Exception as e:
                log.warning("iris page %d POST fail: %s", page, e)
                break

            try:
                j = r.json()
            except Exception as e:
                log.warning("iris page %d JSON decode fail: %s", page, e)
                break

            items = j.get("listBsnsAncmBtinSitu") or []
            if not items:
                log.info("iris page %d: 더 이상 공고 없음", page)
                break

            page_yielded = 0
            body_recovered = 0
            for item in items:
                a = self._parse_item(item)
                if a is None:
                    continue
                scanned += 1
                # 1차: 제목+summary+부처/기관 매칭 (디테일 fetch 절약)
                if not _matches_whitelist(a.title, a.summary, a.agency):
                    # 1차 미통과 → 디테일 fetch + 본문에서 엄격 셋 매칭 (합성어/약어).
                    # IRIS 첨부는 javascript: 라 다운로드 불가 → 본문 HTML 만 매칭 대상.
                    try:
                        a = self.fetch_detail(a)
                    except Exception as e:
                        log.debug("iris pre-filter detail fail %s: %s", a.external_id, e)
                        continue
                    if not _matches_body(a.body):
                        continue
                    body_recovered += 1
                yield a
                seen += 1
                page_yielded += 1
                if seen >= self.max_per_source:
                    break

            if seen >= self.max_per_source or not items:
                break

        log.info(
            "iris: %d건 수집 (스캔 %d건, 본문매칭 회수 %d건)",
            seen, scanned, body_recovered,
        )

    def _parse_item(self, item: dict) -> Announcement | None:
        ancm_id = item.get("ancmId")
        title = (item.get("ancmTl") or "").strip()
        if not ancm_id or not title:
            return None

        # 발주 부처/기관: "과학기술정보통신부 > 한국연구재단" 형식
        govd = (item.get("blngGovdSeNm") or "").strip()
        sorgn = (item.get("sorgnNm") or "").strip()
        if govd and sorgn and govd != sorgn:
            agency = f"{govd} > {sorgn}"
        else:
            agency = govd or sorgn or "IRIS"

        posted_at = _to_iso_date(item.get("ancmDe"))
        deadline_at = _to_iso_date(item.get("rcveEndDe"))
        application_start_date = _to_iso_date(item.get("rcveStrDe"))

        # 분야공모/지정공모 등 공모 유형 — summary 자리에 표시 (본문 없어도 카드에 정보)
        summary_bits = []
        if item.get("pbofrTpSeNmLst"):
            summary_bits.append(item["pbofrTpSeNmLst"])
        if item.get("ancmNo"):
            summary_bits.append(item["ancmNo"])
        summary = " · ".join(summary_bits) if summary_bits else None

        return Announcement(
            source=self.source,
            external_id=f"iris-{ancm_id}",
            title=title,
            url=f"{DETAIL_URL}?ancmId={ancm_id}&ancmPrg=ancmPre",
            agency=agency,
            posted_at=posted_at,
            deadline_at=deadline_at,
            application_start_date=application_start_date,
            summary=summary,
        )

    def fetch_detail(self, a: Announcement) -> Announcement:
        """상세 페이지에서 본문·첨부·예산 추가 추출.

        Idempotent: list_announcements 의 1.5단계 본문매칭이 미리 호출했을 수 있어
        a.body 가 이미 채워져 있으면 네트워크 재요청을 건너뛴다.
        """
        if a.body:
            return a
        try:
            r = self.fetch(a.url)
        except Exception as e:
            log.debug("iris detail fetch fail %s: %s", a.external_id, e)
            return a

        soup = BeautifulSoup(r.text, "lxml")

        # 첨부파일 — IRIS는 javascript:f_bsnsAncm_downloadAtchFile() 호출 방식.
        # 직접 다운로드 불가 → url 은 상세 페이지로 대체(사용자가 거기서 다운로드).
        # downloader 가 javascript: 시도 안 하도록 url 자체를 detail page 로.
        attachments: list[dict] = []
        for atag in soup.find_all("a", href=True):
            href = atag["href"]
            # IRIS 첨부 인식: js 호출 (downloadAtchFile) 또는 일반 패턴
            is_js_attach = "downloadAtchFile" in href or "f_bsnsAncm_download" in href
            is_normal_attach = any(k in href for k in ("fileDownload", "atchFileSeq", "FileDown"))
            if not (is_js_attach or is_normal_attach):
                continue
            name = atag.get_text(" ", strip=True)
            if not name or len(name) < 3:
                continue
            from urllib.parse import urljoin
            # js 호출은 다운로드 불가 — url 을 상세 페이지로 (사용자가 IRIS 가서 받음)
            full_url = a.url if is_js_attach else urljoin(BASE, href)
            # 카테고리 추정 (NIPA 패턴 재사용)
            if any(k in name for k in ("공고서", "공고문", "[공고", "통합공고")):
                cat = "notice"
            elif any(k in name for k in ("제안요청서", "RFP", "요청서")):
                cat = "notice"
            elif any(k in name for k in ("양식", "서식", "신청서", "동의서", "이력서")):
                cat = "form"
            elif any(k in name for k in ("평가", "심사", "기준")):
                cat = "eval"
            else:
                cat = "reference"
            attachments.append({
                "name": name, "url": full_url, "category": cat, "local_path": None,
            })
        if attachments:
            a.attachments = attachments

        # 본문 — div.content 가 깔끔 (정찰 후 확정, 2026-06)
        # 소관부처/전문기관/공고번호/공고명/기간/예산 등 메타 데이터 포함
        main = (
            soup.select_one("div.content")
            or soup.select_one("div.boardView")
            or soup.select_one("div.view-content")
            or soup.select_one("div.cont-area")
            or soup.select_one("div.cont")
            or soup.select_one("article")
        )
        if main is None:
            # 폴백: 큰 텍스트 영역 찾기
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                tag.decompose()
            main = soup.body

        if main is not None:
            for tag in main(["script", "style", "noscript"]):
                tag.decompose()
            body = re.sub(r"\s+", " ", main.get_text(" ")).strip()[:10000]
            a.body = body

            # 예산·기간 추출 (공통 유틸)
            from rfp_targeter.attachments.budget_extract import extract_budget_mw, extract_duration_months
            mw = extract_budget_mw(body)
            if mw is not None:
                a.budget_mw = mw
            dm = extract_duration_months(body)
            if dm is not None:
                a.duration_months = dm

        # 첨부 본문 통합 (공통 헬퍼) — IRIS 는 js 다운로드라 url 이 detail page.
        # downloader 가 어차피 PDF 추출 못 함. 본문(div.content) 만으로 충분.
        # enrich 호출 자체를 skip (warning 노이즈 차단).
        if any((at.get("url") or "").startswith("https://www.iris.go.kr/contents/retrieveBsnsAncmView") is False
               and ".pdf" in (at.get("url") or "").lower()
               for at in (a.attachments or [])):
            from rfp_targeter.crawlers.base import enrich_body_with_attachments
            a = enrich_body_with_attachments(a, referer=BASE + "/")
        if a.body:
            from rfp_targeter.attachments.budget_extract import extract_budget_mw, extract_duration_months
            mw2 = extract_budget_mw(a.body)
            if mw2 is not None and a.budget_mw is None:
                a.budget_mw = mw2
            dm3 = extract_duration_months(a.body)
            if dm3 is not None and a.duration_months is None:
                a.duration_months = dm3
            # 마감/시작 재추출 (목록에서 못 가져온 경우)
            if not a.deadline_at:
                from rfp_targeter.attachments.dates_extract import extract_dates
                start_iso, deadline_iso = extract_dates(a.body)
                if deadline_iso:
                    a.deadline_at = deadline_iso
                if not a.application_start_date and start_iso:
                    a.application_start_date = start_iso
        return a
