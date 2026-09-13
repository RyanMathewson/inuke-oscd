# iNuke Control (web)

A browser-based replacement for Behringer/Music Group's discontinued **iNuke
Remote Connect** app, built on [WebHID](https://developer.mozilla.org/en-US/docs/Web/API/WebHID_API).
No install, no server, no vendor app -- the page talks to the amp directly
over USB from inside the browser tab.

See [`../docs/PROTOCOL_NOTES.md`](../docs/PROTOCOL_NOTES.md) for the full
reverse-engineered protocol this implements.

## Browser requirement

**WebHID is only implemented in Chromium-based browsers**: desktop Chrome,
Edge, or Opera. Firefox and Safari don't support it -- this is a browser API
limitation, not something this app can work around. Any OS those browsers
run on (Windows/macOS/Linux/ChromeOS) works.

## Running it

This is a static site (plain HTML/CSS/JS, ES modules, no build step, no
dependencies). WebHID requires a "secure context," so opening `index.html`
directly via `file://` won't work in all cases -- serve it over `localhost`
or HTTPS:

```
cd webapp
npm run serve        # serves the current directory at http://localhost:8000
```

(or use any other static file server -- `python -m http.server 8000`, etc.)

Then open `http://localhost:8000/` in Chrome/Edge/Opera and click **Connect**.

## Architecture

- `src/osc.js` -- OSC 1.0 binary encode/decode.
- `src/transport.js` -- thin WebHID wrapper (`navigator.hid`), handles the
  63-byte report framing.
- `src/protocol.js` -- typed get/set methods for every address in
  PROTOCOL_NOTES.md's address table, request/reply matching (serialized
  globally, since replies carry no request id -- see the file's docstring),
  and the full connect-handshake sweep.
- `src/state.js` / `src/sync.js` -- a small central store plus a mapper from
  incoming OSC messages onto it. SETs don't get echoed by the device, so
  each UI module also applies an optimistic update immediately after a
  successful SET (see e.g. `src/ui/peq.js`).
- `src/ui/*.js` -- one module per tab (Setup, Configuration,
  Filter/Crossover, Parametric EQ, Dynamic EQ) plus the live meter bar.
  Vanilla DOM, no framework.

## Testing

```
npm test
```

Runs Node's built-in test runner (`node --test`) over `tests/`. The OSC
codec tests assert byte-for-byte against the actual captured packets quoted
in PROTOCOL_NOTES.md; the protocol tests use a mock transport (no hardware
needed) to exercise request/reply matching, timeouts, and serialization.

There is no way to script the native WebHID device-picker dialog (it's a
browser-chrome-level UI, not part of the page), so connecting to a real amp
has to be tested by hand.

## Known limitations

- **Lock/Unlock is not implemented.** The protocol notes flag this as
  deliberately untested against real hardware (risk of locking the amp into
  a state that needs a recovery code) -- this app only shows the lock state
  read-only, sourced from the `/lock` push that follows `/online`.
- **`/gain` is read-only** in the UI -- SET reaches the device but doesn't
  stick on real hardware (see PROTOCOL_NOTES.md).
- **Limiter threshold is shown in peak volts, not dBFS** -- the vendor app's
  dBFS readout is a locally-computed display whose exact scale was never
  reverse-engineered.
- **The meter bar's scale is an approximation**, not calibrated to
  clipping -- the raw linear-amplitude value is shown alongside it so
  nothing is hidden behind the visual guess (see PROTOCOL_NOTES.md, Open
  Questions #5).
