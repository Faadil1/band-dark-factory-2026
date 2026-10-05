'use strict';
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const MAX_AMOUNT = 1000000000;
const HANDLE_RE = /^[a-z0-9_]{1,20}$/;
const MAX_BODY = 8 * 1024 * 1024;
const STATUSES = ['pending', 'paid', 'declined', 'cancelled'];
const AUTH_STATUSES = ['open', 'captured', 'voided', 'expired'];
const DEFAULT_TTL = 600;
const RFC3339 = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;

class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code);
    this.status = status;
    this.code = code;
  }
}
const bad = (m) => new ApiError(400, 'malformed_request', m || 'malformed request');
const invalid = (m) => new ApiError(422, 'validation_failed', m || 'validation failed');
const notFound = (m) => new ApiError(404, 'not_found', m || 'not found');
const forbidden = (m) => new ApiError(403, 'forbidden', m || 'forbidden');
const conflict = (code, m) => new ApiError(409, code, m || code);

// ---------- static UI ----------
const PUBLIC_DIR = path.join(__dirname, 'public');
const ASSETS = {
  '/assets/app.js': ['app.js', 'application/javascript; charset=utf-8'],
  '/assets/app.css': ['app.css', 'text/css; charset=utf-8'],
  '/assets/favicon.svg': ['favicon.svg', 'image/svg+xml'],
};
const UI_ROUTES = new Set(['/', '/split', '/signup', '/login', '/requests', '/authorizations']);
const staticCache = new Map();
function readAsset(file) {
  if (!staticCache.has(file)) staticCache.set(file, fs.readFileSync(path.join(PUBLIC_DIR, file)));
  return staticCache.get(file);
}
const wantsHtml = (req) => /text\/html/i.test(String(req.headers.accept || ''));

// ---------- state ----------
// All handlers run synchronously on one thread, so each operation is atomic.
let S = null; // current state
let X = null; // indices

function emptyState() {
  return {
    currency: 'EUR',
    minorUnits: 2,
    authTtl: DEFAULT_TTL,
    users: [],
    payments: [],
    requests: [],
    authorizations: [],
    tokens: new Map(),
    idem: new Map(),
    operators: [],
    counters: { user: 0, payment: 0, request: 0, split: 0, settlement: 0, auth: 0, seq: 0 },
  };
}

function reindex() {
  X = {
    byId: new Map(),
    byHandle: new Map(),
    byEmail: new Map(),
    payments: new Map(),
    requests: new Map(),
    auths: new Map(),
    open: new Set(),
  };
  for (const u of S.users) {
    X.byId.set(u.id, u);
    X.byHandle.set(u.handle, u);
    X.byEmail.set(u.email.toLowerCase(), u);
  }
  for (const p of S.payments) X.payments.set(p.id, p);
  for (const r of S.requests) X.requests.set(r.id, r);
  for (const a of S.authorizations) {
    X.auths.set(a.id, a);
    if (a.status === 'open') X.open.add(a);
  }
}

function setState(ns) {
  S = ns;
  reindex();
}

function nextId(prefix, kind, map) {
  let id;
  do {
    S.counters[kind] += 1;
    id = prefix + S.counters[kind];
  } while (map.has(id));
  return id;
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d+Z$/, '+00:00');
}
function isoFromMs(ms) {
  return new Date(ms).toISOString().replace(/\.\d+Z$/, '+00:00');
}

// ---------- holds ----------
// Expiry is evaluated lazily against the clock on every request, so reads and
// writes always see a due authorization as `expired` with its hold released.
function expireDue() {
  if (X.open.size === 0) return;
  const now = Date.now();
  for (const a of X.open) {
    if (a.expiresMs <= now) {
      a.status = 'expired';
      X.open.delete(a);
    }
  }
}
const remainingOf = (a) => (a.status === 'open' ? a.amount - a.captured : 0);
function heldOf(user) {
  let held = 0;
  for (const a of X.open) if (a.from === user.id) held += a.amount - a.captured;
  return held;
}
const availableOf = (user) => user.balance - heldOf(user);

// ---------- passwords ----------
const SCRYPT = { N: 8192, r: 8, p: 1 };
function hashPasswordSync(pw) {
  const salt = crypto.randomBytes(16);
  const h = crypto.scryptSync(pw, salt, 32, SCRYPT);
  return salt.toString('hex') + ':' + h.toString('hex');
}
function hashPasswordAsync(pw) {
  return new Promise((resolve, reject) => {
    const salt = crypto.randomBytes(16);
    crypto.scrypt(pw, salt, 32, SCRYPT, (e, h) => (e ? reject(e) : resolve(salt.toString('hex') + ':' + h.toString('hex'))));
  });
}
function verifyPassword(pw, stored) {
  return new Promise((resolve) => {
    const [saltHex, hashHex] = String(stored).split(':');
    if (!saltHex || !hashHex) return resolve(false);
    crypto.scrypt(pw, Buffer.from(saltHex, 'hex'), 32, SCRYPT, (e, h) => {
      if (e) return resolve(false);
      const expected = Buffer.from(hashHex, 'hex');
      resolve(expected.length === h.length && crypto.timingSafeEqual(expected, h));
    });
  });
}

// ---------- helpers ----------
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isInt = (v) => typeof v === 'number' && Number.isSafeInteger(v);

function canon(v) {
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (isObj(v)) {
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
  }
  return JSON.stringify(v);
}

function parseBody(raw, optional) {
  if (raw.trim().length === 0) {
    if (optional) return {};
    throw bad('body required');
  }
  let v;
  try {
    v = JSON.parse(raw);
  } catch (e) {
    throw bad('unparseable body');
  }
  if (!isObj(v)) throw bad('body must be a JSON object');
  return v;
}

function checkAmount(v) {
  if (typeof v !== 'number' || !Number.isInteger(v) || v < 1 || v > MAX_AMOUNT) {
    throw invalid('amount must be an integer between 1 and 1000000000');
  }
  return v;
}
function checkNote(v) {
  if (v === undefined) return '';
  if (typeof v !== 'string') throw invalid('note must be a string');
  if (Array.from(v).length > 200) throw invalid('note too long');
  return v;
}
function checkVisibility(v) {
  if (v === undefined) return 'public';
  if (v !== 'public' && v !== 'private') throw invalid('visibility must be public or private');
  return v;
}
function requireHandle(v, field) {
  if (v === undefined) throw invalid(field + ' required');
  if (typeof v !== 'string') throw bad(field + ' must be a string');
  return v;
}

function userByHandle(h) {
  const u = X.byHandle.get(h);
  if (!u) throw notFound('no such handle');
  return u;
}

function paymentJson(p) {
  return {
    payment_id: p.id,
    from_user_id: p.from,
    from_handle: X.byId.get(p.from).handle,
    to_user_id: p.to,
    to_handle: X.byId.get(p.to).handle,
    amount: p.amount,
    currency: S.currency,
    note: p.note,
    visibility: p.visibility,
    request_id: p.requestId,
    authorization_id: p.authorizationId || null,
    settlement_id: p.settlementId,
    created_at: p.createdAt,
  };
}

function requestJson(r) {
  return {
    request_id: r.id,
    requester_id: r.requester,
    requester_handle: X.byId.get(r.requester).handle,
    payer_id: r.payer,
    payer_handle: X.byId.get(r.payer).handle,
    amount: r.amount,
    currency: S.currency,
    note: r.note,
    status: r.status,
    payment_id: r.paymentId,
    created_at: r.createdAt,
  };
}

function authJson(a) {
  return {
    authorization_id: a.id,
    from_user_id: a.from,
    from_handle: X.byId.get(a.from).handle,
    to_user_id: a.to,
    to_handle: X.byId.get(a.to).handle,
    amount: a.amount,
    captured_amount: a.captured,
    remaining_amount: remainingOf(a),
    currency: S.currency,
    note: a.note,
    visibility: a.visibility,
    status: a.status,
    expires_at: a.expiresAt,
    payment_id: a.paymentIds.length ? a.paymentIds[a.paymentIds.length - 1] : null,
    payment_ids: a.paymentIds.slice(),
    created_at: a.createdAt,
  };
}

function makePayment(from, to, amount, note, visibility, requestId, settlementId, createdAt, authorizationId) {
  from.balance -= amount;
  to.balance += amount;
  const p = {
    id: nextId('p_', 'payment', X.payments),
    from: from.id,
    to: to.id,
    amount,
    note,
    visibility,
    requestId: requestId || null,
    authorizationId: authorizationId || null,
    settlementId: settlementId || null,
    createdAt,
    seq: ++S.counters.seq,
  };
  S.payments.push(p);
  X.payments.set(p.id, p);
  return p;
}

function makeRequest(requester, payer, amount, note, createdAt) {
  const r = {
    id: nextId('rq_', 'request', X.requests),
    requester: requester.id,
    payer: payer.id,
    amount,
    note,
    status: 'pending',
    paymentId: null,
    createdAt,
    seq: ++S.counters.seq,
  };
  S.requests.push(r);
  X.requests.set(r.id, r);
  return r;
}

// ---------- idempotency ----------
// Keyed by (user, path, key). Only successful (201) results are recorded.
function idempotent(user, path, req, body, fn) {
  const key = req.headers['idempotency-key'];
  if (key === undefined || key === '') throw new ApiError(400, 'missing_idempotency_key', 'Idempotency-Key required');
  if (Array.from(key).length > 255) throw invalid('Idempotency-Key too long');
  const id = user.id + '\n' + path + '\n' + key;
  const bodyCanon = canon(body);
  const rec = S.idem.get(id);
  if (rec) {
    if (rec.body !== bodyCanon) throw conflict('idempotency_key_reuse', 'key used with a different body');
    return { status: 200, body: rec.response };
  }
  const res = fn();
  S.idem.set(id, { body: bodyCanon, response: res });
  return { status: 201, body: res };
}

// ---------- auth ----------
function authenticate(req) {
  const h = req.headers['authorization'];
  if (typeof h !== 'string') throw new ApiError(401, 'unauthenticated', 'missing token');
  const m = /^Bearer[ \t]+(\S+)$/i.exec(h.trim());
  if (!m) throw new ApiError(401, 'unauthenticated', 'malformed token');
  const uid = S.tokens.get(m[1]);
  const u = uid && X.byId.get(uid);
  if (!u) throw new ApiError(401, 'unauthenticated', 'unknown token');
  return u;
}

function newToken(user) {
  const t = crypto.randomBytes(32).toString('hex');
  S.tokens.set(t, user.id);
  return t;
}

function deriveHandle(email) {
  const local = email.slice(0, email.lastIndexOf('@')).toLowerCase();
  return Array.from(local).map((c) => (/[a-z0-9_]/.test(c) ? c : '_')).slice(0, 20).join('');
}

function credentialFields(b, names) {
  for (const k of names) {
    if (b[k] === undefined || b[k] === null) throw invalid(k + ' required');
    if (typeof b[k] !== 'string') throw bad(k + ' must be a string');
  }
}

async function signup(raw) {
  const b = parseBody(raw);
  credentialFields(b, ['email', 'password', 'display_name']);
  const { email, password, display_name: dn } = b;
  if (!/^[^@\s]+@[^@\s]+$/.test(email)) throw invalid('invalid email');
  if (Array.from(password).length < 8) throw invalid('password too short');
  if (dn.length === 0) throw invalid('display_name required');
  const hash = await hashPasswordAsync(password);
  if (X.byEmail.has(email.toLowerCase())) throw conflict('email_taken', 'email already registered');
  const handle = deriveHandle(email);
  if (X.byHandle.has(handle)) throw conflict('handle_taken', 'handle already taken');
  const u = { id: nextId('u_', 'user', X.byId), email, handle, displayName: dn, passwordHash: hash, balance: 0 };
  S.users.push(u);
  X.byId.set(u.id, u);
  X.byHandle.set(handle, u);
  X.byEmail.set(email.toLowerCase(), u);
  return { status: 201, body: { user_id: u.id, display_name: u.displayName, token: newToken(u) } };
}

async function login(raw) {
  const b = parseBody(raw);
  credentialFields(b, ['email', 'password']);
  const u = X.byEmail.get(b.email.toLowerCase());
  const ok = u ? await verifyPassword(b.password, u.passwordHash) : false;
  if (!u || !ok || X.byId.get(u.id) !== u) throw new ApiError(401, 'unauthenticated', 'invalid credentials');
  return { status: 200, body: { user_id: u.id, display_name: u.displayName, token: newToken(u) } };
}

// ---------- endpoints ----------
function me(user) {
  const held = heldOf(user);
  return {
    status: 200,
    body: {
      user_id: user.id,
      display_name: user.displayName,
      handle: user.handle,
      balance: user.balance,
      total: user.balance,
      available: user.balance - held,
      held,
      currency: S.currency,
      minor_units: S.minorUnits,
    },
  };
}

function createPayment(user, req, raw) {
  const b = parseBody(raw);
  return idempotent(user, '/payments', req, b, () => {
    const toHandle = requireHandle(b.to_handle, 'to_handle');
    const amount = checkAmount(b.amount);
    const note = checkNote(b.note);
    const vis = checkVisibility(b.visibility);
    const to = userByHandle(toHandle);
    if (to.id === user.id) throw new ApiError(422, 'self_payment', 'cannot pay yourself');
    if (availableOf(user) < amount) throw conflict('insufficient_funds', 'insufficient funds');
    return paymentJson(makePayment(user, to, amount, note, vis, null, null, nowIso()));
  });
}

function createRequest(user, req, raw) {
  const b = parseBody(raw);
  return idempotent(user, '/requests', req, b, () => {
    const payerHandle = requireHandle(b.payer_handle, 'payer_handle');
    const amount = checkAmount(b.amount);
    const note = checkNote(b.note);
    const payer = userByHandle(payerHandle);
    if (payer.id === user.id) throw new ApiError(422, 'self_request', 'cannot request from yourself');
    return requestJson(makeRequest(user, payer, amount, note, nowIso()));
  });
}

function getRequest(id) {
  const r = X.requests.get(id);
  if (!r) throw notFound('no such request');
  return r;
}

function payRequest(user, req, raw, id) {
  const b = parseBody(raw, true);
  return idempotent(user, '/requests/' + id + '/pay', req, b, () => {
    const r = getRequest(id);
    if (r.payer !== user.id) throw forbidden('only the payer may pay');
    const vis = checkVisibility(b.visibility);
    if (r.status !== 'pending') throw conflict('request_not_pending', 'request is not pending');
    if (availableOf(user) < r.amount) throw conflict('insufficient_funds', 'insufficient funds');
    const p = makePayment(user, X.byId.get(r.requester), r.amount, r.note, vis, r.id, null, nowIso());
    r.status = 'paid';
    r.paymentId = p.id;
    return paymentJson(p);
  });
}

function transition(user, id, who, target) {
  const r = getRequest(id);
  if (r[who] !== user.id) throw forbidden('not permitted');
  if (r.status !== target) {
    if (r.status !== 'pending') throw conflict('request_not_pending', 'request is not pending');
    r.status = target;
  }
  return { status: 200, body: requestJson(r) };
}

function paging(query) {
  const num = (name, def, min, max) => {
    const v = query.get(name);
    if (v === null) return def;
    if (!/^[0-9]+$/.test(v)) throw invalid(name + ' must be an integer');
    const n = Number(v);
    if (n < min || n > max) throw invalid(name + ' out of range');
    return n;
  };
  return { limit: num('limit', 50, 1, 200), offset: num('offset', 0, 0, Number.MAX_SAFE_INTEGER) };
}

function page(items, limit, offset) {
  return { slice: items.slice(offset, offset + limit), more: offset + limit < items.length };
}

function listRequests(user, query) {
  const { limit, offset } = paging(query);
  const dir = query.get('direction');
  if (dir !== null && dir !== 'incoming' && dir !== 'outgoing') throw invalid('bad direction');
  const st = query.get('status');
  if (st !== null && !STATUSES.includes(st)) throw invalid('bad status');
  const items = [];
  for (let i = S.requests.length - 1; i >= 0; i--) {
    const r = S.requests[i];
    const incoming = r.payer === user.id;
    const outgoing = r.requester === user.id;
    if (!incoming && !outgoing) continue;
    if (dir === 'incoming' && !incoming) continue;
    if (dir === 'outgoing' && !outgoing) continue;
    if (st !== null && r.status !== st) continue;
    items.push(r);
  }
  const { slice, more } = page(items, limit, offset);
  return { status: 200, body: { requests: slice.map(requestJson), has_more: more } };
}

function listActivity(user, query) {
  const { limit, offset } = paging(query);
  const items = [];
  for (let i = S.payments.length - 1; i >= 0; i--) {
    const p = S.payments[i];
    if (p.visibility === 'public' || p.from === user.id || p.to === user.id) items.push(p);
  }
  const { slice, more } = page(items, limit, offset);
  return { status: 200, body: { payments: slice.map(paymentJson), has_more: more } };
}

function createSplit(user, req, raw) {
  const b = parseBody(raw);
  return idempotent(user, '/splits', req, b, () => {
    const amount = checkAmount(b.amount);
    const ph = b.participant_handles;
    if (ph === undefined) throw invalid('participant_handles required');
    if (!Array.isArray(ph)) throw bad('participant_handles must be an array');
    if (ph.some((h) => typeof h !== 'string')) throw bad('handles must be strings');
    if (ph.length === 0) throw invalid('participant_handles empty');
    if (new Set(ph).size !== ph.length) throw invalid('duplicate handle');
    const note = checkNote(b.note);
    const people = ph.map(userByHandle);
    const n = people.length;
    const base = Math.floor(amount / n);
    const rem = amount - base * n;
    const at = nowIso();
    const shares = people.map((u, i) => ({ handle: u.handle, amount: base + (i < rem ? 1 : 0) }));
    const requests = [];
    people.forEach((u, i) => {
      if (u.id === user.id) return;
      requests.push(requestJson(makeRequest(user, u, shares[i].amount, note, at)));
    });
    return {
      split_id: nextId('sp_', 'split', new Map()),
      amount,
      currency: S.currency,
      note,
      shares,
      requests,
      created_at: at,
    };
  });
}

function createSettlement(user, req, raw) {
  if (!S.operators.includes(user.id)) throw forbidden('operator required');
  const b = parseBody(raw);
  return idempotent(user, '/settlements', req, b, () => {
    const t = b.transfers;
    if (!Array.isArray(t) || t.length < 1 || t.length > 32) throw invalid('transfers must contain 1..32 items');
    const entries = [];
    for (const e of t) {
      if (!isObj(e)) throw invalid('transfer must be an object');
      if (typeof e.from_handle !== 'string' || typeof e.to_handle !== 'string') throw invalid('handles must be strings');
      const amount = checkAmount(e.amount);
      const note = checkNote(e.note);
      const vis = checkVisibility(e.visibility);
      const from = userByHandle(e.from_handle);
      const to = userByHandle(e.to_handle);
      if (from.id === to.id) throw new ApiError(422, 'self_payment', 'self transfer');
      entries.push({ from, to, amount, note, vis });
    }
    const delta = new Map();
    for (const e of entries) {
      delta.set(e.from, (delta.get(e.from) || 0) - e.amount);
      delta.set(e.to, (delta.get(e.to) || 0) + e.amount);
    }
    // Held funds cannot fund net debits: the post-settlement balance must still cover every open hold.
    for (const [u, d] of delta) {
      if (u.balance + d - heldOf(u) < 0) throw conflict('insufficient_funds', 'settlement not affordable');
    }
    const at = nowIso();
    const sid = nextId('st_', 'settlement', new Map());
    const payments = entries.map((e) => paymentJson(makePayment(e.from, e.to, e.amount, e.note, e.vis, null, sid, at)));
    return { settlement_id: sid, committed_at: at, payments };
  });
}

// ---------- authorizations ----------
function createAuthorization(user, req, raw) {
  const b = parseBody(raw);
  return idempotent(user, '/authorizations', req, b, () => {
    const toHandle = requireHandle(b.to_handle, 'to_handle');
    const amount = checkAmount(b.amount);
    const note = checkNote(b.note);
    const vis = checkVisibility(b.visibility);
    const to = userByHandle(toHandle);
    if (to.id === user.id) throw new ApiError(422, 'self_payment', 'cannot authorize a payment to yourself');
    if (availableOf(user) < amount) throw conflict('insufficient_funds', 'insufficient available funds');
    // created_at is rounded up to the second so the hold never lives less than its full lifetime.
    const createdMs = Math.ceil(Date.now() / 1000) * 1000;
    const expiresMs = createdMs + S.authTtl * 1000;
    const a = {
      id: nextId('a_', 'auth', X.auths),
      from: user.id,
      to: to.id,
      amount,
      captured: 0,
      note,
      visibility: vis,
      status: 'open',
      expiresAt: isoFromMs(expiresMs),
      expiresMs,
      paymentIds: [],
      createdAt: isoFromMs(createdMs),
      seq: ++S.counters.seq,
    };
    S.authorizations.push(a);
    X.auths.set(a.id, a);
    X.open.add(a);
    return authJson(a);
  });
}

function getAuth(id) {
  const a = X.auths.get(id);
  if (!a) throw notFound('no such authorization');
  return a;
}

function captureAuthorization(user, req, raw, id) {
  const b = parseBody(raw, true);
  return idempotent(user, '/authorizations/' + id + '/capture', req, b, () => {
    const a = getAuth(id);
    if (a.to !== user.id) throw forbidden('only the receiver may capture');
    let amount;
    if (b.amount !== undefined) {
      if (typeof b.amount !== 'number' || !Number.isInteger(b.amount) || b.amount < 1) throw invalid('amount must be a positive integer');
      amount = b.amount;
    }
    if (b.final !== undefined && typeof b.final !== 'boolean') throw bad('final must be a boolean');
    const final = b.final === undefined ? true : b.final;
    if (a.status !== 'open') {
      if (a.status === 'expired' && a.expiresMs <= Date.now()) throw conflict('authorization_expired', 'authorization has expired');
      throw conflict('authorization_not_open', 'authorization is not open');
    }
    const remaining = a.amount - a.captured;
    if (amount === undefined) amount = remaining;
    if (amount > remaining) throw new ApiError(422, 'capture_exceeds_authorization', 'capture exceeds the remaining authorized amount');
    const p = makePayment(X.byId.get(a.from), user, amount, a.note, a.visibility, null, null, nowIso(), a.id);
    a.captured += amount;
    a.paymentIds.push(p.id);
    if (final || a.captured === a.amount) {
      a.status = 'captured';
      X.open.delete(a);
    }
    return paymentJson(p);
  });
}

function voidAuthorization(user, id) {
  const a = getAuth(id);
  if (a.from !== user.id) throw forbidden('only the payer may void');
  if (a.status === 'open') {
    a.status = 'voided';
    X.open.delete(a);
  } else if (a.status !== 'voided') {
    throw conflict('authorization_not_open', 'authorization is not open');
  }
  return { status: 200, body: authJson(a) };
}

function listAuthorizations(user, query) {
  const { limit, offset } = paging(query);
  const dir = query.get('direction');
  if (dir !== null && dir !== 'incoming' && dir !== 'outgoing') throw invalid('bad direction');
  const st = query.get('status');
  if (st !== null && !AUTH_STATUSES.includes(st)) throw invalid('bad status');
  const items = [];
  for (let i = S.authorizations.length - 1; i >= 0; i--) {
    const a = S.authorizations[i];
    const outgoing = a.from === user.id;
    const incoming = a.to === user.id;
    if (!incoming && !outgoing) continue;
    if (dir === 'incoming' && !incoming) continue;
    if (dir === 'outgoing' && !outgoing) continue;
    if (st !== null && a.status !== st) continue;
    items.push(a);
  }
  const { slice, more } = page(items, limit, offset);
  return { status: 200, body: { authorizations: slice.map(authJson), has_more: more } };
}

// ---------- reset / export / import ----------
function optArray(v, name) {
  if (v === undefined) return [];
  if (!Array.isArray(v)) throw invalid(name + ' must be an array');
  return v;
}

function freshId(given, prefix, kind, ns, used) {
  let id = given;
  if (id !== undefined && (typeof id !== 'string' || !id || id.length > 64 || used.has(id))) throw invalid('bad ' + kind + ' id');
  if (id === undefined) {
    do {
      ns.counters[kind] += 1;
      id = prefix + ns.counters[kind];
    } while (used.has(id));
  }
  used.add(id);
  return id;
}

// An unexpired open hold may never exceed its owner's balance.
function checkHolds(ns, now) {
  const held = new Map();
  for (const a of ns.authorizations) {
    if (a.status === 'open' && a.expiresMs > now) held.set(a.from, (held.get(a.from) || 0) + a.amount - a.captured);
  }
  const bal = new Map(ns.users.map((u) => [u.id, u.balance]));
  for (const [uid, h] of held) if (h > bal.get(uid)) throw invalid('open holds exceed balance');
}

function reset(raw) {
  const f = parseBody(raw);
  const ns = emptyState();
  if (typeof f.currency !== 'string' || f.currency.length === 0) throw invalid('currency required');
  if (![0, 2, 3].includes(f.minor_units)) throw invalid('minor_units must be 0, 2 or 3');
  ns.currency = f.currency;
  ns.minorUnits = f.minor_units;
  if (f.authorization_ttl_seconds !== undefined) {
    const t = f.authorization_ttl_seconds;
    if (typeof t !== 'number' || !Number.isInteger(t) || t < 1 || t > 10 * 365 * 86400) throw invalid('authorization_ttl_seconds must be a positive integer');
    ns.authTtl = t;
  }

  const users = optArray(f.users, 'users');
  const explicit = new Set();
  const handles = new Set();
  const emails = new Set();
  let total = 0;
  for (const u of users) {
    if (!isObj(u)) throw invalid('user must be an object');
    if (typeof u.email !== 'string' || !u.email) throw invalid('user email required');
    if (typeof u.password !== 'string') throw invalid('user password required');
    if (typeof u.handle !== 'string' || !HANDLE_RE.test(u.handle)) throw invalid('bad handle');
    if (!isInt(u.balance) || u.balance < 0) throw invalid('balance must be a non-negative integer');
    if (u.id !== undefined && (typeof u.id !== 'string' || !u.id || u.id.length > 64)) throw invalid('bad user id');
    if (u.display_name !== undefined && typeof u.display_name !== 'string') throw invalid('bad display_name');
    const em = u.email.toLowerCase();
    if (handles.has(u.handle) || emails.has(em) || (u.id !== undefined && explicit.has(u.id))) throw invalid('duplicate user');
    handles.add(u.handle);
    emails.add(em);
    if (u.id !== undefined) explicit.add(u.id);
    total += u.balance;
  }
  if (!Number.isSafeInteger(total)) throw invalid('total too large');
  const used = new Set(explicit);
  for (const u of users) {
    ns.users.push({
      id: null,
      email: u.email,
      handle: u.handle,
      displayName: u.display_name === undefined ? u.handle : u.display_name,
      passwordHash: hashPasswordSync(u.password),
      balance: u.balance,
    });
  }
  // assign ids (explicit ones are kept; others generated avoiding collisions)
  ns.users.forEach((nu, i) => {
    const given = users[i].id;
    if (given !== undefined) {
      nu.id = given;
    } else {
      do {
        ns.counters.user += 1;
        nu.id = 'u_' + ns.counters.user;
      } while (used.has(nu.id));
      used.add(nu.id);
    }
  });

  const known = new Set(ns.users.map((u) => u.id));
  const at = nowIso();
  const pids = new Set();
  for (const p of optArray(f.payments, 'payments')) {
    if (!isObj(p)) throw invalid('payment must be an object');
    if (!known.has(p.from_user_id) || !known.has(p.to_user_id)) throw invalid('payment references unknown user');
    if (!isInt(p.amount) || p.amount < 0) throw invalid('bad payment amount');
    if (p.note !== undefined && typeof p.note !== 'string') throw invalid('bad payment note');
    if (p.visibility !== undefined && p.visibility !== 'public' && p.visibility !== 'private') throw invalid('bad visibility');
    ns.payments.push({
      id: freshId(p.id, 'p_', 'payment', ns, pids),
      from: p.from_user_id,
      to: p.to_user_id,
      amount: p.amount,
      note: p.note === undefined ? '' : p.note,
      visibility: p.visibility === undefined ? 'public' : p.visibility,
      requestId: typeof p.request_id === 'string' ? p.request_id : null,
      authorizationId: typeof p.authorization_id === 'string' ? p.authorization_id : null,
      settlementId: null,
      createdAt: at,
      seq: ++ns.counters.seq,
    });
  }
  const rids = new Set();
  for (const r of optArray(f.requests, 'requests')) {
    if (!isObj(r)) throw invalid('request must be an object');
    if (!known.has(r.requester_id) || !known.has(r.payer_id)) throw invalid('request references unknown user');
    if (!isInt(r.amount) || r.amount < 0) throw invalid('bad request amount');
    if (r.note !== undefined && typeof r.note !== 'string') throw invalid('bad request note');
    const status = r.status === undefined ? 'pending' : r.status;
    if (!STATUSES.includes(status)) throw invalid('bad status');
    ns.requests.push({
      id: freshId(r.id, 'rq_', 'request', ns, rids),
      requester: r.requester_id,
      payer: r.payer_id,
      amount: r.amount,
      note: r.note === undefined ? '' : r.note,
      status,
      paymentId: typeof r.payment_id === 'string' ? r.payment_id : null,
      createdAt: at,
      seq: ++ns.counters.seq,
    });
  }
  const aids = new Set();
  const nowMs = Date.now();
  for (const a of optArray(f.authorizations, 'authorizations')) {
    if (!isObj(a)) throw invalid('authorization must be an object');
    if (!known.has(a.from_user_id) || !known.has(a.to_user_id)) throw invalid('authorization references unknown user');
    if (a.from_user_id === a.to_user_id) throw invalid('authorization to self');
    if (!isInt(a.amount) || a.amount < 1 || a.amount > MAX_AMOUNT) throw invalid('bad authorization amount');
    if (a.note !== undefined && typeof a.note !== 'string') throw invalid('bad authorization note');
    if (a.visibility !== undefined && a.visibility !== 'public' && a.visibility !== 'private') throw invalid('bad visibility');
    const status = a.status === undefined ? 'open' : a.status;
    if (!AUTH_STATUSES.includes(status)) throw invalid('bad authorization status');
    let expiresAt = a.expires_at;
    if (expiresAt === undefined && status !== 'open') expiresAt = at;
    if (typeof expiresAt !== 'string' || !RFC3339.test(expiresAt) || Number.isNaN(Date.parse(expiresAt))) throw invalid('bad expires_at');
    let captured = 0;
    if (a.captured_amount !== undefined) {
      if (!isInt(a.captured_amount) || a.captured_amount < 0 || a.captured_amount > a.amount) throw invalid('bad captured_amount');
      captured = a.captured_amount;
    } else if (status === 'captured') {
      captured = a.amount;
    }
    let paymentIds = [];
    if (a.payment_ids !== undefined) {
      if (!Array.isArray(a.payment_ids) || a.payment_ids.some((x) => typeof x !== 'string')) throw invalid('bad payment_ids');
      paymentIds = a.payment_ids.slice();
    } else if (typeof a.payment_id === 'string') {
      paymentIds = [a.payment_id];
    }
    const expiresMs = Date.parse(expiresAt);
    ns.authorizations.push({
      id: freshId(a.id, 'a_', 'auth', ns, aids),
      from: a.from_user_id,
      to: a.to_user_id,
      amount: a.amount,
      captured,
      note: a.note === undefined ? '' : a.note,
      visibility: a.visibility === undefined ? 'public' : a.visibility,
      status: status === 'open' && expiresMs <= nowMs ? 'expired' : status,
      expiresAt,
      expiresMs,
      paymentIds,
      createdAt: typeof a.created_at === 'string' && RFC3339.test(a.created_at) ? a.created_at : at,
      seq: ++ns.counters.seq,
    });
  }
  checkHolds(ns, nowMs);
  const ops = optArray(f.settlement_operator_ids, 'settlement_operator_ids');
  if (ops.some((o) => typeof o !== 'string')) throw invalid('operator ids must be strings');
  ns.operators = ops.slice();
  setState(ns);
}

function exportState() {
  const snap = {
    currency: S.currency,
    minorUnits: S.minorUnits,
    authTtl: S.authTtl,
    users: S.users,
    payments: S.payments,
    requests: S.requests,
    authorizations: S.authorizations,
    tokens: Array.from(S.tokens.entries()),
    idem: Array.from(S.idem.entries()),
    operators: S.operators,
    counters: S.counters,
  };
  return { track: 'pocketful', format_version: 1, state: JSON.parse(JSON.stringify(snap)) };
}

function importState(raw) {
  const b = parseBody(raw);
  if (b.track !== 'pocketful' || b.format_version !== 1 || !isObj(b.state)) throw invalid('bad export envelope');
  let ns;
  try {
    ns = buildImported(b.state);
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw invalid('invalid state');
  }
  setState(ns);
}

// Accepts exports of this stage and of stage 1 (no authorizations, TTL or authorization ids).
function buildImported(s) {
  const need = (c, m) => {
    if (!c) throw invalid(m || 'invalid state');
    return true;
  };
  need(typeof s.currency === 'string' && s.currency, 'currency');
  need([0, 2, 3].includes(s.minorUnits), 'minorUnits');
  for (const k of ['users', 'payments', 'requests', 'tokens', 'idem', 'operators']) need(Array.isArray(s[k]), k);
  need(s.authorizations === undefined || Array.isArray(s.authorizations), 'authorizations');
  need(isObj(s.counters), 'counters');
  const ns = emptyState();
  ns.currency = s.currency;
  ns.minorUnits = s.minorUnits;
  if (s.authTtl !== undefined) {
    need(isInt(s.authTtl) && s.authTtl >= 1, 'authTtl');
    ns.authTtl = s.authTtl;
  }
  for (const k of Object.keys(ns.counters)) {
    if (k === 'auth' && s.counters[k] === undefined) continue;
    need(isInt(s.counters[k]) && s.counters[k] >= 0, 'counter ' + k);
    ns.counters[k] = s.counters[k];
  }
  const uids = new Set();
  const handles = new Set();
  const emails = new Set();
  for (const u of s.users) {
    need(isObj(u));
    need(typeof u.id === 'string' && u.id && typeof u.email === 'string' && typeof u.displayName === 'string');
    need(typeof u.handle === 'string' && HANDLE_RE.test(u.handle));
    need(typeof u.passwordHash === 'string' && isInt(u.balance) && u.balance >= 0);
    need(!uids.has(u.id) && !handles.has(u.handle) && !emails.has(u.email.toLowerCase()), 'duplicate user');
    uids.add(u.id);
    handles.add(u.handle);
    emails.add(u.email.toLowerCase());
    ns.users.push({
      id: u.id,
      email: u.email,
      handle: u.handle,
      displayName: u.displayName,
      passwordHash: u.passwordHash,
      balance: u.balance,
    });
  }
  const pids = new Set();
  for (const p of s.payments) {
    need(isObj(p) && typeof p.id === 'string' && !pids.has(p.id));
    need(uids.has(p.from) && uids.has(p.to) && isInt(p.amount) && typeof p.note === 'string');
    need(p.visibility === 'public' || p.visibility === 'private');
    need(typeof p.createdAt === 'string' && isInt(p.seq));
    need(p.requestId === null || typeof p.requestId === 'string');
    need(p.settlementId === null || typeof p.settlementId === 'string');
    need(p.authorizationId === undefined || p.authorizationId === null || typeof p.authorizationId === 'string');
    pids.add(p.id);
    ns.payments.push({
      id: p.id,
      from: p.from,
      to: p.to,
      amount: p.amount,
      note: p.note,
      visibility: p.visibility,
      requestId: p.requestId,
      authorizationId: p.authorizationId || null,
      settlementId: p.settlementId,
      createdAt: p.createdAt,
      seq: p.seq,
    });
  }
  const rids = new Set();
  for (const r of s.requests) {
    need(isObj(r) && typeof r.id === 'string' && !rids.has(r.id));
    need(uids.has(r.requester) && uids.has(r.payer) && isInt(r.amount) && typeof r.note === 'string');
    need(STATUSES.includes(r.status));
    need(r.paymentId === null || typeof r.paymentId === 'string');
    need(typeof r.createdAt === 'string' && isInt(r.seq));
    rids.add(r.id);
    ns.requests.push({
      id: r.id,
      requester: r.requester,
      payer: r.payer,
      amount: r.amount,
      note: r.note,
      status: r.status,
      paymentId: r.paymentId,
      createdAt: r.createdAt,
      seq: r.seq,
    });
  }
  const aids = new Set();
  for (const a of s.authorizations || []) {
    need(isObj(a) && typeof a.id === 'string' && !aids.has(a.id));
    need(uids.has(a.from) && uids.has(a.to) && isInt(a.amount) && a.amount >= 1 && typeof a.note === 'string');
    need(isInt(a.captured) && a.captured >= 0 && a.captured <= a.amount);
    need(a.visibility === 'public' || a.visibility === 'private');
    need(AUTH_STATUSES.includes(a.status));
    need(typeof a.expiresAt === 'string' && isInt(a.expiresMs) && typeof a.createdAt === 'string' && isInt(a.seq));
    need(Array.isArray(a.paymentIds) && a.paymentIds.every((x) => typeof x === 'string'));
    aids.add(a.id);
    ns.authorizations.push({
      id: a.id,
      from: a.from,
      to: a.to,
      amount: a.amount,
      captured: a.captured,
      note: a.note,
      visibility: a.visibility,
      status: a.status,
      expiresAt: a.expiresAt,
      expiresMs: a.expiresMs,
      paymentIds: a.paymentIds.slice(),
      createdAt: a.createdAt,
      seq: a.seq,
    });
  }
  for (const t of s.tokens) {
    need(Array.isArray(t) && typeof t[0] === 'string' && uids.has(t[1]));
    ns.tokens.set(t[0], t[1]);
  }
  for (const e of s.idem) {
    need(Array.isArray(e) && typeof e[0] === 'string' && isObj(e[1]) && typeof e[1].body === 'string' && 'response' in e[1]);
    ns.idem.set(e[0], { body: e[1].body, response: e[1].response });
  }
  need(s.operators.every((o) => typeof o === 'string'));
  ns.operators = s.operators.slice();
  ns.payments.sort((a, b) => a.seq - b.seq);
  ns.requests.sort((a, b) => a.seq - b.seq);
  ns.authorizations.sort((a, b) => a.seq - b.seq);
  // Imported holds must still be coverable by the imported balances.
  checkHolds(ns, Date.now());
  return ns;
}

// ---------- routing ----------
function uiResponse(p) {
  if (p === '/' || UI_ROUTES.has(p)) return { status: 200, type: 'text/html; charset=utf-8', file: 'index.html' };
  const a = ASSETS[p];
  if (a) return { status: 200, type: a[1], file: a[0] };
  return null;
}

async function route(req, raw) {
  const url = new URL(req.url, 'http://localhost');
  let path = url.pathname;
  if (path.length > 1 && path.endsWith('/') && req.method === 'GET' && UI_ROUTES.has(path.replace(/\/+$/, '') || '/')) {
    path = path.replace(/\/+$/, '');
  }
  const q = url.searchParams;
  const m = req.method;
  const is = (method, p) => m === method && path === p;

  if (m === 'GET' && path === '/favicon.ico') return { status: 200, type: 'image/svg+xml', file: 'favicon.svg' };
  if (m === 'GET' && ASSETS[path]) return uiResponse(path);
  if (m === 'GET' && UI_ROUTES.has(path)) {
    const shared = path === '/requests' || path === '/authorizations';
    if (!shared || wantsHtml(req)) return uiResponse(path);
  }

  if (is('GET', '/health')) return { status: 200, body: { status: 'ok' } };
  if (is('POST', '/_test/reset')) {
    reset(raw);
    return { status: 204 };
  }
  if (is('GET', '/_test/export')) {
    expireDue();
    return { status: 200, body: exportState() };
  }
  if (is('POST', '/_test/import')) {
    importState(raw);
    expireDue();
    return { status: 204 };
  }
  if (is('POST', '/auth/signup')) return signup(raw);
  if (is('POST', '/auth/login')) return login(raw);

  const known = ['/me', '/payments', '/requests', '/splits', '/activity', '/settlements', '/authorizations'];
  const sub = /^\/requests\/([^/]+)\/(pay|decline|cancel)$/.exec(path);
  const asub = /^\/authorizations\/([^/]+)\/(capture|void)$/.exec(path);
  if (!known.includes(path) && !sub && !asub) throw notFound('no such route');

  const user = authenticate(req);
  expireDue();
  if (is('GET', '/me')) return me(user);
  if (is('POST', '/payments')) return createPayment(user, req, raw);
  if (is('POST', '/requests')) return createRequest(user, req, raw);
  if (is('GET', '/requests')) return listRequests(user, q);
  if (is('POST', '/splits')) return createSplit(user, req, raw);
  if (is('GET', '/activity')) return listActivity(user, q);
  if (is('POST', '/settlements')) return createSettlement(user, req, raw);
  if (is('POST', '/authorizations')) return createAuthorization(user, req, raw);
  if (is('GET', '/authorizations')) return listAuthorizations(user, q);
  if ((sub || asub) && m === 'POST') {
    const match = sub || asub;
    let id;
    try {
      id = decodeURIComponent(match[1]);
    } catch (e) {
      throw notFound('no such resource');
    }
    if (sub) {
      if (sub[2] === 'pay') return payRequest(user, req, raw, id);
      if (sub[2] === 'decline') return transition(user, id, 'payer', 'declined');
      return transition(user, id, 'requester', 'cancelled');
    }
    if (asub[2] === 'capture') return captureAuthorization(user, req, raw, id);
    return voidAuthorization(user, id);
  }
  throw notFound('no such route');
}

function send(res, status, body) {
  if (body === undefined) {
    res.writeHead(status);
    res.end();
    return;
  }
  const data = Buffer.from(JSON.stringify(body), 'utf8');
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': data.length });
  res.end(data);
}

function sendFile(res, r) {
  const data = readAsset(r.file);
  res.writeHead(r.status, {
    'Content-Type': r.type,
    'Content-Length': data.length,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
  });
  res.end(data);
}

const server = http.createServer((req, res) => {
  const chunks = [];
  let size = 0;
  let tooBig = false;
  req.on('data', (c) => {
    size += c.length;
    if (size > MAX_BODY) {
      tooBig = true;
      return;
    }
    chunks.push(c);
  });
  req.on('error', () => {});
  req.on('end', async () => {
    try {
      if (tooBig) throw bad('body too large');
      const r = await route(req, Buffer.concat(chunks).toString('utf8'));
      if (r.file) sendFile(res, r);
      else send(res, r.status, r.body);
    } catch (e) {
      if (e instanceof ApiError) {
        send(res, e.status, { error: { code: e.code, message: e.message } });
      } else {
        console.error(e);
        send(res, 500, { error: { code: 'internal_error', message: 'internal error' } });
      }
    }
  });
});

setState(emptyState());
server.keepAliveTimeout = 65000;
server.listen(Number(process.env.PORT) || 8080, '0.0.0.0');
