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


def profile() -> dict:
    """profile.yaml 없으면 example로 fallback (개발 편의)."""
    real = CONFIG_DIR / "profile.yaml"
    example = CONFIG_DIR / "profile.example.yaml"
    return _load_yaml(real if real.exists() else example)


def secrets() -> dict:
    """secrets.yaml — API 키 등 민감 정보. 없으면 빈 dict 반환."""
    path = CONFIG_DIR / "secrets.yaml"
    if not path.exists():
        return {}
    return _load_yaml(path)


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
