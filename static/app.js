/* 光伏硅片标注站前端(原生 JS,无框架) */
"use strict";

/* ---------- 常量:判定要点 / 依据 / 形态统计(与启动文档同口径) ---------- */
const CODE_TIPS = {
  X: "隐裂/裂纹:细暗线,斜向或 X 形交叉,可贯穿整图;沿裂纹走向一条线记一个框。",
  BX: "崩边/崩缺点:边缘锐利的月牙/三角状小块,可暗可亮(白色崩边),常是裂纹起始点;贴边框。",
  HB: "黑斑:单个/少量小暗点;单点单框,注意与孔洞(KD)区分。",
  HBB: "黑斑-边部:成簇小黑点,集中在硅片边缘/角落;按簇框(B=边部)。",
  HBX: "黑斑-心部:中部云雾状片状暗斑(X=心部);按整片异常范围框。",
  XHB: "线黑斑:L 形/线状暗痕;极稀有(测试集仅 1 例),遇到照实标。",
  HS: "划伤:一组平行斜向细划痕;沿整组划痕走向框一个大框。",
  KD: "孔洞:数像素大的圆形暗点/小坑;小方框,通常远离边缘。",
  DQK: "大缺角:角部大块缺损(D=大,QK=缺角);框住整个缺损区。",
  XQK: "小缺角:硅片边缘线上的小缺口(X=小);小框贴边。",
  BYW: "(白)油污:不规则云雾状污渍斑;沿污渍范围框。",
  KYW: "颗粒油污:4~10 像素的油污小点;看到就框,勿漏。"
};
const CODE_BASIS = {
  X: "产线标注路径就叫「隐裂」;全库最多(373 框/211 图)",
  BX: "产线路径含「白色崩边」;月牙/三角小块,常是裂纹起点",
  HS: "看图确认:一组平行斜向细划痕;76 框",
  KD: "产线标注路径直接叫「孔洞」;圆形暗点/小坑",
  DQK: "Da QueJiao=大缺角;角部大块缺损、82% 贴边吻合",
  XQK: "Xiao QueJiao=小缺角;边缘线上小缺口,14 框",
  HBB: "HeiBan-Bian=黑斑·边部;成簇小点集中在边缘/角落",
  HBX: "HeiBan-Xin=黑斑·心部;中部云雾状片状暗斑",
  HB: "HeiBan=黑斑;单个暗点",
  BYW: "Bai YouWu=(白)油污;云雾状污渍斑",
  KYW: "KeLi YouWu=颗粒油污;4~10px 油污小点,仅 3 框",
  XHB: "Xian HeiBan=线黑斑;L 形/线状暗痕,仅 1 例"
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
  if (b.dataset.view === "progress") { loadProgress(); startProgressPolling(); }
  else stopProgressPolling();
  if (b.dataset.view === "annotate") startTopPolling();
  else stopTopPolling();
  if (b.dataset.view === "review") loadArb();
  if (b.dataset.view === "export") loadSeal();
});

/* ---------- 启动 ---------- */
async function bootApp() {
  state.meta = await api("/api/meta");
  renderCodeBtns();
  renderHelp();
  try { state.refs = await (await fetch("/static/ref/reference.json")).json(); } catch (e) { state.refs = {}; }
  // 产线实测参照样例(测试集真框)异步替换示意样例;拉不到就维持兜底,不阻塞启动
  fetch("/api/reference_prod", { headers: { "X-Token": localStorage.getItem("wafer_token") || "" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      if (j && j.codes && Object.keys(j.codes).length) {
        state.refs = j.codes;
        renderRefs(state.activeCode);
        renderHelp();
      }
    }).catch(() => {});
  await reloadQueue();
  startTopPolling();
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
function refLegendHtml(boxes) {
  const seen = [...new Set((boxes || []).map((b) => b.code))];
  if (!seen.length) return "";
  return '<div class="ref-legend">' + seen.map((c) =>
    '<span><i style="background:' + (state.meta.colors[c] || "#fff") + '"></i>'
    + esc((state.meta.names && state.meta.names[c]) || c) + "</span>").join("") + "</div>";
}
function renderRefs(code) {
  const box = $("refBox");
  const list = (state.refs && state.refs[code]) || [];
  if (!list.length) { box.innerHTML = '<p class="hint">该类暂无参照样例</p>'; return; }
  state.refPage = state.refPage || {};
  state.refPage[code] = state.refPage[code] || 0;
  const per = 4, pages = Math.ceil(list.length / per), page = Math.min(state.refPage[code], pages - 1);
  state.refPage[code] = page;
  const nav = pages > 1
    ? '<div class="toolbar" style="margin-bottom:6px"><button class="btn" id="refPrev">‹</button>'
      + '<span class="hint inline">第 ' + (page + 1) + " / " + pages + " 页 · 共 " + list.length + " 张</span>"
      + '<button class="btn" id="refNext">›</button></div>'
    : "";
  box.innerHTML = nav + '<div id="refPageBox" class="ref-grid"></div>';
  const holder = $("refPageBox");
  list.slice(page * per, page * per + per).forEach((r) => {
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
    img.src = r.url || ("/static/" + r.img);
    cv.onclick = () => bigLightbox(img.src, r.boxes || []);
    item.appendChild(cv);
    item.insertAdjacentHTML("beforeend", refLegendHtml(r.boxes));
    const cap = document.createElement("div");
    cap.className = "cap"; cap.textContent = r.stem;
    item.appendChild(cap);
    holder.appendChild(item);
  });
  if (pages > 1) {
    $("refPrev").onclick = () => { state.refPage[code] = (page - 1 + pages) % pages; renderRefs(code); };
    $("refNext").onclick = () => { state.refPage[code] = (page + 1) % pages; renderRefs(code); };
  }
}

/* ---------- 画布引擎 ---------- */
const cv = $("cv"), ctx = cv.getContext("2d");
let drag = null; // {type:'new'|'move'|'resize', ...}

function canvasPos(e) {
  const r = cv.getBoundingClientRect();
  return { x: Math.round((e.clientX - r.left) * 640 / r.width),
           y: Math.round((e.clientY - r.top) * 640 / r.height) };
}
function drawRect(g, b, color, lw, label, labelRow) {
  g.strokeStyle = color; g.lineWidth = lw;
  g.fillStyle = color + "14";
  g.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
  g.strokeRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
  if (label) {
    const row = labelRow || 0;                 // 多候选叠加时标签按层错开,不被别的框盖住
    g.font = "600 16px Segoe UI, sans-serif";
    const t = label, tw = g.measureText(t).width + 8;
    g.fillStyle = color;
    g.fillRect(b.x0, Math.max(0, b.y0 - 20 - row * 20), tw, 19);
    g.fillStyle = "#0b1220";
    g.fillText(t, b.x0 + 4, Math.max(14, b.y0 - 6 - row * 20));
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
  if (e.altKey || e.shiftKey) {
    // 强制新建:多个缺陷堆在一起时,先框了大的,按住 Alt(或 Shift)拖即可在里面框小的
    state.sel = -1;
    pushUndo();
    drag = { type: "new", box: { code: state.activeCode, x0: p.x, y0: p.y, x1: p.x, y1: p.y } };
    render();
    return;
  }
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
    cv.style.cursor = (e.altKey || e.shiftKey) ? "copy"
      : (h ? "nwse-resize" : (hitBox(p) >= 0 ? "move" : "crosshair"));
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
  clearTimeout(state.msgTimer);
  state.msgTimer = setTimeout(() => el.classList.add("hidden"), 8000);
}
function markDirty() {
  clearTimeout(state.dirtyTimer);
  state.dirtyTimer = setTimeout(() => {
    if (!state.stem) return;
    api("/api/draft", { json: { stem: state.stem, boxes: state.boxes, is_empty: state.isEmpty } })
      .catch(() => {});
  }, 800);
}
function paintTopbar(q) {
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
}
async function refreshTopbar() {
  // 轻量刷新:只更新顶栏数字与回看列表,绝不动当前队列位置/画布(不打断标注)
  try { paintTopbar((await api("/api/queue")).queue); } catch (e) { /* 网络抖动忽略,下轮再试 */ }
}
async function reloadQueue() {
  state.queue = (await api("/api/queue")).queue;
  state.qi = -1;
  paintTopbar(state.queue);
  nextStem();
}
$("btnRefreshQ").onclick = reloadQueue;
$("btnSkip").onclick = () => nextStem(true);
$("btnPrev").onclick = () => stepQueue(-1);
function nextStem(skipCurrent) {
  stepQueue(skipCurrent ? 2 : 1);
}
function stepQueue(delta) {
  const todo = state.queue.filter((o) => o.pri <= 3);
  if (!todo.length) {
    state.stem = null;
    $("annSub").textContent = "你名下的图都标完了!想加标可刷新队列帮队友接力,或去「审阅仲裁」处理分歧。";
    $("cvStem").textContent = "-";
    ctx.clearRect(0, 0, 640, 640);
    return;
  }
  state.qi = ((state.qi + delta) % todo.length + todo.length) % todo.length;
  loadStem(todo[state.qi].stem, false);
}
async function loadStem(stem, revise) {
  const seq = (state.loadSeq = (state.loadSeq || 0) + 1);   // 加载序号:连点/慢网时只认最新一次
  clearTimeout(state.msgTimer);
  $("annMsg").classList.add("hidden");                       // 换图后不残留上一张的提示
  state.stem = stem; state.reviseMode = !!revise;
  state.sel = -1; state.undoStack = []; state.loadedDraft = false;
  $("cvStem").textContent = stem + " · 图片加载中…" + (revise ? " · 回看改判" : "");
  const t = await api("/api/task/" + stem);
  if (seq !== state.loadSeq) return;                        // 已切到别的图,本次作废
  state.imgW = t.w; state.imgH = t.h;
  state.isEmpty = false; $("ckEmpty").checked = false;
  state.boxes = [];
  state.img = null;
  render();
  const img = new Image();
  img.onload = () => {
    if (seq !== state.loadSeq) return;                      // 迟到的旧图不许覆盖新图
    state.img = img;
    $("cvStem").textContent = stem + (revise ? " · 回看改判" : "");
    render();
  };
  img.onerror = () => {
    if (seq !== state.loadSeq) return;
    $("cvStem").textContent = stem + " · 图片加载失败,点「跳过」或刷新重试";
  };
  img.src = "/api/image/" + stem + ".webp";
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
    refreshTopbar();                       // 数字立刻少一张,不用刷新页面
    if (state.reviseMode) {
      // 审阅修订:提交后回到盲审面板看判定结果
      setTimeout(() => {
        document.querySelector('#nav button[data-view="review"]').click();
        openReview(state.stem);
      }, 900);
    } else {
      setTimeout(() => nextStem(), 900);
    }
  } catch (e) { annMsg(e.message); }
};

/* ---------- 进度 ---------- */
let _progTimer = null;
let _topTimer = null;
function startTopPolling() {
  stopTopPolling();
  _topTimer = setInterval(() => {
    if (document.getElementById("view-annotate").classList.contains("hidden")) { stopTopPolling(); return; }
    refreshTopbar();
  }, 30000);
}
function stopTopPolling() { if (_topTimer) { clearInterval(_topTimer); _topTimer = null; } }
function startProgressPolling() {
  stopProgressPolling();
  _progTimer = setInterval(() => {
    if (document.getElementById("view-progress").classList.contains("hidden")) { stopProgressPolling(); return; }
    loadProgress();
  }, 30000);
}
function stopProgressPolling() { if (_progTimer) { clearInterval(_progTimer); _progTimer = null; } }
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
  const f = await api("/api/arbitration?scope=final");
  $("arbCount").textContent = d.list.length;
  $("arbList").innerHTML = d.list.length
    ? d.list.map((o) => '<div class="arb-item" data-stem="' + esc(o.stem) + '"><code>' + esc(o.stem)
        + "</code><span>" + (o.cands >= 3 ? o.cands + " 份标注 · 投票中 →" : "2 份分歧 · 待第三人 →") + "</span></div>").join("")
    : '<p class="hint">没有分歧待决的图,稳!</p>';
  $("arbList").onclick = (e) => {
    const it = e.target.closest(".arb-item[data-stem]");
    if (it) openReview(it.dataset.stem);
  };
  $("finCount").textContent = f.list.length;
  $("finList").innerHTML = f.list.length
    ? f.list.map((o) => '<div class="arb-item" data-fstem="' + esc(o.stem) + '"><code>' + esc(o.stem)
        + "</code><span>已定稿" + (o.round > 1 ? " · 第 " + o.round + " 轮" : "") + " · 查看/异议 →</span></div>").join("")
    : '<p class="hint">还没有定稿的图</p>';
  $("finList").onclick = (e) => {
    const it = e.target.closest(".arb-item[data-fstem]");
    if (it) openReview(it.dataset.fstem);
  };
  state.arbOpen = d.list;
  const c = await api("/api/comments?limit=20");
  $("discCount").textContent = c.list.length + (c.list.length >= 20 ? "+" : "");
  $("discFeed").innerHTML = c.list.length
    ? c.list.map((o) => '<div class="arb-item" data-cstem="' + esc(o.stem) + '" style="flex-direction:column;align-items:flex-start;gap:2px">'
        + "<b>" + esc(o.author) + "</b>@" + esc(o.stem) + "<span>" + esc(o.text) + "</span>"
        + '<span class="hint inline">' + esc(o.created_at) + " · 点我去看这张图 →</span></div>").join("")
    : '<p class="hint">还没有讨论。打开任意一张图,在面板下方「图上讨论」发言。</p>';
  $("discFeed").onclick = (e) => {
    const it = e.target.closest(".arb-item[data-cstem]");
    if (it) openReview(it.dataset.cstem);
  };
  switchArbTab(state.arbTab || "open");
  if (state.discTimer) { clearInterval(state.discTimer); state.discTimer = null; }
  state.discTimer = setInterval(() => {
    if (document.getElementById("view-review").classList.contains("hidden")
        || state.arbTab !== "disc") { clearInterval(state.discTimer); state.discTimer = null; return; }
    loadArb();
  }, 20000);
}
function switchArbTab(t) {
  state.arbTab = t;
  $("arbList").classList.toggle("hidden", t !== "open");
  $("finList").classList.toggle("hidden", t !== "fin");
  $("discFeed").classList.toggle("hidden", t !== "disc");
  $("tabOpen").classList.toggle("btn-primary", t === "open");
  $("tabFin").classList.toggle("btn-primary", t === "fin");
  $("tabDisc").classList.toggle("btn-primary", t === "disc");
  $("arbTabHint").textContent = {
    open: "分歧图盲审投票;对定稿结果有异议就切到「已定稿」,点开一键重开盲审。",
    fin: "已定稿的图:点开查看定稿结果与真名;有异议点面板里「我有异议」一键重开盲审。",
    disc: "全组最新讨论(实名、全库可见);点任意一条直接跳到那张图接着聊。"
  }[t];
}
$("tabOpen").onclick = () => switchArbTab("open");
$("tabFin").onclick = () => switchArbTab("fin");
$("tabDisc").onclick = () => switchArbTab("disc");
function startCommentStream() {
  // SSE 实时:任何人发新评论,服务端 2 秒内推信号 → 立即重载当前面板讨论与讨论流。
  // 断线由 EventSource 自动重连;15s 轮询继续作兜底,两者叠加无害(渲染幂等)。
  if (state.es) return;
  try {
    const es = new EventSource("/api/comments/stream");
    es.onmessage = () => {
      renderRvComments(state.rvStem);
      if (state.arbTab === "disc") loadArb();
    };
    es.onerror = () => { /* 自动重连中 */ };
    state.es = es;
  } catch (e) { /* 无 EventSource 的环境由 15s 轮询兜底 */ }
}
async function renderRvComments(stem) {
  const box = $("rvComments");
  try {
    const d = await api("/api/comments?stem=" + encodeURIComponent(stem));
    if (state.rvStem !== stem) return;                      // 面板已切到别的图
    box.innerHTML = '<h2 style="margin-top:14px">图上讨论 <span class="pill">' + d.list.length + '</span>'
      + ' <span class="hint inline">实名发言,全组可见</span></h2>'
      + '<div class="arb-list">' + (d.list.length ? d.list.map((c) =>
          '<div class="arb-item" style="cursor:default;flex-direction:column;align-items:flex-start;gap:2px">'
          + "<b>" + esc(c.author) + "</b><span>" + esc(c.text) + '</span><span class="hint inline">' + esc(c.created_at) + "</span></div>").join("")
        : '<p class="hint">还没有讨论,有疑问就说两句。</p>') + "</div>"
      + '<div class="toolbar" style="margin-top:6px"><input id="cmtText" maxlength="500" style="flex:1;padding:6px 10px;border:1px solid #cbd5e1;border-radius:8px" placeholder="对这张图说点什么…(1~500 字)">'
      + '<button class="btn btn-primary" id="cmtSend">发送</button></div>';
    const draft = state.cmtDraft && state.cmtDraft[stem];
    if (draft) $("cmtText").value = draft;
    $("cmtText").oninput = () => {
      state.cmtDraft = state.cmtDraft || {};
      state.cmtDraft[stem] = $("cmtText").value;
    };
    $("cmtSend").onclick = async () => {
      const t = $("cmtText").value.trim();
      if (!t) return;
      state.cmtDraft = state.cmtDraft || {};
      delete state.cmtDraft[stem];
      try {
        await api("/api/comments", { json: { stem, text: t } });
        renderRvComments(stem);
      } catch (err) { rvMsg(err.message); }
    };
  } catch (e) { box.innerHTML = ""; }
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
  state.rvFocus = null; state.rvData = null; state.rvImg = null;
  const img = new Image();
  img.onload = () => {
    if (state.rvStem !== stem) return;                      // 面板已切到别的图
    state.rvImg = img; state.rvData = d;
    g.drawImage(img, 0, 0, 640, 640); paintCands(g, d, state.rvFocus);
  };
  state.rvStem = stem;
  img.src = "/api/image/" + stem + ".webp";
  $("rvCands").innerHTML = d.candidates.length
    ? (() => {
        const CN = (code) => (state.meta.names && state.meta.names[code]) || code;
        const boxSummary = (c) => c.is_empty ? "本图无缺陷" :
          Object.entries(c.boxes.reduce((m, b) => (m[b.code] = (m[b.code] || 0) + 1, m), {}))
            .map(([k, n]) => CN(k) + "×" + n).join(" · ");
        // 进池原因:对比最初两份(候选按提交先后排),框数/类型/位置三类说明
        let reasonHtml = "";
        if (!d.final) {
          const a = d.candidates[0], b = d.candidates[1];
          let why;
          if (a.is_empty || b.is_empty) why = "一方认为「本图无缺陷」,另一方画了框";
          else if (a.boxes.length !== b.boxes.length)
            why = "框数不同(" + a.boxes.length + " 框 vs " + b.boxes.length + " 框)";
          else {
            const sig = (c) => c.boxes.map((x) => x.code).sort().join(",");
            why = sig(a) === sig(b)
              ? "缺陷类型相同,但框的位置/大小差异过大(同码框重叠度不足 60%)"
              : "缺陷类型不同(" + boxSummary(a) + " vs " + boxSummary(b) + ")";
          }
          const stage = d.candidates.length === 2
            ? "现在:系统<b>已自动把这张图加派给第三人盲标</b>(第三人提交自己的标注,不是投票);他与任一方一致即直接定稿,无需投票。若等不及,也可在下方提前投。"
            : "现在:第三人已补标,但<b>仍凑不出过半数一致</b>(三人各有说法)→ 进入全员投票裁决。";
          reasonHtml = '<div class="hint small" style="border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;margin-bottom:10px">'
            + "<b>为什么进仲裁:</b>最初两人标注不一致 —— " + why + "。" + stage + "</div>";
        }
        const cards = d.candidates.map((c, i) => {
          const color = CAND_COLORS[i % CAND_COLORS.length];
          const isMine = c.annotator === state.me;
          return '<div class="cand-card' + (isMine ? " mine" : "") + (d.final && d.tally[c.id] ? " chosen" : "") + '">'
            + '<div class="row"><span class="anon" style="color:' + color + '">' + esc(c.anon)
            + (isMine ? "(你)" : "") + "</span><span>" + esc(boxSummary(c))
            + "</span><b>" + (d.tally[c.id] || 0) + " 票</b></div>"
            + '<div class="row"><span class="meta">' + esc(c.submitted_at)
            + (c.annotator ? " · 真名:" + esc(c.annotator) : "") + "</span>"
            + (d.final ? "" : '<button class="btn" data-vote="' + c.id + '"' +
                (d.my_vote === c.id ? " disabled" : "") + ">" + (d.my_vote === c.id ? "已投" : "投这份") + "</button>")
            + "</div></div>";
        }).join("");
        const focusBar = '<div class="toolbar" style="margin:0 0 8px"><span class="hint inline">画布只看:</span>'
          + '<button class="btn" data-focus="-1">全部</button>'
          + d.candidates.map((c, i) => '<button class="btn" data-focus="' + i + '">'
            + '<b style="color:' + CAND_COLORS[i % CAND_COLORS.length] + '">' + esc(c.anon) + "</b></button>").join("")
          + '<span class="hint inline">点某人只看他的框,标签不再互相遮挡</span></div>';
        const fixBtn = '<div class="toolbar" style="margin:0 0 8px"><button class="btn" id="btnFixHere">'
          + "三份都不全/都不对?去标注页<b>自己画一份正确的</b> →</button>"
          + '<span class="hint inline">提交后自动成为新候选参与判定;已定稿的图会自动重开盲审</span></div>';
        return focusBar + fixBtn + reasonHtml + cards
          + (d.final ? "" : '<p class="hint small">投票规则:<b>全员 4 人都能投,包括已标注的人</b>(匿名状态下凭判断选对的一份,坚持己见也是票);≥3 票且<b>严格过半</b>才定稿 —— 2 个人定不了任何图;<b>平票不自动定稿</b>:群里讨论后,再点另一份「投这份」即可覆盖你原来的票;定稿后仍可「我有异议」重开。</p>');
      })()
    : '<p class="hint">这张图还没有任何有效标注</p>';
  $("rvCands").onclick = async (e) => {
    if (e.target.closest("#btnFixHere")) {
      document.querySelector('#nav button[data-view="annotate"]').click();
      setTimeout(() => loadStem(stem, true), 50);
      return;
    }
    const f = e.target.closest("[data-focus]");
    if (f) {
      state.rvFocus = parseInt(f.dataset.focus, 10);
      document.querySelectorAll('#rvCands [data-focus]').forEach((x) => {
        x.style.opacity = parseInt(x.dataset.focus, 10) === state.rvFocus ? "1" : "0.55";
      });
      redrawRv();
      return;
    }
    const b = e.target.closest("[data-vote]");
    if (!b) return;
    try {
      await api("/api/vote", { json: { stem, chosen_id: parseInt(b.dataset.vote, 10) } });
      await loadArb();                                   // 左侧列表与计数即时刷新
      const rem = (state.arbOpen || []).map((o) => o.stem);
      if (!rem.includes(stem)) {
        if (rem.length) {
          openReview(rem[0]);                            // 这张已定稿 → 自动跳下一张(投票中优先)
        } else {
          state.rvStem = null;
          $("rvTitle").textContent = "盲审面板";
          const g = $("rv").getContext("2d");
          g.clearRect(0, 0, 640, 640); g.fillStyle = "#0b1220"; g.fillRect(0, 0, 640, 640);
          $("rvCands").innerHTML = '<p class="hint">全部待决已清空,干得漂亮!</p>';
          $("rvComments").innerHTML = "";
          $("rvDisputes").innerHTML = "";
        }
      } else {
        openReview(stem);                                // 平票未决 → 留在本图看最新票数
      }
    } catch (err) { rvMsg(err.message); }
  };
  if (state.cmtTimer) { clearInterval(state.cmtTimer); state.cmtTimer = null; }
  startCommentStream();
  renderRvComments(stem);
  state.cmtTimer = setInterval(() => {
    if (document.getElementById("view-review").classList.contains("hidden")) {
      clearInterval(state.cmtTimer); state.cmtTimer = null; return;
    }
    const el = document.getElementById("cmtText");
    if (el && document.activeElement === el) return;        // 正在打字,不打扰
    renderRvComments(state.rvStem);
  }, 15000);
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
function paintCands(g, d, focus) {
  const CN = (code) => (state.meta.names && state.meta.names[code]) || code;
  d.candidates.forEach((c, i) => {
    const color = CAND_COLORS[i % CAND_COLORS.length];
    const dim = focus !== undefined && focus !== null && focus >= 0 && focus !== i;
    g.globalAlpha = dim ? 0.15 : 1;
    (c.boxes || []).forEach((b) => drawRect(g, b, color, dim ? 2 : 3,
      dim ? undefined : c.anon + "·" + CN(b.code), dim ? 0 : i));
    g.globalAlpha = 1;
  });
}
function redrawRv() {
  const d = state.rvData;
  if (!d || state.rvStem !== d.stem) return;
  const g = $("rv").getContext("2d");
  g.clearRect(0, 0, 640, 640);
  g.fillStyle = "#0b1220"; g.fillRect(0, 0, 640, 640);
  if (state.rvImg) g.drawImage(state.rvImg, 0, 0, 640, 640);
  paintCands(g, d, state.rvFocus);
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
    "<li><b>画框</b> —— 在缺陷上按住拖拽;点框选中后可拖动/四角缩放/右键或 Delete 删除;<b>小缺陷被大框盖住时,按住 <kbd>Alt</kbd>(或 <kbd>Shift</kbd>)拖拽即可在框内强制新建</b>;</li>" +
    "<li><b>选类别</b> —— 右侧点按钮或按快捷键(<kbd>1</kbd>~<kbd>9</kbd>,<kbd>0</kbd>,<kbd>Q</kbd>,<kbd>W</kbd>);选中框后按类别键可改它的类;</li>" +
    "<li><b>拿不准</b> —— 看参照样例和悬停判定要点;纯无缺陷的图勾「本图无缺陷」或按 <kbd>N</kbd>;</li>" +
    "<li><b>提交</b> —— <kbd>Enter</kbd> 或点提交;之后图进盲审流程,分歧自动加第三人。</li></ol>";
  $("helpCoop").innerHTML =
    '<table class="help-table"><tr><th style="width:130px">机制</th><th>规则</th></tr>' +
    "<tr><td>分配</td><td>每张图恰好 2 人打底(随机、每人约 255 张);不锁图,想加标随时加,进度板全透明。</td></tr>" +
    "<tr><td>留痕</td><td>每次提交/改判/撤销都是新记录,只追加不改写;可回放、可算每人一致率。</td></tr>" +
    "<tr><td>分歧</td><td>两份不一致 → 自动加派第三人盲标;框数相同且同码框 IoU≥0.6 视为一致。</td></tr>" +
    "<tr><td>定稿</td><td>2 份一致自动定稿;不一致 → 自动加第三人盲标(2/3 一致即定稿);仍无多数 → 全员盲投,≥3 票且严格过半才定稿;平票不自动定稿,群里协商后改票即可(再点另一份「投这份」覆盖原票)。</td></tr>" +
    "<tr><td>盲审</td><td>定稿前 everyone 匿名(甲乙丙丁),投完才解锁真名 —— 防碍于情面。</td></tr>" +
    "<tr><td>异议重审</td><td>对定稿有异议,一键「我有异议」+ 一句话理由,自动重开盲投(旧票作废)。</td></tr>" +
    "<tr><td>封板</td><td>任意一人发起,3/4 同意即锁定;训练只认封板后导出的 VOC XML。</td></tr>" +
    '<tr><td>导出</td><td>任何人随时可导(留痕 csv / 定稿 csv / VOC XML 包),服务端实时快照,永不"不同步"。</td></tr></table>';
  const m = state.meta;
  $("helpCodes").innerHTML = "<table class=\"help-table\"><tr><th>代码</th><th>中文名</th><th>全库规模(测试集)</th><th>判定要点</th><th>依据</th></tr>" +
    m.codes.map((c) => "<tr><td><b>" + c + "</b></td><td>" + esc(m.names[c] || "") +
      (m.rare.includes(c) ? ' <span class="chip rare">稀有</span>' : "") + "</td><td>" +
      esc(CODE_STATS[c] || "") + "</td><td>" + esc(CODE_TIPS[c]) + "</td><td>" +
      esc(CODE_BASIS[c] || "") + "</td></tr>").join("") + "</table>" +
    '<p class="hint small">中文名已由队友逐类看图 + 产线目录名确认(2026-09-17);若数据方官方对照有出入,以官方为准,届时只改一张表。</p>';
  const refs = $("helpRefs");
  refs.innerHTML = "";
  m.codes.forEach((c) => {
    ((state.refs || {})[c] || []).slice(0, 8).forEach((r) => {
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
      img.src = r.url || ("/static/" + r.img);
      cvh.onclick = () => bigLightbox(img.src, r.boxes || []);
      item.appendChild(cvh);
      item.insertAdjacentHTML("beforeend", refLegendHtml(r.boxes));
      const cap = document.createElement("div");
      cap.className = "cap"; cap.textContent = c + " · " + r.stem;
      item.appendChild(cap);
      refs.appendChild(item);
    });
  });
  $("helpFaq").innerHTML =
    '<div class="faq-item"><b>标错了怎么办?</b> 定稿前:在「回看改判」里重新提交即可(留痕,不改历史);整笔撤销找组长在导出的留痕表里看,或重新提交一份正确的——投票只看最新有效标注。</div>' +
    '<div class="faq-item"><b>两人标的框差几个像素算分歧吗?</b> 不算。框数相同、同码框位置重叠足够大(IoU≥0.6)即视为一致,自动定稿。</div>' +
    '<div class="faq-item"><b>几个缺陷挤在一起,大框里面画不了小框?</b> 按住 <kbd>Alt</kbd>(或 <kbd>Shift</kbd>)再拖拽,会无视已有框、直接新建;建议先小后大或配合该快捷键。松开前拖出画布也没关系,坐标会自动收敛到图内。</div>' +
    '<div class="faq-item"><b>平票怎么办?</b> 平票不自动定稿——数据准确性优先。群里讨论后,在盲审面板再点另一份「投这份」即可改票(覆盖原票),≥3 票且严格过半即定稿;对已定稿结果不满,随时「我有异议」重开。</div>' +
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
  { t: "分歧怎么办", b: "两人不一致 → 自动加派第三人盲审 → 僵局全员投票、严格过半定稿;平票不自动定稿,群里协商改票。<b>定稿前所有人都匿名(甲乙丙丁)</b>,放平心态,你的判断有价值。有异议随时重审,无理由才不受理。" },
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
  const lg = document.createElement("div");
  lg.style.cssText = "background:#fff;border-radius:8px;padding:6px 12px;margin-top:8px";
  lg.innerHTML = refLegendHtml(boxes) || '<span class="hint">本图无缺陷框</span>';
  lb.appendChild(lg);
  lb.classList.remove("hidden");
  lb.onclick = () => lb.classList.add("hidden");
}

/* ---------- go ---------- */
tryBoot();
