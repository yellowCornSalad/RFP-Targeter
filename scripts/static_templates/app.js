// RFP-Targeter 정적 사이트 — 클라이언트 JS (필터·검색·카드 렌더링)
// 외부 라이브러리 X (vanilla JS)

// ────────────────────────────────────────────────────────────
// 비밀번호 게이트 (간단 — 클라이언트 사이드, 결정적 보안 아님)
// ⚠️ 진짜 secret이 아니라 일반 사용자 진입 방지용
// ────────────────────────────────────────────────────────────
const DASHBOARD_PASSWORD = "enki2026";  // ← 사용자가 직접 변경
const AUTH_KEY = "enki_rfp_auth_v1";

function checkAuth() {
  if (sessionStorage.getItem(AUTH_KEY) === "ok") {
    showApp();
    return;
  }
  document.getElementById("auth-btn").addEventListener("click", tryAuth);
  document.getElementById("auth-pw").addEventListener("keydown", (e) => {
    if (e.key === "Enter") tryAuth();
  });
}
function tryAuth() {
  const pw = document.getElementById("auth-pw").value;
  if (pw === DASHBOARD_PASSWORD) {
    sessionStorage.setItem(AUTH_KEY, "ok");
    showApp();
  } else {
    document.getElementById("auth-err").textContent = "비밀번호가 틀렸습니다";
  }
}
function showApp() {
  document.getElementById("auth-gate").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  loadData();
}

// ────────────────────────────────────────────────────────────
// 데이터 로드 + 상태
// ────────────────────────────────────────────────────────────
let DATA = null;          // 전체
let FILTERED = [];        // 필터 적용 후
const PAGE_SIZE = 10;
let currentPage = 1;
const filters = {
  search: "",
  source: null,             // 단일 source 카드 클릭 (null = 전체)
  onlyOpen: false,
  onlyToday: false,
  minScore: 0,
  sort: "newest",
};

async function loadData() {
  try {
    const r = await fetch("data.json", { cache: "no-cache" });
    DATA = await r.json();
    document.getElementById("total-count").textContent = DATA.total.toLocaleString();
    document.getElementById("today-new").textContent = DATA.today_new;
    renderAgencyGrid();
    bindFilters();
    applyFilters();
  } catch (e) {
    console.error("데이터 로드 실패", e);
    document.getElementById("cards").innerHTML =
      '<div style="text-align:center;padding:40px;color:#999">데이터 로드 실패 — 빌드 후 다시 시도</div>';
  }
}

// ────────────────────────────────────────────────────────────
// 발주기관 그리드 (BMW 톤)
// ────────────────────────────────────────────────────────────
const SOURCE_LABELS = {
  iitp: "IITP", kisa: "KISA", nipa: "NIPA", mss: "중기부",
  kosa: "KOSA", krit: "KRIT", koica: "KOICA",
};
const SOURCE_ORDER = ["iitp", "kisa", "nipa", "mss", "kosa", "krit", "koica"];

function renderAgencyGrid() {
  const grid = document.getElementById("agency-grid");
  // 첫 카드 = "전체" (filters.source === null 일 때 활성)
  // 그 다음 7개 source 카드
  const cards = [
    {
      key: "all",
      label: "전체",
      total: DATA.total,
      newN: DATA.today_new,
      status: "보안 통과",
      isActive: filters.source === null,
      isAll: true,
    },
    ...SOURCE_ORDER.map((src) => {
      const total = DATA.sources_counts[src] || 0;
      return {
        key: src,
        label: SOURCE_LABELS[src],
        total: total,
        newN: DATA.today_new_by_src[src] || 0,
        status: total === 0 ? "수집 대기" : "정상",
        isActive: filters.source === src,
        isAll: false,
      };
    }),
  ];

  grid.innerHTML = cards.map((c) => `
    <div class="agency-card ${c.isActive ? "active" : ""} ${c.isAll ? "is-all" : ""}" data-src="${c.key}">
      ${c.newN > 0 ? `<span class="agency-new-badge">🆕 ${c.newN}</span>` : ""}
      <div class="agency-name">
        <span>${c.isAll ? "📋 " : ""}${c.label}</span>
        <span class="agency-dot ${c.total === 0 ? "zero" : ""}"></span>
      </div>
      <div class="agency-num">${c.total.toLocaleString()}<span class="unit">건</span></div>
      <div class="agency-status">${c.status}</div>
    </div>
  `).join("");

  grid.querySelectorAll(".agency-card").forEach((c) => {
    c.addEventListener("click", () => {
      const key = c.dataset.src;
      if (key === "all") {
        filters.source = null;  // 명시적 전체
      } else {
        // 같은 카드 다시 누르면 해제 (전체로 복귀)
        filters.source = (filters.source === key) ? null : key;
      }
      currentPage = 1;
      renderAgencyGrid();
      applyFilters();
    });
  });
}

// ────────────────────────────────────────────────────────────
// 필터 바인딩
// ────────────────────────────────────────────────────────────
function bindFilters() {
  document.getElementById("search").addEventListener("input", (e) => {
    filters.search = e.target.value.trim().toLowerCase();
    currentPage = 1; applyFilters();
  });
  document.getElementById("sort").addEventListener("change", (e) => {
    filters.sort = e.target.value;
    applyFilters();
  });
  document.getElementById("only-open").addEventListener("change", (e) => {
    filters.onlyOpen = e.target.checked;
    currentPage = 1; applyFilters();
  });
  document.getElementById("only-today").addEventListener("change", (e) => {
    filters.onlyToday = e.target.checked;
    currentPage = 1; applyFilters();
  });
  document.getElementById("min-score").addEventListener("input", (e) => {
    filters.minScore = parseInt(e.target.value);
    document.getElementById("min-score-val").textContent = filters.minScore;
    currentPage = 1; applyFilters();
  });
  document.getElementById("reset-btn").addEventListener("click", () => {
    filters.search = ""; filters.source = null; filters.onlyOpen = false;
    filters.onlyToday = false; filters.minScore = 0; filters.sort = "newest";
    document.getElementById("search").value = "";
    document.getElementById("only-open").checked = false;
    document.getElementById("only-today").checked = false;
    document.getElementById("min-score").value = 0;
    document.getElementById("min-score-val").textContent = "0";
    document.getElementById("sort").value = "newest";
    currentPage = 1;
    renderAgencyGrid();
    applyFilters();
  });
  // 페이지 nav
  ["page-prev", "page-prev2"].forEach((id) => {
    document.getElementById(id).addEventListener("click", () => {
      if (currentPage > 1) { currentPage--; renderCards(); }
    });
  });
  ["page-next", "page-next2"].forEach((id) => {
    document.getElementById(id).addEventListener("click", () => {
      const maxPage = Math.ceil(FILTERED.length / PAGE_SIZE);
      if (currentPage < maxPage) { currentPage++; renderCards(); }
    });
  });
}

// ────────────────────────────────────────────────────────────
// 필터 적용 + 정렬
// ────────────────────────────────────────────────────────────
function applyFilters() {
  const today = new Date().toISOString().slice(0, 10);
  FILTERED = DATA.items.filter((it) => {
    if (filters.source && it.source !== filters.source) return false;
    if (filters.minScore > 0 && (it.scores.total || 0) < filters.minScore) return false;
    if (filters.onlyToday && it.posted_at.slice(0, 10) !== today) return false;
    if (filters.onlyOpen) {
      if (it.deadline_at && it.deadline_at < today) return false;
    }
    if (filters.search) {
      const hay = (it.title + " " + it.agency + " " + it.matched_keywords.join(" ")).toLowerCase();
      if (!hay.includes(filters.search)) return false;
    }
    return true;
  });
  // 정렬
  FILTERED.sort((a, b) => {
    if (filters.sort === "score") {
      return (b.scores.total || 0) - (a.scores.total || 0);
    }
    if (filters.sort === "deadline") {
      const da = a.deadline_at || "9999-12-31";
      const db = b.deadline_at || "9999-12-31";
      return da.localeCompare(db);
    }
    // newest
    const pa = a.posted_at || "0000-00-00";
    const pb = b.posted_at || "0000-00-00";
    if (pa !== pb) return pb.localeCompare(pa);
    return (b.scores.total || 0) - (a.scores.total || 0);
  });
  renderKpiStrip();
  renderCards();
}

// ────────────────────────────────────────────────────────────
// KPI strip — 클릭 시 최소 점수 필터 토글
// 같은 카드 다시 누르면 해제 (전체로 돌아감)
// ────────────────────────────────────────────────────────────
function renderKpiStrip() {
  const strip = document.getElementById("kpi-strip");
  const all = DATA.items;
  const n_top = all.filter((it) => (it.scores.total || 0) >= 90).length;
  const n_good = all.filter((it) => (it.scores.total || 0) >= 75).length;
  const n_fair = all.filter((it) => (it.scores.total || 0) >= 60).length;
  const today = new Date().toISOString().slice(0, 10);
  const n_today = all.filter((it) => it.posted_at.slice(0, 10) === today).length;
  const total = DATA.total;

  // 현재 활성 필터 식별 (활성 카드에 'active' 클래스 부여)
  const active =
    filters.onlyToday ? "today" :
    filters.minScore >= 90 ? "top" :
    filters.minScore >= 75 ? "good" :
    filters.minScore >= 60 ? "fair" :
    "all";

  strip.innerHTML = `
    <div class="kpi-card ${active === "all" ? "active" : ""}" data-kpi="all">
      <div class="kpi-label">전체</div>
      <div class="kpi-value">${total.toLocaleString()}<span class="unit"> 건</span></div>
      <div class="kpi-sub">보안 통과</div>
    </div>
    <div class="kpi-card ${active === "top" ? "active" : ""}" data-kpi="top">
      <div class="kpi-label">🟠 TOP · 90+</div>
      <div class="kpi-value">${n_top}</div>
      <div class="kpi-sub">즉시 검토</div>
    </div>
    <div class="kpi-card ${active === "good" ? "active" : ""}" data-kpi="good">
      <div class="kpi-label">🟢 GOOD · 75+</div>
      <div class="kpi-value">${n_good}</div>
      <div class="kpi-sub">검토 권장</div>
    </div>
    <div class="kpi-card ${active === "fair" ? "active" : ""}" data-kpi="fair">
      <div class="kpi-label">🟡 FAIR · 60+</div>
      <div class="kpi-value">${n_fair}</div>
      <div class="kpi-sub">검토 고려</div>
    </div>
    <div class="kpi-card ${active === "today" ? "active" : ""}" data-kpi="today">
      <div class="kpi-label">🆕 오늘 신규</div>
      <div class="kpi-value">${n_today}</div>
      <div class="kpi-sub">${today}</div>
    </div>
  `;

  // 클릭 핸들러
  strip.querySelectorAll(".kpi-card").forEach((card) => {
    card.addEventListener("click", () => {
      const kind = card.dataset.kpi;
      // 같은 카드 다시 누르면 해제 (전체로)
      const isActive = card.classList.contains("active");

      if (kind === "all" || isActive) {
        // 전체 / 토글 해제
        filters.minScore = 0;
        filters.onlyToday = false;
      } else if (kind === "top") {
        filters.minScore = 90;
        filters.onlyToday = false;
      } else if (kind === "good") {
        filters.minScore = 75;
        filters.onlyToday = false;
      } else if (kind === "fair") {
        filters.minScore = 60;
        filters.onlyToday = false;
      } else if (kind === "today") {
        filters.minScore = 0;
        filters.onlyToday = true;
      }

      // 사이드바 슬라이더/체크박스 UI도 동기화
      document.getElementById("min-score").value = filters.minScore;
      document.getElementById("min-score-val").textContent = filters.minScore;
      document.getElementById("only-today").checked = filters.onlyToday;

      currentPage = 1;
      applyFilters();
    });
  });
}

// ────────────────────────────────────────────────────────────
// 카드 렌더링
// ────────────────────────────────────────────────────────────
function renderCards() {
  const cards = document.getElementById("cards");
  const total = FILTERED.length;
  const maxPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (currentPage > maxPage) currentPage = maxPage;
  const start = (currentPage - 1) * PAGE_SIZE;
  const page = FILTERED.slice(start, start + PAGE_SIZE);

  document.getElementById("visible-count").textContent =
    `${total.toLocaleString()}건 표시 중 (${start + 1}-${Math.min(start + PAGE_SIZE, total)})`;
  ["page-info", "page-info2"].forEach((id) =>
    document.getElementById(id).textContent = `${currentPage} / ${maxPage}`);
  ["page-prev", "page-prev2"].forEach((id) =>
    document.getElementById(id).disabled = currentPage <= 1);
  ["page-next", "page-next2"].forEach((id) =>
    document.getElementById(id).disabled = currentPage >= maxPage);

  if (total === 0) {
    cards.innerHTML = '<div style="text-align:center;padding:60px;color:#999;background:#fff;border-radius:4px">필터 조건에 맞는 공고가 없습니다</div>';
    return;
  }
  cards.innerHTML = page.map(renderCard).join("");
  cards.querySelectorAll(".detail-toggle").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const id = e.target.dataset.id;
      const det = document.querySelector(`.card-detail[data-id="${id}"]`);
      if (det) {
        det.classList.toggle("open");
        btn.textContent = det.classList.contains("open") ? "▲ 상세 접기" : "▼ 상세 보기";
      }
    });
  });
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ────────────────────────────────────────────────────────────
// 본문 정제 + HTML 변환 — 정부 공문 마커별 줄바꿈 + 스타일
//   □ ▣ ■ ▶ : 큰 헤딩 (제목 + border-bottom)
//   ○ ● ◆ ◇ : 항목 (들여쓰기)
//   ※ : 주석 (좌측 border + 회색 배경)
//   ①②③ : 번호 (강조)
// ────────────────────────────────────────────────────────────
function renderBody(body) {
  if (!body) return "";

  let text = String(body);
  // 1) HTML 엔티티 unescape (DB에 &amp; 같은 형태 들어있을 수 있음)
  text = text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');
  // 2) 공백 정규화 + [첨부 본문] 마커 제거
  text = text.replace(/\s+/g, " ").replace(/\[첨부 본문\]\s*/g, "").trim();

  // 3) chrome 잡음 (KISA·KOSA 사이트 메뉴) 제거
  const chromeNoise = [
    /알림마당\s*입찰공고\s*인쇄하기\s*공유하기\s*닫기\s*트위터\s*페이스북/g,
    /인쇄하기\s*공유하기\s*닫기\s*트위터\s*페이스북/g,
    /바로가기\s*메뉴\s*본문\s*바로가기.*?(?=공지사항\s*상세정보|상세정보\s*보기)/gs,
    /등록일\s*\d{4}-\d{2}-\d{2}\s*조회\s*\d+/g,
    /이전\s*글\s*다음\s*글\s*목록/g,
    /이용약관\s*개인정보처리방침\s*찾아오시는\s*길.*$/gs,
    /[=\-_*]{4,}/g,
  ];
  chromeNoise.forEach((re) => { text = text.replace(re, " "); });

  // 4) 가독성 패턴 압축 (날짜·시각·금액·괄호)
  text = text.replace(/(\d{4})\.\s+(\d{1,2})\.\s+(\d{1,2})\./g, "$1.$2.$3.");
  text = text.replace(/(\d{1,2})\s*:\s*(\d{2})/g, "$1:$2");
  text = text.replace(/(\d)\s+(년|월|일|시|분|초|개월|주|건|명|회|차|호|위|등|급|점|만|억|원|%)/g, "$1$2");
  text = text.replace(/(\d{1,3}(?:,\d{3})+)\s+원/g, "$1원");
  text = text.replace(/\(\s+/g, "(").replace(/\s+\)/g, ")");
  // 한글 1글자씩 띄어진 표 헤더 ("사 업 기 간" → "사업기간")
  text = text.replace(/(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])/g, "$1$2$3$4");
  text = text.replace(/(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])/g, "$1$2$3");

  // 5) 마커별 줄바꿈
  text = text.replace(/\s*([□▣■▶])\s*/g, "\n§HEAD§$1 ");
  text = text.replace(/\s*([○●◆◇▷▸])\s*/g, "\n$1 ");
  text = text.replace(/\s*(※)\s*/g, "\n§NOTE§$1 ");
  text = text.replace(/\s*([①-⑳])\s*/g, "\n$1 ");
  // 마침표/물음표 다음 한글 5자+ → 줄바꿈 (단락 분리)
  text = text.replace(/([.!?])\s+(?=[가-힣A-Z][가-힣A-Z\d]{4,})/g, "$1\n");
  // 빈 줄 정리
  text = text.replace(/\n{3,}/g, "\n\n");

  // 6) 줄별 HTML 변환
  const lines = text.split("\n");
  const out = [];
  for (let line of lines) {
    line = line.trim();
    if (!line) {
      out.push('<div class="body-spacer"></div>');
      continue;
    }
    if (line.startsWith("§HEAD§")) {
      out.push(`<div class="body-head">${escapeHtml(line.replace("§HEAD§", ""))}</div>`);
    } else if (line.startsWith("§NOTE§")) {
      out.push(`<div class="body-note">${escapeHtml(line.replace("§NOTE§", ""))}</div>`);
    } else if (/^[○●◆◇▷▸]/.test(line)) {
      out.push(`<div class="body-item">${escapeHtml(line)}</div>`);
    } else if (/^[①-⑳]/.test(line)) {
      out.push(`<div class="body-num">${escapeHtml(line)}</div>`);
    } else if (/^\d+\.\s/.test(line)) {
      // "1. 입찰에 부치는 사항" 같은 번호 헤더
      out.push(`<div class="body-num-head">${escapeHtml(line)}</div>`);
    } else {
      out.push(`<div class="body-line">${escapeHtml(line)}</div>`);
    }
  }
  return out.join("");
}

function gradeOf(total) {
  if (total >= 90) return ["TOP", "top"];
  if (total >= 75) return ["GOOD", "good"];
  if (total >= 60) return ["FAIR", "fair"];
  return ["검토", "low"];
}

function budgetText(mw) {
  if (mw == null || mw <= 0) return null;
  if (mw >= 1000) {
    const eok = mw / 1000;
    const s = (eok === Math.floor(eok)) ? `${eok}` : eok.toFixed(1).replace(/\.0$/, "");
    return `${s}억`;
  }
  return `${mw}백만`;
}

function daysLeft(deadline) {
  if (!deadline) return null;
  const d = new Date(deadline);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.floor((d - today) / 86400000);
}

function renderCard(it) {
  const [gradeLabel, gradeCls] = gradeOf(it.scores.total);
  const today = new Date().toISOString().slice(0, 10);
  const isNew = it.posted_at.slice(0, 10) === today;
  const dLeft = daysLeft(it.deadline_at);
  const bud = budgetText(it.budget_mw);

  // 우측 점수 아래 — 예산 우선, 없으면 미명시
  let budgetBox;
  if (bud) {
    budgetBox = `
      <div class="budget-box">
        <div class="budget-label">예산</div>
        <div class="budget-val">${escapeHtml(bud)}</div>
        ${it.budget_period ? `<div class="budget-period">${escapeHtml(it.budget_period)}</div>` : ""}
      </div>`;
  } else {
    budgetBox = `
      <div class="budget-box">
        <div class="budget-label" style="color:#999">예산</div>
        <div class="budget-val miss">미명시</div>
      </div>`;
  }

  // 매칭 키워드 칩
  const kws = it.matched_keywords.filter((k) => !k.startsWith("[부서]")).slice(0, 6);
  const depts = it.matched_keywords.filter((k) => k.startsWith("[부서]"))
    .map((k) => k.replace("[부서] ", "")).slice(0, 2);
  const chipsHtml = [
    ...depts.map((d) => `<span class="chip dept">부서·${escapeHtml(d)}</span>`),
    ...kws.map((k) => `<span class="chip">#${escapeHtml(k)}</span>`),
  ].join("");

  // 메타 행 — 마감 D-N · 신청기간 · 첨부 N건
  const metaBits = [];
  if (dLeft != null) {
    let dColor = dLeft <= 7 ? "#c2410c" : (dLeft <= 30 ? "#a16207" : "var(--text-muted)");
    metaBits.push(`마감 <b style="color:${dColor}">D-${dLeft}</b>`);
  } else if (it.deadline_at) {
    metaBits.push(`마감 ${escapeHtml(it.deadline_at)}`);
  }
  // 신청기간 — application_start_date ~ deadline_at (둘 다 있으면)
  if (it.application_start_date && it.deadline_at && it.application_start_date !== it.posted_at) {
    const s = it.application_start_date.slice(5).replace("-", "/");  // "05-26" → "5/26"
    const e = it.deadline_at.slice(5).replace("-", "/");
    metaBits.push(`신청 <b>${s}~${e}</b>`);
  }
  if (it.attachments.length > 0) {
    metaBits.push(`📎 첨부 <b>${it.attachments.length}</b>건`);
  }

  // 자격 미달
  let eligLine = "";
  if (it.eligibility_status === "blocked") {
    eligLine = `<div class="elig-bad">자격 미달 · ${escapeHtml(it.eligibility_note)}</div>`;
  } else if (it.eligibility_status === "unsure") {
    eligLine = `<div class="elig-unsure">자격 확인 필요 · ${escapeHtml(it.eligibility_note)}</div>`;
  }

  // 첨부 다운로드 링크 (상세)
  const attsHtml = it.attachments.length > 0
    ? `<h4>첨부 ${it.attachments.length}건</h4><div class="atts">${
        it.attachments.map((a) => `<div class="att"><a href="${escapeHtml(a.url)}" target="_blank">${escapeHtml(a.name)}</a></div>`).join("")
      }</div>`
    : "";

  return `
    <div class="card ${gradeCls}">
      <div class="card-band"></div>
      <div class="card-header">
        <div class="card-meta-top">
          <span class="source-badge ${it.source}">${SOURCE_LABELS[it.source] || it.source}</span>
          <span class="posted-date">${escapeHtml(it.posted_at.slice(0, 10))}</span>
          ${isNew ? '<span class="new-badge">NEW</span>' : ""}
        </div>
        <div class="card-score-block">
          <div class="grade-line">
            <span class="grade-label ${gradeCls}">${gradeLabel}</span>
            <span class="grade-score">${Math.round(it.scores.total)}<span class="max">/100</span></span>
          </div>
          ${budgetBox}
        </div>
      </div>
      <h3 class="card-title">
        ${it.url ? `<a href="${escapeHtml(it.url)}" target="_blank">${escapeHtml(it.title)}<span class="arrow">↗</span></a>` : escapeHtml(it.title)}
      </h3>
      ${eligLine}
      ${metaBits.length > 0 ? `<div class="card-meta">${metaBits.join('<span class="sep">·</span>')}</div>` : ""}
      ${chipsHtml ? `<div class="chips">${chipsHtml}</div>` : ""}
      <div class="axes-line">
        <span>키워드<b>${Math.round(it.scores.keyword)}</b></span>
        <span>예산<b>${Math.round(it.scores.budget)}</b></span>
        <span>컨소시엄<b>${Math.round(it.scores.consortium)}</b></span>
        <span>경쟁<b>${Math.round(it.scores.competitor)}</b></span>
        <span>TRL<b>${Math.round(it.scores.trl)}</b></span>
      </div>
      <button class="detail-toggle" data-id="${it.id}">▼ 상세 보기</button>
      <div class="card-detail" data-id="${it.id}">
        <h4>본문</h4>
        <div class="body-pre">${renderBody(it.body)}</div>
        ${attsHtml}
      </div>
    </div>`;
}

// ────────────────────────────────────────────────────────────
// 시작
// ────────────────────────────────────────────────────────────
checkAuth();
