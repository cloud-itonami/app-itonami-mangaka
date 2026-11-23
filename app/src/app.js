// Mangaka reader shell. The WebView reads the public reader API
// (https://mangaka.itonami.cloud) directly — the same posture as the
// studio static Worker, which reads the reader's public API from the
// browser. No D1/R2 here, no secrets, no POST: writes to the pipeline go
// through the reader's authenticated POST /api/work/:rkey, deliberately
// not wired into this page (studio README).
import data from "./data.js";
import {
  MODE_SPREAD, MODE_SINGLE, MODE_SCROLL,
  resolveUrl, workApiUrl, worksApiUrl, filterWorks, genreTags,
  buildUnits, unitOf, countLabel, stepUnit, initialMode,
} from "./view.js";

const { identity, version } = data;
const ORIGIN = identity.origin;
const $ = (id) => document.getElementById(id);

const worksSection = $("screen-works");
const readerSection = $("screen-reader");
const aboutSection = $("screen-about");
const screenTitle = $("screen-title");
const screenSub = $("screen-sub");
const backBtn = $("back-btn");
const refreshBtn = $("refresh-btn");
const searchInput = $("search");
const countLabelEl = $("count-label");
const worksStatus = $("works-status");
const worksGrid = $("works-grid");
const versionsEl = $("versions");
const readerMeta = $("reader-meta");
const readerStatus = $("reader-status");
const stage = $("stage");
const spread = $("spread");
const scroll = $("scroll");
const countEl = $("count");
const hintEl = $("hint");
const aboutBody = $("about-body");

let screen = "works";
let works = [];
let worksLoaded = false;
let currentWork = null;
let pages = [];
let mode = initialMode(window.innerWidth || 390);
let idx = 0;
let units = [];

function showScreen(name) {
  screen = name;
  worksSection.hidden = name !== "works";
  readerSection.hidden = name !== "reader";
  aboutSection.hidden = name !== "about";
  backBtn.hidden = name !== "reader";
  refreshBtn.hidden = name === "reader";
  $("nav-works").classList.toggle("is-active", name !== "about");
  $("nav-about").classList.toggle("is-active", name === "about");
  if (name === "works") {
    screenTitle.textContent = "Mangaka 作品一覧";
    screenSub.textContent = "公開リーダーの実 UI — 作品一覧から読書画面へ";
  }
  if (name === "about") {
    screenTitle.textContent = "このアプリについて";
    screenSub.textContent = "通信先と境界の説明";
    renderAbout();
  }
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function errorBox(message, retryFn) {
  const box = el("div", "problem-box");
  box.append(el("p", "", message));
  if (retryFn) {
    const btn = el("button", "btn", "もう一度試す");
    btn.type = "button";
    btn.addEventListener("click", retryFn);
    box.append(btn);
  }
  return box;
}

// ---------- works list ----------

function renderWorks() {
  const q = searchInput.value;
  const list = filterWorks(works, q);
  countLabelEl.textContent = worksLoaded ? `${list.length} 件` : "";
  worksGrid.replaceChildren();
  if (!worksLoaded) return;
  if (!works.length) {
    worksStatus.replaceChildren(errorBox("まだ公開作品がありません。通信先を確認してください。", loadWorks));
    return;
  }
  if (!list.length) {
    worksStatus.replaceChildren(el("p", "sub", "条件に合う作品がありません。"));
    return;
  }
  worksStatus.replaceChildren();
  for (const w of list) {
    const card = el("button", "card");
    card.type = "button";
    card.setAttribute("aria-label", `${w.title} を読む`);
    const cover = document.createElement("img");
    cover.loading = "lazy";
    cover.alt = "";
    cover.src = resolveUrl(ORIGIN, w.cover) || "";
    cover.draggable = false;
    card.append(cover);
    const title = el("span", "card-title", w.title || w.rkey);
    card.append(title);
    card.append(el("span", "card-series", [w.series, w.pageCount ? `${w.pageCount} ページ` : ""].filter(Boolean).join(" · ")));
    const tags = genreTags(w.genre);
    if (tags.length) {
      const tagRow = el("span", "card-tags");
      for (const t of tags) tagRow.append(el("span", "chip", t));
      card.append(tagRow);
    }
    if (w.logline) card.append(el("span", "card-logline", w.logline));
    card.addEventListener("click", () => openWork(w.rkey));
    worksGrid.append(card);
  }
}

async function loadWorks() {
  worksStatus.replaceChildren(el("p", "sub", "作品を読み込んでいます…"));
  worksGrid.replaceChildren();
  try {
    const res = await fetch(worksApiUrl(ORIGIN), { headers: { accept: "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    works = Array.isArray(json.works) ? json.works : [];
    worksLoaded = true;
    renderWorks();
  } catch (err) {
    worksLoaded = false;
    worksStatus.replaceChildren(errorBox(`作品一覧を読み込めませんでした（${err.message}）。通信を確認してください。`, loadWorks));
  }
}

// ---------- work reader ----------

function setMode(m) {
  mode = m;
  for (const id of [MODE_SPREAD, MODE_SINGLE, MODE_SCROLL]) {
    $("m-" + id).classList.toggle("on", id === m);
  }
  renderReader();
}

function preload(i) {
  if (i >= 0 && i < pages.length) {
    const im = new Image();
    im.src = pages[i].src;
  }
}

function renderReader() {
  const stageVisible = mode !== MODE_SCROLL;
  stage.hidden = !stageVisible;
  scroll.hidden = stageVisible;
  stage.style.display = stageVisible ? "flex" : "none";
  scroll.style.display = stageVisible ? "none" : "flex";
  if (mode === MODE_SCROLL) {
    if (!scroll.dataset.built) {
      scroll.replaceChildren();
      for (const p of pages) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = p.src;
        img.alt = `p${p.n}`;
        scroll.append(img);
      }
      scroll.dataset.built = "1";
    }
    countEl.textContent = pages.length ? `縦読 ${pages.length} ページ` : "0 / 0";
    return;
  }
  units = buildUnits(pages, mode);
  let ui = unitOf(units, idx);
  if (ui < 0) ui = 0;
  const u = units[ui] || [0];
  const order = mode === MODE_SPREAD ? [...u].reverse() : u;
  spread.replaceChildren();
  for (const i of order) {
    const img = document.createElement("img");
    img.src = pages[i].src;
    img.alt = `p${pages[i].n}`;
    spread.append(img);
  }
  idx = u[0];
  preload(u[u.length - 1] + 1);
  preload(u[u.length - 1] + 2);
  preload(u[0] - 1);
  countEl.textContent = countLabel(pages, u);
}

function next() {
  if (mode === MODE_SCROLL) return;
  const nextIdx = stepUnit(units, idx, +1);
  if (nextIdx !== idx) { idx = nextIdx; renderReader(); }
}
function prev() {
  if (mode === MODE_SCROLL) return;
  const prevIdx = stepUnit(units, idx, -1);
  if (prevIdx !== idx) { idx = prevIdx; renderReader(); }
}

function renderVersions(versions, currentRkey) {
  versionsEl.replaceChildren();
  if (!versions || versions.length < 2) {
    versionsEl.hidden = true;
    return;
  }
  versionsEl.hidden = false;
  versionsEl.append(el("span", "versions-label", "version:"));
  for (const v of versions) {
    if (v.current) {
      versionsEl.append(el("b", "version-current", v.label || v.rkey));
    } else {
      const a = el("a", "version-link", v.label || v.rkey);
      a.href = "#";
      a.addEventListener("click", (e) => { e.preventDefault(); openWork(v.rkey); });
      versionsEl.append(a);
    }
  }
  void currentRkey;
}

async function openWork(rkey) {
  showScreen("reader");
  screenTitle.textContent = "読書画面";
  screenSub.textContent = "作品を読み込んでいます…";
  currentWork = null;
  pages = [];
  idx = 0;
  units = [];
  spread.replaceChildren();
  scroll.replaceChildren();
  scroll.dataset.built = "";
  versionsEl.hidden = true;
  readerStatus.replaceChildren(el("p", "sub", "作品を読み込んでいます…"));
  countEl.textContent = "";
  try {
    const res = await fetch(workApiUrl(ORIGIN, rkey), { headers: { accept: "application/json" } });
    if (res.status === 404) {
      readerStatus.replaceChildren(errorBox("作品が見つかりません。", () => showScreen("works")));
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    currentWork = json;
    pages = (json.pages || []).map((p) => ({ n: p.n, src: resolveUrl(ORIGIN, p.src) || "" }));
    if (!pages.length) {
      readerStatus.replaceChildren(errorBox("この作品にはページがありません。", () => showScreen("works")));
      return;
    }
    screenTitle.textContent = json.title || rkey;
    screenSub.textContent = [json.author, json.series].filter(Boolean).join(" · ") || "公開リーダー";
    readerMeta.textContent = [json.author, json.series, json.genre].filter(Boolean).join(" · ");
    readerStatus.replaceChildren();
    renderVersions(json.versions, rkey);
    setMode(initialMode(window.innerWidth || 390));
    preload(0); preload(1);
  } catch (err) {
    readerStatus.replaceChildren(errorBox(`作品を読み込めませんでした（${err.message}）。`, () => openWork(rkey)));
  }
}

// ---------- about ----------

function renderAbout() {
  const rows = [
    ["アプリ名", identity.title],
    ["ID", identity.id],
    ["バージョン", version],
    ["リポジトリ", identity.source],
    ["作品カタログ", identity.catalog],
    ["通信先", `${identity.origin} （GET のみ・読み取り専用）`],
    ["書き込み", "ありません。このアプリは作品データへの書き込みを行いません。"],
    ["承認境界", "broker / murakumo への呼び出しは含みません（第1段階は reader のみ）。画像生成 API は第2段階の承認で追加します。"],
  ];
  aboutBody.replaceChildren();
  const dl = el("dl", "about-list");
  for (const [k, v] of rows) {
    dl.append(el("dt", "", k), el("dd", "", v));
  }
  aboutBody.append(dl);
  aboutBody.append(el("p", "muted", "通信は公開 API（access-control-allow-origin: * を確認済み）のみ。ページ画像も同じ origin から読みます。"));
}

// ---------- wiring ----------

backBtn.addEventListener("click", () => showScreen("works"));
refreshBtn.addEventListener("click", () => { if (screen === "works") loadWorks(); });
searchInput.addEventListener("input", renderWorks);
$("m-spread").addEventListener("click", () => setMode(MODE_SPREAD));
$("m-single").addEventListener("click", () => setMode(MODE_SINGLE));
$("m-scroll").addEventListener("click", () => setMode(MODE_SCROLL));
$("z-left").addEventListener("click", next);
$("z-right").addEventListener("click", prev);
$("nav-works").addEventListener("click", () => showScreen("works"));
$("nav-about").addEventListener("click", () => showScreen("about"));

let tx = 0;
stage.addEventListener("touchstart", (e) => { tx = e.touches[0].clientX; }, { passive: true });
stage.addEventListener("touchend", (e) => {
  const dx = e.changedTouches[0].clientX - tx;
  if (Math.abs(dx) > 50) { dx < 0 ? next() : prev(); }
});

document.addEventListener("keydown", (e) => {
  if (screen !== "reader") return;
  if (e.key === "ArrowLeft" || e.key === " ") { next(); e.preventDefault(); }
  else if (e.key === "ArrowRight") prev();
});

showScreen("works");
loadWorks();
