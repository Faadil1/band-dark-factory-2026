(function () {
'use strict';

// ---------------------------------------------------------------- state
const TOKEN_KEY = 'pocketful.token';
const USER_KEY = 'pocketful.user';
const st = { me: null, view: 0, seq: 0, drafts: {}, keys: {} };

const store = {
  get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  del(k) { try { window.localStorage.removeItem(k); } catch (e) { /* ignore */ } },
};
const token = () => store.get(TOKEN_KEY);
function cachedUser() { try { return JSON.parse(store.get(USER_KEY) || 'null'); } catch (e) { return null; } }
function cacheUser(patch) {
  const u = Object.assign({}, cachedUser() || {}, patch || {});
  if (st.me) { u.user_id = st.me.user_id; u.display_name = st.me.display_name; u.handle = st.me.handle; }
  store.set(USER_KEY, JSON.stringify(u));
}

// ---------------------------------------------------------------- dom helpers
function h(tag, attrs) {
  const el = document.createElement(tag);
  let value;
  for (const k of Object.keys(attrs || {})) {
    const v = attrs[k];
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'testid') el.setAttribute('data-testid', v);
    else if (k === 'value') value = v;
    else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  const add = (c) => {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) c.forEach(add);
    else el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  };
  for (let i = 2; i < arguments.length; i++) add(arguments[i]);
  if (value !== undefined) el.value = value;
  return el;
}
function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
function mount(el, ...kids) { clear(el); kids.forEach((k) => k && el.appendChild(k)); }

let uid = 0;
function field(labelText, input, hint) {
  const id = 'f' + (++uid);
  input.id = id;
  return h('div', { class: 'field' },
    h('label', { for: id }, labelText), input, hint ? h('span', { class: 'hint' }, hint) : null);
}

function newKey() {
  const c = window.crypto;
  if (c && c.randomUUID) return c.randomUUID();
  const b = new Uint8Array(16);
  if (c && c.getRandomValues) c.getRandomValues(b); else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}
function canon(v) {
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
  return JSON.stringify(v);
}

// ---------------------------------------------------------------- money & time
const cur = () => (st.me ? st.me.currency : '');
const mu = () => (st.me ? st.me.minor_units : 2);
function fmtDec(n) {
  const m = mu();
  const s = String(Math.abs(n));
  if (m === 0) return s;
  const p = s.padStart(m + 1, '0');
  return p.slice(0, p.length - m) + '.' + p.slice(p.length - m);
}
const fmt = (n) => fmtDec(n) + ' ' + cur();

class UserError extends Error {}

function parseAmount(text) {
  const t = String(text).trim();
  if (t === '') throw new UserError('Enter an amount.');
  const m = /^(\d+)(?:\.(\d+))?$/.exec(t);
  if (!m) throw new UserError('Enter the amount as a number, for example ' + exampleAmount() + '.');
  const frac = m[2] || '';
  if (frac.length > mu()) {
    throw new UserError(mu() === 0 ? cur() + ' amounts have no decimal places.' : 'Use at most ' + mu() + ' decimal places for ' + cur() + '.');
  }
  const minor = BigInt(m[1]) * (10n ** BigInt(mu())) + BigInt(mu() === 0 ? '0' : frac.padEnd(mu(), '0'));
  if (minor < 1n) throw new UserError('The amount must be greater than zero.');
  if (minor > 1000000000n) throw new UserError('That amount is too large. The maximum is ' + fmt(1000000000) + '.');
  return Number(minor);
}
function exampleAmount() { return mu() === 0 ? '15' : '15.' + '00'.padEnd(mu(), '0').slice(0, mu()); }

function fmtTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try { return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }); } catch (e) { return d.toString(); }
}
function relTime(iso) {
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return '';
  const a = Math.abs(ms);
  const unit = a < 60000 ? 'less than a minute' : a < 3600000 ? Math.round(a / 60000) + ' min' : a < 86400000 ? Math.round(a / 3600000) + ' h' : Math.round(a / 86400000) + ' d';
  return ms > 0 ? 'in ' + unit : unit + ' ago';
}
function timeEl(iso) { return h('time', { datetime: iso, title: iso }, fmtTime(iso)); }

const normHandle = (v) => String(v).trim().replace(/^@/, '').toLowerCase();

// ---------------------------------------------------------------- api
async function api(method, path, opts) {
  opts = opts || {};
  const headers = { Accept: 'application/json' };
  const t = token();
  if (t && opts.auth !== false) headers.Authorization = 'Bearer ' + t;
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.key) headers['Idempotency-Key'] = opts.key;
  const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), 20000) : null;
  try {
    let res;
    let text;
    try {
      res = await fetch(path, { method, headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body), signal: ctrl ? ctrl.signal : undefined, cache: 'no-store' });
      text = await res.text();
    } catch (e) {
      return { kind: 'unknown', status: 0 };
    }
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = undefined; }
    if (res.status >= 500) return { kind: 'unknown', status: res.status };
    if (res.ok) {
      if (data === undefined) return { kind: 'unknown', status: res.status };
      return { kind: 'ok', status: res.status, data };
    }
    const err = (data && data.error) || {};
    if (res.status === 401 && t && opts.auth !== false) { endSession('Your session has ended. Please sign in again.'); }
    return { kind: 'refused', status: res.status, code: err.code || 'error', message: err.message || '' };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

const MESSAGES = {
  insufficient_funds: 'There aren’t enough available funds for this. Money that is on hold can’t be spent.',
  self_payment: 'You can’t send money to yourself.',
  self_request: 'You can’t request money from yourself.',
  request_not_pending: 'That request has already been settled, so nothing changed.',
  authorization_not_open: 'That authorisation is no longer open, so nothing changed.',
  authorization_expired: 'That authorisation has expired and its funds were released.',
  capture_exceeds_authorization: 'That is more than the amount still held. Lower the amount and try again.',
  forbidden: 'You’re not allowed to do that.',
  idempotency_key_reuse: 'That attempt conflicts with an earlier one. Change a detail and try again.',
  email_taken: 'That email address is already registered. Try signing in instead.',
  handle_taken: 'The handle that would be created from that email is already taken. Try a different email address.',
  unauthenticated: 'Those details don’t match an account.',
};
function errText(r, ctx) {
  ctx = ctx || {};
  if (r.code === 'not_found') return ctx.notFound || 'We couldn’t find that.';
  if (r.code === 'validation_failed') return r.message ? cap(r.message) + '.' : 'Please check the details and try again.';
  if (r.code === 'malformed_request') return 'Something in that form wasn’t understood. Please check it and try again.';
  return MESSAGES[r.code] || (r.message ? cap(r.message) : 'Something went wrong. Please try again.');
}
function cap(s) { s = String(s).replace(/\.$/, ''); return s.charAt(0).toUpperCase() + s.slice(1); }

// ---------------------------------------------------------------- feedback elements
function notice(kind, testid, text, extra) {
  const icon = { error: '!', ok: '✓', unsure: '?', info: 'i' }[kind];
  return h('div', { class: 'notice ' + kind, role: kind === 'error' ? 'alert' : 'status', testid },
    h('span', { class: 'icon', 'aria-hidden': 'true' }, icon), h('div', null, text, extra));
}

// ---------------------------------------------------------------- write helper
// A form that submits one idempotent write. Keeps the key and body of the last
// attempt so that an unchanged resubmission never sends a second payment and an
// uncertain outcome is retried with the same key and body.
function attachWriter(cfg) {
  const att = { key: null, canon: null, state: 'none', dirty: false, busy: false };
  const { form, btn, box, prefix } = cfg;
  const mark = () => { att.dirty = true; };
  form.addEventListener('input', mark);
  form.addEventListener('change', mark);
  const show = (kind, text, extra) => {
    mount(box, kind === 'loading' ? h('div', { class: 'notice info', role: 'status' }, h('span', { class: 'icon', 'aria-hidden': 'true' }, '…'), h('div', null, text))
      : notice(kind, prefix + '-' + (kind === 'ok' ? 'success' : kind === 'unsure' ? 'uncertain' : 'error'), text, extra));
  };
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (att.busy) return;
    let body;
    try { body = cfg.build(); } catch (e) {
      if (e instanceof UserError) { show('error', e.message); return; }
      throw e;
    }
    const c = canon(body);
    let key;
    if (att.key && att.canon === c && att.state === 'uncertain') {
      key = att.key;
    } else if (att.key && att.canon === c && att.state === 'success' && !att.dirty) {
      show('ok', cfg.repeatText);
      return;
    } else {
      key = newKey();
    }
    att.key = key; att.canon = c; att.dirty = false; att.busy = true;
    const view = st.view;
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    show('loading', cfg.busyText);
    const r = await api('POST', cfg.path, { body, key });
    att.busy = false;
    btn.disabled = false;
    btn.removeAttribute('aria-busy');
    if (r.kind === 'ok') {
      att.state = 'success';
      btn.textContent = cfg.label;
      if (view !== st.view) return;
      show('ok', cfg.successText(r.data), cfg.successExtra ? cfg.successExtra(r.data) : null);
      await cfg.refresh();
    } else if (r.kind === 'refused') {
      att.state = 'failed';
      btn.textContent = cfg.label;
      if (view !== st.view) return;
      show('error', errText(r, cfg.errCtx));
      if (cfg.refreshOnRefuse) await cfg.refresh();
    } else {
      att.state = 'uncertain';
      btn.textContent = cfg.retryLabel;
      if (view !== st.view) return;
      show('unsure', cfg.uncertainText + ' Retrying sends the same ' + cfg.noun + ' with the same reference, so it can only happen once.');
    }
  });
}

// ---------------------------------------------------------------- session & router
function endSession(message) {
  store.del(TOKEN_KEY);
  store.del(USER_KEY);
  st.me = null;
  st.flash = message || null;
  navigate('/login', true);
}

function navigate(path, replace) {
  if (replace) window.history.replaceState(null, '', path); else window.history.pushState(null, '', path);
  render();
}

document.addEventListener('click', (ev) => {
  const a = ev.target.closest && ev.target.closest('a[data-link]');
  if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
  ev.preventDefault();
  const href = a.getAttribute('href');
  if (href !== window.location.pathname) navigate(href); else render();
});
window.addEventListener('popstate', render);

const root = document.getElementById('app');

const NAV = [['/', 'Home'], ['/requests', 'Requests'], ['/authorizations', 'Authorisations'], ['/split', 'Split']];

function headerView(path) {
  const u = cachedUser() || {};
  const name = (st.me && st.me.display_name) || u.display_name || '';
  const handle = (st.me && st.me.handle) || u.handle || '';
  return h('header', { class: 'topbar', id: 'topbar' },
    h('div', { class: 'topbar-in' },
      h('a', { class: 'brand', href: '/', 'data-link': true }, h('img', { src: '/favicon.svg', alt: '' }), 'Pocketful'),
      h('nav', { class: 'nav', 'aria-label': 'Main' },
        NAV.map(([p, label]) => h('a', { href: p, 'data-link': true, 'aria-current': p === path ? 'page' : null }, label))),
      h('div', { class: 'who' },
        h('span', { class: 'name', testid: 'current-user' }, name || 'Signed in'),
        handle ? h('span', { class: 'handle' }, h('span', { 'aria-hidden': 'true' }, '@'), h('span', { testid: 'current-handle' }, handle)) : null,
        h('button', { class: 'secondary small', type: 'button', testid: 'logout-button', onclick: () => endSession('You have been signed out.') }, 'Sign out'))));
}
function updateHeader() {
  const old = document.getElementById('topbar');
  if (old) old.replaceWith(headerView(window.location.pathname));
}

function shell(path, ...kids) {
  const main = h('main', { id: 'main', tabindex: '-1' }, kids);
  mount(root, headerView(path), main);
  return main;
}

function pageHead(title, sub, extra) {
  return h('div', { class: 'page-head' }, h('div', null, h('h1', null, title), sub ? h('p', null, sub) : null), extra);
}

function failView(retry, text) {
  return h('div', { class: 'card' },
    notice('error', 'load-error', text || 'We couldn’t load this right now. Check your connection and try again.'),
    h('div', { class: 'actions' }, h('button', { type: 'button', onclick: retry }, 'Try again')));
}

async function loadMe() {
  const r = await api('GET', '/me');
  if (r.kind === 'ok') { st.me = r.data; cacheUser(); updateHeader(); }
  return r;
}

const TITLES = { '/': 'Wallet', '/requests': 'Requests', '/split': 'Split a bill', '/signup': 'Create account', '/login': 'Sign in', '/authorizations': 'Authorisations' };

async function render() {
  const view = ++st.view;
  let path = window.location.pathname.replace(/\/+$/, '') || '/';
  const pages = { '/': homePage, '/requests': requestsPage, '/split': splitPage, '/signup': authPage, '/login': authPage, '/authorizations': authsPage };
  document.title = (TITLES[path] || 'Not found') + ' · Pocketful';
  const page = pages[path];
  const signedIn = !!token();
  if (path === '/signup' || path === '/login') {
    if (signedIn) { navigate('/', true); return; }
    authPage(path, view);
    return;
  }
  if (!signedIn) { navigate('/login', true); return; }
  if (!page) {
    shell(path, h('div', { class: 'card' }, h('h1', null, 'Page not found'), h('p', null, 'That page doesn’t exist.'), h('a', { class: 'btn', href: '/', 'data-link': true }, 'Back to your wallet')));
    return;
  }
  const ctx = { view, path };
  if (!st.me) {
    shell(path, pageHead(TITLES[path]), h('div', { class: 'card', 'aria-busy': 'true' }, h('div', { class: 'skeleton big' }), h('div', { class: 'skeleton line' })));
    const r = await loadMe();
    if (view !== st.view) return;
    if (r.kind !== 'ok') {
      if (r.kind === 'refused') return; // session handling already navigated
      shell(path, pageHead(TITLES[path]), failView(render));
      return;
    }
  }
  page(path, view, ctx);
  const hd = document.querySelector('main h1');
  if (hd) { hd.setAttribute('tabindex', '-1'); hd.focus({ preventScroll: true }); }
}

// ---------------------------------------------------------------- auth pages
function authPage(path, view) {
  const signup = path === '/signup';
  const email = h('input', { type: 'email', autocomplete: 'email', testid: (signup ? 'signup' : 'login') + '-email', autocapitalize: 'none', spellcheck: 'false' });
  const password = h('input', { type: 'password', autocomplete: signup ? 'new-password' : 'current-password', testid: (signup ? 'signup' : 'login') + '-password' });
  const name = signup ? h('input', { type: 'text', autocomplete: 'name', testid: 'signup-display-name' }) : null;
  const submit = h('button', { type: 'submit', testid: signup ? 'signup-submit' : 'login-submit' }, signup ? 'Create account' : 'Sign in');
  const box = h('div', { 'aria-live': 'polite' });
  if (st.flash) { mount(box, notice('info', null, st.flash)); st.flash = null; }
  const form = h('form', { novalidate: true, 'aria-label': signup ? 'Create account' : 'Sign in' },
    signup ? field('Display name', name) : null,
    field('Email', email),
    field('Password', password, signup ? 'At least 8 characters.' : null),
    box,
    submit);
  let busy = false;
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (busy) return;
    const fail = (msg) => mount(box, notice('error', 'auth-error', msg));
    if (!email.value.trim() || !password.value || (signup && !name.value.trim())) { fail('Please fill in every field.'); return; }
    busy = true; submit.disabled = true;
    mount(box, h('div', { class: 'notice info', role: 'status' }, h('span', { class: 'icon', 'aria-hidden': 'true' }, '…'), h('div', null, signup ? 'Creating your account…' : 'Signing in…')));
    const body = signup ? { email: email.value.trim(), password: password.value, display_name: name.value } : { email: email.value.trim(), password: password.value };
    const r = await api('POST', signup ? '/auth/signup' : '/auth/login', { body, auth: false });
    busy = false; submit.disabled = false;
    if (view !== st.view) return;
    if (r.kind === 'ok') {
      store.set(TOKEN_KEY, r.data.token);
      store.set(USER_KEY, JSON.stringify({ user_id: r.data.user_id, display_name: r.data.display_name }));
      st.me = null;
      navigate('/');
    } else if (r.kind === 'refused') {
      fail(signup && r.code === 'unauthenticated' ? errText(r) : r.code === 'validation_failed' && signup ? 'Use a valid email address and a password of at least 8 characters.' : errText(r));
    } else {
      fail('We couldn’t reach Pocketful. Check your connection and try again.');
    }
  });
  mount(root,
    h('div', { class: 'auth-wrap', id: 'main' },
      h('a', { class: 'brand', href: '/', 'data-link': true }, h('img', { src: '/favicon.svg', alt: '' }), 'Pocketful'),
      h('div', { class: 'card' },
        h('header', null, h('h1', null, signup ? 'Create your account' : 'Welcome back'),
          h('p', null, signup ? 'Send, request and split money with a handle.' : 'Sign in to your Pocketful wallet.')),
        form),
      h('p', { class: 'small-note', style: null },
        signup ? 'Already have an account? ' : 'New to Pocketful? ',
        h('a', { href: signup ? '/login' : '/signup', 'data-link': true }, signup ? 'Sign in' : 'Create an account'))));
}

// ---------------------------------------------------------------- shared views
function walletView(me, onRefresh, busy) {
  return h('div', { class: 'wallet', 'aria-busy': busy ? 'true' : null },
    h('div', { class: 'headline-label' }, 'Available to spend'),
    h('div', { class: 'headline', testid: 'wallet-available', 'data-amount': me.available }, fmt(me.available)),
    h('div', { class: 'secondary' },
      h('div', null, h('span', { class: 'label' }, 'Total'), h('span', { class: 'value', testid: 'wallet-balance', 'data-amount': me.total }, fmt(me.total))),
      me.held > 0 ? h('div', { class: 'held' }, h('span', { class: 'label' }, 'On hold'), h('span', { class: 'value', testid: 'wallet-held', 'data-amount': me.held }, fmt(me.held))) : null));
}

function walletCard(ctx, refresh) {
  const holder = h('div', null);
  const status = h('div', { 'aria-live': 'polite' });
  const btn = h('button', { class: 'secondary small', type: 'button', testid: 'wallet-refresh', onclick: () => refresh() }, 'Refresh');
  const card = h('section', { class: 'card', 'aria-label': 'Wallet' }, holder, status, h('div', { class: 'wallet-actions' }, btn));
  const api_ = {
    card,
    paint() {
      if (st.me) mount(holder, walletView(st.me));
      else mount(holder, h('div', { 'aria-busy': 'true' }, h('div', { class: 'skeleton big' }), h('div', { class: 'skeleton line' })));
    },
    busy(b) { btn.textContent = b ? 'Refreshing…' : 'Refresh'; holder.setAttribute('aria-busy', b ? 'true' : 'false'); },
    error(on) {
      if (!on) { clear(status); return; }
      mount(status, notice('error', 'refresh-error', 'We couldn’t refresh just now. What you see may be out of date.'));
    },
  };
  api_.paint();
  return api_;
}

// Latest refresh wins: each refresh takes a sequence number and only the newest may apply.
function makeRefresher(ctx, path, wallet, apply, onState) {
  return async function refresh() {
    const my = ++st.seq;
    wallet.busy(true);
    if (onState) onState('loading');
    const [m, d] = await Promise.all([api('GET', '/me'), api('GET', path)]);
    if (my !== st.seq || ctx.view !== st.view) return;
    wallet.busy(false);
    if (m.kind !== 'ok' || d.kind !== 'ok') {
      wallet.error(true);
      if (onState) onState('error');
      return;
    }
    wallet.error(false);
    st.me = m.data;
    cacheUser();
    updateHeader();
    wallet.paint();
    apply(d.data);
    if (onState) onState('ready');
  };
}

function amountInput(testid) {
  return h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', testid, placeholder: exampleAmount() });
}
function handleInput(testid) {
  return h('input', { type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', testid, placeholder: 'e.g. bob' });
}
function visibilitySelect(testid, value) {
  return h('select', { testid, value: value || 'public' },
    h('option', { value: 'public' }, 'Public – shown in the feed'),
    h('option', { value: 'private' }, 'Private – only you and the recipient'));
}
function checkNote(v) {
  if (Array.from(v).length > 200) throw new UserError('Notes can be at most 200 characters.');
  return v;
}
function needHandle(v, what) {
  const hd = normHandle(v);
  if (!hd) throw new UserError('Enter ' + what + '’s handle.');
  if (st.me && hd === st.me.handle) throw new UserError(what === 'who to pay' ? 'You can’t send money to yourself.' : 'You can’t use your own handle here.');
  return hd;
}

function moneyForm(o) {
  const handle = handleInput(o.prefix + '-handle');
  const amount = amountInput(o.prefix + '-amount');
  const note = h('input', { type: 'text', autocomplete: 'off', testid: o.prefix + '-note', placeholder: 'What is it for? (optional)' });
  const vis = o.visibility ? visibilitySelect(o.prefix + '-visibility') : null;
  const btn = h('button', { type: 'submit', testid: o.prefix + '-submit' }, o.label);
  const box = h('div', { 'aria-live': 'polite' });
  const form = h('form', { novalidate: true, 'aria-label': o.title },
    field(o.handleLabel, handle),
    h('div', { class: 'row two' }, field('Amount (' + cur() + ')', amount), vis ? field('Who can see it', vis) : null),
    field('Note', note),
    box, h('div', { class: 'actions' }, btn));
  attachWriter({
    form, btn, box, prefix: o.prefix, path: o.path, label: o.label, retryLabel: o.retryLabel, noun: o.noun,
    busyText: o.busyText, repeatText: o.repeatText, uncertainText: o.uncertainText, errCtx: { notFound: 'No one has that handle. Check the spelling and try again.' },
    refreshOnRefuse: o.refreshOnRefuse, refresh: o.refresh,
    build() {
      const body = {};
      body[o.handleField] = needHandle(handle.value, o.who);
      body.amount = parseAmount(amount.value);
      body.note = checkNote(note.value);
      if (vis) body.visibility = vis.value;
      return body;
    },
    successText: o.successText,
    successExtra: o.successExtra,
  });
  return h('section', { class: 'card', 'aria-label': o.title },
    h('header', null, h('h2', null, o.title), h('p', null, o.sub)), form);
}

function payForm(ctx) {
  return moneyForm({
    prefix: 'pay', title: 'Send money', sub: 'Pay someone instantly by handle.', handleLabel: 'Recipient handle', handleField: 'to_handle', who: 'who to pay',
    path: '/payments', visibility: true, label: 'Send payment', retryLabel: 'Retry payment', noun: 'payment', busyText: 'Sending payment…',
    repeatText: 'That payment was already sent. Change a detail to send another.',
    uncertainText: 'We couldn’t confirm whether your payment went through.',
    refreshOnRefuse: true, refresh: ctx.refresh,
    successText: (p) => 'Sent ' + fmt(p.amount) + ' to @' + p.to_handle + '.',
  });
}
function requestForm(ctx) {
  return moneyForm({
    prefix: 'request', title: 'Request money', sub: 'Ask someone to pay you. They choose whether it’s public.', handleLabel: 'Who should pay (handle)', handleField: 'payer_handle', who: 'who to ask',
    path: '/requests', visibility: false, label: 'Send request', retryLabel: 'Retry request', noun: 'request', busyText: 'Sending request…',
    repeatText: 'That request was already sent. Change a detail to send another.',
    uncertainText: 'We couldn’t confirm whether your request was sent.',
    refreshOnRefuse: false, refresh: ctx.refresh,
    successText: (r) => 'Requested ' + fmt(r.amount) + ' from @' + r.payer_handle + '.',
    successExtra: () => h('span', null, ' ', h('a', { href: '/requests', 'data-link': true }, 'View requests')),
  });
}
function authorizeForm(ctx) {
  return moneyForm({
    prefix: 'authorize', title: 'Reserve funds', sub: 'Hold money for someone to collect later, in one or more captures. Held money can’t be spent elsewhere.', handleLabel: 'Recipient handle', handleField: 'to_handle', who: 'who to pay',
    path: '/authorizations', visibility: true, label: 'Place hold', retryLabel: 'Retry hold', noun: 'authorisation', busyText: 'Placing hold…',
    repeatText: 'That hold was already placed. Change a detail to place another.',
    uncertainText: 'We couldn’t confirm whether your hold was placed.',
    refreshOnRefuse: true, refresh: ctx.refresh,
    successText: (a) => 'Holding ' + fmt(a.amount) + ' for @' + a.to_handle + '.',
    successExtra: () => h('span', null, ' ', h('a', { href: '/authorizations', 'data-link': true }, 'View authorisations')),
  });
}

// ---------------------------------------------------------------- home
function paymentItem(p) {
  const me = st.me;
  const sent = p.from_user_id === me.user_id;
  const recv = p.to_user_id === me.user_id;
  const tag = p.settlement_id ? 'Settlement' : p.authorization_id ? 'Captured hold' : p.request_id ? 'Paid request' : null;
  return h('li', { class: 'item ' + (sent ? 'sent' : recv ? 'received' : ''), testid: 'activity-item-' + p.payment_id, 'data-visibility': p.visibility },
    h('div', { class: 'item-top' },
      h('div', { class: 'parties', testid: 'activity-parties-' + p.payment_id }, '@' + p.from_handle + ' → @' + p.to_handle),
      h('div', { class: 'amount', testid: 'activity-amount-' + p.payment_id }, fmt(p.amount))),
    h('p', { class: 'note', testid: 'activity-note-' + p.payment_id }, p.note),
    h('div', { class: 'meta' },
      sent ? h('span', { class: 'badge dir' }, 'You sent') : recv ? h('span', { class: 'badge dir' }, 'You received') : null,
      h('span', { class: 'badge ' + p.visibility }, p.visibility === 'public' ? '◯ Public' : '● Private'),
      tag ? h('span', { class: 'badge dir' }, tag) : null,
      timeEl(p.created_at)));
}

function homePage(path, view, ctx) {
  const feed = { items: [], more: false };
  const feedBox = h('div', null);
  const moreBtn = h('button', { class: 'secondary', type: 'button' }, 'Show older payments');
  let feedReady = false;
  function paintFeed() {
    if (!feedReady) {
      mount(feedBox, h('div', { 'aria-busy': 'true' }, h('div', { class: 'skeleton line' }), h('div', { class: 'skeleton line' }), h('div', { class: 'skeleton line' })));
      return;
    }
    if (!feed.items.length) {
      mount(feedBox, h('div', { class: 'empty', testid: 'empty-activity' }, h('strong', null, 'No payments yet'), h('span', null, 'Payments you send, receive or that are public will show up here.')));
      return;
    }
    mount(feedBox, h('ul', { class: 'list', testid: 'activity-list' }, feed.items.map(paymentItem)), feed.more ? h('div', { class: 'actions' }, moreBtn) : null);
  }
  paintFeed();
  const wallet = walletCard(ctx, () => refresh());
  const refresh = makeRefresher(ctx, '/activity?limit=200', wallet, (d) => {
    feed.items = d.payments; feed.more = d.has_more; feedReady = true; paintFeed();
  }, (state) => { if (state === 'error' && !feedReady) { feedReady = false; } });
  ctx.refresh = refresh;
  moreBtn.addEventListener('click', async () => {
    moreBtn.disabled = true;
    const r = await api('GET', '/activity?limit=200&offset=' + feed.items.length);
    if (ctx.view !== st.view) return;
    if (r.kind === 'ok') { feed.items = feed.items.concat(r.data.payments); feed.more = r.data.has_more; paintFeed(); } else { moreBtn.disabled = false; }
  });
  const main = shell(path,
    pageHead('Your wallet', 'Send, request and reserve money.'),
    h('div', { class: 'grid-2' },
      h('div', { class: 'col' }, wallet.card, payForm(ctx), requestForm(ctx), authorizeForm(ctx)),
      h('div', { class: 'col' }, h('section', { class: 'card', 'aria-label': 'Activity' },
        h('header', null, h('h2', null, 'Activity'), h('p', null, 'Public payments and everything you’re part of, newest first.')), feedBox))));
  void main;
  refresh();
}

// ---------------------------------------------------------------- requests
function requestsPage(path, view, ctx) {
  const data = { incoming: [], outgoing: [], ready: false };
  const incomingList = h('ul', { class: 'list', testid: 'incoming-list' });
  const outgoingList = h('ul', { class: 'list', testid: 'outgoing-list' });
  const emptyBox = h('div', null);
  const inNote = h('p', { class: 'small-note' });
  const outNote = h('p', { class: 'small-note' });
  const feedback = h('div', { 'aria-live': 'polite' });
  const inCount = h('span', { class: 'count' });
  const outCount = h('span', { class: 'count' });
  const skeleton = h('div', { class: 'card', 'aria-busy': 'true' }, h('div', { class: 'skeleton line' }), h('div', { class: 'skeleton line' }));
  const body = h('div', { class: 'col' });

  const show = (kind, id, text) => mount(feedback, notice(kind, id, text));

  async function act(r, kind) {
    const view0 = st.view;
    const id = r.request_id;
    const itemBusy = (b) => { const li = document.querySelector('[data-testid="request-item-' + id + '"]'); if (li) li.querySelectorAll('button').forEach((x) => { x.disabled = b; }); };
    itemBusy(true);
    let res;
    if (kind === 'pay') {
      const vis = (st.drafts['vis-' + id]) || 'public';
      const body_ = { visibility: vis };
      const c = canon(body_);
      const k = st.keys[id];
      const key = k && k.canon === c && k.state === 'uncertain' ? k.key : newKey();
      st.keys[id] = { key, canon: c, state: 'sending' };
      res = await api('POST', '/requests/' + encodeURIComponent(id) + '/pay', { body: body_, key });
      st.keys[id].state = res.kind === 'unknown' ? 'uncertain' : 'done';
    } else {
      res = await api('POST', '/requests/' + encodeURIComponent(id) + '/' + kind);
    }
    if (view0 !== st.view) return;
    if (res.kind === 'ok') {
      const verb = { pay: 'Paid', decline: 'Declined', cancel: 'Cancelled' }[kind];
      show('ok', 'request-success', verb + ' the request for ' + fmt(r.amount) + (kind === 'pay' ? ' to @' + r.requester_handle : '') + '.');
    } else if (res.kind === 'refused') {
      show('error', 'request-error', errText(res, { notFound: 'That request no longer exists.' }));
    } else {
      show('unsure', 'request-uncertain', kind === 'pay'
        ? 'We couldn’t confirm whether that payment went through. Press Pay again to retry with the same reference – it can only be paid once.'
        : 'We couldn’t confirm whether that worked. The list below has been refreshed.');
    }
    await refresh();
  }

  function item(r, incoming) {
    const id = r.request_id;
    const pending = r.status === 'pending';
    const who = incoming ? r.requester_handle : r.payer_handle;
    let visSel = null;
    if (incoming && pending) {
      visSel = visibilitySelect('request-visibility-' + id, st.drafts['vis-' + id] || 'public');
      visSel.addEventListener('change', () => { st.drafts['vis-' + id] = visSel.value; });
    }
    return h('li', { class: 'item', testid: 'request-item-' + id, 'data-status': r.status },
      h('div', { class: 'item-top' },
        h('div', { class: 'parties' }, incoming ? '@' + who + ' is asking you' : 'You asked @' + who),
        h('div', { class: 'amount', testid: 'request-amount-' + id }, fmt(r.amount))),
      r.note ? h('p', { class: 'note' }, r.note) : null,
      h('div', { class: 'meta' }, h('span', { class: 'badge ' + r.status }, r.status.charAt(0).toUpperCase() + r.status.slice(1)),
        h('span', { class: 'badge dir' }, incoming ? 'Incoming' : 'Outgoing'), timeEl(r.created_at)),
      pending && incoming ? h('div', { class: 'item-actions' },
        field('Who can see the payment', visSel),
        h('button', { type: 'button', testid: 'request-pay-' + id, onclick: () => act(r, 'pay') }, 'Pay ' + fmt(r.amount)),
        h('button', { type: 'button', class: 'danger', testid: 'request-decline-' + id, onclick: () => act(r, 'decline') }, 'Decline')) : null,
      pending && !incoming ? h('div', { class: 'item-actions' },
        h('button', { type: 'button', class: 'danger', testid: 'request-cancel-' + id, onclick: () => act(r, 'cancel') }, 'Cancel request')) : null);
  }

  function paint() {
    if (!data.ready) { mount(body, skeleton); return; }
    const none = !data.incoming.length && !data.outgoing.length;
    mount(incomingList, ...data.incoming.map((r) => item(r, true)));
    mount(outgoingList, ...data.outgoing.map((r) => item(r, false)));
    inCount.textContent = String(data.incoming.length);
    outCount.textContent = String(data.outgoing.length);
    inNote.textContent = !none && !data.incoming.length ? 'Nothing incoming.' : '';
    outNote.textContent = !none && !data.outgoing.length ? 'Nothing outgoing.' : '';
    mount(emptyBox, none ? h('div', { class: 'empty', testid: 'empty-requests' }, h('strong', null, 'No requests yet'), h('span', null, 'Requests you send or receive will appear here.'),
      h('a', { class: 'btn secondary', href: '/', 'data-link': true }, 'Request money')) : null);
    mount(body, emptyBox,
      h('section', { class: 'card', 'aria-label': 'Incoming requests' }, h('div', { class: 'section-title' }, h('h2', null, 'Incoming'), inCount), inNote, incomingList),
      h('section', { class: 'card', 'aria-label': 'Outgoing requests' }, h('div', { class: 'section-title' }, h('h2', null, 'Outgoing'), outCount), outNote, outgoingList));
  }

  const wallet = walletCard(ctx, () => refresh());
  const refresh = makeRefresher(ctx, '/requests?limit=200', wallet, (d) => {
    data.incoming = d.requests.filter((r) => r.payer_id === st.me.user_id);
    data.outgoing = d.requests.filter((r) => r.requester_id === st.me.user_id);
    data.ready = true;
    paint();
  });
  paint();
  shell(path,
    pageHead('Requests', 'Money you’ve been asked for and money you’ve asked for.', h('a', { class: 'btn secondary', href: '/', 'data-link': true }, 'New request')),
    wallet.card, feedback, body);
  refresh();
}

// ---------------------------------------------------------------- split
function splitPage(path, view, ctx) {
  const amount = amountInput('split-amount');
  const handles = h('input', { type: 'text', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', testid: 'split-handles', placeholder: 'ada, bob, cy' });
  const note = h('input', { type: 'text', autocomplete: 'off', testid: 'split-note', placeholder: 'What was it for? (optional)' });
  const preview = h('div', { class: 'preview', testid: 'split-preview', 'aria-live': 'polite' });
  const btn = h('button', { type: 'submit', testid: 'split-submit' }, 'Split and request');
  const box = h('div', { 'aria-live': 'polite' });

  function parseHandles() {
    return handles.value.split(',').map(normHandle).filter((x) => x.length > 0);
  }
  function shares() {
    const hs = parseHandles();
    if (!hs.length) throw new UserError('Add at least one handle, separated by commas.');
    if (new Set(hs).size !== hs.length) throw new UserError('Each person can only appear once.');
    const total = parseAmount(amount.value);
    const base = Math.floor(total / hs.length);
    const rem = total - base * hs.length;
    return { total, list: hs.map((x, i) => ({ handle: x, amount: base + (i < rem ? 1 : 0) })) };
  }
  function paintPreview() {
    let s;
    try { s = shares(); } catch (e) {
      if (!(e instanceof UserError)) throw e;
      const empty = !amount.value.trim() && !handles.value.trim();
      mount(preview, h('h2', null, 'Preview'), h('p', { class: 'placeholder' }, empty ? 'Enter an amount and who’s splitting to see each share.' : e.message));
      return;
    }
    const others = s.list.filter((x) => !st.me || x.handle !== st.me.handle).length;
    mount(preview, h('h2', null, 'Preview'),
      h('ul', null, s.list.map((x) => h('li', null,
        h('span', null, '@' + x.handle + (st.me && x.handle === st.me.handle ? ' (you)' : '')),
        h('strong', { testid: 'split-share-' + x.handle }, fmt(x.amount))))),
      h('p', { class: 'small-note' }, others === 0 ? 'No requests will be sent.' : others + (others === 1 ? ' request' : ' requests') + ' will be sent for these shares.'));
  }
  [amount, handles].forEach((el) => el.addEventListener('input', paintPreview));

  const form = h('form', { novalidate: true, 'aria-label': 'Split a bill' },
    field('Total amount (' + cur() + ')', amount, 'The bill you already paid.'),
    field('Who’s splitting', handles, 'Handles separated by commas. Include yourself to count your own share. The first people get any extra cent.'),
    field('Note', note),
    preview, box, h('div', { class: 'actions' }, btn));
  attachWriter({
    form, btn, box, prefix: 'split', path: '/splits', label: 'Split and request', retryLabel: 'Retry split', noun: 'split',
    busyText: 'Creating split…', repeatText: 'That split was already created. Change a detail to create another.',
    uncertainText: 'We couldn’t confirm whether your split was created.', errCtx: { notFound: 'One of those handles doesn’t belong to anyone. Check the spelling.' },
    refreshOnRefuse: false, refresh: async () => {},
    build() {
      const s = shares();
      return { amount: s.total, participant_handles: s.list.map((x) => x.handle), note: checkNote(note.value) };
    },
    successText: (d) => 'Split ' + fmt(d.amount) + ' between ' + d.shares.length + (d.shares.length === 1 ? ' person' : ' people') + '; ' + d.requests.length + (d.requests.length === 1 ? ' request' : ' requests') + ' sent.',
    successExtra: () => h('span', null, ' ', h('a', { href: '/requests', 'data-link': true }, 'View requests')),
  });
  paintPreview();
  shell(path,
    pageHead('Split a bill', 'Ask friends for their share of something you paid.'),
    h('section', { class: 'card', 'aria-label': 'Split form' }, form));
}

// ---------------------------------------------------------------- authorisations
function authsPage(path, view, ctx) {
  const data = { items: [], ready: false };
  const list = h('ul', { class: 'list', testid: 'authorization-list' });
  const body = h('div', null);
  const feedback = h('div', { 'aria-live': 'polite' });
  const skeleton = h('div', { 'aria-busy': 'true' }, h('div', { class: 'skeleton line' }), h('div', { class: 'skeleton line' }));
  const show = (kind, id, text) => mount(feedback, notice(kind, id, text));

  async function capture(a) {
    const id = a.authorization_id;
    const view0 = st.view;
    let amt;
    try { amt = parseAmount(st.drafts['cap-' + id] !== undefined ? st.drafts['cap-' + id] : fmtDec(a.remaining_amount)); } catch (e) {
      if (e instanceof UserError) { show('error', 'authorization-error', e.message); return; }
      throw e;
    }
    const keep = !!st.drafts['hold-' + id];
    const b = keep ? { amount: amt, final: false } : { amount: amt };
    const c = canon(b);
    const k = st.keys[id];
    const key = k && k.canon === c && k.state === 'uncertain' ? k.key : newKey();
    st.keys[id] = { key, canon: c, state: 'sending' };
    const li = document.querySelector('[data-testid="authorization-item-' + id + '"]');
    if (li) li.querySelectorAll('button').forEach((x) => { x.disabled = true; });
    const res = await api('POST', '/authorizations/' + encodeURIComponent(id) + '/capture', { body: b, key });
    st.keys[id].state = res.kind === 'unknown' ? 'uncertain' : 'done';
    if (view0 !== st.view) return;
    if (res.kind === 'ok') {
      delete st.drafts['cap-' + id];
      show('ok', 'authorization-success', 'Collected ' + fmt(res.data.amount) + ' from @' + a.from_handle + '.');
    } else if (res.kind === 'refused') {
      show('error', 'authorization-error', errText(res, { notFound: 'That authorisation no longer exists.' }));
    } else {
      show('unsure', 'authorization-uncertain', 'We couldn’t confirm whether that capture went through. Press Capture again to retry with the same reference – it can only be collected once.');
    }
    await refresh();
  }
  async function voidIt(a) {
    const id = a.authorization_id;
    const view0 = st.view;
    const li = document.querySelector('[data-testid="authorization-item-' + id + '"]');
    if (li) li.querySelectorAll('button').forEach((x) => { x.disabled = true; });
    const res = await api('POST', '/authorizations/' + encodeURIComponent(id) + '/void');
    if (view0 !== st.view) return;
    if (res.kind === 'ok') show('ok', 'authorization-success', 'Released the hold of ' + fmt(a.remaining_amount) + '.');
    else if (res.kind === 'refused') show('error', 'authorization-error', errText(res, { notFound: 'That authorisation no longer exists.' }));
    else show('unsure', 'authorization-uncertain', 'We couldn’t confirm whether the hold was released. The list below has been refreshed.');
    await refresh();
  }

  function item(a) {
    const id = a.authorization_id;
    const outgoing = a.from_user_id === st.me.user_id;
    const open = a.status === 'open';
    const other = outgoing ? a.to_handle : a.from_handle;
    let cap = null;
    if (open && !outgoing) {
      const input = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', testid: 'authorization-capture-amount-' + id,
        value: st.drafts['cap-' + id] !== undefined ? st.drafts['cap-' + id] : fmtDec(a.remaining_amount) });
      input.addEventListener('input', () => { st.drafts['cap-' + id] = input.value; });
      const keepBox = h('input', { type: 'checkbox', testid: 'authorization-hold-' + id, checked: !!st.drafts['hold-' + id] });
      keepBox.addEventListener('change', () => { st.drafts['hold-' + id] = keepBox.checked; });
      cap = h('div', { class: 'item-actions' },
        field('Capture amount (' + cur() + ')', input),
        h('button', { type: 'button', testid: 'authorization-capture-' + id, onclick: () => capture(a) }, 'Capture'),
        h('label', { class: 'check' }, keepBox, 'Keep the rest on hold'));
    }
    return h('li', { class: 'item', testid: 'authorization-item-' + id, 'data-status': a.status },
      h('div', { class: 'item-top' },
        h('div', { class: 'parties' }, outgoing ? 'You’re holding for @' + other : '@' + other + ' is holding for you'),
        h('div', { class: 'amount', testid: 'authorization-amount-' + id }, fmt(a.amount))),
      a.note ? h('p', { class: 'note' }, a.note) : null,
      h('div', { class: 'meta' },
        h('span', { class: 'badge ' + a.status }, a.status.charAt(0).toUpperCase() + a.status.slice(1)),
        h('span', { class: 'badge dir' }, outgoing ? 'Outgoing' : 'Incoming'),
        h('span', { class: 'badge ' + a.visibility }, a.visibility === 'public' ? '◯ Public' : '● Private'),
        timeEl(a.created_at)),
      h('div', { class: 'meta' },
        a.status === 'captured' ? h('span', null, 'Captured ', h('strong', { testid: 'authorization-captured-' + id }, fmt(a.captured_amount))) : null,
        a.status !== 'captured' && a.captured_amount > 0 ? h('span', null, 'Captured so far ', h('strong', { testid: 'authorization-progress-' + id }, fmt(a.captured_amount))) : null,
        open ? h('span', null, 'Still held ', h('strong', { testid: 'authorization-remaining-' + id }, fmt(a.remaining_amount))) : null,
        h('span', null, a.status === 'open' ? 'Expires ' : 'Expiry ', h('time', { datetime: a.expires_at, testid: 'authorization-expires-' + id }, a.expires_at), ' (' + relTime(a.expires_at) + ')')),
      cap,
      open && outgoing ? h('div', { class: 'item-actions' },
        h('button', { type: 'button', class: 'danger', testid: 'authorization-void-' + id, onclick: () => voidIt(a) }, 'Release hold')) : null);
  }

  function paint() {
    if (!data.ready) { mount(body, skeleton); return; }
    if (!data.items.length) {
      mount(list);
      mount(body, h('div', { class: 'empty', testid: 'empty-authorizations' }, h('strong', null, 'No authorisations'), h('span', null, 'Holds you place or that are placed for you will appear here.')), list);
      return;
    }
    mount(list, ...data.items.map(item));
    mount(body, list);
  }

  const wallet = walletCard(ctx, () => refresh());
  const refresh = makeRefresher(ctx, '/authorizations?limit=200', wallet, (d) => {
    data.items = d.authorizations; data.ready = true; paint();
  });
  ctx.refresh = refresh;
  paint();
  shell(path,
    pageHead('Authorisations', 'Funds reserved for someone to collect later.'),
    h('div', { class: 'grid-2' },
      h('div', { class: 'col' }, wallet.card, authorizeForm(ctx)),
      h('div', { class: 'col' }, h('section', { class: 'card', 'aria-label': 'Authorisations' },
        h('header', null, h('h2', null, 'Your authorisations'), h('p', null, 'Newest first. Open holds release automatically when they expire.')), feedback, body))));
  refresh();
}

render();
})();
