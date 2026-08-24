(() => {
  "use strict";

  const FPS = 30;
  const DURATION = 122.933;
  const PROTOCOL = {
    protocolVersion: 1,
    capabilities: [
      "seconds-time",
      "rational-fps",
      "seek-keep-playing",
      "composition-manifest-v1",
    ],
    fps: { numerator: FPS, denominator: 1 },
  };

  const state = {
    time: 0,
    playing: false,
    muted: false,
    volume: 1,
    playbackRate: 1,
    lastTickMs: 0,
    scenes: [],
    media: [],
  };

  function post(type, details = {}) {
    window.parent.postMessage(
      { source: "hf-preview", type, ...details, ...PROTOCOL },
      "*",
    );
  }

  async function mountComposition(host) {
    const source = host.dataset.compositionSrc;
    if (!source) return;

    const response = await fetch(source);
    if (!response.ok)
      throw new Error(
        `Unable to load composition ${source}: ${response.status}`,
      );
    const sourceDocument = new DOMParser().parseFromString(
      await response.text(),
      "text/html",
    );
    const template = sourceDocument.querySelector("template");
    if (!template)
      throw new Error(`Composition ${source} does not contain a template`);

    const content = template.content.cloneNode(true);
    const scripts = [...content.querySelectorAll("script")];
    scripts.forEach((script) => script.remove());
    host.appendChild(content);

    for (const sourceScript of scripts) {
      if (sourceScript.src) continue; // GSAP is already loaded by the parent composition.
      const script = document.createElement("script");
      script.textContent = sourceScript.textContent;
      host.appendChild(script);
    }
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function timelineFor(scene) {
    return window.__timelines?.[scene.id] ?? null;
  }

  function syncVisuals(timeSeconds) {
    const master = window.__timelines?.main;
    master?.pause(timeSeconds, false);

    for (const scene of state.scenes) {
      const localTime = clamp(timeSeconds - scene.start, 0, scene.duration);
      timelineFor(scene)?.pause(localTime, false);
      const nearScene =
        timeSeconds >= scene.start - 0.7 &&
        timeSeconds <= scene.start + scene.duration + 0.7;
      scene.element.style.visibility = nearScene ? "visible" : "hidden";
    }

    const captions = window.__timelines?.captions;
    captions?.pause(clamp(timeSeconds, 0, DURATION), false);
  }

  function mediaBounds(media) {
    return {
      start: Number(media.dataset.start ?? 0),
      duration: Number(media.dataset.duration ?? media.duration ?? 0),
    };
  }

  function applyMediaSettings(media) {
    media.muted = state.muted;
    media.volume = state.volume * Number(media.dataset.volume ?? 1);
    media.playbackRate = state.playbackRate;
  }

  function syncMedia(timeSeconds, shouldPlay) {
    for (const media of state.media) {
      const { start, duration } = mediaBounds(media);
      const active = timeSeconds >= start && timeSeconds < start + duration;
      if (!active) {
        media.pause();
        continue;
      }

      applyMediaSettings(media);
      const localTime = clamp(
        timeSeconds - start,
        0,
        Math.max(0, duration - 0.01),
      );
      if (
        Number.isFinite(media.duration) &&
        Math.abs(media.currentTime - localTime) > 0.24
      ) {
        media.currentTime = localTime;
      }
      if (shouldPlay) media.play().catch(() => post("media-autoplay-blocked"));
      else media.pause();
    }
  }

  function emitState() {
    post("state", {
      frame: Math.round(state.time * FPS),
      isPlaying: state.playing,
    });
  }

  function seek(timeSeconds, preservePlayback = false) {
    state.time = clamp(Number(timeSeconds) || 0, 0, DURATION);
    syncVisuals(state.time);
    syncMedia(state.time, preservePlayback && state.playing);
    emitState();
  }

  function play() {
    if (state.time >= DURATION) seek(0);
    state.playing = true;
    state.lastTickMs = performance.now();
    syncMedia(state.time, true);
    emitState();
  }

  function pause() {
    state.playing = false;
    syncMedia(state.time, false);
    emitState();
  }

  function tick() {
    if (!state.playing) return;
    const now = performance.now();
    const elapsed = Math.min(0.1, Math.max(0, (now - state.lastTickMs) / 1000));
    state.lastTickMs = now;
    state.time = clamp(state.time + elapsed * state.playbackRate, 0, DURATION);
    syncVisuals(state.time);
    syncMedia(state.time, true);
    if (state.time >= DURATION) state.playing = false;
    emitState();
  }

  function handleControl(event) {
    const message = event.data;
    if (
      !message ||
      message.source !== "hf-parent" ||
      message.type !== "control"
    )
      return;
    switch (message.action) {
      case "play":
        play();
        break;
      case "pause":
        pause();
        break;
      case "tick":
        tick();
        break;
      case "seek":
        seek(Number(message.timeSeconds ?? message.frame / FPS), state.playing);
        break;
      case "stop-media":
        pause();
        break;
      case "set-muted":
      case "set-media-output-muted":
        state.muted = Boolean(message.muted);
        syncMedia(state.time, state.playing);
        break;
      case "set-volume":
        state.volume = clamp(Number(message.volume ?? 1), 0, 1);
        syncMedia(state.time, state.playing);
        break;
      case "set-playback-rate":
        state.playbackRate = clamp(Number(message.playbackRate ?? 1), 0.1, 5);
        break;
      default:
        break;
    }
  }

  async function boot() {
    const mounts = [...document.querySelectorAll("[data-composition-src]")];
    await Promise.all(mounts.map(mountComposition));

    state.scenes = mounts
      .filter((element) => element.id !== "el-captions")
      .map((element) => ({
        id: element.dataset.compositionId,
        element,
        start: Number(element.dataset.start ?? 0),
        duration: Number(element.dataset.duration ?? 0),
      }));
    state.media = [...document.querySelectorAll("audio, video")];

    window.__player = {
      getDuration: () => DURATION,
      getCurrentTime: () => state.time,
      seek,
      play,
      pause,
    };
    window.addEventListener("message", handleControl);
    seek(0);
    post("ready");
    post("timeline", {
      durationInFrames: Math.round(DURATION * FPS),
      durationSeconds: DURATION,
      compositionWidth: 1920,
      compositionHeight: 1080,
      scenes: state.scenes.map(({ id, start, duration }) => ({
        id,
        start,
        duration,
      })),
    });
  }

  if (document.readyState === "loading")
    document.addEventListener(
      "DOMContentLoaded",
      () => boot().catch(console.error),
      { once: true },
    );
  else boot().catch(console.error);
})();
