// OSC 1.0 binary encode/decode matching the iNuke wire protocol.
// See docs/PROTOCOL_NOTES.md ("Application-layer protocol: OSC" and
// "CONFIRMED: USB wire protocol") -- this is a byte-for-byte port of
// scripts/inuke_client.py's osc_encode/osc_decode, verified against the same
// captured packets in tests/osc.test.js.

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder('ascii');

function pad4(bytes) {
  let padLen = (4 - (bytes.length % 4)) % 4;
  if (padLen === 0) padLen = 4; // OSC always NUL-terminates, even if already aligned
  const out = new Uint8Array(bytes.length + padLen);
  out.set(bytes, 0);
  return out;
}

function concatBytes(arrays) {
  const total = arrays.reduce((n, a) => n + a.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const a of arrays) {
    out.set(a, offset);
    offset += a.length;
  }
  return out;
}

export function oscEncode(address, typetags = '', args = []) {
  const parts = [pad4(textEncoder.encode(address)), pad4(textEncoder.encode(',' + typetags))];
  for (let i = 0; i < typetags.length; i++) {
    const t = typetags[i];
    const a = args[i];
    if (t === 'f' || t === 'i') {
      const buf = new ArrayBuffer(4);
      const view = new DataView(buf);
      if (t === 'f') view.setFloat32(0, a, false);
      else view.setInt32(0, a, false);
      parts.push(new Uint8Array(buf));
    } else if (t === 's') {
      parts.push(pad4(textEncoder.encode(String(a))));
    } else {
      throw new Error(`unsupported typetag ${t}`);
    }
  }
  return concatBytes(parts);
}

export function oscDecode(msg) {
  if (!(msg instanceof Uint8Array)) msg = new Uint8Array(msg);
  if (msg.length === 0 || msg[0] !== 0x2f /* '/' */) return null;

  const end = msg.indexOf(0);
  if (end === -1) return null;
  const addr = textDecoder.decode(msg.subarray(0, end));

  let pos = Math.ceil((end + 1) / 4) * 4;
  if (pos >= msg.length || msg[pos] !== 0x2c /* ',' */) {
    return { addr, typetags: null, args: null };
  }

  const tagEnd = msg.indexOf(0, pos);
  const typetags = textDecoder.decode(msg.subarray(pos + 1, tagEnd));
  pos = Math.ceil((tagEnd + 1) / 4) * 4;

  const view = new DataView(msg.buffer, msg.byteOffset, msg.byteLength);
  const args = [];
  for (const t of typetags) {
    if (t === 'f' || t === 'i') {
      args.push(t === 'f' ? view.getFloat32(pos, false) : view.getInt32(pos, false));
      pos += 4;
    } else if (t === 's') {
      let strEnd = msg.indexOf(0, pos);
      if (strEnd === -1) strEnd = msg.length;
      args.push(textDecoder.decode(msg.subarray(pos, strEnd)));
      pos = Math.ceil((strEnd + 1) / 4) * 4;
    } else {
      args.push(`?${t}?`);
    }
  }
  return { addr, typetags, args };
}
