import './style.css';
import libraryJson from './data/library.json';
import { decodeLooksBin, encodeBundlesBin, hasTone, nameProblem, PackError, validatePack, type Problem } from './format';
import {
  ARTS, MAX_LOOKS, MONO_FILTERS, NAME_MAX, NOTE_MAX, PACK_SCHEMA, SECTORS, SLOT_NAMES, TINTS, TONE_KEYS, blankLook, cloneLook,
  exportable, parsePack, toneIsZero, toneLimit, type Look, type Pack, type SlotName, type Tone,
} from './pack';
import { History } from './history';
import { fromLibrary, libraryOrigin, migratePack, replaceRetiredLooks, resetLook, standardPack } from './reset';
import { renderLook } from './preview';
import { decodeLookCode, decodePackCode, encodeLookCode, encodePackCode, isPackCode } from './sharecode';
import { makeZip } from './zip';
import { rrpreset } from './rapidraw';
import { TARGETS, targetById } from './targets';
import { recipeCard } from './targets/recipe';
import { previewToneLut } from './tone';

// ---------------------------------------------------------------- state
const LIBRARY = parsePack(libraryJson);
const STORE = 'caduceus.pack.v2', STORE_V1 = 'caduceus.pack.v1', STORE_LIB = 'caduceus.library';
// '+m2': forces one more migration pass for packs saved before tone fingerprints were handled
const LIB_VERSION: string = ((libraryJson as { version?: string }).version ?? 'dev') + '+m2';
const SAMPLES = [
  { id: 'market', label: 'Market' }, { id: 'portrait', label: 'Portrait' },
  { id: 'lake', label: 'Lake' }, { id: 'sunset', label: 'Sunset' },
];
const SWATCH = ['#e3c22f', '#e8932e', '#e0602a', '#d03434', '#c43c92', '#8a52c6', '#3d5bd0', '#3d8bd0', '#2fb2c6',
  '#2fb28c', '#45a845', '#9fc63b'];
type Tab = 'hue' | 'light' | 'sat';

let libNotice = '';   // before S: startPack() sets it
const S = {
  pack: startPack(),
  sel: 0,
  tab: 'hue' as Tab,
  image: 'market',
  advice: true,
  compare: false,
};

/** The saved pack brought up to the current built-in library (or the library itself for a first visit). */
function startPack(): Pack {
  const stored = loadStored();
  const swap = stored ? replaceRetiredLooks(stored, LIBRARY) : null;
  const saved = swap ? swap.pack : stored;
  if (swap?.replaced) {
    libNotice = 'Nostalgic has been replaced by Provia 400 in your saved pack.';
    try { localStorage.setItem(STORE, JSON.stringify(swap.pack)); } catch { /* private mode */ }
  }
  let prev: { version?: string; names?: string[] } = {};
  try { prev = JSON.parse(localStorage.getItem(STORE_LIB) ?? '{}'); } catch { /* none */ }
  const stamp = () => { try { localStorage.setItem(STORE_LIB, JSON.stringify({ version: LIB_VERSION, names: LIBRARY.looks.map((l) => l.name) })); } catch { /* private mode */ } };
  if (!saved) { stamp(); return standardPack(LIBRARY); }
  if (prev.version === LIB_VERSION) return saved;
  const m = migratePack(saved, LIBRARY, prev.names);
  stamp();
  if (m.updated || m.added)
    libNotice = (libNotice ? libNotice + ' ' : '') + `Film library updated to v${LIB_VERSION}: ${m.updated} look${m.updated === 1 ? '' : 's'} refreshed` +
      (m.added ? `, ${m.added} added` : '') + '. Your own and edited looks are unchanged.';
  try { localStorage.setItem(STORE, JSON.stringify(m.pack)); } catch { /* private mode */ }
  return m.pack;
}

function loadStored(): Pack | null {
  try {
    const s = localStorage.getItem(STORE);
    if (s) return parsePack(JSON.parse(s));
    // v1 storage predates Look.origin: looks named like a library look are taken to be that look (for Reset look).
    const old = localStorage.getItem(STORE_V1);
    if (!old) return null;
    const p = parsePack(JSON.parse(old));
    for (const l of p.looks) if (LIBRARY.looks.some((o) => o.name === l.name)) l.origin = l.name;
    return p;
  } catch { return null; }
}
let saveTimer = 0;
function flush() { clearTimeout(saveTimer); try { localStorage.setItem(STORE, JSON.stringify(S.pack)); } catch { /* private mode */ } }
function persist() { clearTimeout(saveTimer); saveTimer = window.setTimeout(flush, 250); }
window.addEventListener('pagehide', flush);

// ---------------------------------------------------------------- undo / redo
// Every edit calls save(). Continuous edits (slider drags, typing) run inside draft(): they are saved but only become
// an undo step at the end of the gesture (the input's change event: pointer-up, blur or Enter) via checkpoint().
const hist = new History(JSON.stringify(S.pack), 200);
let drafting = false;
function save() { persist(); if (!drafting) checkpoint(); }
function draft(f: () => void) { drafting = true; try { f(); } finally { drafting = false; } }
function checkpoint() { hist.commit(JSON.stringify(S.pack)); undoUi(); }
function undoUi() {
  const u = document.getElementById('undo') as HTMLButtonElement | null, r = document.getElementById('redo') as HTMLButtonElement | null;
  if (u) u.disabled = !hist.canUndo;
  if (r) r.disabled = !hist.canRedo;
}
function step(dir: 'undo' | 'redo') {
  checkpoint();
  const s = dir === 'undo' ? hist.undo() : hist.redo();
  if (s === null) return;
  const prev = S.pack;
  S.pack = parsePack(JSON.parse(s));
  const n = S.pack.looks.length;
  const k = S.pack.looks.findIndex((l, i) => JSON.stringify(l) !== JSON.stringify(prev.looks[i]));
  S.sel = Math.max(0, Math.min(k >= 0 ? k : S.sel, n - 1));
  persist(); renderAll(); undoUi();
}
const isTextField = (t: EventTarget | null) => t instanceof HTMLTextAreaElement || (t instanceof HTMLElement && t.isContentEditable) ||
  (t instanceof HTMLInputElement && !['range', 'checkbox', 'radio', 'button', 'submit', 'reset', 'color', 'file'].includes(t.type));
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || isTextField(e.target) || document.querySelector('dialog[open]')) return;
  const k = e.key.toLowerCase();
  if (k === 'z') step(e.shiftKey ? 'redo' : 'undo');
  else if (k === 'y' && !e.shiftKey) step('redo');
  else return;
  e.preventDefault();
});
const cur = (): Look | undefined => S.pack.looks[S.sel];

// ---------------------------------------------------------------- DOM helpers
type Attrs = Record<string, unknown>;
function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...kids: (Node | string | null | false | undefined)[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    else if (k === 'class') el.className = String(v);
    else if (k === 'value') (el as HTMLInputElement).value = String(v);
    else if (k === 'checked') (el as HTMLInputElement).checked = Boolean(v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of kids) if (c !== null && c !== false && c !== undefined) el.append(c);
  return el;
}
const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;

function download(name: string, data: Uint8Array | string, type = 'application/octet-stream') {
  const url = URL.createObjectURL(new Blob([data as BlobPart], { type }));
  const a = h('a', { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

let toastTimer = 0;
function toast(msg: string, kind: 'ok' | 'err' = 'ok') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (t.className = 'toast'), 3200);
}

function modal(title: string, body: Node, actions: (HTMLElement | null)[] = []): HTMLDialogElement {
  const dlg = h('dialog', { class: 'modal' },
    h('form', { method: 'dialog', class: 'modal-head' }, h('h2', {}, title), h('button', { class: 'icon', 'aria-label': 'Close' }, '×')),
    h('div', { class: 'modal-body' }, body),
    actions.length ? h('div', { class: 'modal-actions' }, ...actions) : null);
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

async function copy(text: string, what = 'Copied') {
  try { await navigator.clipboard.writeText(text); toast(what); } catch { toast('Copy failed: select the text and copy it by hand', 'err'); }
}

const shareBase = () => location.origin + location.pathname;

// ---------------------------------------------------------------- layout
function shell() {
  const app = $('#app');
  app.replaceChildren(
    h('header', { class: 'top' },
      h('div', { class: 'brand' }, h('span', { class: 'mark', 'aria-hidden': 'true' }, '☤'), h('span', { class: 'word' }, 'Caduceus'),
        h('span', { class: 'sub' }, 'control panel')),
      h('nav', { class: 'actions' },
        h('span', { class: 'undo-btns' },
          h('button', { id: 'undo', class: 'icon', title: 'Undo (Ctrl+Z)', 'aria-label': 'Undo', disabled: true, onclick: () => step('undo') }, '↶'),
          h('button', { id: 'redo', class: 'icon', title: 'Redo (Ctrl+Shift+Z)', 'aria-label': 'Redo', disabled: true, onclick: () => step('redo') }, '↷')),
        menu('New', [
          ['Reset pack to standard', () => newPack('library')],
          ['Empty pack', () => newPack('empty')],
        ]),
        h('button', { onclick: openFile }, 'Open…'),
        h('button', { onclick: pasteDialog }, 'Paste code'),
        h('button', { onclick: sharePack }, 'Share pack'),
        h('button', { onclick: installDialog }, 'Install firmware'),
        h('button', { class: 'primary', onclick: exportDialog }, 'Export'))),
    h('main', { class: 'layout' },
      h('aside', { class: 'pane list-pane', id: 'list' }),
      h('section', { class: 'pane preview-pane', id: 'preview' }),
      h('section', { class: 'pane editor-pane', id: 'editor' })),
    h('footer', { class: 'foot' },
      h('span', {}, 'Caduceus is an unofficial, community firmware mod. Files are made in your browser; nothing is uploaded.'),
      h('a', { href: './samples/CREDITS.md', target: '_blank', rel: 'noopener' }, 'Image credits (CC0)')),
    h('div', { id: 'toast', class: 'toast', role: 'status', 'aria-live': 'polite' }),
    h('input', { type: 'file', id: 'file', accept: '.json,application/json,.bin,.BIN', hidden: true, onchange: onFile }),
    h('input', { type: 'file', id: 'photo', accept: 'image/*', hidden: true, onchange: onPhoto }));
  buildPreview();
}

function menu(label: string, items: [string, () => void][]): HTMLElement {
  const d = h('details', { class: 'menu' }, h('summary', {}, label),
    h('div', { class: 'menu-items' }, ...items.map(([t, f]) => h('button', { onclick: () => { d.open = false; f(); } }, t))));
  document.addEventListener('click', (e) => { if (!d.contains(e.target as Node)) d.open = false; });
  return d;
}

function renderAll() {
  renderList();
  renderEditor();
  schedulePreview();
}

// ---------------------------------------------------------------- look list
let dragFrom = -1;
function renderList() {
  const el = $('#list');
  const p = S.pack;
  const problems = validatePack(p);
  const bad = new Set(problems.map((x) => x.look).filter((x) => x !== undefined));
  const n = p.looks.length;
  el.replaceChildren(
    h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Pack name'),
      h('input', { type: 'text', value: p.name, maxlength: 60, oninput: (e: Event) => draft(() => { p.name = (e.target as HTMLInputElement).value; save(); }), onchange: checkpoint, onkeydown: enterCommits })),
    h('div', { class: 'list-head' }, h('span', {}, 'Looks'), h('span', { class: n > MAX_LOOKS ? 'count over' : 'count' }, `${n} / ${MAX_LOOKS}`)),
    h('ol', { class: 'looks' }, ...p.looks.map((l, i) => {
      const li = h('li', {
        class: `look${i === S.sel ? ' sel' : ''}${bad.has(i) ? ' bad' : ''}`, draggable: 'true', tabindex: 0,
        onclick: () => { S.sel = i; renderAll(); },
        onkeydown: (e: KeyboardEvent) => {
          if (e.key === 'ArrowUp' && e.altKey) { move(i, i - 1); e.preventDefault(); }
          else if (e.key === 'ArrowDown' && e.altKey) { move(i, i + 1); e.preventDefault(); }
          else if (e.key === 'ArrowUp' && i > 0) { S.sel = i - 1; renderAll(); focusSel(); e.preventDefault(); }
          else if (e.key === 'ArrowDown' && i < n - 1) { S.sel = i + 1; renderAll(); focusSel(); e.preventDefault(); }
        },
        ondragstart: (e: DragEvent) => { dragFrom = i; e.dataTransfer?.setData('text/plain', String(i)); li.classList.add('dragging'); },
        ondragend: () => li.classList.remove('dragging'),
        ondragover: (e: DragEvent) => { e.preventDefault(); li.classList.add('over'); },
        ondragleave: () => li.classList.remove('over'),
        ondrop: (e: DragEvent) => { e.preventDefault(); li.classList.remove('over'); if (dragFrom >= 0) move(dragFrom, i); dragFrom = -1; },
      },
      h('span', { class: 'grip', 'aria-hidden': 'true' }, '⋮⋮'),
      h('span', { class: 'idx' }, String(i + 1)),
      h('span', { class: 'nm' }, l.name || '(no name)'),
      l.kind === 'mono' ? h('span', { class: 'kind mono', title: 'Monochrome look' }, 'B&W') : h('span'),
      h('span', { class: 'row-btns' },
        h('button', { class: 'icon', title: 'Move up (Alt+↑)', 'aria-label': 'Move up', disabled: i === 0, onclick: (e: Event) => { e.stopPropagation(); move(i, i - 1); } }, '↑'),
        h('button', { class: 'icon', title: 'Move down (Alt+↓)', 'aria-label': 'Move down', disabled: i === n - 1, onclick: (e: Event) => { e.stopPropagation(); move(i, i + 1); } }, '↓'),
        h('button', { class: 'icon danger', title: 'Remove', 'aria-label': 'Remove', onclick: (e: Event) => { e.stopPropagation(); remove(i); } }, '×')));
      return li;
    })),
    ...(n === 0 ? [h('p', { class: 'empty' }, 'No looks yet. Add one below.')] : []),
    h('div', { class: 'add-row' },
      menu('+ Add look', [
        ['Blank colour look', () => addLook(blankLook('colour', uniqueName('New Look')))],
        ['Blank mono look', () => addLook(blankLook('mono', uniqueName('New Mono')))],
        ['From the built-in library…', libraryPicker],
        ['Duplicate selected', () => { const l = cur(); if (l) addLook({ ...cloneLook(l), name: uniqueName(l.name) }); }],
        ['Paste a look code…', pasteDialog],
      ])));
}
function enterCommits(e: KeyboardEvent) { if (e.key === 'Enter') checkpoint(); }
function focusSel() { ($('#list li.sel') as HTMLElement | null)?.focus(); }

function uniqueName(base: string): string {
  const names = new Set(S.pack.looks.map((l) => l.name.toLowerCase()));
  if (!names.has(base.toLowerCase())) return base;
  for (let k = 2; k < 100; k++) {
    const suf = ` ${k}`, nm = base.slice(0, NAME_MAX - suf.length).trimEnd() + suf;
    if (!names.has(nm.toLowerCase())) return nm;
  }
  return base;
}

function addLook(l: Look) {
  if (S.pack.looks.length >= MAX_LOOKS) { toast(`A pack holds at most ${MAX_LOOKS} looks. Remove one first.`, 'err'); return false; }
  S.pack.looks.push(l);
  S.sel = S.pack.looks.length - 1;
  save(); renderAll();
  return true;
}
function remove(i: number) {
  const l = S.pack.looks[i];
  S.pack.looks.splice(i, 1);
  remapSlots((k) => (k === i ? undefined : k > i ? k - 1 : k));
  S.sel = Math.max(0, Math.min(S.sel, S.pack.looks.length - 1));
  save(); renderAll();
  toast(`Removed "${l.name}"`);
}
function move(from: number, to: number) {
  const n = S.pack.looks.length;
  if (to < 0 || to >= n || from === to) return;
  const [l] = S.pack.looks.splice(from, 1);
  S.pack.looks.splice(to, 0, l);
  const old = [...Array(n).keys()];               // new position -> old index
  old.splice(from, 1); old.splice(to, 0, from);
  const map = new Map(old.map((o, k) => [o, k] as [number, number]));
  remapSlots((k) => map.get(k));
  S.sel = to;
  save(); renderAll(); focusSel();
}
function remapSlots(f: (k: number) => number | undefined) {
  for (const s of SLOT_NAMES) {
    const k = S.pack.slots[s];
    if (k === undefined) continue;
    const v = f(k);
    if (v === undefined) delete S.pack.slots[s]; else S.pack.slots[s] = v;
  }
}

function newPack(kind: 'library' | 'empty') {
  if (!confirm(kind === 'library' ? 'Reset the pack to the standard built-in library? Your current pack is replaced (Undo brings it back).'
    : 'Start an empty pack? The current pack is replaced (Undo brings it back).')) return;
  S.pack = kind === 'library' ? standardPack(LIBRARY) : { schema: PACK_SCHEMA, name: 'My pack', looks: [blankLook('colour', 'My Look')], slots: {} };
  S.sel = 0;
  save(); renderAll();
  toast(kind === 'library' ? 'Pack reset to the built-in library' : 'Started an empty pack');
}

function resetSelected() {
  const i = S.sel, l = cur();
  if (!l) return;
  S.pack.looks[i] = resetLook(l, LIBRARY, S.pack.looks.filter((_, k) => k !== i).map((o) => o.name));
  save(); renderAll();
  toast(libraryOrigin(l, LIBRARY) ? `"${S.pack.looks[i].name}" restored to the built-in values` : `"${l.name}" reset to neutral`);
}

function libraryPicker() {
  const have = new Set(S.pack.looks.map((l) => l.name.toLowerCase()));
  const list = h('div', { class: 'pick-list' }, ...LIBRARY.looks.map((l) => h('button', {
    class: 'pick', onclick: () => { if (addLook({ ...fromLibrary(l), name: uniqueName(l.name) })) dlg.close(); },
  }, h('b', {}, l.name), have.has(l.name.toLowerCase()) ? h('span', { class: 'tag' }, 'in pack') : null, h('small', {}, l.notes))));
  const dlg = modal('Add from the built-in library', list);
}

// ---------------------------------------------------------------- editor
function renderEditor() {
  const el = $('#editor');
  const l = cur();
  if (!l) { el.replaceChildren(h('p', { class: 'empty' }, 'Add a look to start editing.')); return; }
  const i = S.sel;
  const changed = () => { save(); schedulePreview(); refreshProblems(); refreshLookCode(); };
  const np = nameProblem(l.name);
  const nameInput = h('input', {
    type: 'text', value: l.name, maxlength: NAME_MAX, spellcheck: 'false', autocomplete: 'off', 'aria-describedby': 'name-help',
    onchange: checkpoint, onkeydown: enterCommits,
    oninput: (e: Event) => draft(() => {
      l.name = (e.target as HTMLInputElement).value;
      const p = nameProblem(l.name) ?? dupName(l, i);
      $('#name-help').textContent = p ?? `${l.name.length} / ${NAME_MAX}`;
      $('#name-help').className = p ? 'help err' : 'help';
      const row = document.querySelectorAll('#list li .nm')[i];
      if (row) row.textContent = l.name || '(no name)';
      changed();
    }),
  });
  const notesBytes = () => new TextEncoder().encode(l.notes).length;
  el.replaceChildren(
    h('div', { class: 'ed-head' },
      h('label', { class: 'field grow' }, h('span', { class: 'lbl' }, 'Name'), nameInput,
        h('span', { id: 'name-help', class: np || dupName(l, i) ? 'help err' : 'help' }, np ?? dupName(l, i) ?? `${l.name.length} / ${NAME_MAX}`)),
      h('div', { class: 'ed-btns' },
        h('button', {
          class: 'share-btn', onclick: resetSelected,
          title: libraryOrigin(l, LIBRARY) ? `Restore the built-in "${libraryOrigin(l, LIBRARY)!.name}" values` : 'Set every value to neutral',
        }, 'Reset look'),
        h('button', { class: 'share-btn', onclick: () => shareLook(l), title: 'Share this look as a short code' }, 'Share'))),
    seg('Type', [['colour', 'Colour'], ['mono', 'Monochrome']], l.kind, (v) => {
      l.kind = v as Look['kind'];
      if (l.kind === 'mono') { l.art_effect = 'off'; l.advice.mono_filter ??= { colour: 'none', strength: 1 }; }
      renderList(); renderEditor(); changed();
    }),
    l.kind === 'colour' ? sectorPanel(l, changed) : monoPanel(l, changed),
    ...(l.kind === 'colour' ? [tonePanel(l, changed)] : []),
    h('div', { class: 'group' },
      seg('Noise reduction', [['off', 'Camera'], ['standard', 'Standard'], ['fine', 'Low'], ['film', 'Off (most texture)']], l.grain, (v) => { l.grain = v as Look['grain']; renderEditor(); changed(); })),
    effectPanel(l, changed),
    wbPanel(l, changed),
    ...(l.kind === 'colour' ? [h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Art Effect'),
      h('select', { onchange: (e: Event) => { l.art_effect = (e.target as HTMLSelectElement).value as Look['art_effect']; changed(); } },
        ...ARTS.filter((a) => ['off', 'star_light', 'pin_hole'].includes(a) || a === l.art_effect).map((a) =>
          h('option', { value: a, selected: a === l.art_effect }, artLabel(a)))),
      h('span', { class: 'help' }, 'Kept in the pack file, share codes and the starter BUNDLES.BIN (COLOR slots). LOOKS.BIN has no Art Effect field. Not shown in the preview.'))] : []),
    h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Notes'),
      h('textarea', {
        rows: 3, maxlength: 400, placeholder: 'What the look is for, settings advice…', onchange: checkpoint,
        oninput: (e: Event) => draft(() => {
          l.notes = (e.target as HTMLTextAreaElement).value;
          const b = notesBytes();
          $('#notes-help').textContent = `${b} / ${NOTE_MAX} bytes · kept in the pack file (not on the card)`;
          $('#notes-help').className = b > NOTE_MAX ? 'help err' : 'help';
          changed();
        }),
      }, l.notes),
      h('span', { id: 'notes-help', class: notesBytes() > NOTE_MAX ? 'help err' : 'help' }, `${notesBytes()} / ${NOTE_MAX} bytes · kept in the pack file (not on the card)`)),
    lookCodePanel(l),
    h('div', { id: 'problems' }));
  refreshProblems();
  refreshLookCode();
}

/** Per-look share code: live code with copy buttons, and a box to paste a code into this look. */
function lookCodePanel(l: Look): HTMLElement {
  const code = h('code', { id: 'look-code' });
  const help = h('span', { id: 'look-code-help', class: 'help' });
  const inp = h('input', { type: 'text', placeholder: 'Paste a look code to load it into this look', spellcheck: 'false', autocomplete: 'off' });
  const msg = h('span', { class: 'help' });
  const apply = () => {
    const t = inp.value.trim();
    if (!t) return;
    if (isPackCode(t)) { msg.className = 'help err'; msg.textContent = 'That is a pack link: use Paste code at the top.'; return; }
    try {
      const n = decodeLookCode(t), i = S.sel;
      n.notes = l.notes;                                    // codes carry no notes: keep this look's
      S.pack.looks[i] = { ...l, name: '' };                 // so the incoming name may reuse this look's
      n.name = uniqueName(n.name);
      S.pack.looks[i] = n;
      save(); renderAll();
      toast(`Loaded "${n.name}" into look ${i + 1} (Undo brings the old one back)`);
    } catch (e) { msg.className = 'help err'; msg.textContent = (e as Error).message; }
  };
  inp.addEventListener('input', () => { msg.textContent = ''; });
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') apply(); });
  const raw = () => { try { return encodeLookCode(cur()!); } catch { return null; } };
  return h('div', { class: 'group look-code' },
    h('span', { class: 'lbl' }, 'Look code'),
    h('div', { class: 'code-box' }, code,
      h('button', { onclick: () => { const c = raw(); if (c) copy(c, 'Code copied'); } }, 'Copy code'),
      h('button', { onclick: () => { const c = raw(); if (c) copy(`${shareBase()}#${c}`, 'Link copied'); } }, 'Copy link')),
    help,
    h('div', { class: 'code-box' }, inp, h('button', { onclick: apply }, 'Load code')),
    msg);
}
function refreshLookCode() {
  const code = document.getElementById('look-code'), help = document.getElementById('look-code-help'), l = cur();
  if (!code || !help || !l) return;
  try {
    code.textContent = encodeLookCode(l, true);
    help.className = 'help';
    help.textContent = 'Share just this look: anyone can paste the code (or open the link) in the control panel. Notes are not included.';
  } catch (e) {
    code.textContent = '—';
    help.className = 'help err';
    help.textContent = (e as Error).message;
  }
}

function dupName(l: Look, i: number): string | null {
  const j = S.pack.looks.findIndex((o, k) => k !== i && o.name.toLowerCase() === l.name.toLowerCase());
  return j >= 0 ? `Same name as look ${j + 1}.` : null;
}
const artLabel = (a: string) => ({ off: 'Off', star_light: 'Star Light', pin_hole: 'Pin Hole', blur: 'Blur (legacy: Off on v0.21+, issue #20)', white_edge: 'White Edge (legacy: Off on v0.15+)', frame: 'Frame (legacy: Off on v0.15+)' } as Record<string, string>)[a] ?? a;

function seg(label: string, opts: [string, string][], value: string, on: (v: string) => void): HTMLElement {
  return h('div', { class: 'field' }, h('span', { class: 'lbl' }, label),
    h('div', { class: 'seg', role: 'radiogroup', 'aria-label': label }, ...opts.map(([v, t]) =>
      h('button', { role: 'radio', 'aria-checked': String(v === value), class: v === value ? 'on' : '', onclick: () => on(v) }, t))));
}

function slider(min: number, max: number, value: number, on: (v: number) => void, fmt = (v: number) => (v > 0 ? `+${v}` : String(v)), aria = '') {
  const out = h('output', {}, fmt(value));
  const inp = h('input', {
    type: 'range', min, max, step: 1, value, 'aria-label': aria,
    oninput: (e: Event) => { const v = Number((e.target as HTMLInputElement).value); out.textContent = fmt(v); draft(() => on(v)); },
    onchange: checkpoint,
    ondblclick: () => { inp.value = '0'; out.textContent = fmt(0); on(0); },
  });
  return { inp, out };
}

function sectorPanel(l: Look, changed: () => void): HTMLElement {
  const tabs: [Tab, string, number][] = [['hue', 'Hue', 7], ['light', 'Lightness', 7], ['sat', 'Saturation', 5]];
  const lim = tabs.find((t) => t[0] === S.tab)![2];
  const arr = l[S.tab];
  const rows = SECTORS.map((name, k) => {
    const { inp, out } = slider(-lim, lim, arr[k], (v) => { arr[k] = v; changed(); }, undefined, `${name} ${S.tab}`);
    return h('div', { class: 'srow' }, h('span', { class: 'sw', style: `background:${SWATCH[k]}` }), h('span', { class: 'sname' }, name), inp, out);
  });
  return h('div', { class: 'group' },
    h('div', { class: 'tabs', role: 'tablist' }, ...tabs.map(([t, label]) => h('button', {
      role: 'tab', 'aria-selected': String(t === S.tab), class: t === S.tab ? 'on' : '',
      onclick: () => { S.tab = t; renderEditor(); },
    }, label, l[t].some((v) => v !== 0) ? h('span', { class: 'dot' }) : null))),
    h('div', { class: 'sectors' }, ...rows),
    h('div', { class: 'tab-foot' },
      h('span', { class: 'help' }, S.tab === 'sat'
        ? 'Saturation is advice: set it in the camera\'s own colour-profile saturation. It is stored for MONO colour slots (looks without a tone).'
        : `±${lim} per sector (v0.17 firmware). Double-click a slider to zero it.`),
      h('button', { class: 'link', onclick: () => { arr.fill(0); renderEditor(); changed(); } }, 'Reset')));
}

/** Small live tone-curve graph: x = the stock rendering, y = with this look's tone (the camera LUT model). */
function toneCurve(tone: Tone): { svg: SVGSVGElement; draw: () => void } {
  const NS = 'http://www.w3.org/2000/svg', S0 = 200, P = 8, W = S0 - 2 * P;
  const el = <K extends keyof SVGElementTagNameMap>(t: K, a: Record<string, string | number>) => {
    const e = document.createElementNS(NS, t);
    for (const [k, v] of Object.entries(a)) e.setAttribute(k, String(v));
    return e;
  };
  const svg = el('svg', { viewBox: `0 0 ${S0} ${S0}`, width: S0, height: S0, class: 'tone-curve', role: 'img', 'aria-label': 'Tone curve: stock input to look output' });
  const X = (v: number) => P + v * W, Y = (v: number) => P + (1 - v) * W;
  svg.append(el('rect', { x: P, y: P, width: W, height: W, class: 'tc-frame' }));
  for (let i = 1; i < 4; i++) {
    svg.append(el('line', { x1: X(i / 4), y1: Y(0), x2: X(i / 4), y2: Y(1), class: 'tc-grid' }));
    svg.append(el('line', { x1: X(0), y1: Y(i / 4), x2: X(1), y2: Y(i / 4), class: 'tc-grid' }));
  }
  svg.append(el('line', { x1: X(0), y1: Y(0), x2: X(1), y2: Y(1), class: 'tc-ident' }));
  const path = el('path', { class: 'tc-curve', d: '' });
  const dB = el('circle', { r: 3.5, class: 'tc-end' }), dW = el('circle', { r: 3.5, class: 'tc-end' });
  svg.append(path, dB, dW);
  const draw = () => {
    const t = previewToneLut(tone, 128);
    let d = '';
    t.forEach((v, i) => { d += `${i ? 'L' : 'M'}${X(i / 128).toFixed(1)},${Y(v).toFixed(1)}`; });
    path.setAttribute('d', d);
    dB.setAttribute('cx', String(X(0))); dB.setAttribute('cy', String(Y(t[0])));
    dW.setAttribute('cx', String(X(1))); dW.setAttribute('cy', String(Y(t[128])));
    dB.classList.toggle('on', tone.blacks !== 0); dW.classList.toggle('on', tone.whites !== 0);
  };
  draw();
  return { svg, draw };
}

const TONE_LABEL: Record<keyof Tone, string> = { highlights: 'Highlights', shadows: 'Shadows', midtones: 'Midtones', blacks: 'Blacks', whites: 'Whites' };
function tonePanel(l: Look, changed: () => void): HTMLElement {
  const rows = TONE_KEYS.map((k) => {
    const lim = toneLimit(k);
    const { inp, out } = slider(-lim, lim, l.tone[k], (v) => { l.tone[k] = v; drawCurve(); changed(); }, undefined, TONE_LABEL[k]);
    return h('div', { class: 'srow plain' }, h('span', { class: 'sname' }, TONE_LABEL[k]), inp, out);
  });
  const { svg, draw: drawCurve } = toneCurve(l.tone);
  return h('div', { class: 'group' },
    h('div', { class: 'tone-head' }, h('span', { class: 'lbl' }, 'Tone'),
      !toneIsZero(l.tone) ? h('button', { class: 'link', onclick: () => { for (const k of TONE_KEYS) l.tone[k] = 0; renderEditor(); changed(); } }, 'Reset') : null),
    svg,
    ...rows.slice(0, 3),
    h('div', { class: 'tone-sep' }),
    ...rows.slice(3),
    h('p', { class: 'help' },
      'Highlights / Shadows / Midtones (±7): picking the look sets the profile\'s own tone settings to these. ',
      'Blacks / Whites (±5) move the ends of the tone curve (+Blacks lifts to a matte black, −Whites rolls the white point off); ',
      'they act in COLOR slots, and a look with a tone is COLOR-only (it cannot go in a MONO slot). Needs Caduceus v0.19 or later. ',
      'The graph shows stock → this look (camera tone LUT model); dots mark the Blacks and Whites ends.'),
  );
}

function monoPanel(l: Look, changed: () => void): HTMLElement {
  const mf = (l.advice.mono_filter ??= { colour: 'none', strength: 1 });
  return h('div', { class: 'group' },
    h('p', { class: 'help' }, 'Mono looks use the camera\'s Monochrome profile; the per-sector colour sliders do not apply. Filter is advice for the camera setting (and the preview).'),
    h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Colour filter (advice)'),
      h('select', { onchange: (e: Event) => { mf.colour = (e.target as HTMLSelectElement).value as typeof mf.colour; changed(); } },
        ...MONO_FILTERS.map((c) => h('option', { value: c, selected: c === mf.colour }, c[0].toUpperCase() + c.slice(1))))),
    (() => { const { inp, out } = slider(1, 3, mf.strength, (v) => { mf.strength = v; changed(); }, String, 'Filter strength'); return h('div', { class: 'srow plain' }, h('span', { class: 'sname' }, 'Filter strength'), inp, out); })());
}

function effectPanel(l: Look, changed: () => void): HTMLElement {
  const e = l.effect;
  const v = !e ? 0 : e.type === 'clarity' ? e.strength : -e.strength;
  const fmt = (x: number) => (x === 0 ? 'Off' : x < 0 ? `Glow ${-x}` : `Clarity ${x}`);
  const tintSel = h('select', {
    'aria-label': 'Glow colour',
    onchange: (ev: Event) => {
      const t = (ev.target as HTMLSelectElement).value as (typeof TINTS)[number];
      if (l.effect && l.effect.type !== 'clarity') { if (t === 'neutral' && l.effect.type === 'bloom') delete l.effect.tint; else l.effect.tint = t; }
      changed();
    },
  }, ...TINTS.map((t) => h('option', { value: t, selected: (e?.tint ?? (e?.type === 'halation' ? 'red' : 'neutral')) === t }, t[0].toUpperCase() + t.slice(1))));
  const tintRow = h('label', { class: 'field inline' }, h('span', { class: 'lbl' }, 'Glow colour'), tintSel);
  tintRow.hidden = !(e && e.type !== 'clarity');
  const { inp, out } = slider(-5, 5, v, (x) => {
    if (x === 0) l.effect = null;
    else if (x > 0) l.effect = { type: 'clarity', strength: x };
    else {
      const keep = l.effect && l.effect.type !== 'clarity' ? l.effect : null;
      l.effect = { type: keep?.type ?? 'bloom', strength: -x, ...(keep?.tint ? { tint: keep.tint } : {}) };
    }
    tintRow.hidden = !(l.effect && l.effect.type !== 'clarity');
    changed();
  }, fmt, 'Glow to clarity');
  return h('div', { class: 'group' },
    h('div', { class: 'field' }, h('span', { class: 'lbl' }, 'Glow ↔ Clarity'),
      h('div', { class: 'srow plain' }, h('span', { class: 'end' }, 'Glow'), inp, h('span', { class: 'end' }, 'Clarity'), out)),
    tintRow);
}

function wbPanel(l: Look, changed: () => void): HTMLElement {
  const on = l.wb !== null;
  const box = h('input', {
    type: 'checkbox', checked: on,
    onchange: (e: Event) => { l.wb = (e.target as HTMLInputElement).checked ? { a_b: 0, g_m: 0 } : null; renderEditor(); changed(); },
  });
  const rows = on ? [['a_b', 'A–B', 'Amber +  /  Blue −'], ['g_m', 'G–M', 'Green +  /  Magenta −']].map(([k, label, tip]) => {
    const { inp, out } = slider(-7, 7, l.wb![k as 'a_b'], (v) => { l.wb![k as 'a_b'] = v; changed(); }, undefined, label);
    return h('div', { class: 'srow plain', title: tip }, h('span', { class: 'sname' }, label), inp, out);
  }) : [];
  return h('div', { class: 'group' },
    h('label', { class: 'check' }, box, h('span', {}, 'White balance shift'),
      h('span', { class: 'help' }, on ? 'overrides the camera\'s WB fine-tune for this look' : 'off: your own WB fine-tune applies')),
    ...rows);
}

function refreshProblems() {
  const el = document.getElementById('problems');
  const probs = validatePack(S.pack);
  if (el) {
    const mine = probs.filter((p) => p.look === S.sel);
    el.replaceChildren(...(mine.length ? [h('ul', { class: 'problems' }, ...mine.map((p) => h('li', {}, p.message)))] : []));
  }
  const bad = new Set(probs.map((p) => p.look));
  document.querySelectorAll('#list li.look').forEach((li, k) => li.classList.toggle('bad', bad.has(k)));
}

// ---------------------------------------------------------------- preview
let srcData: ImageData | null = null;
let userPhoto: ImageData | null = null;
let canvas: HTMLCanvasElement;
let previewQueued = false;

function buildPreview() {
  canvas = h('canvas', { class: 'pv', 'aria-label': 'Approximate preview of the selected look' });
  const thumbs = h('div', { class: 'thumbs' },
    ...SAMPLES.map((s) => h('button', { class: `thumb${S.image === s.id ? ' on' : ''}`, 'data-id': s.id, onclick: () => pickImage(s.id), title: s.label },
      h('img', { src: `./samples/${s.id}.jpg`, alt: s.label, loading: 'lazy' }))),
    h('button', { class: `thumb own${S.image === 'user' ? ' on' : ''}`, 'data-id': 'user', onclick: () => (userPhoto ? pickImage('user') : $<HTMLInputElement>('#photo').click()), title: 'Your photo (stays on this device)' },
      h('span', {}, '+ Your photo')));
  const cmp = h('button', {
    class: 'compare', title: 'Hold to see the original',
    onpointerdown: () => { S.compare = true; schedulePreview(); },
    onpointerup: () => { S.compare = false; schedulePreview(); },
    onpointerleave: () => { if (S.compare) { S.compare = false; schedulePreview(); } },
  }, 'Hold: original');
  $('#preview').replaceChildren(
    h('div', { class: 'pv-wrap' }, canvas, h('span', { class: 'badge' }, 'Approximate preview'), cmp),
    thumbs,
    h('div', { class: 'pv-opts' },
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: S.advice, onchange: (e: Event) => { S.advice = (e.target as HTMLInputElement).checked; schedulePreview(); } }),
        h('span', {}, 'Include advice (saturation, contrast)')),
      h('button', { class: 'link', onclick: () => $<HTMLInputElement>('#photo').click() }, 'Use your own photo…')),
    h('p', { class: 'help' }, 'A rough desktop-sim port running on JPEGs, not the camera\'s pipeline: use it for direction and strength, then check on the camera. Your own photo never leaves this browser.'));
  pickImage(S.image);
}

async function pickImage(id: string) {
  S.image = id;
  document.querySelectorAll('.thumb').forEach((t) => t.classList.toggle('on', (t as HTMLElement).dataset.id === id));
  if (id === 'user') { srcData = userPhoto; schedulePreview(); return; }
  try {
    const img = new Image();
    img.src = `./samples/${id}.jpg`;
    await img.decode();
    srcData = toImageData(img, img.naturalWidth, img.naturalHeight);
    if (S.image === id) schedulePreview();
  } catch { toast('Could not load the sample image', 'err'); }
}

function toImageData(img: CanvasImageSource, w: number, h0: number, max = 1024): ImageData {
  const k = Math.min(1, max / Math.max(w, h0));
  const W = Math.round(w * k), H = Math.round(h0 * k);
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const ctx = c.getContext('2d', { willReadFrequently: true })!;
  ctx.drawImage(img, 0, 0, W, H);
  return ctx.getImageData(0, 0, W, H);
}

async function onPhoto(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (!f) return;
  try {
    const bmp = await createImageBitmap(f, { imageOrientation: 'from-image' } as ImageBitmapOptions);
    userPhoto = toImageData(bmp, bmp.width, bmp.height);
    bmp.close();
    pickImage('user');
  } catch { toast('That file could not be read as an image', 'err'); }
}

function schedulePreview() {
  if (previewQueued) return;
  previewQueued = true;
  requestAnimationFrame(() => {
    previewQueued = false;
    if (!srcData || !canvas) return;
    if (canvas.width !== srcData.width || canvas.height !== srcData.height) { canvas.width = srcData.width; canvas.height = srcData.height; }
    const ctx = canvas.getContext('2d')!;
    const l = cur();
    if (S.compare || !l) { ctx.putImageData(srcData, 0, 0); return; }
    const out = ctx.createImageData(srcData.width, srcData.height);
    renderLook(srcData, out, l, { advice: S.advice });
    ctx.putImageData(out, 0, 0);
  });
}

// ---------------------------------------------------------------- import / export / share
function openFile() { $<HTMLInputElement>('#file').click(); }
async function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (!f) return;
  const bytes = new Uint8Array(await f.arrayBuffer());
  if (bytes.length >= 4 && String.fromCharCode(...bytes.subarray(0, 4)) === 'EP7B') {   // a card LOOKS.BIN
    try {
      const p = decodeLooksBin(bytes, f.name.replace(/\.bin$/i, '') || 'LOOKS.BIN');
      replacePack(p, `Opened ${f.name} (${p.looks.length} looks; LOOKS.BIN has no notes or Art Effects)`);
    } catch (err) { toast((err as Error).message, 'err'); }
    return;
  }
  try {
    const p = parsePack(JSON.parse(new TextDecoder().decode(bytes)));
    replacePack(p, `Opened "${p.name}" (${p.looks.length} looks)`);
  } catch (err) { toast(`Not a pack file or LOOKS.BIN: ${(err as Error).message}`, 'err'); }
}

function replacePack(p: Pack, msg: string) {
  S.pack = p;
  S.sel = 0;
  save(); renderAll();
  const probs = validatePack(p);
  toast(probs.length ? `${msg}. ${probs.length} problem(s) to fix before export.` : msg, probs.length ? 'err' : 'ok');
}

function shareLook(l: Look) {
  let code: string;
  try { code = encodeLookCode(l); } catch (e) { toast((e as Error).message, 'err'); return; }
  const link = `${shareBase()}#${code}`;
  const grouped = encodeLookCode(l, true);
  modal(`Share "${l.name}"`, h('div', { class: 'share' },
    h('p', {}, 'Anyone can paste this code into the Caduceus Control Panel (Paste code) to get this look.'),
    h('div', { class: 'code-box' }, h('code', {}, grouped), h('button', { onclick: () => copy(code, 'Code copied') }, 'Copy code')),
    h('div', { class: 'code-box link' }, h('input', { type: 'text', readonly: true, value: link, onfocus: (e: Event) => (e.target as HTMLInputElement).select() }),
      h('button', { onclick: () => copy(link, 'Link copied') }, 'Copy link')),
    h('p', { class: 'help' }, `${code.length} characters. Carries the card values (incl. tone), name, Art Effect and mono filter; notes stay out (use a pack link for those). Dashes and case don't matter when pasting.`),
    h('div', { class: 'ex-row' },
      h('div', {}, h('b', {}, 'RapidRAW preset'), h('p', { class: 'help' }, 'This look as a .rrpreset for RapidRAW (Presets › Import), for ORF files or raws from any camera. An approximation of the camera look.')),
      h('button', { onclick: () => { const i = S.pack.looks.indexOf(l); if (i >= 0) downloadRr(i); } }, 'Download'))));
}

async function sharePack() {
  const code = await encodePackCode(S.pack);
  const link = `${shareBase()}#${code}`;
  modal('Share this pack', h('div', { class: 'share' },
    h('p', {}, `A link to the whole pack (${S.pack.looks.length} looks, notes and starter slots). Opening it loads the pack in the editor. The pack is inside the link itself: nothing is stored on the server.`),
    h('div', { class: 'code-box link' }, h('input', { type: 'text', readonly: true, value: link, onfocus: (e: Event) => (e.target as HTMLInputElement).select() }),
      h('button', { onclick: () => copy(link, 'Link copied') }, 'Copy link')),
    h('p', { class: 'help' }, `${link.length} characters. For a single look, use the Share button next to its name: much shorter.`)));
}

function pasteDialog() {
  const ta = h('textarea', { rows: 3, placeholder: 'Paste a look code (e.g. 1K7G-…) or a pack link', spellcheck: 'false' });
  const msg = h('p', { class: 'help' });
  const go = h('button', { class: 'primary' }, 'Import');
  const dlg = modal('Paste a code', h('div', {}, ta, msg), [go]);
  go.addEventListener('click', async () => {
    const r = await importCode(ta.value);
    if (r) dlg.close(); else msg.className = 'help err';
  });
  ta.addEventListener('input', () => { msg.textContent = ''; });
  importCodeMsg = (m) => (msg.textContent = m);
  ta.focus();
}
let importCodeMsg: (m: string) => void = (m) => toast(m, 'err');

async function importCode(text: string, fromLink = false): Promise<boolean> {
  const t = text.trim();
  if (!t) return false;
  try {
    if (isPackCode(t)) {
      const p = await decodePackCode(t);
      if (fromLink) return confirmPack(p);
      if (!confirm(`Open the shared pack "${p.name}" (${p.looks.length} looks)? It replaces your current pack.`)) return false;
      replacePack(p, `Opened "${p.name}"`);
      return true;
    }
    const l = decodeLookCode(t);
    if (S.pack.looks.length >= MAX_LOOKS) { fullDialog(l); return true; }
    l.name = uniqueName(l.name);
    addLook(l);
    toast(`Added "${l.name}"`);
    return true;
  } catch (e) {
    importCodeMsg((e as Error).message);
    return false;
  }
}

/** A shared look arrives while the pack already holds 32: replace one, or start a new pack with it. */
function fullDialog(l: Look) {
  const sel = h('select', { 'aria-label': 'Look to replace' }, ...S.pack.looks.map((o, i) => h('option', { value: i, selected: i === S.sel }, `${i + 1}. ${o.name}`)));
  const rep = h('button', { class: 'primary' }, 'Replace');
  const fresh = h('button', {}, 'New pack with just this look');
  const dlg = modal(`Add "${l.name}"`, h('div', {},
    h('p', {}, `Your pack is full (${MAX_LOOKS} looks, the camera's limit). Replace one of them with "${l.name}", or start a new pack.`),
    h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Replace'), sel)), [fresh, rep]);
  rep.addEventListener('click', () => {
    const i = Number(sel.value);
    const old = S.pack.looks[i].name;
    S.pack.looks[i] = { ...S.pack.looks[i], name: '' };   // so the incoming name may reuse the replaced one
    l.name = uniqueName(l.name);
    S.pack.looks[i] = l;
    S.sel = i;
    save(); renderAll(); dlg.close();
    toast(`Replaced "${old}" with "${l.name}"`);
  });
  fresh.addEventListener('click', () => {
    S.pack = { schema: PACK_SCHEMA, name: 'My pack', looks: [l], slots: {} };
    S.sel = 0;
    save(); renderAll(); dlg.close();
    toast(`New pack with "${l.name}"`);
  });
}

function confirmPack(p: Pack): boolean {
  const yes = h('button', { class: 'primary' }, 'Open pack');
  const keep = h('button', {}, 'Keep my pack');
  const dlg = modal('Open shared pack?', h('div', {},
    h('p', {}, `"${p.name}": ${p.looks.length} looks (${p.looks.slice(0, 6).map((l) => l.name).join(', ')}${p.looks.length > 6 ? ', …' : ''}).`),
    h('p', { class: 'help' }, 'Opening it replaces the pack you are editing. Export yours first if you want to keep it.')), [keep, yes]);
  yes.addEventListener('click', () => { replacePack(p, `Opened "${p.name}"`); dlg.close(); });
  keep.addEventListener('click', () => dlg.close());
  return true;
}

const GH = 'https://github.com/cakelesscoder/caduceus-ep7';
function installDialog() {
  const link = (href: string, text: string) => h('a', { href, target: '_blank', rel: 'noopener' }, text);
  const code = (t: string) => h('code', {}, t);
  const step = (title: string, ...body: (Node | string | null)[]) => h('li', { class: 'step' }, h('b', {}, title), h('div', { class: 'step-body' }, ...body));
  const exportBtn = h('button', { onclick: () => { dlg.close(); exportDialog(); } }, 'Open Export');
  const body = h('div', { class: 'install' },
    h('p', { class: 'warn' }, '⚠️ Unofficial, experimental firmware. Flashing can brick your camera; you do this at your own risk. Without the EP7MOD folder the camera is almost stock, and the restore file returns it fully to stock.'),
    h('ol', { class: 'steps' },
      step('Check your camera',
        h('p', {}, 'Olympus PEN ', h('b', {}, 'E-P7'), ' on firmware ', h('b', {}, '1.1'), ' (Setup › Firmware), a charged battery and an SD card formatted in the camera.')),
      step('Get Python 3.10+ (once)',
        h('p', {}, 'Windows / macOS: ', link('https://www.python.org/downloads/', 'python.org/downloads'), '. Windows: tick ', h('b', {}, 'Add python.exe to PATH'), '. macOS: afterwards run ', code('Install Certificates.command'), ' in the Python folder. Linux: usually already installed.')),
      step('Download Caduceus',
        h('p', {}, 'Open the ', link(`${GH}/releases/latest`, 'latest release'), ', download ', h('b', {}, 'Source code (zip)'), ' and unzip it. There is no firmware file to download: OM\'s licence means you build it yourself in the next step.')),
      step('Build (one double-click)',
        h('p', {}, 'In the unzipped folder, double-click the launcher for your system:'),
        h('ul', {},
          h('li', {}, 'Windows: ', code('Build Caduceus (Windows).bat')),
          h('li', {}, 'macOS: ', code('Build Caduceus (Mac).command'), ' (first time: right-click › Open, then Open)'),
          h('li', {}, 'Linux: ', code('build-caduceus-linux.sh'))),
        h('p', {}, 'It downloads OM\'s official 1.1 firmware, builds Caduceus, checks every file and offers to copy it to your camera card. Otherwise copy ', code('DCOLYMP'), ' and ', code('EP7MOD'), ' to the root of the card. Keep ', code('restore/'), ' on your computer.')),
      step('Your looks: LOOKS.BIN (optional)',
        h('p', {}, h('b', {}, 'Nothing to do if you\'re happy with the built-in looks.'), ' The ', code('EP7MOD/LOOKS.BIN'), ' that step 4 puts on the card already holds all 32 built-in looks (Velvia, Portra 400, CineStill 800T, Acros…).'),
        h('p', {}, 'To use your own versions instead:'),
        h('ol', { class: 'substeps' },
          h('li', {}, 'Tweak looks here in the Control Panel, or add new ones (the preview shows the effect).'),
          h('li', {}, 'Press ', h('b', {}, 'Export'), ' › ', code('LOOKS.BIN'), ' › Download.'),
          h('li', {}, 'Copy it to ', code('EP7MOD/'), ' on the card, replacing the old ', code('LOOKS.BIN'), '. Keep the name exactly ', code('LOOKS.BIN'), '.'),
          h('li', {}, 'Put the card back and half-press once: your looks are on the Film page.')),
        h('p', {}, 'No re-flash needed: swap ', code('LOOKS.BIN'), ' any time. Your saved slot choices (', code('BUNDLES.BIN'), ') stay as they are.'),
        exportBtn),
      step('Flash',
        h('p', {}, 'Put the card in the camera, hold ', h('b', {}, 'OK'), ' and switch on. Wait for the update to finish (blinking LED) and don\'t switch off meanwhile. Setup › Firmware then shows Caduceus.')),
      step('Shoot',
        h('p', {}, 'Half-press once so the looks load. Picture Mode › a Colour Profile › colour wheel, press ', h('b', {}, 'INFO'), ' until ', code('Film: <name>'), ', and turn the dial to pick a look.')))
  );
  const dlg = modal('Install the firmware', body, [
    h('a', { class: 'btn', href: `${GH}/blob/main/docs/INSTALL.md`, target: '_blank', rel: 'noopener' }, 'Full guide on GitHub'),
    h('a', { class: 'btn primary', href: `${GH}/releases/latest`, target: '_blank', rel: 'noopener' }, 'Latest release'),
  ]);
}

const STORE_TARGET = 'caduceus.target';
// Camera selector stays hidden until other cameras have known-good builds (the E-P7 export is used meanwhile).
const SHOW_CAMERA_SELECTOR = false;
function exportDialog() {
  if (!SHOW_CAMERA_SELECTOR) { modal('Export', h('div', { class: 'export' }, ep7Body())); return; }
  let target = targetById((() => { try { return localStorage.getItem(STORE_TARGET); } catch { return null; } })());
  const sel = h('select', {
    'aria-label': 'Camera',
    onchange: () => {
      target = targetById(sel.value);
      try { localStorage.setItem(STORE_TARGET, target.id); } catch { /* private mode */ }
      paint();
    },
  }, ...TARGETS.map((t) => h('option', { value: t.id, disabled: t.status !== 'ready', selected: t.id === target.id },
    t.status === 'ready' ? t.label : `${t.label} (coming soon)`)));
  const soonLinks = h('p', { class: 'help' }, 'Coming soon: ', ...TARGETS.filter((t) => t.status === 'soon').flatMap((t, i) =>
    [i ? ' · ' : '', h('a', { href: t.doc, target: '_blank', rel: 'noopener' }, t.label)]));
  const note = h('p', { class: 'help' });
  const content = h('div', {});
  const paint = () => {
    note.textContent = target.note;
    content.replaceChildren(target.id === 'recipe-card' ? recipeBody() : ep7Body());
  };
  const body = h('div', { class: 'export' },
    h('label', { class: 'field' }, h('span', { class: 'lbl' }, 'Camera'), sel, note), soonLinks, content);
  paint();
  modal('Export', body);
}

function recipeBody(): HTMLElement {
  const fname = (S.pack.name || 'pack').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'pack';
  const l = cur();
  const files = () => targetById('recipe-card').export(S.pack);
  return h('div', {},
    l ? h('pre', { class: 'recipe-card' }, recipeCard(l)) : null,
    h('div', { class: 'ex-row' },
      h('div', {}, h('b', {}, 'This look (.md)'), h('p', { class: 'help' }, `The card above: "${l?.name ?? ''}".`)),
      h('button', { class: 'primary', disabled: !l, onclick: () => { if (l) { const f = files()[S.sel]; download(f.name, f.data, 'text/markdown'); } } }, 'Download')),
    h('div', { class: 'ex-row' },
      h('div', {}, h('b', {}, 'All looks (.zip)'), h('p', { class: 'help' }, `${S.pack.looks.length} cards, one Markdown file per look.`)),
      h('button', {
        disabled: !S.pack.looks.length,
        onclick: () => download(`${fname}-recipes.zip`, makeZip(files().map((f) => ({ name: f.name, data: typeof f.data === 'string' ? new TextEncoder().encode(f.data) : f.data }))), 'application/zip'),
      }, 'Download')));
}

const rrName = (n: string) => n.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'look';
const downloadRr = (i: number) => download(`${rrName(S.pack.looks[i].name)}.rrpreset`, rrpreset(S.pack, i), 'application/json');
const rrFiles = () => S.pack.looks.map((l, i) => ({ name: `${String(i + 1).padStart(2, '0')}-${rrName(l.name)}.rrpreset`, data: new TextEncoder().encode(rrpreset(S.pack, i)) }));
function ep7Body(): HTMLElement {
  const probs = validatePack({ ...S.pack, slots: {} });
  const slotSel = (s: SlotName) => {
    const sel = h('select', {
      onchange: (e: Event) => {
        const v = (e.target as HTMLSelectElement).value;
        if (v === '') delete S.pack.slots[s]; else S.pack.slots[s] = Number(v);
        save();
      },
    }, h('option', { value: '' }, '— stock —'),
    ...S.pack.looks.map((l, i) => (s.startsWith('COLOR') ? l.kind === 'mono' : hasTone(l)) ? null : h('option', { value: i, selected: S.pack.slots[s] === i }, `${i + 1}. ${l.name}`)).filter(Boolean) as HTMLElement[]);
    return h('label', { class: 'slot' }, h('span', {}, s), sel);
  };
  const withBundles = h('input', { type: 'checkbox' });
  const fname = (S.pack.name || 'pack').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'pack';
  const looksBin = () => {
    try { return targetById('ep7-caduceus').export(S.pack)[0].data as Uint8Array; } catch (e) { toast(e instanceof PackError ? 'Fix the problems listed first' : (e as Error).message, 'err'); return null; }
  };
  const packJson = () => JSON.stringify({ ...exportable(S.pack), schema: PACK_SCHEMA }, null, 1) + '\n';
  const body = h('div', { class: 'export' },
    probs.length
      ? h('div', { class: 'problems-box' }, h('b', {}, `${probs.length} problem(s) block LOOKS.BIN:`),
        h('ul', { class: 'problems' }, ...probs.slice(0, 12).map((p) => h('li', {}, fmtProblem(p)))))
      : h('p', { class: 'ok' }, `✓ ${S.pack.looks.length} looks pass the camera's LOOKS.BIN checks (v0.19 firmware).`),
    h('div', { class: 'ex-row' },
      h('div', {}, h('b', {}, 'LOOKS.BIN'), h('p', { class: 'help' }, 'The looks the camera\'s Film page offers. The firmware install already puts the 32 built-in looks on the card; download this only to use your own edits. Copy it to EP7MOD/ on the card (replacing LOOKS.BIN there) and half-press. No re-flash needed.')),
      h('button', { class: 'primary', disabled: probs.length > 0, onclick: () => { const b = looksBin(); if (b) download('LOOKS.BIN', b); } }, 'Download')),
    h('div', { class: 'ex-row' },
      h('div', {}, h('b', {}, 'Pack file (.json)'), h('p', { class: 'help' }, 'Everything, including notes and advice. Open it here later or send it to someone.')),
      h('button', { onclick: () => download(`${fname}.caduceus.json`, packJson(), 'application/json') }, 'Download')),
    h('div', { class: 'ex-row' },
      h('div', {}, h('b', {}, 'RapidRAW presets (.rrpreset)'), h('p', { class: 'help' }, 'One look, or every look as its own preset in a zip, for ORF files or raws from any camera. Unzip, then in RapidRAW: Presets › Import and select the files. Approximate: RapidRAW starts from its own raw rendering, so expect the look\'s character, not an exact match to the camera JPEG.')),
      h('div', { class: 'ex-btns' },
        h('button', { disabled: !cur(), onclick: () => { if (cur()) downloadRr(S.sel); } }, 'This look'),
        h('button', { disabled: !S.pack.looks.length, onclick: () => download(`${fname}-rapidraw.zip`, makeZip(rrFiles()), 'application/zip') }, `All ${S.pack.looks.length} (.zip)`))),
    h('details', { class: 'ex-bundles' },
      h('summary', {}, 'Starter slots (BUNDLES.BIN, optional)'),
      h('p', { class: 'help' }, 'BUNDLES.BIN holds the looks currently in the 8 picture-mode slots. Your card\'s BUNDLES.BIN has your saved slot choices: only replace it if you want to reset them. Empty = the camera\'s stock rendering.'),
      h('div', { class: 'slots' }, ...SLOT_NAMES.map(slotSel))),
    h('div', { class: 'ex-row' },
      h('div', {}, h('b', {}, 'Card folder (.zip)'), h('p', { class: 'help' }, 'EP7MOD/LOOKS.BIN (+ BUNDLES.BIN if ticked) and the pack file. Unzip at the card root.'),
        h('label', { class: 'check' }, withBundles, h('span', {}, 'Include starter BUNDLES.BIN'))),
      h('button', {
        disabled: probs.length > 0, onclick: () => {
          const lb = looksBin();
          if (!lb) return;
          const files = [{ name: 'EP7MOD/LOOKS.BIN', data: lb }];
          if (withBundles.checked) {
            try { files.push({ name: 'EP7MOD/BUNDLES.BIN', data: encodeBundlesBin(S.pack) }); } catch (e) { toast((e as Error).message, 'err'); return; }
          }
          files.push({ name: `${fname}.caduceus.json`, data: new TextEncoder().encode(packJson()) });
          download(`${fname}-card.zip`, makeZip(files), 'application/zip');
        },
      }, 'Download')),
    h('p', { class: 'help' }, 'Copy EP7MOD/ to the root of the card (never into DCOLYMP/). The camera checks every file and ignores one that fails.'));
  return body;
}
const fmtProblem = (p: Problem) => (p.look !== undefined ? `Look ${p.look + 1} (${S.pack.looks[p.look]?.name || 'no name'}): ` : '') + p.message;

// ---------------------------------------------------------------- start
async function handleHash() {
  const code = decodeURIComponent(location.hash.slice(1));
  if (!code) return;
  history.replaceState(null, '', location.pathname + location.search);
  importCodeMsg = (m) => toast(`Link: ${m}`, 'err');
  await importCode(code, true);
  importCodeMsg = (m) => toast(m, 'err');
}

shell();
renderAll();
if (libNotice) toast(libNotice);
undoUi();
handleHash();
window.addEventListener('hashchange', handleHash);
