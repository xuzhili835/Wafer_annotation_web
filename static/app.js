/* 光伏硅片标注站前端(原生 JS,无框架) */
"use strict";

/* ---------- 常量:判定要点 / 依据 / 形态统计(与启动文档同口径) ---------- */
const CODE_TIPS = {
  X: "线状痕迹,两端可追踪;细长连续的一条线记一个框,断续分段可分框。",
  HBB: "点状小斑;与 HB 同族但更弥散,单点单框,成片连发按片框。",
  HBX: "较大面积异常(常在边缘);疑似黑斑+线痕复合,按整片异常范围框。",
  HS: "整片级裂纹,框常贴边且很大;沿裂纹走向框住整条,不必贴合细枝。",
  BX: "边缘缺损/缺角;框住缺损区,通常贴图像边缘。",
  KD: "片内小孔;小方框,通常远离边缘。",
  DQK: "大区域异常,常贴边;框住整个异常区域。",
  HB: "孤立小点斑;单点单框,注意与 KD 区分(依据:形态接近,以产线代码为准)。",
  XQK: "小椭圆点;稀少,遇到照实标。",
  BYW: "边缘污渍;常贴边,沿污渍范围框。",
  KYW: "极小点(2~4px);看到就框,勿漏。",
  XHB: "仅 1 例;遇到截图发群里一起看。"
};
const CODE_BASIS = {
  X: "需求书四类之一「线痕」;全库最多(373 框/211 图)",
  BX: "需求书四类之一「崩边」",
  HS: "需求书四类之一「隐裂」;框中位 609px 且 100% 贴边=整片级裂纹形态,证据最强",
  KD: "拼音 KongDong;10px 小点、仅 5% 贴边(片内小孔)",
  BYW: "拼音 BianYuanWu;40% 贴边与「边缘」吻合",
  HBB: "与 HB 同形态(13px 小点);H 前缀家族",
  HBX: "147px 中大框、70% 贴边;或为 HB+X 复合",
  HB: "11px 小点、41% 贴边;拼音/英文皆可解",
  DQK: "264px 大框、82% 贴边;拼音无解",
  XQK: "39px 小椭圆、14 框;无解",
  KYW: "4px 微点、仅 3 框;无解",
  XHB: "仅 1 框;无解"
};
const CODE_STATS = {
  X: "373 框 / 211 图 · 中位 59×59px · 贴边 38%",
  HBB: "117 框 / 101 图 · 中位 13×13px · 贴边 31%",
  HBX: "115 框 / 85 图 · 中位 147×147px · 贴边 70%",
  HS: "76 框 / 76 图 · 中位 609×609px · 贴边 100%",
  BX: "65 框 / 33 图 · 中位 32×32px · 贴边 22%",
  KD: "63 框 / 63 图 · 中位 10×10px · 贴边 5%",
  DQK: "51 框 / 51 图 · 中位 264×264px · 贴边 82%",
  HB: "49 框 / 49 图 · 中位 11×11px · 贴边 41%",
  XQK: "14 框 / 13 图 · 中位 39×39px · 贴边 36%",
  BYW: "5 框 / 2 图 · 中位 30×30px · 贴边 40%",
  KYW: "3 框 / 2 图 · 中位 4×4px · 贴边 0%",
  XHB: "1 框 / 1 图"
};
const CAND_COLORS = ["#f43f5e", "#3b82f6", "#22c55e", "#eab308"];
const ANON_NAMES = ["甲", "乙", "丙", "丁"];

/* ---------- 基础 ---------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  me: null, meta: null, refs: null,
  queue: [], qi: -1, reviseMode: null,
  stem: null, imgW: 640, imgH: 640, img: null,
  boxes: [], sel: -1, activeCode: null, isEmpty: false,
  undoStack: [], dirtyTimer: null, loadedDraft: false,
  rvStem: null,
};

async function api(path, opts = {}) {
  const o = Object.assign({ credentials: "same-origin" }, opts);
  o.headers = Object.assign({}, o.headers || {});
  const t = localStorage.getItem("wafer_token");
  if (t) o.headers["X-Token"] = t;
  if (o.json !== undefined) {
    o.method = o.method || "POST";
    o.headers["Content-Type"] = "application/json";
    o.body = JSON.stringify(o.json);
  }
  const r = await fetch(path, o);
  if (r.status === 401) { showLogin("令牌过期或无效,请重新输入"); throw new Error("401"); }
  if (!r.ok) {
    let msg = r.status + " " + r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* keep */ }
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
}

/* ---------- 登录 ---------- */
function showLogin(msg) {
  $("loginLayer").classList.remove("hidden");
  if (msg) { $("loginMsg").textContent = msg; $("loginMsg").classList.remove("hidden"); }
}
async function tryBoot() {
  try {
    const me = await api("/api/me");
    if (!me.name) throw new Error("no user");
    state.me = me.name;
    $("loginLayer").classList.add("hidden");
    $("whoami").classList.remove("hidden");
    $("whoami").querySelector("b").textContent = me.name;
    await bootApp();
  } catch (e) { showLogin(); }
}
$("btnLogin").onclick = async () => {
  const tok = $("tokenInput").value.trim();
  if (!tok) return;
  try {
    const r = await api("/api/login", { json: { token: tok } });
    localStorage.setItem("wafer_token", tok);
    state.me = r.name;
    $("loginLayer").classList.add("hidden");
    $("whoami").classList.remove("hidden");
    $("whoami").querySelector("b").textContent = r.name;
    await bootApp();
  } catch (e) {
    $("loginMsg").textContent = e.message || "登录失败";
    $("loginMsg").classList.remove("hidden");
  }
};
$("tokenInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btnLogin").click(); });
$("btnLogout").onclick = async () => {
  try { await api("/api/logout", { json: {} }); } catch (e) {}
  localStorage.removeItem("wafer_token");
  document.cookie = "wafer_token=; Max-Age=0; path=/";
  location.reload();
};

/* ---------- 导航 ---------- */
$("nav").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-view]");
  if (!b) return;
  document.querySelectorAll("#nav button").forEach((x) => x.classList.toggle("active", x === b));
  ["annotate", "progress", "review", "export", "help"].forEach((v) =>
    $("view-" + v).classList.toggle("hidden", v !== b.dataset.view));
  if (b.dataset.view === "progress") loadProgress();
  if (b.dataset.view === "review") loadArb();
  if (b.dataset.view === "export") loadSeal();
});

/* ---------- 启动 ---------- */
async function bootApp() {
  state.meta = await api("/api/meta");
  renderCodeBtns();
  renderHelp();
  try { state.refs = await (await fetch("/static/ref/reference.json")).json(); } catch (e) { state.refs = {}; }
  await reloadQueue();
  if (!localStorage.getItem("wafer_tut_done_v1")) startTut();
}

/* ---------- 类别按钮 / 参照 ---------- */
function renderCodeBtns() {
  const m = state.meta;
  $("codeBtns").innerHTML = m.codes.map((c) => {
    const key = m.keys[c], name = m.names[c] || "", rare = m.rare.includes(c);
    return '<button class="codebtn' + (rare ? " rare" : "") + '" data-code="' + c + '" title="' +
      esc(CODE_TIPS[c]) + '"><span class="sw" style="background:' + m.colors[c] + '"></span>' +
      "<b>" + c + "</b><span class=\"cn\">" + esc(name) + "</span><span class=\"k\">" + key + "</span></button>";
  }).join("");
  $("codeBtns").addEventListener("click", (e) => {
    const b = e.target.closest(".codebtn");
    if (b) setCode(b.dataset.code);
  });
  setCode(m.codes[0]);
}
function setCode(code) {
  state.activeCode = code;
  document.querySelectorAll(".codebtn").forEach((b) => {
    const on = b.dataset.code === code;
    b.classList.toggle("active", on);
    b.style.borderColor = on ? state.meta.colors[code] : "";
  });
  $("codeTips").textContent = "【" + code + " " + (state.meta.names[code] || "") + "】" + CODE_TIPS[code];
  renderRefs(code);
}
function renderRefs(code) {
  const box = $("refBox");
  const list = (state.refs && state.refs[code]) || [];
  if (!list.length) { box.innerHTML = '<p class="hint">该类暂无参照样例</p>'; return; }
  box.innerHTML = "";
  list.slice(0, 4).forEach((r) => {
    const item = document.createElement("div");
    item.className = "ref-item";
    const cv = document.createElement("canvas");
    cv.width = 640; cv.height = 640;
    cv.style.cssText = "width:100%;display:block;border-radius:6px;cursor:zoom-in";
    const img = new Image();
    img.onload = () => {
      const g = cv.getContext("2d");
      g.drawImage(img, 0, 0);
      (r.boxes || []).forEach((b) => drawRect(g, b, state.meta.colors[b.code] || "#fff", 3));
    };
    img.src = "/static/" + r.img;
    cv.onclick = () => bigLightbox(img.src, r.boxes || []);
    item.appendChild(cv);
    const cap = document.createElement("div");
    cap.className = "cap"; cap.textContent = r.stem;
    item.appendChild(cap);
    box.appendChild(item);
  });
}

/* ---------- 画布引擎 ---------- */
const cv = $("cv"), ctx = cv.getContext("2d");
let drag = null; // {type:'new'|'move'|'resize', ...}

function canvasPos(e) {
  const r = cv.getBoundingClientRect();
  return { x: Math.round((e.clientX - r.left) * 640 / r.width),
           y: Math.round((e.clientY - r.top) * 640 / r.height) };
}
function drawRect(g, b, color, lw, label) {
  g.strokeStyle = color; g.lineWidth = lw;
  g.fillStyle = color + "14";
  g.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
  g.strokeRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
  if (label) {
    g.font = "600 16px Segoe UI, sans-serif";
    const t = label, tw = g.measureText(t).width + 8;
    g.fillStyle = color;
    g.fillRect(b.x0, Math.max(0, b.y0 - 20), tw, 19);
    g.fillStyle = "#0b1220";
    g.fillText(t, b.x0 + 4, Math.max(14, b.y0 - 6));
  }
}
function render() {
  ctx.clearRect(0, 0, 640, 640);
  ctx.fillStyle = "#0b1220"; ctx.fillRect(0, 0, 640, 640);
  if (state.img) ctx.drawImage(state.img, 0, 0, 640, 640);
  const m = state.meta;
  state.boxes.forEach((b, i) => {
    const sel = i === state.sel;
    drawRect(ctx, b, m.colors[b.code] || "#fff", sel ? 3.5 : 2,
      b.code + " " + (m.names[b.code] || ""));
    if (sel) {
      ctx.fillStyle = "#fff";
      [[b.x0, b.y0], [b.x1, b.y0], [b.x0, b.y1], [b.x1, b.y1]].forEach(([x, y]) =>
        ctx.fillRect(x - 4, y - 4, 8, 8));
    }
  });
  if (drag && drag.type === "new") {
    drawRect(ctx, drag.box, m.colors[state.activeCode] || "#fff", 2);
  }
}
function hitBox(p) {
  for (let i = state.boxes.length - 1; i >= 0; i--) {
    const b = state.boxes[i];
    if (p.x >= b.x0 - 3 && p.x <= b.x1 + 3 && p.y >= b.y0 - 3 && p.y <= b.y1 + 3) return i;
  }
  return -1;
}
function hitHandle(p) {
  if (state.sel < 0) return null;
  const b = state.boxes[state.sel], H = 8;
  const corners = { nw: [b.x0, b.y0], ne: [b.x1, b.y0], sw: [b.x0, b.y1], se: [b.x1, b.y1] };
  for (const k of Object.keys(corners)) {
    const [x, y] = corners[k];
    if (Math.abs(p.x - x) <= H && Math.abs(p.y - y) <= H) return { k, b };
  }
  return null;
}
function pushUndo() {
  state.undoStack.push(JSON.stringify(state.boxes));
  if (state.undoStack.length > 60) state.undoStack.shift();
  markDirty();
}
cv.addEventListener("mousedown", (e) => {
  if (state.isEmpty) return;
  const p = canvasPos(e);
  const h = hitHandle(p);
  if (h) { pushUndo(); drag = { type: "resize", ...h }; return; }
  const i = hitBox(p);
  if (i >= 0) {
    state.sel = i;
    pushUndo();
    drag = { type: "move", sx: p.x, sy: p.y, orig: { ...state.boxes[i] } };
    render(); return;
  }
  state.sel = -1;
  pushUndo();
  drag = { type: "new", box: { code: state.activeCode, x0: p.x, y0: p.y, x1: p.x, y1: p.y } };
  render();
});
cv.addEventListener("mousemove", (e) => {
  const p = canvasPos(e);
  $("cvPos").textContent = "x=" + p.x + " y=" + p.y;
  if (!drag) {
    const h = hitHandle(p);
    cv.style.cursor = h ? "nwse-resize" : (hitBox(p) >= 0 ? "move" : "crosshair");
    return;
  }
  if (drag.type === "new") {
    drag.box.x1 = p.x; drag.box.y1 = p.y;
  } else if (drag.type === "move") {
    const b = state.boxes[state.sel], dx = p.x - drag.sx, dy = p.y - drag.sy;
    b.x0 = drag.orig.x0 + dx; b.y0 = drag.orig.y0 + dy;
    b.x1 = drag.orig.x1 + dx; b.y1 = drag.orig.y1 + dy;
  } else if (drag.type === "resize") {
    const b = state.boxes[state.sel];
    if (drag.k.includes("w")) b.x0 = p.x; else if (drag.k.includes("e")) b.x1 = p.x;
    if (drag.k.includes("n")) b.y0 = p.y; else if (drag.k.includes("s")) b.y1 = p.y;
  }
  render();
});
window.addEventListener("mouseup", () => {
  if (drag && drag.type === "new") {
    const b = drag.box;
    if (Math.abs(b.x1 - b.x0) >= 3 && Math.abs(b.y1 - b.y0) >= 3) {
      const x0 = Math.min(b.x0, b.x1), x1 = Math.max(b.x0, b.x1);
      const y0 = Math.min(b.y0, b.y1), y1 = Math.max(b.y0, b.y1);
      state.boxes.push({ code: state.activeCode, x0, y0, x1, y1 });
      state.sel = state.boxes.length - 1;
      if (state.isEmpty) { state.isEmpty = false; $("ckEmpty").checked = false; }
    }
    drag = null; render();
  } else if (drag) drag = null;
});
cv.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  const i = hitBox(canvasPos(e));
  if (i >= 0) { pushUndo(); state.boxes.splice(i, 1); state.sel = -1; render(); }
});

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (!$("view-annotate").classList.contains("hidden") === false) return;
  if (!$("loginLayer").classList.contains("hidden")) return;
  if (!$("tutLayer").classList.contains("hidden")) {
    if (e.key === "Enter") $("tutNext").click();
    return;
  }
  if (state.meta && e.key.toUpperCase() === "N") {
    state.isEmpty = $("ckEmpty").checked = !state.isEmpty;
    if (state.isEmpty) { state.sel = -1; state.boxes = []; render(); }
    return;
  }
  if ((e.key === "Delete" || e.key === "Backspace") && state.sel >= 0) {
    pushUndo(); state.boxes.splice(state.sel, 1); state.sel = -1; render(); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    if (state.undoStack.length) { state.boxes = JSON.parse(state.undoStack.pop()); state.sel = -1; render(); markDirty(); }
    return;
  }
  if (e.key === "Escape") { state.sel = -1; render(); return; }
  if (e.key === "Enter") { $("btnSubmit").click(); return; }
  if (!state.meta) return;
  const hit = state.meta.codes.find((c) => state.meta.keys[c] === e.key.toUpperCase());
  if (hit) {
    setCode(hit);
    if (state.sel >= 0) { pushUndo(); state.boxes[state.sel].code = hit; render(); }
  }
});

/* ---------- 队列与标注流 ---------- */
function annMsg(text, cls) {
  const el = $("annMsg");
  el.className = "msg " + (cls || "err");
  el.textContent = text;
  el.classList.remove("hidden");
}
function markDirty() {
  clearTimeout(state.dirtyTimer);
  state.dirtyTimer = setTimeout(() => {
    if (!state.stem) return;
    api("/api/draft", { json: { stem: state.stem, boxes: state.boxes, is_empty: state.isEmpty } })
      .catch(() => {});
  }, 800);
}
async function reloadQueue() {
  const q = (await api("/api/queue")).queue;
  state.queue = q;
  state.qi = -1;
  const todo = q.filter((o) => o.pri <= 3);
  const revise = q.filter((o) => o.pri === 4);
  const done = q.filter((o) => o.pri === 5).length;
  $("annSub").textContent = "待标 " + todo.length + " 张 · 我的回看 " + revise.length +
    " 张 · 全库已定稿 " + done + " / " + q.length;
  $("myReviseBox").innerHTML = revise.length
    ? revise.map((o) => '<span class="chip" data-stem="' + esc(o.stem) + '">' + esc(o.stem) + "</span>").join("")
    : '<span class="hint">暂无待回看的图</span>';
  $("myReviseBox").onclick = (e) => {
    const c = e.target.closest(".chip[data-stem]");
    if (c) loadStem(c.dataset.stem, true);
  };
  nextStem();
}
$("btnRefreshQ").onclick = reloadQueue;
$("btnSkip").onclick = () => nextStem(true);
function nextStem(skipCurrent) {
  const todo = state.queue.filter((o) => o.pri <= 3);
  if (!todo.length) {
    state.stem = null;
    $("annSub").textContent = "你名下的图都标完了!想加标可刷新队列帮队友接力,或去「审阅仲裁」处理分歧。";
    $("cvStem").textContent = "-";
    ctx.clearRect(0, 0, 640, 640);
    return;
  }
  state.qi = (state.qi + 1) % todo.length;
  if (skipCurrent && todo.length > 1) state.qi = (state.qi + 1) % todo.length;
  loadStem(todo[state.qi].stem, false);
}
async function loadStem(stem, revise) {
  state.stem = stem; state.reviseMode = !!revise;
  state.sel = -1; state.undoStack = []; state.loadedDraft = false;
  $("cvStem").textContent = stem + (revise ? " · 回看改判" : "");
  const t = await api("/api/task/" + stem);
  state.imgW = t.w; state.imgH = t.h;
  state.isEmpty = false; $("ckEmpty").checked = false;
  state.boxes = [];
  state.img = null;
  const img = new Image();
  img.onload = () => { state.img = img; render(); };
  img.src = "/api/image/" + stem + "?t=" + Date.now();
  if (t.my_latest) {
    state.boxes = JSON.parse(JSON.stringify(JSON.parse(t.my_latest.boxes_json)));
    state.isEmpty = !!t.my_latest.is_empty;
    $("ckEmpty").checked = state.isEmpty;
  } else if (t.draft && t.draft.length) {
    state.boxes = t.draft; state.loadedDraft = true;
    annMsg("已恢复未提交的草稿", "ok");
  }
  if (t.final) annMsg("该图已定稿——你的新提交会作为异议依据,提交后图将重开盲审", "ok");
  render();
}
$("ckEmpty").addEventListener("change", (e) => {
  state.isEmpty = e.target.checked;
  if (state.isEmpty) { pushUndo(); state.sel = -1; state.boxes = []; render(); }
});
$("btnUndo").onclick = () => {
  if (state.undoStack.length) { state.boxes = JSON.parse(state.undoStack.pop()); state.sel = -1; render(); markDirty(); }
};
$("btnClear").onclick = () => { pushUndo(); state.boxes = []; state.sel = -1; state.isEmpty = false; $("ckEmpty").checked = false; render(); };
$("btnSubmit").onclick = async () => {
  if (!state.stem) return;
  try {
    const r = await api("/api/submit", { json: {
      stem: state.stem, boxes: state.boxes, is_empty: state.isEmpty } });
    let tail = "";
    if (r.final_id) tail = r.auto === "agree" ? " · 与另一份一致,自动定稿 ✓" : " · 已达成多数,定稿 ✓";
    else if (r.conflict) tail = " · 与另一份标注不一致,已进盲审(将加派第三人)";
    else tail = " · 已提交,等其他成员标注后自动比对";
    annMsg("提交成功" + tail, "ok");
    setTimeout(() => nextStem(), 900);
  } catch (e) { annMsg(e.message); }
};

/* ---------- 进度 ---------- */
async function loadProgress() {
  const d = await api("/api/progress");
  const c = { pending: 0, wip: 0, ready: 0, conflict: 0, final: 0 };
  d.cells.forEach((x) => c[x.status]++);
  const me = d.people[d.me] || { assigned: 0, submitted: 0 };
  $("progKpis").innerHTML = [
    [d.cells.length, "总图数"], [c.final, "已定稿"],
    [c.conflict, "分歧待审"], [c.pending + c.wip, "还没人标"],
    [me.assigned, "分配给我"], [me.submitted, "我已提交"],
  ].map(([v, k]) => '<div class="kpi"><b>' + v + "</b><span>" + k + "</span></div>").join("");
  $("heat").innerHTML = d.cells.map((x) =>
    '<button class="cell lg-' + x.status + '" data-stem="' + esc(x.stem) + '" title="' +
    esc(x.stem) + " · " + x.status + " · " + x.n + " 份\"></button>").join("");
  state.progCells = d.cells;
  $("heat").onclick = (e) => {
    const b = e.target.closest(".cell[data-stem]");
    if (!b) return;
    const cell = d.cells.find((x) => x.stem === b.dataset.stem);
    if (cell && cell.status === "final") {
      document.querySelector('#nav button[data-view="review"]').click();
      openReview(b.dataset.stem);
    } else {
      document.querySelector('#nav button[data-view="annotate"]').click();
      loadStem(b.dataset.stem, false);
    }
  };
}

/* ---------- 审阅仲裁 ---------- */
$("btnLoadArb").onclick = loadArb;
async function loadArb() {
  const d = await api("/api/arbitration");
  $("arbCount").textContent = d.list.length;
  $("arbList").innerHTML = d.list.length
    ? d.list.map((s) => '<div class="arb-item" data-stem="' + esc(s) + '"><code>' + esc(s) + "</code><span>盲审 →</span></div>").join("")
    : '<p class="hint">没有分歧待决的图,稳!</p>';
  $("arbList").onclick = (e) => {
    const it = e.target.closest(".arb-item[data-stem]");
    if (it) openReview(it.dataset.stem);
  };
}
async function openReview(stem) {
  state.rvStem = stem;
  document.querySelectorAll(".arb-item").forEach((x) =>
    x.classList.toggle("active", x.dataset.stem === stem));
  const d = await api("/api/review/" + stem);
  $("rvTitle").innerHTML = "盲审面板 · <code>" + esc(stem) + "</code> " +
    (d.final ? '<span class="pill ok">已定稿</span>' : '<span class="pill wip">未定稿 · 匿名中</span>') +
    ' <span class="hint inline">第 ' + d.round + " 轮 · 已收 " + d.votes + " 票</span>";
  const rc = $("rv"), g = rc.getContext("2d");
  g.clearRect(0, 0, 640, 640);
  g.fillStyle = "#0b1220"; g.fillRect(0, 0, 640, 640);
  const img = new Image();
  img.onload = () => { g.drawImage(img, 0, 0, 640, 640); paintCands(g, d); };
  img.src = "/api/image/" + stem + "?t=" + Date.now();
  $("rvCands").innerHTML = d.candidates.length
    ? d.candidates.map((c, i) => {
        const color = CAND_COLORS[i % CAND_COLORS.length];
        const isMine = c.annotator === state.me;
        return '<div class="cand-card' + (isMine ? " mine" : "") + (d.final && d.tally[c.id] ? " chosen" : "") + '">'
          + '<div class="row"><span class="anon" style="color:' + color + '">' + esc(c.anon)
          + (isMine ? "(你)" : "") + "</span><span>" + (c.is_empty ? "本图无缺陷" : c.boxes.length + " 框")
          + "</span><b>" + (d.tally[c.id] || 0) + " 票</b></div>"
          + '<div class="row"><span class="meta">' + esc(c.submitted_at)
          + (c.annotator ? " · 真名:" + esc(c.annotator) : "") + "</span>"
          + (d.final ? "" : '<button class="btn" data-vote="' + c.id + '"' +
              (d.my_vote === c.id ? " disabled" : "") + ">" + (d.my_vote === c.id ? "已投" : "投这份") + "</button>")
          + "</div></div>";
      }).join("") + (d.final ? "" : '<p class="hint small">盲审规则:定稿前匿名;≥3 票且多数即定稿;平票兜底取最早提交的一份。</p>')
    : '<p class="hint">这张图还没有任何有效标注</p>';
  $("rvCands").onclick = async (e) => {
    const b = e.target.closest("[data-vote]");
    if (!b) return;
    try {
      await api("/api/vote", { json: { stem, chosen_id: parseInt(b.dataset.vote, 10) } });
      openReview(stem);
    } catch (err) { rvMsg(err.message); }
  };
  $("rvDisputes").innerHTML = d.final
    ? '<div class="toolbar"><button class="btn" id="btnDispute">我有异议(重开盲审)</button></div>'
      + (d.disputes.length ? '<p class="hint small">历史异议:' + d.disputes.map((x) =>
          esc(x.raised_by) + ":" + esc(x.reason)).join(" · ") + "</p>" : "")
    : (d.disputes.length ? '<p class="hint small">历史异议:' + d.disputes.map((x) =>
        esc(x.raised_by) + ":" + esc(x.reason)).join(" · ") + "</p>" : "");
  const db = $("btnDispute");
  if (db) db.onclick = () => {
    const reason = prompt("一句话说清为什么重审(至少 4 个字):");
    if (reason == null) return;
    api("/api/dispute", { json: { stem, reason } })
      .then(() => openReview(stem))
      .catch((err) => alert(err.message));
  };
}
function rvMsg(t) {
  $("rvMsg").textContent = t;
  $("rvMsg").classList.remove("hidden");
}
function paintCands(g, d) {
  d.candidates.forEach((c, i) => {
    const color = CAND_COLORS[i % CAND_COLORS.length];
    (c.boxes || []).forEach((b) => drawRect(g, b, color, 3, c.anon + "·" + b.code));
  });
}

/* ---------- 导出与封板 ---------- */
document.querySelectorAll("[data-exp]").forEach((b) => {
  b.onclick = async () => {
    const r = await api("/api/export/" + b.dataset.exp);
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const name = (cd.match(/filename=([^;]+)/) || [])[1] || b.dataset.exp;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name.trim();
    a.click();
  };
});
async function loadSeal() {
  const s = await api("/api/seal");
  $("sealPill").textContent = s.sealed ? "已封板" : "未封板(" + s.count + "/3)";
  $("sealPill").className = "pill " + (s.sealed ? "ok" : "todo");
  $("sealWho").innerHTML = s.votes.length
    ? s.votes.map((v) => '<span class="chip ok">' + esc(v) + " ✓</span>").join("")
    : '<span class="hint">还没有人同意</span>';
  $("btnSeal").disabled = s.votes.includes(state.me);
}
$("btnSeal").onclick = async () => {
  await api("/api/seal", { json: {} });
  loadSeal();
};

/* ---------- 帮助 ---------- */
function renderHelp() {
  $("helpFlowBody").innerHTML =
    "<ol><li><b>看图找缺陷</b> —— 640px 灰度硅片图,缺陷可能是线痕、崩边、小点、大片裂纹等;</li>" +
    "<li><b>画框</b> —— 在缺陷上按住拖拽;点框选中后可拖动/四角缩放/右键或 Delete 删除;</li>" +
    "<li><b>选类别</b> —— 右侧点按钮或按快捷键(<kbd>1</kbd>~<kbd>9</kbd>,<kbd>0</kbd>,<kbd>Q</kbd>,<kbd>W</kbd>);选中框后按类别键可改它的类;</li>" +
    "<li><b>拿不准</b> —— 看参照样例和悬停判定要点;纯无缺陷的图勾「本图无缺陷」或按 <kbd>N</kbd>;</li>" +
    "<li><b>提交</b> —— <kbd>Enter</kbd> 或点提交;之后图进盲审流程,分歧自动加第三人。</li></ol>";
  $("helpCoop").innerHTML =
    '<table class="help-table"><tr><th style="width:130px">机制</th><th>规则</th></tr>' +
    "<tr><td>分配</td><td>每张图恰好 2 人打底(随机、每人约 255 张);不锁图,想加标随时加,进度板全透明。</td></tr>" +
    "<tr><td>留痕</td><td>每次提交/改判/撤销都是新记录,只追加不改写;可回放、可算每人一致率。</td></tr>" +
    "<tr><td>分歧</td><td>两份不一致 → 自动加派第三人盲标;框数相同且同码框 IoU≥0.6 视为一致。</td></tr>" +
    "<tr><td>定稿</td><td>2 份一致自动定稿;不一致看盲投:≥3 票且多数 → 定稿;平票兜底取最早提交。</td></tr>" +
    "<tr><td>盲审</td><td>定稿前 everyone 匿名(甲乙丙丁),投完才解锁真名 —— 防碍于情面。</td></tr>" +
    "<tr><td>异议重审</td><td>对定稿有异议,一键「我有异议」+ 一句话理由,自动重开盲投(旧票作废)。</td></tr>" +
    "<tr><td>封板</td><td>任意一人发起,3/4 同意即锁定;训练只认封板后导出的 VOC XML。</td></tr>" +
    '<tr><td>导出</td><td>任何人随时可导(留痕 csv / 定稿 csv / VOC XML 包),服务端实时快照,永不"不同步"。</td></tr></table>';
  const m = state.meta;
  $("helpCodes").innerHTML = "<table class=\"help-table\"><tr><th>代码</th><th>推断名</th><th>全库规模(测试集)</th><th>判定要点</th><th>依据</th></tr>" +
    m.codes.map((c) => "<tr><td><b>" + c + "</b></td><td>" + esc(m.names[c] || "") +
      (m.rare.includes(c) ? ' <span class="chip rare">稀有</span>' : "") + "</td><td>" +
      esc(CODE_STATS[c] || "") + "</td><td>" + esc(CODE_TIPS[c]) + "</td><td>" +
      esc(CODE_BASIS[c] || "") + "</td></tr>").join("") + "</table>" +
    '<p class="hint small">中文名未经数据方确认,问号表示推断;官方对照拿到后只改一张表。</p>';
  const refs = $("helpRefs");
  refs.innerHTML = "";
  m.codes.forEach((c) => {
    ((state.refs || {})[c] || []).slice(0, 2).forEach((r) => {
      const item = document.createElement("div");
      item.className = "ref-item";
      const cvh = document.createElement("canvas");
      cvh.width = 640; cvh.height = 640;
      cvh.style.cssText = "width:100%;display:block;border-radius:6px;cursor:zoom-in";
      const img = new Image();
      img.onload = () => {
        const g = cvh.getContext("2d");
        g.drawImage(img, 0, 0);
        (r.boxes || []).forEach((b) => drawRect(g, b, m.colors[b.code] || "#fff", 3));
      };
      img.src = "/static/" + r.img;
      cvh.onclick = () => bigLightbox(img.src, r.boxes || []);
      item.appendChild(cvh);
      const cap = document.createElement("div");
      cap.className = "cap"; cap.textContent = c + " · " + r.stem;
      item.appendChild(cap);
      refs.appendChild(item);
    });
  });
  $("helpFaq").innerHTML =
    '<div class="faq-item"><b>标错了怎么办?</b> 定稿前:在「回看改判」里重新提交即可(留痕,不改历史);整笔撤销找组长在导出的留痕表里看,或重新提交一份正确的——投票只看最新有效标注。</div>' +
    '<div class="faq-item"><b>两人标的框差几个像素算分歧吗?</b> 不算。框数相同、同码框位置重叠足够大(IoU≥0.6)即视为一致,自动定稿。</div>' +
    '<div class="faq-item"><b>平票怎么办?</b> 兜底规则:取提交时间最早的一份定稿(规则公示,非人为裁定)。</div>' +
    '<div class="faq-item"><b>令牌失效?</b> 浏览器保存 7 天,过期回登录页重贴一次即可;令牌本身永久有效。</div>' +
    '<div class="faq-item"><b>图加载慢?</b> 每张 640px 灰度 png 仅几十 KB;若网络抖动,点「刷新队列」重进。</div>';
}

/* ---------- 新手引导 ---------- */
const TUT = [
  { t: "欢迎来到光伏硅片标注站", b: "我们要给 510 张硅片图<b>画框 + 选缺陷类别</b>。<ul><li>每张图会由 2 人独立标注</li><li>分歧自动加第三人盲审,多数票定稿</li><li>全程留痕,标错可改,别有压力</li></ul>跟着引导走一遍(约 1 分钟)。" },
  { t: "看图找缺陷", b: "左边深色区就是硅片图(640×640 灰度)。常见缺陷:<b>线痕</b>(细长线)、<b>崩边</b>(边缘缺损)、<b>隐裂</b>(大片贴边裂纹)、<b>小点斑</b>(孤立小点)。看不准就对照右侧「参照样例」。" },
  { t: "画框", b: "在缺陷上<b>按住鼠标拖拽</b>即画一个框。<ul><li>点框选中,拖动可移位</li><li>拖四角白点可缩放</li><li>右键点框 / 选中按 <kbd>Delete</kbd> 删除</li><li><kbd>Ctrl+Z</kbd> 撤销</li></ul>" },
  { t: "选类别", b: "右侧 12 个类别按钮,<b>快捷键见角标</b>(<kbd>1</kbd>~<kbd>9</kbd>,<kbd>0</kbd>,<kbd>Q</kbd>,<kbd>W</kbd>)。<ul><li>先选类再画框;选中已有框后按类别键可改它的类</li><li>悬停按钮有判定要点</li><li>整图无缺陷:勾选「本图无缺陷」或按 <kbd>N</kbd>,很重要,别硬找框!</li></ul>" },
  { t: "提交与改判", b: "画完点「提交本图」或按 <kbd>Enter</kbd>,<b>每画一笔自动存草稿</b>,崩了不怕。<ul><li>提交后图进盲审流程</li><li>「回看改判」可重新提交自己标过的未定稿图</li></ul>" },
  { t: "分歧怎么办", b: "两人不一致 → 自动加派第三人盲审 → 多数票定稿,平票全员仲裁。<b>定稿前所有人都匿名(甲乙丙丁)</b>,放平心态,你的判断有价值。有异议随时重审,无理由才不受理。" },
  { t: "开始吧!", b: "队列已按你的分配洗好牌,直接开标。规则细节在「帮助与方案」页随时可查。<br><br><b>记住:如实标,不猜目录,不看别人。</b>" },
];
let tutIdx = 0;
function startTut() {
  tutIdx = 0;
  $("tutLayer").classList.remove("hidden");
  renderTut();
}
function renderTut() {
  const s = TUT[tutIdx];
  $("tutStep").textContent = "引导 " + (tutIdx + 1) + " / " + TUT.length;
  $("tutTitle").textContent = s.t;
  $("tutBody").innerHTML = s.b;
  $("tutPrev").disabled = tutIdx === 0;
  $("tutNext").textContent = tutIdx === TUT.length - 1 ? "开工!" : "下一步";
}
$("tutPrev").onclick = () => { if (tutIdx > 0) { tutIdx--; renderTut(); } };
$("tutNext").onclick = () => {
  if (tutIdx < TUT.length - 1) { tutIdx++; renderTut(); }
  else { $("tutLayer").classList.add("hidden"); localStorage.setItem("wafer_tut_done_v1", "1"); }
};
$("btnTut").onclick = startTut;
$("btnTut2").onclick = startTut;

/* ---------- 灯箱 ---------- */
function bigLightbox(src, boxes) {
  const lb = $("lightbox"), im = $("lightboxImg");
  const cvb = document.createElement("canvas");
  cvb.width = 640; cvb.height = 640;
  cvb.style.cssText = "max-width:92vw;max-height:92vh;border-radius:10px";
  const g = cvb.getContext("2d");
  const i = new Image();
  i.onload = () => {
    g.drawImage(i, 0, 0);
    (boxes || []).forEach((b) => drawRect(g, b, state.meta.colors[b.code] || "#fff", 3));
  };
  i.src = src;
  lb.innerHTML = "";
  lb.appendChild(cvb);
  lb.classList.remove("hidden");
  lb.onclick = () => lb.classList.add("hidden");
}

/* ---------- go ---------- */
tryBoot();
