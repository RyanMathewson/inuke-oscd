// A small read-only SVG frequency-response chart: log-frequency x axis,
// dB y axis, a filled curve, and optional labeled markers (one per band).
// Used by the Parametric EQ, Dynamic EQ, and Filter/Crossover tabs -- see
// curve-math.js for the honesty caveat on what these curves represent.
//
// The SVG's viewBox is kept exactly matched to its actual rendered pixel
// size via ResizeObserver, rather than stretching a fixed-size coordinate
// grid with preserveAspectRatio="none" -- the latter distorts circular
// markers into ellipses whenever the rendered box's aspect ratio drifts
// from the viewBox's (which it does routinely here, since these charts are
// full-width and the page is responsive).
import { el } from '../utils.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const FREQ_TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

export function createEqChart({ dbMin = -15, dbMax = 15, dbStep = 5, freqMin = 20, freqMax = 20000 } = {}) {
  const clampDb = (db) => Math.max(dbMin, Math.min(dbMax, db));

  let width = 600; // fallback until the first ResizeObserver callback fires
  let height = 160;
  const freqToX = (f) => {
    const t = (Math.log10(f) - Math.log10(freqMin)) / (Math.log10(freqMax) - Math.log10(freqMin));
    return t * width;
  };
  const dbToY = (db) => {
    const t = (db - dbMin) / (dbMax - dbMin);
    return height - t * height;
  };

  const svg = svgEl('svg', { class: 'eq-chart', viewBox: `0 0 ${width} ${height}` });
  const grid = svgEl('g', { class: 'eq-chart-grid' });
  const fillPath = svgEl('path', { class: 'eq-chart-fill' });
  const curvePath = svgEl('path', { class: 'eq-chart-curve' });
  const markersGroup = svgEl('g', { class: 'eq-chart-markers' });
  svg.append(grid, fillPath, curvePath, markersGroup);

  let lastCurveFn = () => 0;
  let lastMarkers = [];

  function drawGrid() {
    grid.replaceChildren();
    for (let db = dbMin; db <= dbMax; db += dbStep) {
      const y = dbToY(db);
      grid.append(svgEl('line', { x1: 0, y1: y, x2: width, y2: y, class: db === 0 ? 'eq-chart-zero' : 'eq-chart-gridline' }));
    }
    for (const f of FREQ_TICKS) {
      if (f < freqMin || f > freqMax) continue;
      const x = freqToX(f);
      grid.append(svgEl('line', { x1: x, y1: 0, x2: x, y2: height, class: 'eq-chart-gridline' }));
    }
  }

  function drawCurve(fn, samples = 120) {
    const zeroY = dbToY(0).toFixed(1);
    let d = '';
    for (let i = 0; i < samples; i++) {
      const f = freqMin * (freqMax / freqMin) ** (i / (samples - 1));
      const x = freqToX(f).toFixed(1);
      const y = dbToY(clampDb(fn(f))).toFixed(1);
      d += `${i === 0 ? 'M' : 'L'}${x},${y} `;
    }
    curvePath.setAttribute('d', d.trim());
    fillPath.setAttribute('d', `${d.trim()} L${width},${zeroY} L0,${zeroY} Z`);
  }

  function drawMarkers(markers) {
    markersGroup.replaceChildren(
      ...markers.map(({ label, freq, db, disabled }) => {
        const x = freqToX(freq);
        const y = dbToY(clampDb(db));
        const g = svgEl('g', { class: disabled ? 'eq-chart-marker disabled' : 'eq-chart-marker' });
        g.append(
          svgEl('circle', { cx: x, cy: y, r: 8 }),
          Object.assign(svgEl('text', { x, y: y + 3.5, 'text-anchor': 'middle' }), { textContent: String(label) }),
        );
        return g;
      }),
    );
  }

  function redraw() {
    drawGrid();
    drawCurve(lastCurveFn);
    drawMarkers(lastMarkers);
  }

  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      if (rect.width < 1 || rect.height < 1) return;
      width = rect.width;
      height = rect.height;
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      redraw();
    }).observe(svg);
  }

  function setCurve(fn, samples) {
    lastCurveFn = fn;
    drawCurve(fn, samples);
  }

  function setMarkers(markers) {
    lastMarkers = markers;
    drawMarkers(markers);
  }

  function labels() {
    // Positioned by percentage, so these don't need the real pixel width.
    const wrap = el('div', { class: 'eq-chart-labels' });
    for (const f of FREQ_TICKS) {
      if (f < freqMin || f > freqMax) continue;
      const t = ((Math.log10(f) - Math.log10(freqMin)) / (Math.log10(freqMax) - Math.log10(freqMin))) * 100;
      wrap.append(el('span', { style: `left:${t}%` }, f >= 1000 ? `${f / 1000}k` : String(f)));
    }
    return wrap;
  }

  drawGrid();
  return { svg, setCurve, setMarkers, labelsEl: labels() };
}
