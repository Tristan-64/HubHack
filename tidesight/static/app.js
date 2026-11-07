const $ = id => document.getElementById(id);
const MINC = 0.2;
let R = null, VID = null, momentsList = [], thr = 0.6, cutoff = 0.5, SP = { available: false, byLatin: {}, generic: 'Actinopterygii', minPx: 40 }, QS = '', ORIG = null, RUNS = [], loadedCfg = null, META = null;
let DOC = Boxes.emptyDoc(), HIST = Boxes.createHistory(), SEL = null, saveTimer = null, liveActive = false, ED = null;
const sleep = ms => new Promise(r => setTimeout(r, ms));
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
  showErr(''); $('review').classList.add('hidden'); R = null; ORIG = null; loadedCfg = null; META = null; momentsList = [];
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
  $('sLen').textContent = fmt(R.duration, 0);
  $('sName').textContent = R.name || '–';
  $('endlab').textContent = Math.round(R.duration) + ' s';
  recompute();
}
const gap = () => 1 / R.sample_fps;
// Species suggestion for one box: null = not analysed, else {name, score, maybeNew}
function speciesFor(s, j) {
  const e = (s.sp || {})[j]; if (!e) return null;
  const b = s.boxes[j], px = Math.min((b[2] - b[0]) * R.width, (b[3] - b[1]) * R.height);
  if (!e.length || px < SP.minPx) return { name: 'Unknown', score: 0, why: 'too small' };
  const [lab, sc] = e[0];
  if (lab === SP.generic) return { name: 'Unknown', score: sc, why: 'possibly not on the species list', maybeNew: true };
  if (sc < cutoff) return { name: 'Unknown', score: sc, why: 'not sure' };
  return { name: SP.byLatin[lab] || lab, score: sc };
}
// Boxes that count for the timeline/moments: AI boxes the reviewer has not rejected + the reviewer's own boxes.
function eff(i) {
  return Boxes.boxesAt(R, DOC, i).filter(b => !b.rejected).map(b => ({ conf: b.kind === 'own' ? 1 : b.conf, j: b.j }));
}
const maxOf = arr => arr.reduce((m, b) => Math.max(m, b.conf), 0);
function recompute() {
  // timeline
  const tl = $('tl'); tl.querySelectorAll('.seg').forEach(e => e.remove());
  const g = gap(); let skipped = 0;
  R.samples.forEach((s, i) => {
    const E = eff(i), mc = maxOf(E);
    if (!E.length) { skipped += g; return; }
    const d = document.createElement('div'); d.className = 'seg ' + (mc >= thr ? 't' : 'a');
    d.style.left = (Math.max(0, s.t - g / 2) / R.duration * 100) + '%';
    d.style.width = Math.max(0.15, g / R.duration * 100) + '%';
    tl.insertBefore(d, $('head'));
  });
  $('sSkip').textContent = Math.round(Math.min(100, skipped / R.duration * 100)) + '%';
  // moments
  momentsList = []; let cur = null; const tally = {}; let newish = 0;
  R.samples.forEach((s, i) => {
    const E = eff(i), n = E.filter(b => b.conf >= thr).length;
    if (n) {
      if (cur && cur.end === i - 1) { cur.end = i; cur.max = Math.max(cur.max, n); cur.top = Math.max(cur.top, maxOf(E)); }
      else { cur = { start: i, end: i, max: n, top: maxOf(E), sp: {} }; momentsList.push(cur); }
      E.forEach(b => { if (b.conf < thr || b.j === null) return; const j = b.j, sp = speciesFor(s, j); if (sp) { cur.sp[sp.name] = (cur.sp[sp.name] || 0) + 1; tally[sp.name] = (tally[sp.name] || 0) + 1; if (sp.maybeNew) newish++; } });
    }
  });
  $('sMom').textContent = momentsList.length;
  renderCompare();
  renderSummary(tally, newish);
  renderReview();
  const el = $('moments');
  el.innerHTML = momentsList.length ? '' : '<p class="note">No fish at this confidence. Try moving the slider to the left.</p>';
  momentsList.forEach((m, k) => {
    const t0 = R.samples[m.start].t, dur = (m.end - m.start) * gap() + gap();
    const r = document.createElement('div'); r.className = 'row'; r.dataset.k = k;
    r.innerHTML = `<i class="dot"></i><b>${fmt(t0, 1)}</b><span>·</span>${dur.toFixed(1)} s<span>·</span>up to ${m.max} fish<span>·</span>top ${m.top.toFixed(2)}${mostly(m)}`;
    r.onclick = () => { vid.pause(); seek(t0); };
    el.appendChild(r);
  });
  draw();
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
  const t = vid.currentTime || 0, i = R ? nearest(t) : 0, s = R ? R.samples[i] : null;
  if (R && Math.abs(s.t - t) <= gap() * 1.01) {
    const vr = videoRect(); ctx.font = '600 13px -apple-system,Segoe UI,sans-serif'; ctx.textBaseline = 'top';
    shownBoxes(i).forEach(b => {
      const own = b.kind === 'own', ok = own || b.conf >= thr;
      const col = b.rejected ? '#9aa7ab' : own ? '#3b82f6' : ok ? '#14c4af' : '#f0b429';
      const x = vr.x + b.x1 * vr.w, y = vr.y + b.y1 * vr.h, w = (b.x2 - b.x1) * vr.w, h = (b.y2 - b.y1) * vr.h;
      ctx.lineWidth = 2.5; ctx.strokeStyle = col; ctx.setLineDash(b.rejected ? [6, 4] : []); ctx.strokeRect(x, y, w, h); ctx.setLineDash([]);
      const sp = !own && !b.rejected ? speciesFor(s, b.j) : null, spt = sp ? (sp.name === 'Unknown' ? ' · Unknown' : ` · ${sp.name} ${sp.score.toFixed(2)}`) : '';
      const label = own ? b.label : b.rejected ? `${b.label} · rejected` : `${b.label} ${b.conf.toFixed(2)}${ok ? '' : ' · check'}${b.edited ? ' ✎' : ''}${spt}`;
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
  // readouts
  $('time').textContent = `${fmt(t, 2)} · frame ${Math.round(t * M().fps)}`;
  $('head').style.left = (t / M().duration * 100) + '%';
  if (!scrubbing) $('scrub').value = t / M().duration * 1000;
  const k = momentsList.findIndex(m => i >= m.start && i <= m.end);
  document.querySelectorAll('#moments .row').forEach(r => r.classList.toggle('on', +r.dataset.k === k));
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
$('nextFish').onclick = () => {
  const i = nearest(vid.currentTime), m = momentsList.find(x => x.start > i);
  if (m) { vid.pause(); seek(R.samples[m.start].t); }
};
$('prevFish').onclick = () => {
  const i = nearest(vid.currentTime), inside = momentsList.find(x => i > x.start && i <= x.end);
  const before = momentsList.filter(x => x.start < i);
  const m = inside || before[before.length - 1];
  if (m) { vid.pause(); seek(R.samples[m.start].t); }
};
$('conf').oninput = e => { thr = parseFloat(e.target.value); $('confv').textContent = thr.toFixed(2); if (R) recompute(); };
window.addEventListener('resize', draw);

function mostly(m) {
  const named = Object.entries(m.sp).sort((a, b) => b[1] - a[1]);
  if (!named.length) return '';
  const pick = named.find(([n]) => n !== 'Unknown') || named[0];
  return `<span>·</span>mostly ${pick[0] === 'Unknown' ? 'Unknown' : pick[0]} <span>(AI suggestion)</span>`;
}
function renderSummary(tally, newish) {
  const ents = Object.entries(tally).sort((a, b) => (a[0] === 'Unknown') - (b[0] === 'Unknown') || b[1] - a[1]);
  $('spSum').classList.toggle('hidden', !ents.length);
  $('spChips').innerHTML = ents.map(([n, c]) => `<span class="chip ${n === 'Unknown' ? 'unk' : ''}">${n}<b>${c}</b>${n === 'Unknown' && newish ? ` <small>(${newish} possibly not on our list)</small>` : ''}</span>`).join('');
}

// ---------- species suggestions ----------
fetch('/api/species/info').then(r => r.json()).then(i => {
  SP.available = i.available; SP.generic = i.generic; SP.minPx = i.min_box_px;
  i.species.forEach(x => SP.byLatin[x.scientific] = x.common);
  if (!i.available) {
    $('spBtn').disabled = true;
    $('spMsg').innerHTML = 'Species suggestions need an extra install. Stop the app, run <code>pip install -r requirements-ai.txt</code>, then start it again.';
  } else $('spMsg').textContent = 'The first time you use this it downloads the species model (a large file) and needs internet.';
});
$('spBtn').onclick = e => { e.stopPropagation(); if (!$('spBtn').disabled) $('spMenu').classList.toggle('hidden'); };
document.addEventListener('click', () => $('spMenu').classList.add('hidden'));
$('spFrame').onclick = () => { vid.pause(); runSpecies(nearest(vid.currentTime)); };
$('spAll').onclick = () => runSpecies(-1);
async function runSpecies(sample) {
  $('spMsg').textContent = ''; $('spProg').classList.remove('hidden');
  $('spProgTxt').textContent = 'Getting the species model ready…'; $('spBar').style.width = '2%';
  const r = await fetch(`/api/species/${VID}${QS}&conf=${thr}&sample=${sample}`, { method: 'POST' });
  if (!r.ok) { $('spProg').classList.add('hidden'); $('spMsg').textContent = 'Could not start: ' + (await r.text()); return; }
  while (true) {
    const s = await (await fetch(`/api/species_status/${VID}${QS}`)).json();
    if (s.stage === 'error') { $('spProg').classList.add('hidden'); $('spMsg').innerHTML = `<span style="color:#b3261e">${s.error}</span>`; return; }
    if (s.stage === 'done') break;
    if (s.stage === 'analysing') { $('spProgTxt').textContent = `Identifying fish in picture ${s.done} of ${s.total}`; $('spBar').style.width = (s.total ? s.done / s.total * 100 : 0) + '%'; }
    await new Promise(r => setTimeout(r, 600));
  }
  R = await (await fetch(`/api/results/${VID}${QS}`)).json();
  $('spProg').classList.add('hidden');
  $('spMsg').textContent = sample < 0 ? 'Done. Species were suggested for fish at or above the confidence you had set.' : 'Done for this picture.';
  recompute();
}
$('cut').oninput = e => { cutoff = parseFloat(e.target.value); $('cutv').textContent = cutoff.toFixed(2); if (R) recompute(); };


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
// ---------- filter drawer ----------
function setDrawer(open) {
  $('side').classList.toggle('open', open); $('fTab').classList.toggle('hide', open); $('scrim').classList.toggle('hidden', !open);
}
$('fBtn').onclick = () => setDrawer(!$('side').classList.contains('open'));
$('fTab').onclick = () => setDrawer(true);
$('fClose').onclick = () => setDrawer(false);
$('scrim').onclick = () => setDrawer(false);
document.addEventListener('keydown', e => { if (e.key === 'Escape') setDrawer(false); });
$('startBtn').onclick = () => rerun();
function filtersChanged() {
  updateSvg(); applyPlayer();
  dirtyUI();
  clearTimeout(pvTimer); pvTimer = setTimeout(() => { if (baOn) fetchCompare(); }, 300);
}
vid.addEventListener('seeked', () => { if (vid.paused && baOn) fetchCompare(); });
vid.addEventListener('pause', () => { if (baOn) fetchCompare(); });

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

// ---------- comparison line ----------
function momentsFor(res, t, withEdits) {
  let moments = 0, boxes = 0, prev = false;
  res.samples.forEach((s, i) => {
    const n = withEdits ? eff(i).filter(b => b.conf >= t).length : s.boxes.filter(b => b[4] >= t).length; boxes += n;
    if (n && !prev) moments++; prev = n > 0;
  });
  return { moments, boxes };
}
function renderCompare() {
  if (!R) return;
  const f = x => `${x.moments} fish moment${x.moments === 1 ? '' : 's'}, ${x.boxes} boxes above ${thr.toFixed(2)}`;
  const cur = momentsFor(R, thr, true);
  if (!ORIG || ORIG === R) { $('cmp').innerHTML = `<b>Original (no filters):</b> ${f(cur)}`; return; }
  $('cmp').innerHTML = `<b>Original:</b> ${f(momentsFor(ORIG, thr))} &nbsp;·&nbsp; <b>Current settings:</b> ${f(cur)}`;
}

// ---------- before / after ----------
let baOn = false, baToken = 0;
$('baBtn').onclick = () => {
  baOn = !baOn; $('baBtn').classList.toggle('on', baOn);
  $('baWrap').classList.toggle('hidden', !baOn); $('stage').classList.toggle('hidden', baOn);
  if (baOn) { vid.pause(); fetchCompare(); }
};
async function fetchCompare() {
  const tok = ++baToken, t = vid.currentTime || 0;
  $('baBtn').textContent = '◧ Working…';
  try {
    const r = await fetch(`/api/compare/${VID}?t=${t.toFixed(3)}&model=${curModel()}${cfgParam(cfg)}`);
    if (!r.ok || tok !== baToken) return;
    const d = await r.json();
    await Promise.all([['baO', 'baOc', d.original], ['baE', 'baEc', d.enhanced]].map(([i, c, x]) => new Promise(res => {
      const im = $(i); im.onload = () => { drawBA(c, im, x.boxes); res(); }; im.src = x.img;
    })));
  } finally { if (tok === baToken) $('baBtn').textContent = '◧ Before / after'; }
}
function drawBA(cid, im, boxes) {
  const c = $(cid), dpr = window.devicePixelRatio || 1, W = im.clientWidth, H = im.clientHeight;
  c.width = W * dpr; c.height = H * dpr; const x = c.getContext('2d'); x.setTransform(dpr, 0, 0, dpr, 0, 0);
  x.font = '600 12px -apple-system,Segoe UI,sans-serif'; x.textBaseline = 'top';
  boxes.forEach(b => {
    const ok = b[4] >= thr, col = ok ? '#14c4af' : '#f0b429', bx = b[0] * W, by = b[1] * H;
    x.lineWidth = 2; x.strokeStyle = col; x.strokeRect(bx, by, (b[2] - b[0]) * W, (b[3] - b[1]) * H);
    const l = `Fish ${b[4].toFixed(2)}${ok ? '' : ' · check'}`, tw = x.measureText(l).width + 8, ly = by >= 18 ? by - 17 : by + 1;
    x.fillStyle = col; x.fillRect(bx - 1, ly, tw, 16); x.fillStyle = '#06161a'; x.fillText(l, bx + 3, ly + 2);
  });
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
}

function renderReview() {
  if (!R) return;
  renderSel();
  const all = Boxes.allBoxes(R, DOC);
  $('sEdited').textContent = all.filter(b => b.kind === 'ai' && b.edited).length;
  $('sOwn').textContent = all.filter(b => b.kind === 'own').length;
  // one tick per box; click = jump to it and select it
  $('ticks').innerHTML = all.map(b => {
    const cls = b.rejected ? 'rej' : b.kind === 'own' ? 'own' : (b.conf >= thr ? 'ai' : 'low') + (b.edited ? ' ed' : '');
    return `<i class="tick ${cls}${b.id === SEL ? ' sel' : ''}" data-id="${b.id}" style="left:${R.samples[b.i].t / R.duration * 100}%" title="${b.label}"></i>`;
  }).join('');
  // list
  const onlyEdited = $('fEdited').checked, showRej = $('fRejected').checked;
  let rows = all.filter(b => b.kind === 'own' || b.edited || (b.rejected ? showRej : b.conf >= thr));
  if (!showRej) rows = rows.filter(b => !b.rejected);
  if (onlyEdited) rows = rows.filter(b => b.edited);
  rows.sort((a, b) => R.samples[a.i].t - R.samples[b.i].t);
  const cap = rows.length > 300; if (cap) rows = rows.slice(0, 300);
  $('boxList').innerHTML = rows.length ? `<table class="bt"><tr><th>Time</th><th>Name</th><th>Who</th><th>Confidence</th><th></th></tr>` + rows.map(b =>
    `<tr data-id="${b.id}" class="${b.id === SEL ? 'sel' : ''}"><td>${fmt(R.samples[b.i].t, 1)}</td><td>${b.label.replace(/</g, '&lt;')}</td><td>${b.kind === 'own' ? 'Me' : 'AI'}</td><td>${b.conf === null ? '–' : b.conf.toFixed(2)}</td><td>${b.edited ? '✎ edited ' : ''}${b.rejected ? 'rejected' : ''}</td></tr>`).join('') + '</table>' + (cap ? '<p class="note">Showing the first 300 boxes.</p>' : '')
    : '<p class="note">No boxes to show here.</p>';
}
$('ticks').addEventListener('click', e => { const t = e.target.closest('.tick'); if (t) select(t.dataset.id, true); });
$('boxList').addEventListener('click', e => { const r = e.target.closest('tr[data-id]'); if (r) select(r.dataset.id, true); });
$('fEdited').onchange = $('fRejected').onchange = renderReview;

// ---------- reports and the outlined video ----------
$('expBtn').onclick = async () => {
  await saveNow(); $('expMsg').textContent = 'Saving the report…';
  const r = await (await fetch(`/api/export/${VID}${QS}&thr=${thr}`, { method: 'POST' })).json();
  $('expMsg').innerHTML = `Saved in <code>${r.folder}</code><br>` + r.files.map(f => `<a href="/download/${VID}/${f}">${f}</a>`).join(' · ');
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
