import unittest

from inuke_cli.protocol import INukeClient
from inuke_cli import snapshot
from .fake_transport import FakeTransport


def _full_reply_map():
    replies = {"/ampmode": ("s", ["STEREO"])}
    for ch in (1, 2):
        for b in range(1, 9):
            replies[f"/channel/{ch}/peq/{b}"] = ("sfff", ["PEQ", 1000.0, 0.0, 1.0])
        replies[f"/channel/{ch}/xover/hp"] = ("sf", ["BUT24", 80.0])
        replies[f"/channel/{ch}/xover/lp"] = ("sf", ["BUT24", 120.0])
        replies[f"/channel/{ch}/xover/gain"] = ("f", [0.0])
        for b in (1, 2):
            replies[f"/channel/{ch}/deq/{b}/comp"] = ("fff", [0.0, -20.0, 1.0])
            replies[f"/channel/{ch}/deq/{b}/time"] = ("ff", [5.0, 50.0])
            replies[f"/channel/{ch}/deq/{b}/filt"] = ("sff", ["OFF", 40.0, 1.0])
        replies[f"/channel/{ch}/delay"] = ("fi", [0.0, 0])
        replies[f"/channel/{ch}/limiter"] = ("fff", [69.9, 100.0, 50.0])
    return replies


class SnapshotTests(unittest.TestCase):
    def test_capture_produces_a_restorable_shape(self):
        transport = FakeTransport(_full_reply_map())
        client = INukeClient(transport=transport, min_send_interval_s=0)
        data = snapshot.capture(client)

        self.assertEqual(data["format"], "inuke-cli-snapshot")
        self.assertEqual(data["ampmode"], "STEREO")
        self.assertEqual(len(data["channels"]["1"]["peq"]), 8)
        self.assertEqual(data["channels"]["1"]["peq"][0]["type"], "PEQ")
        self.assertAlmostEqual(data["channels"]["2"]["limiter"]["threshold_vp"], 69.9, delta=0.01)

    def test_restore_sends_a_set_for_every_captured_field(self):
        transport = FakeTransport(_full_reply_map())
        client = INukeClient(transport=transport, min_send_interval_s=0)
        data = snapshot.capture(client)

        transport2 = FakeTransport({})
        client2 = INukeClient(transport=transport2, min_send_interval_s=0)
        progress = []
        snapshot.restore(client2, data, on_progress=lambda i, total, key: progress.append((i, total, key)))

        sent_addrs = {m["addr"] for m in transport2.sent}
        self.assertIn("/ampmode", sent_addrs)
        self.assertIn("/channel/1/peq/1", sent_addrs)
        self.assertIn("/channel/2/limiter", sent_addrs)
        self.assertIn("/channel/1/deq/2/filt", sent_addrs)
        self.assertEqual(progress[-1][0], progress[-1][1])

    def test_restore_rejects_a_file_with_the_wrong_format_marker(self):
        transport = FakeTransport({})
        client = INukeClient(transport=transport)
        with self.assertRaises(ValueError):
            snapshot.restore(client, {"format": "something-else"})


if __name__ == "__main__":
    unittest.main()
