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

# 사이드바 상단 여백 제거 — 로고 위 여백을 로고↔타이틀 간격과 동일하게
st.markdown(
    """
<style>
/* 사이드바 헤더(토글 버튼 영역) 최소화 */
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
    padding: 0.25rem 0.5rem !important;
    min-height: 0 !important;
    height: auto !important;
}
/* 사이드바 컨텐츠 영역의 top padding 제거 */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-top: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div:first-child {
    padding-top: 0 !important;
    margin-top: 0 !important;
}
/* 첫 element-container(로고) 위 여백 negative */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] .element-container:first-of-type {
    margin-top: -1.5rem !important;
}
/* 이미지 자체 위 여백도 제거 */
section[data-testid="stSidebar"] [data-testid="stImage"]:first-of-type {
    margin-top: 0 !important;
    padding-top: 0 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# 사이드바 상단에 ENKI WhiteHat 로고
from rfp_targeter.config import PROJECT_ROOT as _PR
_LOGO = _PR / "assets" / "enki_logo.png"
if _LOGO.exists():
    st.sidebar.image(str(_LOGO), use_container_width=True)

init_db()


# ---------- 데이터 로드 ----------
@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    with get_conn() as conn:
        rows = list_security_announcements(conn, limit=500)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    if "posted_at" in df:
        df["posted_at_dt"] = pd.to_datetime(df["posted_at"], errors="coerce")
    if "deadline_at" in df:
        df["deadline_at_dt"] = pd.to_datetime(df["deadline_at"], errors="coerce")
        df["days_left"] = (df["deadline_at_dt"] - pd.Timestamp.now(tz=df["deadline_at_dt"].dt.tz)).dt.days
    return df


# ---------- 사이드바 ----------
st.sidebar.title("🎯 RFP-Targeter")
st.sidebar.caption(f"엔키화이트햇 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

df = load_data()

if df.empty:
    st.warning("DB에 보안 분류된 공고가 없어. 먼저 `python -m rfp_targeter.scheduler` 또는 `python scripts/run_once.py` 실행해줘.")
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


def _normalize_kw(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def _collect_keywords(df_in) -> tuple[list[str], dict]:
    """모든 매칭 키워드 집계 (부서 매칭 제외)."""
    counter: dict[str, int] = {}
    for mkj in df_in.get("matched_keywords_json", pd.Series(dtype=str)).fillna(""):
        if not mkj:
            continue
        try:
            mks = json.loads(mkj)
        except Exception:
            continue
        for k in mks:
            if isinstance(k, str) and not k.startswith("[부서]"):
                counter[k] = counter.get(k, 0) + 1
    sorted_kws = sorted(counter.keys(), key=lambda x: -counter[x])
    return sorted_kws, counter


all_keywords, kw_counts = _collect_keywords(df)

# 필터
st.sidebar.markdown("### 필터")
search_query = st.sidebar.text_input(
    "🔎 검색", key="search_query",
    placeholder="예: 유망기업 육성, AI 보안, PQC",
    help="제목·부서·요약·본문에서 자유 텍스트 검색 (공백·대소문자 무시, 여러 단어는 모두 포함되는 공고)",
)
sources = st.sidebar.multiselect("기관/소스", sorted(df["source"].unique()), default=list(df["source"].unique()))
min_score = st.sidebar.slider("최소 종합 점수", 0, 100, key="min_score")
only_open = st.sidebar.checkbox("공모중", key="only_open", help="공모 마감일이 지나지 않은 공고만 표시")
selected_kws = st.sidebar.multiselect(
    "키워드 포함 (OR)", all_keywords, key="kw_filter",
    help="선택한 키워드 중 하나라도 매칭된 공고만 표시. 상단 'Top 키워드' 패널에서도 클릭 가능",
)

# 점수 외 필터(source + only_open + search + keyword)를 적용한 base
base = df[df["source"].isin(sources)]
if only_open and "days_left" in base:
    base = base[base["days_left"].fillna(999) >= 0]

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

st.sidebar.markdown("---")
st.sidebar.markdown(f"**{len(filtered)}개** 공고 표시 중")
if search_query and search_query.strip():
    st.sidebar.caption(f"🔎 검색어 적용 중: \"{search_query}\"")
if min_score > 0:
    st.sidebar.caption(f"↑ 점수 임계 적용 중 (≥{min_score}). 0으로 내리면 전체")
if only_open:
    skipped = len(df) - len(base)
    if skipped > 0:
        st.sidebar.caption(f"⏰ 공모 마감된 {skipped}건 숨김 ('공모중' 체크 해제 시 표시)")

# ---------- KPI 헤더 (클릭하면 즉시 필터) ----------
# 카운트는 base 기준 — 현재 사이드바 필터(source+only_open) 적용 후 카드 수와 일치
def _count(threshold: int) -> int:
    return int((base["total_score"].fillna(0) >= threshold).sum())

total_n = len(base)
n_50 = _count(50)
n_60 = _count(60)
n_70 = _count(70)
imminent = int((base.get("days_left", pd.Series(dtype=float)).fillna(999) <= 7).sum())

st.caption("⬇️ 카드 클릭 시 사이드바 슬라이더가 해당 점수로 자동 이동 — 필터 즉시 적용")


def _set_min_score(value: int) -> None:
    """on_click 콜백: widget instantiated 후엔 직접 session_state 수정 불가하므로 콜백 사용."""
    st.session_state["min_score"] = value


def _toggle_imminent() -> None:
    st.session_state["imminent_only"] = not st.session_state.get("imminent_only", False)


imm_active = st.session_state.get("imminent_only", False)
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.button(f"📊 전체 · {total_n}건", key="kpi_all",
              on_click=_set_min_score, args=(0,), use_container_width=True)
with col2:
    st.button(f"🟡 ≥50점 · {n_50}건", key="kpi_50",
              on_click=_set_min_score, args=(50,), use_container_width=True)
with col3:
    st.button(f"🟢 ≥60점 · {n_60}건", key="kpi_60",
              on_click=_set_min_score, args=(60,), use_container_width=True)
with col4:
    st.button(f"🌟 ≥70점 · {n_70}건", key="kpi_70",
              on_click=_set_min_score, args=(70,), use_container_width=True)
with col5:
    st.button(f"{'✅' if imm_active else '🔴'} 마감 ≤7일 · {imminent}건",
              key="kpi_imminent",
              on_click=_toggle_imminent,
              use_container_width=True,
              type="primary" if imm_active else "secondary",
              help="클릭 시 마감 7일 이내 공고만 필터 / 다시 클릭하면 해제")


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

st.markdown("---")

# ---------- 공고 카드 + 디테일 ----------
tab1, tab2, tab3, tab4 = st.tabs(["📋 공고 카드", "📊 점수 비교", "📐 점수 기준", "⚙️ 회사 프로필"])

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


@st.dialog("🤖 AI 초안 생성 확인")
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
        st.markdown(f"**공고:** {row['title'][:60]}")
        with st.spinner("Claude opus-4-7 호출 중... adaptive thinking 활성화로 30~120초 소요"):
            try:
                a2, s2 = _build_announcement_from_row(row)
                path = generate_draft(a2, s2, use_llm=True)
                try:
                    rel = path.relative_to(Path.cwd())
                except ValueError:
                    rel = path
                st.success(f"✅ AI 초안 작성 완료")
                st.code(str(rel), language=None)
                st.caption("위 경로의 파일을 열어 확인. 브레인스토밍 카드 + 1번 선택 + 표준 6목차 뼈대가 자동 작성됨")
            except Exception as e:
                st.error(f"❌ 실패: {e}")
                if "anthropic" in str(e).lower() or "api_key" in str(e).lower() or "미설정" in str(e):
                    st.info("`config/secrets.yaml` 의 `anthropic.api_key` 입력 필요. console.anthropic.com 에서 발급.")
        st.session_state["_ai_running"] = False
        if st.button("닫기", type="primary", use_container_width=True):
            st.session_state["_ai_confirm_id"] = None
            st.rerun()
        return

    # 확인 화면
    st.markdown(f"**공고**: {row['title'][:80]}")
    st.markdown(f"**점수**: 종합 **{row.get('total_score', 0):.0f}/100** · 테마 적합 {row.get('theme_fit', 0):.0f}")
    st.divider()

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

    st.warning(
        "⚠️ **Claude API 호출이 발생합니다**\n\n"
        f"**예상 비용**: **${cost_lo:.3f} ~ ${cost_hi:.3f}** (≈ **{krw_lo:,}~{krw_hi:,}원**)\n\n"
        "- 모델: `claude-opus-4-7` (최신 최강. 입력 $5/M · 출력 $25/M)\n"
        "- **Adaptive thinking + effort `xhigh`** 활성화 — 깊이 사고 후 작성\n"
        "- 응답 길이에 따라 변동 — 표시는 보수적 범위\n"
        "- prompt cache 적용 — 5분 내 반복 호출 시 시스템 입력 90% 절감\n"
        "- 회사 Anthropic 계정 후불 청구\n"
        "- ⓘ 호출 완료 후 **실제 비용**이 초안 푸터에 표시됨\n"
        "- ⏱️ Thinking 깊이 때문에 30~120초 소요"
    )
    col_a, col_b = st.columns(2)
    if col_a.button("✅ 예 — 작성 시작", type="primary", use_container_width=True):
        st.session_state["_ai_running"] = True
        st.rerun()
    if col_b.button("❌ 취소", use_container_width=True):
        st.session_state["_ai_confirm_id"] = None
        st.rerun()


# 페이지 어딘가 dialog 트리거 (트리거 우선)
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
        st.info("필터 조건에 맞는 공고가 없어.")
        page_df = filtered
    else:
        total_count = len(filtered)
        total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
        # 필터 변경 후 페이지가 범위 밖이면 clamp
        if st.session_state["current_page"] > total_pages:
            st.session_state["current_page"] = total_pages
        current_page = st.session_state["current_page"]

        # 상단 페이지 네비
        _page_nav(total_count, total_pages, current_page, "top")
        st.markdown("")

        # 슬라이싱
        start = (current_page - 1) * PAGE_SIZE
        page_df = filtered.iloc[start:start + PAGE_SIZE]

    for _, row in page_df.iterrows():
        with st.container(border=True):
            c1, c2 = st.columns([5, 1.4])
            with c1:
                title = row.get("title") or "(제목 없음)"
                url = row.get("url") or ""
                if not isinstance(title, str): title = str(title)
                if not isinstance(url, str): url = ""
                # 외부 링크는 새 탭으로 강제 — markdown link는 streamlit 환경에 따라 같은 탭에서 열려 대시보드를 떠남
                if url and url.startswith(("http://", "https://")):
                    import html as _html
                    safe_title = _html.escape(title)
                    safe_url = _html.escape(url, quote=True)
                    st.markdown(
                        f'<h3 style="margin-bottom:0.2rem">'
                        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
                        f'style="color:#1f77b4;text-decoration:none">{safe_title} ↗</a></h3>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(f"### {title}")
                    st.caption("🔗 링크 없음 (원문 확인 불가)")
                bits = []
                agency = row.get("agency")
                if agency and pd.notna(agency):
                    bits.append(f"**{agency}**")
                bits.append(f"`{row['source']}`")
                deadline = row.get("deadline_at")
                if deadline and pd.notna(deadline):
                    days = row.get("days_left")
                    if pd.notna(days):
                        emoji = "🔴" if days <= 7 else "🟡" if days <= 30 else "🟢"
                        bits.append(f"{emoji} 마감 D-{int(days)} ({deadline})")
                    else:
                        bits.append(f"마감 {deadline}")
                bud = row.get("budget_mw")
                if bud is not None and pd.notna(bud):
                    bits.append(f"💰 {int(bud)}백만원")
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
                        bits.append(f"📝 양식 {form_n}개")
                except Exception:
                    pass
                st.caption(" · ".join(bits))
                summary = row.get("summary")
                if summary and pd.notna(summary) and isinstance(summary, str):
                    st.write(summary[:300] + ("..." if len(summary) > 300 else ""))

                # 매칭 키워드 칩 표시
                mkj = row.get("matched_keywords_json")
                matched = []
                if mkj and isinstance(mkj, str):
                    try:
                        matched = json.loads(mkj)
                    except Exception:
                        matched = []
                if matched:
                    # 부서 매칭(보라) vs 일반 키워드(파랑) 분리
                    depts = [k.replace("[부서] ", "") for k in matched if isinstance(k, str) and k.startswith("[부서]")]
                    kws = [k for k in matched if isinstance(k, str) and not k.startswith("[부서]")]

                    chip_parts = []
                    for d in depts[:3]:
                        chip_parts.append(
                            f"<span style='background:#f3e5f5;color:#6a1b9a;padding:2px 8px;"
                            f"border-radius:12px;font-size:0.82em;margin:2px;display:inline-block;"
                            f"border:1px solid #ce93d8'>🏢 {d}</span>"
                        )
                    SHOW = 12
                    for k in kws[:SHOW]:
                        chip_parts.append(
                            f"<span style='background:#e3f2fd;color:#1565c0;padding:2px 8px;"
                            f"border-radius:12px;font-size:0.82em;margin:2px;display:inline-block;"
                            f"border:1px solid #90caf9'>{k}</span>"
                        )
                    more = len(kws) - SHOW
                    if more > 0:
                        chip_parts.append(
                            f"<span style='color:#666;font-size:0.82em;padding:2px 4px'>외 {more}개</span>"
                        )
                    st.markdown(
                        "<div style='margin-top:6px'>🔑 매칭: " + " ".join(chip_parts) + "</div>",
                        unsafe_allow_html=True,
                    )
            with c2:
                total = row.get("total_score") or 0
                theme = row.get("theme_fit") or 0
                color = "🟢" if total >= 70 else "🟡" if total >= 50 else "🔴"
                st.metric(f"{color} 종합 /100", f"{total:.0f}")
                st.metric("🎯 테마 적합 /100", f"{theme:.0f}")

            # 5축 점수 — c1 하단 가로 한 줄 (색상으로 강약 표시)
            with c1:
                kw_s = row.get("keyword_score") or 0
                bg_s = row.get("budget_score") or 0
                cs_s = row.get("consortium_score") or 0
                cp_s = row.get("competitor_score") or 0
                tr_s = row.get("trl_score") or 0

                def _color(v: float) -> str:
                    if v >= 70: return "#22c55e"      # 초록
                    if v >= 50: return "#eab308"      # 노랑
                    if v >= 30: return "#94a3b8"      # 회색
                    return "#ef4444"                   # 빨강

                axes = [
                    ("🔑 키워드", kw_s),
                    ("💰 예산", bg_s),
                    ("🤝 컨소시엄", cs_s),
                    ("⚔️ 경쟁", cp_s),
                    ("🧪 TRL", tr_s),
                ]
                chips = "  ·  ".join(
                    f"{name} <b style='color:{_color(v)}'>{v:.0f}</b>"
                    for name, v in axes
                )
                st.markdown(
                    f"<div style='margin-top:10px;font-size:0.92em;color:#475569'>{chips}</div>",
                    unsafe_allow_html=True,
                )

            with st.expander("📈 5축 점수 + 산정 근거"):
                rationale = json.loads(row.get("rationale_json") or "{}")
                axes = ["키워드", "예산", "컨소시엄", "경쟁자", "TRL"]
                vals = [
                    row.get("keyword_score") or 0,
                    row.get("budget_score") or 0,
                    row.get("consortium_score") or 0,
                    row.get("competitor_score") or 0,
                    row.get("trl_score") or 0,
                ]
                fig = go.Figure(go.Scatterpolar(
                    r=vals + [vals[0]],
                    theta=axes + [axes[0]],
                    fill="toself",
                    name=row["title"][:30],
                ))
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                    showlegend=False, height=320, margin=dict(l=20, r=20, t=20, b=20),
                )
                rc1, rc2 = st.columns([1, 1])
                with rc1:
                    st.plotly_chart(fig, width="stretch", key=f"radar_{row['id']}")
                with rc2:
                    for k, label in [
                        ("keyword", "🔑 키워드"), ("budget", "💰 예산"),
                        ("consortium", "🤝 컨소시엄"), ("competitor", "⚔️ 경쟁"),
                        ("trl", "🧪 TRL"), ("theme_fit", "🎯 테마"),
                    ]:
                        reasons = rationale.get(k) or []
                        if reasons:
                            st.markdown(f"**{label}**: " + " / ".join(reasons))

            ec1, ec_ai, ec2, _ = st.columns([1, 1.3, 1, 4])
            with ec1:
                if st.button("📝 초안 생성", key=f"draft_{row['id']}"):
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
                    st.success(f"✅ 초안 생성: `{rel}`")
                    st.code(f"/rfp {rel}", language=None)
                    st.caption("↑ Claude Code 채팅창에 붙여넣기 → 회사 컨텍스트·5축·양식 모두 반영해서 자동 작성")
            with ec_ai:
                if st.button("🤖 AI 초안 (rfp)", key=f"ai_draft_{row['id']}",
                             help="/rfp 스킬을 Claude API로 자동 호출 — 클릭 후 확인 다이얼로그에서 비용 확인 후 진행"):
                    # 모달 띄우기 — 클릭 정보를 session_state에 저장 후 dialog 트리거
                    st.session_state["_ai_confirm_id"] = row["id"]
            with ec2:
                if st.button("🗑 관심 없음", key=f"dismiss_{row['id']}"):
                    with get_conn() as conn:
                        conn.execute("UPDATE announcement SET is_dismissed=1 WHERE id=?", (row["id"],))
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
        chart_df = filtered[["title", "keyword_score", "budget_score",
                             "consortium_score", "competitor_score", "trl_score",
                             "total_score", "theme_fit"]].copy()
        chart_df["title"] = chart_df["title"].str[:40]
        st.dataframe(
            chart_df.sort_values("total_score", ascending=False),
            width="stretch", hide_index=True,
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
