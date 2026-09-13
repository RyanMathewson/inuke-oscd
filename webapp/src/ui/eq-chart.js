// A small read-only SVG frequency-response chart: log-frequency x axis,
// dB y axis, a filled curve, and optional labeled markers (one per band).
// Used by the Parametric EQ, Dynamic EQ, and Filter/Crossover tabs -- see
// curve-math.js for the honesty caveat on what these curves represent.
import { el } from '../utils.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const FREQ_TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function freqToX(f, freqMin, freqMax, width) {
  const t = (Math.log10(f) - Math.log10(freqMin)) / (Math.log10(freqMax) - Math.log10(freqMin));
  return t * width;
}

function dbToY(db, dbMin, dbMax, height) {
  const t = (db - dbMin) / (dbMax - dbMin);
  return height - t * height;
}

export function createEqChart({ dbMin = -15, dbMax = 15, dbStep = 5, freqMin = 20, freqMax = 20000, width = 600, height = 160 } = {}) {
  const clampDb = (db) => Math.max(dbMin, Math.min(dbMax, db));

  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, class: 'eq-chart', preserveAspectRatio: 'none' });

  const grid = svgEl('g', { class: 'eq-chart-grid' });
  for (let db = dbMin; db <= dbMax; db += dbStep) {
    const y = dbToY(db, dbMin, dbMax, height);
    grid.append(svgEl('line', { x1: 0, y1: y, x2: width, y2: y, class: db === 0 ? 'eq-chart-zero' : 'eq-chart-gridline' }));
  }
  for (const f of FREQ_TICKS) {
    if (f < freqMin || f > freqMax) continue;
    const x = freqToX(f, freqMin, freqMax, width);
    grid.append(svgEl('line', { x1: x, y1: 0, x2: x, y2: height, class: 'eq-chart-gridline' }));
  }

  const fillPath = svgEl('path', { class: 'eq-chart-fill' });
  const curvePath = svgEl('path', { class: 'eq-chart-curve' });
  const markersGroup = svgEl('g', { class: 'eq-chart-markers' });

  svg.append(grid, fillPath, curvePath, markersGroup);

  function setCurve(fn, samples = 120) {
    const zeroY = dbToY(0, dbMin, dbMax, height).toFixed(1);
    let d = '';
    for (let i = 0; i < samples; i++) {
      const f = freqMin * (freqMax / freqMin) ** (i / (samples - 1));
      const x = freqToX(f, freqMin, freqMax, width).toFixed(1);
      const y = dbToY(clampDb(fn(f)), dbMin, dbMax, height).toFixed(1);
      d += `${i === 0 ? 'M' : 'L'}${x},${y} `;
    }
    curvePath.setAttribute('d', d.trim());
    fillPath.setAttribute('d', `${d.trim()} L${width},${zeroY} L0,${zeroY} Z`);
  }

  function setMarkers(markers) {
    markersGroup.replaceChildren(
      ...markers.map(({ label, freq, db, disabled }) => {
        const x = freqToX(freq, freqMin, freqMax, width);
        const y = dbToY(clampDb(db), dbMin, dbMax, height);
        const g = svgEl('g', { class: disabled ? 'eq-chart-marker disabled' : 'eq-chart-marker' });
        g.append(
          svgEl('circle', { cx: x, cy: y, r: 8 }),
          Object.assign(svgEl('text', { x, y: y + 3.5, 'text-anchor': 'middle' }), { textContent: String(label) }),
        );
        return g;
      }),
    );
  }

  function labels() {
    const wrap = el('div', { class: 'eq-chart-labels' });
    for (const f of FREQ_TICKS) {
      if (f < freqMin || f > freqMax) continue;
      const x = (freqToX(f, freqMin, freqMax, width) / width) * 100;
      wrap.append(el('span', { style: `left:${x}%` }, f >= 1000 ? `${f / 1000}k` : String(f)));
    }
    return wrap;
  }

  return { svg, setCurve, setMarkers, labelsEl: labels() };
}
