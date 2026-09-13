import { el } from '../utils.js';

// /meter is linear amplitude; the scale top and peak-vs-RMS behavior were
// never confirmed against a clipping signal (PROTOCOL_NOTES.md, Open
// Questions #5) -- moderate playback only reached ~0.01. The bar below uses
// an arbitrary visual multiplier so normal listening levels are visible; it
// is NOT calibrated to 0dBFS/clipping, and the raw number is shown alongside
// it so nothing is hidden behind that guess.
const VISUAL_GAIN = 1000;

const METERS = [
  { key: 'inputA', label: 'In A' },
  { key: 'inputB', label: 'In B' },
  { key: 'outputA', label: 'Out A' },
  { key: 'outputB', label: 'Out B' },
];

export function mountMeters(container, { store }) {
  const rows = METERS.map(({ key, label }) => {
    const fill = el('div', { class: 'meter-fill' });
    const valueText = el('span', { class: 'note', style: 'width:4.5rem;text-align:right' }, '0.0000');
    const row = el('div', { class: 'meter', title: 'Linear amplitude; display scale is an approximation, not calibrated to clipping (see PROTOCOL_NOTES.md Open Questions #5).' }, [
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
      const pct = Math.min(100, v * VISUAL_GAIN);
      r.fill.style.width = `${pct}%`;
      r.fill.classList.toggle('hot', pct > 60);
      r.fill.classList.toggle('clip', pct >= 100);
      r.valueText.textContent = v.toFixed(4);
    }
  });
}
