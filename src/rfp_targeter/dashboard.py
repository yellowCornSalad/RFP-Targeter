"""Streamlit 대시보드.

실행: streamlit run src/rfp_targeter/dashboard.py
"""
from __future__ import annotations

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

# 필터
st.sidebar.markdown("### 필터")
sources = st.sidebar.multiselect("기관/소스", sorted(df["source"].unique()), default=list(df["source"].unique()))
min_score = st.sidebar.slider("최소 종합 점수", 0, 100, 0)
only_open = st.sidebar.checkbox("마감 안 지난 것만", value=True)

filtered = df[df["source"].isin(sources)]
filtered = filtered[filtered["total_score"].fillna(0) >= min_score]
if only_open and "days_left" in filtered:
    filtered = filtered[filtered["days_left"].fillna(999) >= 0]

st.sidebar.markdown("---")
st.sidebar.markdown(f"**{len(filtered)}개** 공고 표시 중")

# ---------- KPI 헤더 ----------
col1, col2, col3, col4 = st.columns(4)
col1.metric("보안 공고 총개수", len(df))
col2.metric("필터링 후", len(filtered))
high_score_n = int((df["total_score"].fillna(0) >= 70).sum())
col3.metric("고득점(≥70) 공고", high_score_n)
imminent = int((df.get("days_left", pd.Series(dtype=float)).fillna(999) <= 7).sum())
col4.metric("마감 임박(≤7일)", imminent)

st.markdown("---")

# ---------- 공고 카드 + 디테일 ----------
tab1, tab2, tab3 = st.tabs(["📋 공고 카드", "📊 점수 비교", "⚙️ 회사 프로필"])

with tab1:
    if filtered.empty:
        st.info("필터 조건에 맞는 공고가 없어.")
    for _, row in filtered.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                st.markdown(f"### [{row['title']}]({row['url']})")
                bits = []
                if row.get("agency"):
                    bits.append(f"**{row['agency']}**")
                bits.append(f"`{row['source']}`")
                if pd.notna(row.get("deadline_at")):
                    days = row.get("days_left")
                    if pd.notna(days):
                        emoji = "🔴" if days <= 7 else "🟡" if days <= 30 else "🟢"
                        bits.append(f"{emoji} 마감 D-{int(days)} ({row['deadline_at']})")
                    else:
                        bits.append(f"마감 {row['deadline_at']}")
                if row.get("budget_mw"):
                    bits.append(f"💰 {int(row['budget_mw'])}백만원")
                st.caption(" · ".join(bits))
                if row.get("summary"):
                    st.write(row["summary"][:300] + ("..." if len(row.get("summary") or "") > 300 else ""))
            with c2:
                total = row.get("total_score") or 0
                theme = row.get("theme_fit") or 0
                color = "🟢" if total >= 70 else "🟡" if total >= 50 else "🔴"
                st.metric("종합", f"{color} {total:.0f}/100")
                st.metric("테마 적합", f"{theme:.0f}/100")
            with c3:
                st.metric("KW", f"{row.get('keyword_score', 0):.0f}")
                st.metric("BG", f"{row.get('budget_score', 0):.0f}")

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

            ec1, ec2, _ = st.columns([1, 1, 4])
            with ec1:
                if st.button("📝 초안 생성", key=f"draft_{row['id']}"):
                    a = Announcement(
                        source=row["source"], external_id=row["external_id"],
                        title=row["title"], url=row["url"], agency=row.get("agency"),
                        posted_at=row.get("posted_at"), deadline_at=row.get("deadline_at"),
                        budget_mw=row.get("budget_mw"), duration_months=row.get("duration_months"),
                        summary=row.get("summary"), body=row.get("body"),
                        matched_keywords=json.loads(row.get("matched_keywords_json") or "[]"),
                        is_security=True,
                    )
                    s = Score(
                        announcement_id=a.id,
                        keyword_score=row["keyword_score"] or 0,
                        budget_score=row["budget_score"] or 0,
                        consortium_score=row["consortium_score"] or 0,
                        competitor_score=row["competitor_score"] or 0,
                        trl_score=row["trl_score"] or 0,
                        total_score=row["total_score"] or 0,
                        theme_fit=row["theme_fit"] or 0,
                        rationale=json.loads(row.get("rationale_json") or "{}"),
                    )
                    path = generate_draft(a, s)
                    st.success(f"초안 생성됨: `{path}`")
            with ec2:
                if st.button("🗑 관심 없음", key=f"dismiss_{row['id']}"):
                    with get_conn() as conn:
                        conn.execute("UPDATE announcement SET is_dismissed=1 WHERE id=?", (row["id"],))
                    st.cache_data.clear()
                    st.rerun()

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
    p = profile()
    st.subheader("회사 프로필")
    if any("???" in str(v) for v in str(p).split()):
        st.warning("프로필에 ??? 미설정 항목 있음 — `python scripts/init_profile.py` 실행 후 `config/profile.yaml` 검수 권장")
    st.json(p)
