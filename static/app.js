'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds = {rack:'架子',cabinet:'柜子',shelf:'层',box:'箱子',bag:'袋子',loose:'无包装'};
const icons = {rack:'▤',cabinet:'▥',shelf:'═',box:'▣',bag:'♧',loose:'◌'};
let state = {containers:[],products:[],stocks:[],tags:[],movements:[]}, user, csrf, view = 'inventory', toastTimer;
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 5000); }
async function api(path, method = 'GET', data) {
  const options = {method, headers:{'X-CSRF-Token':csrf || ''}};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) {options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data);}
  const response = await fetch(path, options);
  let result; try { result = await response.json(); } catch { throw new Error('服务器响应异常，请稍后重试'); }
  if (!response.ok) {if (response.status === 401 && path !== '/api/login') showLogin(); throw new Error(result.error || '操作失败');}
  return result;
}
function showLogin() { user = null; csrf = null; $('#app').hidden = true; $('#login-page').hidden = false; $$('dialog[open]').forEach(d => d.close()); }
async function enter(result) { user = result.user; csrf = result.csrf; await reload(); $('#login-page').hidden = true; $('#app').hidden = false; $('#user-label').textContent = `${user.username} · ${user.role === 'owner' ? '主账号' : '家庭成员'}`; $('#members-panel').hidden = user.role !== 'owner'; }
function descendants(ident) { const result = new Set([Number(ident)]); let changed = true; while (changed) {changed = false; for (const c of state.containers) if (result.has(c.parent_id) && !result.has(c.id)) { result.add(c.id); changed = true; }} return result; }
function options(containers, prefix = '<option value="">请选择储存位置</option>') { return prefix + containers.map(c => `<option value="${c.id}">${escapeHTML(c.path)}</option>`).join(''); }
function setOptions(selector, content) {const el = $(selector), value = el.value; el.innerHTML = content; if ([...el.options].some(o => o.value === value)) el.value = value;}
async function reload() {
  state = await api('/api/state');
  setOptions('#product-select', '<option value="">＋ 添加新物品</option>' + state.products.map(p => `<option value="${p.id}">${escapeHTML(p.name)} · ${escapeHTML(p.unit)}${p.mode === 'percent' ? '（独立包装）' : ''}</option>`).join(''));
  setOptions('#tag-filter', '<option value="">全部标签</option>' + state.tags.map(t => `<option>${escapeHTML(t.name)}</option>`).join(''));
  $('#tag-suggestions').innerHTML = state.tags.map(t => `<option value="${escapeHTML(t.name)}"></option>`).join('');
  setOptions('#container-filter', options(state.containers, '<option value="">全部位置（包含下级容器）</option>'));
  const destinations = state.containers.filter(c => !['rack','cabinet'].includes(c.kind));
  setOptions('#intake-container', options(destinations)); setOptions('#action-container', options(destinations));
  updateContainerFields(); render();
}
function render() {
  const percent = state.stocks.filter(s => state.products.find(p => p.id === s.product_id)?.mode === 'percent');
  const stats = [['在库物品',new Set(state.stocks.map(s => s.product_id)).size,'种'],['库存记录',state.stocks.length,'份'],['收纳容器',state.containers.filter(c => c.kind !== 'shelf').length,'个'],['低余量',percent.filter(s => Number(s.quantity) <= 20).length,'份 ≤20%']];
  $('#stats').innerHTML = stats.map(([title,n,unit]) => `<div class="stat"><small>${title}</small><strong>${n}<span>${unit}</span></strong></div>`).join('');
  renderStocks(); renderContainers(); renderActivity();
}
function renderStocks() {
  const q = $('#search').value.trim().toLowerCase(), tag = $('#tag-filter').value, mode = $('#mode-filter').value, container = $('#container-filter').value;
  const places = container ? descendants(container) : null;
  const rows = state.stocks.filter(s => {const p = state.products.find(p => p.id === s.product_id); return p && (!tag || p.tags.includes(tag)) && (!mode || p.mode === mode) && (!places || places.has(s.container_id)) && (!q || [p.name,p.description,s.description,s.path,...p.tags].join(' ').toLowerCase().includes(q));});
  $('#result-count').textContent = `${rows.length} 条库存记录`;
  $('#stock-list').innerHTML = rows.length ? rows.map(s => {
    const p = state.products.find(p => p.id === s.product_id), quantity = Number(s.quantity);
    return `<article class="stock-card"><img class="card-image" loading="lazy" src="/photos/${escapeHTML(p.photo_id)}.jpg" alt="${escapeHTML(p.name)}"><div class="card-content"><div class="card-title"><h3>${escapeHTML(p.name)}</h3><span class="quantity">${quantity}<small>${escapeHTML(p.unit)}</small></span></div>${p.mode === 'percent' ? `<div class="progress"><progress value="${quantity}" max="100" aria-label="剩余百分比"></progress></div>` : ''}<div class="tags">${p.tags.map(t => `<span class="tag">${escapeHTML(t)}</span>`).join('')}</div><p class="path">⌖ ${escapeHTML(s.path)}</p><p class="card-description">${escapeHTML(p.description)}${s.description ? '\n这份库存：' + escapeHTML(s.description) : ''}</p></div><div class="card-actions"><button data-product="${p.id}">资料</button><button data-stock="${s.id}" data-action="withdraw">出库</button><button data-stock="${s.id}" data-action="transfer">转移</button>${p.mode === 'percent' ? `<button data-stock="${s.id}" data-action="estimate">目测余量</button>` : ''}<button class="text-button" data-stock="${s.id}" data-action="clear">清除</button></div></article>`;
  }).join('') : '<div class="empty"><h3>这里还没有物品</h3><p>点击「物品入库」记录第一件物品，或调整筛选条件。</p></div>';
}
function renderContainers() {
  const q = $('#container-search').value.trim().toLowerCase(), kind = $('#kind-filter').value;
  const rows = state.containers.filter(c => (!kind || c.kind === kind) && (!q || [c.path,c.description].join(' ').toLowerCase().includes(q)));
  $('#container-list').innerHTML = rows.length ? rows.map(c => `<article class="container-card">${c.photo_id ? `<img src="/photos/${escapeHTML(c.photo_id)}.jpg" alt="${escapeHTML(c.name)}" loading="lazy">` : `<div class="container-icon" aria-hidden="true">${icons[c.kind]}</div>`}<h3>${escapeHTML(c.name)} <span class="tag">${kinds[c.kind]}</span></h3><p class="path">${escapeHTML(c.path)}</p><p class="card-description">${escapeHTML(c.description)}</p><p class="container-meta">直接库存 ${c.direct_count} 份 · 包含下级共 ${c.total_count} 份</p><div class="card-actions"><button data-container="${c.id}" data-action="inspect">查看物品</button><button data-container="${c.id}" data-action="edit">${c.kind === 'shelf' ? '编辑描述' : '编辑 / 转移'}</button>${c.kind !== 'shelf' ? `<button class="text-button" data-container="${c.id}" data-action="delete">删除</button>` : ''}</div></article>`).join('') : '<div class="empty">没有符合条件的容器</div>';
}
function renderActivity() {
  $('#activity-list').innerHTML = state.movements.length ? `<table><thead><tr><th>物品 / 容器</th><th>操作</th><th>详情</th><th>操作人</th><th>时间</th></tr></thead><tbody>${state.movements.map(m => `<tr><td>${escapeHTML(m.item_name)}</td><td><span class="tag">${escapeHTML(m.action)}</span></td><td>${escapeHTML(m.detail)}</td><td>${escapeHTML(m.username)}</td><td>${escapeHTML(new Date(m.created_at).toLocaleString())}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">完成首次入库后，操作记录会出现在这里。</div>';
}
async function renderMembers() {if (user?.role !== 'owner') return; const result = await api('/api/users'); $('#member-list').innerHTML = result.users.map(u => `<div class="member"><span>${escapeHTML(u.username)} <span class="tag">${u.role === 'owner' ? '主账号' : '普通账号'}</span></span>${u.role === 'member' ? `<button class="danger" data-member="${u.id}" data-name="${escapeHTML(u.username)}">删除</button>` : ''}</div>`).join('');}
async function changeView(value) {
  view = value; const titles = {inventory:['物品库存','家里的东西，都在这里。','查看余量，沿着储存链找到你需要的物品。'],containers:['收纳容器','每件物品，都有归处。','从架子到袋子，管理位置、嵌套关系与容器内的物品。'],activity:['操作记录','每次变化，都有记录。','查看入库、出库、转移和盘点清除的历史。'],account:['家庭账号','与家人，共享有序生活。','管理你的密码，主账号可添加或移除家庭成员。']};
  const [breadcrumb,title,description] = titles[value]; $('#breadcrumb').textContent = breadcrumb; $('#page-title').textContent = title; $('#page-description').textContent = description;
  ['inventory','containers','activity','account'].forEach(v => $(`#${v}-view`).hidden = v !== value);
  $$('[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === value));
  if (value === 'account') await renderMembers();
}
function updateIntakeFields() {
  const form = $('#intake-form'), p = state.products.find(p => p.id === Number($('#product-select').value)), isNew = !p;
  $('#new-product-fields').hidden = !isNew; $('#saved-product-info').hidden = isNew;
  ['name','photo'].forEach(key => form.elements[key].required = isNew);
  const mode = p ? p.mode : $('#intake-mode').value;
  $('#unit-label').hidden = mode === 'percent'; form.elements.unit.required = isNew && mode === 'count';
  form.elements.quantity.max = mode === 'percent' ? '100' : '1000000';
  $('#quantity-label').firstChild.textContent = mode === 'percent' ? '3. 这份包装的剩余百分比（0–100）' : `3. 入库数量${p ? '（' + p.unit + '）' : ''}`;
  if (p) $('#saved-product-info').textContent = `${p.name} · ${p.unit}\n${p.description}\n标签：${p.tags.join('、') || '暂无'}`;
}
function openIntake() {const form = $('#intake-form'); form.reset(); $('.photo-preview',form).hidden = true; updateIntakeFields(); $('#intake-dialog').showModal();}
function updateContainerFields() {
  const form = $('#container-form'), id = Number(form.elements.id.value), kind = form.elements.kind.value;
  const root = ['rack','cabinet'].includes(kind), shelf = kind === 'shelf', existing = Boolean(id);
  $('#levels-label').hidden = !root || existing; form.elements.levels.required = root && !existing;
  $('#container-photo-label').hidden = existing;
  form.elements.photo.required = !existing && !root;
  $('#parent-label').hidden = root || shelf;
  const excluded = id ? descendants(id) : new Set();
  const allowed = kind === 'box' ? ['shelf','box'] : ['shelf','box','bag'];
  setOptions('#container-parent', options(state.containers.filter(c => allowed.includes(c.kind) && !excluded.has(c.id)), '<option value="">地面</option>'));
  $('#floor-label').hidden = shelf || (!root && Boolean(form.elements.parent_id.value));
  form.elements.floor_note.required = !root && !shelf && !form.elements.parent_id.value;
}
function openContainer(id) {
  const form = $('#container-form'); form.reset(); form.elements.id.value = id || ''; form.elements.kind.disabled = Boolean(id);
  const shelfOption = $('#container-kind option[value="shelf"]'); if (shelfOption) shelfOption.remove();
  if (id) { const c = state.containers.find(c => c.id === id); if (c.kind === 'shelf') form.elements.kind.add(new Option('层','shelf')); ['name','kind','description','floor_note'].forEach(k => form.elements[k].value = c[k] || ''); updateContainerFields(); form.elements.parent_id.value = c.parent_id || ''; }
  else form.elements.kind.value = 'box';
  $('.photo-preview',form).hidden = true; updateContainerFields(); $('#container-dialog-title').textContent = id ? '编辑 / 转移容器' : '创建收纳容器'; $('#container-dialog').showModal();
}
function openAction(id, action) {
  const s = state.stocks.find(s => s.id === id), p = state.products.find(p => p.id === s.product_id), form = $('#action-form'); form.reset();
  form.elements.id.value = id; form.elements.action.value = action; form.elements.quantity.value = Number(s.quantity); form.elements.quantity.max = action === 'estimate' ? '100' : Number(s.quantity); form.elements.quantity.min = action === 'estimate' ? '0' : '0.001';
  const titles = {withdraw:'物品出库',transfer:'转移物品',clear:'清除不符记录',estimate:'更新目测余量'};
  $('#action-title').textContent = titles[action]; $('#action-info').textContent = `${p.name} · 现有 ${Number(s.quantity)} ${p.unit}\n储存链：${s.path}`;
  $('#action-quantity-label').hidden = action === 'clear'; form.elements.quantity.required = action !== 'clear';
  $('#action-quantity-label').firstChild.textContent = action === 'estimate' ? '新的剩余百分比' : p.mode === 'percent' ? '使用 / 转移的百分比（百分点）' : `数量（${p.unit}）`;
  $('#action-container-label').hidden = action !== 'transfer'; form.elements.container_id.required = action === 'transfer'; form.elements.description.required = action === 'clear';
  setOptions('#action-container', options(state.containers.filter(c => !['rack','cabinet'].includes(c.kind) && c.id !== s.container_id)));
  $('#action-hint').textContent = action === 'clear' ? '清除会将这份库存归零，物品资料和操作历史仍保留。' : p.mode === 'percent' ? (action === 'transfer' ? '一份百分比包装需要整体转移。' : action === 'estimate' ? '直接填写目测剩余百分比。例如：还剩 40%，填写 40。' : '出库填写使用量。例如：从 80% 用到 60%，填写 20。') : '确认后将更新库存，并写入操作记录。';
  $('#action-dialog').showModal();
}
function confirmDelete(message) {const dialog = $('#confirm-dialog'); $('#confirm-message').textContent = message; dialog.showModal(); return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once:true}));}
async function uploadPhoto(form) {const file = form.elements.photo.files[0]; if (!file) return null; if (file.size > 12 * 1024 * 1024) throw new Error('照片不能超过 12 MB'); const data = new FormData(); data.append('photo',file); return (await api('/api/photos','POST',data)).id;}
function bindForm(selector, handler) {$(selector).addEventListener('submit', async event => {event.preventDefault(); const form = event.currentTarget, button = $('button[type="submit"],button.primary',form); if (button?.disabled) return; if (button) button.disabled = true; try {await handler(form);} catch (error) {toast(error.message); if(selector === '#login-form') $('#login-error').textContent = error.message;} finally {if(button) button.disabled = false;}});}
bindForm('#login-form', async form => {$('#login-error').textContent = ''; await enter(await api('/api/login','POST',Object.fromEntries(new FormData(form)))); form.reset();});
bindForm('#intake-form', async form => {
  const data = Object.fromEntries(new FormData(form)); data.container_id = Number(data.container_id); data.quantity = data.quantity;
  if (data.product_id) data.product_id = Number(data.product_id);
  else {data.photo_id = await uploadPhoto(form); data.tags = [...new Set(data.tags.split(/[,，、]/).map(t => t.trim()).filter(Boolean))];}
  delete data.photo; await api('/api/intake','POST',data); $('#intake-dialog').close(); await reload(); toast('物品已入库');
});
bindForm('#container-form', async form => {
  const data = Object.fromEntries(new FormData(form)), id = Number(data.id); data.parent_id = data.parent_id ? Number(data.parent_id) : null; data.levels = Number(data.levels);
  if (id) {const old = state.containers.find(c => c.id === id); if (old.kind === 'shelf') data.parent_id = old.parent_id;}
  else data.photo_id = await uploadPhoto(form);
  delete data.photo; await api(id ? `/api/containers/${id}` : '/api/containers', id ? 'PUT' : 'POST', data); $('#container-dialog').close(); await reload(); toast('容器已保存');
});
bindForm('#action-form', async form => {const data = Object.fromEntries(new FormData(form)); data.container_id = Number(data.container_id); await api(`/api/stocks/${data.id}/${data.action}`,'POST',data); $('#action-dialog').close(); await reload(); toast('库存已更新');});
bindForm('#product-form', async form => {const data = Object.fromEntries(new FormData(form)); const photo = await uploadPhoto(form); if(photo) data.photo_id = photo; data.tags = [...new Set(data.tags.split(/[,，、]/).map(t => t.trim()).filter(Boolean))]; delete data.photo; await api(`/api/products/${data.id}`,'PUT',data); $('#product-dialog').close(); await reload(); toast('物品资料已保存');});
bindForm('#member-form', async form => {await api('/api/users','POST',Object.fromEntries(new FormData(form))); form.reset(); await renderMembers(); await reload(); toast('家庭账号已创建');});
bindForm('#password-form', async form => {await api('/api/password','POST',Object.fromEntries(new FormData(form))); form.reset(); showLogin(); toast('密码已修改，请重新登录');});
document.addEventListener('click', async event => {
  const button = event.target.closest('button'); if (!button) return;
  try {
    if (button.dataset.close) $( '#' + button.dataset.close).close();
    if (button.dataset.view) await changeView(button.dataset.view);
    if (button.dataset.product) { const p = state.products.find(p => p.id === Number(button.dataset.product)), form = $('#product-form'); form.reset(); ['id','name','description'].forEach(k => form.elements[k].value = p[k]); form.elements.tags.value = p.tags.join(', '); $('.photo-preview',form).hidden = true; $('#product-dialog').showModal(); }
    if (button.dataset.stock) openAction(Number(button.dataset.stock),button.dataset.action);
    if (button.dataset.container) {
      const id = Number(button.dataset.container), action = button.dataset.action;
      if (action === 'inspect') {$('#container-filter').value = String(id); $('#search').value = ''; $('#tag-filter').value = ''; $('#mode-filter').value = ''; renderStocks(); await changeView('inventory');}
      if (action === 'edit') openContainer(id);
      if (action === 'delete' && await confirmDelete('删除这个空容器？有库存或下级容器时无法删除。')) {await api(`/api/containers/${id}`,'DELETE'); await reload(); toast('空容器已删除');}
    }
    if (button.dataset.member && await confirmDelete(`删除账号 ${button.dataset.name}？该账号的所有会话将立即失效。`)) {await api(`/api/users/${button.dataset.member}`,'DELETE'); await renderMembers(); await reload(); toast('账号已删除');}
  } catch(error) {toast(error.message);}
});
$('#new-intake').addEventListener('click',openIntake); $('#new-container').addEventListener('click',() => openContainer()); $('#intake-create-container').addEventListener('click',() => openContainer());
$('#logout').addEventListener('click',async () => {try {await api('/api/logout','POST',{}); showLogin();} catch(e) {toast(e.message);}});
['#search','#tag-filter','#container-filter','#mode-filter'].forEach(s => $(s).addEventListener('input',renderStocks));
['#container-search','#kind-filter'].forEach(s => $(s).addEventListener('input',renderContainers));
$('#product-select').addEventListener('change',updateIntakeFields); $('#intake-mode').addEventListener('change',updateIntakeFields);
$('#container-kind').addEventListener('change',updateContainerFields); $('#container-parent').addEventListener('change',updateContainerFields);
$$('input[type="file"]').forEach(input => input.addEventListener('change', () => {const preview = $('.photo-preview',input.closest('label')); if (preview.dataset.url) URL.revokeObjectURL(preview.dataset.url); if (input.files[0]) {const url = URL.createObjectURL(input.files[0]); preview.src = url; preview.dataset.url = url; preview.hidden = false;} else preview.hidden = true;}));
(async () => {try {await enter(await api('/api/me'));} catch(e) {showLogin(); if(e.message !== '请先登录') toast(e.message);}})();
