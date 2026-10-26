// Position only: moving the launcher never re-renders the conversation.
export function floatingLauncher(root) {
  const storageKey = 'investiq-martin-position';
  let position = null, gesture = null, suppressClick = false;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    if (saved && ['x', 'y'].every(key => Number.isFinite(saved[key]) && saved[key] >= 0 && saved[key] <= 1)) position = saved;
  } catch { /* Storage is optional. */ }
  const button = () => root.querySelector('.martin-launcher');
  const clamp = (value, min, max) => Math.max(min, Math.min(value, Math.max(min, max)));
  function bounds() {
    const viewport = window.visualViewport;
    const left = (viewport?.offsetLeft || 0) + 12, top = (viewport?.offsetTop || 0) + 12;
    const right = left + (viewport?.width || innerWidth) - 24;
    let bottom = top + (viewport?.height || innerHeight) - 24;
    const nav = document.querySelector('.bottomnav');
    if (nav?.getClientRects().length) bottom = Math.min(bottom, nav.getBoundingClientRect().top - 12);
    return { left, top, right, bottom: Math.max(top, bottom) };
  }
  function range() {
    const area = bounds(), node = button();
    return { ...area, maxX: Math.max(area.left, area.right - node.offsetWidth), maxY: Math.max(area.top, area.bottom - node.offsetHeight) };
  }
  function save() {
    try {
      if (position) localStorage.setItem(storageKey, JSON.stringify(position));
      else localStorage.removeItem(storageKey);
    } catch { /* Moving still works when storage is blocked. */ }
  }
  function placePanel() {
    const panel = root.querySelector('.martin-window');
    if (!panel || panel.hidden) return;
    const area = bounds(), anchor = button().getBoundingClientRect();
    panel.style.position = 'fixed';
    panel.style.right = panel.style.bottom = 'auto';
    panel.style.maxWidth = Math.max(0, area.right - area.left) + 'px';
    panel.style.maxHeight = Math.max(0, area.bottom - area.top) + 'px';
    const { width, height } = panel.getBoundingClientRect();
    const above = anchor.top - height - 14, below = anchor.bottom + 14;
    const top = above >= area.top ? above : below + height <= area.bottom ? below : anchor.bottom - height;
    let left = anchor.right - width;
    if (above < area.top && below + height > area.bottom) {
      if (anchor.right + 14 + width <= area.right) left = anchor.right + 14;
      else if (anchor.left - 14 - width >= area.left) left = anchor.left - 14 - width;
    }
    panel.style.left = clamp(left, area.left, area.right - width) + 'px';
    panel.style.top = clamp(top, area.top, area.bottom - height) + 'px';
  }
  function layout() {
    if (root.hidden || !button()) return;
    const area = range();
    root.style.right = root.style.bottom = root.style.left = root.style.top = '';
    const initial = button().getBoundingClientRect();
    const x = position ? area.left + position.x * (area.maxX - area.left) : initial.left;
    const y = position ? area.top + position.y * (area.maxY - area.top) : initial.top;
    root.style.right = root.style.bottom = 'auto';
    root.style.left = clamp(x, area.left, area.maxX) + 'px';
    root.style.top = clamp(y, area.top, area.maxY) + 'px';
    root.dataset.launcherSide = x < (area.left + area.maxX) / 2 ? 'left' : 'right';
    placePanel();
  }
  function move(x, y) {
    const area = range();
    position = {
      x: (clamp(x, area.left, area.maxX) - area.left) / (area.maxX - area.left || 1),
      y: (clamp(y, area.top, area.maxY) - area.top) / (area.maxY - area.top || 1),
    };
    layout();
  }
  function finish(event, cancelled = false) {
    if (!gesture || event.pointerId !== gesture.id) return;
    const previous = gesture;
    gesture = null;
    delete root.dataset.dragging;
    if (previous.moved) {
      suppressClick = true;
      if (cancelled) { position = previous.position; layout(); }
      else save();
    }
    if (root.hasPointerCapture(event.pointerId)) root.releasePointerCapture(event.pointerId);
  }
  root.addEventListener('pointerdown', event => {
    if (!event.target.closest('.martin-launcher') || !event.isPrimary || event.button !== 0) return;
    suppressClick = false;
    const rect = button().getBoundingClientRect();
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, left: rect.left, top: rect.top, position, moved: false };
  });
  window.addEventListener('pointermove', event => {
    if (!gesture || gesture.id !== event.pointerId) return;
    if (root.hidden || !button()) { finish(event, true); return; }
    const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
    if (!gesture.moved && Math.hypot(dx, dy) < 6) return;
    if (!gesture.moved) {
      gesture.moved = true;
      root.dataset.dragging = 'true';
      root.setPointerCapture(event.pointerId);
    }
    move(gesture.left + dx, gesture.top + dy);
  });
  window.addEventListener('pointerup', event => finish(event));
  window.addEventListener('pointercancel', event => finish(event, true));
  root.addEventListener('lostpointercapture', event => { if (event.target === root) finish(event); });
  root.addEventListener('click', event => {
    if (!suppressClick) return;
    suppressClick = false;
    if (event.detail > 0) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  root.addEventListener('keydown', event => {
    if (!event.target.matches('.martin-launcher')) return;
    const delta = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
    if (event.key === 'Home') { event.preventDefault(); position = null; save(); layout(); }
    else if (delta) {
      event.preventDefault();
      const rect = button().getBoundingClientRect(), step = event.shiftKey ? 48 : 16;
      move(rect.left + delta[0] * step, rect.top + delta[1] * step);
      save();
    }
  });
  window.addEventListener('resize', layout);
  window.visualViewport?.addEventListener('resize', layout);
  window.visualViewport?.addEventListener('scroll', layout);
  return { layout };
}
