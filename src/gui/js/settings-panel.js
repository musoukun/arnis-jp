// arnis-jp: grows the window to the right while the settings panel is open and
// gives the width back when it closes, so the panel never squeezes the map.
// Outside Tauri (a plain browser) and on a maximized window it only overlays.

// Matches --settings-panel-width in settings-panel.css
const PANEL_WIDTH = 700;

// While the panel is open the main view keeps this share of its width, so the
// whole window does not get as wide as main view + panel
const MAIN_SHARE = 0.87;

// Narrowest the main view may get before the panel overlays instead
// (MAIN_SHARE of the app's 1000px minimum width)
const MAIN_MIN_WIDTH = 870;

// Room left for the window frame when fitting the grown window on screen
const FRAME_SLACK = 16;

// Width actually added on open, given back on close (the window's width
// before opening is restored exactly)
let grownBy = 0;

function log(level, message) {
  if (typeof window.arnisLog === 'function') window.arnisLog(level, `[settings-panel] ${message}`);
}

function tauriWindow() {
  const t = window.__TAURI__;
  if (!t || !t.window || !t.window.getCurrentWindow || !t.dpi) {
    log('info', `no Tauri window API (window: ${!!(t && t.window)}, dpi: ${!!(t && t.dpi)})`);
    return null;
  }
  return {
    getCurrentWindow: t.window.getCurrentWindow,
    // A function of the window module, not a method of the window
    currentMonitor: t.window.currentMonitor,
    LogicalSize: t.dpi.LogicalSize,
    LogicalPosition: t.dpi.LogicalPosition,
  };
}

function nextResize(timeoutMs = 500) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    window.addEventListener('resize', () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

// True when the main view still has its minimum width beside the panel,
// so the panel can push it aside rather than cover it.
export function hasRoomForPanel() {
  return window.innerWidth - PANEL_WIDTH >= MAIN_MIN_WIDTH;
}

export async function growWindowForPanel() {
  const api = tauriWindow();
  if (!api || grownBy > 0) return;
  try {
    const win = api.getCurrentWindow();
    if (await win.isMaximized()) {
      log('info', 'window is maximized, panel overlays');
      return;
    }
    const scale = await win.scaleFactor();
    const size = (await win.innerSize()).toLogical(scale);
    const pos = (await win.outerPosition()).toLogical(scale);
    const monitor = await api.currentMonitor();

    let width = Math.round(size.width * MAIN_SHARE) + PANEL_WIDTH;
    let x = pos.x;
    if (monitor) {
      const area = monitor.workArea || { position: monitor.position, size: monitor.size };
      const left = area.position.x / monitor.scaleFactor;
      const right = left + area.size.width / monitor.scaleFactor;
      width = Math.min(width, right - left - FRAME_SLACK);
      // Slide left when the grown window would pass the screen's right edge
      if (x + width + FRAME_SLACK > right) x = Math.max(left, right - width - FRAME_SLACK);
    }

    if (x !== pos.x) await win.setPosition(new api.LogicalPosition(x, pos.y));
    const resized = nextResize();
    await win.setSize(new api.LogicalSize(width, size.height));
    grownBy = width - size.width;
    // The page's innerWidth follows the native resize a moment later
    await resized;
    log('info', `grew window ${size.width} -> ${width} (x ${pos.x} -> ${x})`);
  } catch (e) {
    log('warn', `could not grow the window: ${e}`);
  }
}

export async function shrinkWindowAfterPanel() {
  const api = tauriWindow();
  if (!api || grownBy <= 0) return;
  const by = grownBy;
  grownBy = 0;
  try {
    const win = api.getCurrentWindow();
    const scale = await win.scaleFactor();
    const size = (await win.innerSize()).toLogical(scale);
    await win.setSize(new api.LogicalSize(Math.max(size.width - by, 1000), size.height));
  } catch (e) {
    log('warn', `could not shrink the window: ${e}`);
  }
}
