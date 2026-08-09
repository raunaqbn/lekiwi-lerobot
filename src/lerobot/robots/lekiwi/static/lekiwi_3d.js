import * as THREE from "./vendor/three/three.module.min.js";
import { OrbitControls } from "./vendor/three/examples/jsm/controls/OrbitControls.js";
import URDFLoader from "./vendor/urdf-loader/URDFLoader.js";

const MOTOR_IDS = {
  arm_shoulder_pan: 1,
  arm_shoulder_lift: 2,
  arm_elbow_flex: 3,
  arm_wrist_flex: 4,
  arm_wrist_roll: 5,
  arm_gripper: 6,
  base_left_wheel: 7,
  base_back_wheel: 8,
  base_right_wheel: 9,
};

const SEVERITY_COLORS = {
  healthy: 0x43ad83,
  warning: 0xd89532,
  critical: 0xd95463,
  unpowered: 0x71809a,
  offline: 0x97a1b4,
};

const canvas = document.querySelector("#robot-canvas");
const stage = document.querySelector("#twin-stage");
const loading = document.querySelector("#twin-loading");
const selectedName = document.querySelector("#selected-part-name");
const selectedState = document.querySelector("#selected-part-state");
const selectedId = document.querySelector("#selected-part-id");
const selectedVoltage = document.querySelector("#selected-part-voltage");
const selectedTemp = document.querySelector("#selected-part-temperature");
const selectedPosition = document.querySelector("#selected-part-position");
const selectedTorque = document.querySelector("#selected-part-torque");
const estimatedMotionToggle = document.querySelector("#estimated-chassis-motion");
const odometryWarning = document.querySelector("#odometry-warning");
const resetOdometryButton = document.querySelector("#reset-odometry");

let renderer;
let scene;
let camera;
let controls;
let robot;
let latestFollower;
let selectedMotorName = "arm_shoulder_pan";
let animationFrame;
const hotspots = new Map();

function format(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${value}${suffix}`;
}

function findMotor(name) {
  return latestFollower?.motors?.find((motor) => motor.name === name);
}

function updateInspector(name = selectedMotorName) {
  selectedMotorName = name;
  const motor = findMotor(name);
  if (!motor) return;
  selectedName.textContent = motor.label;
  selectedState.textContent = motor.severity === "unpowered" ? "Unpowered" : motor.severity;
  selectedState.dataset.severity = motor.severity;
  selectedId.textContent = `Follower · ID ${String(motor.id).padStart(2, "0")}`;
  selectedVoltage.textContent = format(motor.voltage_v, " V");
  selectedTemp.textContent = format(motor.temperature_c, " °C");
  selectedPosition.textContent = Number.isFinite(motor.joint_position_rad)
    ? `${motor.joint_position_rad.toFixed(3)} rad · ${format(motor.position_deg, "°")}`
    : "—";
  selectedTorque.textContent = motor.torque_enabled == null ? "—" : motor.torque_enabled ? "Enabled" : "Disabled";
  hotspots.forEach((button, motorName) => button.classList.toggle("is-selected", motorName === name));
}

function selectMotor(name) {
  updateInspector(name);
  tintRobot();
  canvas.setAttribute("aria-label", `${findMotor(name)?.label || name} selected in the LeKiwi digital twin`);
  window.dispatchEvent(new CustomEvent("lekiwi-motor-select", { detail: { source: "follower", id: MOTOR_IDS[name] } }));
}

function createHotspots() {
  Object.entries(MOTOR_IDS).forEach(([name, id]) => {
    if (!robot.joints[name]) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "twin-hotspot";
    button.setAttribute("aria-label", `Inspect follower motor ${id}, ${findMotor(name)?.label || name}`);
    button.title = findMotor(name)?.label || name;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectMotor(name);
    });
    stage.append(button);
    hotspots.set(name, button);
  });
}

function updateHotspots() {
  if (!robot) return;
  const point = new THREE.Vector3();
  hotspots.forEach((button, name) => {
    const joint = robot.joints[name];
    joint.getWorldPosition(point);
    point.project(camera);
    button.style.left = `${(point.x * 0.5 + 0.5) * stage.clientWidth}px`;
    button.style.top = `${(-point.y * 0.5 + 0.5) * stage.clientHeight}px`;
    button.hidden = point.z < -1 || point.z > 1;
    button.dataset.severity = findMotor(name)?.severity || "offline";
  });
}

function tagJointMeshes() {
  Object.keys(MOTOR_IDS).forEach((name) => {
    const joint = robot.joints[name];
    if (!joint) return;
    joint.traverse((object) => {
      if (!object.isMesh) return;
      object.userData.motorName = name;
      object.material = new THREE.MeshStandardMaterial({
        color: 0xd8dce4,
        metalness: 0.08,
        roughness: 0.72,
      });
    });
  });
}

function tintRobot() {
  if (!robot || !latestFollower) return;
  robot.traverse((object) => {
    if (!object.isMesh || !object.userData.motorName) return;
    const motor = findMotor(object.userData.motorName);
    const color = SEVERITY_COLORS[motor?.severity] ?? 0xaab3c4;
    object.material.color.setHex(color);
    object.material.emissive.setHex(object.userData.motorName === selectedMotorName ? color : 0x000000);
    object.material.emissiveIntensity = object.userData.motorName === selectedMotorName ? 0.16 : 0;
  });
}

function applyTelemetry() {
  if (!robot || !latestFollower) return;
  latestFollower.motors.forEach((motor) => {
    const radians = motor.joint_position_rad;
    if (Number.isFinite(radians) && robot.joints[motor.name]) robot.setJointValue(motor.name, radians);
  });
  const odometry = latestFollower.odometry || { x: 0, y: 0, theta: 0 };
  const showEstimatedMotion = Boolean(estimatedMotionToggle?.checked);
  robot.position.set(showEstimatedMotion ? odometry.x || 0 : 0, showEstimatedMotion ? odometry.y || 0 : 0, 0);
  robot.rotation.z = showEstimatedMotion ? odometry.theta || 0 : 0;
  if (odometryWarning) odometryWarning.hidden = !showEstimatedMotion;
  stage.dataset.stale = latestFollower.stale ? "true" : "false";
  hotspots.forEach((button, name) => {
    const motor = findMotor(name);
    if (motor) button.setAttribute("aria-label", `Inspect follower motor ${motor.id}, ${motor.label}`);
  });
  updateInspector();
  tintRobot();
}

function selectFromPointer(event) {
  if (!robot) return;
  const bounds = canvas.getBoundingClientRect();
  const pointer = new THREE.Vector2(
    ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
    -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
  );
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObject(robot, true).find((item) => item.object.userData.motorName);
  if (!hit) return;
  const name = hit.object.userData.motorName;
  selectMotor(name);
}

function resize() {
  if (!renderer || !stage) return;
  const width = Math.max(stage.clientWidth, 320);
  const height = Math.max(stage.clientHeight, 360);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function frameRobot() {
  const box = new THREE.Box3().setFromObject(robot);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxSize = Math.max(size.x, size.y, size.z);
  const distance = (maxSize / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)))) * 1.05;
  const viewDirection = new THREE.Vector3(1.05, -1.45, 0.9).normalize();
  controls.target.copy(center).add(new THREE.Vector3(0, 0, -size.z * 0.14));
  camera.position.copy(center).addScaledVector(viewDirection, distance);
  camera.near = Math.max(distance / 100, 0.001);
  camera.far = distance * 100;
  camera.up.set(0, 0, 1);
  camera.updateProjectionMatrix();
  camera.lookAt(controls.target);
  controls.update();
}

function animate() {
  animationFrame = requestAnimationFrame(animate);
  controls.update();
  updateHotspots();
  renderer.render(scene, camera);
}

function init() {
  if (!canvas || !stage) return;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.92;

    scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xf7f9ff, 0x8994a9, 1.15));
    const key = new THREE.DirectionalLight(0xffffff, 1.65);
    key.position.set(2.5, -3, 5);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xaeb8ff, 0.6);
    fill.position.set(-4, 2, 2);
    scene.add(fill);

    camera = new THREE.PerspectiveCamera(34, 1, 0.01, 100);
    controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.075;
    controls.minDistance = 0.28;
    controls.maxDistance = 2.5;

    const grid = new THREE.GridHelper(1.2, 12, 0xc9ceda, 0xe7eaf0);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -0.035;
    scene.add(grid);

    const manager = new THREE.LoadingManager();
    manager.onLoad = () => {
      if (!robot) return;
      frameRobot();
      applyTelemetry();
      loading.hidden = true;
      stage.dataset.ready = "true";
    };
    const loader = new URDFLoader(manager);
    loader.load(
      "/static/models/lekiwi/LeKiwi.urdf",
      (loadedRobot) => {
        robot = loadedRobot;
        scene.add(robot);
        robot.traverse((object) => {
          if (object.isMesh) {
            object.castShadow = true;
            object.receiveShadow = true;
            object.material = new THREE.MeshStandardMaterial({ color: 0xdfe3ea, roughness: 0.72, metalness: 0.06 });
          }
        });
        tagJointMeshes();
        createHotspots();
      },
      undefined,
      (error) => {
        loading.querySelector("strong").textContent = "3D model unavailable";
        loading.querySelector("span").textContent = error?.message || "The CAD assets could not be loaded.";
      },
    );

    canvas.addEventListener("click", selectFromPointer);
    document.querySelector("#reset-camera")?.addEventListener("click", frameRobot);
    estimatedMotionToggle?.addEventListener("change", applyTelemetry);
    resetOdometryButton?.addEventListener("click", async () => {
      resetOdometryButton.disabled = true;
      try {
        const response = await fetch("/api/odometry/reset", { method: "POST" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        latestFollower = result.state?.sources?.follower || result.state;
        applyTelemetry();
      } finally {
        resetOdometryButton.disabled = false;
      }
    });
    new ResizeObserver(resize).observe(stage);
    resize();
    animate();
  } catch (error) {
    loading.querySelector("strong").textContent = "WebGL unavailable";
    loading.querySelector("span").textContent = "Use the motor network and readings below instead.";
  }
}

window.lekiwiTwin = {
  update(state) {
    latestFollower = state?.sources?.follower;
    applyTelemetry();
  },
  destroy() {
    cancelAnimationFrame(animationFrame);
    renderer?.dispose();
  },
};

init();
