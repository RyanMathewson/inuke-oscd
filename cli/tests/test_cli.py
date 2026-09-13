import unittest
from unittest.mock import MagicMock, patch

from inuke_cli.cli import build_parser, run


class ValidationTests(unittest.TestCase):
    def test_peq_rejects_a_frequency_of_zero(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["peq", "1", "1", "PEQ", "0", "0", "1"])

    def test_peq_rejects_a_negative_frequency(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["peq", "1", "1", "PEQ", "-100", "0", "1"])

    def test_peq_rejects_gain_beyond_the_conservative_bound(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["peq", "1", "1", "PEQ", "1000", "100", "1"])

    def test_peq_rejects_zero_q(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["peq", "1", "1", "PEQ", "1000", "0", "0"])

    def test_peq_accepts_values_at_the_boundary(self):
        args = build_parser().parse_args(["peq", "1", "1", "PEQ", "20000", "24", "20"])
        self.assertEqual(args.freq, 20000)
        self.assertEqual(args.gain, 24)
        self.assertEqual(args.q, 20)

    def test_delay_rejects_a_negative_time(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["delay", "1", "-1", "0"])

    def test_amp_name_rejects_an_overly_long_name(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["name", "x" * 29])

    def test_amp_name_accepts_a_name_at_the_length_limit(self):
        args = build_parser().parse_args(["name", "x" * 28])
        self.assertEqual(args.value, "x" * 28)

    def test_deq_comp_rejects_a_positive_threshold(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["deq", "comp", "1", "1", "0", "5", "1"])  # threshold=5 > 0 max


class CliDispatchTests(unittest.TestCase):
    def _run(self, argv, client_mock):
        args = build_parser().parse_args(argv)
        with patch("inuke_cli.cli.INukeClient") as ClientClass:
            ClientClass.return_value.__enter__.return_value = client_mock
            return run(args)

    def test_peq_with_no_extra_args_reads(self):
        client = MagicMock()
        client.get_peq.return_value = {"type": "PEQ", "freq": 100.0, "gain": 0.0, "q": 1.0}
        self._run(["peq", "1", "3"], client)
        client.get_peq.assert_called_once_with(1, 3)
        client.set_peq.assert_not_called()

    def test_peq_with_all_four_extra_args_sets(self):
        client = MagicMock()
        self._run(["peq", "1", "3", "LS12", "4000", "-3.5", "0.7"], client)
        client.set_peq.assert_called_once_with(1, 3, "LS12", 4000.0, -3.5, 0.7)
        client.get_peq.assert_not_called()

    def test_peq_with_partial_args_raises_systemexit(self):
        client = MagicMock()
        with self.assertRaises(SystemExit):
            self._run(["peq", "1", "3", "LS12", "4000"], client)

    def test_mode_get_vs_set(self):
        client = MagicMock()
        client.get_amp_mode.return_value = "STEREO"
        self._run(["mode"], client)
        client.get_amp_mode.assert_called_once()

        client2 = MagicMock()
        self._run(["mode", "bridged"], client2)
        client2.set_amp_mode.assert_called_once_with("BRIDGED")

    def test_xover_hp_partial_args_raises(self):
        client = MagicMock()
        with self.assertRaises(SystemExit):
            self._run(["xover", "hp", "1", "BUT24"], client)

    def test_xover_type_rejects_unknown_family(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["xover", "hp", "1", "ZZZ99", "80"])

    def test_delay_set_passes_ms_and_phase(self):
        client = MagicMock()
        self._run(["delay", "2", "1.5", "180"], client)
        client.set_delay.assert_called_once_with(2, 1.5, 180)

    def test_limiter_get(self):
        client = MagicMock()
        client.get_limiter.return_value = {"threshold_vp": 69.9, "release_ms": 100.0, "hold_ms": 50.0}
        self._run(["limiter", "1"], client)
        client.get_limiter.assert_called_once_with(1)
        client.set_limiter.assert_not_called()

    def test_preset_store_prompts_and_aborts_without_yes(self):
        client = MagicMock()
        client.get_amp_mode.return_value = "STEREO"
        with patch("builtins.input", return_value="n"):
            code = self._run(["preset", "store", "5", "MyPreset"], client)
        self.assertEqual(code, 1)
        client.save_preset.assert_not_called()

    def test_preset_store_with_yes_skips_prompt(self):
        client = MagicMock()
        client.get_amp_mode.return_value = "STEREO"
        code = self._run(["preset", "store", "5", "MyPreset", "-y"], client)
        self.assertEqual(code, 0)
        client.save_preset.assert_called_once_with(5, 1, "MyPreset")  # STEREO -> enum 1


if __name__ == "__main__":
    unittest.main()
