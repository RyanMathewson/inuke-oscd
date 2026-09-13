import { test } from 'node:test';
import assert from 'node:assert/strict';
import { oscEncode, oscDecode } from '../src/osc.js';

// Byte sequences below are transcribed directly from
// docs/PROTOCOL_NOTES.md's "Confirmed example packets" (live USBPcap
// captures), stripped of the length byte and trailing garbage padding.

test('encodes /ampmode STEREO to match the captured ampmode-change packet', () => {
  const msg = oscEncode('/ampmode', 's', ['STEREO']);
  const expected = Uint8Array.from([
    0x2f, 0x61, 0x6d, 0x70, 0x6d, 0x6f, 0x64, 0x65, 0x00, 0x00, 0x00, 0x00, 0x2c, 0x73, 0x00, 0x00, 0x53, 0x54, 0x45,
    0x52, 0x45, 0x4f, 0x00, 0x00,
  ]);
  assert.deepEqual(Array.from(msg), Array.from(expected));
});

test('encodes /meter ,f 10.0 heartbeat to match the captured packet', () => {
  const msg = oscEncode('/meter', 'f', [10.0]);
  const expected = Uint8Array.from([
    0x2f, 0x6d, 0x65, 0x74, 0x65, 0x72, 0x00, 0x00, 0x2c, 0x66, 0x00, 0x00, 0x41, 0x20, 0x00, 0x00,
  ]);
  assert.deepEqual(Array.from(msg), Array.from(expected));
});

test('/channel/1/limiter round-trips the captured field order [threshold, release, hold]', () => {
  const msg = oscEncode('/channel/1/limiter', 'fff', [69.9, 100.0, 50.0]);
  assert.equal(msg.length, 40); // matches the captured packet's length byte (0x28 = 40)
  const decoded = oscDecode(msg);
  assert.equal(decoded.addr, '/channel/1/limiter');
  assert.equal(decoded.typetags, 'fff');
  assert.ok(Math.abs(decoded.args[0] - 69.9) < 0.01);
  assert.ok(Math.abs(decoded.args[1] - 100.0) < 0.01);
  assert.ok(Math.abs(decoded.args[2] - 50.0) < 0.01);
});

test('round-trips a PEQ band set (values chosen exactly representable in float32)', () => {
  const msg = oscEncode('/channel/2/peq/3', 'sfff', ['LS12', 4000.0, -3.5, 0.5]);
  const decoded = oscDecode(msg);
  assert.deepEqual(decoded, { addr: '/channel/2/peq/3', typetags: 'sfff', args: ['LS12', 4000.0, -3.5, 0.5] });
});

test('a bare GET (empty typetags) encodes and decodes with zero args', () => {
  const msg = oscEncode('/ampmode', '', []);
  const decoded = oscDecode(msg);
  assert.equal(decoded.addr, '/ampmode');
  assert.equal(decoded.typetags, '');
  assert.deepEqual(decoded.args, []);
});

test('preset name GET/reply shape (iis)', () => {
  const req = oscEncode('/preset/name', 'iis', [1, 0, 'DUMMY']);
  const reqDecoded = oscDecode(req);
  assert.deepEqual(reqDecoded.args, [1, 0, 'DUMMY']);

  const reply = oscEncode('/preset/name', 'iis', [1, 0, 'EMPTY']);
  const replyDecoded = oscDecode(reply);
  assert.deepEqual(replyDecoded.args, [1, 0, 'EMPTY']);
});

test('delay message keeps the int argument as Phase, not a float', () => {
  const msg = oscEncode('/channel/1/delay', 'fi', [0.0, 180]);
  const decoded = oscDecode(msg);
  assert.deepEqual(decoded.args, [0.0, 180]);
});

test('oscDecode rejects a non-OSC buffer (no leading slash)', () => {
  assert.equal(oscDecode(Uint8Array.from([0x41, 0x42, 0x43, 0x00])), null);
});

test('oscDecode handles a message with no typetag section (raw tail)', () => {
  const decoded = oscDecode(Uint8Array.from([0x2f, 0x61, 0x00, 0x00]));
  assert.equal(decoded.addr, '/a');
  assert.equal(decoded.typetags, null);
});

test('address and typetag strings always pad to a multiple of 4 with a NUL terminator', () => {
  // 4-char address "/xyz" is already a multiple of 4 but must still get a
  // full 4-byte pad (NUL terminator can't be "free"), per PROTOCOL_NOTES.md.
  const msg = oscEncode('/xyz', '', []);
  assert.equal(msg.length, 12); // 4 ("/xyz") + 4 (pad) + 4 (",\0\0\0")
  assert.deepEqual(Array.from(msg.subarray(0, 8)), [0x2f, 0x78, 0x79, 0x7a, 0x00, 0x00, 0x00, 0x00]);
  assert.deepEqual(Array.from(msg.subarray(8, 12)), [0x2c, 0x00, 0x00, 0x00]);
});
