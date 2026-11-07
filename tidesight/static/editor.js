// Pointer + keyboard handling for editing boxes on the video canvas. Depends on boxes.js (window.Boxes).
// Rules: select a box first, then drag it to move/resize. Dragging from an UNselected box (or empty space) draws a new box.
// Keyboard shortcuts never fire while the reviewer is typing in a text field.
(function (g) {
  const B = g.Boxes;
  const HANDLE_PX = 9, DRAG_PX = 4, MIN = 0.012;

  function typingIn(t) {
    if (!t || !t.tagName) return false;
    const n = t.tagName;
    return n === 'INPUT' || n === 'TEXTAREA' || n === 'SELECT' || t.isContentEditable === true;
  }

  // opts: canvas, getRect() -> {x,y,w,h} (video area in canvas CSS px), getBoxes() -> boxes of the shown picture,
  //       getSelected(), setSelected(id|null), enabled(), onDrawStart(), onAdd(rect), onChange(id, rect, final), onDelete(id), onNudge(id, dx, dy), onUndo()
  function createEditor(opts) {
    const cv = opts.canvas;
    let drag = null;       // {mode:'move'|handle|'draw', id, start:{nx,ny}, rect0, started, target}
    const ed = { draft: null, cursor: 'default' };

    function norm(e) {
      const r = cv.getBoundingClientRect(), v = opts.getRect();
      return { nx: (e.clientX - r.left - v.x) / v.w, ny: (e.clientY - r.top - v.y) / v.h, px: e.clientX - r.left, py: e.clientY - r.top, v };
    }
    const tolOf = v => ({ x: HANDLE_PX / v.w, y: HANDLE_PX / v.h });
    function topBoxAt(nx, ny) {
      const bs = opts.getBoxes().filter(b => B.inside(b, nx, ny));
      bs.sort((a, b) => (a.x2 - a.x1) * (a.y2 - a.y1) - (b.x2 - b.x1) * (b.y2 - b.y1));
      return bs[0] || null;
    }

    function down(e) {
      if (!opts.enabled() || e.button > 0) return;
      const p = norm(e);
      if (p.nx < 0 || p.nx > 1 || p.ny < 0 || p.ny > 1) return;
      const selId = opts.getSelected(), sel = selId && opts.getBoxes().find(b => b.id === selId);
      let mode = null;
      if (sel) mode = B.hit(sel, p.nx, p.ny, tolOf(p.v));   // only the SELECTED box can be moved/resized
      if (mode) drag = { mode, id: sel.id, start: p, rect0: { x1: sel.x1, y1: sel.y1, x2: sel.x2, y2: sel.y2 }, started: true };
      else drag = { mode: 'draw', start: p, started: false, target: topBoxAt(p.nx, p.ny) };
      try { cv.setPointerCapture(e.pointerId); } catch (_) { /* synthetic events */ }
      e.preventDefault();
    }
    function move(e) {
      const p = norm(e);
      if (!drag) { ed.cursor = hoverCursor(p); cv.style.cursor = ed.cursor; return; }
      if (drag.mode === 'draw') {
        if (!drag.started) {
          if (Math.hypot(p.px - drag.start.px, p.py - drag.start.py) < DRAG_PX) return;
          drag.started = true; opts.onDrawStart();            // dragging a new box pauses the video
        }
        ed.draft = B.normRect({ x1: drag.start.nx, y1: drag.start.ny, x2: p.nx, y2: p.ny });
      } else {
        const dx = p.nx - drag.start.nx, dy = p.ny - drag.start.ny;
        const r = drag.mode === 'move' ? B.moveRect(drag.rect0, dx, dy) : B.resizeRect(drag.rect0, drag.mode, p.nx, p.ny, MIN);
        drag.last = r; opts.onChange(drag.id, r, false);
      }
    }
    function up(e) {
      if (!drag) return;
      const d = drag; drag = null;
      try { cv.releasePointerCapture(e.pointerId); } catch (_) { }
      if (d.mode === 'draw') {
        const r = ed.draft; ed.draft = null;
        if (d.started && r && (r.x2 - r.x1) > MIN && (r.y2 - r.y1) > MIN) opts.onAdd(r);
        else if (!d.started) opts.setSelected(d.target ? d.target.id : null);   // a plain click selects (or deselects)
      } else if (d.last) opts.onChange(d.id, d.last, true);
    }
    function hoverCursor(p) {
      if (!opts.enabled()) return 'default';
      const selId = opts.getSelected(), sel = selId && opts.getBoxes().find(b => b.id === selId);
      const h = sel && B.hit(sel, p.nx, p.ny, tolOf(p.v));
      if (!h) return 'crosshair';
      return h === 'move' ? 'move' : ({ n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize', nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize' })[h];
    }
    function key(e) {
      if (typingIn(e.target) || typingIn(document.activeElement)) return;   // typing a name: no shortcuts at all
      if (!opts.enabled()) return;
      const id = opts.getSelected(), mod = e.metaKey || e.ctrlKey;
      if (mod && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); opts.onUndo(); return; }
      if (e.key === 'Escape') { opts.setSelected(null); return; }
      if (!id) return;
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); opts.onDelete(id); return; }
      const step = e.shiftKey ? 0.02 : 0.004;
      const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
      if (d) { e.preventDefault(); opts.onNudge(id, d[0], d[1]); }
    }

    cv.addEventListener('pointerdown', down); cv.addEventListener('pointermove', move);
    cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
    document.addEventListener('keydown', key);
    ed.destroy = () => { cv.removeEventListener('pointerdown', down); cv.removeEventListener('pointermove', move); cv.removeEventListener('pointerup', up); cv.removeEventListener('pointercancel', up); document.removeEventListener('keydown', key); };
    ed.typingIn = typingIn;
    return ed;
  }
  g.BoxEditor = { createEditor, typingIn };
})(typeof window !== 'undefined' ? window : globalThis);
