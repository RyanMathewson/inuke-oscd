import unittest

from inuke_cli.protocol import DeviceTimeoutError, INukeClient, osc_decode, osc_encode
from .fake_transport import FakeTransport


class OscCodecTests(unittest.TestCase):
    # Byte sequences transcribed from docs/PROTOCOL_NOTES.md's "Confirmed
    # example packets" (live USBPcap captures).

    def test_ampmode_stereo_matches_captured_bytes(self):
        msg = osc_encode("/ampmode", "s", ["STEREO"])
        expected = bytes(
            [
                0x2F, 0x61, 0x6D, 0x70, 0x6D, 0x6F, 0x64, 0x65, 0x00, 0x00, 0x00, 0x00,
                0x2C, 0x73, 0x00, 0x00,
                0x53, 0x54, 0x45, 0x52, 0x45, 0x4F, 0x00, 0x00,
            ]
        )
        self.assertEqual(msg, expected)

    def test_meter_heartbeat_matches_captured_bytes(self):
        msg = osc_encode("/meter", "f", [10.0])
        expected = bytes([0x2F, 0x6D, 0x65, 0x74, 0x65, 0x72, 0x00, 0x00, 0x2C, 0x66, 0x00, 0x00, 0x41, 0x20, 0x00, 0x00])
        self.assertEqual(msg, expected)

    def test_limiter_round_trips_captured_field_order(self):
        msg = osc_encode("/channel/1/limiter", "fff", [69.9, 100.0, 50.0])
        self.assertEqual(len(msg), 40)
        decoded = osc_decode(msg)
        self.assertEqual(decoded["addr"], "/channel/1/limiter")
        self.assertEqual(decoded["typetags"], "fff")
        self.assertAlmostEqual(decoded["args"][0], 69.9, delta=0.01)
        self.assertAlmostEqual(decoded["args"][1], 100.0, delta=0.01)
        self.assertAlmostEqual(decoded["args"][2], 50.0, delta=0.01)

    def test_peq_band_round_trip(self):
        msg = osc_encode("/channel/2/peq/3", "sfff", ["LS12", 4000.0, -3.5, 0.5])
        decoded = osc_decode(msg)
        self.assertEqual(decoded, {"addr": "/channel/2/peq/3", "typetags": "sfff", "args": ["LS12", 4000.0, -3.5, 0.5]})

    def test_bare_get_has_empty_typetags_and_no_args(self):
        msg = osc_encode("/ampmode", "", [])
        decoded = osc_decode(msg)
        self.assertEqual(decoded["addr"], "/ampmode")
        self.assertEqual(decoded["typetags"], "")
        self.assertEqual(decoded["args"], [])

    def test_delay_int_arg_is_phase_not_a_unit_selector(self):
        msg = osc_encode("/channel/1/delay", "fi", [0.0, 180])
        decoded = osc_decode(msg)
        self.assertEqual(decoded["args"], [0.0, 180])

    def test_decode_rejects_non_osc_buffer(self):
        self.assertIsNone(osc_decode(bytes([0x41, 0x42, 0x43, 0x00])))

    def test_address_padding_always_nul_terminates_to_a_multiple_of_4(self):
        msg = osc_encode("/xyz", "", [])
        self.assertEqual(len(msg), 12)  # 4 ("/xyz") + 4 (pad) + 4 (",\0\0\0")
        self.assertEqual(msg[:8], bytes([0x2F, 0x78, 0x79, 0x7A, 0x00, 0x00, 0x00, 0x00]))


class INukeClientTests(unittest.TestCase):
    def test_get_resolves_with_decoded_reply(self):
        transport = FakeTransport({"/ampmode": ("s", ["STEREO"])})
        client = INukeClient(transport=transport)
        self.assertEqual(client.get_amp_mode(), "STEREO")

    def test_get_times_out_when_nothing_replies(self):
        transport = FakeTransport({})
        client = INukeClient(transport=transport)
        with self.assertRaises(DeviceTimeoutError):
            client.get("/nope", timeout_s=0.05)

    def test_typed_get_peq_decodes_named_fields(self):
        transport = FakeTransport({"/channel/1/peq/3": ("sfff", ["LS12", 4000.0, -3.5, 0.5])})
        client = INukeClient(transport=transport)
        self.assertEqual(client.get_peq(1, 3), {"type": "LS12", "freq": 4000.0, "gain": -3.5, "q": 0.5})

    def test_set_peq_sends_without_waiting_for_a_reply(self):
        transport = FakeTransport({})
        client = INukeClient(transport=transport)
        client.set_peq(2, 1, "PEQ", 1000.0, 2.0, 1.0)
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(
            transport.sent[0], {"addr": "/channel/2/peq/1", "typetags": "sfff", "args": ["PEQ", 1000.0, 2.0, 1.0]}
        )

    def test_full_sync_reports_progress_and_tolerates_missing_replies(self):
        transport = FakeTransport({"/info": ("ssi", ["MyAmp", "(V1.3)", 5]), "/ampmode": ("s", ["STEREO"])})
        # keep unanswered GETs fast for this test
        client = INukeClient(transport=transport, default_timeout_s=0.02)
        progress = []
        results = client.full_sync(on_progress=lambda i, total, key: progress.append((i, total, key)))

        self.assertEqual(results["info"], {"amp_name": "MyAmp", "firmware": "(V1.3)", "unknown": 5})
        self.assertEqual(results["ampmode"], "STEREO")
        self.assertIn("error", results["gain"])  # no reply configured -> timed out, captured not raised
        self.assertEqual(progress[-1][0], progress[-1][1])  # last progress call reports done == total


if __name__ == "__main__":
    unittest.main()
