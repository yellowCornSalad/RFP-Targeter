"""Streamlit 대시보드.

실행: streamlit run src/rfp_targeter/dashboard.py
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pathlib import Path

from rfp_targeter.config import profile
from rfp_targeter.db.models import get_conn, init_db, list_security_announcements
from rfp_targeter.drafter.draft_generator import generate_draft
from rfp_targeter.db.models import Announcement, Score

st.set_page_config(page_title="RFP-Targeter | 엔키화이트햇", layout="wide", page_icon="🎯")

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
/* === 색상 토큰 (Cobalt Blue — 산뜻한 블루 + 중립 슬레이트) === */
:root {
    --bg:            #ffffff;
    --bg-warm:       #fafbfc;
    --surface:       #ffffff;
    --surface-alt:   #f8fafc;       /* slate-50 */
    --border:        #f1f5f9;       /* slate-100 — 거의 안 보일 만큼 옅게 */
    --border-strong: #e2e8f0;       /* slate-200 */
    --text:          #0f172a;       /* slate-900 — 중립 다크 (보라 기 없음) */
    --text-muted:    #64748b;       /* slate-500 */
    --text-soft:     #334155;       /* slate-700 */
    --text-faint:    #94a3b8;       /* slate-400 */
    --primary:       #1e40af;       /* blue-800 — 사이드바 타이틀 등 진한 블루 */
    --primary-soft:  #1d4ed8;       /* blue-700 */
    --accent:        #3b82f6;       /* blue-500 — 메인 액센트(슬라이더, 호버, 칩) */
    --accent-hover:  #2563eb;       /* blue-600 */
    --accent-soft:   #eff6ff;       /* blue-50 — 칩/호버 배경 */
    --chip-text:     #1d4ed8;       /* blue-700 — 칩 글자 */
    --chip-border:   #bfdbfe;       /* blue-200 — 칩 보더 */
    --success:       #16a34a;
    --warning:       #d97706;
    --danger:        #dc2626;
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

/* === 전체 배경 === */
[data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background: var(--bg) !important;
}
.main .block-container, [data-testid="stMain"] .block-container {
    padding-top: 1.2rem !important;
    max-width: 1280px;
}

/* === Streamlit 기본 데코 숨김 (Deploy 버튼 위 영역, 햄버거 메뉴 등) === */
[data-testid="stToolbar"] { right: 1rem; }
[data-testid="stDecoration"] { display: none !important; }
#MainMenu, footer { visibility: hidden; }

/* === 사이드바 === */
section[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
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
section[data-testid="stSidebar"] h3 {
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.08em !important;
    color: var(--text-faint) !important;
    font-weight: 700 !important;
    margin-top: 1.2rem !important;
}

/* === 헤더 (h1~h4) === */
h1, h2, h3, h4 {
    color: var(--text) !important;
    letter-spacing: -0.025em !important;
    font-weight: 700 !important;
}
h1 { font-size: 1.6rem !important; }
h2 { font-size: 1.25rem !important; }
h3 { font-size: 1.05rem !important; }

/* === Tabs — 미니멀 언더라인 === */
[data-testid="stTabs"] [role="tablist"] {
    gap: 0.25rem;
    border-bottom: 1px solid var(--border) !important;
    margin-bottom: 1.25rem;
}
[data-testid="stTabs"] [role="tab"] {
    color: var(--text-muted) !important;
    font-weight: 500 !important;
    padding: 0.65rem 1rem !important;
    border-bottom: 2px solid transparent !important;
    transition: all 0.15s ease;
}
[data-testid="stTabs"] [role="tab"]:hover {
    color: var(--primary) !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: var(--primary) !important;
    font-weight: 700 !important;
    border-bottom-color: var(--accent) !important;
}

/* === 일반 버튼 — 아웃라인 + 그림자 톤 === */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button {
    border-radius: 10px !important;
    border: 1px solid var(--border-strong) !important;
    background: var(--surface) !important;
    color: var(--text) !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
    padding: 0.45rem 0.85rem !important;
    transition: all 0.15s ease !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
}
[data-testid="stButton"] > button:hover:not(:disabled),
[data-testid="stDownloadButton"] > button:hover:not(:disabled) {
    border-color: var(--accent) !important;
    background: var(--accent-soft) !important;
    color: var(--primary-soft) !important;
    box-shadow: 0 2px 6px rgba(59, 130, 246, 0.15) !important;
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

/* === 카드 컨테이너 (st.container(border=True)) === */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--border) !important;
    border-radius: 16px !important;
    background: var(--surface) !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
    transition: box-shadow 0.2s ease, border-color 0.2s ease, transform 0.15s ease !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: var(--chip-border) !important;
    box-shadow: 0 8px 24px rgba(59, 130, 246, 0.10), 0 2px 6px rgba(15, 23, 42, 0.04) !important;
}
/* 오늘 신규 공고 카드 — 호버 시 노란 글로우로 변경 (NEW 스티커 강조).
   카드 본문 첫 element가 NEW 띠(linear-gradient 들어간 height:4px div)일 때 적용 */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]:has(
    > div > div > [data-testid="stElementContainer"]:first-of-type
    [style*="linear-gradient(90deg,#fbbf24"]
) {
    border-color: #fde68a !important;
    box-shadow: 0 0 0 1px #fde68a, 0 8px 24px rgba(245, 158, 11, 0.15),
                0 2px 8px rgba(245, 158, 11, 0.10) !important;
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

/* === Expander — 카드 친화 === */
[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    background: var(--surface-alt) !important;
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

/* === 입력/선택 위젯 — 통일된 라운드 + 보더 === */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div,
[data-baseweb="popover"] {
    border-radius: 10px !important;
    border-color: var(--border-strong) !important;
}
[data-testid="stTextInput"] input:focus,
[data-baseweb="select"] > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15) !important;
}

/* === Slider — 인디고 thumb (트랙은 Streamlit 기본 유지) === */
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
    background: var(--accent) !important;
    border: 2px solid #ffffff !important;
    box-shadow: 0 0 0 1px var(--accent) !important;
}

/* === Multiselect 칩 === */
[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
    background: var(--accent-soft) !important;
    color: var(--primary-soft) !important;
    border: 1px solid #c7d2fe !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
}

/* === Checkbox === */
[data-testid="stCheckbox"] [data-baseweb="checkbox"] [data-checked="true"] {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
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

/* === 링크 === */
a {
    color: var(--accent) !important;
    text-decoration: none !important;
    border-bottom: 1px solid transparent;
    transition: border-color 0.15s ease;
}
a:hover {
    border-bottom-color: var(--accent) !important;
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

/* === 본문 상단 sticky app bar === */
.enki-appbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 14px;
    margin-bottom: 18px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}
.enki-appbar .left {
    display: flex; align-items: center; gap: 14px;
}
.enki-appbar .crumb {
    color: var(--text-faint); font-size: 0.78rem;
    text-transform: uppercase; letter-spacing: 0.1em; font-weight: 700;
}
.enki-appbar .title {
    font-size: 1.05rem; font-weight: 700; color: var(--text);
    letter-spacing: -0.02em;
}
.enki-appbar .badge {
    background: var(--accent-soft); color: var(--chip-text);
    padding: 3px 10px; border-radius: 999px;
    font-size: 0.78rem; font-weight: 700; border: 1px solid var(--chip-border);
}
.enki-appbar .right {
    display: flex; align-items: center; gap: 8px;
    color: var(--text-muted); font-size: 0.82rem;
}
.enki-appbar .right .dot { width:6px;height:6px;border-radius:50%;
    background: var(--success); display:inline-block; margin-right:4px; }

/* === KPI Stats Strip === */
.enki-kpi-strip { display: grid; gap: 10px; margin-bottom: 18px; }
.enki-kpi-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 14px 16px;
    transition: all 0.15s ease;
    cursor: pointer;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}
.enki-kpi-card:hover {
    border-color: var(--accent); transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(59, 130, 246, 0.10);
}
.enki-kpi-card.active {
    background: var(--accent-soft); border-color: var(--accent);
}
.enki-kpi-card.warn {
    background: #fff7ed; border-color: #fed7aa;
}
.enki-kpi-label {
    color: var(--text-muted); font-size: 0.78rem;
    font-weight: 600; letter-spacing: 0.02em;
    display: flex; align-items: center; gap: 6px;
}
.enki-kpi-label .dot {
    width: 8px; height: 8px; border-radius: 50%; display: inline-block;
}
.enki-kpi-value {
    font-size: 1.85rem; font-weight: 800;
    color: var(--text); letter-spacing: -0.04em;
    font-feature-settings: 'tnum' on;
    margin-top: 4px; line-height: 1.1;
}
.enki-kpi-value .unit { font-size: 0.7em; color: var(--text-muted); font-weight: 600; margin-left: 2px; }
.enki-kpi-delta {
    margin-top: 4px; font-size: 0.75rem; color: var(--text-muted);
    display: flex; align-items: center; gap: 4px;
}
.enki-kpi-delta.up   { color: var(--success); }
.enki-kpi-delta.down { color: var(--danger); }
.enki-kpi-delta.warn { color: #c2410c; }

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

/* === 공고 카드 좌측 점수 컬러 밴드 === */
[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] {
    position: relative;
    overflow: hidden;
}
.enki-card-band {
    position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
    border-top-left-radius: 16px; border-bottom-left-radius: 16px;
}
.band-top    { background: linear-gradient(180deg, #f59e0b, #fbbf24); }   /* ≥70 */
.band-high   { background: linear-gradient(180deg, #16a34a, #22c55e); }   /* ≥60 */
.band-mid    { background: linear-gradient(180deg, #d97706, #eab308); }   /* ≥50 */
.band-low    { background: linear-gradient(180deg, #94a3b8, #cbd5e1); }   /* <50 */

/* === 상태 배지 (카드 우상단) === */
.enki-status-badge {
    display: inline-block; padding: 4px 10px;
    border-radius: 999px; font-size: 0.72rem;
    font-weight: 700; letter-spacing: 0.02em;
    border: 1px solid;
}
.enki-status-badge.top  { background:#fff7ed; color:#c2410c; border-color:#fdba74; }
.enki-status-badge.high { background:#f0fdf4; color:#15803d; border-color:#86efac; }
.enki-status-badge.mid  { background:#fefce8; color:#a16207; border-color:#fde047; }
.enki-status-badge.low  { background:#f8fafc; color:#64748b; border-color:#cbd5e1; }

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
            conn, limit=500, include_dismissed=include_dismissed,
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
        row = conn.execute(
            "SELECT COUNT(*) FROM announcement WHERE is_security = 1 AND is_dismissed = 1"
        ).fetchone()
    return int(row[0] if row else 0)


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
sources = st.sidebar.multiselect(
    "기관 / 소스", sorted(df["source"].unique()),
    default=list(df["source"].unique()),
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
_appbar_html = f"""
<div style="display:flex;align-items:center;justify-content:space-between;
            padding:14px 20px;background:#ffffff;border:1px solid #f1f5f9;
            border-radius:14px;margin-bottom:18px;
            box-shadow:0 1px 3px rgba(15,23,42,0.04)">
  <div style="display:flex;align-items:center;gap:14px">
    <span style="color:#94a3b8;font-size:0.72rem;text-transform:uppercase;
                 letter-spacing:0.12em;font-weight:700">대시보드</span>
    <span style="color:#cbd5e1">/</span>
    <span style="font-size:1.05rem;font-weight:700;color:#0f172a;letter-spacing:-0.02em">
      RFP 공고 탐색
    </span>
    <span style="background:#eff6ff;color:#1d4ed8;padding:3px 10px;
                 border-radius:999px;font-size:0.75rem;font-weight:700;
                 border:1px solid #bfdbfe;margin-left:4px">
      {len(df):,}건 수집
    </span>
  </div>
  <div style="display:flex;align-items:center;gap:10px;color:#64748b;font-size:0.82rem">
    <span><span style="width:6px;height:6px;border-radius:50%;background:#16a34a;
                       display:inline-block;margin-right:6px"></span>
      오늘 신규 <b style="color:#0f172a">{_today_n}</b>건
    </span>
    <span style="color:#cbd5e1">·</span>
    <span>업데이트 {datetime.now().strftime('%H:%M')}</span>
  </div>
</div>
"""
st.html(_appbar_html)

# ---------- KPI Stats Strip ----------
# 카운트는 base 기준 — 현재 사이드바 필터(source+only_open) 적용 후 카드 수와 일치
def _count(threshold: int) -> int:
    return int((base["total_score"].fillna(0) >= threshold).sum())

total_n = len(base)
n_50 = _count(50)
n_60 = _count(60)
n_70 = _count(70)
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


# KPI 카드 전체가 단일 버튼 — 클릭 시 바로 필터. (중복 버튼 행 폐기)
# 버튼 라벨은 Streamlit 마크다운 지원: ## 제목, **굵게**, 그리고 줄바꿈은
# 마크다운에서 "  \n" (공백 2개 + 개행).
def _kpi_label(name: str, value: int, sub: str) -> str:
    return f"**{name}**  \n## {value:,} 건  \n_{sub}_"


k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.button(
        _kpi_label("전체 공고", total_n, f"오늘 신규 +{_today_n}"),
        key="kpi_all", on_click=_set_min_score, args=(0,),
        use_container_width=True,
        type="primary" if cur_min == 0 else "secondary",
        help="전체 공고 표시 (점수 0점 이상)",
    )
with k2:
    st.button(
        _kpi_label("≥ 50점 (Fair)", n_50,
                   f"전체의 {int(100*n_50/max(total_n,1))}%"),
        key="kpi_50", on_click=_set_min_score, args=(50,),
        use_container_width=True,
        type="primary" if cur_min == 50 else "secondary",
        help="검토 고려할 수준의 공고만",
    )
with k3:
    st.button(
        _kpi_label("≥ 60점 (Good)", n_60,
                   f"전체의 {int(100*n_60/max(total_n,1))}%"),
        key="kpi_60", on_click=_set_min_score, args=(60,),
        use_container_width=True,
        type="primary" if cur_min == 60 else "secondary",
        help="적극 검토 권장 수준",
    )
with k4:
    st.button(
        _kpi_label("≥ 70점 (Top)", n_70,
                   f"전체의 {int(100*n_70/max(total_n,1))}%"),
        key="kpi_70", on_click=_set_min_score, args=(70,),
        use_container_width=True,
        type="primary" if cur_min == 70 else "secondary",
        help="우선 수주 대상 수준",
    )
with k5:
    st.button(
        _kpi_label("마감 ≤ 7일", imminent,
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
    if total >= 70: return "band-top"
    if total >= 60: return "band-high"
    if total >= 50: return "band-mid"
    return "band-low"


_BADGE_BASE = ("display:inline-block;padding:4px 10px;border-radius:999px;"
               "font-size:0.72rem;font-weight:700;letter-spacing:0.02em;border:1px solid")


def _status_badge(total: float) -> str:
    if total >= 70:
        return (f"<span style='{_BADGE_BASE} #fdba74;background:#fff7ed;color:#c2410c'>"
                f"TOP · 우선 검토</span>")
    if total >= 60:
        return (f"<span style='{_BADGE_BASE} #86efac;background:#f0fdf4;color:#15803d'>"
                f"GOOD · 검토 권장</span>")
    if total >= 50:
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


# ─── 기관 배지 (소스별 색·이모지·풀네임) ──────────────────────────────
_AGENCY_META = {
    "kisa":   {"label": "KISA",   "name": "한국인터넷진흥원",       "color": "#0c4a6e", "bg": "#e0f2fe", "icon": "🛡"},
    "iitp":   {"label": "IITP",   "name": "정보통신기획평가원",     "color": "#1e3a8a", "bg": "#dbeafe", "icon": "🔬"},
    "ntis":   {"label": "NTIS",   "name": "국가과학기술지식정보",   "color": "#1e40af", "bg": "#e0e7ff", "icon": "🧪"},
    "kosa":   {"label": "KOSA",   "name": "한국SW산업협회",         "color": "#5b21b6", "bg": "#ede9fe", "icon": "💻"},
    "nipa":   {"label": "NIPA",   "name": "정보통신산업진흥원",     "color": "#0e7490", "bg": "#cffafe", "icon": "🌐"},
    "krit":   {"label": "KRIT",   "name": "국방기술진흥연구소",     "color": "#3f6212", "bg": "#ecfccb", "icon": "🛩"},
    "mss":    {"label": "MSS",    "name": "중소벤처기업부",         "color": "#c2410c", "bg": "#fff7ed", "icon": "🏭"},
    "koica":  {"label": "KOICA",  "name": "한국국제협력단",         "color": "#166534", "bg": "#dcfce7", "icon": "🌍"},
    "bizinfo":{"label": "bizinfo","name": "기업마당",               "color": "#475569", "bg": "#f1f5f9", "icon": "📌"},
}


def _agency_badge_html(source: str, agency: str | None = None) -> str:
    """기관 큰 배지 — 색/이모지/약어/풀네임."""
    meta = _AGENCY_META.get(source, {
        "label": source.upper(), "name": agency or "", "color": "#475569",
        "bg": "#f1f5f9", "icon": "📋",
    })
    full = meta["name"]
    # agency가 더 구체적이면 (예: 'KISA 입찰공고') 그걸 우선
    if agency and agency.strip() and agency.strip() not in (meta["label"], full):
        full = agency.strip()
    import html as _h
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;"
        f"background:{meta['bg']};color:{meta['color']};"
        f"padding:5px 11px;border-radius:8px;font-weight:700;"
        f"font-size:0.82rem;border:1px solid {meta['color']}22;"
        f"line-height:1.2'>"
        f"<span style='font-size:1em'>{meta['icon']}</span>"
        f"<span>{_h.escape(meta['label'])}</span>"
        f"<span style='color:{meta['color']}99;font-weight:500;"
        f"font-size:0.88em;margin-left:2px'>· {_h.escape(full)}</span>"
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


# ─── 상세 보기 다이얼로그 — 카드 [상세 보기] 클릭 시 ──────────────────────
@st.dialog("공고 상세", width="large")
def _detail_dialog():
    aid = st.session_state.get("_detail_id")
    if not aid:
        return
    rm = df[df["id"] == aid]
    if rm.empty:
        st.error("공고 정보를 찾을 수 없습니다.")
        if st.button("닫기"):
            st.session_state["_detail_id"] = None
            st.rerun()
        return
    row = rm.iloc[0]
    total = float(row.get("total_score") or 0)
    theme = float(row.get("theme_fit") or 0)

    # 헤더
    import html as _h
    title = str(row.get("title") or "(제목 없음)")
    url = str(row.get("url") or "")
    badge = _status_badge(total)
    title_html = (
        f'<a href="{_h.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'style="color:var(--text);text-decoration:none">{_h.escape(title)}'
        f'<span style="color:var(--accent);margin-left:6px">↗</span></a>'
    ) if url.startswith(("http://", "https://")) else _h.escape(title)
    st.html(
        f"<div style='display:flex;gap:12px;align-items:start;justify-content:space-between;margin-bottom:6px'>"
        f"  <h3 style='margin:0;font-size:1.15rem;font-weight:700;line-height:1.4'>{title_html}</h3>"
        f"  <div style='flex-shrink:0'>{badge}</div>"
        f"</div>"
    )

    # 메타
    bits = []
    if pd.notna(row.get("agency")): bits.append(_h.escape(str(row["agency"])))
    bits.append(f"<code>{row['source']}</code>")
    if pd.notna(row.get("deadline_at")):
        d = row.get("days_left")
        if pd.notna(d):
            bits.append(f"마감 D-{int(d)} ({row['deadline_at']})")
        else:
            bits.append(f"마감 {row['deadline_at']}")
    if pd.notna(row.get("budget_mw")):
        bits.append(f"예산 {int(row['budget_mw'])}백만원")
    st.html(
        f"<div style='color:var(--text-muted);font-size:0.88em;margin-bottom:14px'>"
        + " · ".join(bits) + "</div>"
    )

    # 점수 요약 4칸
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("종합", f"{total:.0f}", help="가중합 + 테마 보너스")
    sc2.metric("테마 적합", f"{theme:.0f}")
    sc3.metric("키워드", f"{float(row.get('keyword_score') or 0):.0f}")
    sc4.metric("경쟁 강도", f"{float(row.get('competitor_score') or 0):.0f}")

    st.markdown("---")

    # 5축 레이더 + 산정 근거
    rationale = json.loads(row.get("rationale_json") or "{}")
    axes_names = ["키워드", "예산", "컨소시엄", "경쟁자", "TRL"]
    vals = [
        float(row.get("keyword_score") or 0),
        float(row.get("budget_score") or 0),
        float(row.get("consortium_score") or 0),
        float(row.get("competitor_score") or 0),
        float(row.get("trl_score") or 0),
    ]
    # 레이더 차트 — Plotly. dialog 컨테이너에서 안 보이는 이슈 회피 위해
    # height/width 명시 + use_container_width=True 사용.
    fig = go.Figure(go.Scatterpolar(
        r=vals + [vals[0]], theta=axes_names + [axes_names[0]],
        fill="toself",
        line=dict(color="#3b82f6", width=2),
        fillcolor="rgba(59,130,246,0.20)",
        name=title[:30],
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True, range=[0, 100],
                gridcolor="#e2e8f0", tickfont=dict(size=10, color="#64748b"),
                tickvals=[20, 40, 60, 80, 100],
            ),
            angularaxis=dict(tickfont=dict(size=11, color="#0f172a"),
                              gridcolor="#f1f5f9"),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=False, height=320,
        margin=dict(l=40, r=40, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Pretendard Variable, Pretendard, sans-serif"),
    )

    rc1, rc2 = st.columns([1, 1])
    with rc1:
        # use_container_width=True — dialog 안에서 width="stretch"가 잘 안 먹는 케이스 회피
        st.plotly_chart(fig, use_container_width=True, key=f"radar_dlg_{aid}")
        # 백업: 레이더가 안 보일 때를 대비한 텍스트 5축 표 (항상 표시)
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
                st.markdown(f"<div style='font-size:0.86em;margin-bottom:6px'>"
                            f"<b>{label}</b> · "
                            f"<span style='color:var(--text-muted)'>{' / '.join(reasons)}</span>"
                            f"</div>", unsafe_allow_html=True)
        if not any_rationale:
            st.caption("산정 근거 데이터가 없어요 — 점수만 표시됩니다.")

    # 본문 요약
    summary = row.get("summary")
    if summary and pd.notna(summary) and isinstance(summary, str):
        st.markdown("---")
        st.markdown("**요약**")
        st.markdown(f"<div style='color:var(--text-soft);font-size:0.9em;line-height:1.6'>"
                    f"{_h.escape(summary[:600])}{'...' if len(summary) > 600 else ''}</div>",
                    unsafe_allow_html=True)

    # 첨부
    try:
        atts = json.loads(row.get("attachments_json") or "[]")
    except Exception:
        atts = []
    if atts:
        st.markdown("---")
        st.markdown(f"**첨부 {len(atts)}건**")
        for a in atts[:8]:
            if not isinstance(a, dict):
                continue
            name = _h.escape(str(a.get("name", "")))
            cat = a.get("category", "")
            st.markdown(f"<div style='font-size:0.85em;color:var(--text-soft);margin:2px 0'>"
                        f"<span style='color:var(--text-faint)'>[{cat or '기타'}]</span> {name}"
                        f"</div>", unsafe_allow_html=True)
        if len(atts) > 8:
            st.caption(f"외 {len(atts) - 8}개")

    st.markdown("---")
    if st.button("닫기", type="primary", use_container_width=True):
        st.session_state["_detail_id"] = None
        st.rerun()


# 페이지 어딘가 dialog 트리거 (트리거 우선)
if st.session_state.get("_ai_confirm_id"):
    _ai_confirm_dialog()
elif st.session_state.get("_detail_id"):
    _detail_dialog()


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
            # ── 좌측 점수 컬러 밴드 ──
            total = float(row.get("total_score") or 0)
            theme = float(row.get("theme_fit") or 0)
            _band_color = (
                "linear-gradient(180deg,#f59e0b,#fbbf24)" if total >= 70 else
                "linear-gradient(180deg,#16a34a,#22c55e)" if total >= 60 else
                "linear-gradient(180deg,#d97706,#eab308)" if total >= 50 else
                "linear-gradient(180deg,#94a3b8,#cbd5e1)"
            )
            st.html(
                f"<div style='position:absolute;left:0;top:0;bottom:0;width:4px;"
                f"background:{_band_color};border-top-left-radius:16px;"
                f"border-bottom-left-radius:16px'></div>"
            )

            # ── 오늘 신규 공고: NEW 스티커 + 카드 노란 스포트라이트 ──
            _is_new = _is_today_new(row.get("posted_at"))
            if _is_new:
                # 상단 그라데이션 띠 + 우상단 회전 NEW 스티커
                st.html(
                    "<div style='position:absolute;top:0;left:0;right:0;height:4px;"
                    "background:linear-gradient(90deg,#fbbf24,#f59e0b,#ea580c);"
                    "border-radius:16px 16px 0 0;z-index:5'></div>"
                    "<div style='position:absolute;top:-12px;right:14px;"
                    "background:linear-gradient(135deg,#fbbf24 0%,#f59e0b 100%);"
                    "color:#fff;padding:6px 14px;border-radius:999px;"
                    "font-weight:800;font-size:0.74rem;letter-spacing:0.06em;"
                    "transform:rotate(8deg);"
                    "box-shadow:0 6px 16px rgba(245,158,11,0.45),0 2px 4px rgba(245,158,11,0.3);"
                    "z-index:10;font-family:Pretendard Variable,Pretendard,sans-serif'>"
                    "✨ NEW</div>"
                )

            # ── 숨김 상태 배지 (목록에 포함된 dismissed 항목) ──
            if row.get("is_dismissed"):
                st.html(
                    "<div style='background:#fef2f2;border:1px solid #fecaca;"
                    "color:#991b1b;padding:6px 12px;border-radius:8px;"
                    "font-size:0.82rem;font-weight:600;margin-bottom:10px;"
                    "display:inline-block'>"
                    "🗂 숨김 처리됨 · 우측 [숨김 해제]로 복원"
                    "</div>"
                )

            c1, c2 = st.columns([5, 1.4])
            with c1:
                # ── 제목 + 상태 배지 ──
                title = row.get("title") or "(제목 없음)"
                url = row.get("url") or ""
                if not isinstance(title, str): title = str(title)
                if not isinstance(url, str): url = ""
                import html as _html
                safe_title = _html.escape(title)
                if url and url.startswith(("http://", "https://")):
                    safe_url = _html.escape(url, quote=True)
                    title_html = (
                        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
                        f'style="color:var(--text);text-decoration:none">{safe_title}'
                        f'<span style="color:var(--accent);margin-left:6px">↗</span></a>'
                    )
                else:
                    title_html = f'<span style="color:var(--text)">{safe_title}</span>'

                # 자격 미달 / 불확실 시 추가 배지 (status_badge 오른쪽에)
                _elig_status = row.get("eligibility_status")
                _elig_note = row.get("eligibility_note") or ""
                _badges_html = _status_badge(total)
                if _elig_status == "blocked":
                    _badges_html += (
                        f"<span style='{_BADGE_BASE} #fca5a5;background:#fef2f2;"
                        f"color:#991b1b;margin-left:6px' title='{_html.escape(_elig_note)}'>"
                        f"⚠ 자격 미달</span>"
                    )
                elif _elig_status == "unsure":
                    _badges_html += (
                        f"<span style='{_BADGE_BASE} #fde68a;background:#fffbeb;"
                        f"color:#92400e;margin-left:6px' title='{_html.escape(_elig_note)}'>"
                        f"? 자격 확인</span>"
                    )

                st.html(
                    f"<div style='display:flex;gap:12px;align-items:start;justify-content:space-between;margin-bottom:8px'>"
                    f"  <h3 style='font-size:1.15rem;font-weight:700;margin:0;line-height:1.4;letter-spacing:-0.02em'>{title_html}</h3>"
                    f"  <div style='flex-shrink:0;white-space:nowrap'>{_badges_html}</div>"
                    f"</div>"
                )
                if not (url and url.startswith(("http://", "https://"))):
                    st.caption("원문 링크 없음")
                # 자격 미달이면 본문 위에 한 줄 더 (사용자가 즉시 인지)
                if _elig_status == "blocked" and _elig_note:
                    st.html(
                        f"<div style='background:#fef2f2;border-left:3px solid #ef4444;"
                        f"padding:6px 10px;border-radius:4px;margin-bottom:8px;"
                        f"font-size:0.82rem;color:#991b1b'>"
                        f"🚫 {_html.escape(_elig_note)}</div>"
                    )

                # ── 기관 배지 (큰 컬러 스티커) ──
                agency = row.get("agency")
                agency_str = str(agency) if (agency and pd.notna(agency)) else None
                st.html(
                    f"<div style='margin-bottom:8px'>"
                    f"{_agency_badge_html(row['source'], agency_str)}"
                    f"</div>"
                )

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
                bud = row.get("budget_mw")
                if bud is not None and pd.notna(bud):
                    bits.append(f"예산 <b style='color:var(--text)'>{int(bud)}</b>백만")
                # 양식 첨부 수 — 같은 파일의 .hwp/.hwpx/.odt 묶어서 카운트
                try:
                    import re as _re
                    from rfp_targeter.attachments import classify as _cls
                    atts = json.loads(row.get("attachments_json") or "[]")
                    seen_bases: set[str] = set()
                    form_n = 0
                    for x in atts:
                        if not isinstance(x, dict):
                            continue
                        cat = x.get("category") or _cls(x.get("name", ""))
                        if cat != "form":
                            continue
                        base = _re.sub(r"\.[^.\s)]+$", "", x.get("name", "")).strip().lower()
                        if base and base not in seen_bases:
                            seen_bases.add(base)
                            form_n += 1
                    if form_n > 0:
                        bits.append(f"양식 <b>{form_n}</b>개")
                except Exception:
                    pass
                st.html(
                    f"<div style='color:var(--text-muted);font-size:0.85em;margin-bottom:8px'>"
                    + " <span style='color:var(--text-faint);margin:0 4px'>·</span> ".join(bits)
                    + "</div>"
                )

                summary = row.get("summary")
                if summary and pd.notna(summary) and isinstance(summary, str):
                    st.html(
                        f"<div style='color:var(--text-soft);font-size:0.92em;line-height:1.55;margin-bottom:6px'>"
                        f"{_html.escape(summary[:240] + ('...' if len(summary) > 240 else ''))}"
                        f"</div>"
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
                    for d in depts[:3]:
                        chip_parts.append(
                            f"<span style='background:#f1f5f9;color:#334155;padding:3px 9px;"
                            f"border-radius:6px;font-size:0.78em;margin-right:4px;display:inline-block;"
                            f"border:1px solid #cbd5e1;font-weight:500'>부서 · {_html.escape(d)}</span>"
                        )
                    SHOW = 10
                    for k in kws[:SHOW]:
                        chip_parts.append(
                            f"<span style='background:#eff6ff;color:#1d4ed8;padding:3px 9px;"
                            f"border-radius:6px;font-size:0.78em;margin-right:4px;display:inline-block;"
                            f"border:1px solid #bfdbfe;font-weight:500'>{_html.escape(k)}</span>"
                        )
                    more = len(kws) - SHOW
                    if more > 0:
                        chip_parts.append(
                            f"<span style='color:#94a3b8;font-size:0.78em;padding:2px 4px'>+{more}</span>"
                        )
                    st.html("<div style='margin-top:8px;line-height:1.9'>" + "".join(chip_parts) + "</div>")

                # 5축 progress bar는 제거 (공간 절약, 카드는 정량 정보 위주).
                # 5축 + 산정 근거는 [상세 보기] 다이얼로그에서 충분히 확인 가능.

            with c2:
                # ── 점수 컬럼 ── 종합 점수 + 예산 강조 (테마 적합도는 작게)
                bud_raw = row.get("budget_mw")
                if bud_raw is not None and pd.notna(bud_raw) and bud_raw > 0:
                    bud_val = int(bud_raw)
                    # 백만원 → 사람 친화 단위 (1000백만원 = 10억)
                    if bud_val >= 1000:
                        bud_text = f"{bud_val/1000:.1f}".rstrip("0").rstrip(".") + "<span style='font-size:0.5em;color:var(--text-faint);font-weight:600'> 억</span>"
                    else:
                        bud_text = f"{bud_val}<span style='font-size:0.5em;color:var(--text-faint);font-weight:600'> 백만</span>"
                    budget_block = (
                        f"<div style='margin-top:14px;color:var(--text-muted);font-size:0.78rem;font-weight:600'>예산</div>"
                        f"<div style='font-size:1.5rem;font-weight:700;color:#0369a1;letter-spacing:-0.04em;"
                        f"line-height:1.1;font-feature-settings:\"tnum\" on'>{bud_text}</div>"
                    )
                else:
                    budget_block = (
                        f"<div style='margin-top:14px;color:var(--text-muted);font-size:0.78rem;font-weight:600'>예산</div>"
                        f"<div style='font-size:0.95rem;color:var(--text-faint);font-weight:500;"
                        f"line-height:1.1'>정보 없음</div>"
                    )
                st.html(
                    f"<div style='text-align:right'>"
                    f"  <div style='color:var(--text-muted);font-size:0.78rem;font-weight:600;margin-bottom:2px'>종합 점수</div>"
                    f"  <div style='font-size:2.4rem;font-weight:800;color:var(--text);letter-spacing:-0.05em;line-height:1;font-feature-settings:\"tnum\" on'>{total:.0f}<span style='font-size:0.4em;color:var(--text-faint);font-weight:600'> / 100</span></div>"
                    f"  {budget_block}"
                    f"  <div style='margin-top:10px;color:var(--text-faint);font-size:0.74rem'>테마 적합 <b style='color:var(--text-muted)'>{theme:.0f}</b></div>"
                    f"</div>"
                )

            # ── 액션 버튼 (좌측 컬럼 하단) ──
            ec1, ec2, ec3, ec4, _ = st.columns([1.1, 1.2, 1, 1, 3])
            with ec1:
                if st.button("상세 보기", key=f"detail_{row['id']}",
                             on_click=_open_detail, args=(row["id"],),
                             use_container_width=True):
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
                            conn.execute(
                                "UPDATE announcement SET is_dismissed=0 WHERE id=?",
                                (row["id"],),
                            )
                        st.cache_data.clear()
                        st.rerun()
                else:
                    if st.button("숨김", key=f"dismiss_{row['id']}",
                                 use_container_width=True,
                                 help="이 공고를 목록에서 제외 (사이드바 '숨김 포함 표시'로 복원 가능)"):
                        with get_conn() as conn:
                            conn.execute(
                                "UPDATE announcement SET is_dismissed=1 WHERE id=?",
                                (row["id"],),
                            )
                        st.cache_data.clear()
                        st.rerun()

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

        chart_df = filtered[["title", "total_score", "theme_fit",
                             "keyword_score", "budget_mw", "consortium_score",
                             "competitor_score", "trl_score"]].copy()
        chart_df["title"] = chart_df["title"].str[:40]
        chart_df["budget_mw"] = chart_df["budget_mw"].map(_fmt_budget)
        chart_df = chart_df.sort_values("total_score", ascending=False)

        def _axis_cfg(label):
            return st.column_config.ProgressColumn(
                label, min_value=0, max_value=100, format="%d"
            )

        # 행 수에 맞춰 표 높이를 키워 페이지 여백을 채움 (최대 ~18행)
        _h = min(len(chart_df), 18) * 35 + 40

        st.dataframe(
            chart_df,
            width="stretch", hide_index=True, height=_h,
            column_config={
                "title": st.column_config.TextColumn("공고명", width="large"),
                "total_score": st.column_config.NumberColumn(
                    "종합 /100", format="%.1f", help="가중합 + 테마 보너스"),
                "theme_fit": _axis_cfg("🎯 테마"),
                "keyword_score": _axis_cfg("🔑 키워드"),
                "budget_mw": st.column_config.TextColumn(
                    "💰 예산", help="공고 사업비(추정)"),
                "consortium_score": _axis_cfg("🤝 컨소시엄"),
                "competitor_score": _axis_cfg("⚔️ 경쟁"),
                "trl_score": _axis_cfg("🧪 TRL"),
            },
        )

with tab3:
    st.subheader("📐 점수 산정 기준")
    st.markdown("""
### 종합 점수 = 가중합 + 테마 보너스
```
total = kw × 0.35 + bg × 0.10 + cs × 0.20 + cp × 0.20 + tr × 0.15
      + theme_fit 보너스
```

**theme_fit 보너스**: ≥80 → **+10** · ≥60 → **+5** · <30 → **−5** · 그 외 0
""")

    st.markdown("### 5축별 산정 기준")
    st.markdown("""
#### 🔑 1. 키워드 적합도 — `kw` (가중치 **35%**)
- 회사 `core_keywords` 매칭 — 매칭당 **+12**
- `positioning_keywords` 매칭 — 매칭당 **+8**
- 보안 필터 추가 매칭 — 매칭당 **+4**
- 최대 100점

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
    p = profile()
    st.subheader("회사 프로필")
    if any("???" in str(v) for v in str(p).split()):
        st.warning("프로필에 ??? 미설정 항목 있음 — `python scripts/init_profile.py` 실행 후 `config/profile.yaml` 검수 권장")
    st.json(p)
