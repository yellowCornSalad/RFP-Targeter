"""첨부 파일 → 텍스트 추출.

지원 포맷:
- .hwpx (한컴 OWPML, ZIP + XML)
- .odt  (OpenDocument, ZIP + XML)
- .pdf  (pypdf)
- .hwp  (구버전 OLE) — 지원 안 함 (라이브러리 복잡)
- 기타 — fallback (utf-8 텍스트 시도)
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

# hwp5txt 가용성 1회만 확인
_HAS_HWP5TXT: bool | None = None


def _has_hwp5txt() -> bool:
    global _HAS_HWP5TXT
    if _HAS_HWP5TXT is None:
        _HAS_HWP5TXT = shutil.which("hwp5txt") is not None
    return _HAS_HWP5TXT

MAX_TEXT_LEN = 50_000   # 본문에 합칠 최대 길이


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:MAX_TEXT_LEN]


def _extract_hwpx(path: Path) -> str:
    """한컴 .hwpx — Preview/PrvText.txt 우선, 없으면 Contents/section*.xml 의 <hp:t>."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            # 1) PrvText 우선 (가장 깔끔)
            if "Preview/PrvText.txt" in names:
                raw = zf.read("Preview/PrvText.txt").decode("utf-8", errors="ignore")
                prv_text = _normalize(raw)
                if len(prv_text) > 200:
                    # PrvText는 미리보기라 짧을 수 있음. section 으로 보강
                    sections = sorted([n for n in names if n.startswith("Contents/section") and n.endswith(".xml")])
                    if sections:
                        try:
                            xml = zf.read(sections[0]).decode("utf-8", errors="ignore")
                            texts = re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", xml)
                            full = " ".join(t for t in texts if t.strip())
                            if len(full) > len(prv_text):
                                return _normalize(full)
                        except Exception:
                            pass
                    return prv_text
            # 2) section0.xml
            sections = sorted([n for n in names if n.startswith("Contents/section") and n.endswith(".xml")])
            parts = []
            for s in sections:
                try:
                    xml = zf.read(s).decode("utf-8", errors="ignore")
                    parts.extend(re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", xml))
                except Exception:
                    continue
            joined = " ".join(t for t in parts if t.strip())
            if joined:
                return _normalize(joined)
    except zipfile.BadZipFile:
        return ""
    return ""


def _extract_odt(path: Path) -> str:
    """ODT — content.xml 안의 <text:p>, <text:span>."""
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("content.xml").decode("utf-8", errors="ignore")
            # 모든 텍스트 노드 추출
            texts = re.findall(r"<text:[a-zA-Z-]+[^>]*>([^<]*)</text:[a-zA-Z-]+>", xml)
            joined = " ".join(t for t in texts if t.strip())
            if joined:
                return _normalize(joined)
            # fallback: 모든 태그 제거
            clean = re.sub(r"<[^>]+>", " ", xml)
            return _normalize(clean)
    except (zipfile.BadZipFile, KeyError):
        return ""


def _extract_hwp(path: Path) -> str:
    """.hwp (구버전 OLE) — pyhwp 의 hwp5txt CLI 호출."""
    if not _has_hwp5txt():
        return ""
    try:
        r = subprocess.run(
            ["hwp5txt", str(path)],
            capture_output=True,
            timeout=45,
        )
        if r.returncode == 0:
            return _normalize(r.stdout.decode("utf-8", errors="ignore"))
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.debug("hwp5txt fail %s: %s", path.name, e)
    return ""


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path), strict=False)
        parts = []
        for page in reader.pages[:30]:  # 첫 30 페이지만
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return _normalize(" ".join(parts))
    except Exception as e:
        log.debug("PDF extract fail %s: %s", path.name, e)
        return ""


def _extract_zip_generic(path: Path) -> str:
    """.docx 등 ZIP 일반 — 모든 XML 의 텍스트 노드 합치기."""
    try:
        with zipfile.ZipFile(path) as zf:
            parts = []
            for n in zf.namelist():
                if not n.endswith(".xml"):
                    continue
                try:
                    raw = zf.read(n).decode("utf-8", errors="ignore")
                    clean = re.sub(r"<[^>]+>", " ", raw)
                    parts.append(clean)
                except Exception:
                    continue
            return _normalize(" ".join(parts))
    except zipfile.BadZipFile:
        return ""


def extract_text(path: Path) -> str:
    """파일 확장자/시그니처 기반으로 텍스트 추출. 실패 시 빈 문자열."""
    if path is None or not path.exists():
        return ""

    ext = path.suffix.lower()

    # 시그니처 기반 (확장자 신뢰 못 할 때)
    try:
        with path.open("rb") as f:
            head = f.read(8)
    except Exception:
        return ""

    if head[:4] == b"%PDF":
        return _extract_pdf(path)

    # OLE compound (.hwp 구버전, .doc) — hwp5txt 시도
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        text = _extract_hwp(path)
        if text:
            return text
        log.info(".hwp 추출 실패 (hwp5txt 없거나 파일 손상): %s", path.name)
        return ""

    if head[:4] == b"PK\x03\x04":
        # ZIP 계열 — 내용물로 분기
        if ext in (".hwpx", ""):
            text = _extract_hwpx(path)
            if text: return text
        if ext == ".odt":
            text = _extract_odt(path)
            if text: return text
        # 시도: hwpx → odt → generic
        for fn in (_extract_hwpx, _extract_odt, _extract_zip_generic):
            text = fn(path)
            if text:
                return text
        return ""

    # 평문
    try:
        return _normalize(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return ""
