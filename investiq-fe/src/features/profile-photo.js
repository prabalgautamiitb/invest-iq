import { profileApi } from '../api/services.js';

export function photoSection({ account, avatar, link, preview = true }) {
  return `<section class="panel profile-photo-panel" aria-label="Profile photo"><div class="profile-photo-summary">${preview ? avatar('large') : ''}<div><h2>Profile photo</h2><p class="small">Make your account feel like you.</p></div></div>${account ? `<div class="profile-photo-actions"><button type="button" class="secondary" data-photo-action="upload">Upload photo</button><button type="button" class="secondary" data-photo-action="edit" data-photo-requires-image ${account.photo_version ? '' : 'hidden'}>Edit photo</button><button type="button" class="ghost negative" data-photo-action="remove" data-photo-requires-image ${account.photo_version ? '' : 'hidden'}>Remove photo</button></div><input type="file" data-photo-file accept="image/jpeg,image/png,image/webp" hidden aria-label="Choose a profile photo"><p class="small">JPG, PNG, or WebP · up to 5 MB. Crop your photo before saving.</p><p class="photo-notice" role="status"></p>` : `<p>${link('Sign in to add a photo', 'login', 'secondary')}</p>`}</section>`;
}

export function createPhotoEditor({ getAccount, current, saved, toast }) {
  const dialog = document.createElement('dialog');
  dialog.className = 'photo-editor';
  dialog.setAttribute('aria-labelledby', 'photo-editor-title');
  document.body.append(dialog);
  let image = null, zoom = 1, rotation = 0, pan = { x: 0, y: 0 }, drag = null;
  let owner = null, sequence = 0, busy = false, trigger = null;
  const SIZE = 512;
  const canvas = () => dialog.querySelector('canvas');
  const controls = () => dialog.querySelectorAll('button, input');
  function notice(message) {
    const node = dialog.open ? dialog.querySelector('[data-photo-status]') : document.querySelector('.photo-notice');
    if (node) node.textContent = message;
  }
  function close() {
    if (dialog.open) dialog.close();
    sequence++;
    image = null; drag = null; busy = false; owner = null;
    dialog.replaceChildren();
    if (trigger?.isConnected) trigger.focus({ preventScroll: true });
  }
  function paint() {
    if (!image || !canvas()) return;
    const swapped = rotation % 180 !== 0;
    const width = swapped ? image.naturalHeight : image.naturalWidth;
    const height = swapped ? image.naturalWidth : image.naturalHeight;
    const scale = Math.max(SIZE / width, SIZE / height) * zoom;
    const maxX = (width * scale - SIZE) / 2, maxY = (height * scale - SIZE) / 2;
    pan.x = Math.max(-maxX, Math.min(maxX, pan.x));
    pan.y = Math.max(-maxY, Math.min(maxY, pan.y));
    const ctx = canvas().getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.save(); ctx.translate(SIZE / 2 + pan.x, SIZE / 2 + pan.y);
    ctx.rotate(rotation * Math.PI / 180);
    ctx.drawImage(image, -image.naturalWidth * scale / 2, -image.naturalHeight * scale / 2, image.naturalWidth * scale, image.naturalHeight * scale);
    ctx.restore();
  }
  function show() {
    zoom = 1; rotation = 0; pan = { x: 0, y: 0 };
    dialog.innerHTML = `<header class="row"><h2 id="photo-editor-title">Edit profile photo</h2><button type="button" class="ghost" data-photo-editor="cancel" aria-label="Close photo editor">✕</button></header><p>Drag the photo to reposition it. Use zoom to frame your face.</p><canvas width="512" height="512" tabindex="0" role="img" aria-label="Photo crop preview. Drag or use arrow keys to reposition."></canvas><label class="field photo-zoom">Zoom<input type="range" min="1" max="3" step="0.05" value="1" aria-label="Photo zoom"></label><div class="photo-editor-tools"><button type="button" class="secondary" data-photo-editor="rotate">Rotate photo</button><button type="button" class="ghost" data-photo-editor="reset">Reset crop</button></div><p role="status" data-photo-status></p><footer><button type="button" class="secondary" data-photo-editor="cancel">Cancel</button><button type="button" class="primary" data-photo-editor="save">Save photo</button></footer>`;
    paint(); dialog.showModal();
  }
  async function load(blob) {
    const token = ++sequence, id = getAccount()?.id;
    if (!id) return;
    const url = URL.createObjectURL(blob);
    try {
      const next = new Image(); next.src = url; await next.decode();
      if (token !== sequence || getAccount()?.id !== id || !current().startsWith('profile')) return;
      if (next.naturalWidth * next.naturalHeight > 24_000_000 || Math.max(next.naturalWidth, next.naturalHeight) > 8192) throw new Error('Choose a smaller photo, up to 24 megapixels.');
      image = next; owner = id; show();
    } catch (error) {
      if (token === sequence && id === getAccount()?.id) notice(error.message === 'The source image cannot be decoded.' ? 'This photo could not be opened. Choose a valid JPG, PNG, or WebP image.' : error.message);
    } finally { URL.revokeObjectURL(url); }
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-photo-action]');
    if (!button || busy || !getAccount()) return;
    trigger = button;
    const section = button.closest('.profile-photo-panel');
    if (button.dataset.photoAction === 'upload') { section.querySelector('[data-photo-file]').click(); return; }
    const id = getAccount().id, token = ++sequence;
    button.disabled = true;
    try {
      if (button.dataset.photoAction === 'edit') {
        const blob = await profileApi.photo();
        if (token === sequence && id === getAccount()?.id) await load(blob);
      } else if (button.dataset.photoAction === 'remove') {
        const user = await profileApi.removePhoto();
        if (token === sequence && id === getAccount()?.id) { saved(user); syncControls(); toast('Profile photo removed.'); }
      }
    } catch (error) { if (token === sequence && id === getAccount()?.id) notice(error.message); }
    finally { if (button.isConnected) button.disabled = false; }
  });
  document.addEventListener('change', event => {
    if (!event.target.matches('[data-photo-file]')) return;
    const file = event.target.files[0]; event.target.value = '';
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { notice('Choose a JPG, PNG, or WebP photo.'); return; }
    if (file.size > 5 * 1024 * 1024) { notice('Choose a photo smaller than 5 MB.'); return; }
    notice(''); load(file);
  });
  function syncControls() {
    document.querySelectorAll('[data-photo-requires-image]').forEach(node => { node.hidden = !getAccount()?.photo_version; });
  }
  dialog.addEventListener('input', event => {
    if (!busy && event.target.matches('input[type="range"]')) { zoom = Number(event.target.value); paint(); }
  });
  dialog.addEventListener('pointerdown', event => {
    if (busy || event.target !== canvas() || !event.isPrimary || event.button !== 0) return;
    const rect = canvas().getBoundingClientRect();
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, pan: { ...pan }, scale: SIZE / rect.width };
    canvas().setPointerCapture(event.pointerId);
  });
  dialog.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id || busy) return;
    pan = { x: drag.pan.x + (event.clientX - drag.x) * drag.scale, y: drag.pan.y + (event.clientY - drag.y) * drag.scale }; paint();
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) dialog.addEventListener(type, () => { drag = null; });
  dialog.addEventListener('keydown', event => {
    if (busy || event.target !== canvas()) return;
    const delta = { ArrowLeft: [-16, 0], ArrowRight: [16, 0], ArrowUp: [0, -16], ArrowDown: [0, 16] }[event.key];
    if (delta) { event.preventDefault(); pan.x += delta[0]; pan.y += delta[1]; paint(); }
  });
  dialog.addEventListener('cancel', event => { event.preventDefault(); if (!busy) close(); });
  dialog.addEventListener('click', async event => {
    const action = event.target.closest('[data-photo-editor]')?.dataset.photoEditor;
    if (!action || busy) return;
    if (action === 'cancel') { close(); return; }
    if (action === 'rotate') { rotation = (rotation + 90) % 360; paint(); return; }
    if (action === 'reset') { zoom = 1; rotation = 0; pan = { x: 0, y: 0 }; dialog.querySelector('input').value = '1'; paint(); return; }
    const token = sequence, id = owner;
    busy = true; controls().forEach(node => { node.disabled = true; }); notice('Saving your photo…');
    try {
      const blob = await new Promise(resolve => canvas().toBlob(resolve, 'image/jpeg', 0.9));
      if (!blob) throw new Error('Your photo could not be prepared. Please try again.');
      const user = await profileApi.savePhoto(blob);
      if (token !== sequence || id !== getAccount()?.id) return;
      saved(user); syncControls(); close(); toast('Profile photo saved.');
    } catch (error) { if (token === sequence && id === getAccount()?.id) notice(error.message); }
    finally { if (token === sequence) { busy = false; controls().forEach(node => { node.disabled = false; }); } }
  });
  document.addEventListener('investiq:render', () => {
    if (!current().startsWith('profile') || (owner && owner !== getAccount()?.id)) close();
  });
}
