/**
 * 管理窗口逻辑。与 Python 的契约见 callname/schemas.py 与 callname/api.py。
 * 每次变更后重新 list_people() 渲染（几十行，无需增量更新）。
 */

const api = () => window.pywebview.api;

/** @typedef {{id:number,name:string,weight:number,active:boolean,draw_count:number,sort_order:number,last_drawn_at:string|null}} PersonItem */
/** @typedef {{total:number,active:number,sum_draws:number,last_draw_at:string|null}} StatsResult */
/** @typedef {{path:string,format:string,count:number,file_dups:number,db_dups:number,unweighted:number,names:string[]}} ImportPreview */

const rowsBody = /** @type {HTMLElement} */ (document.getElementById('rows'));
const emptyHint = /** @type {HTMLElement} */ (document.getElementById('empty'));
const statsEl = /** @type {HTMLElement} */ (document.getElementById('stats'));
const searchEl = /** @type {HTMLInputElement} */ (document.getElementById('search'));
const newNameEl = /** @type {HTMLInputElement} */ (document.getElementById('new-name'));
const newWeightEl = /** @type {HTMLInputElement} */ (document.getElementById('new-weight'));
const addBtn = /** @type {HTMLButtonElement} */ (document.getElementById('add'));
const importBtn = /** @type {HTMLButtonElement} */ (document.getElementById('import'));
const deleteSelectedBtn = /** @type {HTMLButtonElement} */ (document.getElementById('delete-selected'));
const clearCountsBtn = /** @type {HTMLButtonElement} */ (document.getElementById('clear-counts'));
const checkAll = /** @type {HTMLInputElement} */ (document.getElementById('check-all'));

const importModal = /** @type {HTMLElement} */ (document.getElementById('import-modal'));
const confirmModal = /** @type {HTMLElement} */ (document.getElementById('confirm-modal'));

class ApiFailure extends Error {
  constructor(error) {
    super(error.message);
    this.code = error.code;
  }
}

async function unwrap(promise) {
  const response = await promise;
  if (!response || response.ok !== true) {
    throw new ApiFailure((response && response.error) || { code: 'UNKNOWN', message: '未知错误' });
  }
  return response.data;
}

function toast(message) {
  const el = document.getElementById('stats');
  if (!el) return;
  const original = el.dataset.base || el.textContent || '';
  el.dataset.base = original;
  el.textContent = message;
  window.setTimeout(() => { el.textContent = original; }, 2600);
}

/** @param {string|null} iso */
function formatWhen(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
    + `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function weightInput(value, onCommit) {
  const input = document.createElement('input');
  input.type = 'number';
  input.min = '1';
  input.max = '99';
  input.step = '1';
  input.className = 'input input-weight';
  input.value = String(value);
  input.addEventListener('change', () => {
    const next = Number.parseInt(input.value, 10);
    if (!Number.isFinite(next) || next < 1 || next > 99) {
      input.value = String(value);
      toast('权重必须在 1 到 99 之间');
      return;
    }
    onCommit(next, input);
  });
  return input;
}

/** @param {PersonItem} person */
function buildRow(person) {
  const tr = document.createElement('tr');
  if (!person.active) tr.classList.add('inactive');

  const checkCell = document.createElement('td');
  const check = document.createElement('input');
  check.type = 'checkbox';
  check.className = 'row-check';
  check.dataset.id = String(person.id);
  checkCell.appendChild(check);
  tr.appendChild(checkCell);

  const nameCell = document.createElement('td');
  const nameInput = document.createElement('input');
  nameInput.className = 'name-input';
  nameInput.value = person.name;
  nameInput.addEventListener('change', () => {
    const next = nameInput.value.trim();
    if (!next) {
      nameInput.value = person.name;
      toast('姓名不能为空');
      return;
    }
    void updatePerson(person.id, { name: next });
  });
  nameCell.appendChild(nameInput);
  tr.appendChild(nameCell);

  const weightCell = document.createElement('td');
  weightCell.appendChild(weightInput(person.weight, (weight) => {
    void updatePerson(person.id, { weight });
  }));
  tr.appendChild(weightCell);

  const countCell = document.createElement('td');
  countCell.className = 'count';
  countCell.textContent = String(person.draw_count);
  tr.appendChild(countCell);

  const whenCell = document.createElement('td');
  whenCell.className = 'when';
  whenCell.textContent = formatWhen(person.last_drawn_at);
  tr.appendChild(whenCell);

  const activeCell = document.createElement('td');
  const tag = document.createElement('span');
  tag.className = 'tag';
  tag.textContent = person.active ? '启用' : '已停用';
  activeCell.appendChild(tag);
  tr.appendChild(activeCell);

  const actionsCell = document.createElement('td');
  const actions = document.createElement('div');
  actions.className = 'row-actions';
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'icon-btn';
  toggle.textContent = person.active ? '停用' : '启用';
  toggle.addEventListener('click', () => { void setActive(person.id, !person.active); });
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'icon-btn danger';
  remove.textContent = '删除';
  remove.addEventListener('click', () => { void removePerson(person); });
  actions.append(toggle, remove);
  actionsCell.appendChild(actions);
  tr.appendChild(actionsCell);

  return tr;
}

/** @param {PersonItem[]} people */
function renderRows(people) {
  rowsBody.replaceChildren(...people.map(buildRow));
  emptyHint.hidden = people.length > 0;
  checkAll.checked = false;
}

async function loadAll() {
  const query = searchEl.value.trim();
  const [people, stats] = await Promise.all([
    unwrap(api().list_people(query)),
    unwrap(api().stats()),
  ]);
  renderRows(people);
  statsEl.dataset.base = `总人数 ${stats.total} · 启用 ${stats.active} · 累计抽中 ${stats.sum_draws}`;
  statsEl.textContent = statsEl.dataset.base;
}

async function updatePerson(id, patch) {
  try {
    await unwrap(api().update_person(id, patch));
    await loadAll();
  } catch (error) {
    toast(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    await loadAll().catch(() => {});
  }
}

async function setActive(id, active) {
  try {
    await unwrap(api().set_active(id, active));
    await loadAll();
  } catch (error) {
    toast(`操作失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

/** @param {PersonItem} person */
async function removePerson(person) {
  const confirmed = await askConfirm('删除姓名', `确定删除「${person.name}」吗？累计次数会一起删除。`);
  if (!confirmed) return;
  try {
    await unwrap(api().delete_person(person.id));
    await loadAll();
  } catch (error) {
    toast(`删除失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

async function addPerson() {
  const name = newNameEl.value.trim();
  if (!name) {
    toast('请先填写姓名');
    newNameEl.focus();
    return;
  }
  const weight = Number.parseInt(newWeightEl.value, 10) || 1;
  try {
    const result = await unwrap(api().add_person(name, weight));
    if (result.warning === 'DUPLICATE_NAME') {
      toast(`已添加「${name}」（名单中已有同名学生）`);
    }
    newNameEl.value = '';
    newWeightEl.value = '1';
    await loadAll();
  } catch (error) {
    toast(`添加失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

async function deleteSelected() {
  const ids = [...rowsBody.querySelectorAll('.row-check:checked')]
    .map((node) => Number.parseInt(/** @type {HTMLInputElement} */ (node).dataset.id || '', 10))
    .filter((id) => Number.isFinite(id));
  if (!ids.length) {
    toast('先勾选要删除的行');
    return;
  }
  const confirmed = await askConfirm('删除所选', `确定删除选中的 ${ids.length} 人吗？`);
  if (!confirmed) return;
  try {
    await unwrap(api().delete_many(ids));
    await loadAll();
  } catch (error) {
    toast(`删除失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

async function clearCounts() {
  const confirmed = await askConfirm(
    '重置累计次数',
    '将把所有人和抽签日志的累计次数清零。这一步无法撤销，确定继续吗？',
  );
  if (!confirmed) return;
  try {
    const result = await unwrap(api().clear_draw_counts());
    toast(`已清零 ${result.people} 人的累计次数`);
    await loadAll();
  } catch (error) {
    toast(`操作失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

// ---------- 弹层 ----------
/** @type {(() => void) | null} */
let confirmResolve = null;

function askConfirm(title, text) {
  return new Promise((resolve) => {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-text').textContent = text;
    confirmModal.hidden = false;
    confirmResolve = () => { confirmModal.hidden = true; resolve(true); };
    const cancel = () => { confirmModal.hidden = true; resolve(false); };
    const okBtn = /** @type {HTMLButtonElement} */ (document.getElementById('confirm-ok'));
    const cancelBtn = /** @type {HTMLButtonElement} */ (document.getElementById('confirm-cancel'));
    okBtn.onclick = () => { confirmResolve && confirmResolve(); };
    cancelBtn.onclick = cancel;
  });
}

/** @type {{ key: string, preview: ImportPreview } | null} */
let pendingImport = null;

function openImportModal(preview, key) {
  pendingImport = { key, preview };
  document.getElementById('import-title').textContent = '导入预览';
  const facts = document.getElementById('import-facts');
  facts.replaceChildren();
  const entries = [
    ['来源', preview.path],
    ['格式', preview.format],
    ['文件内名字', String(preview.count)],
    ['文件内重复', String(preview.file_dups)],
    ['未写权重', String(preview.unweighted)],
    ['库中已存在', String(preview.db_dups)],
    ['将新增', String(preview.names.length)],
  ];
  for (const [key2, value] of entries) {
    const dt = document.createElement('dt');
    dt.textContent = key2;
    const dd = document.createElement('dd');
    dd.textContent = value;
    facts.append(dt, dd);
  }
  const warning = document.getElementById('import-warning');
  if (preview.format === 'pkl') {
    warning.hidden = false;
    warning.textContent = '导入 .pkl 会执行文件中的代码，请只导入自己生成的文件。';
  } else {
    warning.hidden = true;
  }
  importModal.hidden = false;
}

async function pickImport() {
  try {
    const path = await unwrap(api().pick_import_file());
    if (!path) return;
    const preview = await unwrap(api().preview_import(path));
    openImportModal(preview, path);
  } catch (error) {
    toast(`读取文件失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

async function commitImport() {
  if (!pendingImport) return;
  const dedupe = document.querySelector('input[name="dedupe"]:checked')?.value !== 'overwrite';
  const mode = document.querySelector('input[name="mode"]:checked')?.value === 'replace' ? 'replace' : 'merge';
  const weight = Number.parseInt(
    /** @type {HTMLInputElement} */ (document.getElementById('import-weight')).value,
    10,
  ) || 1;
  const { key } = pendingImport;
  try {
    const result = await unwrap(api().commit_import(key, mode, weight, dedupe));
    importModal.hidden = true;
    pendingImport = null;
    toast(`导入完成：新增 ${result.added}，更新 ${result.updated}，跳过 ${result.skipped}`);
    await loadAll();
  } catch (error) {
    toast(`导入失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

// ---------- 绑定 ----------
function bind() {
  addBtn.addEventListener('click', () => { void addPerson(); });
  newNameEl.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); void addPerson(); }
  });
  importBtn.addEventListener('click', () => { void pickImport(); });
  deleteSelectedBtn.addEventListener('click', () => { void deleteSelected(); });
  clearCountsBtn.addEventListener('click', () => { void clearCounts(); });
  checkAll.addEventListener('change', () => {
    for (const node of rowsBody.querySelectorAll('.row-check')) {
      /** @type {HTMLInputElement} */ (node).checked = checkAll.checked;
    }
  });
  let searchTimer = 0;
  searchEl.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => { void loadAll().catch(() => {}); }, 180);
  });
  document.getElementById('import-cancel')?.addEventListener('click', () => {
    importModal.hidden = true;
    pendingImport = null;
  });
  document.getElementById('import-confirm')?.addEventListener('click', () => { void commitImport(); });
}

async function boot() {
  bind();
  try {
    await loadAll();
  } catch (error) {
    toast(`初始化失败：${error instanceof Error ? error.message : String(error)}`);
  }
}

window.addEventListener('pywebviewready', () => { void boot(); });
