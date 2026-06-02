"""첨부 파일 다운로더.

기본은 requests. 정부 사이트(msit.go.kr 등) SSL handshake 차단 시 curl subprocess로 폴백.
"""
from __future__ import annotations

import logging
import os
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

# 호스트 단위 서킷 브레이커 (프로세스 = 1회 크롤 범위).
#   한 호스트(예: msit.go.kr)가 연속 N회 다운로드 실패하면 이번 실행에서
#   그 호스트로의 남은 다운로드를 즉시 skip 한다.
#   배경: requests(30s)+curl(30s)=호출당 ~60s 라, 정부 사이트가 다운되면
#   첨부 수십 개가 직렬로 60s 씩 실패 → crawl.yml 40분 timeout → cancelled
#   (데이터 미갱신). breaker 로 호스트당 낭비를 ~N*60s 로 묶어 크롤을 완주시킨다.
#   성공 시 카운터 리셋 → 일시적 blip 이 영구 skip 으로 굳지 않음(정상경로 무영향).
_HOST_FAIL_THRESHOLD = max(1, int(os.environ.get("ATTACH_HOST_FAIL_THRESHOLD", "5")))
_host_consecutive_fails: dict[str, int] = {}
_host_tripped_logged: set[str] = set()


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

    host = urlparse(url).netloc

    # 서킷 브레이커: 이 호스트가 이번 실행에서 연속 N회 실패했으면 즉시 skip
    # (호출당 ~60s 낭비 방지 → 크롤이 40분 timeout 전에 완주).
    if _host_consecutive_fails.get(host, 0) >= _HOST_FAIL_THRESHOLD:
        if host not in _host_tripped_logged:
            log.warning(
                "첨부 다운로드 서킷 오픈: %s 연속 %d회 실패 → 이번 실행 남은 다운로드 skip",
                host, _HOST_FAIL_THRESHOLD,
            )
            _host_tripped_logged.add(host)
        return None

    # 1차: requests
    try:
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
            _host_consecutive_fails[host] = 0  # 성공 → breaker 리셋
            return dest
    except Exception as e:
        log.debug("requests download fail (%s): %s", url[:60], e)

    # 2차: curl 폴백
    if _has_curl() and _curl_download(url, dest, referer=referer):
        _host_consecutive_fails[host] = 0  # 성공 → breaker 리셋
        return dest

    _host_consecutive_fails[host] = _host_consecutive_fails.get(host, 0) + 1
    log.warning("다운로드 실패: %s", url[:80])
    return None
