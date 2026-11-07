// Box editing model: pure functions, no DOM. Used by the page, by Node tests and by the headless-Chrome test.
// The AI only says "fish". People may type any name on any box.
(function (g) {
  const DEFAULT = 'fish', TOL = 1e-4, C = ['x1', 'y1', 'x2', 'y2'];
  const rectOf = b => ({ x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 });
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  function emptyDoc() { return { version: 1, ai: {}, own: [], next_id: 1 }; }
  // Older files: missing label -> "fish", missing original -> current
  function normalizeDoc(d) {
    const o = emptyDoc(); if (!d || typeof d !== 'object') return o;
    Object.entries(d.ai || {}).forEach(([k, e]) => {
      if (!e) return; e = { ...e }; e.label = (e.label || DEFAULT).trim() || DEFAULT; e.rejected = !!e.rejected;
      if (e.orig) e.orig = { label: DEFAULT, ...C.reduce((a, c) => (c in e ? { ...a, [c]: e[c] } : a), {}), ...e.orig };
      else if (C.every(c => c in e)) e.orig = { ...rectOf(e), label: e.label };
      o.ai[k] = e;
    });
    (d.own || []).forEach(b => { if (b && C.every(c => c in b) && 'sample' in b) o.own.push({ ...b, label: (b.label || DEFAULT).trim() || DEFAULT }); });
    o.next_id = d.next_id || (o.own.length + 1); return o;
  }
  const clone = d => JSON.parse(JSON.stringify(d));
  function differs(cur, orig) { return C.some(c => Math.abs(cur[c] - orig[c]) > TOL) || cur.label !== orig.label; }

  // Every box of one checked picture (index i): AI boxes (with their reviewer edits) + the reviewer's own.
  function boxesAt(res, doc, i) {
    const out = [], s = res.samples[i]; if (!s) return out;
    s.boxes.forEach((b, j) => {
      const base = { x1: b[0], y1: b[1], x2: b[2], y2: b[3], label: DEFAULT }, e = doc.ai[`${i}:${j}`];
      const cur = e ? { ...base, ...pick(e) } : base, orig = e ? (e.orig || { ...cur }) : base;
      out.push({ id: `m${i}-${j}`, kind: 'ai', i, j, ...cur, conf: b[4], rejected: !!(e && e.rejected), edited: differs(cur, orig), orig });
    });
    doc.own.forEach(o => { if (o.sample === i) out.push({ id: o.id, kind: 'own', i, j: null, ...pick(o), conf: null, rejected: false, edited: false, orig: null }); });
    return out;
  }
  // Fish counted in picture i: not removed, and (the reviewer's own box, or confident, or edited). Same rule as the report.
  function countedAt(res, doc, i, thr) {
    const by = {}; let n = 0, unsure = 0, ai = 0, own = 0;
    boxesAt(res, doc, i).forEach(b => {
      if (b.rejected) return;
      if (b.kind === 'own' || b.conf >= thr || b.edited) { n++; by[b.label] = (by[b.label] || 0) + 1; if (b.kind === 'own') own++; else ai++; } else unsure++;
    });
    return { n, unsure, by, ai, own };
  }
  function pick(e) { const r = {}; C.forEach(c => { if (c in e) r[c] = e[c]; }); if (e.label) r.label = e.label; return r; }
  function allBoxes(res, doc) { const o = []; res.samples.forEach((_, i) => o.push(...boxesAt(res, doc, i))); return o; }
  function findBox(res, doc, id) {
    if (id[0] === 'm') { const [i, j] = id.slice(1).split('-').map(Number); return boxesAt(res, doc, i).find(b => b.j === j) || null; }
    const o = doc.own.find(x => x.id === id); return o ? boxesAt(res, doc, o.sample).find(b => b.id === id) : null;
  }

  // ---- edits (mutate the doc; callers snapshot for undo first)
  function ensureAI(res, doc, id) {
    const [i, j] = id.slice(1).split('-').map(Number), key = `${i}:${j}`, b = res.samples[i].boxes[j];
    const base = { x1: b[0], y1: b[1], x2: b[2], y2: b[3], label: DEFAULT };
    return doc.ai[key] || (doc.ai[key] = { ...base, rejected: false, orig: { ...base } });
  }
  function patchBox(res, doc, id, patch) {
    if (id[0] === 'm') {
      const [i, j] = id.slice(1).split('-').map(Number), key = `${i}:${j}`;
      const e = ensureAI(res, doc, id);
      Object.assign(e, pick(patch));
      if ('label' in patch) e.label = (patch.label || '').trim() || DEFAULT;
      // moved back to its original place and name: it is an untouched AI box again
      if (!e.rejected && !differs(e, e.orig)) delete doc.ai[key];
    } else {
      const o = doc.own.find(x => x.id === id); if (!o) return;
      Object.assign(o, pick(patch)); if ('label' in patch) o.label = (patch.label || '').trim() || DEFAULT;
    }
  }
  function rejectAI(res, doc, id) { ensureAI(res, doc, id).rejected = true; }
  function restoreAI(res, doc, id) {
    const [i, j] = id.slice(1).split('-').map(Number), key = `${i}:${j}`, e = doc.ai[key]; if (!e) return;
    e.rejected = false; if (!differs(e, e.orig)) delete doc.ai[key];
  }
  function resetAI(res, doc, id) { const [i, j] = id.slice(1).split('-'); delete doc.ai[`${i}:${j}`]; }
  function deleteOwn(doc, id) { doc.own = doc.own.filter(x => x.id !== id); }
  function addOwn(doc, sample, r, label) {
    const id = `r${doc.next_id++}`, n = normRect(r);
    doc.own.push({ id, sample, ...n, label: (label || DEFAULT).trim() || DEFAULT }); return id;
  }

  // ---- geometry (normalised 0-1)
  function normRect(r) { return { x1: clamp(Math.min(r.x1, r.x2), 0, 1), y1: clamp(Math.min(r.y1, r.y2), 0, 1), x2: clamp(Math.max(r.x1, r.x2), 0, 1), y2: clamp(Math.max(r.y1, r.y2), 0, 1) }; }
  // px = hit tolerance in normalised units per axis ({x, y}); returns 'nw','n',... 'move' or null
  function hit(b, nx, ny, tol) {
    const tx = tol.x, ty = tol.y, L = Math.abs(nx - b.x1) <= tx, R = Math.abs(nx - b.x2) <= tx, T = Math.abs(ny - b.y1) <= ty, B = Math.abs(ny - b.y2) <= ty;
    const inX = nx >= b.x1 - tx && nx <= b.x2 + tx, inY = ny >= b.y1 - ty && ny <= b.y2 + ty;
    if (!(inX && inY)) return null;
    const mx = Math.abs(nx - (b.x1 + b.x2) / 2) <= tx, my = Math.abs(ny - (b.y1 + b.y2) / 2) <= ty;
    if (T && L) return 'nw'; if (T && R) return 'ne'; if (B && L) return 'sw'; if (B && R) return 'se';
    if (T && mx) return 'n'; if (B && mx) return 's'; if (L && my) return 'w'; if (R && my) return 'e';
    return (nx >= b.x1 && nx <= b.x2 && ny >= b.y1 && ny <= b.y2) ? 'move' : null;
  }
  function inside(b, nx, ny) { return nx >= b.x1 && nx <= b.x2 && ny >= b.y1 && ny <= b.y2; }
  function moveRect(r, dx, dy) {
    const w = r.x2 - r.x1, h = r.y2 - r.y1, x1 = clamp(r.x1 + dx, 0, 1 - w), y1 = clamp(r.y1 + dy, 0, 1 - h);
    return { x1, y1, x2: x1 + w, y2: y1 + h };
  }
  function resizeRect(r, handle, nx, ny, min = 0.01) {
    let { x1, y1, x2, y2 } = r; nx = clamp(nx, 0, 1); ny = clamp(ny, 0, 1);
    if (handle.includes('w')) x1 = Math.min(nx, x2 - min);
    if (handle.includes('e')) x2 = Math.max(nx, x1 + min);
    if (handle.includes('n')) y1 = Math.min(ny, y2 - min);
    if (handle.includes('s')) y2 = Math.max(ny, y1 + min);
    return { x1, y1, x2, y2 };
  }
  // names already used in this video (never a fixed species list)
  function labelSuggestions(res, doc) {
    const set = new Set([DEFAULT]);
    allBoxes(res, doc).forEach(b => { if (!b.rejected) set.add(b.label); });
    return [...set].sort((a, b) => (a === DEFAULT ? -1 : b === DEFAULT ? 1 : a.localeCompare(b)));
  }
  function createHistory(limit = 60) {
    const st = [];
    return { push(doc) { st.push(JSON.stringify(doc)); if (st.length > limit) st.shift(); }, undo() { return st.length ? normalizeDoc(JSON.parse(st.pop())) : null; }, get size() { return st.length; } };
  }

  const api = { DEFAULT, emptyDoc, normalizeDoc, clone, boxesAt, countedAt, allBoxes, findBox, patchBox, rejectAI, restoreAI, resetAI, deleteOwn, addOwn,
    normRect, hit, inside, moveRect, resizeRect, labelSuggestions, createHistory, differs };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else g.Boxes = api;
})(typeof window !== 'undefined' ? window : globalThis);
