import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const canvas = document.getElementById("plan");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const warningsEl = document.getElementById("warnings");
const selectionInfo = document.getElementById("selection-info");
const sceneNote = document.getElementById("scene-note");
const measuredInput = document.getElementById("measured-mm");
const wallHeightInput = document.getElementById("wall-height");

let project = null;
let sourceImage = new Image();
let mode = "select"; // select | draw
let selectedWallId = null;
let pickPoints = [];
let drawPoints = [];
let scale = 1;

const view3d = {
  renderer: null,
  scene: null,
  camera: null,
  controls: null,
  root: null,
};

async function loadProject() {
  const res = await fetch("/api/project");
  if (!res.ok) {
    statusEl.textContent = "No project found. Run: apartment-plan process";
    statusEl.className = "status warn";
    return;
  }
  project = await res.json();
  wallHeightInput.value = project.wall_height_mm || 2700;
  updateStatus();
  warningsEl.innerHTML = "";
  for (const w of project.source.warnings || []) {
    const li = document.createElement("li");
    li.textContent = w;
    warningsEl.appendChild(li);
  }
  sourceImage = new Image();
  sourceImage.onload = () => {
    drawPlan();
  };
  sourceImage.src = project.source_image_url + "?t=" + Date.now();
  await refreshScene();
}

function updateStatus() {
  if (!project) return;
  if (project.calibration.calibrated) {
    statusEl.textContent = project.calibration.note;
    statusEl.className = "status ok";
  } else {
    statusEl.textContent =
      "UNCALIBRATED — not real scale until you measure a wall and click Calibrate.";
    statusEl.className = "status warn";
  }
}

function activeWalls() {
  return (project.walls || []).filter((w) => !w.removed);
}

function drawPlan() {
  if (!sourceImage.naturalWidth) return;
  const maxW = Math.min(1100, sourceImage.naturalWidth);
  scale = maxW / sourceImage.naturalWidth;
  canvas.width = Math.round(sourceImage.naturalWidth * scale);
  canvas.height = Math.round(sourceImage.naturalHeight * scale);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(sourceImage, 0, 0, canvas.width, canvas.height);

  for (const wall of activeWalls()) {
    const isSel = wall.id === selectedWallId;
    ctx.strokeStyle = isSel ? "#c45c00" : confidenceColor(wall.confidence);
    ctx.lineWidth = isSel ? 3.5 : 2;
    ctx.beginPath();
    ctx.moveTo(wall.start.x * scale, wall.start.y * scale);
    ctx.lineTo(wall.end.x * scale, wall.end.y * scale);
    ctx.stroke();
  }

  for (const room of (project.rooms || []).filter((r) => !r.removed)) {
    if (!room.points?.length) continue;
    ctx.strokeStyle = "rgba(20,140,90,0.85)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    room.points.forEach((p, i) => {
      const x = p.x * scale;
      const y = p.y * scale;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
  }

  for (const p of pickPoints) {
    ctx.fillStyle = "#0f5c4c";
    ctx.beginPath();
    ctx.arc(p.x * scale, p.y * scale, 5, 0, Math.PI * 2);
    ctx.fill();
  }
  if (pickPoints.length === 2) {
    ctx.strokeStyle = "#0f5c4c";
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(pickPoints[0].x * scale, pickPoints[0].y * scale);
    ctx.lineTo(pickPoints[1].x * scale, pickPoints[1].y * scale);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  for (const p of drawPoints) {
    ctx.fillStyle = "#1a4";
    ctx.beginPath();
    ctx.arc(p.x * scale, p.y * scale, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function confidenceColor(c) {
  if (c === "high") return "#1f8a3b";
  if (c === "low") return "#c0392b";
  if (c === "user") return "#d35400";
  return "#e67e22";
}

function canvasToImage(evt) {
  const rect = canvas.getBoundingClientRect();
  const x = ((evt.clientX - rect.left) / rect.width) * sourceImage.naturalWidth;
  const y = ((evt.clientY - rect.top) / rect.height) * sourceImage.naturalHeight;
  return { x, y };
}

function distPointSeg(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy || 1;
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const qx = a.x + t * dx;
  const qy = a.y + t * dy;
  return Math.hypot(p.x - qx, p.y - qy);
}

canvas.addEventListener("click", async (evt) => {
  if (!project) return;
  const p = canvasToImage(evt);
  if (mode === "draw") {
    drawPoints.push(p);
    if (drawPoints.length === 2) {
      await fetch("/api/walls", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: drawPoints[0], end: drawPoints[1] }),
      });
      drawPoints = [];
      await loadProject();
    } else {
      drawPlan();
    }
    return;
  }

  // Prefer using clicks as calibration points when collecting a measured segment
  if (pickPoints.length < 2) {
    pickPoints.push(p);
    selectionInfo.textContent =
      pickPoints.length === 1
        ? "First calibration point set — click the other end of the wall."
        : `Calibration segment ready (${Math.hypot(
            pickPoints[1].x - pickPoints[0].x,
            pickPoints[1].y - pickPoints[0].y
          ).toFixed(1)} px). Enter mm and calibrate.`;
    drawPlan();
  }

  // Also select nearest wall for delete
  let best = null;
  let bestD = 12 / scale;
  for (const wall of activeWalls()) {
    const d = distPointSeg(p, wall.start, wall.end);
    if (d < bestD) {
      bestD = d;
      best = wall;
    }
  }
  selectedWallId = best ? best.id : selectedWallId;
  document.getElementById("btn-remove").disabled = !selectedWallId;
  drawPlan();
});

document.getElementById("btn-clear-selection").onclick = () => {
  pickPoints = [];
  selectionInfo.textContent = "";
  drawPlan();
};

document.getElementById("btn-calibrate").onclick = async () => {
  if (pickPoints.length !== 2) {
    alert("Click two endpoints of a known wall first.");
    return;
  }
  const measured = Number(measuredInput.value);
  if (!(measured > 0)) {
    alert("Enter a positive measured length in millimetres.");
    return;
  }
  const res = await fetch("/api/calibrate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      measured_mm: measured,
      start: pickPoints[0],
      end: pickPoints[1],
      segment_id: selectedWallId,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "Calibration failed");
    return;
  }
  pickPoints = [];
  await loadProject();
  alert("Calibrated. DXF/SVG re-exported with metric units.");
};

document.getElementById("btn-remove").onclick = async () => {
  if (!selectedWallId) return;
  await fetch(`/api/walls/${selectedWallId}/remove`, { method: "POST" });
  selectedWallId = null;
  await loadProject();
};

document.getElementById("btn-export").onclick = async () => {
  const res = await fetch("/api/export", { method: "POST" });
  const data = await res.json();
  alert("Exported:\n" + Object.values(data.exports || {}).join("\n"));
};

document.getElementById("btn-mode-select").onclick = () => {
  mode = "select";
  document.getElementById("btn-mode-select").classList.add("active");
  document.getElementById("btn-mode-draw").classList.remove("active");
};

document.getElementById("btn-mode-draw").onclick = () => {
  mode = "draw";
  document.getElementById("btn-mode-draw").classList.add("active");
  document.getElementById("btn-mode-select").classList.remove("active");
};

wallHeightInput.addEventListener("change", async () => {
  const wall_height_mm = Number(wallHeightInput.value);
  await fetch("/api/wall-height", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ wall_height_mm }),
  });
  await refreshScene();
});

function init3d() {
  const host = document.getElementById("view3d");
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(host.clientWidth, host.clientHeight);
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xd5ddd8);
  const camera = new THREE.PerspectiveCamera(50, host.clientWidth / host.clientHeight, 0.05, 500);
  camera.position.set(4, 6, 8);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  controls.update();

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dir = new THREE.DirectionalLight(0xffffff, 0.7);
  dir.position.set(5, 10, 3);
  scene.add(dir);
  scene.add(new THREE.GridHelper(20, 20, 0x889988, 0xb7c4bc));

  const root = new THREE.Group();
  scene.add(root);

  view3d.renderer = renderer;
  view3d.scene = scene;
  view3d.camera = camera;
  view3d.controls = controls;
  view3d.root = root;

  window.addEventListener("resize", () => {
    const w = host.clientWidth;
    const h = host.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });

  (function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  })();
}

async function refreshScene() {
  const res = await fetch("/api/scene");
  const data = await res.json();
  sceneNote.textContent = `${data.units}: ${data.note}`;
  while (view3d.root.children.length) {
    view3d.root.remove(view3d.root.children[0]);
  }

  const height = data.wall_height_m || 2.7;
  const mat = new THREE.MeshStandardMaterial({
    color: data.calibrated ? 0xd9c8a8 : 0xc9a27a,
    roughness: 0.85,
    metalness: 0.05,
    side: THREE.DoubleSide,
  });

  let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
  for (const wall of data.walls) {
    const [x1, z1] = wall.a;
    const [x2, z2] = wall.b;
    minX = Math.min(minX, x1, x2);
    maxX = Math.max(maxX, x1, x2);
    minZ = Math.min(minZ, z1, z2);
    maxZ = Math.max(maxZ, z1, z2);

    const dx = x2 - x1;
    const dz = z2 - z1;
    const length = Math.hypot(dx, dz);
    if (length < 1e-4) continue;
    const geom = new THREE.BoxGeometry(length, height, 0.12);
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.set((x1 + x2) / 2, height / 2, (z1 + z2) / 2);
    mesh.rotation.y = -Math.atan2(dz, dx);
    view3d.root.add(mesh);
  }

  if (Number.isFinite(minX)) {
    const cx = (minX + maxX) / 2;
    const cz = (minZ + maxZ) / 2;
    view3d.controls.target.set(cx, 0, cz);
    view3d.camera.position.set(cx + 4, 6, cz + 8);
    view3d.controls.update();
  }
}

init3d();
loadProject();
