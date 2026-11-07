// Node tests for static/boxes.js.  Usage: node tests/boxes_node_test.js            (run the tests)
//                                         node tests/boxes_node_test.js fixture.json (print boxes for a results+state fixture)
const B = require('../static/boxes.js'), fs = require('fs'), assert = require('assert');
if (process.argv[2]) {
  const fx = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), doc = B.normalizeDoc(fx.state);
  console.log(JSON.stringify(B.allBoxes(fx.results, doc).map(b => ({ id: b.id, label: b.label, edited: b.edited, rejected: b.rejected, kind: b.kind }))));
  process.exit(0);
}
const res = { samples: [{ t: 0, frame: 0, boxes: [[.1, .1, .3, .3, .9], [.5, .5, .7, .7, .4]] }, { t: .5, frame: 15, boxes: [[.2, .2, .4, .4, .8]] }] };
let n = 0; const ok = (c, m) => { assert(c, m); n++; };

let d = B.emptyDoc();
ok(B.boxesAt(res, d, 0).every(b => b.label === 'fish' && !b.edited && !b.rejected), 'default label is fish');
B.patchBox(res, d, 'm0-0', { label: 'cunner' });
let b = B.findBox(res, d, 'm0-0');
ok(b.label === 'cunner' && b.edited && b.orig.label === 'fish' && b.kind === 'ai', 'rename marks the AI box edited, keeps original');
B.patchBox(res, d, 'm0-0', { x1: .12, x2: .32 });
ok(Math.abs(B.findBox(res, d, 'm0-0').orig.x1 - .1) < 1e-9, 'original coordinates are kept');
B.patchBox(res, d, 'm0-0', { label: 'fish', x1: .1, x2: .3 });
ok(!B.findBox(res, d, 'm0-0').edited && Object.keys(d.ai).length === 0, 'moving back + original name = unedited again');

B.rejectAI(res, d, 'm0-1'); ok(B.findBox(res, d, 'm0-1').rejected, 'AI delete = rejected');
B.restoreAI(res, d, 'm0-1'); ok(!B.findBox(res, d, 'm0-1').rejected && Object.keys(d.ai).length === 0, 'restore brings it back');

const id = B.addOwn(d, 1, { x1: .6, y1: .2, x2: .4, y2: .1 }, '  shark ');
b = B.findBox(res, d, id);
ok(b.label === 'shark' && b.x1 === .4 && b.kind === 'own', 'own box: trimmed name, normalised rect');
B.patchBox(res, d, id, { label: '' }); ok(B.findBox(res, d, id).label === 'fish', 'empty name falls back to fish');
B.patchBox(res, d, id, { label: 'pollock' });
ok(B.labelSuggestions(res, d).join() === 'fish,pollock', 'suggestions come only from names used in this video');
B.deleteOwn(d, id); ok(B.findBox(res, d, id) === null, 'own box removed completely');

// geometry
const r = { x1: .2, y1: .2, x2: .4, y2: .4 };
const m = B.moveRect(r, 2, 2); ok(m.x2 <= 1 && m.y2 <= 1 && Math.abs(m.x2 - m.x1 - .2) < 1e-9, 'move is clamped to the picture and keeps size');
const z = B.resizeRect(r, 'se', .1, .1, .01); ok(z.x2 > z.x1 && z.y2 > z.y1, 'resize never inverts');
ok(B.hit({ x1: .2, y1: .2, x2: .4, y2: .4 }, .4, .4, { x: .01, y: .01 }) === 'se', 'handle hit');
ok(B.hit({ x1: .2, y1: .2, x2: .4, y2: .4 }, .3, .3, { x: .01, y: .01 }) === 'move', 'inside = move');
ok(B.hit({ x1: .2, y1: .2, x2: .4, y2: .4 }, .8, .8, { x: .01, y: .01 }) === null, 'outside = nothing');

// old files without labels still open
const old = B.normalizeDoc({ ai: { '0:0': { x1: .15, y1: .1, x2: .3, y2: .3 } }, own: [{ id: 'r9', sample: 0, x1: .5, y1: .5, x2: .6, y2: .6 }] });
b = B.findBox(res, old, 'm0-0'); ok(b.label === 'fish' && !b.edited, 'old file: default label fish, original = current');
ok(B.findBox(res, old, 'r9').label === 'fish', 'old own box gets label fish');

// undo
const h = B.createHistory(); let dd = B.emptyDoc(); h.push(dd); B.addOwn(dd, 0, { x1: .1, y1: .1, x2: .2, y2: .2 });
const back = h.undo(); ok(back.own.length === 0 && h.size === 0, 'undo restores the previous state');
console.log(`boxes.js: ${n} checks passed`);
