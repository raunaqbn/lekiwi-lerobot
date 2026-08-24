(function () {
  "use strict";

  const ARM = [
    ["arm_shoulder_pan", "Shoulder pan"],
    ["arm_shoulder_lift", "Shoulder lift"],
    ["arm_elbow_flex", "Elbow flex"],
    ["arm_wrist_flex", "Wrist flex"],
    ["arm_wrist_roll", "Wrist roll"],
    ["arm_gripper", "Gripper"],
  ];
  const BASE = [
    ["base_left_wheel", "Left wheel"],
    ["base_back_wheel", "Back wheel"],
    ["base_right_wheel", "Right wheel"],
  ];
  let scenario = "wheel";

  function motor([name, label], id, source, tick) {
    const leader = source === "leader";
    const wheel = name.startsWith("base_");
    const gripper = name === "arm_gripper";
    const wave = Math.sin(tick / 2400 + id * 0.72);
    const position = gripper ? 52 + wave * 28 : wave * (wheel ? 18 : 42);
    return {
      source,
      name,
      label,
      id,
      group: wheel ? "base" : "arm",
      detected: true,
      model: "STS3215",
      position_raw: Math.round(((position + 180) / 360) * 4096),
      position_deg: Number(position.toFixed(1)),
      joint_position_rad: Number((gripper ? (position / 100) * 0.8 : position * Math.PI / 180).toFixed(4)),
      velocity_raw: wheel ? Math.round(Math.sin(tick / 900 + id) * 12) : 0,
      velocity_deg_s: wheel ? Number((Math.sin(tick / 900 + id) * 1.1).toFixed(1)) : 0,
      voltage_v: leader ? 5.2 : 12.1,
      temperature_c: 32 + (id % 5),
      current_raw: 10 + id * 2,
      torque_enabled: !leader,
      severity: "healthy",
      findings: [],
      in_profile: true,
    };
  }

  function counts(motors) {
    return {
      expected: motors.length,
      detected: motors.filter((item) => item.detected).length,
      healthy: motors.filter((item) => item.severity === "healthy").length,
      warning: motors.filter((item) => item.severity === "warning").length,
      critical: motors.filter((item) => item.severity === "critical").length,
      unpowered: motors.filter((item) => item.severity === "unpowered").length,
    };
  }

  function source(role, motors, now) {
    const sourceCounts = counts(motors);
    const railOff = role === "follower" && scenario === "rail";
    const overall = sourceCounts.critical ? "critical" : sourceCounts.warning || sourceCounts.unpowered ? "warning" : "healthy";
    const findings = [];
    if (railOff) {
      findings.push({ severity: "warning", title: "No servo power detected", detail: "The controller is online, but the follower servos returned no status packets." });
    } else {
      motors.filter((item) => item.severity === "critical").forEach((item) => {
        findings.push({ severity: "critical", title: item.label, detail: "No response on the selected baud rate." });
      });
    }
    return {
      source: role,
      source_label: role === "leader" ? "Leader arm" : "Follower robot",
      connected: true,
      demo: true,
      serial_port: role === "leader" ? "SIMULATED /dev/cu.usbmodem-leader" : "SIMULATED /dev/ttyACM0",
      endpoint: role === "follower" ? "https://sample-robot.local" : null,
      baudrate: 1000000,
      last_update: now,
      poll_latency_ms: role === "leader" ? 3.8 : 7.4,
      overall,
      error: null,
      counts: sourceCounts,
      power: role === "follower"
        ? {
            usb_controller: "online",
            servo_rail: railOff ? "no_power_detected" : "powered",
            confidence: "confirmed",
            detail: railOff
              ? "The USB controller is reachable, but no follower servo answered. Check the servo rail switch and shared data cable."
              : "Controller and servo rail are both reporting through the follower owner loop.",
          }
        : { usb_controller: "online", servo_rail: "powered", confidence: "confirmed", detail: "Leader bus online." },
      battery: role === "follower" && !railOff
        ? { available: true, voltage_v: 12.1, percent_min: 72, percent_max: 88, remaining_wh_min: 41.6, remaining_wh_max: 50.8 }
        : { available: false },
      motors,
      findings,
      profile: {
        key: role === "leader" ? "so101_leader" : "lekiwi_follower",
        label: role === "leader" ? "SO-101 leader" : "LeKiwi follower",
        expected_ids: motors.map((item) => item.id),
        voltage_band: role === "leader" ? [4.3, 6.0] : [9.0, 13.0],
      },
      joint_frame: "lekiwi-fusion-cad-v1",
      odometry: { x: 0, y: 0, theta: 0 },
      stale: false,
    };
  }

  function snapshot() {
    const now = new Date().toISOString();
    const tick = performance.now();
    const leaderMotors = ARM.map((item, index) => motor(item, index + 1, "leader", tick));
    const followerMotors = [...ARM, ...BASE].map((item, index) => motor(item, index + 1, "follower", tick));

    if (scenario === "wheel") {
      const backWheel = followerMotors.find((item) => item.name === "base_back_wheel");
      Object.assign(backWheel, {
        detected: false,
        model: "—",
        position_raw: null,
        position_deg: null,
        joint_position_rad: null,
        velocity_raw: null,
        velocity_deg_s: null,
        voltage_v: null,
        temperature_c: null,
        current_raw: null,
        torque_enabled: null,
        severity: "critical",
        findings: ["No response on the selected baud rate"],
      });
    }

    if (scenario === "rail") {
      followerMotors.forEach((item) => Object.assign(item, {
        detected: false,
        position_raw: null,
        position_deg: null,
        joint_position_rad: null,
        velocity_raw: null,
        velocity_deg_s: null,
        voltage_v: null,
        temperature_c: null,
        current_raw: null,
        torque_enabled: null,
        severity: "unpowered",
        findings: ["No servo power or status packet detected"],
      }));
    }

    const leader = source("leader", leaderMotors, now);
    const follower = source("follower", followerMotors, now);
    const allMotors = [...leaderMotors, ...followerMotors];
    const systemCounts = counts(allMotors);
    const systemOverall = systemCounts.critical ? "critical" : systemCounts.warning || systemCounts.unpowered ? "warning" : "healthy";

    return {
      connected: true,
      connecting: false,
      demo: true,
      sample_mode: "hosted_demo",
      serial_port: leader.serial_port,
      baudrate: 1000000,
      last_update: now,
      poll_latency_ms: leader.poll_latency_ms,
      overall: systemOverall,
      system_overall: systemOverall,
      error: null,
      sources: { leader, follower },
      system_counts: systemCounts,
      connected_sources: 2,
      all_motors: allMotors,
      follower_url: follower.endpoint,
      battery: follower.battery,
      read_only: true,
      cameras: {
        front: { available: false, stale: true, last_update: null },
        wrist: { available: false, stale: true, last_update: null },
      },
      control: {
        available: false,
        permitted: false,
        enabled: false,
        arm_takeover: false,
        stop_latched: false,
        speed_index: 0,
        permit_reason: "Preview only — run the local service to control hardware.",
      },
      autodetecting: false,
      autodetect_status: "demo",
    };
  }

  window.LEKIWI_HOSTED_DEMO = {
    snapshot,
    setScenario(next) {
      scenario = next;
      window.dispatchEvent(new CustomEvent("lekiwi-demo-change"));
    },
  };

  window.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-demo-scenario]").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll("[data-demo-scenario]").forEach((candidate) => {
          candidate.setAttribute("aria-pressed", String(candidate === button));
        });
        window.LEKIWI_HOSTED_DEMO.setScenario(button.dataset.demoScenario);
      });
    });
  });
})();
