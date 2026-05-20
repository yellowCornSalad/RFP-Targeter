"""설정 파일 로더."""
from __future__ import annotations

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
    rel = settings()["database"]["path"]
    path = PROJECT_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
