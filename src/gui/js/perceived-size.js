// arnis-jp: the "Perceived Real Size" section. Each item is its own setting
// (stored by settings-store.js, sent with the generation request). The master
// switch only sets them all at once: on gives arnis-jp's sizes and World Scale
// 1.4, off gives upstream Arnis's. It shows on while every item matches.

const ITEMS = [
  { id: 'wide-roads-toggle', on: true, off: false },
  { id: 'bare-bicycle-parking-toggle', on: true, off: false },
  { id: 'fill-split-buildings-toggle', on: true, off: false },
  { id: 'tall-elevated-toggle', on: true, off: false },
  { id: 'elevated-ratio-slider', on: 1.2, off: 1.2 },
];
const SCALE_ON = 1.4;

function read(el) {
  return el.type === 'checkbox' ? el.checked : parseFloat(el.value);
}

function write(el, value) {
  if (read(el) === value) return;
  if (el.type === 'checkbox') el.checked = value;
  else el.value = value;
  // Events so the label, the store and the summary follow
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function syncMaster(master) {
  master.checked = ITEMS.every((item) => {
    const el = document.getElementById(item.id);
    return el && read(el) === item.on;
  });
}

function refreshRatioLabel() {
  const slider = document.getElementById('elevated-ratio-slider');
  const label = document.getElementById('elevated-ratio-value');
  if (slider && label) label.textContent = parseFloat(slider.value).toFixed(2);
}

export function initPerceivedSize() {
  const master = document.getElementById('perceived-size-toggle');
  if (!master) return;

  master.addEventListener('change', () => {
    const on = master.checked;
    ITEMS.forEach((item) => {
      const el = document.getElementById(item.id);
      if (el) write(el, on ? item.on : item.off);
    });
    const scale = document.getElementById('scale-value-slider');
    if (on && scale && !scale.disabled) write(scale, SCALE_ON);
  });

  ITEMS.forEach((item) => {
    const el = document.getElementById(item.id);
    if (el) el.addEventListener('change', () => syncMaster(master));
  });

  const slider = document.getElementById('elevated-ratio-slider');
  if (slider) slider.addEventListener('input', refreshRatioLabel);
  refreshRatioLabel();
}

// After settings-store.js restores the items, the master has to follow them.
export function syncPerceivedSize() {
  const master = document.getElementById('perceived-size-toggle');
  if (master) syncMaster(master);
  refreshRatioLabel();
}

// The values sent with gui_start_generation
export function perceivedSizeArgs() {
  const get = (id) => document.getElementById(id);
  const ratio = parseFloat(get('elevated-ratio-slider').value);
  return {
    wideRoads: get('wide-roads-toggle').checked,
    tallElevated: get('tall-elevated-toggle').checked,
    elevatedRatio: Number.isFinite(ratio) ? ratio : 1.2,
    bareBicycleParking: get('bare-bicycle-parking-toggle').checked,
    fillSplitBuildings: get('fill-split-buildings-toggle').checked,
  };
}
