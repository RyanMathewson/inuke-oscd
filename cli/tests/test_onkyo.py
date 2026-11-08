import unittest

from inuke_cli import onkyo
from inuke_cli.onkyo import (
    LevelHold,
    Onkyo,
    OnkyoError,
    Preconditions,
    code_for,
    mode_name,
    source_name,
)


class FakeSerial:
    """A TX-SR806 as observed on the wire: replies end in 0x1A alone, sets echo.

    ``extra`` frames are delivered before the answer to a query, standing in for
    the unsolicited status the receiver sends when the front panel is touched.
    """

    def __init__(self, state=None, extra=(), answer=True):
        self.state = {"PWR": "01", "MVL": "2A", "SLI": "10", "LMD": "00", "AMT": "00"}
        self.state.update(state or {})
        self.extra = list(extra)
        self.answer = answer
        self.sent = []
        self._out = bytearray()
        self.closed = False

    # -- the bits of pyserial's API that Onkyo uses --
    def write(self, data):
        text = data.decode("ascii").strip("\r")
        assert text.startswith("!1"), text
        body = text[2:]
        self.sent.append(body)
        name, value = body[:3], body[3:]
        if not self.answer:
            return len(data)
        for frame in self.extra:
            self._out += f"!1{frame}".encode() + b"\x1a"
        self.extra = []
        if value == "QSTN":
            current = self.state.get(name)
            self._out += f"!1{name}{current if current is not None else 'N/A'}".encode() + b"\x1a"
        else:
            self.state[name] = value
            self._out += f"!1{name}{value}".encode() + b"\x1a"
        return len(data)

    def read_until(self, terminator):
        index = self._out.find(terminator)
        if index < 0:
            out, self._out = bytes(self._out), bytearray()
            return out  # no terminator -> Onkyo treats it as a timeout
        out = bytes(self._out[: index + len(terminator)])
        del self._out[: index + len(terminator)]
        return out

    def reset_input_buffer(self):
        self._out = bytearray()

    def close(self):
        self.closed = True


def connect(**kwargs):
    amp = Onkyo("COM-TEST", timeout_s=0.5)
    amp._serial = FakeSerial(**kwargs)
    return amp


class VolumeScalingTests(unittest.TestCase):
    """Raw MVL is hex on the wire, one unit per dB, with raw 82 = 0 dB."""

    def test_known_points(self):
        amp = connect()
        self.assertEqual(amp.raw_to_db(82), 0.0)
        self.assertEqual(amp.raw_to_db(42), -40.0)
        self.assertEqual(amp.db_to_raw(-40), 42)
        self.assertEqual(amp.db_to_raw(0), 82)

    def test_reads_hex_not_decimal(self):
        # 0x2A is 42, not 2A-as-decimal and not 0x2a misread as 2.
        self.assertEqual(connect().volume_raw(), 42)
        self.assertEqual(connect().volume_db(), -40.0)

    def test_sets_as_hex(self):
        amp = connect()
        amp.set_volume_db(-32)
        self.assertIn("MVL32", amp._serial.sent)  # raw 50 == 0x32

    def test_zero_db_raw_is_configurable(self):
        amp = Onkyo("COM-TEST", zero_db_raw=80)
        amp._serial = FakeSerial()
        self.assertEqual(amp.raw_to_db(42), -38.0)


class LevelCapTests(unittest.TestCase):
    """A measurement sweep never needs a loud level, and a typo should not make one."""

    def test_refuses_above_cap(self):
        amp = connect()
        with self.assertRaises(OnkyoError) as caught:
            amp.set_volume_raw(90)
        self.assertIn("cap", str(caught.exception))
        self.assertEqual(amp._serial.state["MVL"], "2A", "volume must be untouched")

    def test_force_overrides(self):
        amp = connect()
        amp.set_volume_raw(90, allow_above_max=True)
        self.assertEqual(amp._serial.state["MVL"], "5A")

    def test_cap_is_configurable(self):
        amp = Onkyo("COM-TEST", max_raw=50)
        amp._serial = FakeSerial()
        amp.set_volume_raw(50)
        with self.assertRaises(OnkyoError):
            amp.set_volume_raw(51)

    def test_rejects_out_of_range(self):
        with self.assertRaises(OnkyoError):
            connect().set_volume_raw(-1)


class ProtocolTests(unittest.TestCase):
    def test_frames_use_cr_out_and_0x1a_back(self):
        amp = connect()
        amp.send("PWRQSTN")
        self.assertEqual(amp._serial.sent[-1], "PWRQSTN")

    def test_skips_unsolicited_frames_before_the_answer(self):
        # The receiver volunteers a volume change; a query for the mode must not
        # return the volume frame by mistake.
        amp = connect(extra=["MVL30"])
        self.assertEqual(amp.mode(), "00")

    def test_na_means_unavailable_not_a_value(self):
        amp = connect(state={"MVL": None})
        self.assertIsNone(amp.volume_raw())

    def test_silence_returns_none(self):
        amp = connect(answer=False)
        self.assertIsNone(amp.power())

    def test_set_that_does_not_stick_is_an_error(self):
        amp = connect()

        def wrong(data):
            amp._serial.sent.append(data.decode().strip("\r")[2:])
            amp._serial._out += b"!1MVL2A\x1a"  # echoes the old value
            return len(data)

        amp._serial.write = wrong
        with self.assertRaises(OnkyoError) as caught:
            amp.set_volume_raw(50)
        self.assertIn("did not take", str(caught.exception))

    def test_unavailable_when_receiver_never_answers(self):
        from inuke_cli.onkyo import OnkyoUnavailable

        with self.assertRaises(OnkyoUnavailable):
            connect(answer=False).state()


class StateTests(unittest.TestCase):
    def test_reports_everything_in_one_pass(self):
        state = connect().state()
        self.assertEqual(state["power"], True)
        self.assertEqual(state["volume_raw"], 42)
        self.assertEqual(state["volume_db"], -40.0)
        self.assertEqual(state["muted"], False)
        self.assertEqual(state["source"], "10")
        self.assertEqual(state["mode"], "00")

    def test_standby_does_not_invent_a_volume(self):
        state = connect(state={"PWR": "00", "MVL": None}).state()
        self.assertEqual(state["power"], False)
        self.assertIsNone(state["volume_raw"])

    def test_names(self):
        self.assertEqual(source_name("10"), "DVD")
        self.assertEqual(mode_name("01"), "Direct")
        self.assertEqual(mode_name("00"), "Stereo")
        self.assertEqual(mode_name("7F"), "code 7F")
        self.assertEqual(mode_name(None), "unknown")


class CodeLookupTests(unittest.TestCase):
    def test_by_name_case_insensitive(self):
        self.assertEqual(code_for("direct", onkyo.MODES), "01")
        self.assertEqual(code_for("All Ch Stereo", onkyo.MODES), "0C")

    def test_by_raw_code(self):
        self.assertEqual(code_for("0c", onkyo.MODES), "0C")

    def test_rejects_nonsense(self):
        with self.assertRaises(OnkyoError):
            code_for("Audyssey Off", onkyo.MODES)


class GuardTests(unittest.TestCase):
    """The point of the guard: never measure through room correction or an upmix."""

    def test_passes_in_direct(self):
        amp = connect(state={"LMD": "01"})
        amp.check(expect_source="10", expect_mode="01")

    def test_rejects_stereo_when_direct_expected(self):
        amp = connect(state={"LMD": "00"})
        with self.assertRaises(Preconditions) as caught:
            amp.check(expect_mode="01")
        self.assertIn("Stereo", str(caught.exception))
        self.assertIn("Direct", str(caught.exception))

    def test_rejects_wrong_input(self):
        amp = connect(state={"LMD": "01", "SLI": "23"})
        with self.assertRaises(Preconditions) as caught:
            amp.check(expect_source="10")
        self.assertIn("CD", str(caught.exception))

    def test_rejects_mute_and_standby(self):
        with self.assertRaises(Preconditions) as caught:
            connect(state={"LMD": "01", "AMT": "01"}).check()
        self.assertIn("muted", str(caught.exception))
        with self.assertRaises(Preconditions) as caught:
            connect(state={"PWR": "00"}).check(expect_mode=None)
        self.assertIn("standby", str(caught.exception))

    def test_reports_every_problem_at_once(self):
        amp = connect(state={"LMD": "0C", "SLI": "23", "AMT": "01"})
        with self.assertRaises(Preconditions) as caught:
            amp.check(expect_source="10", expect_mode="01")
        self.assertEqual(len(caught.exception.problems), 3)

    def test_mode_check_can_be_skipped(self):
        connect(state={"LMD": "0C"}).check(expect_mode=None)

    def test_volume_can_be_required(self):
        with self.assertRaises(Preconditions):
            connect(state={"LMD": "01"}).check(expect_mode="01", expect_volume_raw=50)


class LevelHoldTests(unittest.TestCase):
    def test_sets_then_restores(self):
        amp = connect()
        with LevelHold(amp, 50):
            self.assertEqual(amp._serial.state["MVL"], "32")
        self.assertEqual(amp._serial.state["MVL"], "2A", "listening level must come back")

    def test_restores_after_an_exception(self):
        amp = connect()
        with self.assertRaises(RuntimeError):
            with LevelHold(amp, 50):
                raise RuntimeError("sweep interrupted")
        self.assertEqual(amp._serial.state["MVL"], "2A")

    def test_refuses_a_level_above_the_cap(self):
        amp = connect()
        with self.assertRaises(OnkyoError):
            with LevelHold(amp, 90):
                pass
        self.assertEqual(amp._serial.state["MVL"], "2A")


class FakeInner:
    """Stands in for a real measurer: records the receiver level at sweep time."""

    def __init__(self, amp):
        self.amp = amp
        self.level_during_sweep = None
        self.calls = 0

    def measure(self, rew, title):
        self.calls += 1
        self.level_during_sweep = self.amp.volume_raw()
        return f"uuid-{self.calls}"


class ReceiverGuardedTests(unittest.TestCase):
    """The wrapper must block a bad measurement and hold the level for the sweep."""

    def guarded(self, state=None, **kwargs):
        from inuke_cli.room_eq import ReceiverGuarded

        amp = connect(state=state)
        inner = FakeInner(amp)
        kwargs.setdefault("out", lambda *_: None)
        return ReceiverGuarded(inner, amp, **kwargs), inner, amp

    def test_sweeps_when_preconditions_hold(self):
        guard, inner, _ = self.guarded(state={"LMD": "01"}, expect_mode="01", expect_source="10")
        self.assertEqual(guard.measure(None, "t"), "uuid-1")
        self.assertEqual(inner.calls, 1)

    def test_does_not_sweep_in_the_wrong_mode(self):
        guard, inner, _ = self.guarded(state={"LMD": "0C"}, expect_mode="01")
        with self.assertRaises(Preconditions):
            guard.measure(None, "t")
        self.assertEqual(inner.calls, 0, "a bad measurement must never be taken")

    def test_does_not_sweep_when_muted(self):
        guard, inner, _ = self.guarded(state={"LMD": "01", "AMT": "01"}, expect_mode="01")
        with self.assertRaises(Preconditions):
            guard.measure(None, "t")
        self.assertEqual(inner.calls, 0)

    def test_holds_the_level_during_the_sweep_then_restores(self):
        guard, inner, amp = self.guarded(state={"LMD": "01"}, expect_mode="01", level_raw=50)
        guard.measure(None, "t")
        self.assertEqual(inner.level_during_sweep, 50, "sweep must run at the measurement level")
        self.assertEqual(amp.volume_raw(), 42, "listening level must be restored")

    def test_level_is_restored_even_if_the_sweep_fails(self):
        guard, inner, amp = self.guarded(state={"LMD": "01"}, expect_mode="01", level_raw=50)

        def boom(rew, title):
            raise RuntimeError("sweep failed")

        inner.measure = boom
        with self.assertRaises(RuntimeError):
            guard.measure(None, "t")
        self.assertEqual(amp.volume_raw(), 42)

    def test_without_a_level_the_volume_is_left_alone(self):
        guard, inner, amp = self.guarded(state={"LMD": "01"}, expect_mode="01")
        guard.measure(None, "t")
        self.assertEqual(inner.level_during_sweep, 42)
        self.assertEqual(amp.volume_raw(), 42)

    def test_level_above_the_cap_is_refused_before_sweeping(self):
        guard, inner, amp = self.guarded(state={"LMD": "01"}, expect_mode="01", level_raw=90)
        with self.assertRaises(OnkyoError):
            guard.measure(None, "t")
        self.assertEqual(inner.calls, 0)
        self.assertEqual(amp.volume_raw(), 42)


class MissingDependencyTests(unittest.TestCase):
    def test_message_names_the_package(self):
        import builtins
        from unittest.mock import patch

        from inuke_cli.onkyo import OnkyoUnavailable

        real_import = builtins.__import__

        def no_serial(name, *args, **kwargs):
            if name == "serial":
                raise ImportError("no module named serial")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", no_serial):
            with self.assertRaises(OnkyoUnavailable) as caught:
                Onkyo("COM-TEST").open()
        self.assertIn("pyserial", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
