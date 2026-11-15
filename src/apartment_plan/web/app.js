import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const canvas = $("plan");
const ctx = canvas.getContext("2d");

const COLORS = { high: "#1f8a3b", medium: "#e08a00", low: "#d43a2a", user: "#1f5fd0" };
const OPENING_COLORS = { door: "#8a4b12", window: "#0a8fb8", opening: "#c23ac2" };
const HINTS = {
  select: "Click a line to select it · drag an endpoint to move it · drag empty space to pan · scroll to zoom",
  wall: "Click the start, then the end of the wall · Shift keeps it horizontal/vertical · Esc cancels",
  door: "Click both sides of the door opening",
  window: "Click both ends of the window",
  calibrate: "Click the two ends of a wall whose real length you know",
};

const state = {
  project: null,
  image: null,
  view: { k: 1, tx: 0, ty: 0 },
  tool: "select",
  selected: null, // { id, group }
  pick: [], // calibration points (image px)
  draft: null, // first point of a segment being drawn
  mouse: null, // image px
  drag: null,
  shift: false,
  layers: { scan: true, walls: true, openings: true, rooms: true, texts: false },
};

/* ------------------------------------------------------------------ API */

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.className = "toast"), isError ? 5000 : 2500);
}

async function api(method, url, body) {
  try {
    const res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json();
    if (!res.ok) {
      toast(data.error || `Request failed (${res.status})`, true);
      return null;
    }
    setProject(data);
    return data;
  } catch (err) {
    toast("Cannot reach the local review server: " + err.message, true);
    return null;
  }
}

function setProject(data) {
  state.project = data;
  if (state.selected && !findEntity(state.selected.id)) state.selected = null;
  renderPanels();
  draw();
  refreshScene();
}

function active(group) {
  return (state.project?.[group] || []).filter((e) => !e.removed);
}

function findEntity(id) {
  for (const group of ["walls", "openings", "rooms"]) {
    const e = active(group).find((x) => x.id === id);
    if (e) return { entity: e, group };
  }
  return null;
}

/* ---------------------------------------------------------------- Panels */

function fmtLen(e) {
  if (e.length_m != null) return `${e.length_m.toFixed(3)} m`;
  return `${e.length_px.toFixed(0)} px — real length unknown until the scale is set`;
}

function renderPanels() {
  const p = state.project;
  $("project-name").textContent = `${p.id} · ${active("walls").length} walls · ${active("openings").length} openings · ${active("rooms").length} rooms`;

  const badge = $("scale-badge");
  const note = $("scale-note");
  if (p.scale_state === "calibrated") {
    badge.textContent = "✔ Calibrated — real scale";
    badge.className = "badge ok";
    note.className = "scale-note ok";
    note.textContent = p.calibration.note;
  } else if (p.scale_state === "PROVISIONAL") {
    badge.textContent = "PROVISIONAL scale — not verified";
    badge.className = "badge prov";
    note.className = "scale-note prov";
    note.textContent = p.calibration.note;
  } else {
    badge.textContent = "UNCALIBRATED — not real scale";
    badge.className = "badge warn";
    note.className = "scale-note warn";
    note.textContent =
      "This is an automatic draft in scan pixels. It has not been measured: check the trace, then enter one known wall length.";
  }

  const warnings = $("warnings");
  warnings.replaceChildren(
    ...(p.source.warnings || []).map((w) => Object.assign(document.createElement("li"), { textContent: w }))
  );

  const exportsEl = $("exports");
  exportsEl.replaceChildren(
    ...p.exports.map((e) =>
      Object.assign(document.createElement("a"), { href: e.url, textContent: "Download " + e.name })
    )
  );
  if (p.scale_state !== "calibrated") {
    exportsEl.append(
      Object.assign(document.createElement("p"), {
        className: "muted",
        textContent:
          p.scale_state === "PROVISIONAL"
            ? "Files are in millimetres from a printed dimension and are marked PROVISIONAL."
            : "Files are in pixel units and marked UNCALIBRATED. Set the scale to export real millimetres.",
      })
    );
  }

  const rooms = active("rooms");
  const list = $("rooms-list");
  if (rooms.length) {
    const rows = rooms
      .map(
        (r) =>
          `<tr><td>${escapeHtml(r.label || "room")}</td><td>${
            r.area_m2 != null ? "≈ " + r.area_m2.toFixed(2) + " m²" : "area unknown (no scale)"
          }</td></tr>`
      )
      .join("");
    list.innerHTML = `<p class="muted">Rooms (inside wall faces; names are OCR suggestions):</p><table>${rows}</table>`;
  } else {
    list.innerHTML = `<p class="muted">No enclosed rooms yet — close gaps, then “Recompute rooms”.</p>`;
  }

  const dims = active("texts").filter((t) => t.kind === "dimension");
  const hints = $("dimension-hints");
  hints.replaceChildren();
  if (dims.length) {
    hints.append("Numbers OCR read on the plan (hints only, check against the scan): ");
    const seen = new Set();
    for (const d of dims) {
      if (seen.has(d.text)) continue;
      seen.add(d.text);
      const b = Object.assign(document.createElement("button"), {
        type: "button",
        className: "secondary",
        textContent: d.text,
        title: "Use as a printed length in cm",
      });
      b.onclick = () => {
        $("cal-length").value = d.text.replace(",", ".");
        $("cal-unit").value = "cm";
        document.querySelector('input[name="cal-method"][value="printed"]').checked = true;
      };
      hints.append(b);
    }
  }

  $("wall-height").value = (p.wall_height_mm / 1000).toFixed(2);
  renderSelection();
  renderPick();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function renderSelection() {
  const box = $("selection");
  const sel = state.selected && findEntity(state.selected.id);
  $("btn-delete").disabled = !sel;
  $("btn-use-selected").disabled = !(sel && sel.group !== "rooms");
  if (!sel) {
    box.className = "selection muted";
    box.textContent = "Nothing selected.";
    return;
  }
  box.className = "selection";
  const e = sel.entity;
  if (sel.group === "walls") {
    const thick =
      e.thickness_px != null
        ? state.project.calibration.scale_mm_per_px
          ? `≈ ${((e.thickness_px * state.project.calibration.scale_mm_per_px) / 10).toFixed(0)} cm (estimate from scan)`
          : `${e.thickness_px.toFixed(0)} px on the scan`
        : "not set";
    box.innerHTML = `<b>Wall</b> · ${fmtLen(e)}<br>Thickness: ${thick}<br>Source: ${
      e.source === "user" ? "edited by you" : "automatic, confidence " + e.confidence
    }`;
  } else if (sel.group === "openings") {
    box.innerHTML = `<b>${escapeHtml(e.entity_type)}</b> · ${fmtLen(e)}<div class="row">Mark as:
      <button type="button" class="secondary" data-kind="door">Door</button>
      <button type="button" class="secondary" data-kind="window">Window</button></div>`;
    box.querySelectorAll("button[data-kind]").forEach((b) => {
      b.onclick = () => api("PATCH", `/api/entities/${e.id}`, { kind: b.dataset.kind });
    });
  } else {
    box.innerHTML = `<b>Room</b> · ${
      e.area_m2 != null ? "≈ " + e.area_m2.toFixed(2) + " m²" : "area unknown (no scale)"
    }<div class="row"><input type="text" id="room-label" value="${escapeHtml(e.label || "")}" placeholder="room name" aria-label="Room name" />
      <button type="button" class="secondary" id="room-save">Save name</button></div>`;
    $("room-save").onclick = () => api("PATCH", `/api/entities/${e.id}`, { label: $("room-label").value });
  }
}

function renderPick() {
  const info = $("pick-info");
  if (state.pick.length === 2) {
    const px = Math.hypot(state.pick[1].x - state.pick[0].x, state.pick[1].y - state.pick[0].y);
    info.textContent = `Segment picked: ${px.toFixed(1)} px. Enter its real length and press “Set scale”.`;
  } else if (state.pick.length === 1) {
    info.textContent = "First end set — click the other end.";
  } else {
    info.textContent = "No segment picked.";
  }
}

/* ------------------------------------------------------------- 2D canvas */

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  draw();
}

function fitView() {
  const p = state.project;
  if (!p) return;
  const rect = canvas.getBoundingClientRect();
  const b = p.source.plan_bbox || [0, 0, p.source.image_width, p.source.image_height];
  const pad = 0.06 * Math.max(b[2] - b[0], b[3] - b[1]);
  const w = b[2] - b[0] + 2 * pad;
  const h = b[3] - b[1] + 2 * pad;
  const k = Math.min(rect.width / w, rect.height / h);
  state.view = {
    k,
    tx: (rect.width - w * k) / 2 - (b[0] - pad) * k,
    ty: (rect.height - h * k) / 2 - (b[1] - pad) * k,
  };
  draw();
}

const toScreen = (p) => ({ x: p.x * state.view.k + state.view.tx, y: p.y * state.view.k + state.view.ty });
const toImage = (s) => ({ x: (s.x - state.view.tx) / state.view.k, y: (s.y - state.view.ty) / state.view.k });

function eventPos(evt) {
  const rect = canvas.getBoundingClientRect();
  return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
}

function line(a, b) {
  const s = toScreen(a);
  const e = toScreen(b);
  ctx.beginPath();
  ctx.moveTo(s.x, s.y);
  ctx.lineTo(e.x, e.y);
  ctx.stroke();
}

function dot(p, r, fill, stroke) {
  const s = toScreen(p);
  ctx.beginPath();
  ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}

function draw() {
  const p = state.project;
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!p) return;
  const { k, tx, ty } = state.view;
  const L = state.layers;

  if (L.scan && state.image?.complete && state.image.naturalWidth) {
    ctx.globalAlpha = 0.9;
    ctx.drawImage(state.image, tx, ty, state.image.naturalWidth * k, state.image.naturalHeight * k);
    ctx.globalAlpha = 1;
  }

  if (L.rooms) {
    for (const room of active("rooms")) {
      if (room.points.length < 3) continue;
      ctx.beginPath();
      room.points.forEach((pt, i) => {
        const s = toScreen(pt);
        if (i === 0) ctx.moveTo(s.x, s.y);
        else ctx.lineTo(s.x, s.y);
      });
      ctx.closePath();
      const sel = state.selected?.id === room.id;
      ctx.fillStyle = sel ? "rgba(31,95,208,0.22)" : "rgba(40,160,110,0.14)";
      ctx.fill();
      ctx.strokeStyle = sel ? "#1f5fd0" : "rgba(30,130,90,0.7)";
      ctx.lineWidth = sel ? 2 : 1;
      ctx.stroke();
      const c = toScreen(centroid(room.points));
      ctx.fillStyle = "#124a37";
      ctx.font = "600 12px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(room.label || "room", c.x, c.y + 26);
      if (room.area_m2 != null) ctx.fillText(`≈ ${room.area_m2.toFixed(2)} m²`, c.x, c.y + 41);
    }
  }

  if (L.walls) {
    for (const wall of active("walls")) {
      const color = COLORS[wall.confidence] || COLORS.medium;
      if (wall.thickness_px) {
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.22;
        ctx.lineWidth = Math.max(wall.thickness_px * k, 1);
        ctx.lineCap = "butt";
        line(wall.start, wall.end);
        ctx.globalAlpha = 1;
      }
      const sel = state.selected?.id === wall.id;
      ctx.strokeStyle = sel ? "#111" : color;
      ctx.lineWidth = sel ? 3.5 : 2.2;
      ctx.lineCap = "round";
      line(wall.start, wall.end);
      dot(wall.start, 2.6, color);
      dot(wall.end, 2.6, color);
    }
  }

  if (L.openings) {
    for (const o of active("openings")) {
      const sel = state.selected?.id === o.id;
      ctx.strokeStyle = sel ? "#111" : OPENING_COLORS[o.entity_type] || OPENING_COLORS.opening;
      ctx.lineWidth = sel ? 5 : 4;
      ctx.setLineDash(o.entity_type === "opening" ? [6, 4] : []);
      ctx.lineCap = "butt";
      line(o.start, o.end);
      ctx.setLineDash([]);
      const m = toScreen({ x: (o.start.x + o.end.x) / 2, y: (o.start.y + o.end.y) / 2 });
      ctx.fillStyle = ctx.strokeStyle;
      ctx.font = "11px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(o.entity_type === "opening" ? "opening?" : o.entity_type, m.x, m.y - 6);
    }
  }

  if (L.texts) {
    ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "left";
    for (const t of active("texts")) {
      const s = toScreen(t.position);
      ctx.strokeStyle = t.kind === "dimension" ? "#b06a00" : "#7a4bb5";
      ctx.lineWidth = 1;
      ctx.strokeRect(s.x, s.y, t.width * k, t.height * k);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fillText(t.text, s.x, s.y - 2);
    }
  }

  // Stored calibration segment
  const cal = p.calibration;
  if (cal.calibrated && cal.pixel_start && cal.pixel_end) {
    ctx.strokeStyle = p.scale_state === "calibrated" ? "#1f6b3a" : "#a15a00";
    ctx.lineWidth = 2;
    ctx.setLineDash([10, 5]);
    line(cal.pixel_start, cal.pixel_end);
    ctx.setLineDash([]);
    const m = toScreen({ x: (cal.pixel_start.x + cal.pixel_end.x) / 2, y: (cal.pixel_start.y + cal.pixel_end.y) / 2 });
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = "600 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(`${(cal.measured_mm / 1000).toFixed(3)} m (${cal.method})`, m.x, m.y - 8);
  }

  // Selected segment handles
  const sel = state.selected && findEntity(state.selected.id);
  if (sel && sel.group !== "rooms") {
    dot(sel.entity.start, 6, "#fff", "#111");
    dot(sel.entity.end, 6, "#fff", "#111");
  }

  // Calibration pick
  if (state.pick.length) {
    ctx.strokeStyle = "#7b1fa2";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    if (state.pick.length === 2) line(state.pick[0], state.pick[1]);
    else if (state.mouse && state.tool === "calibrate") line(state.pick[0], state.mouse);
    ctx.setLineDash([]);
    state.pick.forEach((pt) => dot(pt, 5, "#7b1fa2", "#fff"));
  }

  // Segment being drawn
  if (state.draft && state.mouse) {
    ctx.strokeStyle = state.tool === "wall" ? COLORS.user : OPENING_COLORS[state.tool];
    ctx.lineWidth = 2.5;
    line(state.draft, state.mouse);
    dot(state.draft, 4, ctx.strokeStyle);
  }
}

function centroid(points) {
  // Area centroid; falls back to the vertex mean for degenerate shapes
  let a = 0, cx = 0, cy = 0;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const f = points[j].x * points[i].y - points[i].x * points[j].y;
    a += f;
    cx += (points[j].x + points[i].x) * f;
    cy += (points[j].y + points[i].y) * f;
  }
  if (Math.abs(a) < 1e-6) {
    const n = points.length;
    return { x: points.reduce((s, p) => s + p.x, 0) / n, y: points.reduce((s, p) => s + p.y, 0) / n };
  }
  return { x: cx / (3 * a), y: cy / (3 * a) };
}

function distPointSeg(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy || 1;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

function pointInPolygon(p, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    if (pts[i].y > p.y !== pts[j].y > p.y && p.x < ((pts[j].x - pts[i].x) * (p.y - pts[i].y)) / (pts[j].y - pts[i].y) + pts[i].x)
      inside = !inside;
  }
  return inside;
}

/** Snap an image-space point to nearby wall/opening endpoints; Shift keeps it axis-aligned to `anchor`. */
function snap(p, anchor, ignoreId) {
  const tol = 9 / state.view.k;
  let best = null;
  let bestD = tol;
  for (const group of ["walls", "openings"]) {
    for (const e of active(group)) {
      if (e.id === ignoreId) continue;
      for (const q of [e.start, e.end]) {
        const d = Math.hypot(q.x - p.x, q.y - p.y);
        if (d < bestD) {
          bestD = d;
          best = { x: q.x, y: q.y };
        }
      }
    }
  }
  let out = best || p;
  if (state.shift && anchor) {
    out = Math.abs(out.x - anchor.x) >= Math.abs(out.y - anchor.y) ? { x: out.x, y: anchor.y } : { x: anchor.x, y: out.y };
  }
  return out;
}

function hitTest(p) {
  const tol = 7 / state.view.k;
  let best = null;
  let bestD = tol;
  for (const group of ["openings", "walls"]) {
    if (!state.layers[group]) continue;
    for (const e of active(group)) {
      const d = distPointSeg(p, e.start, e.end);
      if (d < bestD) {
        bestD = d;
        best = { id: e.id, group };
      }
    }
  }
  if (best) return best;
  if (state.layers.rooms) {
    for (const r of active("rooms")) if (pointInPolygon(p, r.points)) return { id: r.id, group: "rooms" };
  }
  return null;
}

function setTool(tool) {
  state.tool = tool;
  state.draft = null;
  document.querySelectorAll("#tools button").forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
  canvas.classList.toggle("tool-select", tool === "select");
  $("hint").textContent = HINTS[tool];
  draw();
}

canvas.addEventListener("pointerdown", (evt) => {
  if (!state.project) return;
  canvas.focus();
  canvas.setPointerCapture(evt.pointerId);
  const s = eventPos(evt);
  const p = toImage(s);
  state.drag = { kind: "pending", startScreen: s, startView: { ...state.view }, moved: false };

  if (state.tool === "select" && evt.button === 0) {
    const sel = state.selected && findEntity(state.selected.id);
    if (sel && sel.group !== "rooms") {
      const r = 10 / state.view.k;
      for (const end of ["start", "end"]) {
        if (Math.hypot(sel.entity[end].x - p.x, sel.entity[end].y - p.y) < r) {
          state.drag = { kind: "endpoint", end, entity: sel.entity, original: { ...sel.entity[end] }, moved: false };
          return;
        }
      }
    }
  }
});

canvas.addEventListener("pointermove", (evt) => {
  const s = eventPos(evt);
  state.shift = evt.shiftKey;
  const raw = toImage(s);
  const d = state.drag;
  if (d?.kind === "endpoint") {
    const other = d.end === "start" ? d.entity.end : d.entity.start;
    const q = snap(raw, other, d.entity.id);
    d.entity[d.end] = q;
    d.moved = true;
    draw();
    return;
  }
  if (d?.kind === "pending") {
    const dx = s.x - d.startScreen.x;
    const dy = s.y - d.startScreen.y;
    if (d.moved || Math.hypot(dx, dy) > 4) {
      d.moved = true;
      canvas.classList.add("panning");
      state.view.tx = d.startView.tx + dx;
      state.view.ty = d.startView.ty + dy;
    }
  }
  state.mouse = snap(raw, state.draft || (state.pick.length === 1 ? state.pick[0] : null));
  draw();
});

canvas.addEventListener("pointerup", async (evt) => {
  const d = state.drag;
  state.drag = null;
  canvas.classList.remove("panning");
  if (!d || !state.project) return;

  if (d.kind === "endpoint") {
    if (d.moved) {
      const ok = await api("PATCH", `/api/entities/${d.entity.id}`, { [d.end]: d.entity[d.end] });
      if (!ok) {
        d.entity[d.end] = d.original;
        draw();
      }
    }
    return;
  }
  if (d.moved || evt.button !== 0) return; // it was a pan

  state.shift = evt.shiftKey;
  const raw = toImage(eventPos(evt));

  if (state.tool === "select") {
    state.selected = hitTest(raw);
    renderSelection();
    draw();
    return;
  }

  if (state.tool === "calibrate") {
    if (state.pick.length >= 2) state.pick = [];
    state.pick.push(snap(raw, state.pick[0]));
    renderPick();
    draw();
    return;
  }

  // wall / door / window
  const p = snap(raw, state.draft);
  if (!state.draft) {
    state.draft = p;
    draw();
    return;
  }
  const start = state.draft;
  state.draft = null;
  await api("POST", "/api/entities", { kind: state.tool, start, end: p });
});

canvas.addEventListener(
  "wheel",
  (evt) => {
    evt.preventDefault();
    const s = eventPos(evt);
    const before = toImage(s);
    const factor = Math.exp(-evt.deltaY * 0.0015);
    state.view.k = Math.min(12, Math.max(0.05, state.view.k * factor));
    state.view.tx = s.x - before.x * state.view.k;
    state.view.ty = s.y - before.y * state.view.k;
    draw();
  },
  { passive: false }
);

async function deleteSelected() {
  if (!state.selected) return;
  const id = state.selected.id;
  state.selected = null;
  await api("DELETE", `/api/entities/${id}`);
}

window.addEventListener("keydown", (evt) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  if (evt.key === "Delete" || evt.key === "Backspace") {
    evt.preventDefault();
    deleteSelected();
  } else if (evt.key === "Escape") {
    state.draft = null;
    if (state.tool === "calibrate") state.pick = [];
    renderPick();
    draw();
  } else {
    const tool = { v: "select", w: "wall", d: "door", n: "window", c: "calibrate" }[evt.key.toLowerCase()];
    if (tool && !evt.metaKey && !evt.ctrlKey) setTool(tool);
  }
});

document.querySelectorAll("#tools button").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
document.querySelectorAll("input[data-layer]").forEach((box) => {
  box.onchange = () => {
    state.layers[box.dataset.layer] = box.checked;
    draw();
  };
});

$("btn-delete").onclick = deleteSelected;
$("btn-undo").onclick = () => api("POST", "/api/undo-remove");
$("btn-fit").onclick = fitView;
$("btn-remove-low").onclick = async () => {
  const before = active("walls").length;
  if (await api("POST", "/api/remove-low-confidence"))
    toast(`Removed ${before - active("walls").length} uncertain walls. “Undo delete” brings them back.`);
};
$("btn-rooms").onclick = async () => {
  if (await api("POST", "/api/rooms/recompute")) toast(`${active("rooms").length} enclosed room(s) found.`);
};

$("btn-use-selected").onclick = () => {
  const sel = state.selected && findEntity(state.selected.id);
  if (!sel || sel.group === "rooms") return;
  state.pick = [{ ...sel.entity.start }, { ...sel.entity.end }];
  renderPick();
  draw();
};

$("btn-calibrate").onclick = async () => {
  if (state.pick.length !== 2) {
    toast("Pick the two ends of a wall first (Measure tool).", true);
    return;
  }
  const length = Number($("cal-length").value);
  if (!(length > 0) || !Number.isFinite(length)) {
    toast("Enter the real length as a positive number.", true);
    return;
  }
  const method = document.querySelector('input[name="cal-method"]:checked').value;
  const ok = await api("POST", "/api/calibrate", {
    length,
    unit: $("cal-unit").value,
    method,
    start: state.pick[0],
    end: state.pick[1],
    segment_id: state.selected?.group === "walls" ? state.selected.id : null,
  });
  if (ok) {
    state.pick = [];
    renderPick();
    draw();
    toast(method === "measured" ? "Scale set from your measurement. Exports are now in millimetres." : "Provisional scale set. Measure a real wall to confirm it.");
  }
};

$("btn-clear-cal").onclick = async () => {
  if (await api("POST", "/api/calibration/clear")) toast("Scale cleared — the plan is uncalibrated again.");
};

$("wall-height").addEventListener("change", () => {
  const metres = Number($("wall-height").value);
  if (!(metres > 0)) {
    toast("Wall height must be a positive number of metres.", true);
    return;
  }
  api("POST", "/api/wall-height", { wall_height_mm: metres * 1000 });
});

/* ------------------------------------------------------------ 3D preview */

const view3d = {};

function init3d() {
  const host = $("view3d");
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (err) {
    host.textContent = "3D preview needs WebGL, which this browser did not provide.";
    return;
  }
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(host.clientWidth, host.clientHeight);
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xdfe5e1);
  const camera = new THREE.PerspectiveCamera(45, host.clientWidth / host.clientHeight, 0.05, 2000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.maxPolarAngle = Math.PI / 2.05;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f8c, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(6, 12, 4);
  scene.add(sun);

  const root = new THREE.Group();
  scene.add(root);
  Object.assign(view3d, { renderer, scene, camera, controls, root, host, framed: false });

  new ResizeObserver(() => {
    const w = host.clientWidth;
    const h = host.clientHeight;
    if (!w || !h) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }).observe(host);

  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(scene, camera);
  });
}

async function refreshScene() {
  if (!view3d.root) return;
  let data;
  try {
    data = await (await fetch("/api/scene")).json();
  } catch {
    return;
  }
  $("scene-note").textContent = data.calibrated
    ? `Illustrative preview in metres (${data.scale_state}). Wall thickness is an estimate from the scan; openings are markers, not cut-outs.`
    : "UNCALIBRATED: proportions only. Sizes and wall height are not to scale until you set the scale.";

  const root = view3d.root;
  root.traverse((o) => {
    o.geometry?.dispose();
    o.material?.dispose?.();
  });
  root.clear();

  const H = data.wall_height;
  const wallMat = new THREE.MeshStandardMaterial({ color: data.calibrated ? 0xe6dcc8 : 0xd9b99a, roughness: 0.9 });
  const box = new THREE.Box3();

  for (const w of data.walls) {
    const dx = w.b[0] - w.a[0];
    const dy = w.b[1] - w.a[1];
    const len = Math.hypot(dx, dy);
    if (len < 1e-6) continue;
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(len + w.thickness, H, w.thickness), wallMat);
    mesh.position.set((w.a[0] + w.b[0]) / 2, H / 2, -(w.a[1] + w.b[1]) / 2);
    mesh.rotation.y = Math.atan2(dy, dx);
    root.add(mesh);
    box.expandByObject(mesh);
  }

  const floorMat = new THREE.MeshStandardMaterial({ color: 0xb9a583, roughness: 1, side: THREE.DoubleSide });
  for (const r of data.rooms) {
    if (r.points.length < 3) continue;
    const shape = new THREE.Shape(r.points.map((p) => new THREE.Vector2(p[0], p[1])));
    const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), floorMat);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.005;
    root.add(mesh);
  }

  for (const o of data.openings) {
    const dx = o.b[0] - o.a[0];
    const dy = o.b[1] - o.a[1];
    const len = Math.hypot(dx, dy);
    if (len < 1e-6) continue;
    const isWindow = o.kind === "window";
    const h = isWindow ? H * 0.45 : H * 0.76;
    const y = isWindow ? H * 0.33 + h / 2 : h / 2;
    const mat = new THREE.MeshStandardMaterial({
      color: isWindow ? 0x7fc8e8 : o.kind === "door" ? 0x8a5a2b : 0xc23ac2,
      transparent: true,
      opacity: isWindow ? 0.55 : 0.75,
    });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(len, h, H * 0.03), mat);
    mesh.position.set((o.a[0] + o.b[0]) / 2, y, -(o.a[1] + o.b[1]) / 2);
    mesh.rotation.y = Math.atan2(dy, dx);
    root.add(mesh);
  }

  if (!box.isEmpty()) {
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.z, 1);
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(span * 3, span * 3),
      new THREE.MeshStandardMaterial({ color: 0xcfd6d1, roughness: 1 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(center.x, -0.01, center.z);
    root.add(ground);
    if (!view3d.framed || view3d.framedState !== data.scale_state) {
      view3d.controls.target.set(center.x, 0, center.z);
      view3d.camera.position.set(center.x + span * 0.25, span * 1.05, center.z + span * 0.95);
      view3d.camera.near = span / 500;
      view3d.camera.far = span * 50;
      view3d.camera.updateProjectionMatrix();
      view3d.framed = true;
      view3d.framedState = data.scale_state;
    }
  }
}

/* ------------------------------------------------------------------ Boot */

async function boot() {
  init3d();
  setTool("select");
  new ResizeObserver(resizeCanvas).observe($("canvas-wrap"));
  const data = await api("GET", "/api/project");
  if (!data) {
    $("scale-badge").textContent = "No project — run: apartment-plan process";
    return;
  }
  state.image = new Image();
  state.image.onload = () => {
    resizeCanvas();
    fitView();
  };
  state.image.src = "/api/source.png?t=" + Date.now();
}

boot();
