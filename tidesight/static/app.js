const $ = id => document.getElementById(id);
const MINC = 0.2;
let R = null, VID = null, thr = 0.6, QS = '', ORIG = null, RUNS = [], loadedCfg = null, META = null;
let GRID = { on: false, rows: 3, cols: 3 }, lastCount = '';
let DOC = Boxes.emptyDoc(), HIST = Boxes.createHistory(), SEL = null, saveTimer = null, liveActive = false, ED = null;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const htmlEscape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const curModel = () => $('model').value, curRate = () => parseFloat($('sfps').value) || 2;
const M = () => R || META || { duration: 1, fps: 30, width: 16, height: 9 };
const vid = $('vid'), cv = $('cv'), ctx = cv.getContext('2d');

// ---------- setup ----------
fetch('/api/models').then(r => r.json()).then(m => {
  $('model').innerHTML = Object.entries(m).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
});
const drop = $('drop'), file = $('file');
drop.onclick = () => file.click();
file.onchange = () => file.files[0] && start(file.files[0]);
['dragover', 'dragenter'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', ev => ev.dataTransfer.files[0] && start(ev.dataTransfer.files[0]));

function showErr(msg) { $('err').textContent = msg; $('err').classList.toggle('hidden', !msg); }
function setProg(txt, frac) { $('prog').classList.remove('hidden'); $('progtxt').textContent = txt; $('progbar').style.width = (frac * 100) + '%'; }

function start(f) {
  showErr(''); $('review').classList.add('hidden'); R = null; ORIG = null; loadedCfg = null; META = null;
  const fd = new FormData(); fd.append('file', f);
  const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/upload');
  xhr.upload.onprogress = e => e.lengthComputable && setProg(`Adding your video… ${Math.round(e.loaded / e.total * 100)}%`, e.loaded / e.total);
  xhr.onerror = () => showErr('Could not reach the app. Is it still running?');
  xhr.onload = () => {
    if (xhr.status !== 200) return showErr('Upload failed: ' + (xhr.responseText || xhr.status));
    VID = JSON.parse(xhr.responseText).id; enterFilters();
  };
  xhr.send(fd);
}

// Step 2: the video is ready, choose filters BEFORE any detection runs
async function enterFilters() {
  setProg('Getting your video ready to play…', 0.05);
  let p;
  while (true) {
    p = await (await fetch(`/api/prepare/${VID}`)).json();
    if (p.stage === 'error') { $('prog').classList.add('hidden'); return showErr(p.error || 'Could not prepare the video.'); }
    if (p.stage === 'ready') break;
    await sleep(700);
  }
  $('prog').classList.add('hidden');
  META = p; R = null; loadedCfg = null; cv.style.pointerEvents = '';
  $('review').classList.remove('hidden'); $('review').classList.add('stage-filters');
  $('usedNote').textContent = ''; $('dirtyNote').classList.add('hidden');
  $('mdl').textContent = p.name || '';
  $('rerun').textContent = 'Start detection';
  vid.src = `/video/${VID}/${p.playable}`;
  setSliders(DEF);
  setDrawer(true);
  await loadRuns();
}

// ---------- review ----------
function fmt(t, d = 2) { const m = Math.floor(t / 60), sec = t - m * 60; return String(m).padStart(2, '0') + ':' + sec.toFixed(d).padStart(2 + (d ? d + 1 : 0), '0'); }
function load() {
  $('review').classList.remove('hidden'); $('review').classList.remove('stage-filters');
  $('rerun').textContent = 'Re-run detection with these settings';
  applyPlayer();
  cv.style.pointerEvents = 'auto';
  $('mdl').textContent = `${R.model} · ${R.sample_fps} pictures/sec`;
  $('endlab').textContent = Math.round(R.duration) + ' s';
  recompute();
}
const gap = () => 1 / R.sample_fps;
// Boxes that count for the timeline/moments: AI boxes the reviewer has not rejected + the reviewer's own boxes.
function eff(i) {
  return Boxes.boxesAt(R, DOC, i).filter(b => !b.rejected).map(b => ({ conf: b.kind === 'own' ? 1 : b.conf, j: b.j }));
}
const maxOf = arr => arr.reduce((m, b) => Math.max(m, b.conf), 0);
function recompute() {
  // timeline
  const tl = $('tl'); tl.querySelectorAll('.seg').forEach(e => e.remove());
  const g = gap();
  R.samples.forEach((s, i) => {
    const E = eff(i), mc = maxOf(E);
    if (!E.length) return;
    const d = document.createElement('div'); d.className = 'seg ' + (mc >= thr ? 't' : 'a');
    d.style.left = (Math.max(0, s.t - g / 2) / R.duration * 100) + '%';
    d.style.width = Math.max(0.15, g / R.duration * 100) + '%';
    tl.insertBefore(d, $('head'));
  });
  renderReview();
  draw();
}

function drawGrid() {
  const v = videoRect(), r = GRID.rows, c = GRID.cols;
  ctx.save(); ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(255,255,255,.55)'; ctx.fillStyle = 'rgba(255,255,255,.85)';
  ctx.font = '600 12px -apple-system,Segoe UI,sans-serif'; ctx.textBaseline = 'top'; ctx.shadowColor = 'rgba(0,0,0,.8)'; ctx.shadowBlur = 3;
  ctx.setLineDash([6, 4]);
  for (let i = 1; i < r; i++) { const y = v.y + v.h * i / r; ctx.beginPath(); ctx.moveTo(v.x, y); ctx.lineTo(v.x + v.w, y); ctx.stroke(); }
  for (let j = 1; j < c; j++) { const x = v.x + v.w * j / c; ctx.beginPath(); ctx.moveTo(x, v.y); ctx.lineTo(x, v.y + v.h); ctx.stroke(); }
  ctx.setLineDash([]); ctx.strokeRect(v.x, v.y, v.w, v.h);
  for (let i = 0; i < r; i++) for (let j = 0; j < c; j++) ctx.fillText(String.fromCharCode(65 + i) + (j + 1), v.x + v.w * j / c + 5, v.y + v.h * i / r + 4);
  ctx.restore();
}
// How many fish are in the picture on screen (same rule as the report: not rejected, and confident or edited)
function countNow() {
  const i = R ? shownIndex() : -1; if (i < 0) return { n: 0, by: {}, unsure: 0, none: true };
  return Boxes.countedAt(R, DOC, i, thr);
}
function updateCount() {
  if (!R) return;
  const c = countNow(), key = JSON.stringify(c) + thr + DOC.own.length;
  if (key === lastCount) return; lastCount = key;
  $('cntNow').textContent = c.none ? '–' : c.n;
  $('cntWho').textContent = c.none ? '(move the video to a checked picture)' : `(${c.ai} found automatically + ${c.own} added by you)`;
}
function shownIndex() { const t = vid.currentTime || 0, i = nearest(t); return Math.abs(R.samples[i].t - t) <= gap() * 1.01 ? i : -1; }
function shownBoxes(i) { return i < 0 ? [] : Boxes.boxesAt(R, DOC, i); }

function nearest(t) {
  const S = R.samples; let lo = 0, hi = S.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; (S[mid].t <= t) ? lo = mid : hi = mid; }
  return (Math.abs(S[hi].t - t) < Math.abs(S[lo].t - t)) ? hi : lo;
}
function seek(t) { vid.currentTime = Math.max(0, Math.min(M().duration, t)); }

function videoRect() {
  const W = cv.clientWidth, H = cv.clientHeight, vw = vid.videoWidth || M().width, vh = vid.videoHeight || M().height;
  const sc = Math.min(W / vw, H / vh), w = vw * sc, h = vh * sc;
  return { x: (W - w) / 2, y: (H - h) / 2, w, h };
}
function draw() {
  if (!R && !META) return;
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  if (GRID.on) drawGrid();
  const t = vid.currentTime || 0, i = R ? nearest(t) : 0, s = R ? R.samples[i] : null;
  if (R && Math.abs(s.t - t) <= gap() * 1.01) {
    const vr = videoRect(); ctx.font = '600 13px -apple-system,Segoe UI,sans-serif'; ctx.textBaseline = 'top';
    shownBoxes(i).forEach(b => {
      const own = b.kind === 'own', ok = own || b.conf >= thr;
      const col = b.rejected ? '#9aa7ab' : own ? '#3b82f6' : ok ? '#14c4af' : '#f0b429';
      const x = vr.x + b.x1 * vr.w, y = vr.y + b.y1 * vr.h, w = (b.x2 - b.x1) * vr.w, h = (b.y2 - b.y1) * vr.h;
      ctx.lineWidth = 2.5; ctx.strokeStyle = col; ctx.setLineDash(b.rejected ? [6, 4] : []); ctx.strokeRect(x, y, w, h); ctx.setLineDash([]);
      const label = own ? b.label : b.rejected ? `${b.label} · rejected` : `${b.label} ${b.conf.toFixed(2)}${ok ? '' : ' · check'}${b.edited ? ' ✎' : ''}`;
      const tw = ctx.measureText(label).width + 10, ly = y >= 20 ? y - 20 : y + 2;
      ctx.fillStyle = col; ctx.fillRect(x - 1, ly, tw, 18); ctx.fillStyle = b.rejected ? '#fff' : own ? '#fff' : '#06161a'; ctx.fillText(label, x + 4, ly + 3);
      if (b.id === SEL) {   // selected: white outline and drag handles
        ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.strokeRect(x - 3, y - 3, w + 6, h + 6);
        [[x, y], [x + w / 2, y], [x + w, y], [x, y + h / 2], [x + w, y + h / 2], [x, y + h], [x + w / 2, y + h], [x + w, y + h]].forEach(([hx, hy]) => {
          ctx.fillStyle = '#fff'; ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.fillRect(hx - 4, hy - 4, 8, 8); ctx.strokeRect(hx - 4, hy - 4, 8, 8);
        });
      }
    });
    if (ED && ED.draft) {   // the new box being drawn
      const d = ED.draft, x = vr.x + d.x1 * vr.w, y = vr.y + d.y1 * vr.h;
      ctx.lineWidth = 2; ctx.strokeStyle = '#3b82f6'; ctx.setLineDash([5, 4]); ctx.strokeRect(x, y, (d.x2 - d.x1) * vr.w, (d.y2 - d.y1) * vr.h); ctx.setLineDash([]);
    }
  }
  updateCount();
  // readouts
  $('time').textContent = `${fmt(t, 2)} · frame ${Math.round(t * M().fps)}`;
  $('head').style.left = (t / M().duration * 100) + '%';
  if (!scrubbing) $('scrub').value = t / M().duration * 1000;
  if (baOn && baMode() === 'video') { syncPair(); drawPair(); }
  $('play').textContent = vid.paused ? '▶ Play' : '⏸ Pause';
}
let scrubbing = false;
(function loop() { draw(); requestAnimationFrame(loop); })();

$('play').onclick = () => vid.paused ? vid.play() : vid.pause();
vid.onclick = $('play').onclick;
$('scrub').oninput = e => { scrubbing = true; seek(e.target.value / 1000 * M().duration); };
$('scrub').onchange = () => scrubbing = false;
$('tl').onclick = e => { const r = $('tl').getBoundingClientRect(); seek((e.clientX - r.left) / r.width * R.duration); };
$('stepB').onclick = () => { vid.pause(); seek(R.samples[Math.max(0, nearest(vid.currentTime) - 1)].t); };
$('stepF').onclick = () => { vid.pause(); seek(R.samples[Math.min(R.samples.length - 1, nearest(vid.currentTime) + 1)].t); };
$('conf').oninput = e => { thr = parseFloat(e.target.value); $('confv').textContent = thr.toFixed(2); if (R) recompute(); };
window.addEventListener('resize', draw);

// ---------- picture filters ----------
const FILTERS = [
  ['Light', null],
  ['brightness', 'Brightness', -100, 100, 1, 0], ['contrast', 'Contrast', 0.5, 3, 0.05, 1], ['gamma', 'Gamma (lifts dark water)', 0.3, 3, 0.05, 1],
  ['Detail', null],
  ['clahe', 'Local contrast', 0, 10, 0.5, 0], ['denoise', 'Denoise', 0, 20, 1, 0], ['sharpen', 'Sharpen', 0, 3, 0.1, 0],
  ['Colour', null],
  ['saturation', 'Colour strength', 0, 3, 0.05, 1], ['warmth', 'Warmth (brings back reds)', -50, 50, 1, 0],
];
const DEF = {}; FILTERS.forEach(f => { if (f[1]) DEF[f[0]] = f[5]; });
let cfg = { ...DEF };
const isDef = c => Object.keys(DEF).every(k => Math.abs((c[k] ?? DEF[k]) - DEF[k]) < 1e-9);
const cfgParam = c => isDef(c) ? '' : `&cfg=${encodeURIComponent(JSON.stringify(c))}`;
const baseQ = () => `?model=${curModel()}&sample_fps=${curRate()}`;
const sameCfg = (a, b) => Object.keys(DEF).every(k => Math.abs((a[k] ?? DEF[k]) - (b[k] ?? DEF[k])) < 1e-6);

(function buildFilters() {
  const box = $('filters');
  FILTERS.forEach(f => {
    if (!f[1]) { box.insertAdjacentHTML('beforeend', `<div class="fgroup">${f[0]}</div>`); return; }
    const [k, label, mn, mx, st, df] = f;
    box.insertAdjacentHTML('beforeend', `<div class="frow"><label>${label}<b id="fv_${k}">${df}</b></label><input type="range" id="f_${k}" min="${mn}" max="${mx}" step="${st}" value="${df}"></div>`);
    $('f_' + k).oninput = e => { cfg[k] = parseFloat(e.target.value); $('fv_' + k).textContent = cfg[k]; filtersChanged(); };
  });
})();
function setSliders(c) {
  cfg = { ...DEF, ...c };
  Object.keys(DEF).forEach(k => { $('f_' + k).value = cfg[k]; $('fv_' + k).textContent = cfg[k]; });
  filtersChanged();
}
let pvTimer = null;
function dirtyUI() {
  const dirty = !!R && !sameCfg(cfg, loadedCfg || DEF);
  $('dirtyNote').classList.toggle('hidden', !dirty); $('fBadge').classList.toggle('hidden', !dirty);
}
// ---------- side panels (they push the video; they never cover it) ----------
function setDrawer(open) { $('review').classList.toggle('rp-open', open); }          // right: video filters
function setLeft(open) { $('review').classList.toggle('lp-open', open); }            // left: fish lookup
$('fBtn').onclick = () => setDrawer(!$('review').classList.contains('rp-open'));
$('rpRail').onclick = () => setDrawer(true);
$('fClose').onclick = () => setDrawer(false);
$('lpRail').onclick = () => setLeft(true);
$('lpClose').onclick = () => setLeft(false);
$('startBtn').onclick = () => rerun();
function filtersChanged() {
  updateSvg(); applyPlayer();
  dirtyUI();
  clearTimeout(pvTimer); pvTimer = setTimeout(() => { if (baOn) { if (baMode() === 'still') fetchCompare(); else setupPair(); } }, 300);
}
vid.addEventListener('seeked', () => { if (vid.paused && baOn && baMode() === 'still') fetchCompare(); });
vid.addEventListener('pause', () => { if (baOn && baMode() === 'still') fetchCompare(); });

// Quick (approximate) live preview on the playing video via an SVG filter.
// Local contrast and denoise can't be done live; they are in the rendered filtered video.
function updateSvg() {
  const c = { ...DEF, ...cfg }, set = (id, sel, attrs) => document.querySelectorAll(`#${id} ${sel}`).forEach(e => Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)));
  set('vf_bc', '*', { slope: c.contrast, intercept: c.brightness / 255 });
  set('vf_g', '*', { exponent: 1 / c.gamma });
  $('vf_sat').setAttribute('values', c.saturation);
  const f = c.warmth / 100; $('vf_warm').setAttribute('values', `${1 + f} 0 0 0 0  0 1 0 0 0  0 0 ${1 - f} 0 0  0 0 0 1 0`);
  const a = c.sharpen * 0.4; $('vf_sh').setAttribute('kernelMatrix', `0 ${-a} 0 ${-a} ${1 + 4 * a} ${-a} 0 ${-a} 0`);
}
// Which file the player shows: the exact filtered video when the sliders match the results, else the original + quick preview.
function applyPlayer() {
  const exact = !!(R && R.filtered && loadedCfg && sameCfg(cfg, loadedCfg));
  const name = exact ? R.filtered : (R ? R.playable : META && META.playable);
  if (!name) return;
  const want = `/video/${VID}/${name}`;
  if (!vid.src.endsWith(want)) {
    const t = vid.currentTime, paused = vid.paused;
    vid.src = want;
    vid.addEventListener('loadedmetadata', () => { vid.currentTime = t; if (!paused) vid.play(); }, { once: true });
  }
  vid.style.filter = (!exact && !isDef(cfg)) ? 'url(#vf)' : 'none';
}
$('resetF').onclick = () => setSliders(DEF);

// Take a results object as "the results shown"
async function adopt(res, first) {
  R = res; loadedCfg = { ...DEF, ...(res.settings || {}) };
  $('model').value = res.model; $('sfps').value = res.sample_fps;
  QS = `?model=${res.model}&sample_fps=${res.sample_fps}` + cfgParam(loadedCfg);
  if (first) setSliders(loadedCfg); else dirtyUI();
  $('usedNote').innerHTML = `Results shown used: <b>${res.settings_text || 'Original (no changes)'}</b>`;
  if (isDef(loadedCfg)) ORIG = res;
  else if (!ORIG || ORIG.model !== res.model || ORIG.sample_fps !== res.sample_fps) {
    try { const r = await fetch(`/api/results/${VID}?model=${res.model}&sample_fps=${res.sample_fps}`); ORIG = r.ok ? await r.json() : null; } catch { ORIG = null; }
  }
  await loadDoc();
  await loadRuns();
}
async function loadDoc() {
  try { DOC = Boxes.normalizeDoc(await (await fetch(`/api/review/${VID}${QS}`)).json()); } catch { DOC = Boxes.emptyDoc(); }
  HIST = Boxes.createHistory(); SEL = null; liveActive = false;
}
async function loadRuns() {
  RUNS = (await (await fetch(`/api/runs/${VID}`)).json()).filter(r => r.model === curModel() && r.sample_fps === curRate());
  const cur = R ? RUNS.findIndex(r => sameCfg(r.cfg, loadedCfg)) : -1;
  $('runs').innerHTML = `<option value="-1">${RUNS.length ? (R ? '(pick one to switch)' : 'None picked: choose filters below') : 'None yet'}</option>` + RUNS.map((r, i) => `<option value="${i}">${r.text}</option>`).join('');
  $('runs').value = cur;
}
$('runs').onchange = e => { const r = RUNS[+e.target.value]; if (!r) return; setSliders(r.cfg); rerun(); };

async function rerun() {
  const btn = $('rerun'); btn.disabled = true; $('startBtn').disabled = true; setDrawer(true);
  const q = baseQ() + cfgParam(cfg);
  try {
    const r = await (await fetch(`/api/analyse/${VID}${q}`, { method: 'POST' })).json();
    if (!r.cached) {
      $('rrProg').classList.remove('hidden');
      while (true) {
        const s = await (await fetch(`/api/status/${VID}${q}`)).json();
        if (s.stage === 'error') { $('rrTxt').textContent = s.error; return; }
        if (s.stage === 'done') break;
        $('rrTxt').textContent = s.stage === 'rendering' ? `Preparing the filtered video: ${s.done} of ${s.total} frames`
          : s.stage === 'analysing' ? `Analysing ${s.done} of ${s.total} frames`
          : s.stage === 'downloading' ? `Downloading the fish finder (first time only)… ${Math.round((s.dl || 0) * 100)}%` : 'Getting ready…';
        $('rrBar').style.width = (s.stage === 'downloading' ? (s.dl || 0) * 100 : s.total ? s.done / s.total * 100 : 2) + '%';
        await new Promise(r => setTimeout(r, 700));
      }
    }
    const res = await (await fetch(`/api/results/${VID}${q}`)).json();
    await adopt(res, false); load(); setDrawer(false);
  } finally { btn.disabled = false; $('startBtn').disabled = false; $('rrProg').classList.add('hidden'); }
}
$('rerun').onclick = rerun;

// ---------- before / after (still pictures, or two videos that play together) ----------
let baOn = false, baToken = 0, baLast = null;
const baMode = () => document.querySelector('input[name=bam]:checked').value;
const baBoxesOn = () => $('baBoxes').checked;
$('baBtn').onclick = () => {
  baOn = !baOn; $('baBtn').classList.toggle('on', baOn);
  $('baWrap').classList.toggle('hidden', !baOn); $('baBar').classList.toggle('hidden', !baOn); $('stage').classList.toggle('hidden', baOn);
  if (baOn) { vid.pause(); showMode(); }
};
document.querySelectorAll('input[name=bam]').forEach(r => r.onchange = showMode);
function showMode() {
  const v = baMode() === 'video';
  ['baO', 'baE'].forEach(i => $(i).classList.toggle('hidden', v)); ['baOv', 'baEv'].forEach(i => $(i).classList.toggle('hidden', !v));
  if (v) setupPair(); else { $('baNote').textContent = ''; fetchCompare(); }
}
$('baBoxes').onchange = () => { if (baMode() === 'still') { if (baLast) paintStill(); } else drawPair(); };
function setupPair() {
  const exact = !!(R && R.filtered && loadedCfg && sameCfg(cfg, loadedCfg)), orig = R ? R.playable : META && META.playable;
  if (!orig) return;
  const a = `/video/${VID}/${orig}`, b = `/video/${VID}/${exact ? R.filtered : orig}`;
  [['baOv', a], ['baEv', b]].forEach(([id, url]) => { const e = $(id); if (!e.src.endsWith(url)) e.src = url; e.muted = true; });
  $('baOv').style.filter = 'none'; $('baEv').style.filter = (!exact && !isDef(cfg)) ? 'url(#vf)' : 'none';
  $('baNote').textContent = exact ? '' : (isDef(cfg) ? '' : 'Right side is a quick preview. Start detection to get the exact filtered video.');
  $('baEcap').textContent = exact ? 'With your filters' : (isDef(cfg) ? 'With your filters (none yet)' : 'With your filters (quick preview)');
  syncPair(true);
}
// the two videos follow the main player (which still has the play button, scrub bar and step buttons)
function syncPair(force) {
  const t = vid.currentTime || 0;
  [$('baOv'), $('baEv')].forEach(e => {
    if (force || Math.abs(e.currentTime - t) > 0.15) { try { e.currentTime = t; } catch { } }
    if (vid.paused && !e.paused) e.pause(); else if (!vid.paused && e.paused) e.play().catch(() => { });
  });
}
function boxStyle(b, ok) { return b.rejected ? '#9aa7ab' : b.own ? '#3b82f6' : ok ? '#14c4af' : '#f0b429'; }
// boxes: [{x1,y1,x2,y2,label,conf (null = yours),rejected}]
function paintBoxes(cid, el, boxes) {
  const c = $(cid), dpr = window.devicePixelRatio || 1, W = el.clientWidth, H = el.clientHeight;
  if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) { c.width = W * dpr; c.height = H * dpr; }
  const x = c.getContext('2d'); x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, W, H);
  if (!baBoxesOn()) return;
  x.font = '600 12px -apple-system,Segoe UI,sans-serif'; x.textBaseline = 'top';
  boxes.forEach(b => {
    const own = b.conf === null, ok = own || b.conf >= thr, col = boxStyle({ rejected: b.rejected, own }, ok), bx = b.x1 * W, by = b.y1 * H;
    x.lineWidth = 2; x.strokeStyle = col; x.strokeRect(bx, by, (b.x2 - b.x1) * W, (b.y2 - b.y1) * H);
    const l = own ? b.label : `${b.label} ${b.conf.toFixed(2)}${ok ? '' : ' · check'}`, tw = x.measureText(l).width + 8, ly = by >= 18 ? by - 17 : by + 1;
    x.fillStyle = col; x.fillRect(bx - 1, ly, tw, 16); x.fillStyle = '#06161a'; x.fillText(l, bx + 3, ly + 2);
  });
}
function drawPair() {
  if (!baOn || baMode() !== 'video') return;
  let bs = [];
  if (R) { const i = shownIndex(); bs = shownBoxes(i).filter(b => !b.rejected).map(b => ({ x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2, label: b.label, conf: b.kind === 'own' ? null : b.conf })); }
  paintBoxes('baOc', $('baOv'), bs); paintBoxes('baEc', $('baEv'), bs);
}
async function fetchCompare() {
  const tok = ++baToken, t = vid.currentTime || 0;
  $('baBtn').textContent = '◧ Working…';
  try {
    const r = await fetch(`/api/compare/${VID}?t=${t.toFixed(3)}&model=${curModel()}${cfgParam(cfg)}`);
    if (!r.ok || tok !== baToken) return;
    const d = await r.json();
    await Promise.all([['baO', d.original], ['baE', d.enhanced]].map(([i, x]) => new Promise(res => { const im = $(i); im.onload = res; im.src = x.img; })));
    baLast = d; paintStill();
  } finally { if (tok === baToken) $('baBtn').textContent = '◧ Before / after'; }
}
function paintStill() {
  const conv = x => x.boxes.map(b => ({ x1: b[0], y1: b[1], x2: b[2], y2: b[3], label: 'Fish', conf: b[4] }));
  paintBoxes('baOc', $('baO'), conv(baLast.original)); paintBoxes('baEc', $('baE'), conv(baLast.enhanced));
}


// ======================= reviewer edits: rename / move / resize / delete =======================
function afterEdit(save = true) {
  if (save) scheduleSave();
  recompute();
}
function scheduleSave() { clearTimeout(saveTimer); $('saveNote').textContent = 'Saving…'; saveTimer = setTimeout(saveNow, 400); }
async function saveNow() {
  clearTimeout(saveTimer); saveTimer = null;
  try {
    await fetch(`/api/review/${VID}${QS}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(DOC), keepalive: true });
    $('saveNote').textContent = 'All changes saved ✓';
  } catch { $('saveNote').textContent = 'Could not save. Is the app still running?'; }
}
window.addEventListener('pagehide', () => { if (saveTimer) saveNow(); });
document.addEventListener('visibilitychange', () => { if (document.hidden && saveTimer) saveNow(); });

function edit(fn) { HIST.push(DOC); fn(); afterEdit(); }
function selBox() { return SEL ? Boxes.findBox(R, DOC, SEL) : null; }
function select(id, jump) {
  SEL = id; const b = selBox();
  if (jump && b) { vid.pause(); seek(R.samples[b.i].t); }
  renderSel(); draw();
}
function deleteSelected() {
  const b = selBox(); if (!b) return;
  if (b.kind === 'own') edit(() => { Boxes.deleteOwn(DOC, b.id); SEL = null; });
  else if (!b.rejected) edit(() => Boxes.rejectAI(R, DOC, b.id));
}
function doUndo() { const d = HIST.undo(); if (!d) return; DOC = d; if (SEL && !selBox()) SEL = null; afterEdit(); }

ED = BoxEditor.createEditor({
  canvas: cv,
  getRect: videoRect,
  getBoxes: () => (R ? shownBoxes(shownIndex()) : []),
  getSelected: () => SEL,
  setSelected: id => select(id, false),
  enabled: () => !!R && !baOn,
  onDrawStart: () => vid.pause(),
  onAdd: r => { const i = shownIndex(); if (i < 0) return; let id; edit(() => { id = Boxes.addOwn(DOC, i, r, 'fish'); }); select(id, false); },
  onChange: (id, r, final) => {
    if (!liveActive) { HIST.push(DOC); liveActive = true; }
    Boxes.patchBox(R, DOC, id, r);
    if (final) { liveActive = false; afterEdit(); renderSel(); }
  },
  onDelete: deleteSelected,
  onNudge: (id, dx, dy) => { const b = selBox(); if (!b) return; edit(() => Boxes.patchBox(R, DOC, id, Boxes.moveRect(b, dx, dy))); },
  onUndo: doUndo,
});

$('undoBtn').onclick = doUndo;
$('delBtn').onclick = deleteSelected;
$('restoreBtn').onclick = () => { const b = selBox(); if (b) edit(() => Boxes.restoreAI(R, DOC, b.id)); };
$('resetBtn').onclick = () => { const b = selBox(); if (b) edit(() => Boxes.resetAI(R, DOC, b.id)); };
function commitName() {
  const b = selBox(); if (!b) return; const v = $('nameIn').value.trim() || Boxes.DEFAULT;
  if (v !== b.label) edit(() => Boxes.patchBox(R, DOC, b.id, { label: v }));
  $('nameIn').value = v;
}
$('nameIn').addEventListener('change', commitName);
$('nameIn').addEventListener('keydown', e => { if (e.key === 'Enter') { commitName(); $('nameIn').blur(); } if (e.key === 'Escape') { $('nameIn').value = (selBox() || {}).label || ''; $('nameIn').blur(); } });

function renderSel() {
  const b = selBox(), inp = $('nameIn');
  $('selbox').classList.toggle('on', !!b);
  inp.disabled = !b;
  if (!b) { inp.value = ''; $('selInfo').textContent = 'Click a box to select it, then drag to move it or drag its handles to resize. Drag on an empty part of the picture to draw a new box.'; }
  else {
    if (document.activeElement !== inp) inp.value = b.label;
    $('selInfo').textContent = b.kind === 'own' ? 'Your box' : `AI box · confidence ${b.conf.toFixed(2)}${b.edited ? ' · edited' : ''}${b.rejected ? ' · rejected' : ''}`;
  }
  $('labelList').innerHTML = Boxes.labelSuggestions(R, DOC).map(l => `<option value="${l.replace(/"/g, '&quot;')}">`).join('');
  $('delBtn').classList.toggle('hidden', !b || b.rejected); $('delBtn').textContent = b && b.kind === 'ai' ? 'Delete AI box' : 'Delete box';
  $('restoreBtn').classList.toggle('hidden', !(b && b.rejected));
  $('resetBtn').classList.toggle('hidden', !(b && b.kind === 'ai' && b.edited));
  $('undoBtn').disabled = HIST.size === 0;
  renderLookup();
}

function renderReview() {
  if (!R) return;
  lastCount = '';
  renderSel();
  const all = Boxes.allBoxes(R, DOC);
  // one tick per box; click = jump to it and select it
  $('ticks').innerHTML = all.map(b => {
    const cls = b.rejected ? 'rej' : b.kind === 'own' ? 'own' : (b.conf >= thr ? 'ai' : 'low') + (b.edited ? ' ed' : '');
    return `<i class="tick ${cls}${b.id === SEL ? ' sel' : ''}" data-id="${b.id}" style="left:${R.samples[b.i].t / R.duration * 100}%" title="${b.label}"></i>`;
  }).join('');
  // list (filtered by the boxes filters)
  const onlyEdited = $('fEdited').checked, showRej = $('fRejected').checked;
  let rows = all.filter(b => b.kind === 'own' || b.edited || (b.rejected ? showRej : b.conf >= thr));
  if (!showRej) rows = rows.filter(b => !b.rejected);
  if (onlyEdited) rows = rows.filter(b => b.edited);
  const minC = parseFloat($('fConf').value), t0 = parseTime($('fFrom').value), t1 = parseTime($('fTo').value);
  if (!isNaN(minC)) rows = rows.filter(b => b.kind === 'own' || (b.conf !== null && b.conf >= minC));
  if (t0 !== null) rows = rows.filter(b => R.samples[b.i].t >= t0);
  if (t1 !== null) rows = rows.filter(b => R.samples[b.i].t <= t1);
  if ($('fSort').value === 'conf') rows.sort((a, b) => (b.conf ?? 2) - (a.conf ?? 2) || R.samples[a.i].t - R.samples[b.i].t);
  else rows.sort((a, b) => R.samples[a.i].t - R.samples[b.i].t);
  const total = rows.length, cap = parseInt($('fRows').value, 10); if (cap && rows.length > cap) rows = rows.slice(0, cap);
  $('boxList').innerHTML = rows.length ? `<table class="bt"><tr><th>Time</th><th>Species</th><th>Who</th><th>Confidence</th><th></th></tr>` + rows.map(b =>
    `<tr data-id="${b.id}" class="${b.id === SEL ? 'sel' : ''}"><td><button type="button" class="box-time" data-jump="${b.id}" aria-label="Jump to fish at ${fmt(R.samples[b.i].t, 1)}">${fmt(R.samples[b.i].t, 1)}</button></td><td><input class="species-input" type="text" data-species="${b.id}" value="${htmlEscape(b.label)}" aria-label="Species"></td><td>${b.kind === 'own' ? 'Me' : 'Auto'}</td><td>${b.conf === null ? '–' : b.conf.toFixed(2)}</td><td>${b.edited ? '✎ edited ' : ''}${b.rejected ? 'rejected' : ''}</td></tr>`).join('') + `</table><p class="note">Showing ${rows.length} of ${total} box${total === 1 ? '' : 'es'}.</p>`
    : '<p class="note">No boxes match these filters.</p>';
}
// "1:30", "90" or "" -> seconds (null = not set)
function parseTime(v) {
  v = String(v || '').trim(); if (!v) return null;
  const p = v.split(':').map(Number); if (p.some(isNaN)) return null;
  return p.reduce((a, x) => a * 60 + x, 0);
}
$('ticks').addEventListener('click', e => { const t = e.target.closest('.tick'); if (t) select(t.dataset.id, true); });
$('boxList').addEventListener('click', e => {
  const time = e.target.closest('.box-time');
  if (time) {
    e.stopPropagation();
    select(time.dataset.jump, true);
    $('stage').scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }
  if (e.target.closest('.species-input')) return;
  const r = e.target.closest('tr[data-id]'); if (r) select(r.dataset.id, true);
});
$('boxList').addEventListener('change', e => {
  const input = e.target.closest('.species-input'); if (!input) return;
  const b = Boxes.findBox(R, DOC, input.dataset.species); if (!b) return;
  const label = input.value.trim() || Boxes.DEFAULT;
  if (label !== b.label) edit(() => Boxes.patchBox(R, DOC, b.id, { label }));
  else input.value = label;
});
['fEdited', 'fRejected', 'fRows', 'fConf', 'fFrom', 'fTo', 'fSort'].forEach(id => { $(id).onchange = renderReview; $(id).oninput = renderReview; });

// ---------- reports and the outlined video ----------
$('expBtn').onclick = async () => {
  await saveNow(); $('expMsg').textContent = 'Saving the report…';
  const r = await (await fetch(`/api/export/${VID}${QS}&thr=${thr}&rows=${GRID.rows}&cols=${GRID.cols}`, { method: 'POST' })).json();
  $('expMsg').innerHTML = `Saved in <code>${r.folder}</code><br>` + r.files.filter(f => f.endsWith('.csv')).map(f => `<a href="/download/${VID}/${f}">${f}</a>`).join(' · ');
};
$('olBtn').onclick = async () => {
  await saveNow(); const b = $('olBtn'); b.disabled = true;
  try {
    await fetch(`/api/outline/${VID}${QS}&thr=${thr}`, { method: 'POST' });
    while (true) {
      const s = await (await fetch(`/api/outline_status/${VID}${QS}`)).json();
      if (s.stage === 'error') { $('olMsg').textContent = s.error; return; }
      if (s.stage === 'done') { $('olMsg').innerHTML = `Done. <a href="/download/${VID}/outlined.mp4">Download the outlined video</a>`; return; }
      $('olMsg').textContent = `Drawing the boxes on the video: ${s.done} of ${s.total} frames`; await sleep(800);
    }
  } finally { b.disabled = false; }
};

// ---------- grid overlay (in the filters drawer) ----------
function gridChanged() {
  GRID.on = $('gridOn').checked;
  GRID.rows = Math.min(12, Math.max(1, parseInt($('gridRows').value) || 3)); GRID.cols = Math.min(12, Math.max(1, parseInt($('gridCols').value) || 3));
  if (R) renderReview(); draw();
}
['gridOn', 'gridRows', 'gridCols'].forEach(id => $(id).addEventListener('input', gridChanged));


// ======================= fish lookup: closest fish in fishmorph_clean.csv =======================
const FMSTEP = { MBl: 1, BEl: 1, CPt: 1 };      // whole numbers for these, tenths for the rest
let FM = null, lookupFor = null;
const FMVALS = {}, FMRES = {};     // remembered per box while this page is open
fetch('/api/fishmorph/info').then(r => r.json()).then(i => { FM = i; buildLookup(); renderLookup(); }).catch(() => { FM = { available: false }; });
const fnum = v => (Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 100) / 100);
function buildLookup() {
  if (!FM || !FM.available) return;
  if (FM.images) $('fmPics').textContent = `Pictures are shown for ${FM.images.toLocaleString()} of the ${FM.rows.toLocaleString()} fish (they load from the internet).`;
  $('srchGrid').innerHTML = FM.traits.map(t => `<label class="fmrow" title="${t.name}: ${t.hint}"><span><b>${t.code}</b> <small>${t.name}</small></span><input type="number" min="0" step="${FMSTEP[t.code] || 0.1}" data-code="${t.code}" placeholder="e.g. ${fnum(t.median)}"></label>`).join('');
  $('srchGrid').querySelectorAll('input').forEach(inp => inp.addEventListener('input', () => {
    if (!lookupFor) return; (FMVALS[lookupFor] = FMVALS[lookupFor] || {})[inp.dataset.code] = inp.value;
  }));
}
function renderLookup() {
  const b = R ? selBox() : null, ok = !!(FM && FM.available);
  $('srchBtn').disabled = !b || !ok;
  $('lpSel').innerHTML = FM && !FM.available ? 'The fish list <code>fishmorph_clean.csv</code> was not found in the tidesight folder.'
    : b ? `Selected: <b>${b.label.replace(/</g, '&lt;')}</b> · ${fmt(R.samples[b.i].t, 1)} ${b.kind === 'ai' ? `· AI confidence ${b.conf.toFixed(2)}` : '· your box'}`
    : 'Click a fish box on the video to select it, then press Search fish.';
  const id = b ? b.id : null;
  if (id !== lookupFor) {               // a different box was selected: show its own numbers and results
    lookupFor = id;
    const v = (id && FMVALS[id]) || {};
    $('srchGrid').querySelectorAll('input').forEach(inp => { inp.value = v[inp.dataset.code] || ''; });
    $('srchMsg').classList.add('hidden');
    showResults(id ? FMRES[id] : null);
    if (!id) $('srchForm').classList.add('hidden');
  }
}
$('srchBtn').onclick = () => $('srchForm').classList.toggle('hidden');
$('srchClear').onclick = () => { $('srchGrid').querySelectorAll('input').forEach(i => { i.value = ''; }); if (lookupFor) { FMVALS[lookupFor] = {}; FMRES[lookupFor] = null; } showResults(null); $('srchMsg').classList.add('hidden'); };
$('srchGo').onclick = async () => {
  if (!lookupFor) return;
  const values = {}; $('srchGrid').querySelectorAll('input').forEach(i => { if (i.value !== '') values[i.dataset.code] = parseFloat(i.value); });
  const msg = $('srchMsg'); msg.classList.add('hidden');
  const r = await fetch('/api/fishmorph/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ values, k: 5 }) });
  if (!r.ok) { let t = ''; try { t = (await r.json()).detail; } catch { } msg.textContent = t || 'Search failed.'; msg.classList.remove('hidden'); return; }
  const res = (await r.json()).results; FMRES[lookupFor] = res; showResults(res);
};
const safeUrl = u => (/^https?:\/\//i.test(u || '') ? htmlEscape(u) : '');
function showResults(res) {
  const el = $('srchRes');
  if (!res) { el.innerHTML = ''; return; }
  if (!res.length) { el.innerHTML = '<p class="note">No fish had enough of those measurements to compare. Try fewer numbers.</p>'; return; }
  el.innerHTML = '<p class="note"><b>Closest fish</b> (a lower difference is a closer match)</p>' + res.map((m, k) => {
    const im = m.image, big = im && safeUrl(im.url);
    const pic = big
      ? `<a class="fmpic" href="${big}" target="_blank" rel="noopener noreferrer" title="Open the larger picture"><img src="${big}" data-thumb="${safeUrl(im.thumb)}" alt="${htmlEscape(m.species)}" loading="lazy" referrerpolicy="no-referrer"></a>`
      : '<div class="fmpic none">No picture available</div>';
    const page = im && safeUrl(im.page);
    const credit = im ? `<div class="fmcredit">Photo: ${htmlEscape(im.credit || 'credit not given')}${im.license ? ` · ${htmlEscape(im.license)}` : ''}${page ? ` · <a href="${page}" target="_blank" rel="noopener noreferrer">${htmlEscape(im.source || 'source')} ↗</a>` : ''}</div>` : '';
    return `<div class="fmres">${pic}<b>${k + 1}. <i>${htmlEscape(m.species)}</i></b><div class="note">${htmlEscape(m.family)} · ${htmlEscape(m.order)}</div>
     <div class="note">Difference <b>${m.difference.toFixed(2)}</b> · compared ${m.compared} of the ${m.typed} number${m.typed === 1 ? '' : 's'} you typed</div>
     <div class="fmvals">${Object.entries(m.values).map(([c, v]) => `${c} ${v === null ? '–' : fnum(v)}`).join(' · ')}</div>${credit}
     <button data-name="${htmlEscape(m.species)}">Use as this box’s species</button></div>`;
  }).join('');
}
// a picture that fails to load: try the small version, then show a plain "no picture" box (error events do not bubble, so capture them)
$('srchRes').addEventListener('error', e => {
  const img = e.target; if (!img || img.tagName !== 'IMG') return;
  if (!img.dataset.tried && img.dataset.thumb && img.src !== img.dataset.thumb) { img.dataset.tried = '1'; img.src = img.dataset.thumb; return; }
  const box = document.createElement('div'); box.className = 'fmpic none'; box.textContent = 'Picture could not be loaded';
  (img.closest('a') || img).replaceWith(box);
}, true);
$('srchRes').addEventListener('click', e => {
  const b = e.target.closest('button[data-name]'); if (!b || !SEL) return;
  const name = b.dataset.name; edit(() => Boxes.patchBox(R, DOC, SEL, { label: name })); renderSel();
});
