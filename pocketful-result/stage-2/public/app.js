(function () {
  'use strict';

  var TOKEN_KEY = 'pocketful.token';
  var MAX_AMOUNT = 1000000000;
  var cfg = { currency: '', mu: 2 };
  var me = null;

  // ---------- small helpers ----------
  function store(k, v) {
    try {
      if (v === null) localStorage.removeItem(k);
      else if (v !== undefined) localStorage.setItem(k, v);
      return localStorage.getItem(k);
    } catch (e) {
      return null;
    }
  }
  var getToken = function () { return store(TOKEN_KEY); };

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k.indexOf('on') === 0) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? '' : String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) c.forEach(function (x) { add(el, x); });
    else if (typeof c === 'string' || typeof c === 'number') el.appendChild(document.createTextNode(String(c)));
    else el.appendChild(c);
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  function newKey() {
    var a = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  // ---------- money ----------
  function plain(n) {
    var s = String(n);
    if (cfg.mu === 0) return s;
    s = s.padStart(cfg.mu + 1, '0');
    return s.slice(0, -cfg.mu) + '.' + s.slice(-cfg.mu);
  }
  function fmt(n) { return plain(n) + ' ' + cfg.currency; }

  // Decimal text -> minor units. Returns {minor} or {error}.
  function parseAmount(text) {
    var s = String(text).trim();
    var m = /^(\d*)(?:\.(\d*))?$/.exec(s);
    if (!m || (m[1] === '' && !m[2])) return { error: 'Enter an amount as a number, for example ' + (cfg.mu ? '15.00' : '15') + '.' };
    var frac = m[2] || '';
    if (frac.length > cfg.mu) {
      return { error: cfg.mu === 0 ? 'This currency has no decimal places. Enter a whole number.' : 'Use at most ' + cfg.mu + ' decimal places.' };
    }
    var digits = ((m[1] || '') + frac.padEnd(cfg.mu, '0')).replace(/^0+/, '');
    if (digits === '') return { error: 'Amount must be greater than zero.' };
    if (digits.length > 10 || Number(digits) > MAX_AMOUNT) return { error: 'Amount is too large. The maximum is ' + fmt(MAX_AMOUNT) + '.' };
    return { minor: Number(digits) };
  }

  var dtf = null;
  function fmtTime(iso) {
    try {
      dtf = dtf || new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
      var d = new Date(iso);
      return isNaN(d) ? iso : dtf.format(d);
    } catch (e) {
      return iso;
    }
  }
  function timeEl(iso, testid) {
    return h('time', { datetime: iso, title: iso, 'data-testid': testid, text: testid ? iso : fmtTime(iso) });
  }
  function relative(iso) {
    var ms = new Date(iso).getTime() - Date.now();
    if (isNaN(ms)) return '';
    var s = Math.round(Math.abs(ms) / 1000);
    var t = s < 90 ? s + ' sec' : s < 5400 ? Math.round(s / 60) + ' min' : s < 172800 ? Math.round(s / 3600) + ' hr' : Math.round(s / 86400) + ' days';
    return ms >= 0 ? 'in ' + t : t + ' ago';
  }

  function normHandle(s) { return String(s).trim().replace(/^@/, ''); }
  function noteTooLong(s) { return Array.from(s).length > 200; }

  // ---------- API ----------
  function ApiFail(o) {
    this.status = o.status || 0;
    this.code = o.code || '';
    this.message = o.message || '';
    this.uncertain = !!o.uncertain;
  }

  function api(method, url, o) {
    o = o || {};
    var headers = { Accept: 'application/json' };
    var t = getToken();
    if (t && o.auth !== false) headers.Authorization = 'Bearer ' + t;
    if (o.body !== undefined) headers['Content-Type'] = 'application/json';
    if (o.key) headers['Idempotency-Key'] = o.key;
    return fetch(url, { method: method, headers: headers, body: o.body === undefined ? undefined : JSON.stringify(o.body), cache: 'no-store' }).then(
      function (res) {
        return res.text().then(
          function (text) {
            var data = null;
            try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
            if (res.ok) {
              if (text && data === null) throw new ApiFail({ uncertain: true, message: 'unreadable response' });
              return { status: res.status, data: data };
            }
            if (res.status === 401 && o.auth !== false) {
              store(TOKEN_KEY, null);
              location.replace('/login');
            }
            var er = (data && data.error) || {};
            throw new ApiFail({ status: res.status, code: er.code, message: er.message, uncertain: res.status >= 500 });
          },
          function () { throw new ApiFail({ uncertain: true, message: 'connection lost' }); }
        );
      },
      function () { throw new ApiFail({ uncertain: true, message: 'network error' }); }
    );
  }

  function explain(e) {
    if (!(e instanceof ApiFail)) return 'Something went wrong. Please try again.';
    switch (e.code) {
      case 'insufficient_funds': return 'Not enough available funds for this. Money on hold can’t be spent.';
      case 'self_payment': return 'You can’t send money to yourself.';
      case 'self_request': return 'You can’t request money from yourself.';
      case 'not_found': return 'We couldn’t find that person or item.';
      case 'forbidden': return 'You’re not allowed to do that.';
      case 'request_not_pending': return 'This request is no longer pending, so nothing was changed.';
      case 'authorization_not_open': return 'This authorization is no longer open, so nothing was changed.';
      case 'authorization_expired': return 'This authorization has expired and its hold was released.';
      case 'capture_exceeds_authorization': return 'That is more than the amount still reserved.';
      case 'email_taken': return 'That email is already registered. Try logging in instead.';
      case 'handle_taken': return 'The handle derived from that email is already taken. Use a different email.';
      case 'unauthenticated': return 'Those details didn’t match an account.';
      case 'validation_failed': return e.message ? 'Please check your details: ' + e.message : 'Please check your details.';
      default: return e.message || 'Something went wrong. Please try again.';
    }
  }

  // ---------- idempotent write attempts ----------
  // One attempt per form. An unchanged form whose outcome is unknown retries with the same key;
  // a changed form (or one that was definitively refused) is a new attempt with a new key.
  var attempts = {};
  function attemptWrite(slot, sig, send, keepDone) {
    var at = attempts[slot];
    if (!at || at.sig !== sig || at.phase === 'failed') {
      at = attempts[slot] = { sig: sig, key: newKey(), phase: 'idle' };
    } else if (at.phase === 'inflight' || at.phase === 'done') {
      return Promise.resolve({ skipped: true });
    }
    at.phase = 'inflight';
    return send(at.key).then(
      function (r) {
        if (keepDone) at.phase = 'done';
        else delete attempts[slot];
        return { ok: true, res: r.data };
      },
      function (e) {
        if (!(e instanceof ApiFail)) { at.phase = 'failed'; return { error: e }; }
        at.phase = e.uncertain ? 'uncertain' : 'failed';
        return { error: e };
      }
    );
  }

  function setMsg(box, kind, testid, text) {
    clear(box);
    if (!text) return;
    box.appendChild(h('div', { class: 'msg ' + kind, role: kind === 'error' ? 'alert' : 'status', 'data-testid': testid, text: text }));
  }

  function latest() {
    var n = 0;
    return { next: function () { return ++n; }, is: function (i) { return i === n; } };
  }

  // ---------- chrome ----------
  var NAV = [['/', 'Wallet'], ['/requests', 'Requests'], ['/split', 'Split'], ['/authorizations', 'Authorizations']];
  var route = location.pathname.replace(/\/+$/, '') || '/';

  function renderChrome() {
    var nav = document.getElementById('nav');
    clear(nav);
    var signedIn = !!getToken();
    var items = signedIn ? NAV : [['/login', 'Log in'], ['/signup', 'Sign up']];
    items.forEach(function (it) {
      nav.appendChild(h('a', { href: it[0], 'aria-current': route === it[0] ? 'page' : null, text: it[1] }));
    });
  }
  function renderWho() {
    var who = document.getElementById('who');
    clear(who);
    if (!getToken() || !me) return;
    who.appendChild(h('span', { 'data-testid': 'current-user', text: me.display_name }));
    who.appendChild(h('span', { class: 'handle', 'data-testid': 'current-handle', text: me.handle }));
    who.appendChild(h('button', { type: 'button', class: 'secondary', 'data-testid': 'logout-button', text: 'Log out', onclick: logout }));
  }
  function logout() {
    store(TOKEN_KEY, null);
    location.assign('/login');
  }
  function applyMe(m) {
    me = m;
    cfg.currency = m.currency;
    cfg.mu = m.minor_units;
    renderWho();
  }
  function setTitle(t) { document.title = t + ' · Pocketful'; }

  // ---------- shared components ----------
  function field(id, label, input, hint) {
    input.id = id;
    return h('div', { class: 'field' }, h('label', { for: id, text: label }), input, hint ? h('span', { class: 'hint', text: hint }) : null);
  }
  function textInput(testid, o) {
    o = o || {};
    return h('input', { type: 'text', 'data-testid': testid, autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', inputmode: o.decimal ? 'decimal' : null, placeholder: o.placeholder, maxlength: o.maxlength });
  }
  function visibilitySelect(testid) {
    return h('select', { 'data-testid': testid },
      h('option', { value: 'public', text: 'Public – visible in the feed' }),
      h('option', { value: 'private', text: 'Private – only you and the recipient' }));
  }

  function walletCard(withRefresh, onRefresh) {
    var avail = h('p', { class: 'headline' }, h('span', { class: 'skeleton' }));
    var totalDd = h('dd', null, h('span', { class: 'skeleton' }));
    var heldRow = h('div', { class: 'held' });
    var sub = h('dl', { class: 'wallet-sub' }, h('div', null, h('dt', { text: 'Total balance' }), totalDd), heldRow);
    var btn = withRefresh ? h('button', { type: 'button', class: 'on-dark', 'data-testid': 'wallet-refresh', text: 'Refresh', onclick: onRefresh }) : null;
    var err = h('div');
    var el = h('section', { class: 'card wallet', 'aria-labelledby': 'wallet-h', 'aria-busy': 'true' },
      h('h1', { class: 'eyebrow', id: 'wallet-h', text: 'Available to spend' }), avail, sub,
      withRefresh ? h('div', { class: 'wallet-foot' }, btn) : null, err);
    heldRow.hidden = true;
    return {
      el: el,
      set: function (m) {
        clear(avail);
        avail.setAttribute('data-testid', 'wallet-available');
        avail.setAttribute('data-amount', m.available);
        avail.textContent = fmt(m.available);
        clear(totalDd);
        totalDd.setAttribute('data-testid', 'wallet-balance');
        totalDd.setAttribute('data-amount', m.total);
        totalDd.textContent = fmt(m.total);
        clear(heldRow);
        if (m.held > 0) {
          heldRow.hidden = false;
          heldRow.appendChild(h('dt', { text: 'On hold' }));
          heldRow.appendChild(h('dd', { 'data-testid': 'wallet-held', 'data-amount': m.held, text: fmt(m.held) }));
        } else {
          heldRow.hidden = true;
        }
      },
      busy: function (b) {
        el.setAttribute('aria-busy', b ? 'true' : 'false');
        if (btn) { btn.textContent = b ? 'Refreshing…' : 'Refresh'; }
      },
      error: function (text) { setMsg(err, 'error', 'refresh-error', text); },
    };
  }

  // A form that creates something for a handle (payment or authorization).
  function moneyForm(o) {
    var handle = textInput(o.id + '-handle', { placeholder: 'e.g. bob' });
    var amount = textInput(o.id + '-amount', { decimal: true, placeholder: '0.00' });
    var note = textInput(o.id + '-note', { maxlength: 200 });
    var vis = visibilitySelect(o.id + '-visibility');
    var out = h('div', { 'aria-live': 'polite' });
    var errBox = h('div');
    var btn = h('button', { type: 'submit', class: o.primary ? 'primary' : 'secondary', 'data-testid': o.id + '-submit', text: o.button });
    var sending = false;

    function showError(t) { setMsg(errBox, 'error', o.id + '-error', t); }
    function showUncertain(t) { setMsg(out, 'uncertain', o.id + '-uncertain', t); }
    function showOk(t) { setMsg(out, 'success', o.id + '-success', t); }

    function submit(ev) {
      ev.preventDefault();
      if (sending) return;
      var hd = normHandle(handle.value);
      var p = parseAmount(amount.value);
      var problem = null;
      if (!hd) problem = 'Enter the handle of the person you want to ' + o.verb + '.';
      else if (p.error) problem = p.error;
      else if (noteTooLong(note.value)) problem = 'Notes can be up to 200 characters.';
      if (problem) { showError(problem); return; }
      var sig = JSON.stringify([handle.value, amount.value, note.value, vis.value]);
      var body = { to_handle: hd, amount: p.minor, note: note.value, visibility: vis.value };
      sending = true;
      btn.disabled = true;
      btn.textContent = o.busy;
      attemptWrite(o.id, sig, function (key) { return api('POST', o.url, { body: body, key: key }); }, o.keepDone).then(function (r) {
        sending = false;
        btn.disabled = false;
        btn.textContent = o.button;
        if (r.skipped) return;
        if (r.ok) {
          setMsg(errBox, '', '', '');
          showOk(o.success(p.minor, hd));
          if (!o.keepDone) { handle.value = ''; amount.value = ''; note.value = ''; vis.value = 'public'; }
          return o.after();
        }
        if (r.error.uncertain) {
          setMsg(errBox, '', '', '');
          showUncertain('We didn’t get a reply, so we can’t tell whether this went through. Select “' + o.button + '” again to retry safely — the same request is sent, so it can only happen once.');
          return;
        }
        setMsg(out, '', '', '');
        showError(explain(r.error));
        return o.after();
      });
    }

    var form = h('form', { novalidate: true, onsubmit: submit },
      field(o.id + '-handle-f', 'Recipient handle', handle, 'Their handle, without the @.'),
      h('div', { class: 'row2' },
        field(o.id + '-amount-f', 'Amount (' + cfg.currency + ')', amount),
        field(o.id + '-vis-f', 'Visibility', vis)),
      field(o.id + '-note-f', 'Note (optional)', note),
      h('div', { class: 'actions' }, btn), errBox, out);
    return h('section', { class: 'card', 'aria-labelledby': o.id + '-h' }, h('h2', { id: o.id + '-h', text: o.title }), h('p', { class: 'lede', text: o.lede }), form);
  }

  function requestForm(after) {
    var handle = textInput('request-handle', { placeholder: 'e.g. ada' });
    var amount = textInput('request-amount', { decimal: true, placeholder: '0.00' });
    var note = textInput('request-note', { maxlength: 200 });
    var out = h('div', { 'aria-live': 'polite' });
    var errBox = h('div');
    var btn = h('button', { type: 'submit', class: 'secondary', 'data-testid': 'request-submit', text: 'Request money' });
    var sending = false;
    function submit(ev) {
      ev.preventDefault();
      if (sending) return;
      var hd = normHandle(handle.value);
      var p = parseAmount(amount.value);
      var problem = !hd ? 'Enter the handle of the person you want to ask.' : p.error ? p.error : noteTooLong(note.value) ? 'Notes can be up to 200 characters.' : null;
      if (problem) { setMsg(errBox, 'error', 'request-error', problem); return; }
      var sig = JSON.stringify([handle.value, amount.value, note.value]);
      sending = true;
      btn.disabled = true;
      btn.textContent = 'Sending…';
      attemptWrite('request', sig, function (key) {
        return api('POST', '/requests', { body: { payer_handle: hd, amount: p.minor, note: note.value }, key: key });
      }).then(function (r) {
        sending = false;
        btn.disabled = false;
        btn.textContent = 'Request money';
        if (r.skipped) return;
        if (r.ok) {
          setMsg(errBox, '', '', '');
          setMsg(out, 'success', 'request-success', 'Requested ' + fmt(p.minor) + ' from @' + hd + '. You can follow it on the Requests page.');
          handle.value = ''; amount.value = ''; note.value = '';
          return after();
        }
        if (r.error.uncertain) {
          setMsg(errBox, '', '', '');
          setMsg(out, 'uncertain', 'request-uncertain', 'We didn’t get a reply, so we can’t tell whether the request was created. Select “Request money” again to retry safely.');
          return;
        }
        setMsg(out, '', '', '');
        setMsg(errBox, 'error', 'request-error', explain(r.error));
      });
    }
    return h('section', { class: 'card', 'aria-labelledby': 'request-h' },
      h('h2', { id: 'request-h', text: 'Request money' }),
      h('p', { class: 'lede', text: 'Ask someone to pay you. They choose whether to pay.' }),
      h('form', { novalidate: true, onsubmit: submit },
        field('request-handle-f', 'Who should pay?', handle, 'Their handle, without the @.'),
        field('request-amount-f', 'Amount (' + cfg.currency + ')', amount),
        field('request-note-f', 'Note (optional)', note),
        h('div', { class: 'actions' }, btn), errBox, out));
  }

  function authorizeForm(after) {
    return moneyForm({
      id: 'authorize', url: '/authorizations', title: 'Reserve funds',
      lede: 'Hold money for someone to collect later. Reserved funds can’t be spent until collected, released or expired.',
      button: 'Authorize', busy: 'Authorizing…', verb: 'reserve money for', primary: false,
      success: function (n, hd) { return 'Reserved ' + fmt(n) + ' for @' + hd + '.'; },
      after: after,
    });
  }

  function skeletonRows(n) {
    var d = h('div', { 'aria-hidden': 'true' });
    for (var i = 0; i < n; i++) d.appendChild(h('span', { class: 'sk-dark' }));
    return d;
  }
  function loadError(text, retry) {
    return h('div', { class: 'msg error', role: 'alert', 'data-testid': 'load-error' }, h('strong', { text: 'We couldn’t load this.' }), text || '', ' ', h('button', { type: 'button', class: 'secondary', text: 'Try again', onclick: retry }));
  }

  // ---------- pages ----------
  function homePage(main) {
    setTitle('Wallet');
    var seq = latest();
    var feed = h('div', { 'aria-live': 'polite' }, skeletonRows(3));
    var items = [];
    var more = false;
    var firstLoaded = false;
    var loads = 0;

    var wallet = walletCard(true, function () { load(); });

    function renderFeed() {
      clear(feed);
      if (items.length === 0) {
        feed.appendChild(h('div', { class: 'empty', 'data-testid': 'empty-activity' }, h('strong', { text: 'No activity yet' }), 'Payments you send, receive or see in the public feed will appear here.'));
        return;
      }
      var ol = h('ol', { class: 'list', 'data-testid': 'activity-list' });
      items.forEach(function (p) {
        var dir = p.from_user_id === me.user_id ? 'sent' : p.to_user_id === me.user_id ? 'received' : 'other';
        var dirText = dir === 'sent' ? 'You paid' : dir === 'received' ? 'You received' : 'Public payment';
        ol.appendChild(h('li', { class: 'item ' + dir, 'data-testid': 'activity-item-' + p.payment_id, 'data-visibility': p.visibility },
          h('div', { class: 'item-top' },
            h('span', { class: 'parties', 'data-testid': 'activity-parties-' + p.payment_id },
              '@' + p.from_handle, h('span', { class: 'sr', text: ' paid ' }), h('span', { 'aria-hidden': 'true', text: ' → ' }), '@' + p.to_handle),
            h('span', { class: 'amount', 'data-testid': 'activity-amount-' + p.payment_id, text: fmt(p.amount) })),
          h('p', { class: 'note', 'data-testid': 'activity-note-' + p.payment_id, text: p.note }),
          h('div', { class: 'meta' },
            h('span', { class: 'chip ' + (dir === 'other' ? '' : dir), text: dirText }),
            h('span', { class: 'chip ' + (p.visibility === 'private' ? 'private' : ''), text: p.visibility === 'private' ? '🔒 Private' : 'Public' }),
            timeEl(p.created_at))));
      });
      feed.appendChild(ol);
      if (more) {
        feed.appendChild(h('div', { class: 'actions' }, h('button', { type: 'button', class: 'secondary', text: 'Show more', onclick: showMore })));
      }
    }

    function showMore() {
      var gen = loads;
      api('GET', '/activity?limit=200&offset=' + items.length).then(function (r) {
        if (gen !== loads) return; // a refresh replaced the list meanwhile
        items = items.concat(r.data.payments);
        more = r.data.has_more;
        renderFeed();
      }, function () { /* leave the list as it is */ });
    }

    function load() {
      var my = seq.next();
      loads++;
      wallet.busy(true);
      return Promise.all([api('GET', '/me'), api('GET', '/activity?limit=200&offset=0')]).then(function (rs) {
        if (!seq.is(my)) return; // latest refresh wins
        applyMe(rs[0].data);
        wallet.set(rs[0].data);
        wallet.error('');
        items = rs[1].data.payments;
        more = rs[1].data.has_more;
        firstLoaded = true;
        renderFeed();
        wallet.busy(false);
      }, function (e) {
        if (!seq.is(my)) return;
        wallet.busy(false);
        if (firstLoaded) {
          wallet.error('We couldn’t refresh just now, so the figures below may be out of date. Select Refresh to try again.');
        } else {
          clear(feed);
          feed.appendChild(loadError('Check your connection and try again.', load));
        }
      });
    }

    // The forms need the currency; build them once /me has answered.
    var slot = h('div', { class: 'grid2' });
    var reserveSlot = h('div');
    main.appendChild(wallet.el);
    main.appendChild(slot);
    main.appendChild(reserveSlot);
    main.appendChild(h('section', { class: 'card', 'aria-labelledby': 'feed-h' },
      h('h2', { id: 'feed-h', text: 'Activity' }), h('p', { class: 'lede', text: 'Public payments and your own, newest first.' }), feed));

    wallet.busy(true);
    api('GET', '/me').then(function (r) {
      applyMe(r.data);
      var pay = moneyForm({
        id: 'pay', url: '/payments', title: 'Send money', lede: 'Pay anyone by handle. The money moves immediately.',
        button: 'Send payment', busy: 'Sending…', verb: 'pay', primary: true, keepDone: true,
        success: function (n, hd) { return 'Sent ' + fmt(n) + ' to @' + hd + '.'; },
        after: load,
      });
      slot.appendChild(pay);
      slot.appendChild(requestForm(load));
      reserveSlot.appendChild(authorizeForm(load));
      return load();
    }, function (e) {
      wallet.busy(false);
      clear(feed);
      feed.appendChild(loadError('Check your connection and try again.', function () { location.reload(); }));
    });
  }

  function requestsPage(main) {
    setTitle('Requests');
    var seq = latest();
    var wallet = walletCard(false);
    var errBox = h('div', { 'aria-live': 'polite' });
    var body = h('div', { class: 'grid2' });
    var top = h('div', { 'aria-live': 'polite' }, skeletonRows(2));
    var busy = false;
    var firstLoaded = false;

    main.appendChild(h('h1', { class: 'page-title', text: 'Requests' }));
    main.appendChild(wallet.el);
    main.appendChild(errBox);
    main.appendChild(top);
    main.appendChild(body);

    function fetchAll(offset, acc) {
      return api('GET', '/requests?limit=200&offset=' + offset).then(function (r) {
        acc = acc.concat(r.data.requests);
        return r.data.has_more ? fetchAll(offset + 200, acc) : acc;
      });
    }

    function load() {
      var my = seq.next();
      return Promise.all([api('GET', '/me'), fetchAll(0, [])]).then(function (rs) {
        if (!seq.is(my)) return;
        applyMe(rs[0].data);
        wallet.set(rs[0].data);
        wallet.busy(false);
        firstLoaded = true;
        clear(top);
        render(rs[1]);
      }, function () {
        if (!seq.is(my)) return;
        wallet.busy(false);
        if (!firstLoaded) {
          clear(top);
          top.appendChild(loadError('Check your connection and try again.', load));
        } else {
          setMsg(errBox, 'error', 'refresh-error', 'We couldn’t refresh the list just now, so it may be out of date.');
        }
      });
    }

    function run(btn, work) {
      if (busy) return;
      busy = true;
      Array.prototype.forEach.call(main.querySelectorAll('button'), function (b) { b.disabled = true; });
      var finish = function () {
        busy = false;
        Array.prototype.forEach.call(main.querySelectorAll('button'), function (b) { b.disabled = false; });
      };
      work().then(finish, finish);
    }

    function actionDone(r, okText, slotName) {
      if (r.skipped) return load();
      if (r.ok) {
        setMsg(errBox, 'success', 'request-success', okText);
        return load();
      }
      if (r.error.uncertain) {
        setMsg(errBox, 'uncertain', 'request-uncertain', 'We didn’t get a reply, so we can’t tell whether that went through. Try the same action again, or refresh the list to check.');
        return load();
      }
      setMsg(errBox, 'error', 'request-error', explain(r.error));
      return load(); // stale buttons disappear once the list is current
    }

    function payIt(r, vis) {
      run(null, function () {
        return attemptWrite('rpay:' + r.request_id, vis, function (key) {
          return api('POST', '/requests/' + encodeURIComponent(r.request_id) + '/pay', { body: { visibility: vis }, key: key });
        }).then(function (res) { return actionDone(res, 'Paid ' + fmt(r.amount) + ' to @' + r.requester_handle + '.'); });
      });
    }
    function simple(r, verb, past) {
      run(null, function () {
        return api('POST', '/requests/' + encodeURIComponent(r.request_id) + '/' + verb).then(
          function () { return actionDone({ ok: true }, 'Request ' + past + '.'); },
          function (e) { return actionDone({ error: e }); });
      });
    }

    function item(r, incoming) {
      var vis = null;
      var actions = null;
      if (r.status === 'pending') {
        if (incoming) {
          vis = h('select', { 'aria-label': 'Visibility of your payment', id: 'rv-' + r.request_id, 'data-testid': 'request-visibility-' + r.request_id },
            h('option', { value: 'public', text: 'Pay publicly' }), h('option', { value: 'private', text: 'Pay privately' }));
          actions = h('div', { class: 'actions' }, vis,
            h('button', { type: 'button', class: 'primary', 'data-testid': 'request-pay-' + r.request_id, text: 'Pay ' + fmt(r.amount), onclick: function (ev) { payIt(r, vis.value); } }),
            h('button', { type: 'button', class: 'danger', 'data-testid': 'request-decline-' + r.request_id, text: 'Decline', onclick: function () { simple(r, 'decline', 'declined'); } }));
        } else {
          actions = h('div', { class: 'actions' },
            h('button', { type: 'button', class: 'danger', 'data-testid': 'request-cancel-' + r.request_id, text: 'Cancel request', onclick: function () { simple(r, 'cancel', 'cancelled'); } }));
        }
      }
      var label = r.status.charAt(0).toUpperCase() + r.status.slice(1);
      return h('li', { class: 'item st-' + r.status, 'data-testid': 'request-item-' + r.request_id, 'data-status': r.status },
        h('div', { class: 'item-top' },
          h('span', { class: 'parties', text: incoming ? '@' + r.requester_handle + ' asks you' : 'You ask @' + r.payer_handle }),
          h('span', { class: 'amount', 'data-testid': 'request-amount-' + r.request_id, text: fmt(r.amount) })),
        h('p', { class: 'note', text: r.note }),
        h('div', { class: 'meta' }, h('span', { class: 'chip ' + r.status, text: label }), timeEl(r.created_at)),
        actions);
    }

    function render(all) {
      var inc = all.filter(function (r) { return r.payer_id === me.user_id; });
      var out = all.filter(function (r) { return r.requester_id === me.user_id; });
      clear(top);
      clear(body);
      var empty = inc.length === 0 && out.length === 0;
      if (empty) {
        top.appendChild(h('div', { class: 'empty', 'data-testid': 'empty-requests' }, h('strong', { text: 'No requests yet' }), 'Ask someone for money from the Wallet page, or split a bill.'));
      }
      var il = h('ul', { class: 'list', 'data-testid': 'incoming-list' });
      var ol = h('ul', { class: 'list', 'data-testid': 'outgoing-list' });
      inc.forEach(function (r) { il.appendChild(item(r, true)); });
      out.forEach(function (r) { ol.appendChild(item(r, false)); });
      var ic = h('section', { class: 'card', 'aria-labelledby': 'inc-h' }, h('h2', { id: 'inc-h', text: 'Incoming' }), h('p', { class: 'lede', text: 'People asking you for money.' }), il);
      var oc = h('section', { class: 'card', 'aria-labelledby': 'out-h' }, h('h2', { id: 'out-h', text: 'Outgoing' }), h('p', { class: 'lede', text: 'Requests you have made.' }), ol);
      if (empty) { ic.hidden = true; oc.hidden = true; }
      body.appendChild(ic);
      body.appendChild(oc);
    }

    load();
  }

  function authorizationsPage(main) {
    setTitle('Authorizations');
    var seq = latest();
    var wallet = walletCard(false);
    var errBox = h('div', { 'aria-live': 'polite' });
    var listBox = h('div', { 'aria-live': 'polite' }, skeletonRows(2));
    var busy = false;
    var firstLoaded = false;
    var drafts = {};

    function fetchAll(offset, acc) {
      return api('GET', '/authorizations?limit=200&offset=' + offset).then(function (r) {
        acc = acc.concat(r.data.authorizations);
        return r.data.has_more ? fetchAll(offset + 200, acc) : acc;
      });
    }

    function load() {
      var my = seq.next();
      return Promise.all([api('GET', '/me'), fetchAll(0, [])]).then(function (rs) {
        if (!seq.is(my)) return;
        applyMe(rs[0].data);
        wallet.set(rs[0].data);
        wallet.busy(false);
        firstLoaded = true;
        render(rs[1]);
      }, function () {
        if (!seq.is(my)) return;
        wallet.busy(false);
        if (!firstLoaded) {
          clear(listBox);
          listBox.appendChild(loadError('Check your connection and try again.', load));
        } else {
          setMsg(errBox, 'error', 'refresh-error', 'We couldn’t refresh the list just now, so it may be out of date.');
        }
      });
    }

    function run(work) {
      if (busy) return;
      busy = true;
      Array.prototype.forEach.call(listBox.querySelectorAll('button'), function (b) { b.disabled = true; });
      var finish = function () {
        busy = false;
        Array.prototype.forEach.call(listBox.querySelectorAll('button'), function (b) { b.disabled = false; });
      };
      work().then(finish, finish);
    }

    function done(r, okText) {
      if (r.skipped) return load();
      if (r.ok) {
        setMsg(errBox, 'success', 'authorization-success', okText);
        return load();
      }
      if (r.error.uncertain) {
        setMsg(errBox, 'uncertain', 'authorization-uncertain', 'We didn’t get a reply, so we can’t tell whether that went through. Try again with the same details; it can only happen once.');
        return load();
      }
      setMsg(errBox, 'error', 'authorization-error', explain(r.error));
      return load();
    }

    function capture(a, amountInput, keep) {
      var p = parseAmount(amountInput.value);
      if (p.error) { setMsg(errBox, 'error', 'authorization-error', p.error); return; }
      var body = keep.checked ? { amount: p.minor, final: false } : { amount: p.minor };
      run(function () {
        return attemptWrite('cap:' + a.authorization_id, JSON.stringify(body), function (key) {
          return api('POST', '/authorizations/' + encodeURIComponent(a.authorization_id) + '/capture', { body: body, key: key });
        }).then(function (res) {
          if (res.ok) delete drafts[a.authorization_id];
          return done(res, 'Collected ' + fmt(p.minor) + ' from @' + a.from_handle + '.');
        });
      });
    }
    function voidIt(a) {
      run(function () {
        return api('POST', '/authorizations/' + encodeURIComponent(a.authorization_id) + '/void').then(
          function () { return done({ ok: true }, 'Released the hold for @' + a.to_handle + '.'); },
          function (e) { return done({ error: e }); });
      });
    }

    function item(a) {
      var id = a.authorization_id;
      var incoming = a.to_user_id === me.user_id;
      var label = a.status.charAt(0).toUpperCase() + a.status.slice(1);
      var extra = null;
      if (a.status === 'open' && incoming) {
        var d = drafts[id];
        if (!d || d.rem !== a.remaining_amount) d = drafts[id] = { rem: a.remaining_amount, value: plain(a.remaining_amount), keep: false };
        var inp = textInput('authorization-capture-amount-' + id, { decimal: true });
        inp.value = d.value;
        inp.addEventListener('input', function () { d.value = inp.value; });
        var keep = h('input', { type: 'checkbox', id: 'keep-' + id, 'data-testid': 'authorization-keep-' + id });
        keep.checked = d.keep;
        keep.addEventListener('change', function () { d.keep = keep.checked; });
        extra = h('div', { class: 'cap-form' },
          field('cap-' + id, 'Amount to collect (' + cfg.currency + ')', inp),
          h('label', { class: 'check', for: 'keep-' + id }, keep, 'Keep the rest on hold'),
          h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primary', 'data-testid': 'authorization-capture-' + id, text: 'Collect', onclick: function () { capture(a, inp, keep); } })));
      } else if (a.status === 'open') {
        extra = h('div', { class: 'actions' }, h('button', { type: 'button', class: 'danger', 'data-testid': 'authorization-void-' + id, text: 'Release hold', onclick: function () { voidIt(a); } }));
      }
      var expLabel = a.status === 'open' ? 'Expires' : a.status === 'expired' ? 'Expired' : 'Expiry';
      return h('li', { class: 'item st-' + a.status, 'data-testid': 'authorization-item-' + id, 'data-status': a.status },
        h('div', { class: 'item-top' },
          h('span', { class: 'parties', text: incoming ? '@' + a.from_handle + ' reserved for you' : 'You reserved for @' + a.to_handle }),
          h('span', { class: 'amount', 'data-testid': 'authorization-amount-' + id, text: fmt(a.amount) })),
        h('p', { class: 'note', text: a.note }),
        h('div', { class: 'meta' },
          h('span', { class: 'chip ' + a.status, text: label }),
          h('span', { class: 'chip ' + (a.visibility === 'private' ? 'private' : ''), text: a.visibility === 'private' ? '🔒 Private' : 'Public' }),
          h('span', null, expLabel + ' ', timeEl(a.expires_at, 'authorization-expires-' + id), ' (' + relative(a.expires_at) + ')')),
        a.status === 'captured' ? h('div', { class: 'meta' }, 'Collected ', h('strong', { 'data-testid': 'authorization-captured-' + id, text: fmt(a.captured_amount) })) : null,
        a.status !== 'captured' && a.captured_amount > 0 ? h('div', { class: 'meta' }, 'Collected so far ' + fmt(a.captured_amount) + '; ' + fmt(a.remaining_amount) + ' still held.') : null,
        extra);
    }

    function render(all) {
      clear(listBox);
      if (all.length === 0) {
        listBox.appendChild(h('div', { class: 'empty', 'data-testid': 'empty-authorizations' }, h('strong', { text: 'No authorizations yet' }), 'Reserve funds for someone to collect later, or wait for someone to reserve funds for you.'));
        return;
      }
      var ul = h('ul', { class: 'list', 'data-testid': 'authorization-list' });
      all.forEach(function (a) { ul.appendChild(item(a)); });
      listBox.appendChild(ul);
    }

    main.appendChild(h('h1', { class: 'page-title', text: 'Authorizations' }));
    main.appendChild(wallet.el);
    var formSlot = h('div');
    main.appendChild(formSlot);
    main.appendChild(errBox);
    main.appendChild(h('section', { class: 'card', 'aria-labelledby': 'auth-h' },
      h('h2', { id: 'auth-h', text: 'Reserved funds' }), h('p', { class: 'lede', text: 'Newest first. Collect what’s reserved for you, or release your own holds.' }), listBox));
    api('GET', '/me').then(function (r) {
      applyMe(r.data);
      formSlot.appendChild(authorizeForm(load));
      return load();
    }, function () {
      clear(listBox);
      listBox.appendChild(loadError('Check your connection and try again.', function () { location.reload(); }));
    });
  }

  function splitPage(main) {
    setTitle('Split a bill');
    var seqUnused = null;
    void seqUnused;
    main.appendChild(h('h1', { class: 'page-title', text: 'Split a bill' }));
    var holder = h('div');
    main.appendChild(holder);
    api('GET', '/me').then(function (r) {
      applyMe(r.data);
      build();
    }, function () {
      holder.appendChild(loadError('Check your connection and try again.', function () { location.reload(); }));
    });

    function build() {
      var amount = textInput('split-amount', { decimal: true, placeholder: '0.00' });
      var handles = textInput('split-handles', { placeholder: 'ada, bob, cy' });
      var note = textInput('split-note', { maxlength: 200 });
      var previewBox = h('div', { 'aria-live': 'polite' });
      var errBox = h('div');
      var out = h('div', { 'aria-live': 'polite' });
      var btn = h('button', { type: 'submit', class: 'primary', 'data-testid': 'split-submit', text: 'Split and request' });
      var sending = false;

      function parseHandles() {
        return handles.value.split(',').map(normHandle).filter(function (x) { return x !== ''; });
      }
      // Equal split by the service's rule: base share each, extra minor units to the first participants.
      function shares(total, list) {
        var base = Math.floor(total / list.length);
        var rem = total - base * list.length;
        return list.map(function (hd, i) { return { handle: hd, amount: base + (i < rem ? 1 : 0) }; });
      }
      function problem() {
        var p = parseAmount(amount.value);
        var list = parseHandles();
        if (p.error) return { text: p.error };
        if (list.length === 0) return { text: 'Add at least one handle, separated by commas.' };
        if (new Set(list).size !== list.length) return { text: 'Each handle can only appear once.' };
        return { p: p.minor, list: list };
      }
      function preview() {
        clear(previewBox);
        var v = problem();
        if (!v.list) {
          previewBox.appendChild(h('p', { class: 'hint', 'data-testid': 'split-hint', text: amount.value.trim() === '' && handles.value.trim() === '' ? 'Enter an amount and who is splitting to preview each share.' : v.text }));
          return;
        }
        var ul = h('ul');
        shares(v.p, v.list).forEach(function (s) {
          ul.appendChild(h('li', null, h('span', { class: 'who-h', text: '@' + s.handle }), h('span', { class: 'amount', 'data-testid': 'split-share-' + s.handle, text: fmt(s.amount) })));
        });
        previewBox.appendChild(h('div', { class: 'preview', 'data-testid': 'split-preview' },
          h('strong', { text: 'Each share' }), h('div', { class: 'hint', text: 'Extra minor units go to the first people listed. If you are included, you pay your own share.' }), ul));
      }
      amount.addEventListener('input', preview);
      handles.addEventListener('input', preview);

      function submit(ev) {
        ev.preventDefault();
        if (sending) return;
        var v = problem();
        if (!v.list) { setMsg(errBox, 'error', 'split-error', v.text); return; }
        if (noteTooLong(note.value)) { setMsg(errBox, 'error', 'split-error', 'Notes can be up to 200 characters.'); return; }
        var body = { amount: v.p, participant_handles: v.list, note: note.value };
        sending = true;
        btn.disabled = true;
        btn.textContent = 'Splitting…';
        attemptWrite('split', JSON.stringify(body), function (key) { return api('POST', '/splits', { body: body, key: key }); }).then(function (r) {
          sending = false;
          btn.disabled = false;
          btn.textContent = 'Split and request';
          if (r.skipped) return;
          if (r.ok) {
            setMsg(errBox, '', '', '');
            var n = r.res.requests.length;
            clear(out);
            out.appendChild(h('div', { class: 'msg success', role: 'status', 'data-testid': 'split-success' },
              'Split ' + fmt(v.p) + ' between ' + v.list.length + (v.list.length === 1 ? ' person. ' : ' people. '),
              n === 0 ? 'No requests were needed.' : n + (n === 1 ? ' request was' : ' requests were') + ' sent. ',
              n === 0 ? null : h('a', { href: '/requests', text: 'View requests' })));
            amount.value = ''; handles.value = ''; note.value = '';
            preview();
            return;
          }
          if (r.error.uncertain) {
            setMsg(errBox, '', '', '');
            setMsg(out, 'uncertain', 'split-uncertain', 'We didn’t get a reply, so we can’t tell whether the split was created. Select “Split and request” again to retry safely.');
            return;
          }
          setMsg(out, '', '', '');
          setMsg(errBox, 'error', 'split-error', explain(r.error));
        });
      }

      clear(holder);
      holder.appendChild(h('section', { class: 'card narrow', style: null, 'aria-labelledby': 'split-h' },
        h('h2', { id: 'split-h', text: 'Split an amount you paid' }),
        h('p', { class: 'lede', text: 'We’ll request each other person’s share from them.' }),
        h('form', { novalidate: true, onsubmit: submit },
          field('split-amount-f', 'Total amount (' + cfg.currency + ')', amount),
          field('split-handles-f', 'Who is splitting? (handles, comma-separated)', handles, 'Order matters: extra minor units go to the first people listed.'),
          field('split-note-f', 'Note (optional)', note),
          previewBox,
          h('div', { class: 'actions' }, btn), errBox, out)));
      preview();
    }
  }

  function authPage(kind) {
    var signup = kind === 'signup';
    setTitle(signup ? 'Sign up' : 'Log in');
    var email = h('input', { type: 'email', 'data-testid': kind + '-email', autocomplete: signup ? 'email' : 'username', autocapitalize: 'off' });
    var pw = h('input', { type: 'password', 'data-testid': kind + '-password', autocomplete: signup ? 'new-password' : 'current-password' });
    var name = signup ? h('input', { type: 'text', 'data-testid': 'signup-display-name', autocomplete: 'name' }) : null;
    var errBox = h('div');
    var btn = h('button', { type: 'submit', class: 'primary', 'data-testid': kind + '-submit', text: signup ? 'Create account' : 'Log in' });
    var sending = false;
    function submit(ev) {
      ev.preventDefault();
      if (sending) return;
      var body = signup ? { email: email.value.trim(), password: pw.value, display_name: name.value.trim() } : { email: email.value.trim(), password: pw.value };
      if (!body.email || !pw.value || (signup && !body.display_name)) {
        setMsg(errBox, 'error', 'auth-error', signup ? 'Enter your name, email and a password.' : 'Enter your email and password.');
        return;
      }
      if (signup && Array.from(pw.value).length < 8) {
        setMsg(errBox, 'error', 'auth-error', 'Choose a password of at least 8 characters.');
        return;
      }
      sending = true;
      btn.disabled = true;
      btn.textContent = signup ? 'Creating account…' : 'Logging in…';
      api('POST', signup ? '/auth/signup' : '/auth/login', { body: body, auth: false }).then(function (r) {
        store(TOKEN_KEY, r.data.token);
        location.assign('/');
      }, function (e) {
        sending = false;
        btn.disabled = false;
        btn.textContent = signup ? 'Create account' : 'Log in';
        setMsg(errBox, 'error', 'auth-error', e.uncertain ? 'We couldn’t reach Pocketful. Check your connection and try again.' : explain(e));
      });
    }
    var main = document.getElementById('main');
    main.appendChild(h('section', { class: 'card narrow', 'aria-labelledby': 'auth-h' },
      h('h1', { class: 'page-title', id: 'auth-h', text: signup ? 'Create your account' : 'Welcome back' }),
      h('p', { class: 'lede', text: signup ? 'Pay, request and split in seconds.' : 'Log in to your wallet.' }),
      h('form', { novalidate: true, onsubmit: submit },
        signup ? field('f-name', 'Display name', name) : null,
        field('f-email', 'Email', email),
        field('f-pw', 'Password', pw, signup ? 'At least 8 characters.' : null),
        h('div', { class: 'actions' }, btn), errBox),
      h('p', { class: 'hint', style: null }, signup ? 'Already have an account? ' : 'New here? ', h('a', { href: signup ? '/login' : '/signup', text: signup ? 'Log in' : 'Create an account' }))));
    // Show who is signed in, if anyone, on every screen.
    if (getToken()) {
      api('GET', '/me').then(function (r) { applyMe(r.data); }, function () {});
    }
  }

  // ---------- boot ----------
  renderChrome();
  var main = document.getElementById('main');
  if (route === '/login' || route === '/signup') {
    authPage(route.slice(1));
  } else if (!getToken()) {
    location.replace('/login');
  } else if (route === '/requests') {
    requestsPage(main);
  } else if (route === '/authorizations') {
    authorizationsPage(main);
  } else if (route === '/split') {
    splitPage(main);
  } else {
    homePage(main);
  }
})();
