const canvas = document.getElementById("gridCanvas");
const ctx = canvas.getContext("2d");
let layout = { scale: 1, offsetX: 0, offsetY: 0 };
let edgeScreenCache = [];
let commuteChart;
let speedChart;
let maxSpeedLimit = 15;

function showToast(message) {
  const template = document.getElementById("toastTemplate");
  const toast = template.content.firstElementChild.cloneNode(true);
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3600);
}

function mapNetworkToCanvas(network) {
  const nodes = network.nodes || [];
  if (!nodes.length) return layout;
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padding = 50;
  const width = canvas.width - padding * 2;
  const height = canvas.height - padding * 2;
  const scaleX = width / Math.max(maxX - minX || 1, 1);
  const scaleY = height / Math.max(maxY - minY || 1, 1);
  const scale = Math.min(scaleX, scaleY);
  layout = {
    scale,
    offsetX: padding - minX * scale,
    offsetY: padding - minY * scale,
  };
  return layout;
}

function toScreen(x, y) {
  return {
    x: x * layout.scale + layout.offsetX,
    y: y * layout.scale + layout.offsetY,
  };
}

function drawGlowingEdge(edge, nodes, isClosed) {
  const from = nodes[edge.from];
  const to = nodes[edge.to];
  if (!from || !to) return;
  const start = toScreen(from.x, from.y);
  const end = toScreen(to.x, to.y);

  ctx.save();
  ctx.strokeStyle = isClosed ? "#ff6b6b" : "rgba(108,244,255,0.8)";
  ctx.lineWidth = 8;
  ctx.lineCap = "round";
  ctx.shadowColor = isClosed ? "rgba(255,107,107,0.8)" : "rgba(108,244,255,0.8)";
  ctx.shadowBlur = 16;
  ctx.beginPath();
  ctx.moveTo(start.x, start.y);
  ctx.lineTo(end.x, end.y);
  ctx.stroke();
  ctx.restore();

  edgeScreenCache.push({ id: edge.id, start, end });
}

function drawVehicle(veh) {
  const { x, y } = toScreen(veh.coords.x, veh.coords.y);
  const speedRatio = Math.min(veh.velocity / maxSpeedLimit, 1);
  const red = Math.floor(255 * speedRatio);
  const green = Math.floor(255 * (1 - speedRatio));
  ctx.save();
  ctx.fillStyle = `rgb(${red},${green},120)`;
  ctx.shadowColor = "rgba(255,255,255,0.6)";
  ctx.shadowBlur = 10;
  ctx.beginPath();
  ctx.arc(x, y, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawState(state) {
  if (!state.network) return;
  edgeScreenCache = [];
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const nodes = Object.fromEntries((state.network.nodes || []).map((n) => [n.id, n]));
  mapNetworkToCanvas(state.network);
  const edges = state.network.edges || [];
  maxSpeedLimit = Math.max(...edges.map((e) => e.speed_limit || 1), 1);

  edges.forEach((edge) => {
    drawGlowingEdge(edge, nodes, state.closed_edges.includes(edge.id));
  });

  (state.vehicles || []).forEach(drawVehicle);
}

function updateMetrics(state) {
  document.getElementById("tickValue").textContent = state.tick;
  document.getElementById("avgSpeed").textContent = state.metrics.average_speed.toFixed(2);
  document.getElementById("avgCommute").textContent = state.metrics.average_commute_time.toFixed(1);
  document.getElementById("stuckCount").textContent = state.metrics.stuck_vehicles;

  if (state.settings) {
    document.getElementById("spawnInterval").value = state.settings.spawn_interval;
    document.getElementById("nsTiming").value = state.settings.signal_timings.NS;
    document.getElementById("ewTiming").value = state.settings.signal_timings.EW;
  }
}

function initCharts() {
  const commuteCtx = document.getElementById("commuteChart").getContext("2d");
  const speedCtx = document.getElementById("speedChart").getContext("2d");

  commuteChart = new Chart(commuteCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Avg Commute (ticks)",
          data: [],
          borderColor: "#6cf4ff",
          backgroundColor: "rgba(108,244,255,0.2)",
          tension: 0.3,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#8da2c0" } }, y: { ticks: { color: "#8da2c0" } } },
    },
  });

  speedChart = new Chart(speedCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Avg Speed (m/s)",
          data: [],
          borderColor: "#7bff85",
          backgroundColor: "rgba(123,255,133,0.2)",
          tension: 0.3,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#8da2c0" } }, y: { ticks: { color: "#8da2c0" } } },
    },
  });
}

function updateCharts(history) {
  if (!commuteChart || !speedChart) return;
  const labels = history.map((h) => h.tick);
  commuteChart.data.labels = labels;
  commuteChart.data.datasets[0].data = history.map((h) => h.average_commute_time);
  commuteChart.update("none");

  speedChart.data.labels = labels;
  speedChart.data.datasets[0].data = history.map((h) => h.average_speed);
  speedChart.update("none");
}

async function fetchState() {
  const res = await fetch("/api/state");
  if (!res.ok) throw new Error("Failed to fetch state");
  return res.json();
}

async function poll() {
  try {
    const state = await fetchState();
    drawState(state);
    updateMetrics(state);
    updateCharts(state.history || []);
  } catch (err) {
    console.error(err);
  } finally {
    requestAnimationFrame(() => setTimeout(poll, 800));
  }
}

async function updateSignals() {
  const ns = parseFloat(document.getElementById("nsTiming").value);
  const ew = parseFloat(document.getElementById("ewTiming").value);
  const res = await fetch("/api/settings/signals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ns, ew }),
  });
  if (!res.ok) throw new Error("Unable to update signals");
  showToast("Signal timings updated");
}

async function updateSpawn() {
  const spawn_interval = parseInt(document.getElementById("spawnInterval").value, 10);
  const res = await fetch("/api/settings/spawn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spawn_interval }),
  });
  if (!res.ok) throw new Error("Unable to update spawn interval");
  showToast("Spawn interval updated");
}

function distanceToEdge(pt, edge) {
  const { start, end } = edge;
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSq = dx * dx + dy * dy || 1;
  const t = Math.max(0, Math.min(1, ((pt.x - start.x) * dx + (pt.y - start.y) * dy) / lengthSq));
  const projX = start.x + t * dx;
  const projY = start.y + t * dy;
  const distX = pt.x - projX;
  const distY = pt.y - projY;
  return Math.sqrt(distX * distX + distY * distY);
}

async function handleCanvasClick(event) {
  const rect = canvas.getBoundingClientRect();
  const click = { x: event.clientX - rect.left, y: event.clientY - rect.top };
  let closest = { id: null, dist: Infinity };
  edgeScreenCache.forEach((edge) => {
    const dist = distanceToEdge(click, edge);
    if (dist < closest.dist) closest = { id: edge.id, dist };
  });

  if (closest.id && closest.dist < 14) {
    const res = await fetch("/api/closures/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edge_id: closest.id }),
    });
    if (res.ok) {
      const result = await res.json();
      showToast(`${result.edge_id} is now ${result.closed ? "closed" : "open"}`);
    }
  }
}

function bindControls() {
  document.getElementById("updateSignals").addEventListener("click", () => {
    updateSignals().catch(() => showToast("Failed to update signals"));
  });
  document.getElementById("updateSpawn").addEventListener("click", () => {
    updateSpawn().catch(() => showToast("Failed to update spawn"));
  });
  canvas.addEventListener("click", (evt) => handleCanvasClick(evt));
}

initCharts();
bindControls();
poll();
