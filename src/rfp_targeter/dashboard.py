"""Streamlit 대시보드.

실행: streamlit run src/rfp_targeter/dashboard.py
"""
from __future__ import annotations

# Streamlit Cloud는 dashboard.py를 직접 실행 → src/ 가 sys.path 에 없어서
# `rfp_targeter` import 실패. 패키지 부모 디렉토리(=src/)를 명시적으로 추가.
import sys
from pathlib import Path
_SRC_DIR = Path(__file__).resolve().parents[1]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfp_targeter.config import profile
from rfp_targeter.db.models import get_conn, init_db, list_security_announcements
from rfp_targeter.drafter.draft_generator import generate_draft
from rfp_targeter.db.models import Announcement, Score

st.set_page_config(page_title="RFP-Targeter | 엔키화이트햇", layout="wide", page_icon="🎯")


# ─────────────────────────────────────────────────────────────────────────────
# 비밀번호 보호 (Streamlit Cloud public app 보호용)
# 로컬 실행 시: secrets.yaml에 dashboard.password 없으면 자동 skip
# Cloud 배포 시: st.secrets["DASHBOARD_PASSWORD"] 또는 secrets.yaml 의
#                dashboard.password 가 설정돼있으면 입력 페이지 표시
# ─────────────────────────────────────────────────────────────────────────────
def _get_password() -> str | None:
    """비밀번호 가져오기. st.secrets → secrets.yaml dashboard.password 순."""
    import os
    # 1. Streamlit Cloud secrets
    try:
        if "DASHBOARD_PASSWORD" in st.secrets:
            return str(st.secrets["DASHBOARD_PASSWORD"]).strip() or None
    except Exception:
        pass
    # 2. 환경변수
    env = os.environ.get("DASHBOARD_PASSWORD")
    if env and env.strip():
        return env.strip()
    # 3. secrets.yaml의 dashboard.password (로컬 옵션)
    try:
        from rfp_targeter.config import secrets as _s
        pw = ((_s().get("dashboard") or {}).get("password") or "").strip()
        if pw:
            return pw
    except Exception:
        pass
    return None


def _check_password() -> bool:
    """비밀번호 페이지 표시. 일치하면 True, 아니면 stop."""
    correct = _get_password()
    if not correct:
        return True  # 비밀번호 설정 안 됨 → 보호 X (로컬 개발용)

    if st.session_state.get("_auth_ok"):
        return True

    # 로그인 페이지 (대시보드 다른 UI는 숨김)
    st.html(
        "<div style='max-width:420px;margin:60px auto 0;text-align:center'>"
        "<div style='font-size:2.5rem'>🔒</div>"
        "<h2 style='margin:12px 0 6px;color:#0f172a;font-weight:700;letter-spacing:-0.02em'>"
        "RFP-Targeter</h2>"
        "<div style='color:#64748b;font-size:0.9rem;margin-bottom:24px'>"
        "엔키화이트햇 사내 도구 — 비밀번호 입력</div>"
        "</div>"
    )
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        pw = st.text_input("비밀번호", type="password", key="_pw_input",
                            label_visibility="collapsed", placeholder="비밀번호 입력")
        if st.button("로그인", type="primary", use_container_width=True):
            if pw == correct:
                st.session_state["_auth_ok"] = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    st.stop()


_check_password()

# ─────────────────────────────────────────────────────────────────────────────
# 전역 테마 — ENKI 브랜드 톤(딥 네이비 + 인디고) · Pretendard · 부드러운 카드
# st.html() 사용 — st.markdown은 <style> 안의 [class*="css"] 같은 CSS 속성
# 셀렉터를 markdown 링크로 오인해서 CSS 전체가 텍스트로 렌더되는 버그가 있음.
# ─────────────────────────────────────────────────────────────────────────────
st.html(
    """
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet"
    href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
/* === 색상 토큰 — BMW 톤 (검정 + 흰 + 회색 그라데이션) === */
:root {
    --bg:            #e8e8e8;       /* 메인 회색 배경 (BMW) */
    --bg-warm:       #f0f0f0;
    --surface:       #ffffff;       /* 카드 흰색 */
    --surface-alt:   #f7f7f7;       /* 보조 흰색 */
    --surface-sunk:  #ebebeb;
    --border:        #d4d4d4;       /* BMW 회색 보더 */
    --border-strong: #999999;       /* BMW 진한 회색 */
    --border-soft:   #e8e8e8;
    --text:          #111111;       /* BMW 검정 텍스트 */
    --text-muted:    #666666;       /* BMW 중간 회색 */
    --text-soft:     #333333;       /* BMW 진한 회색 */
    --text-faint:    #999999;       /* BMW 옅은 회색 */
    --primary:       #000000;       /* BMW 검정 액센트 */
    --primary-soft:  #111111;
    --primary-dark:  #000000;
    --accent:        #000000;       /* primary = accent (검정 통일) */
    --accent-hover:  #333333;
    --accent-soft:   #f0f0f0;       /* 검정 soft = 회색 */
    --chip-text:     #111111;
    --chip-border:   #d4d4d4;
    --bmw-blue:      #1c69d4;       /* BMW 보조 액센트 — 링크만 */
    --success:       #008c4e;       /* BMW 친화 초록 */
    --success-soft:  #e8f5ec;
    --warning:       #d97706;
    --warning-soft:  #fff7ed;
    --danger:        #c0392b;
    --danger-soft:   #fdedeb;
    /* Shadow tokens — 매우 절제 */
    --shadow-xs:     0 1px 2px rgba(0, 0, 0, 0.04);
    --shadow-sm:     0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04);
    --shadow-md:     0 4px 12px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);
    --shadow-lg:     0 12px 32px rgba(0, 0, 0, 0.08), 0 4px 8px rgba(0, 0, 0, 0.04);
    /* Radius — 일관성 (네이버/토스 8~12px) */
    --radius-sm:     6px;
    --radius:        8px;
    --radius-md:     10px;
    --radius-lg:     12px;
}

/* === 전역 폰트 — Pretendard === */
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] *,
section[data-testid="stSidebar"], section[data-testid="stSidebar"] * {
    font-family: 'Pretendard Variable', 'Pretendard', -apple-system, BlinkMacSystemFont,
                 'Segoe UI', system-ui, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif !important;
    font-feature-settings: 'tnum' on, 'kern' on;
    letter-spacing: -0.01em;
}
/* Streamlit 아이콘(Material Symbols)은 글리프 폰트라 Pretendard로 덮으면
   'keyboard_double_arrow_left' 같은 텍스트가 그대로 노출됨 — 예외 복원 */
.material-symbols-rounded, .material-symbols-outlined, .material-symbols-sharp,
.material-icons, .material-icons-outlined, .material-icons-round, .material-icons-sharp,
[class*="material-symbols"], [class*="material-icons"],
[data-testid="stIcon"], [data-testid="stIconMaterial"],
[data-testid="stExpanderToggleIcon"],
[data-testid="stExpander"] summary svg,
[data-testid="stExpander"] summary span:first-child,
/* 사이드바 접기/펼치기 버튼 (<<, >>) */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapseButton"] *,
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapsedControl"] *,
[data-testid="collapsedControl"],
[data-testid="collapsedControl"] *,
/* 우상단 헤더 chrome (Deploy 등 영역의 아이콘 버튼) */
[data-testid="stToolbar"] button,
[data-testid="stToolbar"] button *,
[data-testid="stHeader"] button,
[data-testid="stHeader"] button *,
header[data-testid="stHeader"] *,
button[kind="header"], button[kind="header"] *,
button[kind="headerNoPadding"], button[kind="headerNoPadding"] *,
[data-testid="baseButton-header"], [data-testid="baseButton-header"] *,
[data-testid="baseButton-headerNoPadding"], [data-testid="baseButton-headerNoPadding"] *,
/* 셀렉트박스/날짜픽커 등의 드롭다운 아이콘 */
[data-baseweb="select"] svg, [data-baseweb="select"] [role="presentation"],
[data-baseweb="popover"] svg,
[data-baseweb="icon"], [data-baseweb="icon"] *,
/* 일반적인 SVG 아이콘 컨테이너 */
svg[class*="icon"], i[class*="icon"] {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
                 'Material Icons', 'Material Icons Outlined' !important;
    font-feature-settings: 'liga' !important;
    letter-spacing: normal !important;
    text-transform: none !important;
}

/* === 전체 배경 — BMW 톤 (진한 회색 + 흰 카드 확실히 떠보이게) === */
[data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stAppViewContainer"] > div,
.stApp {
    background: #e8e8e8 !important;
}
.main .block-container, [data-testid="stMain"] .block-container {
    padding-top: 1rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1600px;  /* BMW 와이드 — 2-column 카드 그리드 충분 공간 */
    background: transparent !important;
}

/* === 사이드바 폭 조정 — BMW 식 컴팩트 (280px) === */
section[data-testid="stSidebar"] {
    width: 280px !important;
    min-width: 280px !important;
}
section[data-testid="stSidebar"][aria-expanded="true"] {
    min-width: 280px !important;
    max-width: 280px !important;
}
section[data-testid="stSidebar"] > div {
    width: 280px !important;
}
/* 사이드바 내부 패딩 더 컴팩트 */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-left: 0.85rem !important;
    padding-right: 0.85rem !important;
}

/* === Streamlit 기본 데코 숨김 (Deploy 버튼 위 영역, 햄버거 메뉴 등) === */
[data-testid="stToolbar"] { right: 1rem; }
[data-testid="stDecoration"] { display: none !important; }
#MainMenu, footer { visibility: hidden; }

/* === 사이드바 — BMW 흰색 (메인 진한 회색과 대비) === */
section[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #d4d4d4 !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
    padding: 0.25rem 0.5rem !important;
    min-height: 0 !important;
    height: auto !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-top: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div:first-child {
    padding-top: 0 !important;
    margin-top: 0 !important;
}
/* 로고 컨테이너 — 위 여백 negative, 아래 타이틀 가깝게 */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] .element-container:first-of-type {
    margin-top: -1.5rem !important;
    margin-bottom: -1.25rem !important;
}
section[data-testid="stSidebar"] [data-testid="stImage"]:first-of-type {
    margin: 0 !important;
    padding: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stImage"]:first-of-type + div,
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] .element-container:nth-of-type(2) {
    margin-top: 0 !important;
    padding-top: 0 !important;
}
section[data-testid="stSidebar"] h1 {
    margin-top: 0.5rem !important;
    padding-top: 0 !important;
    font-size: 1.25rem !important;
    color: var(--primary) !important;
    font-weight: 800 !important;
    letter-spacing: -0.025em !important;
}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    color: var(--text-faint) !important;
    font-size: 0.78rem !important;
}
section[data-testid="stSidebar"] hr {
    border-color: var(--border) !important;
    margin: 1rem 0 !important;
}
/* 사이드바 섹션 헤더 — BMW 식 강한 톤 (uppercase + tracking + 상단 보더) */
section[data-testid="stSidebar"] h3 {
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: #111 !important;
    font-weight: 800 !important;
    margin-top: 1.6rem !important;
    margin-bottom: 0.55rem !important;
    padding-top: 0.85rem !important;
    border-top: 1px solid #e5e5e5 !important;
}
/* 첫 번째 h3 는 위 보더 제거 (사이드바 헤더 직후라 중복) */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div > div > div > div > div:first-of-type h3,
section[data-testid="stSidebar"] h3:first-of-type {
    border-top: none !important;
    padding-top: 0 !important;
    margin-top: 0.75rem !important;
}
/* 사이드바 라벨 (selectbox 등) — 더 작고 단정 */
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    font-size: 0.825rem !important;
    color: var(--text-soft) !important;
    font-weight: 500 !important;
    margin-bottom: 4px !important;
}

/* === 헤더 (h1~h4) — 네이버/토스 톤 위계 === */
h1, h2, h3, h4 {
    color: var(--text) !important;
    letter-spacing: -0.025em !important;
    font-weight: 700 !important;
    line-height: 1.3 !important;
}
h1 { font-size: 1.5rem !important; }
h2 { font-size: 1.15rem !important; margin-top: 0.5rem !important; }
h3 { font-size: 1rem !important; font-weight: 600 !important; }
h4 { font-size: 0.9rem !important; font-weight: 600 !important; }

/* === Tabs — BMW 식 가로 메뉴 (검정 액센트) === */
[data-testid="stTabs"] [role="tablist"] {
    gap: 0;
    border-bottom: 1px solid #ddd !important;
    margin-bottom: 1.5rem;
}
[data-testid="stTabs"] [role="tab"] {
    color: #666 !important;
    font-weight: 500 !important;
    padding: 0.75rem 1.5rem !important;
    border-bottom: 2px solid transparent !important;
    transition: color 0.15s ease, border-color 0.15s ease;
    border-radius: 0 !important;
}
[data-testid="stTabs"] [role="tab"]:hover {
    color: #111 !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #111 !important;
    font-weight: 700 !important;
    border-bottom-color: #111 !important;
}

/* === Streamlit Button 내부 텍스트 — 발주기관 카드와 동일 톤 (Pretendard + 자간) === */
[data-testid="stButton"] button p,
[data-testid="stButton"] button strong,
[data-testid="stButton"] button em,
[data-testid="stButton"] button span,
[data-testid="stButton"] button div {
    font-family: 'Pretendard Variable', 'Pretendard', -apple-system, BlinkMacSystemFont,
                 'Segoe UI', system-ui, sans-serif !important;
    letter-spacing: -0.02em !important;
    font-style: normal !important;  /* markdown italic(_x_) 도 평문 */
}
/* button 안 strong (큰 숫자) — 더 굵게 */
[data-testid="stButton"] button strong {
    font-weight: 700 !important;
    font-size: 1.4em !important;
}

/* === 일반 버튼 — BMW 톤 (각진 모서리, flat, 절제된 hover) === */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button {
    border-radius: 2px !important;
    border: 1px solid var(--border) !important;
    background: var(--surface) !important;
    color: var(--text) !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    padding: 0.55rem 1rem !important;
    transition: border-color 0.15s ease, background 0.15s ease !important;
    box-shadow: none !important;
}
[data-testid="stButton"] > button:hover:not(:disabled),
[data-testid="stDownloadButton"] > button:hover:not(:disabled) {
    border-color: #333 !important;
    background: #fafafa !important;
    color: var(--text) !important;
}
/* Primary 버튼 — BMW 식 검정 (강조 액션) */
[data-testid="stButton"] > button[kind="primary"] {
    background: #111 !important;
    border-color: #111 !important;
    color: #fff !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover:not(:disabled) {
    background: #333 !important;
    border-color: #333 !important;
    color: #fff !important;
}
[data-testid="stButton"] > button:disabled {
    opacity: 0.45 !important;
    box-shadow: none !important;
}
/* primary 버튼 (활성 KPI 등) — 브랜드 컬러 */
[data-testid="stButton"] > button[kind="primary"] {
    background: var(--primary) !important;
    border-color: var(--primary) !important;
    color: #ffffff !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover:not(:disabled) {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
    color: #ffffff !important;
}

/* === 카드 컨테이너 — BMW 식 (컴팩트) === */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] {
    border: none !important;
    border-radius: 4px !important;
    background: #ffffff !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08) !important;
    transition: box-shadow 0.18s ease !important;
    margin-bottom: 10px !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.10) !important;
}
/* 카드 내부 padding 최소화 */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] > div > div {
    padding: 2px !important;
}
/* ★ 카드 안 element 사이 gap 강제 0 (streamlit 기본 16px 제거) ★ */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stElementContainer"] {
    margin: 0 !important;
    padding: 0 !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"] {
    margin: 0 !important;
    padding: 0 !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdown"] {
    margin: 0 !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {
    gap: 6px !important;
}
/* 카드 안 제목 h3 */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] h3 {
    font-size: 1.02rem !important;
    line-height: 1.35 !important;
    margin: 4px 14px !important;
}
/* 카드 안 다음 row 추가 element padding */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stElementContainer"] > div {
    padding: 0 14px !important;
}
/* 액션 버튼 row */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"] {
    padding: 6px 14px 8px !important;
}
/* 오늘 신규 공고 카드 — 미세한 상단 빨간 액센트 라인 + 단정한 boder */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(
    > div > div > [data-testid="stElementContainer"]:first-of-type
    [style*="background:#fef2f2"]
) {
    border-color: #fecaca !important;
    box-shadow: var(--shadow-xs) !important;
}

/* === Metric (종합/테마 점수) — 흰 배경, 큰 숫자 === */
[data-testid="stMetric"] {
    background: transparent !important;
    padding: 0.25rem 0 !important;
}
[data-testid="stMetricValue"] {
    font-feature-settings: 'tnum' on;
    font-weight: 700 !important;
    color: var(--text) !important;
    font-size: 2rem !important;
    letter-spacing: -0.04em !important;
}
[data-testid="stMetricLabel"] {
    color: var(--text-muted) !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
}

/* === Expander — BMW 식 단정 (각진 모서리, 흰 배경) === */
[data-testid="stExpander"] {
    border: 1px solid #e5e5e5 !important;
    border-radius: 2px !important;
    background: #ffffff !important;
    box-shadow: none !important;
}
[data-testid="stExpander"] summary {
    color: var(--text-muted) !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
}
[data-testid="stExpander"] summary:hover {
    color: var(--primary) !important;
}

/* === 입력/선택 위젯 — BMW 식 각진 모서리 === */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div,
[data-baseweb="popover"] {
    border-radius: 2px !important;
    border-color: #d4d4d4 !important;
}
[data-testid="stTextInput"] input:focus,
[data-baseweb="select"] > div:focus-within {
    border-color: #111 !important;
    box-shadow: 0 0 0 1px #111 !important;
}

/* === Slider — BMW 검정 thumb + 검정 트랙 === */
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
    background: #111 !important;
    border: 2px solid #ffffff !important;
    box-shadow: 0 0 0 1px #111 !important;
}
[data-testid="stSlider"] [data-baseweb="slider"] > div > div > div {
    background: #111 !important;
}

/* === Multiselect 칩 — BMW 식 검정 강제 (streamlit 인라인 style 덮어쓰기) ===
   Streamlit 1.40+ 가 inline background-color 를 직접 박아넣어서 더 강한 셀렉터 필요 */
[data-testid="stMultiSelect"] span[data-baseweb="tag"],
[data-testid="stMultiSelect"] div[data-baseweb="tag"],
[data-baseweb="tag"],
[data-baseweb="tag"] > div,
[data-baseweb="tag"] > span,
section[data-testid="stSidebar"] [data-baseweb="tag"] {
    background: #111111 !important;
    background-color: #111111 !important;
    color: #ffffff !important;
    border: 1px solid #111111 !important;
    border-radius: 2px !important;
    font-weight: 600 !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"] *,
[data-baseweb="tag"] * {
    color: #ffffff !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"] svg,
[data-baseweb="tag"] svg {
    fill: #ffffff !important;
    color: #ffffff !important;
}

/* === Checkbox — BMW 검정 === */
[data-testid="stCheckbox"] [data-baseweb="checkbox"] [data-checked="true"],
[data-testid="stCheckbox"] [data-baseweb="checkbox"] > div:first-child[aria-checked="true"] {
    background: #111 !important;
    border-color: #111 !important;
}

/* === Streamlit Primary Button 강제 검정 + 흰 글자 (KPI 활성 카드) ===
   markdown bold(**), em(*) 등 모든 자식 태그까지 흰색 강제 */
button[kind="primary"],
[data-testid="stButton"] button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background-color: #000000 !important;
    border-color: #000000 !important;
    color: #ffffff !important;
}
button[kind="primary"] *,
button[kind="primary"] p,
button[kind="primary"] strong,
button[kind="primary"] em,
button[kind="primary"] span,
button[kind="primary"] div,
[data-testid="stButton"] button[kind="primary"] *,
button[data-testid="baseButton-primary"] * {
    color: #ffffff !important;
    background: transparent !important;
}
button[kind="primary"]:hover:not(:disabled) {
    background-color: #333333 !important;
    border-color: #333333 !important;
}
button[kind="primary"]:hover:not(:disabled) * {
    color: #ffffff !important;
}

/* === Streamlit BaseWeb 컴포넌트 강제 BMW 톤 ===
   BaseWeb 인라인 style을 모두 덮기 위한 와일드카드 셀렉터 */
/* multiselect 칩 (사이드바·메인 다) */
[data-baseweb="tag"] {
    background: #000000 !important;
    background-color: #000000 !important;
    border-color: #000000 !important;
    color: #ffffff !important;
}
[data-baseweb="tag"] > div,
[data-baseweb="tag"] > span,
[data-baseweb="tag"] * {
    color: #ffffff !important;
    background: transparent !important;
}
[data-baseweb="tag"] svg,
[data-baseweb="tag"] path {
    fill: #ffffff !important;
    color: #ffffff !important;
    stroke: #ffffff !important;
}
/* Slider thumb + 채워진 트랙 */
[data-baseweb="slider"] [role="slider"],
[data-baseweb="slider"] [role="slider"] > div {
    background: #000000 !important;
    background-color: #000000 !important;
}
[data-baseweb="slider"] div[data-testid] {
    background: #000000 !important;
}
/* Checkbox 체크된 상태 */
[data-baseweb="checkbox"] [aria-checked="true"],
[data-baseweb="checkbox"] [data-checked="true"],
[data-testid="stCheckbox"] [aria-checked="true"] {
    background: #000000 !important;
    background-color: #000000 !important;
    border-color: #000000 !important;
}
/* Select 드롭다운 활성 옵션 */
[data-baseweb="menu"] li[aria-selected="true"] {
    background: #f0f0f0 !important;
    color: #000000 !important;
}

/* === 사이드바 select/multiselect 박스 self === */
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #ffffff !important;
    border-color: #d4d4d4 !important;
}

/* === Divider === */
hr {
    border-color: var(--border) !important;
    margin: 1.5rem 0 !important;
}

/* === Caption · 본문 === */
[data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
}

/* === 인라인 코드 === */
code:not(pre code) {
    background: var(--surface-alt) !important;
    color: var(--accent-hover) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    padding: 0.1rem 0.4rem !important;
    font-size: 0.85em !important;
    font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace !important;
}

/* === 정보 박스 (st.info, st.warning) === */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border: 1px solid var(--border) !important;
}

/* === 다이얼로그 === */
[role="dialog"] {
    border-radius: 18px !important;
    box-shadow: 0 24px 64px rgba(15, 23, 42, 0.22) !important;
}

/* === 링크 — BMW 블루 (보조 액센트), 호버 시 밑줄 === */
a {
    color: var(--bmw-blue) !important;
    text-decoration: none !important;
    border-bottom: 1px solid transparent;
    transition: border-color 0.15s ease;
}
a:hover {
    border-bottom-color: var(--bmw-blue) !important;
}

/* === Scrollbar (Webkit) — 미니멀 === */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: var(--border-strong);
    border-radius: 8px;
}
::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }

/* ═════════════════════════════════════════════════════════════════════════
   Production UX 패턴 — top bar / filter chips / progress bar / badges /
   ghost buttons / empty state / card score band
   ═════════════════════════════════════════════════════════════════════════ */

/* === 본문 상단 app bar — 네이버 메인 상단 톤 (그림자 X, 단순) === */
.enki-appbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px; background: var(--surface);
    border: 1px solid var(--border); border-radius: var(--radius);
    margin-bottom: 18px;
    box-shadow: none;
}
.enki-appbar .left {
    display: flex; align-items: center; gap: 12px;
}
.enki-appbar .crumb {
    color: var(--text-muted); font-size: 12px;
    font-weight: 500;
}
.enki-appbar .title {
    font-size: 1rem; font-weight: 700; color: var(--text);
    letter-spacing: -0.02em;
}
.enki-appbar .badge {
    background: var(--accent-soft); color: var(--primary);
    padding: 2px 9px; border-radius: 5px;
    font-size: 11px; font-weight: 600; border: 1px solid var(--chip-border);
}
.enki-appbar .right {
    display: flex; align-items: center; gap: 12px;
    color: var(--text-muted); font-size: 12px;
}
.enki-appbar .right .dot { width:6px;height:6px;border-radius:50%;
    background: var(--success); display:inline-block; margin-right:4px; }

/* === KPI Stats Strip — 네이버/토스 톤, 절제된 hover === */
.enki-kpi-strip { display: grid; gap: 10px; margin-bottom: 18px; }
.enki-kpi-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px 16px;
    transition: border-color 0.15s ease, background 0.15s ease;
    cursor: pointer;
    box-shadow: none;
}
.enki-kpi-card:hover {
    border-color: var(--border-strong);
    background: var(--surface-alt);
}
.enki-kpi-card.active {
    background: var(--accent-soft); border-color: var(--primary);
}
.enki-kpi-card.warn {
    background: var(--warning-soft); border-color: #fde68a;
}
.enki-kpi-label {
    color: var(--text-muted); font-size: 12px;
    font-weight: 500; letter-spacing: 0;
    display: flex; align-items: center; gap: 6px;
}
.enki-kpi-label .dot {
    width: 6px; height: 6px; border-radius: 50%; display: inline-block;
}
.enki-kpi-value {
    font-size: 1.65rem; font-weight: 700;
    color: var(--text); letter-spacing: -0.03em;
    font-feature-settings: 'tnum' on;
    margin-top: 6px; line-height: 1.1;
}
.enki-kpi-value .unit { font-size: 0.65em; color: var(--text-muted); font-weight: 500; margin-left: 3px; }
.enki-kpi-delta {
    margin-top: 6px; font-size: 12px; color: var(--text-muted);
    display: flex; align-items: center; gap: 4px;
}
.enki-kpi-delta.up   { color: var(--success); }
.enki-kpi-delta.down { color: var(--danger); }
.enki-kpi-delta.warn { color: var(--warning); }

/* === 활성 필터 칩 바 === */
.enki-filter-bar {
    display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    padding: 10px 14px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 12px;
    margin-bottom: 14px; font-size: 0.85rem;
}
.enki-filter-bar .lead {
    color: var(--text-muted); font-weight: 600; margin-right: 4px;
}
.enki-filter-bar .chip {
    background: var(--accent-soft); color: var(--chip-text);
    border: 1px solid var(--chip-border);
    padding: 3px 9px 3px 10px; border-radius: 6px;
    font-size: 0.8rem; font-weight: 500;
    display: inline-flex; align-items: center; gap: 6px;
}
.enki-filter-bar .chip.warn {
    background: #fff7ed; color: #c2410c; border-color: #fed7aa;
}
.enki-filter-bar .empty {
    color: var(--text-faint); font-style: italic;
}

/* === 공고 카드 좌측 점수 컬러 밴드 — 단색 (그라데이션 X) === */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] {
    position: relative;
    overflow: hidden;
}
.enki-card-band {
    position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
    border-top-left-radius: var(--radius-lg); border-bottom-left-radius: var(--radius-lg);
}
.band-top    { background: #f59e0b; }   /* ≥90 — top */
.band-high   { background: var(--success); }   /* ≥75 — good */
.band-mid    { background: #facc15; }   /* ≥60 — fair */
.band-low    { background: var(--border-strong); }   /* <60 */

/* === 상태 배지 (카드 우상단) — 네이버/토스 톤, soft 배경 === */
.enki-status-badge {
    display: inline-block; padding: 3px 9px;
    border-radius: 5px; font-size: 11px;
    font-weight: 600; letter-spacing: 0.02em;
    border: 1px solid transparent;
}
.enki-status-badge.top  { background:var(--warning-soft); color:var(--warning); border-color:#fde68a; }
.enki-status-badge.high { background:var(--success-soft); color:var(--success); border-color:#a7f3d0; }
.enki-status-badge.mid  { background:#fefce8; color:#a16207; border-color:#fde047; }
.enki-status-badge.low  { background:var(--surface-alt); color:var(--text-muted); border-color:var(--border); }

/* === 5축 mini progress bar === */
.enki-axes { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.enki-axis-row {
    display: grid; grid-template-columns: 92px 1fr 32px;
    gap: 10px; align-items: center;
    font-size: 0.78rem; color: var(--text-soft);
}
.enki-axis-row .name { font-weight: 500; }
.enki-axis-row .bar {
    height: 6px; background: var(--surface-alt);
    border-radius: 999px; overflow: hidden;
}
.enki-axis-row .fill {
    height: 100%; border-radius: 999px;
    transition: width 0.3s ease;
}
.enki-axis-row .val {
    text-align: right; font-weight: 700; font-feature-settings: 'tnum' on;
    color: var(--text);
}

/* === 빈 상태 === */
.enki-empty {
    text-align: center; padding: 64px 24px;
    background: var(--surface); border: 1px dashed var(--border-strong);
    border-radius: 16px; color: var(--text-muted);
}
.enki-empty .icon {
    width: 64px; height: 64px; margin: 0 auto 16px;
    background: var(--accent-soft); border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    color: var(--accent); font-size: 28px;
}
.enki-empty .title { font-size: 1.05rem; font-weight: 700; color: var(--text); margin-bottom: 6px; }
.enki-empty .desc { font-size: 0.9rem; color: var(--text-muted); margin-bottom: 18px; }

/* === Section divider (캡션 위 가는 hairline) === */
.enki-section {
    margin: 24px 0 12px;
    color: var(--text-faint); font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700;
    display: flex; align-items: center; gap: 10px;
}
.enki-section::after {
    content: ''; flex: 1; height: 1px; background: var(--border);
}
</style>
"""
)

# 사이드바 상단에 ENKI WhiteHat 로고 (클릭 시 홈으로 — 모든 필터 리셋)
from rfp_targeter.config import PROJECT_ROOT as _PR
_LOGO = _PR / "assets" / "enki_logo.png"


@st.cache_data
def _logo_b64() -> str:
    import base64
    return base64.b64encode(_LOGO.read_bytes()).decode()


if _LOGO.exists():
    # ?home=1 URL 파라미터 트릭 — 같은 탭에서 리로드 + 다음 사이클에서 감지·리셋
    st.sidebar.markdown(
        f'<a href="?home=1" target="_self" '
        f'style="display:block;text-decoration:none;line-height:0">'
        f'<img src="data:image/png;base64,{_logo_b64()}" '
        f'style="width:220px;cursor:pointer;transition:opacity 0.15s" '
        f'onmouseover="this.style.opacity=0.85" '
        f'onmouseout="this.style.opacity=1" '
        f'title="홈으로 (모든 필터 초기화)"></a>',
        unsafe_allow_html=True,
    )

# 홈 신호 감지 — ?home=1 들어오면 모든 필터 초기화하고 query param 정리
if st.query_params.get("home"):
    for k in (
        "search_query", "min_score", "kw_filter", "imminent_only",
        "eligibility_mode_label", "current_page", "sort_by",
        "_detail_id", "_ai_confirm_id", "_ai_running",
        "include_dismissed",
    ):
        if k in st.session_state:
            del st.session_state[k]
    st.query_params.clear()
    st.rerun()

init_db()


# ---------- 데이터 로드 ----------
@st.cache_data(ttl=60)
def load_data(include_dismissed: bool = False) -> pd.DataFrame:
    with get_conn() as conn:
        rows = list_security_announcements(
            conn, limit=2000, include_dismissed=include_dismissed,
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    if "posted_at" in df:
        df["posted_at_dt"] = pd.to_datetime(df["posted_at"], errors="coerce")
    if "deadline_at" in df:
        df["deadline_at_dt"] = pd.to_datetime(df["deadline_at"], errors="coerce")
        df["days_left"] = (df["deadline_at_dt"] - pd.Timestamp.now(tz=df["deadline_at_dt"].dt.tz)).dt.days
    return df


@st.cache_data(ttl=30)
def count_dismissed() -> int:
    """현재 숨김 처리된 공고 수 — 사이드바 토글 라벨에 노출."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM announcement WHERE is_security = TRUE AND is_dismissed = TRUE"
            )
            row = cur.fetchone()
    return int(row["n"] if row else 0)


# ---------- 사이드바 ----------
st.sidebar.title("RFP-Targeter")
st.sidebar.caption(f"엔키화이트햇  ·  {datetime.now().strftime('%Y.%m.%d %H:%M')}")
if st.sidebar.button("데이터 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# 숨김 포함 토글 — sidebar 새로고침 버튼 바로 아래
_dismissed_n = count_dismissed()
_include_dismissed_label = (
    f"숨김 처리 {_dismissed_n}개 포함 표시" if _dismissed_n
    else "숨김된 공고 없음"
)
include_dismissed = st.sidebar.checkbox(
    _include_dismissed_label,
    value=False, key="include_dismissed",
    disabled=(_dismissed_n == 0),
    help="체크하면 [숨김] 버튼으로 가린 공고도 함께 표시 — 거기서 [숨김 해제]로 복원 가능",
)

with st.spinner("공고 데이터 불러오는 중..."):
    df = load_data(include_dismissed=include_dismissed)

if df.empty:
    st.html(
        "<div style='text-align:center;padding:64px 24px;background:#ffffff;"
        "border:1px dashed #e2e8f0;border-radius:16px;color:#64748b'>"
        "<div style='width:64px;height:64px;margin:0 auto 16px;background:#eff6ff;"
        "border-radius:50%;display:flex;align-items:center;justify-content:center;"
        "color:#3b82f6;font-size:28px'>📭</div>"
        "<div style='font-size:1.05rem;font-weight:700;color:#0f172a;margin-bottom:6px'>"
        "아직 수집된 공고가 없어요</div>"
        "<div style='font-size:0.9rem;color:#64748b;margin-bottom:14px'>"
        "먼저 스케줄러 또는 일회성 크롤링을 실행해 주세요.</div>"
        "<code style='font-size:0.82em;background:#f8fafc;padding:6px 12px;"
        "border-radius:6px;color:#1d4ed8;border:1px solid #e2e8f0'>"
        "python -m rfp_targeter.scheduler</code>"
        "</div>"
    )
    st.stop()

# ─── 카드 본문 휑함 보강 helper — body에서 핵심 정보 추출 (hallucination 방지) ───
def _extract_key_facts(body: str | None) -> list[str]:
    """본문에서 카드에 표시할 facts 추출 (사업기간·소요예산·낙찰방법 등).
    hallucination 방지 — 본문에 명시된 패턴만 추출. 못 찾으면 빈 리스트.
    """
    if not body or not isinstance(body, str):
        return []
    import re as _re
    head = body[:3000]  # 본문 머리 — 입찰공고는 대부분 앞쪽에 facts
    head = _re.sub(r"\s+", " ", head)
    out: list[tuple[str, str]] = []
    # 1) 사업기간 — "사업기간 : 계약체결일 ~ 2026. 12. 31."
    m = _re.search(r"사업\s*기간\s*[:：]\s*([^.①②③④⑤◆●○□■▶※]{6,80}?)(?=\s*(?:①|②|③|◆|●|○|□|■|▶|※|\s2\.|낙찰자|입찰|$))", head)
    if m:
        val = _re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        if 4 < len(val) < 70:
            out.append(("기간", val))
    # 2) 소요예산 / 사업비 — "소요예산 : 332,000,000 원" "사업비 : ..."
    m = _re.search(r"(?:소요\s*예산|사업\s*비|예산\s*\(?\s*총\s*\)?|총\s*사업비)\s*[:：]\s*([^.①②③④⑤◆●○□■▶※]{4,80}?)(?=\s*(?:①|②|③|◆|●|○|□|■|▶|※|\s2\.|사업\s*기간|낙찰자|$))", head)
    if m:
        val = _re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        # 1억 미만은 표기 명확화 위해 그대로 두기
        if 3 < len(val) < 80 and any(c.isdigit() for c in val):
            out.append(("예산", val))
    # ❌ 낙찰자 결정방법은 정부 R&D 공고 표준 문구 ("기획재정부 계약예규 협상에 의한 ...")
    #    모든 카드 동일 → 정보 가치 0 → 사용자 피드백 반영해서 제거
    return [f"{k}: {v}" for k, v in out[:2]]  # 카드는 최대 2줄


def _extract_card_excerpt(body: str | None, max_len: int = 160) -> str:
    """본문에서 카드용 핵심 1문장 추출 (facts 못 찾았을 때 폴백).
    머리말(알림마당·입찰공고·인쇄하기·트위터 등) 스킵.
    """
    if not body or not isinstance(body, str):
        return ""
    import re as _re
    txt = body
    # 1) 의미 있는 시작점 마커
    SKIP_MARKERS = [
        "□ 사업개요", "□ 사업 개요", "○ 사업개요", "○ 사업 개요",
        "■ 사업개요", "■ 사업 개요",
        "1. 사업개요", "1. 사업 개요",
        "사업명:", "사업명 :", "추진 배경", "사업 목적",
        "□ 추진 목적", "○ 추진 목적", "◆ 추진 목적",
        "공고합니다", "안내드립니다", "모집합니다",
    ]
    cut = -1
    for m in SKIP_MARKERS:
        idx = txt.find(m)
        if idx >= 0 and (cut < 0 or idx < cut):
            cut = idx
    if cut >= 0:
        txt = txt[cut:]
    else:
        # 머리말 잡음 스킵 (KISA 머리말은 모두 표 형식)
        for noise in ["인쇄하기 공유하기 닫기", "트위터 페이스북", "==========="]:
            i = txt.find(noise)
            if i >= 0:
                txt = txt[i + len(noise):].lstrip(" =\t\n")
                break
    txt = _re.sub(r"\s+", " ", txt).strip()
    # 표 머리(관리번호 ... 입찰방법) 다음으로 한번 더 건너뛰기
    for table_head in ["관리번호", "계 약 건 명", "사업명 사업기간"]:
        i = txt.find(table_head)
        if 0 <= i < 80:
            # 이 뒤 의미있는 문장 찾기 — 마침표나 절 마커 다음으로 점프
            j = txt.find(". ", i + len(table_head))
            if 0 < j < i + 300:
                txt = txt[j + 2:]
                break
    if len(txt) < 30:
        return ""
    # max_len 안에서 자연스럽게 자르기
    snippet = txt[:max_len + 60]
    cuts = [snippet.find(c, max_len // 2) for c in [".", "다 ", ". ", "?"]]
    cuts = [c for c in cuts if 0 < c <= max_len + 50]
    if cuts:
        snippet = snippet[: min(cuts) + 1]
    else:
        snippet = snippet[:max_len] + "…"
    return snippet.strip()


def _extract_contact(body: str | None) -> str:
    """본문에서 담당자 정보 1줄 추출.
    KISA: "담당부서 블록체인AI확산팀 전화 061-820-3938"
    IITP: "담당자 홍길동 (02-1234-5678)"
    """
    if not body or not isinstance(body, str):
        return ""
    import re as _re
    head = body[:800]  # KISA·IITP 머리말에 담당자 있음
    # 1) "담당부서 X 전화 NNN-NNNN-NNNN" 패턴
    m = _re.search(r"담당부서\s*([^\s].{0,30}?)\s*(?:전화|☎|TEL)\s*([\d\-\.\s]{8,18})", head)
    if m:
        dept = m.group(1).strip()
        tel = _re.sub(r"\s+", "", m.group(2)).strip(".-")
        return f"{dept} · {tel}"
    # 2) "문의 X (NNN-NNNN-NNNN)" 패턴
    m = _re.search(r"(?:문의처?|담당자)\s*[:：]?\s*([^\(\n]{1,30})\s*\(?\s*([\d]{2,4}-[\d]{3,4}-[\d]{4})", head)
    if m:
        who = m.group(1).strip().rstrip(":：")
        tel = m.group(2)
        return f"{who} · {tel}"
    # 3) 전화번호만이라도
    m = _re.search(r"(0\d{1,2}-\d{3,4}-\d{4})", head)
    if m:
        return m.group(1)
    return ""


# session_state로 KPI 클릭 ↔ 사이드바 슬라이더 동기화
if "min_score" not in st.session_state:
    st.session_state["min_score"] = 0
if "only_open" not in st.session_state:
    st.session_state["only_open"] = True
if "kw_filter" not in st.session_state:
    st.session_state["kw_filter"] = []
if "imminent_only" not in st.session_state:
    st.session_state["imminent_only"] = False
if "search_query" not in st.session_state:
    st.session_state["search_query"] = ""
if "sort_by" not in st.session_state:
    st.session_state["sort_by"] = "📅 최신 등록순"
if "eligibility_mode_label" not in st.session_state:
    st.session_state["eligibility_mode_label"] = "전체 (자격 미달 포함)"

# 정렬 옵션 (라벨 → 내부 키) — 사이드바 selectbox와 정렬 로직에서 공유
SORT_OPTIONS = {
    "📅 최신 등록순": "newest",
    "🌟 선정 예상 점수 높은순": "score",
    "⏰ 마감 임박순": "deadline",
}


def _normalize_kw(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def _dedup_keywords(raws) -> list[str]:
    """matched_keywords 리스트에서 normalize(공백 제거+lower) 기준 중복 제거.
    같은 개념의 변형(예: '정보보호' vs '정보 보호', 'AI 보안' vs 'AI보안')은
    keywords.yaml의 must_any 순서대로 가장 먼저 등장한 변형을 canonical로 유지.
    부서 매칭(`[부서] xxx`)은 그대로 통과.
    """
    seen: set[str] = set()
    out: list[str] = []
    for k in raws or []:
        if not isinstance(k, str):
            continue
        # 부서 매칭은 정규화 대상 아님 (이미 enum 정확 매칭)
        if k.startswith("[부서]"):
            if k not in seen:
                seen.add(k)
                out.append(k)
            continue
        n = _normalize_kw(k)
        if n in seen:
            continue
        seen.add(n)
        out.append(k)
    return out


def _collect_keywords(df_in) -> tuple[list[str], dict]:
    """모든 매칭 키워드 집계 (부서 매칭 제외).

    공백·대소문자 차이의 변형('정보보호'/'정보 보호', 'AI 보안'/'AI보안' 등)은
    하나의 개념으로 묶어 공고 단위로 unique 카운트. 표시명은 must_any 순서에서
    첫 등장한 변형을 사용 (keywords.yaml 작성자의 의도 반영).
    """
    canonical: dict[str, str] = {}   # norm → 표시용 raw
    counter: dict[str, int] = {}     # norm → 매칭된 공고 수 (변형 중복 제거)
    for mkj in df_in.get("matched_keywords_json", pd.Series(dtype=str)).fillna(""):
        if not mkj:
            continue
        try:
            mks = json.loads(mkj)
        except Exception:
            continue
        seen_norms: set[str] = set()
        for k in mks:
            if not isinstance(k, str) or k.startswith("[부서]"):
                continue
            n = _normalize_kw(k)
            if n not in canonical:
                canonical[n] = k     # 첫 등장 변형을 표시명으로 고정
            seen_norms.add(n)
        for n in seen_norms:
            counter[n] = counter.get(n, 0) + 1
    sorted_norms = sorted(counter.keys(), key=lambda x: -counter[x])
    sorted_kws = [canonical[n] for n in sorted_norms]
    counts = {canonical[n]: counter[n] for n in sorted_norms}
    return sorted_kws, counts


all_keywords, kw_counts = _collect_keywords(df)

# ─── 사이드바 필터 (3개 섹션) ───────────────────────────────────────────────
# 1. 기본 — 검색, 기관, 상태
st.sidebar.markdown("### 기본")
search_query = st.sidebar.text_input(
    "검색", key="search_query",
    placeholder="공고명·부서·키워드",
    help="제목·부서·요약·본문에서 자유 텍스트 검색 (공백·대소문자 무시)",
)
# 사용자 명시 7개 source 우선 표시 (불변 합의)
_REQUIRED_SRCS = ["iitp", "kisa", "kosa", "krit", "koica", "nipa", "mss"]
_db_srcs = set(df["source"].unique()) if not df.empty else set()
# 사용자 명시 7개를 항상 옵션에 포함 + 그 외 DB에 있는 source도 옵션 끝에
_options = [s for s in _REQUIRED_SRCS if s in _db_srcs or s in ("koica",)]  # KOICA는 0건이어도 옵션 유지
_extra = sorted(_db_srcs - set(_REQUIRED_SRCS))

# BMW 카드 그리드에서 클릭한 source (query_params로 전달) — 단일 source 모드
_qp_src = st.query_params.get("src")
if _qp_src and _qp_src in (_options + _extra):
    _default_srcs = [_qp_src]  # 단일 source만 활성 (카드 클릭으로 진입)
else:
    _default_srcs = _options    # 전체 (7개 모두)

# 오늘 등록 + 보안 통과 + 숨김 아님인 공고의 source별 카운트 → 사이드바 옵션 NEW 배지
_today = datetime.now().date()
if "posted_at_dt" in df.columns and not df.empty:
    _today_df = df[
        (df["posted_at_dt"].dt.date == _today)
        & (df.get("is_dismissed", False) == False)  # noqa: E712
    ]
    _today_by_src: dict[str, int] = _today_df["source"].value_counts().to_dict()
else:
    _today_by_src = {}

def _src_label(s: str) -> str:
    """source 옵션 표시 — 오늘 신규 있으면 🆕 N건 배지 부착."""
    name = s.upper() if s != "mss" else "중기부"
    n = _today_by_src.get(s, 0)
    return f"{name}  🆕 {n}" if n > 0 else name

sources = st.sidebar.multiselect(
    "기관 / 소스", _options + _extra,
    default=_default_srcs,
    format_func=_src_label,
)
only_open = st.sidebar.checkbox(
    "공모중만", key="only_open",
    help="공모 마감일이 지나지 않은 공고만 표시",
)
_ELIG_MODES = {
    "전체 (자격 미달 포함)": "all",
    "자격 가능만": "eligible_only",
    "자격 미달만 (참고용)": "blocked_only",
}
eligibility_mode_label = st.sidebar.selectbox(
    "자격 분류",
    list(_ELIG_MODES.keys()),
    key="eligibility_mode_label",
    help="회사 연차(2016년 설립 = 10년차)로 신청 가능한 공고만/미달만 분류",
)
eligibility_mode = _ELIG_MODES[eligibility_mode_label]

# 2. 점수 — 최소 점수
st.sidebar.markdown("### 점수")
min_score = st.sidebar.slider("최소 종합 점수", 0, 100, key="min_score")

# 3. 키워드 — 매칭 키워드 필터
st.sidebar.markdown("### 키워드")
selected_kws = st.sidebar.multiselect(
    "포함 키워드 (OR)", all_keywords, key="kw_filter",
    help="선택한 키워드 중 하나라도 매칭된 공고만. 상단 Top 패널에서도 클릭 가능",
)
# 정렬 selectbox는 카드 탭 본문에서 렌더 — session_state로 값 공유
sort_label = st.session_state.get("sort_by", "📅 최신 등록순")

# 점수 외 필터(source + only_open + search + keyword)를 적용한 base
base = df[df["source"].isin(sources)]
if only_open and "days_left" in base:
    base = base[base["days_left"].fillna(999) >= 0]
if eligibility_mode == "eligible_only" and "eligibility_status" in base.columns:
    # blocked 만 제거. unsure/ok/unknown/NULL 은 통과.
    base = base[base["eligibility_status"].fillna("unknown") != "blocked"]
elif eligibility_mode == "blocked_only" and "eligibility_status" in base.columns:
    # blocked 만 (자격 미달 공고 모음 — 추후 참고/검토용)
    base = base[base["eligibility_status"] == "blocked"]

# 자유 텍스트 검색 (제목·부서·요약·본문 — 모든 단어가 포함된 공고만)
if search_query and search_query.strip():
    tokens = [_normalize_kw(t) for t in search_query.split() if t.strip()]

    def _matches_search(row) -> bool:
        haystack = _normalize_kw(" ".join(
            str(row.get(c) or "")
            for c in ("title", "agency", "summary", "body")
        ))
        return all(tok in haystack for tok in tokens)

    base = base[base.apply(_matches_search, axis=1)]

# 키워드 필터 (OR 매칭, 공백·대소문자 무시)
if selected_kws:
    sel_norm = {_normalize_kw(k) for k in selected_kws}

    def _has_any_kw(mkj):
        if not mkj or not isinstance(mkj, str):
            return False
        try:
            mks = json.loads(mkj)
        except Exception:
            return False
        for m in mks:
            if isinstance(m, str) and _normalize_kw(m) in sel_norm:
                return True
        return False

    base = base[base["matched_keywords_json"].apply(_has_any_kw)]

# 마감 임박 필터 (KPI '🔴 마감 임박' 클릭으로 토글)
if st.session_state.get("imminent_only") and "days_left" in base:
    base = base[(base["days_left"].fillna(999) >= 0) & (base["days_left"].fillna(999) <= 7)]

filtered = base[base["total_score"].fillna(0) >= min_score]

# 정렬: 사이드바 selectbox 값에 따라 분기. 1순위가 같으면 점수 높은 순으로 2차 정렬.
sort_key = SORT_OPTIONS.get(sort_label, "newest")
if sort_key == "newest" and "posted_at_dt" in filtered.columns:
    # 최신 등록순 — 등록일 DESC, 동일 날짜는 점수 DESC, 없으면 맨 아래
    filtered = filtered.sort_values(
        ["posted_at_dt", "total_score"],
        ascending=[False, False],
        na_position="last",
        kind="mergesort",
    )
elif sort_key == "score":
    # 점수 높은순 — 점수 DESC, 동점은 최신 등록순으로
    sort_cols = ["total_score"]
    sort_asc = [False]
    if "posted_at_dt" in filtered.columns:
        sort_cols.append("posted_at_dt")
        sort_asc.append(False)
    filtered = filtered.sort_values(
        sort_cols, ascending=sort_asc,
        na_position="last", kind="mergesort",
    )
elif sort_key == "deadline" and "deadline_at_dt" in filtered.columns:
    # 마감 임박순 — 마감일 ASC(가까운 게 위), 동일은 점수 DESC, 마감일 없으면 맨 아래
    filtered = filtered.sort_values(
        ["deadline_at_dt", "total_score"],
        ascending=[True, False],
        na_position="last",
        kind="mergesort",
    )

st.sidebar.markdown("---")
st.sidebar.caption(f"표시 중 {len(filtered)} / 전체 {len(df)}")

# ─── Top app bar ──────────────────────────────────────────────────────────
_today_n = int((df.get("posted_at_dt", pd.Series(dtype="datetime64[ns]"))
                .dt.date == datetime.now().date()).sum()) if "posted_at_dt" in df else 0
# BMW 식 큰 상단 헤더 — 회색 배경 위 흰 카드, 큰 타이틀 + 부제
_appbar_html = f"""
<div style="background:#ffffff;padding:32px 36px;margin:-8px -8px 24px;
            border-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,0.05)">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              flex-wrap:wrap;gap:16px">
    <div>
      <div style="color:#999;font-size:12px;letter-spacing:0.05em;margin-bottom:6px;
                  font-weight:500">대시보드 · RFP-Targeter</div>
      <h1 style="font-size:1.75rem;font-weight:800;color:#111;
                 letter-spacing:-0.025em;margin:0;line-height:1.2">
        RFP 공고 탐색 &amp; 점수 비교
      </h1>
      <div style="color:#666;font-size:0.95rem;margin-top:8px;line-height:1.5;max-width:680px">
        7개 정부기관(IITP·KISA·NIPA·MSS·KOSA·KRIT·KOICA)에서 발주한 RFP 공고를
        엔키화이트햇 본업 적합도 5축으로 자동 점수화.
      </div>
    </div>
    <div style="text-align:right;flex-shrink:0">
      <div style="font-size:2rem;font-weight:800;color:#111;letter-spacing:-0.03em;
                  line-height:1;font-feature-settings:'tnum'">{len(df):,}<span style="font-size:0.5em;color:#666;font-weight:500;margin-left:4px">건</span></div>
      <div style="color:#666;font-size:12px;margin-top:6px;display:flex;
                  align-items:center;gap:10px;justify-content:flex-end">
        <span><span style="display:inline-block;width:6px;height:6px;border-radius:50%;
                           background:#10b981;margin-right:5px"></span>
          오늘 +{_today_n}건
        </span>
        <span style="color:#ccc">·</span>
        <span>{datetime.now().strftime('%m.%d %H:%M')}</span>
      </div>
    </div>
  </div>
</div>
"""
st.html(_appbar_html)

# ─── 7개 기관 상태 실시간 모니터 ─────────────────────────────────────
# 사용자 명시 (불변): KISA · KOSA · IITP · KRIT · KOICA · NIPA · MSS
# 각 기관별 DB 건수 + 첨부 추출률 + 첨부 누락 자동 감지 표시
@st.cache_data(ttl=60)
def _source_health() -> list[dict]:
    """모든 source의 건수 + 첨부 추출률 조회."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT source, COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE attachments_json IS NOT NULL
                                           AND attachments_json NOT IN ('','[]')) AS with_att,
                          MAX(updated_at) AS last_upd
                   FROM announcement GROUP BY source"""
            )
            return [dict(r) for r in cur.fetchall()]


_health = {h["source"]: h for h in _source_health()}
_REQ7 = [("iitp","IITP"), ("kisa","KISA"), ("nipa","NIPA"), ("mss","중기부"),
         ("kosa","KOSA"), ("krit","KRIT"), ("koica","KOICA")]

# 활성 source — query_params로 단일 선택, 빈 값이면 전체
_qp = st.query_params
_active_src = _qp.get("src") or None
if _active_src and _active_src not in {s for s, _ in _REQ7}:
    _active_src = None

# BMW 식 카테고리 그리드 — 7개 발주기관을 큰 클릭 카드로
_cards_html = []
for src, label in _REQ7:
    h = _health.get(src, {"total": 0, "with_att": 0})
    total = int(h.get("total") or 0)
    with_att = int(h.get("with_att") or 0)
    att_rate = int(100 * with_att / total) if total else 0
    if total == 0:
        dot_color, status_txt = "#ef4444", "수집 대기"
    elif src in ("kosa", "krit") and total > 0:
        dot_color, status_txt = "#10b981", "정상"
    elif total > 5 and att_rate < 30:
        dot_color, status_txt = "#f59e0b", f"첨부 {att_rate}%"
    else:
        dot_color, status_txt = "#10b981", "정상"

    is_active = (_active_src == src)
    bg = "#111" if is_active else "#fff"
    text_color = "#fff" if is_active else "#111"
    sub_color = "#bbb" if is_active else "#666"
    border = "#111" if is_active else "#d4d4d4"

    # 오늘 신규 등록 N건 — 사이드바 multiselect와 동일 카운트 (위에서 계산)
    _new_n = _today_by_src.get(src, 0)
    new_badge = (
        f"<span style='position:absolute;top:-6px;right:-6px;"
        f"background:#dc2626;color:#fff;font-size:10px;font-weight:800;"
        f"letter-spacing:0.04em;padding:2px 6px;border-radius:10px;"
        f"box-shadow:0 1px 3px rgba(220,38,38,0.4);line-height:1.2;"
        f"min-width:36px;text-align:center'>🆕 {_new_n}</span>"
        if _new_n > 0 else ""
    )

    # 클릭 토글: 같은 카드면 해제, 다른 카드면 그것 활성
    next_qp = "" if is_active else f"?src={src}"
    _cards_html.append(
        f"<a href='{next_qp}' target='_self' style='text-decoration:none;flex:1'>"
        f"<div style='background:{bg};border:1px solid {border};"
        f"border-radius:2px;padding:14px 12px;min-width:0;cursor:pointer;"
        f"transition:all 0.15s ease;position:relative'>"
        f"{new_badge}"
        f"<div style='display:flex;align-items:center;justify-content:space-between;"
        f"margin-bottom:8px'>"
        f"<span style='font-weight:700;color:{text_color};font-size:14px;"
        f"letter-spacing:0.02em'>{label}</span>"
        f"<span style='width:6px;height:6px;border-radius:50%;background:{dot_color};"
        f"flex-shrink:0'></span>"
        f"</div>"
        f"<div style='font-size:1.4rem;font-weight:800;color:{text_color};"
        f"letter-spacing:-0.03em;line-height:1;font-feature-settings:\"tnum\"'>"
        f"{total:,}<span style='font-size:0.55em;color:{sub_color};font-weight:500;"
        f"margin-left:3px'>건</span></div>"
        f"<div style='color:{sub_color};font-size:11px;margin-top:4px'>{status_txt}</div>"
        f"</div></a>"
    )

# 액션 라벨 (활성 source 있을 때)
_action_txt = (
    f"<a href='?' target='_self' style='color:#0066b1;font-size:12px;font-weight:600;"
    f"text-decoration:none'>전체 보기 ↩</a>"
    if _active_src else
    "<span style='color:#999;font-size:11px'>카드 클릭 시 해당 기관만 필터링</span>"
)
st.html(
    "<div style='background:#fff;border-radius:2px;padding:16px;"
    "box-shadow:0 1px 3px rgba(0,0,0,0.06);margin-bottom:20px'>"
    "<div style='display:flex;align-items:center;justify-content:space-between;"
    "margin-bottom:12px'>"
    "<span style='color:#666;font-size:11px;font-weight:600;letter-spacing:0.08em;"
    "text-transform:uppercase'>발주기관 — 카드 클릭으로 필터</span>"
    f"{_action_txt}"
    "</div>"
    "<div style='display:grid;grid-template-columns:repeat(7,1fr);gap:8px'>"
    + "".join(_cards_html)
    + "</div></div>"
)

# ---------- KPI Stats Strip ----------
# 카운트는 base 기준 — 현재 사이드바 필터(source+only_open) 적용 후 카드 수와 일치
def _count(threshold: int) -> int:
    return int((base["total_score"].fillna(0) >= threshold).sum())

total_n = len(base)
# 임계값을 새 점수 분포에 맞춰 60/75/90으로 상향 — 변별력 확보
# (이전 50/60/70은 50점 이상이 74% 차지해 'Fair' 의미 약함)
n_fair = _count(60)
n_good = _count(75)
n_top  = _count(90)
imminent = int(
    ((base.get("days_left", pd.Series(dtype=float)).fillna(999) >= 0) &
     (base.get("days_left", pd.Series(dtype=float)).fillna(999) <= 7)).sum()
)


def _set_min_score(value: int) -> None:
    """on_click 콜백: widget instantiated 후엔 직접 session_state 수정 불가하므로 콜백 사용."""
    st.session_state["min_score"] = value


def _toggle_imminent() -> None:
    st.session_state["imminent_only"] = not st.session_state.get("imminent_only", False)


imm_active = st.session_state.get("imminent_only", False)
cur_min = st.session_state.get("min_score", 0)


# KPI 카드 — 발주기관 카드와 동일 톤 (italic 제거, 일반 폰트로 통일)
def _kpi_label(name: str, value: int, sub: str) -> str:
    return f"{name}  \n**{value:,}** 건  \n{sub}"


k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.button(
        _kpi_label("전체 공고", total_n, f"오늘 신규 {_today_n}건"),
        key="kpi_all", on_click=_set_min_score, args=(0,),
        use_container_width=True,
        type="primary" if cur_min == 0 else "secondary",
        help="전체 공고 표시 (점수 0점 이상)",
    )
with k2:
    st.button(
        _kpi_label("Fair · 60점+", n_fair,
                   f"전체의 {int(100*n_fair/max(total_n,1))}%"),
        key="kpi_fair", on_click=_set_min_score, args=(60,),
        use_container_width=True,
        type="primary" if cur_min == 60 else "secondary",
        help="검토 고려할 수준의 공고만",
    )
with k3:
    st.button(
        _kpi_label("Good · 75점+", n_good,
                   f"전체의 {int(100*n_good/max(total_n,1))}%"),
        key="kpi_good", on_click=_set_min_score, args=(75,),
        use_container_width=True,
        type="primary" if cur_min == 75 else "secondary",
        help="적극 검토 권장 수준",
    )
with k4:
    st.button(
        _kpi_label("Top · 90점+", n_top,
                   f"전체의 {int(100*n_top/max(total_n,1))}%"),
        key="kpi_top", on_click=_set_min_score, args=(90,),
        use_container_width=True,
        type="primary" if cur_min == 90 else "secondary",
        help="우선 수주 대상 수준",
    )
with k5:
    st.button(
        _kpi_label("마감 임박 (7일내)", imminent,
                   "필터 적용 중" if imm_active else "클릭해서 필터"),
        key="kpi_imminent", on_click=_toggle_imminent,
        use_container_width=True,
        type="primary" if imm_active else "secondary",
        help="마감 7일 이내 공고만 / 다시 클릭 시 해제",
    )


# ---------- 자주 매칭되는 키워드 (클릭하여 필터 추가/제거) ----------
def _toggle_kw(kw: str) -> None:
    current = list(st.session_state.get("kw_filter", []))
    if kw in current:
        current.remove(kw)
    else:
        current.append(kw)
    st.session_state["kw_filter"] = current


TOP_N = 15
top_kws = all_keywords[:TOP_N]
if top_kws:
    with st.expander(f"🏷️ 자주 매칭되는 키워드 Top {len(top_kws)} — 클릭하면 필터에 추가/제거", expanded=False):
        active = set(st.session_state.get("kw_filter", []))
        per_row = 5
        for start in range(0, len(top_kws), per_row):
            cols = st.columns(per_row)
            for i, kw in enumerate(top_kws[start:start + per_row]):
                cnt = kw_counts.get(kw, 0)
                is_active = kw in active
                label = f"{'✅ ' if is_active else ''}{kw} ({cnt})"
                with cols[i]:
                    st.button(label, key=f"kwbtn_{start + i}",
                              on_click=_toggle_kw, args=(kw,),
                              use_container_width=True,
                              type="primary" if is_active else "secondary")
        if active:
            st.caption(f"✓ 활성 키워드: {', '.join(sorted(active))} (사이드바 'X' 클릭 또는 다시 클릭으로 제거)")

# ---------- 활성 필터 칩 바 ----------
def _reset_all_filters() -> None:
    st.session_state["search_query"] = ""
    st.session_state["min_score"] = 0
    st.session_state["kw_filter"] = []
    st.session_state["imminent_only"] = False
    st.session_state["eligibility_mode_label"] = "전체 (자격 미달 포함)"
    # only_open은 사용자가 일부러 켜둔 default라 유지


_CHIP_NORMAL = ("background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;"
                "padding:3px 9px;border-radius:6px;font-size:0.8rem;font-weight:500;"
                "display:inline-block;margin-right:4px")
_CHIP_WARN   = ("background:#fff7ed;color:#c2410c;border:1px solid #fed7aa;"
                "padding:3px 9px;border-radius:6px;font-size:0.8rem;font-weight:500;"
                "display:inline-block;margin-right:4px")

_active_chips: list[str] = []
if search_query and search_query.strip():
    _active_chips.append(f"<span style='{_CHIP_NORMAL}'>검색 · {search_query.strip()[:24]}</span>")
if sources and len(sources) != len(df["source"].unique()):
    _active_chips.append(f"<span style='{_CHIP_NORMAL}'>기관 · {', '.join(sources)}</span>")
if min_score > 0:
    _active_chips.append(f"<span style='{_CHIP_NORMAL}'>≥{min_score}점</span>")
if selected_kws:
    _kw_disp = ', '.join(selected_kws[:3]) + (f' 외 {len(selected_kws)-3}' if len(selected_kws) > 3 else '')
    _active_chips.append(f"<span style='{_CHIP_NORMAL}'>키워드 · {_kw_disp}</span>")
if imm_active:
    _active_chips.append(f"<span style='{_CHIP_WARN}'>마감 ≤ 7일</span>")
if eligibility_mode == "eligible_only":
    _active_chips.append(f"<span style='{_CHIP_NORMAL}'>자격 가능만</span>")
elif eligibility_mode == "blocked_only":
    _active_chips.append(f"<span style='{_CHIP_WARN}'>자격 미달만 (참고용)</span>")

_FILTER_BAR_STYLE = ("display:flex;flex-wrap:wrap;gap:6px;align-items:center;"
                     "padding:10px 14px;background:#ffffff;border:1px solid #f1f5f9;"
                     "border-radius:12px;margin-bottom:14px;font-size:0.85rem")

_fc1, _fc2 = st.columns([8, 1])
with _fc1:
    if _active_chips:
        st.html(
            f"<div style='{_FILTER_BAR_STYLE}'>"
            f"<span style='color:#64748b;font-weight:600;margin-right:4px'>적용 중</span>"
            + " ".join(_active_chips)
            + "</div>"
        )
    else:
        st.html(
            f"<div style='{_FILTER_BAR_STYLE}'>"
            f"<span style='color:#94a3b8;font-style:italic'>적용 중인 필터 없음 — 사이드바에서 좁혀보세요</span>"
            f"</div>"
        )
with _fc2:
    st.button("전체 해제", on_click=_reset_all_filters, use_container_width=True,
              disabled=not _active_chips)

# ---------- 공고 카드 + 디테일 ----------
tab1, tab2, tab3, tab4 = st.tabs([
    f"공고 카드  {len(filtered):,}",
    "점수 비교",
    "점수 기준",
    "회사 프로필",
])

PAGE_SIZE = 10
if "current_page" not in st.session_state:
    st.session_state["current_page"] = 1

# AI 초안 확인 다이얼로그 상태
if "_ai_confirm_id" not in st.session_state:
    st.session_state["_ai_confirm_id"] = None
if "_ai_running" not in st.session_state:
    st.session_state["_ai_running"] = False


def _build_announcement_from_row(row):
    """DataFrame row → Announcement·Score 안전 변환."""
    def _ns(v, default=None):
        return default if v is None or (isinstance(v, float) and pd.isna(v)) else v
    mkj = _ns(row.get("matched_keywords_json"), "[]")
    rj = _ns(row.get("rationale_json"), "{}")
    a = Announcement(
        source=row["source"], external_id=row["external_id"],
        title=_ns(row.get("title"), ""), url=_ns(row.get("url"), ""),
        agency=_ns(row.get("agency")), posted_at=_ns(row.get("posted_at")),
        deadline_at=_ns(row.get("deadline_at")),
        budget_mw=_ns(row.get("budget_mw")),
        duration_months=_ns(row.get("duration_months")),
        summary=_ns(row.get("summary")), body=_ns(row.get("body")),
        matched_keywords=json.loads(mkj),
        attachments=json.loads(_ns(row.get("attachments_json"), "[]")),
        is_security=True,
    )
    s = Score(
        announcement_id=a.id,
        keyword_score=_ns(row.get("keyword_score"), 0),
        budget_score=_ns(row.get("budget_score"), 0),
        consortium_score=_ns(row.get("consortium_score"), 0),
        competitor_score=_ns(row.get("competitor_score"), 0),
        trl_score=_ns(row.get("trl_score"), 0),
        total_score=_ns(row.get("total_score"), 0),
        theme_fit=_ns(row.get("theme_fit"), 0),
        rationale=json.loads(rj),
    )
    return a, s


@st.dialog("초안 생성 확인")
def _ai_confirm_dialog():
    aid = st.session_state.get("_ai_confirm_id")
    if not aid:
        return
    row_match = df[df["id"] == aid]
    if row_match.empty:
        st.error("공고 정보를 찾을 수 없습니다.")
        if st.button("닫기"):
            st.session_state["_ai_confirm_id"] = None
            st.rerun()
        return
    row = row_match.iloc[0]

    # 실행 중 화면
    if st.session_state.get("_ai_running"):
        st.markdown(f"**{row['title'][:60]}**")
        with st.spinner("Claude로 작성 중 · 30~120초 소요"):
            try:
                a2, s2 = _build_announcement_from_row(row)
                path = generate_draft(a2, s2, use_llm=True)
                try:
                    rel = path.relative_to(Path.cwd())
                except ValueError:
                    rel = path
                st.success("초안 작성 완료")
                st.code(str(rel), language=None)
                st.caption("위 경로의 파일을 열어 확인 — 브레인스토밍 + 자동 선택 + 표준 6목차 뼈대 포함")
            except Exception as e:
                st.error(f"실패: {e}")
                if "anthropic" in str(e).lower() or "api_key" in str(e).lower() or "미설정" in str(e):
                    st.info("`config/secrets.yaml` 의 `anthropic.api_key` 입력 필요. console.anthropic.com 에서 발급.")
        st.session_state["_ai_running"] = False
        if st.button("닫기", type="primary", use_container_width=True):
            st.session_state["_ai_confirm_id"] = None
            st.rerun()
        return

    # 양식 첨부 여부로 토큰 추정 조정
    try:
        atts = json.loads(row.get("attachments_json") or "[]")
        has_form = any((x.get("category") or "") == "form" for x in atts if isinstance(x, dict))
    except Exception:
        has_form = False

    from rfp_targeter.drafter.llm_writer import estimate_cost_range
    cost_lo, cost_hi = estimate_cost_range(has_form=has_form)
    krw_lo = int(cost_lo * 1400)
    krw_hi = int(cost_hi * 1400)
    krw_mid = (krw_lo + krw_hi) // 2

    # 미니멀 본문 — 사용자가 원했던 "정말 초안을 작성하시겠습니까? 소모비용은 약 xx원입니다" 톤
    st.markdown(
        f"<div style='color:#475569;font-size:0.9em;margin-bottom:8px'>공고</div>"
        f"<div style='font-weight:600;color:#0f172a;margin-bottom:18px;line-height:1.4'>{row['title']}</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:18px 20px;margin-bottom:18px'>
  <div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px'>
    <span style='color:#475569;font-size:0.88em'>예상 비용</span>
    <span style='color:#0f172a;font-size:1.35em;font-weight:700;letter-spacing:-0.02em'>약 {krw_mid:,}원</span>
  </div>
  <div style='color:#94a3b8;font-size:0.82em;text-align:right'>{krw_lo:,} ~ {krw_hi:,}원 · Claude API 호출 후 실비 청구</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        "<div style='color:#64748b;font-size:0.88em;margin-bottom:18px'>"
        "작성에 30~120초 소요됩니다. 회사 Anthropic 계정으로 후불 청구."
        "</div>",
        unsafe_allow_html=True,
    )

    col_a, col_b = st.columns(2)
    if col_a.button("작성 시작", type="primary", use_container_width=True):
        st.session_state["_ai_running"] = True
        st.rerun()
    if col_b.button("취소", use_container_width=True):
        st.session_state["_ai_confirm_id"] = None
        st.rerun()


# ─── 카드·다이얼로그 공통 시각 헬퍼 (양쪽에서 사용 → module-level) ──────
def _score_band_class(total: float) -> str:
    # 임계값: ≥90 Top / ≥75 Good / ≥60 Fair (분포에 맞게 조정)
    if total >= 90: return "band-top"
    if total >= 75: return "band-high"
    if total >= 60: return "band-mid"
    return "band-low"


_BADGE_BASE = ("display:inline-block;padding:4px 10px;border-radius:999px;"
               "font-size:0.72rem;font-weight:700;letter-spacing:0.02em;border:1px solid")


def _status_badge(total: float) -> str:
    # 임계값 60/75/90 (KPI 카드 + 좌측 밴드와 동일)
    if total >= 90:
        return (f"<span style='{_BADGE_BASE} #fdba74;background:#fff7ed;color:#c2410c'>"
                f"TOP · 즉시 우선 검토</span>")
    if total >= 75:
        return (f"<span style='{_BADGE_BASE} #86efac;background:#f0fdf4;color:#15803d'>"
                f"GOOD · 검토 권장</span>")
    if total >= 60:
        return (f"<span style='{_BADGE_BASE} #fde047;background:#fefce8;color:#a16207'>"
                f"FAIR · 검토 고려</span>")
    return (f"<span style='{_BADGE_BASE} #cbd5e1;background:#f8fafc;color:#64748b'>"
            f"LOW · 참고</span>")


def _axis_color(v: float) -> str:
    if v >= 70: return "#22c55e"
    if v >= 50: return "#eab308"
    if v >= 30: return "#94a3b8"
    return "#ef4444"


def _axes_progress_html(kw_s, bg_s, cs_s, cp_s, tr_s) -> str:
    """5축 점수 mini progress bar — inline style (CSS class fallback 회피)."""
    rows = [
        ("키워드 적합도",   kw_s),
        ("예산 적합도",     bg_s),
        ("컨소시엄 부담",   cs_s),
        ("경쟁 강도",       cp_s),
        ("기술 성숙도",     tr_s),
    ]
    out = ("<div style='display:flex;flex-direction:column;gap:8px;margin-top:14px'>")
    for name, v in rows:
        v = float(v or 0)
        c = _axis_color(v)
        out += (
            "<div style='display:grid;grid-template-columns:96px 1fr 36px;"
            "gap:10px;align-items:center;font-size:0.78rem;color:#334155'>"
            f"<span style='font-weight:500'>{name}</span>"
            f"<div style='height:6px;background:#f1f5f9;border-radius:999px;overflow:hidden'>"
            f"  <div style='height:100%;width:{v:.0f}%;background:{c};border-radius:999px'></div>"
            f"</div>"
            f"<span style='text-align:right;font-weight:700;color:#0f172a;"
            f"font-feature-settings:&quot;tnum&quot; on'>{v:.0f}</span>"
            "</div>"
        )
    out += "</div>"
    return out


def _open_detail(aid: int) -> None:
    st.session_state["_detail_id"] = aid


if "_detail_id" not in st.session_state:
    st.session_state["_detail_id"] = None


# ─── 기관 메타 — 네이버 톤 단정한 컬러 (채도 낮춤, 일관된 명도) ─────────
_AGENCY_META = {
    "kisa":   {"label": "KISA",   "name": "한국인터넷진흥원",       "color": "#0284c7", "bg": "#f0f9ff", "icon": ""},
    "iitp":   {"label": "IITP",   "name": "정보통신기획평가원",     "color": "#2563eb", "bg": "#eff6ff", "icon": ""},
    "ntis":   {"label": "NTIS",   "name": "국가과학기술지식정보",   "color": "#4f46e5", "bg": "#eef2ff", "icon": ""},
    "kosa":   {"label": "KOSA",   "name": "한국SW산업협회",         "color": "#7c3aed", "bg": "#f5f3ff", "icon": ""},
    "nipa":   {"label": "NIPA",   "name": "정보통신산업진흥원",     "color": "#0891b2", "bg": "#ecfeff", "icon": ""},
    "krit":   {"label": "KRIT",   "name": "국방기술진흥연구소",     "color": "#65a30d", "bg": "#f7fee7", "icon": ""},
    "mss":    {"label": "MSS",    "name": "중소벤처기업부",         "color": "#ea580c", "bg": "#fff7ed", "icon": ""},
    "koica":  {"label": "KOICA",  "name": "한국국제협력단",         "color": "#16a34a", "bg": "#f0fdf4", "icon": ""},
    "bizinfo":{"label": "bizinfo","name": "기업마당",               "color": "#6b7280", "bg": "#f9fafb", "icon": ""},
}


def _agency_badge_html(source: str, agency: str | None = None) -> str:
    """발주기관 라벨 — 네이버 검색결과 카드 톤 (작은 컬러 prefix + 풀네임 텍스트)."""
    meta = _AGENCY_META.get(source, {
        "label": source.upper(), "name": agency or "", "color": "#6b7280",
        "bg": "#f3f4f6", "icon": "",
    })
    full = meta["name"]
    if agency and agency.strip() and agency.strip() not in (meta["label"], full):
        full = agency.strip()
    import html as _h
    color = meta["color"]
    label = _h.escape(meta["label"])
    name = _h.escape(full)
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;"
        f"font-size:13px;line-height:1.4'>"
        f"<span style='background:{color};color:#fff;padding:1px 7px;"
        f"border-radius:3px;font-weight:600;font-size:11px;"
        f"letter-spacing:0.04em'>{label}</span>"
        f"<span style='color:var(--text-muted);font-weight:400'>{name}</span>"
        f"</span>"
    )


def _is_today_new(posted_at_str) -> bool:
    """공고 등록일이 오늘인지."""
    if not posted_at_str or pd.isna(posted_at_str):
        return False
    try:
        ts = pd.to_datetime(posted_at_str, errors="coerce")
        if pd.isna(ts):
            return False
        return ts.date() == datetime.now().date()
    except Exception:
        return False


# ─── 상세 보기 — 카드 아래에 inline으로 펼쳐짐 (dialog 폐기, 첫 버전처럼) ──
def _render_detail_inline(row, aid):
    """[상세 보기] 토글 시 카드 안에 펼쳐지는 풀 디테일."""
    import html as _h
    rationale = json.loads(row.get("rationale_json") or "{}")
    axes_names = ["키워드", "예산", "컨소시엄", "경쟁자", "TRL"]
    vals = [
        float(row.get("keyword_score") or 0),
        float(row.get("budget_score") or 0),
        float(row.get("consortium_score") or 0),
        float(row.get("competitor_score") or 0),
        float(row.get("trl_score") or 0),
    ]

    # 시각 구분선 + 헤더
    st.html(
        "<div style='border-top:1px solid var(--border);margin:14px 0 12px'></div>"
        "<div style='color:var(--text-muted);font-size:0.72rem;font-weight:700;"
        "letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px'>"
        "📐 상세 정보</div>"
    )

    # 5축 레이더 + 산정 근거
    fig = go.Figure(go.Scatterpolar(
        r=vals + [vals[0]], theta=axes_names + [axes_names[0]],
        fill="toself",
        line=dict(color="#3b82f6", width=2),
        fillcolor="rgba(59,130,246,0.20)",
        name=str(row.get("title", ""))[:30],
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100],
                            gridcolor="#e2e8f0",
                            tickfont=dict(size=10, color="#64748b"),
                            tickvals=[20, 40, 60, 80, 100]),
            angularaxis=dict(tickfont=dict(size=11, color="#0f172a"),
                             gridcolor="#f1f5f9"),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=False, height=300,
        margin=dict(l=40, r=40, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Pretendard Variable, Pretendard, sans-serif"),
    )

    rc1, rc2 = st.columns([1, 1])
    with rc1:
        st.plotly_chart(fig, use_container_width=True, key=f"radar_inline_{aid}")
        st.html(_axes_progress_html(*vals))
    with rc2:
        st.markdown("**산정 근거**")
        any_rationale = False
        for k, label in [
            ("keyword", "키워드"), ("budget", "예산"),
            ("consortium", "컨소시엄"), ("competitor", "경쟁"),
            ("trl", "TRL"), ("theme_fit", "테마"),
        ]:
            reasons = rationale.get(k) or []
            if reasons:
                any_rationale = True
                st.markdown(
                    f"<div style='font-size:0.86em;margin-bottom:6px'>"
                    f"<b>{label}</b> · "
                    f"<span style='color:var(--text-muted)'>{' / '.join(reasons)}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        if not any_rationale:
            st.caption("산정 근거 데이터가 없어요 — 점수만 표시됩니다.")

    # 예산 근거 — 본문 발췌 (hallucination 방지)
    bud_excerpt = row.get("budget_excerpt")
    bud_mw = row.get("budget_mw")
    if bud_excerpt and pd.notna(bud_excerpt):
        bud_period = row.get("budget_period") or "단년"
        bud_conf = row.get("budget_confidence") or "medium"
        # 금액 사람친화 포맷
        try:
            bud_val = int(bud_mw)
            if bud_val >= 1000:
                bud_str = f"{bud_val/1000:.1f}".rstrip("0").rstrip(".") + "억원"
            else:
                bud_str = f"{bud_val}백만원"
        except Exception:
            bud_str = "?"
        conf_color = "#10b981" if bud_conf == "high" else "#f59e0b"
        conf_label = "높음" if bud_conf == "high" else "보통"
        st.html(
            "<div style='color:var(--text-muted);font-size:0.72rem;font-weight:700;"
            "letter-spacing:0.08em;text-transform:uppercase;margin:14px 0 6px'>"
            "💰 예산 근거 (본문 발췌)</div>"
            f"<div style='background:#f0f9ff;border-left:3px solid #0369a1;padding:10px 14px;"
            f"border-radius:6px;font-size:0.88em;line-height:1.6'>"
            f"<div style='display:flex;gap:10px;align-items:center;margin-bottom:6px;flex-wrap:wrap'>"
            f"<span style='font-size:1.1em;font-weight:700;color:#0369a1'>{bud_str}</span>"
            f"<span style='background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;"
            f"font-size:0.85em;font-weight:600'>{bud_period}</span>"
            f"<span style='background:{conf_color}1a;color:{conf_color};padding:2px 8px;border-radius:4px;"
            f"font-size:0.85em;font-weight:600'>신뢰도 {conf_label}</span>"
            f"</div>"
            f"<div style='color:var(--text-soft);font-size:0.93em;font-style:italic'>"
            f"“…{_h.escape(str(bud_excerpt))}…”</div>"
            f"<div style='color:var(--text-faint);font-size:0.78em;margin-top:6px'>"
            f"※ 위 발췌는 본문에서 그대로 가져온 원문입니다. 추정·계산값 아닙니다.</div>"
            f"</div>"
        )

    # 본문 — 정부 공문 마커(□○※①…) 기준 줄바꿈 + HTML 엔티티 디코드
    body = row.get("body") or row.get("summary")
    if body and pd.notna(body) and isinstance(body, str):
        st.html(
            "<div style='color:var(--text-muted);font-size:0.72rem;font-weight:700;"
            "letter-spacing:0.08em;text-transform:uppercase;margin:14px 0 4px'>"
            "📄 본문</div>"
        )

        import re as _re_local
        clean = _h.unescape(body)
        clean = clean.replace("​", "").replace("\xa0", " ")
        clean = _re_local.sub(r"\s+", " ", clean)
        clean = _re_local.sub(r"\[첨부 본문\]\s*", "", clean)

        # KISA·정부 사이트 chrome 텍스트 제거 (메뉴·공유·navigation 잡음)
        _CHROME_PATTERNS = [
            r"알림마당\s*입찰공고\s*인쇄하기\s*공유하기\s*닫기\s*트위터\s*페이스북",
            r"인쇄하기\s*공유하기\s*닫기\s*트위터\s*페이스북",
            r"공유하기\s*닫기\s*트위터\s*페이스북",
            r"등록일\s*\d{4}-\d{2}-\d{2}\s*조회\s*\d+",
            r"바로가기\s*메뉴\s*본문\s*바로가기\s*주메뉴\s*바로가기\s*푸터\s*바로가기",
            r"이전\s*글\s*다음\s*글\s*목록",
            r"※\s*입찰설명회는\s*별도\s*진행하지\s*않으며.{0,200}?변경될\s*수\s*있습니다\s*\.",  # 너무 긴 boilerplate
            # === KOSA(sw.or.kr) 네비 메뉴 — "바로가기 메뉴 ... 채용안내" 까지가 사이트 전체 메뉴
            #     실제 본문은 "공지사항 상세정보 보기 제목" 부터 시작. 그 앞까지 통째로 제거.
            r"바로가기\s*메뉴\s*본문\s*바로가기\s*주메뉴.*?(?=공지사항\s*상세정보\s*보기|상세정보\s*보기)",
            r"KOSA\s*Menu\s*회원가입\s*로그인\s*KOSA\s*전체메뉴.*?(?=알림마당\s*협회에서)",
            r"알림마당\s*협회에서\s*활동하고\s*있는\s*다양한\s*소식을\s*알려\s*드립니다\s*\.\s*글씨크게.*?(?=공지사항\s*상세정보|제목\s)",
            # KOSA 푸터 — "이용약관 ... 사업자번호" 이후 끝까지
            r"이용약관\s*개인정보처리방침\s*찾아오시는\s*길\s*사이트맵.*$",
            # 빈 메타 라인 ("이전글 목록 다음글", "구분 공지사항")
            r"이전글\s*목록\s*다음글",
        ]
        for pat in _CHROME_PATTERNS:
            clean = _re_local.sub(pat, " ", clean, flags=_re_local.DOTALL)
        # ===== 같은 구분선 (3자 이상 반복) 제거
        clean = _re_local.sub(r"[=\-_*]{4,}", " ", clean)
        # 공백 다시 정규화
        clean = _re_local.sub(r"\s+", " ", clean).strip()

        # ──────────────────────────────────────────────────────
        # 정부 사이트 HTML→텍스트 변환 잡음 정리 (KISA 본문 가독성)
        # ──────────────────────────────────────────────────────
        # 1) 날짜 패턴만 좁게 압축 — "2026. 6. 9. 11 : 00" → "2026.6.9. 11:00"
        #    "2026. 12. 31. 2. 낙찰자" 같은 케이스에서 31.과 2. 가 붙지 않게.
        #    년(4자리) + 점 + 월(1~2) + 점 + 일(1~2) + 점 — 정확히 날짜만 매칭
        clean = _re_local.sub(
            r"(\d{4})\.\s+(\d{1,2})\.\s+(\d{1,2})\.", r"\1.\2.\3.", clean,
        )
        # 시각: HH:MM — 콜론 양옆 공백만
        clean = _re_local.sub(r"(\d{1,2})\s*:\s*(\d{2})", r"\1:\2", clean)
        # 2) 한글 한 글자씩 띄어 있는 표 헤더: "사 업 기 간" → "사업기간"
        #    2~5자 한글이 모두 공백으로 분리된 경우 (실제 글자 띄어쓰기는 1글자만 분리되는 일이 거의 없음)
        clean = _re_local.sub(r"(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])", r"\1\2\3\4", clean)
        clean = _re_local.sub(r"(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])", r"\1\2\3", clean)
        # 3) 숫자 + 한글 단위 공백: "2026 년", "10 일", "1 개월", "100 건"
        clean = _re_local.sub(
            r"(\d)\s+(년|월|일|시|분|초|개월|주|건|명|회|차|호|위|등|급|점|배|배수|만|억|원|%|％)",
            r"\1\2", clean,
        )
        # 4) 콤마 자릿수 + "원" 사이 공백: "332,000,000 원" → "332,000,000원"
        clean = _re_local.sub(r"(\d{1,3}(?:,\d{3})+)\s+원", r"\1원", clean)
        # 5) 괄호 내부 공백 압축: "( 부가세포함 )" → "(부가세포함)"
        clean = _re_local.sub(r"\(\s+", "(", clean)
        clean = _re_local.sub(r"\s+\)", ")", clean)
        # 6) 따옴표 내부 공백: '" 협상에 의한 "' → '"협상에 의한"'
        clean = _re_local.sub(r'"\s+', '"', clean)
        clean = _re_local.sub(r'\s+"', '"', clean)
        # 7) 번호 점 분리: "1 ." "2 ." → "1." "2." (목차 번호)
        clean = _re_local.sub(r"(\d)\s+\.\s+(?=[가-힣])", r"\1. ", clean)
        # 8) 영문/약어 단위 공백: "30 %", "5 GB" 등
        clean = _re_local.sub(r"(\d)\s+(%|％|MB|GB|TB|KB|kg|km|cm|mm)", r"\1\2", clean)
        # 9) 표 패턴 분해 (KISA 입찰공고 — 표 헤더+row 가 한 줄로 붙어옴)
        #    "1. 입찰에 부치는 사항 관리번호 계약건명 등록마감일시 제안서평가일(예정) 입찰방법" 헤더 다음
        #    값들이 이어지면 표 헤더 자체를 줄바꿈 + 값들도 줄바꿈
        clean = _re_local.sub(
            r"1\.\s*입찰에\s*부치는\s*사항\s+관리번호\s+계약건명\s+등록마감일시\s+제안서평가일\s*\(예정\)\s+입찰방법\s+",
            "\n\n§§HEAD§§□ 입찰에 부치는 사항\n",
            clean,
        )
        # "낙찰자 결정방법", "입찰 참가자격" 같은 큰 헤더 — 다음 내용과 분리
        clean = _re_local.sub(
            r"\s+(\d\.\s*(?:낙찰자\s*결정\s*방법|입찰\s*참가\s*자격|입찰\s*및\s*계약\s*방법|기타\s*사항|입찰\s*보증금|예정가격|제안서\s*평가)[^.①②③\n]{0,40})",
            r"\n\n§§HEAD§§\1\n",
            clean,
        )
        # 공백 한번 더 정리 (위 치환들이 중복 공백 만들 수 있음)
        clean = _re_local.sub(r"[ \t]+", " ", clean)
        clean = _re_local.sub(r" *\n *", "\n", clean)

        # 정부 공문 마커별 줄바꿈
        clean = _re_local.sub(r"\s*([□▣■▶])\s*", r"\n\n§§HEAD§§\1 ", clean)
        clean = _re_local.sub(r"\s*([○●◆◇▷▸])\s*", r"\n\1 ", clean)
        clean = _re_local.sub(r"\s*(※)\s*", r"\n§§NOTE§§\1 ", clean)
        clean = _re_local.sub(r"\s*([①-⑳])\s*", r"\n\1 ", clean)
        clean = _re_local.sub(r"\s+(·|‧|・)\s*", r"\n  \1 ", clean)
        # 마침표·콜론 후 한글 5자 이상 시작 → 줄바꿈 (짧은 토막 분리 방지)
        clean = _re_local.sub(r"([.!?])\s+(?=[가-힣A-Z][가-힣A-Z\d]{4,})", r"\1\n", clean)
        # 다중 빈 줄 정리
        clean = _re_local.sub(r"\n{3,}", "\n\n", clean)

        # 짧은 단편 줄 (3자 이하 또는 숫자만) 제거 — '6.', '9.', '16.' 같은 거
        _lines = clean.split("\n")
        _filtered = []
        for ln in _lines:
            stripped = ln.strip()
            if not stripped:
                _filtered.append(ln)
                continue
            # §§HEAD§§ / §§NOTE§§ 마커 있는 줄은 유지
            if "§§" in stripped:
                _filtered.append(ln)
                continue
            # 숫자·구두점만 있는 짧은 줄 (예: "6.", "9.", "16.") 제거
            if _re_local.fullmatch(r"[\d\s.,:()-]+", stripped) and len(stripped) <= 8:
                continue
            # 3자 이하 매우 짧은 줄도 제거
            if len(stripped) <= 3:
                continue
            _filtered.append(ln)
        clean = "\n".join(_filtered).strip()

        MAX = 2000  # 1500 → 2000 (더 풍부)
        truncated = len(clean) > MAX
        if truncated:
            clean = clean[:MAX]
            last_nl = clean.rfind("\n")
            if last_nl > 0:
                clean = clean[:last_nl]

        lines_html = []
        for line in clean.split("\n"):
            line = line.strip()
            if not line:
                lines_html.append("<div style='height:10px'></div>")
                continue
            esc = _h.escape(line)
            if "§§HEAD§§" in line:
                esc = _h.escape(line.replace("§§HEAD§§", ""))
                lines_html.append(
                    f"<div style='font-weight:700;color:#000;"
                    f"margin:20px 0 8px;font-size:17px;"
                    f"padding-bottom:6px;border-bottom:1px solid #d4d4d4'>{esc}</div>"
                )
            elif "§§NOTE§§" in line:
                esc = _h.escape(line.replace("§§NOTE§§", ""))
                lines_html.append(
                    f"<div style='color:#555;font-style:normal;"
                    f"margin:8px 0 8px 8px;font-size:14px;line-height:1.7;"
                    f"padding:10px 14px;background:#f7f7f7;border-left:3px solid #999;"
                    f"border-radius:2px'>{esc}</div>"
                )
            else:
                lines_html.append(
                    f"<div style='margin:8px 0;color:#111;font-size:15px;"
                    f"line-height:1.85'>{esc}</div>"
                )

        st.html(
            f"<div style='font-size:15px;line-height:2.0;"
            f"background:#ffffff;padding:28px 32px;"
            f"border:1px solid #d4d4d4;border-radius:2px;"
            f"max-height:800px;overflow-y:auto;font-family:Pretendard,sans-serif;"
            f"letter-spacing:-0.01em;color:#111'>"
            f"{''.join(lines_html)}"
            + (
                f"<div style='color:#999;font-size:13px;margin-top:18px;"
                f"padding-top:14px;border-top:1px solid #e5e5e5'>"
                f"… 이하 생략 — 원문 사이트에서 전체 확인</div>"
                if truncated else ""
            )
            + "</div>"
        )

    # 첨부 — 클릭 가능한 다운로드 링크
    try:
        atts = json.loads(row.get("attachments_json") or "[]")
    except Exception:
        atts = []
    # odt는 hwp 파일과 동일 내용 중복 → 제외 (정부 공고가 한글 호환 위해 같이 올림)
    atts = [
        a for a in atts
        if isinstance(a, dict) and not str(a.get("name", "")).lower().endswith(".odt")
    ]
    if atts:
        st.html(
            f"<div style='color:var(--text-muted);font-size:0.72rem;font-weight:700;"
            f"letter-spacing:0.08em;text-transform:uppercase;margin:14px 0 4px'>"
            f"📎 첨부 {len(atts)}건 · 파일명 클릭 시 다운로드</div>"
        )
        for a in atts[:20]:
            if not isinstance(a, dict):
                continue
            name = _h.escape(str(a.get("name", "")))
            url = a.get("url") or ""
            cat = a.get("category", "") or "기타"
            cat_bg = {
                "notice": "#fef3c7", "form": "#dbeafe",
                "eval": "#fce7f3", "reference": "#f3f4f6",
            }.get(cat, "#f1f5f9")
            cat_color = {
                "notice": "#a16207", "form": "#1e40af",
                "eval": "#9d174d", "reference": "#475569",
            }.get(cat, "#64748b")
            # URL 있으면 클릭 가능한 링크로
            if url and isinstance(url, str) and url.startswith(("http://", "https://")):
                name_html = (
                    f"<a href='{_h.escape(url)}' target='_blank' rel='noopener' "
                    f"style='color:var(--accent);text-decoration:none;"
                    f"border-bottom:1px dotted var(--accent-soft)'>{name}</a>"
                )
            else:
                name_html = f"<span style='color:var(--text-soft)'>{name}</span>"
            st.html(
                f"<div style='font-size:0.88em;margin:5px 0;line-height:1.5'>"
                f"<span style='background:{cat_bg};color:{cat_color};padding:2px 7px;"
                f"border-radius:4px;font-size:0.85em;font-weight:600;margin-right:6px'>"
                f"{cat}</span>{name_html}</div>"
            )
        if len(atts) > 20:
            st.caption(f"외 {len(atts) - 20}개")
    elif row.get("source_url") or row.get("url"):
        # 첨부 없으면 원문 페이지 링크라도 노출
        ann_url = row.get("source_url") or row.get("url")
        if ann_url and str(ann_url).startswith(("http://", "https://")):
            st.html(
                f"<div style='color:var(--text-muted);font-size:0.72rem;font-weight:700;"
                f"letter-spacing:0.08em;text-transform:uppercase;margin:14px 0 4px'>"
                f"📎 첨부 정보 없음</div>"
                f"<a href='{_h.escape(str(ann_url))}' target='_blank' rel='noopener' "
                f"style='font-size:0.88em;color:var(--accent);text-decoration:none'>"
                f"🔗 원문 사이트에서 확인하기 →</a>"
            )


def _toggle_detail(aid):
    """[상세 보기] 토글 — 같은 ID면 닫고, 다른 ID면 그것만 열고 이전은 자동 닫힘."""
    cur = st.session_state.get("_detail_id")
    st.session_state["_detail_id"] = None if cur == aid else aid


# dialog 트리거 — AI 초안 확인만 (상세보기는 카드 inline으로 변경됨)
if st.session_state.get("_ai_confirm_id"):
    _ai_confirm_dialog()


def _set_page(p: int) -> None:
    st.session_state["current_page"] = max(1, p)


def _page_nav(total_count: int, total_pages: int, current_page: int, key_prefix: str) -> None:
    """페이지 네비게이션 한 줄 — 상단/하단에 동일 컨트롤."""
    cols = st.columns([1, 1, 3, 1, 1])
    cols[0].button("⏮ 처음", key=f"{key_prefix}_first",
                   disabled=(current_page == 1),
                   on_click=_set_page, args=(1,), use_container_width=True)
    cols[1].button("◀ 이전", key=f"{key_prefix}_prev",
                   disabled=(current_page == 1),
                   on_click=_set_page, args=(current_page - 1,), use_container_width=True)
    start_n = (current_page - 1) * PAGE_SIZE + 1
    end_n = min(current_page * PAGE_SIZE, total_count)
    cols[2].markdown(
        f"<div style='text-align:center;padding-top:0.4em'>"
        f"<b>{start_n}–{end_n}</b> / {total_count}건 · 페이지 <b>{current_page}</b> / {total_pages}"
        f"</div>",
        unsafe_allow_html=True,
    )
    cols[3].button("다음 ▶", key=f"{key_prefix}_next",
                   disabled=(current_page == total_pages),
                   on_click=_set_page, args=(current_page + 1,), use_container_width=True)
    cols[4].button("끝 ⏭", key=f"{key_prefix}_last",
                   disabled=(current_page == total_pages),
                   on_click=_set_page, args=(total_pages,), use_container_width=True)


with tab1:
    if filtered.empty:
        st.html(
            "<div style='text-align:center;padding:64px 24px;background:#ffffff;"
            "border:1px dashed #e2e8f0;border-radius:16px;color:#64748b'>"
            "<div style='width:64px;height:64px;margin:0 auto 16px;background:#eff6ff;"
            "border-radius:50%;display:flex;align-items:center;justify-content:center;"
            "color:#3b82f6;font-size:28px'>🔍</div>"
            "<div style='font-size:1.05rem;font-weight:700;color:#0f172a;margin-bottom:6px'>"
            "조건에 맞는 공고가 없어요</div>"
            "<div style='font-size:0.9rem;color:#64748b'>"
            "사이드바 필터를 완화하거나 위쪽 [전체 해제]를 눌러보세요.</div>"
            "</div>"
        )
        page_df = filtered
    else:
        total_count = len(filtered)
        total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
        # 필터 변경 후 페이지가 범위 밖이면 clamp
        if st.session_state["current_page"] > total_pages:
            st.session_state["current_page"] = total_pages
        current_page = st.session_state["current_page"]

        # 정렬 컨트롤 — 본문 영역 상단 (우측 정렬: 힌트 ← 좌, selectbox → 우)
        _SORT_HINTS = {
            "newest":   "동일 날짜는 점수 높은 순",
            "score":    "동점은 최신 등록순",
            "deadline": "동일 마감일은 점수 높은 순",
        }
        scol1, scol2 = st.columns([5, 2])
        with scol1:
            st.markdown(
                f"<div style='padding-top:34px;color:#64748b;font-size:0.88em'>"
                f"💡 {_SORT_HINTS.get(sort_key, '')}"
                f"</div>",
                unsafe_allow_html=True,
            )
        with scol2:
            st.selectbox(
                "🔃 정렬 기준",
                list(SORT_OPTIONS.keys()),
                key="sort_by",
                help="공고 카드 표시 순서. 동일 1순위 값일 때 점수 높은 순으로 2차 정렬",
            )

        # 상단 페이지 네비
        _page_nav(total_count, total_pages, current_page, "top")
        st.markdown("")

        # 슬라이싱
        start = (current_page - 1) * PAGE_SIZE
        page_df = filtered.iloc[start:start + PAGE_SIZE]

    for _, row in page_df.iterrows():
        with st.container(border=True):
            # ── 좌측 점수 컬러 밴드 — BMW 식 (등급별 단색, 검정 강조 + 채도 절제) ──
            total = float(row.get("total_score") or 0)
            theme = float(row.get("theme_fit") or 0)
            _band_color = (
                "#111111" if total >= 90 else   # TOP — BMW 검정 (최고 강조)
                "#0066b1" if total >= 75 else   # GOOD — BMW 블루
                "#888888" if total >= 60 else   # FAIR — 중성 회색
                "#e5e5e5"                        # LOW — 옅은 회색
            )
            st.html(
                f"<div style='position:absolute;left:0;top:0;bottom:0;width:3px;"
                f"background:{_band_color};border-top-left-radius:4px;"
                f"border-bottom-left-radius:4px'></div>"
            )

            # ── 오늘 신규 공고: NEW 플래그 (헤더에 인라인 표시 위해 변수만)
            _is_new = _is_today_new(row.get("posted_at"))

            # ── 숨김 상태 (단정한 회색 텍스트) ──
            if row.get("is_dismissed"):
                st.html(
                    "<div style='color:var(--text-muted);font-size:12px;"
                    "margin-bottom:8px'>· 숨김 처리됨 — 우측 [숨김 해제]로 복원</div>"
                )

            # ──────────────────────────────────────────────────────
            # 카드 헤더 영역 — 인스타 피드 식 (좌: 기관/날짜  우: 점수/등급)
            # 단일 컬럼 구조 (c1/c2 분리 폐기) — 정보 위계가 위→아래로 흐름
            # ──────────────────────────────────────────────────────
            import html as _html
            agency = row.get("agency")
            agency_str = str(agency) if (agency and pd.notna(agency)) else None
            agency_badge = _agency_badge_html(row['source'], agency_str)
            # posted_at이 NaN(float)일 수 있음 — pd.notna로 확실히 가드
            _p = row.get("posted_at")
            posted = str(_p) if _p is not None and pd.notna(_p) else ""

            # 등급 라벨 (TOP/GOOD/FAIR/검토)
            grade_label = (
                "TOP" if total >= 90 else
                "GOOD" if total >= 75 else
                "FAIR" if total >= 60 else
                "검토"
            )
            grade_color = (
                "var(--warning)" if total >= 90 else
                "var(--success)" if total >= 75 else
                "#ca8a04" if total >= 60 else
                "var(--text-muted)"
            )
            # NEW 라벨 (헤더 좌측 인라인 — 점수와 겹치지 않게)
            new_badge = (
                "<span style='background:#dc2626;color:#fff;padding:1px 7px;"
                "border-radius:2px;font-weight:700;font-size:10px;"
                "letter-spacing:0.06em;margin-left:6px;flex-shrink:0'>NEW</span>"
                if _is_new else ""
            )

            # 카드 우측 점수 아래 — 예산/기간 우선, 없으면 마감일/담당자 폴백 (항상 표시)
            _bud_raw = row.get("budget_mw")
            _bud_period_raw = row.get("budget_period") or ""
            _body_for_facts = row.get("body") or ""
            _card_facts = _extract_key_facts(_body_for_facts)  # 본문 추출 fallback
            _card_contact = _extract_contact(_body_for_facts)
            budget_html = ""
            if _bud_raw is not None and pd.notna(_bud_raw) and int(_bud_raw) > 0:
                # 1순위: 정제된 budget_mw (확신 있는 정규화 값)
                _bv = int(_bud_raw)
                if _bv >= 1000:
                    _amt = f"{_bv/1000:.1f}".rstrip("0").rstrip(".") + "억"
                else:
                    _amt = f"{_bv}백만"
                _period_disp = _bud_period_raw if _bud_period_raw else ""
                _period_color = "#666" if "미명시" not in _period_disp else "#999"
                budget_html = (
                    f"<div style='margin-top:10px;text-align:right'>"
                    f"<div style='color:#666;font-size:10px;font-weight:600;"
                    f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:3px'>예산</div>"
                    f"<div style='color:#111;font-weight:700;font-size:1.1rem;"
                    f"font-feature-settings:\"tnum\";line-height:1.1'>{_amt}</div>"
                    + (f"<div style='color:{_period_color};font-size:11px;margin-top:3px;"
                       f"line-height:1.3'>{_html.escape(_period_disp)}</div>"
                       if _period_disp else "")
                    + "</div>"
                )
            else:
                # 우측은 무조건 [예산 + 기간] 자리 — 마감/담당자 폴백 X (좌측 메타에 이미 있음)
                # 사용자 일관성 요청: 모든 카드 우측은 같은 슬롯
                _raw_budget_fact = next((f[4:] for f in _card_facts if f.startswith("예산:")), "")
                _raw_period_fact = next((f[4:] for f in _card_facts if f.startswith("기간:")), "")
                if _raw_budget_fact:
                    # 2순위: 본문 명시 raw 예산 (정규화 안됐지만 표시 가치 있음)
                    _short = _raw_budget_fact[:24] + ("…" if len(_raw_budget_fact) > 24 else "")
                    budget_html = (
                        f"<div style='margin-top:10px;text-align:right'>"
                        f"<div style='color:#666;font-size:10px;font-weight:600;"
                        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:3px'>예산</div>"
                        f"<div style='color:#111;font-weight:700;font-size:0.95rem;"
                        f"line-height:1.2;font-feature-settings:\"tnum\"'>"
                        f"{_html.escape(_short)}</div>"
                        + (f"<div style='color:#666;font-size:11px;margin-top:3px;"
                           f"line-height:1.3'>{_html.escape(_raw_period_fact[:30])}</div>"
                           if _raw_period_fact else "")
                        + "</div>"
                    )
                else:
                    # 3순위: 예산 미명시 — 우측 자리 일관성 유지 (기간만 있으면 기간 표시)
                    budget_html = (
                        f"<div style='margin-top:10px;text-align:right'>"
                        f"<div style='color:#999;font-size:10px;font-weight:600;"
                        f"letter-spacing:0.06em;text-transform:uppercase;margin-bottom:3px'>예산</div>"
                        f"<div style='color:#aaa;font-size:13px;line-height:1.2;"
                        f"font-weight:500'>미명시</div>"
                        + (f"<div style='color:#888;font-size:11px;margin-top:4px;"
                           f"line-height:1.3'>{_html.escape(_raw_period_fact[:30])}</div>"
                           if _raw_period_fact else "")
                        + "</div>"
                    )

            st.html(
                "<div style='display:flex;justify-content:space-between;"
                "align-items:flex-start;gap:14px;margin-bottom:8px;padding:10px 14px 0'>"
                f"<div style='flex:1;min-width:0;display:flex;align-items:center;gap:10px;"
                f"flex-wrap:wrap'>"
                f"{agency_badge}"
                f"<span style='font-size:11px;color:var(--text-faint)'>"
                f"{_html.escape(posted) if posted else ''}</span>"
                f"{new_badge}"
                f"</div>"
                f"<div style='text-align:right;flex-shrink:0'>"
                f"<div style='display:flex;align-items:baseline;gap:8px;justify-content:flex-end'>"
                f"<span style='font-size:11px;font-weight:700;color:{grade_color};"
                f"letter-spacing:0.04em'>{grade_label}</span>"
                f"<span style='font-size:1.3rem;font-weight:700;color:var(--text);"
                f"letter-spacing:-0.03em;line-height:1;font-feature-settings:\"tnum\"'>"
                f"{total:.0f}<span style='font-size:0.5em;color:var(--text-faint);"
                f"font-weight:500;margin-left:2px'>/100</span></span>"
                f"</div>"
                f"{budget_html}"
                f"</div>"
                "</div>"
            )

            # ── 카드 본문 — 제목, 자격 경고, 메타 정보 ──
            c1, c2 = st.columns([99, 1])  # c2는 사실상 placeholder (기존 점수 박스 자리)
            with c1:
                # ── 제목 ──
                title = row.get("title") or "(제목 없음)"
                url = row.get("url") or ""
                if not isinstance(title, str): title = str(title)
                if not isinstance(url, str): url = ""
                safe_title = _html.escape(title)
                if url and url.startswith(("http://", "https://")):
                    safe_url = _html.escape(url, quote=True)
                    title_html = (
                        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
                        f'style="color:var(--text);text-decoration:none">{safe_title}'
                        f'<span style="color:var(--primary);margin-left:4px;font-size:0.85em">↗</span></a>'
                    )
                else:
                    title_html = f'<span style="color:var(--text)">{safe_title}</span>'

                st.html(
                    f"<h3 style='font-size:1.2rem;font-weight:700;margin:0 0 10px;"
                    f"line-height:1.45;letter-spacing:-0.02em;color:var(--text)'>"
                    f"{title_html}</h3>"
                )

                # 자격 미달 / 불확실 한 줄 (단정)
                _elig_status = row.get("eligibility_status")
                _elig_note = row.get("eligibility_note") or ""
                if _elig_status == "blocked":
                    st.html(
                        f"<div style='color:var(--danger);font-size:13px;"
                        f"margin-bottom:8px;font-weight:500'>"
                        f"자격 미달 · {_html.escape(_elig_note)}</div>"
                    )
                elif _elig_status == "unsure":
                    st.html(
                        f"<div style='color:#a16207;font-size:13px;"
                        f"margin-bottom:8px'>자격 확인 필요 · {_html.escape(_elig_note)}</div>"
                    )

                if not (url and url.startswith(("http://", "https://"))):
                    st.caption("원문 링크 없음")

                # ── 메타 행 ── (기관은 위 배지로 분리됨)
                bits = []
                deadline = row.get("deadline_at")
                if deadline and pd.notna(deadline):
                    days = row.get("days_left")
                    if pd.notna(days):
                        d = int(days)
                        if d <= 7:
                            tag = f"<span style='color:#c2410c;font-weight:700'>D-{d}</span>"
                        elif d <= 30:
                            tag = f"<span style='color:#a16207;font-weight:600'>D-{d}</span>"
                        else:
                            tag = f"<span style='color:var(--text-muted)'>D-{d}</span>"
                        bits.append(f"마감 {tag}")
                    else:
                        bits.append(f"마감 {deadline}")
                # 예산은 카드 우측 상단 점수 아래로 이동 — 메타 줄에 중복 표시 안 함
                # 첨부: 전체 N건 (양식뿐 아니라 모든 첨부 — odt 중복만 제외) + 양식이 있으면 따로
                try:
                    import re as _re
                    from rfp_targeter.attachments import classify as _cls
                    atts = json.loads(row.get("attachments_json") or "[]")
                    # odt는 hwp 중복이라 제외
                    atts = [x for x in atts if isinstance(x, dict)
                            and not str(x.get("name", "")).lower().endswith(".odt")]
                    total_att_n = len(atts)
                    seen_bases: set[str] = set()
                    form_n = 0
                    for x in atts:
                        cat = x.get("category") or _cls(x.get("name", ""))
                        if cat != "form":
                            continue
                        base = _re.sub(r"\.[^.\s)]+$", "", x.get("name", "")).strip().lower()
                        if base and base not in seen_bases:
                            seen_bases.add(base)
                            form_n += 1
                    if total_att_n > 0:
                        att_label = (
                            f"📎 첨부 <b>{total_att_n}</b>건"
                            + (f" <span style='color:var(--text-faint)'>(양식 {form_n})</span>"
                               if form_n > 0 else "")
                        )
                        bits.append(att_label)
                except Exception:
                    pass
                # 담당자 (본문에서 추출) — 카드 본문에 한 줄 정보 추가
                if _card_contact:
                    bits.append(
                        f"<span style='color:var(--text-soft)'>담당</span> "
                        f"<b style='color:var(--text);font-weight:600'>{_html.escape(_card_contact)}</b>"
                    )
                st.html(
                    f"<div style='color:var(--text-muted);font-size:0.85em;margin-bottom:8px'>"
                    + " <span style='color:var(--text-faint);margin:0 4px'>·</span> ".join(bits)
                    + "</div>"
                )

                # 카드 본문 영역 우선순위: AI 요약 → summary → facts (예산 제외) → excerpt
                _ai_sum = row.get("ai_summary")
                summary = row.get("summary")
                if _ai_sum and pd.notna(_ai_sum) and isinstance(_ai_sum, str) and len(_ai_sum) > 10:
                    # 1순위: LLM 자동 요약 (DB에 캐시됨) — 본문 핵심만 1~2문장
                    st.html(
                        f"<div style='background:#fafafa;border-left:3px solid #111;"
                        f"padding:10px 14px;margin-bottom:8px;"
                        f"color:var(--text);font-size:0.93em;line-height:1.6;"
                        f"font-weight:500'>"
                        f"<span style='color:#666;font-size:10px;font-weight:700;"
                        f"letter-spacing:0.08em;margin-right:6px'>AI 요약</span>"
                        f"{_html.escape(_ai_sum)}</div>"
                    )
                elif summary and pd.notna(summary) and isinstance(summary, str):
                    # 2순위: 크롤러에서 추출한 summary 필드
                    st.html(
                        f"<div style='color:var(--text-soft);font-size:0.92em;line-height:1.55;margin-bottom:6px'>"
                        f"{_html.escape(summary[:240] + ('...' if len(summary) > 240 else ''))}"
                        f"</div>"
                    )
                else:
                    # 3순위: 본문 facts (예산은 점수 아래로, "선정"은 표준 문구라 제거됨)
                    _facts_for_body = [f for f in _card_facts if not f.startswith("예산:")]
                    if _facts_for_body:
                        _fact_html = " &nbsp;<span style='color:var(--text-faint)'>·</span>&nbsp; ".join(
                            f"<span style='color:var(--text-muted);font-size:11px;"
                            f"font-weight:600;letter-spacing:0.04em'>{_html.escape(f[:3])}</span> "
                            f"<span style='color:var(--text-soft);font-size:13px'>"
                            f"{_html.escape(f[4:][:60])}</span>"
                            for f in _facts_for_body[:2]
                        )
                        st.html(
                            f"<div style='background:#fafafa;border:1px solid #ececec;"
                            f"border-radius:3px;padding:8px 12px;margin-bottom:8px;"
                            f"line-height:1.6'>{_fact_html}</div>"
                        )
                    else:
                        # 4순위: 본문 첫 문장 폴백
                        _excerpt = _extract_card_excerpt(_body_for_facts)
                        if _excerpt:
                            st.html(
                                f"<div style='color:var(--text-soft);font-size:0.9em;"
                                f"line-height:1.55;margin-bottom:6px;"
                                f"display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;"
                                f"overflow:hidden'>{_html.escape(_excerpt)}</div>"
                            )

                # ── 매칭 키워드 칩 ──
                mkj = row.get("matched_keywords_json")
                matched = []
                if mkj and isinstance(mkj, str):
                    try:
                        matched = json.loads(mkj)
                    except Exception:
                        matched = []
                if matched:
                    depts = [k.replace("[부서] ", "") for k in matched if isinstance(k, str) and k.startswith("[부서]")]
                    kws_raw = [k for k in matched if isinstance(k, str) and not k.startswith("[부서]")]
                    kws = _dedup_keywords(kws_raw)
                    chip_parts = []
                    # 부서: 회색 톤
                    for d in depts[:3]:
                        chip_parts.append(
                            f"<span style='background:var(--surface-alt);color:var(--text-soft);"
                            f"padding:2px 8px;border-radius:4px;font-size:12px;margin-right:4px;"
                            f"display:inline-block;border:1px solid var(--border);font-weight:500'>"
                            f"부서·{_html.escape(d)}</span>"
                        )
                    SHOW = 8
                    for k in kws[:SHOW]:
                        chip_parts.append(
                            f"<span style='background:var(--accent-soft);color:var(--primary);"
                            f"padding:2px 8px;border-radius:4px;font-size:12px;margin-right:4px;"
                            f"display:inline-block;font-weight:500'>"
                            f"#{_html.escape(k)}</span>"
                        )
                    more = len(kws) - SHOW
                    if more > 0:
                        chip_parts.append(
                            f"<span style='color:var(--text-muted);font-size:12px;padding:2px 4px'>"
                            f"+{more}</span>"
                        )
                    st.html("<div style='margin-top:10px;line-height:1.9'>" + "".join(chip_parts) + "</div>")

                # ── 5축 mini 한 줄 — 단정한 회색 톤 (네이버/인스타식) ──
                kw_s = float(row.get("keyword_score") or 0)
                bg_s = float(row.get("budget_score") or 0)
                cs_s = float(row.get("consortium_score") or 0)
                cp_s = float(row.get("competitor_score") or 0)
                tr_s = float(row.get("trl_score") or 0)
                # 색상 강조 X — 모든 점수 같은 톤 (정보 위계 평등)
                axes_inline = [
                    ("키워드", kw_s), ("예산", bg_s), ("컨소시엄", cs_s),
                    ("경쟁", cp_s), ("TRL", tr_s),
                ]
                axes_html = "  ".join(
                    f"<span style='color:var(--text-muted)'>{name}</span> "
                    f"<b style='color:var(--text);font-weight:600;"
                    f"font-feature-settings:&quot;tnum&quot; on'>{v:.0f}</b>"
                    for name, v in axes_inline
                )
                st.html(
                    f"<div style='margin-top:12px;padding-top:10px;"
                    f"border-top:1px solid var(--border-soft);"
                    f"font-size:13px;line-height:1.5;color:var(--text-soft)'>"
                    f"{axes_html}"
                    f"</div>"
                )

            with c2:
                # 점수는 카드 헤더로 이동됨. c2는 placeholder.
                pass

            # ── 액션 버튼 (좌측 컬럼 하단) ──
            ec1, ec2, ec3, ec4, _ = st.columns([1.1, 1.2, 1, 1, 3])
            _detail_open = (st.session_state.get("_detail_id") == row["id"])
            with ec1:
                # 토글: 같은 ID면 닫힘 / 다른 ID면 그것만 열리고 이전은 자동 닫힘
                if st.button(
                    "▲ 상세 접기" if _detail_open else "▼ 상세 보기",
                    key=f"detail_{row['id']}",
                    on_click=_toggle_detail, args=(row["id"],),
                    use_container_width=True,
                ):
                    pass
            with ec2:
                if st.button("AI 초안", key=f"ai_draft_{row['id']}",
                             type="primary", use_container_width=True,
                             help="/rfp 스킬을 Claude API로 자동 호출 — 비용 확인 다이얼로그 뜸"):
                    st.session_state["_ai_confirm_id"] = row["id"]
            with ec3:
                if st.button("초안", key=f"draft_{row['id']}", use_container_width=True,
                             help="회사 컨텍스트·5축·양식 모두 반영한 초안 md 파일 생성"):
                    def _nan_safe(v, default=None):
                        return default if v is None or (isinstance(v, float) and pd.isna(v)) else v
                    mkj = _nan_safe(row.get("matched_keywords_json"), "[]")
                    rj = _nan_safe(row.get("rationale_json"), "{}")
                    a = Announcement(
                        source=row["source"], external_id=row["external_id"],
                        title=_nan_safe(row.get("title"), ""), url=_nan_safe(row.get("url"), ""),
                        agency=_nan_safe(row.get("agency")),
                        posted_at=_nan_safe(row.get("posted_at")),
                        deadline_at=_nan_safe(row.get("deadline_at")),
                        budget_mw=_nan_safe(row.get("budget_mw")),
                        duration_months=_nan_safe(row.get("duration_months")),
                        summary=_nan_safe(row.get("summary")), body=_nan_safe(row.get("body")),
                        matched_keywords=json.loads(mkj),
                        is_security=True,
                    )
                    s = Score(
                        announcement_id=a.id,
                        keyword_score=_nan_safe(row.get("keyword_score"), 0),
                        budget_score=_nan_safe(row.get("budget_score"), 0),
                        consortium_score=_nan_safe(row.get("consortium_score"), 0),
                        competitor_score=_nan_safe(row.get("competitor_score"), 0),
                        trl_score=_nan_safe(row.get("trl_score"), 0),
                        total_score=_nan_safe(row.get("total_score"), 0),
                        theme_fit=_nan_safe(row.get("theme_fit"), 0),
                        rationale=json.loads(rj),
                    )
                    path = generate_draft(a, s)
                    try:
                        rel = path.relative_to(Path.cwd())
                    except ValueError:
                        rel = path
                    st.success(f"초안 생성: `{rel}`")
                    st.code(f"/rfp {rel}", language=None)
                    st.caption("Claude Code 채팅창에 붙여넣기 → 회사 컨텍스트·5축·양식 모두 반영해서 자동 작성")
            with ec4:
                _is_hidden = bool(row.get("is_dismissed"))
                if _is_hidden:
                    if st.button("숨김 해제", key=f"unhide_{row['id']}",
                                 use_container_width=True,
                                 help="다시 일반 목록에 표시"):
                        with get_conn() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE announcement SET is_dismissed=FALSE WHERE id=%s",
                                    (row["id"],),
                                )
                        st.cache_data.clear()
                        st.rerun()
                else:
                    if st.button("숨김", key=f"dismiss_{row['id']}",
                                 use_container_width=True,
                                 help="이 공고를 목록에서 제외 (사이드바 '숨김 포함 표시'로 복원 가능)"):
                        with get_conn() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE announcement SET is_dismissed=TRUE WHERE id=%s",
                                    (row["id"],),
                                )
                        st.cache_data.clear()
                        st.rerun()

            # ── [상세 보기] 토글이 켜진 카드는 여기에 inline으로 펼침 ──
            if _detail_open:
                _render_detail_inline(row, row["id"])

    # 하단 페이지 네비 (카드 루프 종료 후)
    if not filtered.empty:
        st.markdown("")
        _page_nav(len(filtered),
                  max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE),
                  st.session_state["current_page"], "bot")

with tab2:
    st.subheader("점수 비교 (필터된 공고)")
    if filtered.empty:
        st.info("비교할 공고 없음")
    else:
        def _fmt_budget(mw):
            """budget_mw(백만원 단위) → '10억', '1억 3천만' 형태."""
            if mw is None or pd.isna(mw) or mw <= 0:
                return "—"
            man = int(round(float(mw))) * 100          # 백만원 → 만원
            eok, rest = divmod(man, 10000)             # 1억 = 10000만
            parts = []
            if eok:
                parts.append(f"{eok:,}억")
            if rest:
                parts.append(f"{rest // 1000}천만" if rest % 1000 == 0
                              else f"{rest:,}만")
            return " ".join(parts) if parts else "—"

        # 같은 (title, url)이 여러 source에서 수집된 경우 → 한 행으로 합치고
        # 발주기관을 슬래시(/)로 표시. 데이터 정리됐지만 잔재 가능성 대비.
        view = filtered[["title", "url", "source", "agency", "total_score", "theme_fit",
                         "keyword_score", "budget_mw", "consortium_score",
                         "competitor_score", "trl_score"]].copy()
        view["title"] = view["title"].fillna("").str[:80]
        view["budget_mw"] = view["budget_mw"].map(_fmt_budget)

        # title 기준 그룹화 — 같은 공고가 여러 행에 있으면 source 모음
        grouped = (
            view.groupby("title", as_index=False)
                .agg({
                    "url": "first",
                    "source": lambda s: " / ".join(sorted({str(x) for x in s if x})),
                    "agency": "first",
                    "total_score": "max",
                    "theme_fit": "max",
                    "keyword_score": "max",
                    "budget_mw": "first",
                    "consortium_score": "max",
                    "competitor_score": "max",
                    "trl_score": "max",
                })
                .sort_values("total_score", ascending=False)
        )

        import html as _html

        def _bar(v: float, color: str = "#2563eb") -> str:
            v = float(v or 0)
            pct = max(0, min(100, v))
            return (
                f"<div style='position:relative;background:#f3f4f6;border-radius:4px;"
                f"height:18px;overflow:hidden;min-width:60px'>"
                f"<div style='position:absolute;left:0;top:0;height:100%;"
                f"width:{pct:.0f}%;background:{color};opacity:0.85'></div>"
                f"<div style='position:relative;text-align:center;line-height:18px;"
                f"font-size:0.78em;font-weight:600;color:#111827;font-feature-settings:\"tnum\"'>"
                f"{pct:.0f}</div></div>"
            )

        def _agency_chip(source_str: str) -> str:
            """공고명 앞에 붙는 작은 발주기관 칩. '/' 로 여러 기관 합쳐서 받음."""
            chips = []
            for src in (source_str or "").split(" / "):
                src = src.strip().lower()
                if not src:
                    continue
                meta = _AGENCY_META.get(src, {
                    "label": src.upper(), "color": "#475569", "bg": "#f1f5f9",
                })
                # f-string 안에 \" escape 안 됨 — 변수로 분리
                bg = meta["bg"]
                color = meta["color"]
                label = _html.escape(meta["label"])
                chips.append(
                    f"<span style='background:{bg};color:{color};"
                    f"padding:2px 7px;border-radius:5px;font-size:0.72rem;"
                    f"font-weight:700;letter-spacing:0.02em;"
                    f"border:1px solid {color}22;"
                    f"display:inline-block;margin-right:5px;line-height:1.5;"
                    f"vertical-align:middle;white-space:nowrap'>"
                    f"{label}</span>"
                )
            return "".join(chips)

        rows_html = []
        for _, row in grouped.iterrows():
            title_esc = _html.escape(str(row["title"]))
            url = str(row["url"] or "")
            agency_chips = _agency_chip(str(row["source"] or ""))
            if url and url.startswith(("http://", "https://")):
                title_link = (
                    f"<a href='{_html.escape(url)}' target='_blank' rel='noopener' "
                    f"style='color:#111827;text-decoration:none;font-weight:500;"
                    f"border-bottom:1px dashed #d1d5db'>{title_esc}</a>"
                )
            else:
                title_link = title_esc
            title_cell = f"{agency_chips}{title_link}"
            rows_html.append(
                "<tr>"
                f"<td style='padding:8px 10px;font-size:0.9em'>{title_cell}</td>"
                f"<td style='padding:8px 10px;text-align:center;font-weight:700;font-size:0.95em;"
                f"font-feature-settings:\"tnum\"'>{float(row['total_score'] or 0):.0f}</td>"
                f"<td style='padding:8px 8px'>{_bar(row['theme_fit'], '#f59e0b')}</td>"
                f"<td style='padding:8px 8px'>{_bar(row['keyword_score'], '#2563eb')}</td>"
                f"<td style='padding:8px 10px;text-align:right;font-size:0.85em;"
                f"font-feature-settings:\"tnum\"'>{_html.escape(str(row['budget_mw']))}</td>"
                f"<td style='padding:8px 8px'>{_bar(row['consortium_score'], '#8b5cf6')}</td>"
                f"<td style='padding:8px 8px'>{_bar(row['competitor_score'], '#ef4444')}</td>"
                f"<td style='padding:8px 8px'>{_bar(row['trl_score'], '#10b981')}</td>"
                "</tr>"
            )

        st.caption("공고명 클릭 시 원문 사이트가 새 탭에서 열림 · 여러 기관 공동 발주는 ' / '로 표시")
        st.html(
            "<style>"
            ".score-table { width: 100%; border-collapse: collapse; }"
            ".score-table th { background: #f9fafb; padding: 10px 10px; text-align: left;"
            "  font-size: 0.75em; font-weight: 600; color: #6b7280; border-bottom: 1px solid #e5e7eb;"
            "  text-transform: uppercase; letter-spacing: 0.06em; }"
            ".score-table td { border-bottom: 1px solid #f3f4f6; vertical-align: middle; }"
            ".score-table tr:hover { background: #fafafa; }"
            "</style>"
            "<table class='score-table'>"
            "<thead><tr>"
            "<th style='width:44%'>발주기관 · 공고명</th>"
            "<th style='width:7%;text-align:center'>종합</th>"
            "<th style='width:10%'>테마</th>"
            "<th style='width:10%'>키워드</th>"
            "<th style='width:9%;text-align:right'>예산</th>"
            "<th style='width:10%'>컨소시엄</th>"
            "<th style='width:5%'>경쟁</th>"
            "<th style='width:5%'>TRL</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody>"
            "</table>"
        )

with tab3:
    st.subheader("📐 점수 산정 기준")

    st.markdown("""
### 🎯 등급 임계값 (2026-05 튜닝)

| 등급 | 점수 | 비율 | 의미 | 배지 색 |
|---|---:|---:|---|---|
| **TOP** | ≥ 90 | ~2% | 즉시 우선 검토 | 🟠 오렌지 |
| **GOOD** | ≥ 75 | ~10% | 검토 권장 | 🟢 초록 |
| **FAIR** | ≥ 60 | ~27% | 검토 고려 | 🟡 노랑 |
| **LOW** | < 60 | ~60% | 참고만 | ⚪ 회색 |

KPI 카드 · 카드 좌측 컬러 밴드 · 상태 배지 모두 위 기준 통일.
""")

    st.markdown("""
### 종합 점수 = 가중합 + 테마 보너스
```
total = kw × 0.35 + bg × 0.10 + cs × 0.20 + cp × 0.20 + tr × 0.15
      + theme_fit 보너스
```

**theme_fit 보너스**: ≥90 → **+20** · ≥80 → **+12** · ≥60 → **+6** · <30 → **−10** · 그 외 0
""")

    st.markdown("### 5축별 산정 기준")
    st.markdown("""
#### 🔑 1. 키워드 적합도 — `kw` (가중치 **35%**)
- **baseline 30** (보안 필터 통과 또는 회사 키워드 1+ 매칭 시)
- 회사 `core_keywords` 매칭 — 매칭당 **+18** (자체 제품명, 정부 공고 매칭 시 강한 신호)
- `positioning_keywords` 매칭 — 매칭당 **+12**
- 보안 필터 추가 매칭 — 매칭당 **+8**
- 보안 필터 8개 이상 — **+5** 풍부도 보너스
- 최대 100점

**예시**:
- 양자내성암호 사업: baseline 30 + core 2×18 + boost 2×8 = **82**
- 일반 보안 공고: baseline 30 + boost 3×8 = **54**
- 회사 무관: 0

#### 💰 2. 예산 적합도 — `bg` (가중치 **10%**)
| 조건 | 점수 |
|------|------|
| Sweet spot (800~3000 백만원) | **100** |
| 회사 범위(200~5000) 내, sweet spot 밖 | 60~100 (선형) |
| 너무 작음 (< 200) | 20 |
| 너무 큼 (> 5000) | 25 |
| 정보 없음 | **35** (정보 부족 페널티) |

#### 🤝 3. 컨소시엄 부담 — `cs` (가중치 **20%**)
부담이 적을수록 점수↑. baseline **100**에서 감점.

| 신호 | 감점 |
|------|------|
| 대학 필요 + KAIST 활용 가능 | −5 |
| 대학 필요 + 파트너 미설정 | −35 |
| 다기관 컨소시엄 + 회사 가능 범위 | −10 |
| 다기관 컨소시엄 + 회사 부담 큼 | −30 |
| 단독 수행 가능 명시 | 0 (만점 유지) |
| 단독 수행 미명시 | −10 |

#### ⚔️ 4. 경쟁 강도 — `cp` (가중치 **20%**)
baseline **50**.

| 신호 | 효과 |
|------|------|
| 전문 영역 매칭 (양자내성·PQC·AI 보안·공격 시뮬레이션 등) | 매칭당 **+15** (최대 +40) |
| 대형 경쟁 매칭 (통합 플랫폼·관제·SOC·SIEM) | 매칭당 **−15** (최대 −35) |
| 본문에 경쟁사 이름 명시 | **−15** |
| 본문 200자 미만 | **−5** |

#### 🧪 5. 기술 성숙도 — `tr` (가중치 **15%**)
| 조건 | 점수 |
|------|------|
| 회사 TRL과 일치 | **100** |
| Gap 1 / 2 / 3+ | 85 / 65 / 40 |
| 공고에서 TRL 추정 불가 | **45** (정보 부족) |
| TRL 추정 가능, 회사 TRL 미설정 | 50 |

#### 🎯 별도: 테마 적합도 — `theme_fit`
회사 본업 매칭 강도. 5축 가중합에는 안 들어가지만, 위의 **보너스 규칙**으로 종합 점수 영향.

| 항목 | 점수 |
|------|------|
| baseline | 25 |
| 보유 기술 매칭 | 매칭당 +15 (최대 +40) |
| core_keywords 매칭 | 매칭당 +4 (최대 +20) |
| positioning_keywords 매칭 | 매칭당 +6 (최대 +15) |
| 보안 필터 매칭 6+ / 3~5 / 1~2 | +25 / +15 / +8 |
| 본문 1500자+ (정보 풍부) | +3 |
""")
    st.info(
        "📄 더 상세한 설명은 `docs/scoring_guide.md` 참조. "
        "가중치는 `config/settings.yaml > scoring_weights` 에서 조정."
    )

with tab4:
    p = profile() or {}
    import html as _h_prof

    company = p.get("company") or {}
    name = company.get("name", "(미설정)")
    eng = company.get("english_name", "")
    home = company.get("homepage", "")
    est_year = company.get("established_year")
    size = company.get("size", "")
    positioning = company.get("positioning", "")

    # ─── 회사 헤더 (flat, 좌측 색바 + 깔끔한 정보 구성) ──────────────
    from datetime import datetime as _dt_now
    age_str = ""
    if est_year:
        try:
            age = _dt_now.now().year - int(est_year)
            age_str = f"창업 {age}년차"
        except Exception:
            age_str = ""

    meta_items = []
    if est_year:
        meta_items.append(f"{est_year}년 설립")
    if age_str:
        meta_items.append(age_str)
    if size:
        meta_items.append(f"{size} 기업")
    meta_line = "  ·  ".join(meta_items)

    home_html = (
        f'<a href="{_h_prof.escape(home)}" target="_blank" rel="noopener" '
        f'style="color:var(--primary);font-weight:500;'
        f'border-bottom:1px solid transparent;text-decoration:none">'
        f'{_h_prof.escape(home.replace("https://", "").replace("http://", ""))}'
        f'</a>'
        if home else ""
    )
    st.html(
        '<div style="background:var(--surface);border:1px solid var(--border);'
        'border-radius:var(--radius-lg);padding:28px 32px;margin-bottom:20px;'
        'border-left:4px solid var(--primary);box-shadow:var(--shadow-xs)">'
        '<div style="font-size:11px;color:var(--text-muted);letter-spacing:0.12em;'
        'text-transform:uppercase;font-weight:600;margin-bottom:8px">회사 프로필</div>'
        '<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:4px">'
        f'<h1 style="font-size:1.75rem;font-weight:800;color:var(--text);'
        f'margin:0;letter-spacing:-0.025em;line-height:1.2">{_h_prof.escape(name)}</h1>'
        + (f'<span style="font-size:0.95rem;color:var(--text-muted);font-weight:500">'
           f'{_h_prof.escape(eng)}</span>' if eng else '')
        + '</div>'
        + (f'<div style="font-size:0.875rem;color:var(--text-muted);margin-top:6px">'
           f'{_h_prof.escape(meta_line)}</div>' if meta_line else '')
        + (f'<div style="margin-top:18px;padding-top:16px;border-top:1px solid var(--border-soft);'
           f'font-size:0.95rem;line-height:1.65;color:var(--text-soft);max-width:780px">'
           f'{_h_prof.escape(positioning)}</div>' if positioning else '')
        + (f'<div style="margin-top:14px;font-size:0.88rem">{home_html}</div>'
           if home_html else '')
        + '</div>'
    )

    # ─── 핵심 지표 — 카드 그리드 (이모지 X, 타이포로만) ───────────
    track = p.get("track_record") or {}
    ip = track.get("ip_assets") or {}
    std = track.get("standards") or {}
    data_a = track.get("data_assets") or {}
    consortium = p.get("consortium") or {}

    kpis = []
    if ip.get("patents_total"):
        reg = ip.get("patents_registered_domestic", 0) or 0
        pend = ip.get("patents_pending_domestic", 0) or 0
        kpis.append(("특허", str(ip["patents_total"]), "건", f"등록 {reg} · 출원 {pend}"))
    if std.get("domestic_count") or std.get("international_count"):
        d = std.get("domestic_count", 0) or 0
        i = std.get("international_count", 0) or 0
        kpis.append(("표준", str(d + i), "건", f"국내 {d} · 국제 {i}"))
    if data_a.get("hacker_knowledge_db_count"):
        cnt = data_a["hacker_knowledge_db_count"]
        kpis.append(("해커 DB", f"{cnt//10000}만+", "건",
                     f"{data_a.get('db_accumulation_years', '?')}년 누적"))
    if consortium.get("max_partners"):
        kpis.append(("컨소시엄", consortium.get("preferred_role", "?"), "",
                     f"최대 {consortium['max_partners']}개사 협업"))
    if consortium.get("solo_capable"):
        kpis.append(("단독 수행", "가능", "", "4단계 platform 모듈"))

    if kpis:
        cols = st.columns(len(kpis))
        for col, (label, val, unit, sub) in zip(cols, kpis):
            with col:
                st.html(
                    '<div style="background:var(--surface);border:1px solid var(--border);'
                    'border-radius:var(--radius);padding:18px 20px;height:100%;'
                    'transition:border-color 0.15s ease">'
                    f'<div style="font-size:12px;color:var(--text-muted);'
                    f'font-weight:500;margin-bottom:8px">{label}</div>'
                    f'<div style="font-size:1.75rem;font-weight:700;color:var(--text);'
                    f'letter-spacing:-0.03em;line-height:1.1;font-feature-settings:\'tnum\'">'
                    f'{_h_prof.escape(str(val))}'
                    + (f'<span style="font-size:0.6em;color:var(--text-muted);'
                       f'font-weight:500;margin-left:3px">{unit}</span>' if unit else '')
                    + '</div>'
                    + f'<div style="font-size:12px;color:var(--text-muted);margin-top:6px;'
                      f'line-height:1.4">{_h_prof.escape(sub)}</div>'
                    + '</div>'
                )

    # ─── 자체 보유 기술 ────────────────────────────────────────────
    techs = p.get("technologies") or []
    if techs:
        st.html('<div style="margin-top:28px;margin-bottom:12px">'
                '<div style="font-size:1.05rem;font-weight:700;color:var(--text);'
                'letter-spacing:-0.015em">자체 보유 기술</div>'
                '<div style="font-size:0.82rem;color:var(--text-muted);margin-top:2px">'
                'TRL: Technology Readiness Level (9=상용화, 8=실증, 7=시제, ...)</div>'
                '</div>')
        for tech in techs:
            tname = tech.get("name", "")
            trl = tech.get("trl", "?")
            kws = tech.get("keywords") or []
            is_mature = isinstance(trl, int) and trl >= 8
            trl_bg = "var(--success-soft)" if is_mature else "var(--warning-soft)"
            trl_color = "var(--success)" if is_mature else "var(--warning)"
            kw_chips = "".join(
                f'<span style="background:var(--surface-alt);color:var(--text-soft);'
                f'padding:4px 10px;border-radius:6px;font-size:0.8rem;font-weight:500;'
                f'margin:3px 5px 0 0;display:inline-block;border:1px solid var(--border-soft)">'
                f'{_h_prof.escape(str(k))}</span>'
                for k in kws[:8]
            )
            st.html(
                '<div style="background:var(--surface);border:1px solid var(--border);'
                'border-radius:var(--radius);padding:16px 20px;margin:10px 0">'
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'margin-bottom:10px;flex-wrap:wrap">'
                f'<span style="font-weight:700;color:var(--text);font-size:1rem">'
                f'{_h_prof.escape(tname)}</span>'
                f'<span style="background:{trl_bg};color:{trl_color};'
                f'padding:3px 10px;border-radius:6px;font-size:11px;font-weight:700;'
                f'letter-spacing:0.04em">TRL {trl}</span>'
                f'</div>'
                f'<div style="margin-top:2px">{kw_chips}</div>'
                '</div>'
            )

    # ─── 예산 적합 구간 ────────────────────────────────────────────
    budget = p.get("budget_range") or {}
    if budget.get("sweet_spot_min") and budget.get("sweet_spot_max"):
        sm = budget["sweet_spot_min"]
        sx = budget["sweet_spot_max"]
        mn = budget.get("min", 0)
        mx = budget.get("max", sx * 2)
        st.html('<div style="margin-top:28px;margin-bottom:12px">'
                '<div style="font-size:1.05rem;font-weight:700;color:var(--text);'
                'letter-spacing:-0.015em">예산 적합 구간</div>'
                '<div style="font-size:0.82rem;color:var(--text-muted);margin-top:2px">'
                '회사 규모 대비 최적 사업비 범위 — 점수의 예산 축 가중치 기준</div>'
                '</div>')
        scale = max(mx, 1)
        pct_min = 100 * sm / scale
        pct_max = 100 * sx / scale
        pct_mn = 100 * mn / scale
        st.html(
            '<div style="background:var(--surface);border:1px solid var(--border);'
            'border-radius:var(--radius);padding:20px 24px">'
            f'<div style="text-align:center;margin-bottom:14px">'
            f'<span style="font-size:1.4rem;font-weight:700;color:var(--text);'
            f'letter-spacing:-0.025em">{sm//100}억 ~ {sx//100}억원</span>'
            f'<span style="font-size:0.85rem;color:var(--text-muted);margin-left:8px">'
            f'sweet spot</span></div>'
            f'<div style="position:relative;background:var(--surface-sunk);'
            f'height:8px;border-radius:4px;margin:14px 0">'
            f'<div style="position:absolute;left:{pct_mn}%;width:{pct_min-pct_mn}%;'
            f'top:0;height:100%;background:#fde68a"></div>'
            f'<div style="position:absolute;left:{pct_min}%;width:{pct_max-pct_min}%;'
            f'top:0;height:100%;background:var(--success);border-radius:4px"></div>'
            f'<div style="position:absolute;left:{pct_max}%;right:0;'
            f'top:0;height:100%;background:var(--border-strong)"></div>'
            f'</div>'
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:0.78rem;color:var(--text-muted);margin-top:8px">'
            f'<span>{mn//100}억</span>'
            f'<span style="color:var(--success);font-weight:600">최적 구간</span>'
            f'<span>{mx//100}억+</span></div>'
            '</div>'
        )

    # ─── 핵심 키워드 ───────────────────────────────────────────────
    core_kws = p.get("core_keywords") or []
    if core_kws:
        st.html(f'<div style="margin-top:28px;margin-bottom:12px">'
                f'<div style="font-size:1.05rem;font-weight:700;color:var(--text);'
                f'letter-spacing:-0.015em">핵심 기술 키워드</div>'
                f'<div style="font-size:0.82rem;color:var(--text-muted);margin-top:2px">'
                f'{len(core_kws)}개 · 공고 자동 매칭 기준</div></div>')
        chips = "".join(
            f'<span style="background:var(--accent-soft);color:var(--primary);'
            f'padding:6px 12px;border-radius:6px;font-size:0.85rem;font-weight:500;'
            f'margin:3px 4px 3px 0;display:inline-block;'
            f'border:1px solid var(--chip-border)">'
            f'{_h_prof.escape(str(k))}</span>'
            for k in core_kws
        )
        st.html(
            '<div style="background:var(--surface);border:1px solid var(--border);'
            f'border-radius:var(--radius);padding:18px;line-height:2.2">{chips}</div>'
        )

    # ─── 타겟 / 파트너 / 정책 — 깔끔한 3컬럼 ──────────────────────
    targets = p.get("target_markets") or {}
    partner_list = consortium.get("existing_partners") or []
    policy = p.get("policy_alignment") or []

    def _list_block(title: str, sub: str, items: list[str]) -> str:
        if not items:
            return ''
        lis = "".join(
            f'<li style="padding:6px 0;border-bottom:1px solid var(--border-soft);'
            f'font-size:0.875rem;color:var(--text-soft);list-style:none">'
            f'{_h_prof.escape(str(i))}</li>'
            for i in items
        )
        return (
            '<div style="background:var(--surface);border:1px solid var(--border);'
            'border-radius:var(--radius);padding:18px 20px;height:100%">'
            f'<div style="font-size:0.78rem;color:var(--text-muted);letter-spacing:0.08em;'
            f'text-transform:uppercase;font-weight:600;margin-bottom:2px">{title}</div>'
            f'<div style="font-size:0.75rem;color:var(--text-faint);margin-bottom:10px">{sub}</div>'
            f'<ul style="margin:0;padding:0">{lis}</ul></div>'
        )

    st.html('<div style="margin-top:28px;margin-bottom:12px">'
            '<div style="font-size:1.05rem;font-weight:700;color:var(--text);'
            'letter-spacing:-0.015em">타겟 시장 · 파트너 · 정책</div></div>')
    cols2 = st.columns(3)
    with cols2[0]:
        st.html(_list_block("주력 타겟", "국내 발주 1순위",
                            targets.get("primary_domestic", [])))
    with cols2[1]:
        partner_items = []
        for pp in partner_list:
            if isinstance(pp, dict):
                partner_items.append(f"{pp.get('name','')} ({pp.get('type','')})")
        st.html(_list_block("협업 파트너", "공동 R&D 또는 컨소시엄",
                            partner_items))
    with cols2[2]:
        st.html(_list_block("정책 정합", "회사 사업이 따르는 규제·정책",
                            policy[:6]))

    # ─── 미설정 경고 ──────────────────────────────────────────────
    if any("???" in str(v) for v in str(p).split()):
        st.warning("프로필에 미설정 항목 있음 — `config/profile.yaml` 검수 권장")

    # ─── 원본 YAML (개발자용, 펼치기) ────────────────────────────
    with st.expander("원본 데이터 (개발자용)", expanded=False):
        st.caption("배포·운영 시 위의 뷰만 사용. 데이터 구조 확인이 필요한 경우만 펼침.")
        st.json(p)
