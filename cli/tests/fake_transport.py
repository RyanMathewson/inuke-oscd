"""A fake HID transport implementing the same interface as hidapi's
hid.device() (.write/.read/.close), so INukeClient can be exercised without
a real amp. See inuke_cli/protocol.py's `_open_real_transport` for the real
counterpart this mimics.
"""
from inuke_cli.protocol import REPORT_LEN, osc_decode, osc_encode


class FakeTransport:
    def __init__(self, replies=None):
        # addr -> (typetags, args), or a list of such tuples to reply with in
        # sequence (pop from the front) for addresses queried more than once.
        self.replies = dict(replies or {})
        self.sent: list[dict] = []
        self._queue: list[bytes] = []

    def write(self, data):
        # INukeClient.send() prepends a report-id byte (0x00) before the report.
        report = bytes(data[1 : 1 + REPORT_LEN])
        n = report[0]
        decoded = osc_decode(report[1 : 1 + n])
        if decoded is None:
            return
        self.sent.append(decoded)
        spec = self.replies.get(decoded["addr"])
        if spec is None:
            return
        if isinstance(spec, list):
            if not spec:
                return
            typetags, args = spec.pop(0)
        else:
            typetags, args = spec
        msg = osc_encode(decoded["addr"], typetags, args)
        out = (bytes([len(msg)]) + msg).ljust(REPORT_LEN, b"\x00")
        self._queue.append(out)

    def read(self, length, timeout_ms=100):
        if self._queue:
            return self._queue.pop(0)
        return b""

    def close(self):
        pass
