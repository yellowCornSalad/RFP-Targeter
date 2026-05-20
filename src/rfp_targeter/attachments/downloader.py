"""첨부 파일 다운로더.

기본은 requests. 정부 사이트(msit.go.kr 등) SSL handshake 차단 시 curl subprocess로 폴백.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from rfp_targeter.config import DATA_DIR

log = logging.getLogger(__name__)

ATTACHMENTS_DIR = DATA_DIR / "attachments"
TIMEOUT = 30

# curl 가용성 1회만 검사 (Windows 10+ 기본 내장)
_HAS_CURL: bool | None = None


def _has_curl() -> bool:
    global _HAS_CURL
    if _HAS_CURL is None:
        _HAS_CURL = shutil.which("curl") is not None
    return _HAS_CURL


def _safe_filename(name: str) -> str:
    """파일명에서 OS 금지문자 제거."""
    bad = '<>:"/\\|?*'
    out = "".join(c if c not in bad else "_" for c in name)
    return out[:200] or "attachment.bin"


def _curl_download(url: str, dest: Path, referer: str | None = None) -> bool:
    """curl로 다운로드 (Python ssl 우회)."""
    cmd = [
        "curl", "-L", "-sS", "-k", "--max-time", str(TIMEOUT),
        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
        "-o", str(dest),
    ]
    if referer:
        cmd += ["-e", referer]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT + 5)
        if r.returncode != 0:
            log.debug("curl failed (%d): %s", r.returncode, r.stderr.decode("utf-8", errors="ignore")[:200])
            return False
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        log.debug("curl exception: %s", e)
        return False


def download_file(
    url: str,
    external_id: str,
    filename: str,
    *,
    referer: str | None = None,
    overwrite: bool = False,
) -> Path | None:
    """첨부 1개 다운로드 → data/attachments/{external_id}/{filename}.

    requests 먼저 시도 → 실패 시 curl 폴백.
    """
    if not url:
        return None
    folder = ATTACHMENTS_DIR / _safe_filename(external_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / _safe_filename(filename)

    if dest.exists() and not overwrite and dest.stat().st_size > 0:
        return dest

    # 1차: requests
    try:
        host = urlparse(url).netloc
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
                "Referer": referer or f"https://{host}/",
            },
            timeout=TIMEOUT,
            stream=True,
            verify=False,
        )
        if r.status_code == 200 and len(r.content) > 0:
            dest.write_bytes(r.content)
            return dest
    except Exception as e:
        log.debug("requests download fail (%s): %s", url[:60], e)

    # 2차: curl 폴백
    if _has_curl() and _curl_download(url, dest, referer=referer):
        return dest

    log.warning("다운로드 실패: %s", url[:80])
    return None
