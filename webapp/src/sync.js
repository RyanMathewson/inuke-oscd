// Maps every incoming decoded OSC message (from a GET reply during sync, or
// an unsolicited device push like /meter or /lock) onto the central store.
// SETs issued by the UI don't get echoed by the device, so this only ever
// reflects what the device itself reported -- see each UI module for the
// separate optimistic update applied immediately after a successful SET.
import { channelPatch } from './state.js';

const CHANNEL_ADDR = /^\/channel\/(\d)\/(.+)$/;

export function applyMessageToState(store, msg) {
  const { addr, args } = msg;
  if (!args) return;

  switch (addr) {
    case '/info':
      return store.set({ info: { ampName: args[0], firmware: args[1], unknown: args[2] } });
    case '/ampmode':
      return store.set({ ampMode: args[0] });
    case '/gain':
      return store.set({ gain: { gainA: args[0], gainB: args[1], muteA: args[2], muteB: args[3] } });
    case '/lock':
      return store.set({ lock: !!args[0] });
    case '/meter':
      if (args.length === 4) return store.set({ meter: { inputA: args[0], inputB: args[1], outputA: args[2], outputB: args[3] } });
      return;
    case '/preset/name': {
      const [slot, modeEnum, name] = args;
      return store.set((s) => ({ presets: s.presets.map((p) => (p.slot === slot ? { slot, modeEnum, name } : p)) }));
    }
    default:
      break;
  }

  const chMatch = CHANNEL_ADDR.exec(addr);
  if (!chMatch) return;
  const ch = Number(chMatch[1]);
  const rest = chMatch[2];

  let m;
  if ((m = /^peq\/(\d)$/.exec(rest))) {
    const band = Number(m[1]);
    const [type, freq, gain, q] = args;
    return store.set((s) => channelPatch(s, ch, (c) => ({ ...c, peq: { ...c.peq, [band]: { type, freq, gain, q } } })));
  }
  if (rest === 'xover/hp') {
    const [type, freq] = args;
    return store.set((s) => channelPatch(s, ch, (c) => ({ ...c, xover: { ...c.xover, hp: { type, freq } } })));
  }
  if (rest === 'xover/lp') {
    const [type, freq] = args;
    return store.set((s) => channelPatch(s, ch, (c) => ({ ...c, xover: { ...c.xover, lp: { type, freq } } })));
  }
  if (rest === 'xover/gain') {
    return store.set((s) => channelPatch(s, ch, (c) => ({ ...c, xover: { ...c.xover, gain: args[0] } })));
  }
  if ((m = /^deq\/(\d)\/comp$/.exec(rest))) {
    const band = Number(m[1]);
    const [gain, threshold, ratio] = args;
    return store.set((s) =>
      channelPatch(s, ch, (c) => ({ ...c, deq: { ...c.deq, [band]: { ...c.deq[band], comp: { gain, threshold, ratio } } } })),
    );
  }
  if ((m = /^deq\/(\d)\/time$/.exec(rest))) {
    const band = Number(m[1]);
    const [attack, release] = args;
    return store.set((s) =>
      channelPatch(s, ch, (c) => ({ ...c, deq: { ...c.deq, [band]: { ...c.deq[band], time: { attack, release } } } })),
    );
  }
  if ((m = /^deq\/(\d)\/filt$/.exec(rest))) {
    const band = Number(m[1]);
    const [type, freq, q] = args;
    return store.set((s) =>
      channelPatch(s, ch, (c) => ({ ...c, deq: { ...c.deq, [band]: { ...c.deq[band], filt: { type, freq, q } } } })),
    );
  }
  if (rest === 'delay') {
    const [timeMs, phaseDeg] = args;
    return store.set((s) => channelPatch(s, ch, (c) => ({ ...c, delay: { timeMs, phaseDeg } })));
  }
  if (rest === 'limiter') {
    const [thresholdVp, releaseMs, holdMs] = args;
    return store.set((s) => channelPatch(s, ch, (c) => ({ ...c, limiter: { thresholdVp, releaseMs, holdMs } })));
  }
}
