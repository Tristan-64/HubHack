const $ = id => document.getElementById(id);
const MINC = 0.2;
let R = null, VID = null, momentsList = [], thr = 0.6, cutoff = 0.5, SP = { available: false, byLatin: {}, generic: 'Actinopterygii', minPx: 40 }, QS = '';
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
  showErr(''); $('review').classList.add('hidden');
  const model = $('model').value, sfps = parseFloat($('sfps').value) || 2;
  const fd = new FormData(); fd.append('file', f); fd.append('model', model); fd.append('sample_fps', sfps);
  const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/upload');
  xhr.upload.onprogress = e => e.lengthComputable && setProg(`Adding your video… ${Math.round(e.loaded / e.total * 100)}%`, e.loaded / e.total);
  xhr.onerror = () => showErr('Could not reach the app. Is it still running?');
  xhr.onload = () => {
    if (xhr.status !== 200) return showErr('Upload failed: ' + (xhr.responseText || xhr.status));
    const j = JSON.parse(xhr.responseText); VID = j.id; poll(j.id, j.model, j.sample_fps);
  };
  xhr.send(fd);
}

async function poll(id, model, sfps) {
  const q = `?model=${model}&sample_fps=${sfps}`;
  while (true) {
    const s = await (await fetch(`/api/status/${id}${q}`)).json();
    if (s.stage === 'error') { $('prog').classList.add('hidden'); return showErr(s.error || 'Something went wrong.'); }
    if (s.stage === 'done') break;
    if (s.stage === 'downloading') setProg(`Downloading the fish finder (first time only)… ${Math.round((s.dl || 0) * 100)}%`, s.dl || 0);
    else if (s.stage === 'loading' || s.stage === 'unknown') setProg('Getting ready…', 0.02);
    else setProg(`Analysing ${s.done} of ${s.total} frames${s.converting ? ' · preparing video for playback' : ''}`, s.total ? s.done / s.total : 0);
    await new Promise(r => setTimeout(r, 600));
  }
  QS = q; R = await (await fetch(`/api/results/${id}${q}`)).json();
  $('prog').classList.add('hidden');
  load();
}

// ---------- review ----------
function fmt(t, d = 2) { const m = Math.floor(t / 60), sec = t - m * 60; return String(m).padStart(2, '0') + ':' + sec.toFixed(d).padStart(2 + (d ? d + 1 : 0), '0'); }
function load() {
  $('review').classList.remove('hidden');
  vid.src = `/video/${VID}/${R.playable}`;
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
const maxConf = s => s.boxes.reduce((m, b) => Math.max(m, b[4]), 0);
function recompute() {
  // timeline
  const tl = $('tl'); tl.querySelectorAll('.seg').forEach(e => e.remove());
  const g = gap(); let skipped = 0;
  R.samples.forEach(s => {
    const mc = maxConf(s);
    if (!s.boxes.length) { skipped += g; return; }
    const d = document.createElement('div'); d.className = 'seg ' + (mc >= thr ? 't' : 'a');
    d.style.left = (Math.max(0, s.t - g / 2) / R.duration * 100) + '%';
    d.style.width = Math.max(0.15, g / R.duration * 100) + '%';
    tl.insertBefore(d, $('head'));
  });
  $('sSkip').textContent = Math.round(Math.min(100, skipped / R.duration * 100)) + '%';
  // moments
  momentsList = []; let cur = null; const tally = {}; let newish = 0;
  R.samples.forEach((s, i) => {
    const n = s.boxes.filter(b => b[4] >= thr).length;
    if (n) {
      if (cur && cur.end === i - 1) { cur.end = i; cur.max = Math.max(cur.max, n); cur.top = Math.max(cur.top, maxConf(s)); }
      else { cur = { start: i, end: i, max: n, top: maxConf(s), sp: {} }; momentsList.push(cur); }
      s.boxes.forEach((b, j) => { if (b[4] < thr) return; const sp = speciesFor(s, j); if (sp) { cur.sp[sp.name] = (cur.sp[sp.name] || 0) + 1; tally[sp.name] = (tally[sp.name] || 0) + 1; if (sp.maybeNew) newish++; } });
    }
  });
  $('sMom').textContent = momentsList.length;
  renderSummary(tally, newish);
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

function nearest(t) {
  const S = R.samples; let lo = 0, hi = S.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; (S[mid].t <= t) ? lo = mid : hi = mid; }
  return (Math.abs(S[hi].t - t) < Math.abs(S[lo].t - t)) ? hi : lo;
}
function seek(t) { vid.currentTime = Math.max(0, Math.min(R.duration, t)); }

function videoRect() {
  const W = cv.clientWidth, H = cv.clientHeight, vw = vid.videoWidth || R.width, vh = vid.videoHeight || R.height;
  const sc = Math.min(W / vw, H / vh), w = vw * sc, h = vh * sc;
  return { x: (W - w) / 2, y: (H - h) / 2, w, h };
}
function draw() {
  if (!R) return;
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const t = vid.currentTime || 0, i = nearest(t), s = R.samples[i];
  if (Math.abs(s.t - t) <= gap() * 1.01) {
    const vr = videoRect(); ctx.font = '600 13px -apple-system,Segoe UI,sans-serif'; ctx.textBaseline = 'top';
    s.boxes.forEach((b, idx) => {
      const ok = b[4] >= thr, col = ok ? '#14c4af' : '#f0b429';
      const x = vr.x + b[0] * vr.w, y = vr.y + b[1] * vr.h, w = (b[2] - b[0]) * vr.w, h = (b[3] - b[1]) * vr.h;
      ctx.lineWidth = 2.5; ctx.strokeStyle = col; ctx.strokeRect(x, y, w, h);
      const sp = speciesFor(s, idx), spt = sp ? (sp.name === 'Unknown' ? ' · Unknown' : ` · ${sp.name} ${sp.score.toFixed(2)}`) : '';
      const label = (ok ? `Fish ${b[4].toFixed(2)}` : `Fish ${b[4].toFixed(2)} · check`) + spt, tw = ctx.measureText(label).width + 10;
      const ly = y >= 20 ? y - 20 : y + 2;
      ctx.fillStyle = col; ctx.fillRect(x - 1, ly, tw, 18); ctx.fillStyle = '#06161a'; ctx.fillText(label, x + 4, ly + 3);
    });
  }
  // readouts
  $('time').textContent = `${fmt(t, 2)} · frame ${Math.round(t * R.fps)}`;
  $('head').style.left = (t / R.duration * 100) + '%';
  if (!scrubbing) $('scrub').value = t / R.duration * 1000;
  const k = momentsList.findIndex(m => i >= m.start && i <= m.end);
  document.querySelectorAll('#moments .row').forEach(r => r.classList.toggle('on', +r.dataset.k === k));
  $('play').textContent = vid.paused ? '▶ Play' : '⏸ Pause';
}
let scrubbing = false;
(function loop() { draw(); requestAnimationFrame(loop); })();

$('play').onclick = () => vid.paused ? vid.play() : vid.pause();
vid.onclick = $('play').onclick;
$('scrub').oninput = e => { scrubbing = true; seek(e.target.value / 1000 * R.duration); };
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
