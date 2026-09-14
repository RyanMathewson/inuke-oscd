import unittest
from pathlib import Path

from inuke_cli.protocol import INukeClient
from inuke_cli import snapshot, arp
from .fake_transport import FakeTransport
from .test_snapshot import _full_reply_map

FIXTURE = Path(__file__).resolve().parents[2] / "existing_settings.arp"


class ArpRoundTripTests(unittest.TestCase):
    def test_capture_format_parse_round_trips(self):
        transport = FakeTransport(_full_reply_map())
        client = INukeClient(transport=transport, min_send_interval_s=0)
        data = snapshot.capture(client)

        text = arp.format_arp(data)
        parsed = arp.parse_arp(text)

        self.assertEqual(parsed["ampmode"], data["ampmode"])
        self.assertEqual(parsed["channels"]["1"]["peq"][0], data["channels"]["1"]["peq"][0])
        self.assertAlmostEqual(parsed["channels"]["2"]["limiter"]["threshold_vp"], data["channels"]["2"]["limiter"]["threshold_vp"], delta=0.01)
        self.assertEqual(parsed["channels"]["1"]["delay"]["phase_deg"], data["channels"]["1"]["delay"]["phase_deg"])

    def test_format_writes_k_notation_for_large_frequencies(self):
        transport = FakeTransport(_full_reply_map())
        client = INukeClient(transport=transport, min_send_interval_s=0)
        data = snapshot.capture(client)
        data["channels"]["1"]["peq"][0]["freq"] = 4000.0

        text = arp.format_arp(data)
        self.assertIn("4k00", text)

    def test_restore_from_parsed_arp_sends_every_field(self):
        transport = FakeTransport(_full_reply_map())
        client = INukeClient(transport=transport, min_send_interval_s=0)
        data = snapshot.capture(client)
        parsed = arp.parse_arp(arp.format_arp(data))

        transport2 = FakeTransport({})
        client2 = INukeClient(transport=transport2, min_send_interval_s=0)
        snapshot.restore(client2, parsed)

        sent_addrs = {m["addr"] for m in transport2.sent}
        self.assertIn("/ampmode", sent_addrs)
        self.assertIn("/channel/1/peq/1", sent_addrs)
        self.assertIn("/channel/2/limiter", sent_addrs)


class ArpFixtureTests(unittest.TestCase):
    def setUp(self):
        self.data = arp.parse_arp(FIXTURE.read_text(encoding="ascii"))

    def test_ampmode(self):
        self.assertEqual(self.data["ampmode"], "BIAMP1")

    def test_peq_with_plain_decimals(self):
        p = self.data["channels"]["1"]["peq"][1]  # band 2
        self.assertEqual(p["type"], "PEQ")
        self.assertAlmostEqual(p["freq"], 33.9, delta=0.01)
        self.assertAlmostEqual(p["gain"], -10.0, delta=0.01)
        self.assertAlmostEqual(p["q"], 4.41, delta=0.01)

    def test_peq_with_k_notation_frequency(self):
        p7 = self.data["channels"]["1"]["peq"][6]  # band 7 -> 4k00
        p8 = self.data["channels"]["1"]["peq"][7]  # band 8 -> 10k00
        self.assertAlmostEqual(p7["freq"], 4000.0, delta=0.01)
        self.assertAlmostEqual(p8["freq"], 10000.0, delta=0.01)


class ArpNegativeTests(unittest.TestCase):
    def test_garbage_text_raises(self):
        with self.assertRaises(arp.ArpFormatError):
            arp.parse_arp("this is not a preset file")

    def test_missing_ampmode_raises(self):
        text = "\r\nBEGIN_OSC_DATA\r\n/channel/1/delay fi 0.0 0\r\nEND_OSC_DATA"
        with self.assertRaises(arp.ArpFormatError):
            arp.parse_arp(text)


if __name__ == "__main__":
    unittest.main()
