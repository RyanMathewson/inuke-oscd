import { test } from 'node:test';
import assert from 'node:assert/strict';
import { INukeProtocol, DeviceTimeoutError } from '../src/protocol.js';
import { oscEncode, oscDecode } from '../src/osc.js';

// These tests exercise INukeProtocol's request/reply matching and
// serialization without any real HID device: they replace
// protocol.transport.sendReport with a stub that decodes the outgoing OSC
// message and, if configured, synthesizes a device-shaped reply back
// through the same 'report' event the real transport emits (see
// transport.js's _onInputReport / 'report' CustomEvent).

function encodeReport(address, typetags, args) {
  const msg = oscEncode(address, typetags, args);
  const report = new Uint8Array(63);
  report[0] = msg.length;
  report.set(msg, 1);
  return report;
}

function mockSendReport(protocol, replies, onSend) {
  return async (reportBytes) => {
    const n = reportBytes[0];
    const decoded = oscDecode(reportBytes.subarray(1, 1 + n));
    if (onSend) onSend(decoded);
    const reply = decoded && replies[decoded.addr];
    if (reply) {
      queueMicrotask(() => {
        protocol.transport.dispatchEvent(
          new CustomEvent('report', { detail: encodeReport(decoded.addr, reply[0], reply[1]) }),
        );
      });
    }
  };
}

test('get() resolves with a decoded reply matched by address', async () => {
  const protocol = new INukeProtocol();
  protocol.transport.sendReport = mockSendReport(protocol, { '/ampmode': ['s', ['STEREO']] });
  assert.equal(await protocol.getAmpMode(), 'STEREO');
});

test('get() rejects with DeviceTimeoutError when nothing replies', async () => {
  const protocol = new INukeProtocol();
  protocol.transport.sendReport = mockSendReport(protocol, {});
  await assert.rejects(() => protocol.get('/nope', '', [], 30), DeviceTimeoutError);
});

test('concurrent get() calls are serialized: the second is not sent until the first settles', async () => {
  const order = [];
  const protocol = new INukeProtocol();
  protocol.transport.sendReport = mockSendReport(
    protocol,
    { '/a': ['i', [1]], '/b': ['i', [2]] },
    (decoded) => order.push(decoded.addr),
  );
  const [a, b] = await Promise.all([protocol.get('/a'), protocol.get('/b')]);
  assert.deepEqual(order, ['/a', '/b']);
  assert.equal(a.args[0], 1);
  assert.equal(b.args[0], 2);
});

test('a get() that times out does not block the next queued get()', async () => {
  const protocol = new INukeProtocol();
  protocol.transport.sendReport = mockSendReport(protocol, { '/b': ['i', [2]] });
  const p1 = protocol.get('/a', '', [], 30); // never replies -> times out
  const p2 = protocol.get('/b');
  await assert.rejects(() => p1, DeviceTimeoutError);
  assert.equal((await p2).args[0], 2);
});

test('typed getPeq() decodes sfff args into a named object', async () => {
  const protocol = new INukeProtocol();
  protocol.transport.sendReport = mockSendReport(protocol, {
    '/channel/1/peq/3': ['sfff', ['LS12', 4000.0, -3.5, 0.5]],
  });
  const peq = await protocol.getPeq(1, 3);
  assert.deepEqual(peq, { type: 'LS12', freq: 4000.0, gain: -3.5, q: 0.5 });
});

test('onMessage(address, cb) fires for unsolicited pushes (e.g. /meter) without a matching get()', async () => {
  const protocol = new INukeProtocol();
  const seen = [];
  const unsubscribe = protocol.onMessage('/meter', (m) => seen.push(m.args));
  protocol.transport.dispatchEvent(
    new CustomEvent('report', { detail: encodeReport('/meter', 'ffff', [0.01, 0.02, 0.03, 0.04]) }),
  );
  await new Promise((r) => setTimeout(r, 0));
  unsubscribe();
  assert.equal(seen.length, 1);
  seen[0].forEach((v, i) => assert.ok(Math.abs(v - [0.01, 0.02, 0.03, 0.04][i]) < 1e-6));
});

test('setPeq() sends sfff without waiting for a reply (fire-and-forget)', async () => {
  const protocol = new INukeProtocol();
  const sent = [];
  protocol.transport.sendReport = mockSendReport(protocol, {}, (decoded) => sent.push(decoded));
  await protocol.setPeq(2, 1, 'PEQ', 1000.0, 2.0, 1.0);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { addr: '/channel/2/peq/1', typetags: 'sfff', args: ['PEQ', 1000.0, 2.0, 1.0] });
});
