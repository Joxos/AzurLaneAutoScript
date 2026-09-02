// PROBE: temporary instrumentation for the remaining whole-machine stutter.
//
// The backend OCR/CPU probe (removed) showed the bot process is idle-ish
// during stutter (sys_cpu ~13%, OCR calls 2-21ms, no call >=250ms), so the
// remaining suspect is the WebView side: the renderer/main thread of the
// Tauri WebView2 (or the browser tab) doing layout/insert/JSON work while
// the log stream keeps it saturated.
//
// What this measures, every 30s, tagged [PROBE][WEB]:
//   - longtasks   main-thread long tasks (>=50ms) from PerformanceObserver
//   - fps / frameGapMax  requestAnimationFrame cadence (visual smoothness)
//   - lagMax      setTimeout drift (event-loop saturation)
//   - dom         total element count of the page (log blowup detection)
//   - heap        usedJSHeapSize (Chromium/WebView2 only; undefined elsewhere)
//
// The summary is printed to the browser console AND POSTed to the backend
// /probe sink, so it lands in the webui log file (grep PROBE log/*gui*.txt)
// even when the desktop WebView has no visible devtools.
//
// Remove together with module/webui/api/routers/probe.py, the /probe entry
// in vite.config.ts, the POST_* helper here, and the startWebviewProbe()
// call in main.ts once the data is collected.

const BASE = import.meta.env.VITE_API_BASE ?? "";
const INTERVAL_MS = 30_000;
const LAG_TICK_MS = 500;

interface WebviewProbeState {
  rafId: number | null;
  frames: number;
  lastFrameTs: number;
  maxFrameGap: number;
  expectedLag: number;
  maxLag: number;
  longtasks: number;
  longtaskTotalMs: number;
  longtaskMaxMs: number;
  since: number;
  observer: PerformanceObserver | null;
  started: boolean;
}

const state: WebviewProbeState = {
  rafId: null,
  frames: 0,
  lastFrameTs: 0,
  maxFrameGap: 0,
  expectedLag: 0,
  maxLag: 0,
  longtasks: 0,
  longtaskTotalMs: 0,
  longtaskMaxMs: 0,
  since: 0,
  observer: null,
  started: false,
};

/** Reset frame/lag baselines when the tab becomes visible again (rAF and
 *  timers are throttled/suspended while hidden, which would inflate gaps). */
function onVisibility(): void {
  state.lastFrameTs = 0;
  state.frames = 0;
  state.expectedLag = performance.now();
  state.maxLag = 0;
}

function frameLoop(): void {
  if (document.hidden) {
    state.rafId = requestAnimationFrame(frameLoop);
    return;
  }
  const now = performance.now();
  state.frames += 1;
  if (state.lastFrameTs > 0) {
    const gap = now - state.lastFrameTs;
    if (gap > state.maxFrameGap) state.maxFrameGap = gap;
  }
  state.lastFrameTs = now;
  state.rafId = requestAnimationFrame(frameLoop);
}

function startLongTaskObserver(): void {
  try {
    state.observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        state.longtasks += 1;
        const ms = entry.duration;
        state.longtaskTotalMs += ms;
        if (ms > state.longtaskMaxMs) state.longtaskMaxMs = ms;
      }
    });
    state.observer.observe({ type: "longtask", buffered: false });
  } catch {
    // longtask observer unsupported: the rest of the probe still works.
    state.observer = null;
  }
}

function heapMb(): number | null {
  const mem = (performance as unknown as { memory?: { usedJSHeapSize?: number } }).memory;
  if (!mem || typeof mem.usedJSHeapSize !== "number") return null;
  return mem.usedJSHeapSize / (1024 * 1024);
}

/** POST a [PROBE]-tagged line to the backend /probe sink so it lands in
 *  the webui log file (grep PROBE log/*gui*.txt). Shared by this module and
 *  the SSE/LogView probes. Never throws. */
export function postProbe(line: string): void {
  try {
    if (!line.startsWith("[PROBE]")) return;
    fetch(`${BASE}/probe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ line }),
    }).catch(() => undefined);
  } catch {
    // network/webview teardown: ignore
  }
}

function flush(): void {
  try {
    const now = performance.now();
    const secs = (now - state.since) / 1000;
    const visible = !document.hidden;
    const fps = visible ? state.frames / secs : null;
    const parts = [
      `longtasks=${state.longtasks}`,
      `longtaskTotal=${state.longtaskTotalMs.toFixed(0)}ms`,
      `longtaskMax=${state.longtaskMaxMs.toFixed(1)}ms`,
      fps === null ? `fps=n/a(hidden)` : `fps=${fps.toFixed(1)}`,
      `frameGapMax=${state.maxFrameGap.toFixed(1)}ms`,
      visible ? `lagMax=${state.maxLag.toFixed(0)}ms` : "lagMax=n/a(hidden)",
      `dom=${document.getElementsByTagName("*").length}`,
    ];
    const heap = heapMb();
    if (heap !== null) parts.push(`heap=${heap.toFixed(1)}MB`);
    const line = `[PROBE][WEB] ${parts.join(" ")}`;
    console.warn(line);
    postProbe(line);
    // Reset window counters.
    state.frames = 0;
    state.maxFrameGap = 0;
    state.maxLag = 0;
    state.longtasks = 0;
    state.longtaskTotalMs = 0;
    state.longtaskMaxMs = 0;
    state.since = now;
    state.expectedLag = now;
  } catch {
    // The probe must never break the app.
  }
}

/** Start the webview-side probe. No-op if already started; safe to call in
 *  both the browser tab and the Tauri WebView. */
export function startWebviewProbe(): void {
  if (state.started) return;
  state.started = true;
  state.since = performance.now();
  state.expectedLag = state.since;

  startLongTaskObserver();

  document.addEventListener("visibilitychange", onVisibility);

  // Timers keep running for the whole app lifetime on purpose: the probe
  // can never be "stopped" mid-investigation by a lost handle.
  state.rafId = requestAnimationFrame(frameLoop);
  window.setInterval(() => {
    if (document.hidden) return;
    const now = performance.now();
    const drift = now - state.expectedLag;
    if (drift > state.maxLag) state.maxLag = drift;
    state.expectedLag = now + LAG_TICK_MS;
  }, LAG_TICK_MS);
  window.setInterval(flush, INTERVAL_MS);
}
