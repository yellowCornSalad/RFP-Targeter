"""설정 파일 로더."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DRAFTS_DIR = PROJECT_ROOT / "drafts"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"설정 파일 없음: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def settings() -> dict:
    return _load_yaml(CONFIG_DIR / "settings.yaml")


@lru_cache(maxsize=1)
def keywords() -> dict:
    return _load_yaml(CONFIG_DIR / "keywords.yaml")


def _streamlit_secrets_as_env() -> None:
    """Streamlit Cloud의 st.secrets 값들을 환경변수로 펼침.

    Streamlit Cloud는 dashboard.py 시작 시 st.secrets dict로 secrets 제공.
    우리 코드는 환경변수 기반이라 둘을 브리지.
    """
    try:
        import streamlit as st  # noqa: F401
        # st.secrets 접근은 streamlit 실행 컨텍스트에서만 가능
        sec = st.secrets
        for k in ("DATABASE_URL", "DATA_GO_KR_KEY", "MSS_API_KEY",
                  "ANTHROPIC_API_KEY", "SLACK_WEBHOOK_URL",
                  "PROFILE_YAML_B64", "DASHBOARD_PASSWORD"):
            if k in sec and not os.environ.get(k):
                os.environ[k] = str(sec[k])
    except Exception:
        pass  # streamlit 미실행 컨텍스트 (CLI 등) — 무시


def secrets() -> dict:
    """secrets.yaml — API 키 등 민감 정보.

    파일 없으면 환경변수에서 자동 구성:
      - 로컬: config/secrets.yaml 직접 사용
      - GitHub Actions: env (workflow에서 secrets 주입)
      - Streamlit Cloud: st.secrets → env로 펼침 (위 _streamlit_secrets_as_env)

    환경변수 이름:
      DATABASE_URL          → supabase.database_url
      DATA_GO_KR_KEY        → data_go_kr.service_key
      MSS_API_KEY           → mss.service_key (없으면 DATA_GO_KR_KEY 재사용)
      ANTHROPIC_API_KEY     → anthropic.api_key
      SLACK_WEBHOOK_URL     → slack.webhook_url
    """
    path = CONFIG_DIR / "secrets.yaml"
    if path.exists():
        return _load_yaml(path)
    # Streamlit Cloud 환경이면 st.secrets → env 펼침
    _streamlit_secrets_as_env()
    # env로 폴백
    s: dict = {}
    if os.environ.get("DATABASE_URL"):
        s["supabase"] = {"database_url": os.environ["DATABASE_URL"]}
    if os.environ.get("DATA_GO_KR_KEY"):
        s["data_go_kr"] = {
            "service_key": os.environ["DATA_GO_KR_KEY"],
            "endpoint": "https://apis.data.go.kr/1721000/msitannouncementinfo/businessAnnouncMentList",
            "iitp_only_filter": False,
        }
    if os.environ.get("MSS_API_KEY") or os.environ.get("DATA_GO_KR_KEY"):
        s["mss"] = {
            "service_key": os.environ.get("MSS_API_KEY") or os.environ["DATA_GO_KR_KEY"],
            "endpoint": "https://apis.data.go.kr/1421000/mssBizService_v2/getbizList_v2",
        }
    if os.environ.get("ANTHROPIC_API_KEY"):
        s["anthropic"] = {
            "api_key": os.environ["ANTHROPIC_API_KEY"],
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
            "effort": os.environ.get("ANTHROPIC_EFFORT", "xhigh"),
        }
    if os.environ.get("SLACK_WEBHOOK_URL"):
        s["slack"] = {"webhook_url": os.environ["SLACK_WEBHOOK_URL"]}
    return s


def profile() -> dict:
    """profile.yaml 없으면 PROFILE_YAML_B64 env 디코드 → example fallback."""
    real = CONFIG_DIR / "profile.yaml"
    if real.exists():
        return _load_yaml(real)
    # Streamlit Cloud / GitHub Actions: PROFILE_YAML_B64 환경변수에서 복원
    _streamlit_secrets_as_env()
    b64 = os.environ.get("PROFILE_YAML_B64", "").strip()
    if b64:
        try:
            import base64
            decoded = base64.b64decode(b64).decode("utf-8")
            return yaml.safe_load(decoded) or {}
        except Exception:
            pass
    example = CONFIG_DIR / "profile.example.yaml"
    return _load_yaml(example)


def db_path() -> Path:
    """레거시 SQLite 경로 — 마이그레이션 스크립트에서만 사용 (현재는 PostgreSQL)."""
    rel = settings().get("database", {}).get("path", "data/rfp.db")
    path = PROJECT_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def db_url() -> str:
    """PostgreSQL connection string.

    우선순위:
      1. 환경변수 DATABASE_URL (GitHub Actions / 클라우드 배포)
      2. secrets.yaml 의 supabase.database_url (로컬 개발)

    형태: postgresql://postgres.{project}:{password}@{host}:{port}/postgres
    """
    env = os.environ.get("DATABASE_URL")
    if env and env.strip():
        return env.strip()
    sec = (secrets().get("supabase") or {})
    url = (sec.get("database_url") or "").strip()
    if not url or url == "???":
        raise RuntimeError(
            "DATABASE_URL 미설정. config/secrets.yaml 의 supabase.database_url 또는 "
            "환경변수 DATABASE_URL 둘 중 하나 필요."
        )
    return url
