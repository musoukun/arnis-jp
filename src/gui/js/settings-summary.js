// arnis-jp: a short read-out of the main settings next to the Start button, so
// what the next generation will use is visible without opening the settings.
// It only reads the controls; values and persistence stay with settings-store.js.

import { SETTINGS_REFRESHED_EVENT } from './settings-layout.js';

// label: key in locales/jp/<lang>.json. section: the settings section a click opens.
// Two per row in this order; wide items take a whole row for their longer values.
const ITEMS = [
  { label: 'summary_world_scale', section: 'area', id: 'scale-value-slider', kind: 'range', unit: '' },
  { label: 'summary_height_multiplier', section: 'area', id: 'height-multiplier-slider', kind: 'range', unit: '×' },
  { label: 'summary_rotation', section: 'area', id: 'rotation-angle-input', kind: 'number', unit: '°' },
  { label: 'summary_world_time', section: 'world', id: 'world-time-value', kind: 'text' },
  { label: 'summary_gsi', section: 'japan', id: 'gsi-toggle', kind: 'checkbox' },
  { label: 'summary_satellite', section: 'japan', id: 'satellite-toggle', kind: 'checkbox' },
  { label: 'summary_plateau', section: 'japan', id: 'plateau-toggle', kind: 'checkbox' },
  { label: 'summary_interior', section: 'generation', id: 'interior-toggle', kind: 'checkbox' },
  { label: 'summary_generation_mode', section: 'generation', id: 'generation-mode-cards', kind: 'segmented', wide: true },
  { label: 'summary_gamemode', section: 'world', id: 'gamemode-group', kind: 'segmented', wide: true },
];

function text(key) {
  const loc = window.localization || {};
  return loc[key] || key;
}

function readValue(item, el) {
  switch (item.kind) {
    case 'range':
      return parseFloat(el.value).toFixed(2) + item.unit;
    case 'number':
      return (parseFloat(el.value) || 0) + item.unit;
    case 'checkbox':
      return text(el.checked ? 'summary_on' : 'summary_off');
    case 'segmented': {
      const active = el.querySelector('.segment.active');
      if (!active) return '-';
      const title = active.querySelector('.choice-title');
      return (title || active).textContent.trim();
    }
    default:
      return el.textContent.trim();
  }
}

// settings-store.js marks each row that differs from its default.
function isModified(el) {
  const row = el.closest('.settings-row');
  return !!(row && row.classList.contains('is-modified'));
}

function openSection(section) {
  if (typeof window.openSettings === 'function') window.openSettings();
  const nav = document.querySelector(`.settings-nav-item[data-target="settings-section-${section}"]`);
  if (nav) nav.click();
}

export function refreshSettingsSummary() {
  const root = document.getElementById('settings-summary');
  if (!root) return;
  const title = root.querySelector('.settings-summary-title');
  const list = root.querySelector('.settings-summary-list');
  title.textContent = text('summary_title');
  list.replaceChildren();

  ITEMS.forEach((item) => {
    const el = document.getElementById(item.id);
    if (!el) return;
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'settings-summary-item';
    row.classList.toggle('is-modified', isModified(el));
    row.classList.toggle('is-wide', !!item.wide);
    row.title = text('summary_open_hint');
    row.addEventListener('click', () => openSection(item.section));

    const label = document.createElement('span');
    label.className = 'settings-summary-label';
    label.textContent = text(item.label);
    const value = document.createElement('span');
    value.className = 'settings-summary-value';
    value.textContent = readValue(item, el);

    row.append(label, value);
    list.append(row);
  });
}

export function initSettingsSummary() {
  document.addEventListener(SETTINGS_REFRESHED_EVENT, refreshSettingsSummary);
}
