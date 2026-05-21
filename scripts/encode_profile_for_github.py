"""config/profile.yaml 을 base64로 인코딩 — GitHub Secret 'PROFILE_YAML_B64' 용.

사용:
    python scripts/encode_profile_for_github.py
    → 출력된 base64 문자열을 GitHub Secret에 붙여넣기.

GitHub Secret 등록 위치:
    repo → Settings → Secrets and variables → Actions → New repository secret
    Name: PROFILE_YAML_B64
    Value: 아래 출력 전체
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

PROFILE = Path(__file__).resolve().parents[1] / "config" / "profile.yaml"

if not PROFILE.exists():
    print(f"NG: {PROFILE} 없음")
    sys.exit(1)

raw = PROFILE.read_bytes()
b64 = base64.b64encode(raw).decode("ascii")

print(f"# config/profile.yaml ({len(raw):,} bytes → {len(b64):,} chars base64)")
print(f"# GitHub Secret 'PROFILE_YAML_B64' 에 아래 한 줄 통째로 붙여넣기:")
print()
print(b64)
print()
print("# 셋업 후 GitHub Actions가 매 실행마다 자동 디코드 → config/profile.yaml 복원")
