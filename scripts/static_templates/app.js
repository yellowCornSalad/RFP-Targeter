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
  // onlyOpen 제거됨 (2026-05-27) — 사이트 노출 = 이미 활성 공고만이라 무의미.
  // 만료는 monitor_crawler 가 30분마다 is_dismissed=TRUE 처리.
  onlyToday: false,
  minScore: 0,
  budgetMode: "all",        // all | ge100 (1억+) | lt100 (1억 미만, NULL 제외)
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
  krit: "KRIT",
};
// kosa 제거 (2026-05-27) — 영양가 부족
// koica 제거 (2026-05-27) — apis.data.go.kr 빈 응답 + openapi.koica.go.kr unreachable
//                          정부 API 사망. 부활 가능성 낮음 → UI 카드 숨김
const SOURCE_ORDER = ["iitp", "kisa", "nipa", "mss", "krit"];

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
        // KRIT 는 국방 R&D 게시판 — 어댑터 정상이지만 보안 필터 통과 0건 흔함
        status: total === 0
          ? (src === "krit" ? "필터 통과 0" : "수집 대기")
          : "정상",
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
  // 예산 필터 (전체 / 1억+ / 1억 미만) — 2026-05-27 신규
  document.getElementById("budget-filter").addEventListener("change", (e) => {
    filters.budgetMode = e.target.value;
    currentPage = 1; applyFilters();
  });
  // '오늘 신규만' 체크박스 제거 (2026-05-27) — 아래 KPI strip '오늘 신규' 카드 클릭으로 대체
  document.getElementById("min-score").addEventListener("input", (e) => {
    filters.minScore = parseInt(e.target.value);
    document.getElementById("min-score-val").textContent = filters.minScore;
    currentPage = 1; applyFilters();
  });
  document.getElementById("reset-btn").addEventListener("click", () => {
    filters.search = ""; filters.source = null;
    filters.onlyToday = false; filters.minScore = 0; filters.sort = "newest";
    filters.budgetMode = "all";
    document.getElementById("search").value = "";
    document.getElementById("min-score").value = 0;
    document.getElementById("min-score-val").textContent = "0";
    document.getElementById("sort").value = "newest";
    document.getElementById("budget-filter").value = "all";
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
    // 예산 필터 — NULL(예산 미명시) 은 두 필터 모두에서 제외 (판단 불가)
    if (filters.budgetMode === "ge100") {
      if (it.budget_mw == null || it.budget_mw < 100) return false;
    } else if (filters.budgetMode === "lt100") {
      if (it.budget_mw == null || it.budget_mw >= 100) return false;
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
  const n_good = all.filter((it) => (it.scores.total || 0) >= 80).length;
  const n_fair = all.filter((it) => (it.scores.total || 0) >= 60).length;
  const today = new Date().toISOString().slice(0, 10);
  const n_today = all.filter((it) => it.posted_at.slice(0, 10) === today).length;
  const total = DATA.total;

  // 현재 활성 필터 식별 (활성 카드에 'active' 클래스 부여)
  const active =
    filters.onlyToday ? "today" :
    filters.minScore >= 90 ? "top" :
    filters.minScore >= 80 ? "good" :
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
      <div class="kpi-label">🟢 GOOD · 80+</div>
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
        filters.minScore = 80;
        filters.onlyToday = false;
      } else if (kind === "fair") {
        filters.minScore = 60;
        filters.onlyToday = false;
      } else if (kind === "today") {
        filters.minScore = 0;
        filters.onlyToday = true;
      }

      // 사이드바 슬라이더 UI도 동기화 ('오늘 신규만' 체크박스 제거됨 — KPI strip 자체로 표시)
      document.getElementById("min-score").value = filters.minScore;
      document.getElementById("min-score-val").textContent = filters.minScore;

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

  // 칩 클릭 → 해당 키워드로 검색 필터 적용 (검색창에도 표시)
  cards.querySelectorAll(".chip[data-kw]").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      const kw = chip.dataset.kw;
      if (!kw) return;
      // 같은 키워드 다시 클릭 시 검색 해제
      const searchEl = document.getElementById("search");
      const isActive = filters.search === kw.toLowerCase();
      if (isActive) {
        filters.search = "";
        searchEl.value = "";
      } else {
        filters.search = kw.toLowerCase();
        searchEl.value = kw;
      }
      currentPage = 1;
      applyFilters();
      // 페이지 상단으로 부드럽게 스크롤 (필터 결과 확인)
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  // Accordion 동작 — 한 번에 하나의 상세보기만 열림.
  // 다른 카드의 상세보기를 누르면 이전에 펼쳐둔 건 자동으로 닫힘.
  cards.querySelectorAll(".detail-toggle").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const id = e.target.dataset.id;
      const det = document.querySelector(`.card-detail[data-id="${id}"]`);
      if (!det) return;
      const willOpen = !det.classList.contains("open");

      // 다른 모든 열린 상세보기 닫기 + 그 버튼 텍스트 복원
      if (willOpen) {
        document.querySelectorAll(".card-detail.open").forEach((other) => {
          if (other === det) return;
          other.classList.remove("open");
          const otherId = other.dataset.id;
          const otherBtn = document.querySelector(`.detail-toggle[data-id="${otherId}"]`);
          if (otherBtn) otherBtn.textContent = "▼ 상세 보기";
        });
      }

      // 현재 카드 토글
      det.classList.toggle("open");
      btn.textContent = det.classList.contains("open") ? "▲ 상세 접기" : "▼ 상세 보기";

      // 새로 펼친 경우 — 그 카드를 화면 상단으로 부드럽게 스크롤
      if (det.classList.contains("open")) {
        const cardEl = det.closest(".card");
        if (cardEl) {
          // 약간의 지연 후 스크롤 (DOM 업데이트 반영 시간)
          setTimeout(() => {
            cardEl.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 50);
        }
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

  // 🔥 Python build_static.py 에서 이미 §§HEAD§§ / §§NOTE§§ 토큰 + 줄바꿈 처리 완료된 경우.
  //    이 경우엔 추가 정제 불필요, 토큰만 보고 클래스 입힘.
  const hasPyTokens = text.includes("§§HEAD§§") || text.includes("§§NOTE§§");

  if (!hasPyTokens) {
    // 폴백: raw body → 클라이언트에서 처리 (구버전 data.json 호환)
    text = text
      .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&nbsp;/g, " ").replace(/&#39;/g, "'").replace(/&quot;/g, '"');
    text = text.replace(/\s+/g, " ").replace(/\[첨부 본문\]\s*/g, "").trim();
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
    text = text.replace(/(\d{4})\.\s+(\d{1,2})\.\s+(\d{1,2})\./g, "$1.$2.$3.");
    text = text.replace(/(\d{1,2})\s*:\s*(\d{2})/g, "$1:$2");
    text = text.replace(/(\d)\s+(년|월|일|시|분|초|개월|주|건|명|회|차|호|위|등|급|점|만|억|원|%)/g, "$1$2");
    text = text.replace(/(\d{1,3}(?:,\d{3})+)\s+원/g, "$1원");
    text = text.replace(/\(\s+/g, "(").replace(/\s+\)/g, ")");
    text = text.replace(/(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])/g, "$1$2$3$4");
    text = text.replace(/(?<![가-힣])([가-힣])\s([가-힣])\s([가-힣])(?![가-힣])/g, "$1$2$3");
    text = text.replace(/\s*([□▣■▶])\s*/g, "\n§§HEAD§§$1 ");
    text = text.replace(/\s*([○●◆◇▷▸])\s*/g, "\n$1 ");
    text = text.replace(/\s*(※)\s*/g, "\n§§NOTE§§$1 ");
    text = text.replace(/\s*([①-⑳])\s*/g, "\n$1 ");
    text = text.replace(/([.!?])\s+(?=[가-힣A-Z][가-힣A-Z\d]{4,})/g, "$1\n");
    text = text.replace(/\n{3,}/g, "\n\n");
  }

  // 줄별 HTML 변환
  const lines = text.split("\n");
  const out = [];
  let prevEmpty = false;
  for (let line of lines) {
    line = line.trim();
    if (!line) {
      if (!prevEmpty) out.push('<div class="body-spacer"></div>');
      prevEmpty = true;
      continue;
    }
    prevEmpty = false;
    if (line.startsWith("§§HEAD§§")) {
      out.push(`<div class="body-head">${escapeHtml(line.replace("§§HEAD§§", ""))}</div>`);
    } else if (line.startsWith("§§NOTE§§")) {
      out.push(`<div class="body-note">${escapeHtml(line.replace("§§NOTE§§", ""))}</div>`);
    } else if (line.startsWith("§HEAD§")) {  // 폴백 (구버전 토큰)
      out.push(`<div class="body-head">${escapeHtml(line.replace("§HEAD§", ""))}</div>`);
    } else if (line.startsWith("§NOTE§")) {
      out.push(`<div class="body-note">${escapeHtml(line.replace("§NOTE§", ""))}</div>`);
    } else if (/^[○●◆◇▷▸]/.test(line)) {
      out.push(`<div class="body-item">${escapeHtml(line)}</div>`);
    } else if (/^[①-⑳]/.test(line)) {
      out.push(`<div class="body-num">${escapeHtml(line)}</div>`);
    } else if (/^\d+\.\s/.test(line)) {
      out.push(`<div class="body-num-head">${escapeHtml(line)}</div>`);
    } else {
      out.push(`<div class="body-line">${escapeHtml(line)}</div>`);
    }
  }
  return out.join("");
}

// ────────────────────────────────────────────────────────────
// 5축 SVG 레이더 차트 (Plotly 의존 제거 — vanilla SVG)
// scores = { keyword, budget, consortium(=eligibility), competitor, trl } (각 0~100)
// 주의: scores.consortium DB 컬럼은 legacy. 실제 의미는 자격 적합도(eligibility).
// ────────────────────────────────────────────────────────────
function renderRadar(scores) {
  const W = 280, H = 260;
  const cx = W / 2, cy = H / 2 + 6;
  const R = 90;  // 외곽 반경
  const axes = [
    { key: "keyword",    label: "키워드" },
    { key: "budget",     label: "예산" },
    { key: "consortium", label: "자격" },   // 의미: eligibility_fit
    { key: "competitor", label: "경쟁" },
    { key: "trl",        label: "TRL" },
  ];
  const N = axes.length;
  // 각 축의 각도 (12시 방향부터 시계방향)
  const angle = (i) => (-Math.PI / 2) + (i * 2 * Math.PI / N);

  // 격자 (20/40/60/80/100) 5단계
  const rings = [];
  for (let r = 0.2; r <= 1.0001; r += 0.2) {
    const pts = [];
    for (let i = 0; i < N; i++) {
      const a = angle(i);
      pts.push(`${cx + Math.cos(a) * R * r},${cy + Math.sin(a) * R * r}`);
    }
    rings.push(`<polygon points="${pts.join(" ")}" fill="none" stroke="#e2e8f0" stroke-width="1"/>`);
  }
  // 축 라인 (cx,cy → 각 꼭짓점)
  const axisLines = [];
  for (let i = 0; i < N; i++) {
    const a = angle(i);
    axisLines.push(`<line x1="${cx}" y1="${cy}" x2="${cx + Math.cos(a) * R}" y2="${cy + Math.sin(a) * R}" stroke="#f1f5f9" stroke-width="1"/>`);
  }
  // 점수 폴리곤
  const scorePts = [];
  const labelEls = [];
  for (let i = 0; i < N; i++) {
    const a = angle(i);
    const v = Math.max(0, Math.min(100, scores[axes[i].key] || 0)) / 100;
    scorePts.push(`${cx + Math.cos(a) * R * v},${cy + Math.sin(a) * R * v}`);
    // 축 라벨 — 외곽에서 살짝 떨어진 위치
    const lx = cx + Math.cos(a) * (R + 18);
    const ly = cy + Math.sin(a) * (R + 18) + 4;
    const anchor = Math.abs(Math.cos(a)) < 0.3 ? "middle" : (Math.cos(a) > 0 ? "start" : "end");
    labelEls.push(`<text x="${lx}" y="${ly}" text-anchor="${anchor}" class="radar-label">${axes[i].label}</text>`);
    labelEls.push(`<text x="${lx}" y="${ly + 12}" text-anchor="${anchor}" class="radar-score">${Math.round(scores[axes[i].key] || 0)}</text>`);
  }

  return `
    <svg class="radar-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg">
      ${rings.join("")}
      ${axisLines.join("")}
      <polygon points="${scorePts.join(" ")}" fill="rgba(17,17,17,0.12)" stroke="#111" stroke-width="1.8" stroke-linejoin="round"/>
      ${scorePts.map((p) => {
        const [x, y] = p.split(",");
        return `<circle cx="${x}" cy="${y}" r="3" fill="#111"/>`;
      }).join("")}
      ${labelEls.join("")}
    </svg>`;
}

function gradeOf(total) {
  if (total >= 90) return ["TOP", "top"];
  if (total >= 80) return ["GOOD", "good"];
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

  // 매칭 키워드 칩 — 클릭 시 해당 키워드로 필터링
  const kws = it.matched_keywords.filter((k) => !k.startsWith("[부서]")).slice(0, 6);
  const depts = it.matched_keywords.filter((k) => k.startsWith("[부서]"))
    .map((k) => k.replace("[부서] ", "")).slice(0, 2);
  const chipsHtml = [
    ...depts.map((d) => `<button type="button" class="chip dept" data-kw="${escapeHtml(d)}" title="이 부서로 필터링">부서·${escapeHtml(d)}</button>`),
    ...kws.map((k) => `<button type="button" class="chip" data-kw="${escapeHtml(k)}" title="이 키워드로 필터링">#${escapeHtml(k)}</button>`),
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
      ${it.ai_summary ? `<p class="card-summary">${escapeHtml(it.ai_summary)}</p>` : ""}
      ${eligLine}
      ${metaBits.length > 0 ? `<div class="card-meta">${metaBits.join('<span class="sep">·</span>')}</div>` : ""}
      ${chipsHtml ? `<div class="chips">${chipsHtml}</div>` : ""}
      <div class="axes-line">
        <span>키워드<b>${Math.round(it.scores.keyword)}</b></span>
        <span>예산<b>${Math.round(it.scores.budget)}</b></span>
        <span>자격<b>${Math.round(it.scores.consortium)}</b></span>
        <span>경쟁<b>${Math.round(it.scores.competitor)}</b></span>
        <span>TRL<b>${Math.round(it.scores.trl)}</b></span>
      </div>
      <button class="detail-toggle" data-id="${it.id}">▼ 상세 보기</button>
      <div class="card-detail" data-id="${it.id}">
        <div class="detail-radar-row">
          <div class="detail-radar">
            <h4>5축 점수</h4>
            ${renderRadar(it.scores)}
          </div>
          <div class="detail-verdict-col">
            ${renderVerdict(it)}
            ${renderAxesCompact(it.scores)}
          </div>
        </div>
        ${renderStrengths(it)}
        <h4>본문</h4>
        <div class="body-pre">${renderBody(it.body)}</div>
        ${attsHtml}
      </div>
    </div>`;
}

// ────────────────────────────────────────────────────────────
// 응찰 체크리스트 (5축 점수 → 사람 판단)
// ────────────────────────────────────────────────────────────
function _verdictFromTotal(total) {
  if (total >= 90) return { grade: "최우선 응찰", cls: "v-top", emoji: "🟢" };
  if (total >= 70) return { grade: "검토 추천",   cls: "v-good", emoji: "🔵" };
  if (total >= 50) return { grade: "조건부 검토", cls: "v-mid", emoji: "🟠" };
  return { grade: "포기 권장", cls: "v-low", emoji: "⚫" };
}

function _checkIcon(value, goodTh = 60, midTh = 40) {
  if (value >= goodTh) return { icon: "✅", cls: "ok" };
  if (value >= midTh)  return { icon: "⚠",  cls: "warn" };
  return { icon: "❌", cls: "bad" };
}

function _daysUntil(dateStr) {
  if (!dateStr || dateStr.length < 10) return null;
  const d = new Date(dateStr.slice(0, 10));
  if (isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d - today) / (1000 * 60 * 60 * 24));
}

function renderVerdict(it) {
  const sc = it.scores || {};
  const total = Math.round(sc.total || 0);
  const verdict = _verdictFromTotal(total);

  const checks = [];
  // 자격 (consortium 컬럼 = eligibility)
  const elig = _checkIcon(sc.consortium || 0);
  checks.push(`<li class="chk ${elig.cls}">${elig.icon} 응찰 자격 ${Math.round(sc.consortium || 0)}점</li>`);
  // 예산
  const bg = _checkIcon(sc.budget || 0, 70, 40);
  const budgetLabel = it.budget_mw
    ? `${(it.budget_mw / 100).toFixed(1)}억`
    : "예산 미명시";
  checks.push(`<li class="chk ${bg.cls}">${bg.icon} 예산 ${budgetLabel} (${Math.round(sc.budget || 0)}점)</li>`);
  // 마감
  const days = _daysUntil(it.deadline_at);
  if (days !== null) {
    let dcls = "ok", dico = "✅", dmsg;
    if (days < 0) { dcls = "bad"; dico = "❌"; dmsg = `마감 ${-days}일 경과`; }
    else if (days < 7) { dcls = "bad"; dico = "❌"; dmsg = `D-${days} 매우 빠듯`; }
    else if (days < 14) { dcls = "warn"; dico = "⚠"; dmsg = `D-${days} 빠듯`; }
    else if (days < 30) { dcls = "ok"; dico = "✅"; dmsg = `D-${days} 준비 가능`; }
    else { dcls = "ok"; dico = "✅"; dmsg = `D-${days} 충분`; }
    checks.push(`<li class="chk ${dcls}">${dico} 마감 ${dmsg}</li>`);
  } else {
    checks.push(`<li class="chk warn">⚠ 마감일 미명시</li>`);
  }
  // 키워드
  const kw = _checkIcon(sc.keyword || 0, 70, 50);
  checks.push(`<li class="chk ${kw.cls}">${kw.icon} 회사 키워드 매칭 ${Math.round(sc.keyword || 0)}점</li>`);
  // 경쟁
  const cp = _checkIcon(sc.competitor || 0, 60, 45);
  checks.push(`<li class="chk ${cp.cls}">${cp.icon} 경쟁 영역 ${Math.round(sc.competitor || 0)}점</li>`);

  return `
    <div class="verdict-box ${verdict.cls}">
      <div class="verdict-head">
        <span class="v-emoji">${verdict.emoji}</span>
        <span class="v-grade">${verdict.grade}</span>
        <span class="v-total">${total}/100</span>
      </div>
      <ul class="verdict-checks">${checks.join("")}</ul>
    </div>`;
}

// ────────────────────────────────────────────────────────────
// 점수 분해 컴팩트 (한 줄)
// ────────────────────────────────────────────────────────────
function renderAxesCompact(scores) {
  const items = [
    ["키워드", scores.keyword],
    ["예산", scores.budget],
    ["자격", scores.consortium],
    ["경쟁", scores.competitor],
    ["TRL", scores.trl],
  ];
  return `
    <div class="axes-compact">
      ${items.map(([label, v]) => {
        const val = Math.round(v || 0);
        const lvl = val >= 80 ? "high" : val >= 60 ? "mid" : val >= 40 ? "low" : "min";
        return `
          <div class="ax-cell ax-${lvl}">
            <div class="ax-label">${label}</div>
            <div class="ax-val">${val}</div>
          </div>`;
      }).join("")}
      <div class="ax-cell ax-theme">
        <div class="ax-label">테마</div>
        <div class="ax-val">${Math.round(scores.theme_fit || 0)}</div>
      </div>
    </div>`;
}

// ────────────────────────────────────────────────────────────
// 회사 매칭 강점 (RFP 작성 시 어필 자산 자동 추출)
// ────────────────────────────────────────────────────────────
function _norm(s) {
  return (s || "").toLowerCase().replace(/\s+/g, "");
}

function renderStrengths(it) {
  const pf = (DATA && DATA.portfolio) || {};
  const blob = _norm((it.title || "") + " " + (it.body || ""));
  if (!blob) return "";

  const strengths = [];

  // 1. 보유 기술 매칭 (가장 강한 신호)
  for (const t of (pf.technologies || [])) {
    const kws = t.keywords || [];
    const matched = kws.find(kw => kw && blob.includes(_norm(kw)));
    if (matched) {
      const trlBadge = t.trl ? ` <span class="s-trl">TRL ${t.trl}</span>` : "";
      strengths.push({
        icon: "🛡",
        text: `${t.name}${trlBadge}`,
        reason: `본문 "${matched}" 매칭`,
        weight: 100,
      });
    }
  }

  // 2. 핵심 키워드 매칭
  const coreHits = (pf.core_keywords || []).filter(k => k && blob.includes(_norm(k)));
  if (coreHits.length > 0) {
    strengths.push({
      icon: "🎯",
      text: `핵심 키워드 ${coreHits.length}개 직격`,
      reason: coreHits.slice(0, 3).join(", ") + (coreHits.length > 3 ? ` 외 ${coreHits.length - 3}개` : ""),
      weight: 80,
    });
  }

  // 3. 포지셔닝 메시지 매칭
  const posHits = (pf.positioning_keywords || []).filter(k => k && blob.includes(_norm(k)));
  if (posHits.length > 0) {
    strengths.push({
      icon: "📌",
      text: `포지셔닝 메시지 매칭`,
      reason: posHits[0],
      weight: 60,
    });
  }

  // 4. 컨소시엄 파트너 (학계/다기관 신호 있을 때)
  const consortSignal = /대학|산학|교수|컨소시엄|공동연구|참여기관|산학협력/.test(it.title || "" + it.body || "");
  if (consortSignal) {
    const universities = (pf.partners?.existing || []).filter(p => p.type === "대학");
    if (universities.length > 0) {
      const evidence = universities.find(u => u.evidence)?.evidence || "모의해킹 R&D 공동";
      strengths.push({
        icon: "🏛",
        text: `대학 파트너 ${universities.length}곳 (${universities.map(u => u.name.replace(/\(.+\)/, "")).join(", ")})`,
        reason: evidence,
        weight: 70,
      });
    }
  }

  // 5. ecosystem 파트너 (도메인 매칭)
  if (consortSignal) {
    const ecoMatches = (pf.partners?.ecosystem || []).filter(p => {
      if (!p.domain) return false;
      const areas = p.domain.split(",").map(s => _norm(s.trim())).filter(Boolean);
      return areas.some(a => blob.includes(a));
    });
    if (ecoMatches.length > 0) {
      strengths.push({
        icon: "🤝",
        text: `협력 시너지 가능: ${ecoMatches.slice(0, 3).map(p => p.name).join(", ")}`,
        reason: `같은 영역 (${ecoMatches[0].domain}) 협력 기회`,
        weight: 50,
      });
    }
  }

  // 6. KISA 2026 신기술 선정 (정보보호 전문기업 우대 시)
  if (/정보보호.*전문기업|보안.*전문기업|신기술.*기업|정보보호.*신기술/.test(it.body || "" + it.title || "")) {
    strengths.push({
      icon: "🏆",
      text: `KISA 2026 정보보호 신기술 사업화 선정 (50개사 중 1)`,
      reason: "공고 우대 조건 충족",
      weight: 90,
    });
  }

  // 7. 특허 매칭 (특허 highlights 키워드)
  const patentMatches = (pf.highlights?.patents_highlights || []).filter(ph => {
    const phLower = ph.toLowerCase();
    // 특허 제목 키워드 추출 → 본문 매칭
    if (phLower.includes("kaist") && /대학|산학|컨소시엄|네트워크.*공격|트래픽/.test(it.body || "")) return true;
    if (phLower.includes("침투 테스트") && blob.includes("모의해킹")) return true;
    if (phLower.includes("취약점") && blob.includes("취약점")) return true;
    if (phLower.includes("llm") && /llm|인공지능|ai/i.test(it.body || "")) return true;
    return false;
  });
  if (patentMatches.length > 0) {
    strengths.push({
      icon: "📜",
      text: `등록 특허 ${patentMatches.length}건 매칭 (회사 총 ${pf.highlights?.patents_total || 38}건)`,
      reason: patentMatches[0].substring(0, 60),
      weight: 75,
    });
  }

  // 8. 23.8만 건 해커 DB (AI 보안·공격 시뮬레이션 매칭 시)
  if (/ai.*보안|공격.*시뮬|위협.*인텔|레드.*팀|red.*team/i.test((it.body || "") + (it.title || ""))) {
    strengths.push({
      icon: "📊",
      text: `23.8만 건 해커 지식 DB (10년 누적, 55% NDA 실전)`,
      reason: "AI 보안·위협 모델 학습 차별점",
      weight: 65,
    });
  }

  if (strengths.length === 0) {
    return `
      <div class="strengths-empty">
        💡 자동 매칭된 회사 강점 없음 — 본문 키워드 풍부도 부족 또는 비직격 영역
      </div>`;
  }

  // 가중치 정렬 + 최대 5개
  strengths.sort((a, b) => b.weight - a.weight);
  const top = strengths.slice(0, 5);
  return `
    <div class="strengths-box">
      <h4>💼 이 공고에서 회사가 강조할 자산 (RFP 작성 시 어필)</h4>
      <ul class="strengths-list">
        ${top.map(s => `
          <li class="strength">
            <span class="s-icon">${s.icon}</span>
            <span class="s-body">
              <span class="s-text">${s.text}</span>
              <span class="s-reason">← ${s.reason}</span>
            </span>
          </li>`).join("")}
      </ul>
    </div>`;
}

// ────────────────────────────────────────────────────────────
// 시작
// ────────────────────────────────────────────────────────────
checkAuth();
