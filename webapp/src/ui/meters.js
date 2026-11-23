import { el } from '../utils.js';

// /meter is linear amplitude. We display it as dBFS assuming 1.0 = digital
// full scale, the usual float-DSP convention. That top is still not confirmed
// against a genuinely clipping signal (PROTOCOL_NOTES.md, Open Questions #5),
// but loud bass-heavy playback measured 2026-11-23 peaked around 0.13 in /
// 0.07 out (~-18 / -23 dBFS) with the front panel's red LIMIT LED dark (its
// 3 amber steps + red LIMIT carry no dB marks; only the bottom amber flickered). (An earlier linear x1000 display
// pinned the bar at "clip" from 0.1 upward -- i.e. at normal loud listening.)
const FLOOR_DB = -60;
const HOT_DB = -12;
const CLIP_DB = -0.5;

const METERS = [
  { key: 'inputA', label: 'In A' },
  { key: 'inputB', label: 'In B' },
  { key: 'outputA', label: 'Out A' },
  { key: 'outputB', label: 'Out B' },
];

export function toDbfs(v) {
  return v > 0 ? 20 * Math.log10(v) : -Infinity;
}

export function mountMeters(container, { store }) {
  const rows = METERS.map(({ key, label }) => {
    const fill = el('div', { class: 'meter-fill' });
    const valueText = el('span', { class: 'note', style: 'width:4.5rem;text-align:right' }, '-inf dB');
    const row = el('div', { class: 'meter', title: `dBFS assuming 1.0 = full scale (${FLOOR_DB}..0 dB). Full-scale point not yet confirmed against real clipping.` }, [
      el('span', { class: 'meter-label' }, label),
      el('div', { class: 'meter-track' }, [fill]),
      valueText,
    ]);
    return { key, fill, valueText, row };
  });

  container.append(...rows.map((r) => r.row));

  store.subscribe((state) => {
    for (const r of rows) {
      const v = state.meter[r.key] ?? 0;
      const db = toDbfs(v);
      const pct = Math.max(0, Math.min(100, ((db - FLOOR_DB) / -FLOOR_DB) * 100));
      r.fill.style.width = `${pct}%`;
      r.fill.classList.toggle('hot', db >= HOT_DB && db < CLIP_DB);
      r.fill.classList.toggle('clip', db >= CLIP_DB);
      r.valueText.textContent = Number.isFinite(db) ? `${db.toFixed(1)} dB` : '-inf dB';
      r.row.title = `${v.toFixed(5)} linear`;
    }
  });
}
