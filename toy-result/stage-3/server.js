'use strict';
const http = require('http');
const fs = require('fs');
const nodePath = require('path');

const INDEX = fs.readFileSync(nodePath.join(__dirname, 'index.html'), 'utf8');
const PORT = parseInt(process.env.PORT, 10) || 8080;
let counter = 0;

function send(res, status, body) {
  if (body === undefined) {
    res.writeHead(status);
    return res.end();
  }
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function readBody(req, cb) {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => cb(Buffer.concat(chunks).toString('utf8')));
  req.on('error', () => cb(''));
}

function parseJson(text) {
  if (text.trim() === '') return { ok: true, value: {} };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (e) {
    return { ok: false };
  }
}

const server = http.createServer((req, res) => {
  const path = (req.url || '/').split('?')[0];
  const method = req.method;

  if (method === 'GET' && path === '/') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    return res.end(INDEX);
  }
  if (method === 'GET' && path === '/health') return send(res, 200, { status: 'ok' });
  if (method === 'GET' && path === '/counter') return send(res, 200, { value: counter });

  if (method === 'POST' && path === '/counter/increment') {
    return readBody(req, () => {
      // Single-threaded event loop: this read-modify-write is one synchronous
      // step with no await/yield between read and write, so it is atomic.
      counter += 1;
      send(res, 200, { value: counter });
    });
  }

  if (method === 'POST' && path === '/_test/reset') {
    return readBody(req, (text) => {
      const p = parseJson(text);
      const v = p.ok && p.value !== null && typeof p.value === 'object' ? p.value.value : undefined;
      if (!Number.isInteger(v) || v < 0 || v > 1000000) return send(res, 400, { error: 'invalid value' });
      counter = v;
      send(res, 204);
    });
  }

  send(res, 404, { error: 'not found' });
});

server.listen(PORT, '0.0.0.0', () => console.log('listening on ' + PORT));
