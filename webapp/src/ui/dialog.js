// A non-blocking in-page confirmation dialog, used instead of the native
// window.confirm() -- the native dialog freezes the entire tab's event
// loop (including any attached automation/devtools) until dismissed, which
// is both a poor UX for a control panel and a real hazard during testing.
import { el } from '../utils.js';

export function confirmDialog(message) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKeydown);
      overlay.remove();
      resolve(result);
    };
    const onKeydown = (e) => {
      if (e.key === 'Escape') finish(false);
    };

    const cancelBtn = el('button', { onclick: () => finish(false) }, 'Cancel');
    const okBtn = el('button', { class: 'danger', onclick: () => finish(true) }, 'Confirm');
    const box = el('div', { class: 'modal-box' }, [
      el('p', {}, message),
      el('div', { class: 'field-row', style: 'justify-content:flex-end' }, [cancelBtn, okBtn]),
    ]);
    const overlay = el('div', { class: 'modal-overlay', onclick: (e) => { if (e.target === overlay) finish(false); } }, [box]);

    document.body.append(overlay);
    document.addEventListener('keydown', onKeydown);
    okBtn.focus();
  });
}
