const isFilePreview = window.location.protocol === "file:";

const elements = {
  app: document.querySelector("#app"),
  fileLaunch: document.querySelector("#file-launch"),
  copyCommand: document.querySelector("#copy-command"),
  launchCommand: document.querySelector("#launch-command"),
  form: document.querySelector("#connection-form"),
  port: document.querySelector("#serial-port"),
  portList: document.querySelector("#available-ports"),
  baudrate: document.querySelector("#baudrate"),
  deepScan: document.querySelector("#deep-scan"),
  followerUrl: document.querySelector("#follower-url"),
  saveFollower: document.querySelector("#save-follower"),
  connectButton: document.querySelector("#connect-button"),
  disconnectButton: document.querySelector("#disconnect-button"),
  autodetectButton: document.querySelector("#autodetect-button"),
  refreshPorts: document.querySelector("#refresh-ports"),
  settings: document.querySelector("#connection-settings"),
  connectionIcon: document.querySelector("#connection-icon"),
  connectionTitle: document.querySelector("#connection-title"),
  connectionDetail: document.querySelector("#connection-detail"),
  headerDot: document.querySelector("#header-dot"),
  headerState: document.querySelector("#header-state"),
  errorBanner: document.querySelector("#error-banner"),
  errorMessage: document.querySelector("#error-message"),
  dismissError: document.querySelector("#dismiss-error"),
  networkCanvas: document.querySelector("#network-canvas"),
  leaderRail: document.querySelector("#leader-motor-rail"),
  followerArmRail: document.querySelector("#follower-arm-rail"),
  followerBaseRail: document.querySelector("#follower-base-rail"),
  leaderRouteMeta: document.querySelector("#leader-route-meta"),
  followerRouteMeta: document.querySelector("#follower-route-meta"),
  sourceDots: document.querySelectorAll(".route-source-dot"),
  leaderCard: document.querySelector("#leader-source-card"),
  followerCard: document.querySelector("#follower-source-card"),
  leaderDetail: document.querySelector("#leader-source-detail"),
  followerDetail: document.querySelector("#follower-source-detail"),
  leaderCount: document.querySelector("#leader-source-count"),
  followerCount: document.querySelector("#follower-source-count"),
  leaderVoltage: document.querySelector("#leader-source-voltage"),
  followerVoltage: document.querySelector("#follower-source-voltage"),
  verdictIcon: document.querySelector("#verdict-icon"),
  verdictTitle: document.querySelector("#verdict-title"),
  verdictDetail: document.querySelector("#verdict-detail"),
  updatedAt: document.querySelector("#updated-at"),
  countDetected: document.querySelector("#count-detected"),
  countExpected: document.querySelector("#count-expected"),
  countAttention: document.querySelector("#count-attention"),
  trackHealthy: document.querySelector("#track-healthy"),
  trackWarning: document.querySelector("#track-warning"),
  trackCritical: document.querySelector("#track-critical"),
  trackOffline: document.querySelector("#track-offline"),
  findingList: document.querySelector("#finding-list"),
  findingTotal: document.querySelector("#finding-total"),
  activeLink: document.querySelector("#active-link"),
  activeProfile: document.querySelector("#active-profile"),
  activeBaud: document.querySelector("#active-baud"),
  pollLatency: document.querySelector("#poll-latency"),
  tableBody: document.querySelector("#motor-table-body"),
  rowTemplate: document.querySelector("#motor-row-template"),
  filters: document.querySelectorAll(".filter-button"),
  footerTopology: document.querySelector("#footer-topology"),
  powerConfidence: document.querySelector("#power-confidence"),
  usbPowerNode: document.querySelector("#usb-power-node"),
  railPowerNode: document.querySelector("#rail-power-node"),
  usbPowerState: document.querySelector("#usb-power-state"),
  railPowerState: document.querySelector("#rail-power-state"),
  powerDetail: document.querySelector("#power-detail"),
  batteryVoltage: document.querySelector("#battery-voltage"),
  batteryRange: document.querySelector("#battery-range"),
  batteryEnergy: document.querySelector("#battery-energy"),
  batteryFill: document.querySelector("#battery-fill"),
  batteryDetail: document.querySelector("#battery-detail"),
  accessModeBadge: document.querySelector("#access-mode-badge"),
  accessModeLabel: document.querySelector("#access-mode-label"),
  footerMode: document.querySelector("#footer-mode"),
  controlEnabled: document.querySelector("#control-enabled"),
  controlStateChip: document.querySelector("#control-state-chip"),
  controlPermitReason: document.querySelector("#control-permit-reason"),
  armTakeover: document.querySelector("#arm-takeover"),
  stopMotion: document.querySelector("#stop-motion"),
  baseCommandOutput: document.querySelector("#base-command-output"),
  baseButtons: document.querySelectorAll("[data-base-key]"),
  speedButtons: document.querySelectorAll("#speed-selector [data-speed]"),
  jointRows: document.querySelectorAll(".joint-jog[data-joint]"),
  controlSafety: document.querySelector("#control-safety"),
  cameraHealth: document.querySelector("#camera-health"),
  cameraViews: document.querySelectorAll(".camera-view[data-camera]"),
  frontCameraAge: document.querySelector("#front-camera-age"),
  wristCameraAge: document.querySelector("#wrist-camera-age"),
};

const severityCopy = {
  healthy: "Healthy",
  warning: "Check",
  critical: "Fault",
  unpowered: "Unpowered",
  offline: "Offline",
  not_applicable: "Not on bus",
};

let latestState = null;
let requestInFlight = false;
let activeFilter = "all";
let initialAutodetectRequested = false;
let eventSource = null;
let lastFullRenderAt = 0;
const holdTimers = new Map();
const operationUiReady = [
  elements.accessModeLabel,
  elements.footerMode,
  elements.controlEnabled,
  elements.controlStateChip,
  elements.controlPermitReason,
  elements.armTakeover,
  elements.stopMotion,
  elements.controlSafety,
  elements.cameraHealth,
].every(Boolean);

function format(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${value}${suffix}`;
}

function formatBaud(value) {
  return value ? Number(value).toLocaleString("en-US") : "—";
}

function timeAgo(timestamp) {
  if (!timestamp) return "No sample yet";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (seconds < 2) return "Updated now";
  if (seconds < 60) return `Updated ${seconds}s ago`;
  return `Updated ${Math.round(seconds / 60)}m ago`;
}

function averageVoltage(source) {
  const values = source.motors.map((motor) => motor.voltage_v).filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  return Math.round((values.reduce((total, value) => total + value, 0) / values.length) * 10) / 10;
}

function sourceSummary(source) {
  if (source.connected) {
    if (source.counts.unpowered) return "USB controller online · no servo power detected.";
    if (source.counts.critical) return `${source.counts.critical} fault${source.counts.critical === 1 ? " needs" : "s need"} attention.`;
    if (source.counts.warning) return `${source.counts.warning} reading${source.counts.warning === 1 ? "" : "s"} need a check.`;
    return `All ${source.counts.expected} expected motors are responding.`;
  }
  if (source.error) return `Feed unavailable: ${source.error}`;
  return source.source === "leader"
    ? "Waiting for the six-motor leader bus."
    : "Add the Pi diagnostics URL to receive all nine motors.";
}

async function loadPorts() {
  elements.refreshPorts.disabled = true;
  try {
    const response = await fetch("/api/ports", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    elements.portList.replaceChildren();
    data.ports.forEach((port) => {
      const option = document.createElement("option");
      option.value = port.device;
      const tags = [port.remembered ? "remembered" : "", port.plausible ? "USB serial" : ""].filter(Boolean).join(", ");
      option.label = `${port.description}${tags ? ` · ${tags}` : ""}`;
      elements.portList.append(option);
    });
    if (!elements.port.value && data.selected && !String(data.selected).startsWith("SIMULATED")) elements.port.value = data.selected;
    if (!elements.port.value && data.ports.length === 1) elements.port.value = data.ports[0].device;
  } catch (error) {
    showError(`Could not list serial ports: ${error.message}`);
  } finally {
    elements.refreshPorts.disabled = false;
  }
}

async function fetchState() {
  if (requestInFlight) return;
  requestInFlight = true;
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    render(state);
    if (!initialAutodetectRequested && !state.demo && !state.connected && state.autodetect_status === "idle") {
      initialAutodetectRequested = true;
      void autodetect();
    }
  } catch (error) {
    showError(`Diagnostics service is unavailable: ${error.message}`);
  } finally {
    requestInFlight = false;
  }
}

function startStream() {
  if (eventSource || typeof EventSource === "undefined") return;
  eventSource = new EventSource("/api/stream");
  eventSource.addEventListener("state", (event) => {
    try {
      const state = JSON.parse(event.data);
      const now = performance.now();
      // Pose flows to the digital twin at the stream rate. Rebuilding the
      // evidence table is intentionally limited to health-field cadence.
      if (now - lastFullRenderAt >= 900 || !latestState) {
        render(state);
        lastFullRenderAt = now;
      } else {
        latestState = state;
        window.lekiwiTwin?.update(state);
      }
    } catch (error) {
      showError(`Invalid telemetry stream sample: ${error.message}`);
    }
  });
  eventSource.onerror = () => {
    eventSource?.close();
    eventSource = null;
    window.setTimeout(startStream, 1000);
  };
}

async function autodetect() {
  elements.autodetectButton.disabled = true;
  elements.autodetectButton.querySelector("span").textContent = "Finding…";
  try {
    const response = await fetch("/api/autodetect", { method: "POST" });
    const result = await response.json();
    render(result.state);
  } catch (error) {
    showError(`Leader detection could not start: ${error.message}`);
  } finally {
    window.setTimeout(() => {
      elements.autodetectButton.disabled = false;
      elements.autodetectButton.querySelector("span").textContent = "Find automatically";
    }, 500);
  }
}

async function connect(event) {
  event.preventDefault();
  elements.connectButton.disabled = true;
  elements.connectButton.textContent = elements.deepScan.checked ? "Scanning all rates…" : "Connecting…";
  try {
    const response = await fetch("/api/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        port: elements.port.value.trim(),
        baudrate: Number(elements.baudrate.value),
        deep: elements.deepScan.checked,
      }),
    });
    const result = await response.json();
    render(result.state);
    if (!response.ok) throw new Error(result.error || "Connection failed");
  } catch (error) {
    showError(error.message);
  } finally {
    elements.connectButton.disabled = false;
    elements.connectButton.textContent = "Connect manually";
  }
}

async function disconnect() {
  elements.disconnectButton.disabled = true;
  try {
    const response = await fetch("/api/disconnect", { method: "POST" });
    render((await response.json()).state);
  } catch (error) {
    showError(`Could not disconnect cleanly: ${error.message}`);
  } finally {
    elements.disconnectButton.disabled = false;
  }
}

async function saveFollower() {
  elements.saveFollower.disabled = true;
  elements.saveFollower.textContent = "Connecting…";
  try {
    const response = await fetch("/api/follower", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: elements.followerUrl.value.trim() }),
    });
    const result = await response.json();
    render(result.state);
  } catch (error) {
    showError(`Could not configure the follower feed: ${error.message}`);
  } finally {
    elements.saveFollower.disabled = false;
    elements.saveFollower.textContent = "Connect follower feed";
  }
}

async function sendControl(path, payload, { renderState = true } = {}) {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-LeKiwi-Control": "dashboard-v1",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (renderState && result.state) render(result.state);
    if (!response.ok) throw new Error(result.error || `Control request failed (HTTP ${response.status})`);
    return result;
  } catch (error) {
    showError(error.message);
    throw error;
  }
}

function bindDeadmanButton(button, path, payload, onVisualState) {
  const stop = () => {
    const timer = holdTimers.get(button);
    if (timer) window.clearInterval(timer);
    holdTimers.delete(button);
    if (!button.classList.contains("is-pressed")) return;
    button.classList.remove("is-pressed");
    onVisualState?.(false);
    void sendControl(path, { ...payload, active: false }, { renderState: false }).catch(() => {});
  };

  button.addEventListener("pointerdown", (event) => {
    if (button.disabled) return;
    event.preventDefault();
    button.setPointerCapture?.(event.pointerId);
    button.classList.add("is-pressed");
    onVisualState?.(true);
    const pulse = () => void sendControl(path, { ...payload, active: true }, { renderState: false }).catch(stop);
    pulse();
    holdTimers.set(button, window.setInterval(pulse, 180));
  });
  button.addEventListener("pointerup", stop);
  button.addEventListener("pointercancel", stop);
  button.addEventListener("lostpointercapture", stop);
  button.addEventListener("contextmenu", (event) => event.preventDefault());
}

function renderOperation(state) {
  // A long-running Flask process can retain an older Jinja template while
  // static assets are refreshed from disk. Keep the core diagnostics feed
  // usable until that process is restarted instead of failing the full render.
  if (!operationUiReady) return;

  const control = state.control || {};
  const available = Boolean(control.available);
  const permitted = Boolean(control.permitted);
  const enabled = Boolean(control.enabled);
  const armTakeover = Boolean(control.arm_takeover);
  const stopped = Boolean(control.stop_latched);

  elements.accessModeLabel.textContent = available ? "Teleop control" : "Read only";
  elements.footerMode.textContent = available ? "Cached telemetry · owner-loop controls" : "Safe, read-only inspection";
  elements.controlEnabled.checked = enabled;
  elements.controlEnabled.disabled = !available || (!permitted && !enabled);
  elements.controlPermitReason.textContent = control.permit_reason || "Start teleoperation to enable controls.";
  elements.armTakeover.checked = armTakeover;
  elements.armTakeover.disabled = !enabled;
  elements.stopMotion.disabled = !available;

  let stateLabel = "Unavailable";
  let stateKey = "offline";
  if (stopped) {
    stateLabel = "Stop latched";
    stateKey = "stopped";
  } else if (enabled) {
    stateLabel = armTakeover ? "Base + arm armed" : "Base armed";
    stateKey = "armed";
  } else if (permitted) {
    stateLabel = "Ready to enable";
    stateKey = "ready";
  }
  elements.controlStateChip.textContent = stateLabel;
  elements.controlStateChip.dataset.state = stateKey;
  elements.controlSafety.dataset.state = stateKey;
  if (stopped) {
    elements.controlSafety.innerHTML = "<span aria-hidden=\"true\">■</span><p><strong>Motion stop is latched.</strong> Base velocity is zero and the follower arm is holding its observed pose. Re-enable dashboard control to resume.</p>";
  } else if (enabled) {
    elements.controlSafety.innerHTML = "<span aria-hidden=\"true\">●</span><p><strong>Dashboard control is armed.</strong> Every movement button is a dead-man control; release it to stop. Stop motion remains available at all times.</p>";
  } else {
    elements.controlSafety.innerHTML = "<span aria-hidden=\"true\">◎</span><p><strong>Controls are locked.</strong> Lift the base for first tests, clear the arm’s workspace, then enable dashboard control.</p>";
  }

  elements.baseButtons.forEach((button) => { button.disabled = !enabled; });
  elements.speedButtons.forEach((button) => {
    button.disabled = !enabled;
    button.classList.toggle("is-active", Number(button.dataset.speed) === Number(control.speed_index || 0));
  });
  elements.jointRows.forEach((row) => {
    row.querySelectorAll("button").forEach((button) => { button.disabled = !enabled || !armTakeover; });
  });

  const followerMotors = state.sources?.follower?.motors || [];
  elements.jointRows.forEach((row) => {
    const motorName = row.dataset.joint.replace(/\.pos$/, "");
    const motor = followerMotors.find((candidate) => candidate.name === motorName);
    const value = motor?.position_deg;
    row.querySelector("output").textContent = Number.isFinite(value)
      ? `${value.toFixed(1)}${motorName === "arm_gripper" ? "%" : "°"}`
      : "—";
  });

  const cameras = state.cameras || {};
  let liveCameras = 0;
  elements.cameraViews.forEach((view) => {
    const status = cameras[view.dataset.camera] || {};
    const stale = !status.available || status.stale;
    view.dataset.stale = String(stale);
    if (!stale) liveCameras += 1;
    const age = status.last_update ? timeAgo(status.last_update).replace("Updated ", "") : "No frame";
    const target = view.dataset.camera === "front" ? elements.frontCameraAge : elements.wristCameraAge;
    target.textContent = age;
  });
  elements.cameraHealth.dataset.severity = liveCameras === 2 ? "healthy" : liveCameras ? "warning" : "offline";
  elements.cameraHealth.textContent = liveCameras === 2 ? "2 cameras live" : liveCameras ? "1 camera live" : "Waiting for frames";
}

function showError(message) {
  elements.errorMessage.textContent = message;
  elements.errorBanner.hidden = false;
}

function render(state) {
  if (!state?.sources) return;
  latestState = state;
  const leader = state.sources.leader;
  const follower = state.sources.follower;
  const counts = state.system_counts;
  const attention = counts.warning + counts.critical;
  const bothConnected = state.connected_sources === 2;
  const embedded = state.sample_mode === "embedded_control_loop";

  elements.headerDot.dataset.severity = state.system_overall;
  elements.headerState.textContent = bothConnected
    ? `${counts.detected} of ${counts.expected} motors live across both arms`
    : state.connected_sources
      ? `1 of 2 telemetry sources connected`
      : "Robot sources offline";

  elements.connectionIcon.dataset.state = state.connected ? "connected" : state.autodetecting ? "searching" : "attention";
  elements.connectionTitle.textContent = embedded ? "Telemetry embedded in teleoperation" : state.connected ? "Local motor bus connected" : state.autodetecting ? "Finding the leader arm" : "Leader arm is not connected";
  elements.connectionDetail.textContent = embedded
    ? "Teleoperation exclusively owns both serial buses; this dashboard only reads cached snapshots."
    : state.connected
    ? "The Mac USB feed is live; follower telemetry is handled separately through the Pi."
    : "Connect the leader USB adapter or open connection settings to choose it manually.";
  elements.autodetectButton.hidden = embedded;
  elements.settings.hidden = embedded;
  elements.autodetectButton.disabled = state.connected || state.autodetecting || state.demo;
  elements.disconnectButton.hidden = !state.connected || state.demo;
  elements.connectButton.disabled = state.autodetecting || state.demo;
  elements.networkCanvas.dataset.mode = bothConnected ? "connected" : state.connected_sources ? "partial" : "offline";

  if (state.follower_url && !elements.followerUrl.matches(":focus")) elements.followerUrl.value = state.follower_url.replace(/\/api\/state$/, "");

  renderSourceCard(leader, elements.leaderCard, elements.leaderDetail, elements.leaderCount, elements.leaderVoltage, "Bus voltage");
  renderSourceCard(follower, elements.followerCard, elements.followerDetail, elements.followerCount, elements.followerVoltage, "Battery rail");
  elements.leaderRouteMeta.textContent = `${leader.serial_port || "Mac USB"} · ${leader.connected ? "live" : "offline"}`;
  elements.followerRouteMeta.textContent = `${follower.endpoint?.replace(/\/api\/state$/, "") || "Raspberry Pi"} · ${follower.connected ? "live" : "offline"}`;
  elements.sourceDots.forEach((dot) => dot.dataset.severity = state.sources[dot.dataset.source].overall);

  renderRail(elements.leaderRail, leader.motors, "leader");
  renderRail(elements.followerArmRail, follower.motors.filter((motor) => motor.group === "arm"), "follower");
  renderRail(elements.followerBaseRail, follower.motors.filter((motor) => motor.group === "base"), "follower");
  renderVerdict(state, attention);
  renderTable(state.all_motors);
  renderFindings(state.sources);
  renderPower(follower.power);
  renderBattery(state.battery);
  renderOperation(state);
  window.lekiwiTwin?.update(state);

  const timestamps = [leader.last_update, follower.last_update].filter(Boolean).sort();
  elements.updatedAt.textContent = timestamps.length ? timeAgo(timestamps[0]) : "No sample yet";
  elements.countDetected.textContent = counts.detected;
  elements.countExpected.textContent = `of ${counts.expected} expected`;
  elements.countAttention.textContent = attention;
  elements.activeProfile.textContent = "Leader + follower";
  elements.activeLink.textContent = `${leader.connected ? "Mac" : "—"} + ${follower.connected ? "Pi" : "—"}`;
  elements.activeBaud.textContent = `${formatBaud(leader.baudrate)} / ${formatBaud(follower.baudrate)}`;
  elements.pollLatency.textContent = [leader.poll_latency_ms, follower.poll_latency_ms].filter(Number.isFinite).map((value) => `${value} ms`).join(" / ") || "—";
  elements.footerTopology.textContent = `Dual-source robot network · ${counts.expected} expected devices`;

  const offline = Math.max(0, counts.expected - counts.detected);
  const denominator = counts.expected || 1;
  elements.trackHealthy.style.flexBasis = `${(counts.healthy / denominator) * 100}%`;
  elements.trackWarning.style.flexBasis = `${(counts.warning / denominator) * 100}%`;
  elements.trackCritical.style.flexBasis = `${(counts.critical / denominator) * 100}%`;
  elements.trackOffline.style.flexBasis = `${(offline / denominator) * 100}%`;

  const localError = state.error;
  if (localError) showError(localError);
  else elements.errorBanner.hidden = true;
}

function renderSourceCard(source, card, detail, count, voltage) {
  card.dataset.severity = source.overall;
  detail.textContent = sourceSummary(source);
  count.textContent = `${source.counts.detected} / ${source.counts.expected}`;
  voltage.textContent = format(averageVoltage(source), " V");
}

function renderPower(power = {}) {
  const usb = power.usb_controller || "offline";
  const rail = power.servo_rail || "unknown";
  elements.usbPowerNode.dataset.state = usb;
  elements.railPowerNode.dataset.state = rail;
  elements.usbPowerState.textContent = usb === "online" ? "Online" : "Offline";
  elements.railPowerState.textContent = rail === "powered" ? "Powered" : rail === "no_power_detected" ? "No power detected" : "Unknown";
  elements.powerConfidence.textContent = power.confidence === "confirmed" ? "Confirmed" : power.confidence === "inferred" ? "Best inference" : "Unknown";
  elements.powerConfidence.dataset.severity = rail === "powered" ? "healthy" : rail === "no_power_detected" ? "warning" : "offline";
  elements.powerDetail.textContent = power.detail || "Waiting for follower telemetry.";
}

function renderBattery(battery = {}) {
  if (!battery.available) {
    elements.batteryVoltage.textContent = "—";
    elements.batteryRange.textContent = "Unavailable";
    elements.batteryEnergy.textContent = "Turn on the servo rail to sample pack voltage.";
    elements.batteryFill.style.transform = "scaleX(0)";
    elements.batteryDetail.textContent = "The follower voltage is unavailable. A 5 V leader reading is never used for this estimate.";
    return;
  }
  elements.batteryVoltage.textContent = `${battery.voltage_v} V`;
  elements.batteryRange.textContent = `${battery.percent_min}–${battery.percent_max}%`;
  elements.batteryEnergy.textContent = `${battery.remaining_wh_min}–${battery.remaining_wh_max} Wh estimated`;
  elements.batteryFill.style.transform = `scaleX(${battery.percent_max / 100})`;
  elements.batteryDetail.textContent = "Low-confidence range from the follower’s 3S servo rail. Runtime needs pack-current data or a logged discharge curve.";
}

function renderRail(container, motors, source) {
  container.replaceChildren();
  motors.forEach((motor) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "motor-node motor-node--rail";
    button.dataset.severity = motor.severity;
    button.dataset.source = source;
    button.dataset.motorId = motor.id;
    const index = document.createElement("span");
    index.className = "node-index";
    index.textContent = String(motor.id).padStart(2, "0");
    const copy = document.createElement("span");
    copy.className = "node-copy";
    const name = document.createElement("strong");
    name.textContent = motor.label;
    const reading = document.createElement("small");
    reading.textContent = motor.detected ? `${format(motor.voltage_v, " V")} · ${format(motor.temperature_c, "°C")}` : motor.severity === "unpowered" ? "No servo power" : "Not sampled";
    copy.append(name, reading);
    const motorState = document.createElement("span");
    motorState.className = "node-state";
    motorState.textContent = severityCopy[motor.severity] || "Unknown";
    button.append(index, copy, motorState);
    button.setAttribute("aria-label", `${source} motor ${motor.id}, ${motor.label}, ${motorState.textContent}`);
    button.addEventListener("click", () => focusMotor(source, motor.id));
    container.append(button);
  });
}

function renderVerdict(state, attention) {
  const counts = state.system_counts;
  let title;
  let detail;
  if (state.connected_sources === 2 && !attention) {
    if (counts.unpowered) {
      title = "Follower servo rail appears to be off";
      detail = "The Pi and USB controller are online, but no follower servo returned a powered status packet.";
    } else {
      title = "Both robot sources are healthy";
      detail = `All ${counts.expected} leader and follower motors are reporting.`;
    }
  } else if (state.connected_sources === 2) {
    title = `${attention} reading${attention === 1 ? " needs" : "s need"} attention`;
    detail = "The source and motor name identify exactly which physical arm owns each reading.";
  } else if (state.connected_sources === 1) {
    title = "One telemetry source is still missing";
    detail = "Connected motors remain visible; the missing source is not counted as a motor fault.";
  } else {
    title = "Connect the leader and follower feeds";
    detail = "The leader uses local USB. The follower publishes from the Raspberry Pi.";
  }
  elements.verdictIcon.dataset.severity = state.system_overall;
  elements.verdictTitle.textContent = title;
  elements.verdictDetail.textContent = detail;
}

function renderTable(motors) {
  elements.tableBody.replaceChildren();
  motors.filter(matchesFilter).forEach((motor) => {
    const row = elements.rowTemplate.content.firstElementChild.cloneNode(true);
    row.dataset.motorId = motor.id;
    row.dataset.source = motor.source;
    row.dataset.group = motor.group;
    const sourceLabel = row.querySelector(".table-source");
    sourceLabel.dataset.source = motor.source;
    sourceLabel.textContent = motor.source === "leader" ? "Leader" : "Follower";
    row.querySelector(".table-id").textContent = String(motor.id).padStart(2, "0");
    row.querySelector(".table-name").textContent = motor.label;
    row.querySelector(".table-model").textContent = motor.detected ? motor.model : motor.severity === "unpowered" ? "No servo power" : "No response";
    const stateLabel = row.querySelector(".table-state");
    stateLabel.dataset.severity = motor.severity;
    stateLabel.textContent = severityCopy[motor.severity] || "Unknown";
    row.querySelector(".position-value").textContent = format(motor.position_deg, "°");
    row.querySelector(".position-raw").textContent = motor.position_raw == null ? "" : `raw ${motor.position_raw}`;
    row.querySelector(".velocity-value").textContent = format(motor.velocity_deg_s, "°/s");
    row.querySelector(".velocity-raw").textContent = motor.velocity_raw == null ? "" : `raw ${motor.velocity_raw}`;
    row.querySelector(".voltage-value").textContent = format(motor.voltage_v, " V");
    row.querySelector(".temperature-value").textContent = format(motor.temperature_c, " °C");
    row.querySelector(".current-value").textContent = format(motor.current_raw);
    row.querySelector(".torque-value").textContent = motor.torque_enabled == null ? "—" : motor.torque_enabled ? "Enabled" : "Disabled";
    elements.tableBody.append(row);
  });
}

function matchesFilter(motor) {
  if (activeFilter === "all") return true;
  if (activeFilter === "leader" || activeFilter === "follower") return motor.source === activeFilter;
  return motor.group === activeFilter;
}

function renderFindings(sources) {
  const issues = [];
  Object.values(sources).forEach((source) => {
    if (!source.connected) {
      issues.push({ severity: "offline", title: `${source.source_label} feed`, detail: sourceSummary(source) });
      return;
    }
    source.findings.filter((finding) => finding.severity !== "healthy").forEach((finding) => {
      issues.push({ ...finding, title: `${source.source_label} · ${finding.title}` });
    });
  });
  elements.findingList.replaceChildren();
  elements.findingTotal.textContent = issues.length;
  if (!issues.length) {
    const empty = document.createElement("div");
    empty.className = "finding-empty";
    empty.innerHTML = "<strong>No issues detected</strong><span>Both sources are reporting within their own voltage and temperature bands.</span>";
    elements.findingList.append(empty);
    return;
  }
  issues.forEach((finding) => {
    const item = document.createElement("div");
    item.className = "finding-item";
    const dot = document.createElement("i");
    dot.dataset.severity = finding.severity;
    const title = document.createElement("strong");
    title.textContent = finding.title;
    const detail = document.createElement("span");
    detail.textContent = finding.detail;
    item.append(dot, title, detail);
    elements.findingList.append(item);
  });
}

function setFilter(filter) {
  activeFilter = filter;
  elements.filters.forEach((button) => button.classList.toggle("is-active", button.dataset.filter === filter));
  if (latestState) renderTable(latestState.all_motors);
}

function focusMotor(source, id) {
  if (!latestState) return;
  if (activeFilter !== "all" && activeFilter !== source) setFilter(source);
  window.setTimeout(() => {
    const row = elements.tableBody.querySelector(`[data-source="${source}"][data-motor-id="${id}"]`);
    if (!row) return;
    row.classList.add("is-focused");
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => row.classList.remove("is-focused"), 1800);
  }, 20);
}

window.addEventListener("lekiwi-motor-select", (event) => focusMotor(event.detail.source, event.detail.id));

elements.form?.addEventListener("submit", connect);
elements.disconnectButton?.addEventListener("click", disconnect);
elements.autodetectButton?.addEventListener("click", autodetect);
elements.refreshPorts?.addEventListener("click", loadPorts);
elements.saveFollower?.addEventListener("click", saveFollower);
elements.dismissError?.addEventListener("click", () => { elements.errorBanner.hidden = true; });
elements.filters.forEach((button) => button.addEventListener("click", () => setFilter(button.dataset.filter)));
elements.copyCommand?.addEventListener("click", async () => {
  await navigator.clipboard.writeText(elements.launchCommand.textContent);
  elements.copyCommand.textContent = "Copied";
  window.setTimeout(() => { elements.copyCommand.textContent = "Copy"; }, 1200);
});

elements.controlEnabled?.addEventListener("change", async () => {
  try {
    await sendControl("/api/control/enable", { enabled: elements.controlEnabled.checked });
  } catch (_error) {
    elements.controlEnabled.checked = false;
  }
});

elements.armTakeover?.addEventListener("change", async () => {
  try {
    await sendControl("/api/control/arm", { enabled: elements.armTakeover.checked });
  } catch (_error) {
    elements.armTakeover.checked = false;
  }
});

elements.stopMotion?.addEventListener("click", async () => {
  elements.baseCommandOutput.textContent = "Stopped";
  elements.baseButtons.forEach((button) => button.classList.remove("is-pressed"));
  elements.jointRows.forEach((row) => row.querySelectorAll("button").forEach((button) => button.classList.remove("is-pressed")));
  await sendControl("/api/control/stop", {});
});

elements.speedButtons.forEach((button) => button.addEventListener("click", async () => {
  await sendControl("/api/control/speed", { speed: Number(button.dataset.speed) });
}));

const baseLabels = {
  w: "Forward",
  s: "Backward",
  a: "Strafe left",
  d: "Strafe right",
  z: "Rotate left",
  x: "Rotate right",
};
elements.baseButtons.forEach((button) => bindDeadmanButton(
  button,
  "/api/control/base",
  { key: button.dataset.baseKey },
  (pressed) => { elements.baseCommandOutput.textContent = pressed ? baseLabels[button.dataset.baseKey] : "Stopped"; },
));

elements.jointRows.forEach((row) => {
  row.querySelectorAll("button[data-direction]").forEach((button) => bindDeadmanButton(
    button,
    "/api/control/joint",
    { joint: row.dataset.joint, direction: Number(button.dataset.direction) },
  ));
});

if (isFilePreview) {
  elements.app.hidden = true;
  elements.fileLaunch.hidden = false;
} else {
  loadPorts();
  fetchState();
  startStream();
  // A low-rate fallback also heals state if a browser or proxy blocks SSE.
  window.setInterval(() => { if (!eventSource) fetchState(); }, 1000);
}
