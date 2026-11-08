import http.server
import json
import os
import threading
import unittest
from unittest.mock import patch

from inuke_cli import filtermath, room_eq
from inuke_cli.cli import build_parser, main
from inuke_cli.rew import (
    AMP_BANDS,
    Response,
    RewClient,
    RewError,
    RewUnavailable,
    amp_bands_to_rew,
    decode_floats,
    deviation,
    encode_floats,
    rew_filters_to_amp,
    shelf_midpoint_factor,
)


def pk(index, freq, gain, q):
    return {"index": index, "type": "PK", "enabled": True, "isAuto": True, "frequency": freq, "gaindB": gain, "q": q}


def none(index):
    return {"index": index, "type": "None", "enabled": True, "isAuto": True}


class CodecTests(unittest.TestCase):
    def test_decodes_the_example_from_rews_api_docs(self):
        self.assertEqual(decode_floats("PgAAAD6AAAA+wAAAPwAAAA=="), [0.125, 0.25, 0.375, 0.5])

    def test_encode_is_the_inverse(self):
        self.assertEqual(encode_floats([0.125, 0.25, 0.375, 0.5]), "PgAAAD6AAAA+wAAAPwAAAA==")

    def test_log_spaced_response(self):
        r = Response.from_api({"startFreq": 20.0, "ppo": 1, "magnitude": encode_floats([1.0, 2.0, 3.0])})
        self.assertEqual(r.freqs, [20.0, 40.0, 80.0])
        self.assertAlmostEqual(r.at(40.0), 2.0)
        self.assertAlmostEqual(r.at(20 * 2 ** 0.5), 1.5, places=5)
        self.assertIsNone(r.at(10.0))
        self.assertIsNone(r.at(100.0))

    def test_linear_response(self):
        r = Response.from_api({"startFreq": 0.0, "ppo": None, "freqStep": 10.0, "magnitude": encode_floats([0, 1, 2])})
        self.assertEqual(r.freqs, [0.0, 10.0, 20.0])


class DeviationTests(unittest.TestCase):
    def test_constant_offset(self):
        a = Response([10.0, 1000.0], [3.0, 3.0])
        b = Response([10.0, 1000.0], [0.0, 0.0])
        d = deviation(a, b, 20, 500)
        self.assertAlmostEqual(d.rms_db, 3.0)
        self.assertAlmostEqual(d.max_db, 3.0)

    def test_no_overlap_is_none(self):
        a = Response([10.0, 20.0], [0.0, 0.0])
        self.assertIsNone(deviation(a, a, 100, 200))


class FilterMappingTests(unittest.TestCase):
    def test_sorts_by_frequency_and_pads_with_off(self):
        m = rew_filters_to_amp([pk(1, 300, -3, 2), none(2), pk(3, 45, -6, 5)])
        self.assertEqual(len(m.bands), AMP_BANDS)
        self.assertEqual(m.bands[0], {"type": "PEQ", "freq": 45.0, "gain": -6.0, "q": 5.0})
        self.assertEqual(m.bands[1]["freq"], 300.0)
        self.assertTrue(all(b["type"] == "OFF" for b in m.bands[2:]))
        self.assertEqual(m.notes, [])

    def test_clamps_and_says_so(self):
        m = rew_filters_to_amp([pk(1, 97.2, -30, 13.47)])
        self.assertEqual(m.bands[0], {"type": "PEQ", "freq": 97.2, "gain": -24.0, "q": 10.0})
        self.assertEqual(len(m.notes), 2)
        self.assertIn("Q 13.47 clamped to 10.00", m.notes[1])

    def test_max_q_is_configurable(self):
        m = rew_filters_to_amp([pk(1, 100, -3, 6)], max_q=4)
        self.assertEqual(m.bands[0]["q"], 4.0)

    def test_ignores_disabled_filters(self):
        f = pk(1, 100, -3, 2)
        f["enabled"] = False
        self.assertEqual(rew_filters_to_amp([f]).bands[0]["type"], "OFF")

    def test_rejects_more_filters_than_bands(self):
        with self.assertRaises(RewError):
            rew_filters_to_amp([pk(i, 100 * i, -1, 1) for i in range(1, AMP_BANDS + 2)])

    def test_rejects_types_the_amp_lacks(self):
        with self.assertRaises(RewError):
            rew_filters_to_amp([{"index": 1, "type": "LP", "enabled": True, "frequency": 100.0}])

    def test_shelf_uses_fixed_q_and_midpoint_frequency(self):
        ls = {"index": 1, "type": "LS", "enabled": True, "frequency": 100.0, "gaindB": 6.0}
        hs = {"index": 2, "type": "HS 6dB", "enabled": True, "frequency": 2000.0, "gaindB": -9.0}
        bands = rew_filters_to_amp([ls, hs]).bands
        self.assertEqual(bands[0]["type"], "LS12")
        self.assertEqual(bands[0]["q"], 0.71)
        self.assertAlmostEqual(bands[0]["freq"], round(100 * 10 ** (6 / 80), 1))
        self.assertEqual(bands[1]["type"], "HS6")
        self.assertAlmostEqual(bands[1]["freq"], round(2000 / 10 ** (9 / 40), 1))

    def test_corner_convention_leaves_shelf_frequency_alone(self):
        ls = {"index": 1, "type": "LS", "enabled": True, "frequency": 100.0, "gaindB": 6.0}
        self.assertEqual(rew_filters_to_amp([ls], shelf_midpoint=False).bands[0]["freq"], 100.0)

    def test_midpoint_factor_is_one_for_peq(self):
        self.assertEqual(shelf_midpoint_factor("PEQ", 6.0), 1.0)

    def test_round_trip_through_rew_format(self):
        bands = [
            {"type": "LS12", "freq": 60.0, "gain": 4.0, "q": 0.71},
            {"type": "PEQ", "freq": 120.0, "gain": -5.0, "q": 3.0},
            {"type": "HS6", "freq": 6000.0, "gain": -2.0, "q": 0.71},
        ] + [dict(room_eq.OFF_BAND) for _ in range(5)]
        rew_list = amp_bands_to_rew(bands, 22)
        self.assertEqual(len(rew_list), 22)
        self.assertEqual(rew_list[0]["type"], "LS 12dB")
        self.assertNotIn("q", rew_list[0])
        self.assertEqual(rew_list[21]["type"], "None")
        self.assertFalse(any(f["isAuto"] for f in rew_list))
        self.assertEqual(rew_filters_to_amp(rew_list).bands, bands)


class FilterMathTests(unittest.TestCase):
    def test_peq_has_its_gain_at_the_centre(self):
        self.assertAlmostEqual(filtermath.band_db("PEQ", 100, -6, 4, 100), -6, places=3)
        self.assertAlmostEqual(filtermath.band_db("PEQ", 100, -6, 4, 1000), 0, places=1)

    def test_shelves_reach_their_gain_and_pass_half_at_the_midpoint(self):
        for t in ("LS12", "LS6"):
            self.assertAlmostEqual(filtermath.band_db(t, 200, 6, 0.707, 10), 6, places=1)
            self.assertAlmostEqual(filtermath.band_db(t, 200, 6, 0.707, 200), 3, places=1)
            self.assertAlmostEqual(filtermath.band_db(t, 200, 6, 0.707, 10000), 0, places=1)
        for t in ("HS12", "HS6"):
            self.assertAlmostEqual(filtermath.band_db(t, 2000, -6, 0.707, 20), 0, places=1)
            self.assertAlmostEqual(filtermath.band_db(t, 2000, -6, 0.707, 2000), -3, places=1)

    def test_off_is_flat(self):
        self.assertEqual(filtermath.band_db("OFF", 100, 6, 1, 100), 0.0)


class FitSettingsTests(unittest.TestCase):
    def test_nothing_set_means_nothing_sent(self):
        s = room_eq.FitSettings()
        self.assertEqual(s.target_settings(), {})
        self.assertEqual(s.match_settings(), {})

    def test_prompt_edits(self):
        s = room_eq.FitSettings()
        recalc = s.apply_text("range=20-300 boost=3 shelves=on q=6")
        self.assertFalse(recalc)
        self.assertEqual(
            s.match_settings(),
            {"startFrequency": 20, "endFrequency": 300, "individualMaxBoostdB": 3, "allowLowShelf": True, "allowHighShelf": True},
        )
        self.assertEqual(s.max_q, 6.0)
        self.assertTrue(s.apply_text("shape=subwoofer"))
        self.assertEqual(s.target_settings(), {"shape": "Subwoofer"})
        self.assertTrue(s.apply_text("bm=65 bm-slope=24"))
        self.assertEqual(s.target_settings(), {"shape": "Subwoofer", "bassManagementCutoffHz": 65, "bassManagementSlopedBPerOctave": 24})
        self.assertTrue(s.apply_text("level=auto"))
        s.apply_text("level=78.5")
        self.assertEqual(s.target_level_db, 78.5)

    def test_prompt_rejects_nonsense(self):
        s = room_eq.FitSettings()
        for bad in ("range=300-20", "shape=wobbly", "frobnicate=1", "boost", "shelves=maybe"):
            with self.assertRaises(ValueError, msg=bad):
                s.apply_text(bad)


class FlakyAmp(room_eq.SimulatedAmp):
    """Drops the first write to each band."""

    def __init__(self):
        super().__init__()
        self.seen = set()
        self.writes = 0

    def set_peq(self, ch, band, type_, freq, gain, q):
        self.writes += 1
        if (ch, band) not in self.seen:
            self.seen.add((ch, band))
            return
        super().set_peq(ch, band, type_, freq, gain, q)


class WriteBandsTests(unittest.TestCase):
    BANDS = [{"type": "PEQ", "freq": 100.0 + i, "gain": -3.0, "q": 2.0} for i in range(AMP_BANDS)]

    def test_retries_dropped_writes(self):
        amp = FlakyAmp()
        room_eq.write_bands(amp, 1, self.BANDS)
        self.assertEqual(room_eq.read_bands(amp, 1), self.BANDS)
        self.assertEqual(amp.writes, 2 * AMP_BANDS)

    def test_gives_up_on_an_amp_that_never_applies(self):
        amp = room_eq.SimulatedAmp()
        amp.set_peq = lambda *a: None
        with self.assertRaises(RewError):
            room_eq.write_bands(amp, 1, self.BANDS)

    def test_float32_rounding_counts_as_applied(self):
        amp = room_eq.SimulatedAmp()
        real_set = amp.set_peq
        amp.set_peq = lambda ch, b, t, f, g, q: real_set(ch, b, t, f + 0.003, g - 0.004, q + 0.0001)
        room_eq.write_bands(amp, 2, self.BANDS)


class FakeRew:
    """Just enough of RewClient for RoomEqSession, with canned responses."""

    FREQS = [20.0, 40.0, 80.0, 160.0]

    def __init__(self):
        self.store = {}
        self.calls = []
        self.level_calcs = 0
        self.levels_set = []
        self.next_id = 0
        self.filters_by = {}

    def _new(self, resp):
        self.next_id += 1
        uuid = f"u{self.next_id}"
        self.store[uuid] = resp
        return uuid

    def version(self):
        return "fake"

    def uuids(self):
        return set(self.store)

    def smooth(self, mid, smoothing="Var"):
        self.calls.append(("smooth", mid))

    def use_amp_equaliser(self, mid):
        return 22

    def set_filters(self, mid, filters):
        self.filters_by[mid] = filters

    def filters(self, mid):
        return [pk(1, 40.0, -3.0, 4.0)] + [none(i) for i in range(2, 23)]

    def frequency_response(self, mid, ppo=48, smoothing=None, equalised=False):
        r = self.store[mid]
        if equalised:  # pretend the EQ adds 1 dB everywhere
            return Response(r.freqs, [m + 1 for m in r.mags])
        return r

    def target_response(self, mid, ppo=48):
        return Response(self.FREQS, [80.0] * 4)

    def import_response(self, title, response, ppo):
        return self._new(response)

    def db_average(self, uuids):
        self.calls.append(("avg", tuple(uuids)))
        rs = [self.store[u] for u in uuids]
        return self._new(Response(rs[0].freqs, [sum(v) / len(v) for v in zip(*(r.mags for r in rs))]))

    def rename(self, mid, title):
        pass

    def update_target_settings(self, mid, settings):
        self.calls.append(("target", settings))

    def update_match_settings(self, settings):
        self.calls.append(("match", settings))

    def eq_command(self, mid, command):
        self.calls.append(("eq", command))
        if command == "Calculate target level":
            self.level_calcs += 1

    def target_level(self, mid):
        return 81.0

    def set_target_level(self, mid, level):
        self.levels_set.append(level)

    def match_settings(self):
        return {"startFrequency": 20, "endFrequency": 160, "individualMaxBoostdB": 6, "flatnessTargetdB": 1}

    def target_settings(self, mid):
        return {"shape": "Full range"}


class FakeMeasurer:
    def __init__(self, mags_seq):
        self.mags_seq = list(mags_seq)

    def measure(self, rew, title):
        return rew._new(Response(FakeRew.FREQS, self.mags_seq.pop(0)))


class SessionTests(unittest.TestCase):
    def _session(self, mags_seq, settings=None):
        rew = FakeRew()
        amp = room_eq.SimulatedAmp()
        s = room_eq.RoomEqSession(rew, amp, 1, FakeMeasurer(mags_seq), settings or room_eq.FitSettings(), out=lambda *_: None)
        return rew, amp, s

    def test_measure_removes_the_applied_eq(self):
        rew, _, s = self._session([[80.0, 82.0, 84.0, 86.0]])
        s.measure("baseline")
        est = rew.store[s.estimates[0]]
        # measured - (equalised - measured) with the fake EQ adding 1 dB
        self.assertEqual(est.mags, [79.0, 81.0, 83.0, 85.0])
        self.assertIn(("smooth", "u1"), rew.calls)
        self.assertEqual(len(rew.filters_by["u1"]), 22)

    def test_first_fit_uses_the_estimate_directly_later_fits_average(self):
        rew, _, s = self._session([[80.0] * 4, [82.0] * 4])
        s.measure("a")
        fit1 = s.fit()
        self.assertEqual(fit1.basis_uuid, s.estimates[0])
        self.assertEqual(fit1.mapped.bands[0]["freq"], 40.0)
        s.measure("b")
        fit2 = s.fit()
        self.assertIn(("avg", tuple(s.estimates)), rew.calls)
        self.assertEqual(fit2.basis_count, 2)
        # level is calculated once, then reused
        self.assertEqual(rew.level_calcs, 1)
        self.assertEqual(rew.levels_set, [81.0])

    def test_recalc_and_explicit_level(self):
        rew, _, s = self._session([[80.0] * 4], room_eq.FitSettings(target_level_db=75.0))
        s.measure("a")
        s.fit()
        self.assertEqual(rew.level_calcs, 0)
        self.assertEqual(rew.levels_set, [75.0])
        s.settings.target_level_db = None
        s.fit(recalc_level=True)
        self.assertEqual(rew.level_calcs, 1)

    def test_apply_restore_and_verify(self):
        rew, amp, s = self._session([[80.0] * 4, [80.5] * 4])
        original = room_eq.read_bands(amp, 1)
        s.measure("a")
        fit = s.fit()
        s.apply(fit.mapped.bands)
        self.assertEqual(room_eq.read_bands(amp, 1), fit.mapped.bands)
        v = s.verify(s.measure("b"), fit)
        self.assertAlmostEqual(v.vs_target.rms_db, 0.5, places=5)
        s.restore_original()
        self.assertEqual(room_eq.read_bands(amp, 1), original)
        self.assertEqual([e["kind"] for e in s.log.events], ["measure", "fit", "apply", "measure", "verify", "restore"])

    def test_interactive_loop_keep(self):
        rew, amp, s = self._session([[80.0] * 4, [80.0] * 4])
        answers = iter(["", "y", "", "k"])
        self.assertEqual(room_eq.run_loop(s, ask=lambda _: next(answers)), 0)
        self.assertEqual(room_eq.read_bands(amp, 1)[0]["type"], "PEQ")

    def test_interactive_loop_decline_then_undo(self):
        rew, amp, s = self._session([[80.0] * 4])
        answers = iter(["", "n", "x", "u"])
        self.assertEqual(room_eq.run_loop(s, ask=lambda _: next(answers)), 0)
        self.assertEqual(room_eq.read_bands(amp, 1)[0]["type"], "OFF")
        self.assertNotIn("apply", [e["kind"] for e in s.log.events])


class MirroredChannelTests(unittest.TestCase):
    """Two identical subwoofers fed one mono signal: the mic hears their sum, so
    there is nothing to attribute to one channel. One fit goes to both."""

    def _session(self, mags_seq, mirrors=(2,)):
        rew = FakeRew()
        amp = room_eq.SimulatedAmp()
        s = room_eq.RoomEqSession(
            rew, amp, 1, FakeMeasurer(mags_seq), room_eq.FitSettings(),
            out=lambda *_: None, mirror_channels=list(mirrors),
        )
        return rew, amp, s

    def test_apply_writes_the_same_bands_to_both(self):
        _, amp, s = self._session([[80.0] * 4])
        s.measure("a")
        fit = s.fit()
        s.apply(fit.mapped.bands)
        self.assertEqual(room_eq.read_bands(amp, 1), fit.mapped.bands)
        self.assertEqual(room_eq.read_bands(amp, 2), fit.mapped.bands)
        self.assertEqual(room_eq.read_bands(amp, 1), room_eq.read_bands(amp, 2))

    def test_restore_puts_each_channel_back_to_its_own_original(self):
        # Start the two channels mismatched, as the real amp was found.
        rew = FakeRew()
        amp = room_eq.SimulatedAmp()
        amp.set_peq(2, 1, "PEQ", 78.0, 13.0, 5.0)
        s = room_eq.RoomEqSession(
            rew, amp, 1, FakeMeasurer([[80.0] * 4]), room_eq.FitSettings(),
            out=lambda *_: None, mirror_channels=[2],
        )
        before1 = room_eq.read_bands(amp, 1)
        before2 = room_eq.read_bands(amp, 2)
        self.assertNotEqual(before1, before2)
        s.measure("a")
        s.apply(s.fit().mapped.bands)
        self.assertEqual(room_eq.read_bands(amp, 1), room_eq.read_bands(amp, 2))
        s.restore_original()
        self.assertEqual(room_eq.read_bands(amp, 1), before1)
        self.assertEqual(room_eq.read_bands(amp, 2), before2, "each channel must go back to its own EQ")

    def test_log_records_both_channels(self):
        _, _, s = self._session([[80.0] * 4])
        self.assertEqual(s.log.mirror_channels, [2])
        self.assertIn("2", s.log.original_mirror_bands)
        s.measure("a")
        s.apply(s.fit().mapped.bands)
        apply_event = [e for e in s.log.events if e["kind"] == "apply"][0]
        self.assertEqual(apply_event["channels"], [1, 2])

    def test_the_fit_itself_is_unchanged_by_mirroring(self):
        _, _, single = self._session([[80.0] * 4], mirrors=())
        single.measure("a")
        a = single.fit().mapped.bands
        _, _, both = self._session([[80.0] * 4], mirrors=(2,))
        both.measure("a")
        self.assertEqual(both.fit().mapped.bands, a, "mirroring must not alter the fit")

    def test_mirroring_the_fitted_channel_is_a_no_op(self):
        _, _, s = self._session([[80.0] * 4], mirrors=(1,))
        self.assertEqual(s.mirror_channels, [])
        self.assertEqual(s.all_channels, [1])

    def test_loop_undo_restores_both(self):
        rew = FakeRew()
        amp = room_eq.SimulatedAmp()
        amp.set_peq(2, 1, "PEQ", 78.0, 13.0, 5.0)
        s = room_eq.RoomEqSession(
            rew, amp, 1, FakeMeasurer([[80.0] * 4, [80.0] * 4]), room_eq.FitSettings(),
            out=lambda *_: None, mirror_channels=[2],
        )
        before2 = room_eq.read_bands(amp, 2)
        answers = iter(["", "y", "", "u"])
        self.assertEqual(room_eq.run_loop(s, ask=lambda _: next(answers)), 0)
        self.assertEqual(room_eq.read_bands(amp, 2), before2)


class ChannelSpecTests(unittest.TestCase):
    def test_parsing(self):
        from inuke_cli.rew_cli import _channel_spec

        self.assertEqual(_channel_spec("1"), (1, []))
        self.assertEqual(_channel_spec("2"), (2, []))
        self.assertEqual(_channel_spec("both"), (1, [2]))
        self.assertEqual(_channel_spec(" BOTH "), (1, [2]))

    def test_rejects_nonsense(self):
        import argparse as _argparse

        from inuke_cli.rew_cli import _channel_spec

        for bad in ("3", "0", "left", ""):
            with self.assertRaises(_argparse.ArgumentTypeError):
                _channel_spec(bad)


class ManualMeasurerTests(unittest.TestCase):
    def test_waits_for_a_new_measurement(self):
        class Rew:
            polls = 0

            def uuids(self):
                self.polls += 1
                return {"old"} if self.polls < 4 else {"old", "new"}

            def rename(self, mid, title):
                self.renamed = (mid, title)

        rew = Rew()
        m = room_eq.ManualMeasurer(out=lambda *_: None, poll_s=0)
        self.assertEqual(m.measure(rew, "t"), "new")
        self.assertEqual(rew.renamed, ("new", "t"))

    def test_times_out(self):
        class Rew:
            def uuids(self):
                return set()

        m = room_eq.ManualMeasurer(out=lambda *_: None, timeout_s=0.05, poll_s=0.01)
        with self.assertRaises(RewError):
            m.measure(Rew(), "t")


class DynamicEqTests(unittest.TestCase):
    def test_enabled_band_with_zero_gain_is_harmless(self):
        amp = room_eq.SimulatedAmp()
        amp.get_deq_filt = lambda ch, b: {"type": "BP" if b == 2 else "OFF", "freq": 2000.0, "q": 1.0}
        self.assertFalse(room_eq.dynamic_eq_active(amp, 1))
        amp.get_deq_comp = lambda ch, b: {"gain": 6.0, "threshold": -30.0, "ratio": 5.0}
        self.assertTrue(room_eq.dynamic_eq_active(amp, 1))


class RewCliTests(unittest.TestCase):
    def test_loop_needs_a_channel(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["rew", "loop"])

    def test_loop_options(self):
        a = build_parser().parse_args(
            ["rew", "loop", "--channel", "2", "--range", "20-300", "--no-shelves", "--shape", "subwoofer", "--shelf-freq", "corner"]
        )
        self.assertEqual(a.range, (20, 300))
        self.assertFalse(a.shelves)
        self.assertEqual(a.shape, "Subwoofer")
        self.assertEqual(a.measure, "auto")
        self.assertEqual(a.shelf_freq, "corner")

    def test_bad_range_is_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["rew", "fit", "1", "--range", "500-20"])

    def test_unreachable_rew_is_a_clean_error(self):
        with patch("sys.stderr"):
            self.assertEqual(main(["rew", "--url", "http://127.0.0.1:9", "status"]), 4)

    def test_fit_apply_needs_channel(self):
        args = build_parser().parse_args(["rew", "--url", "http://127.0.0.1:9", "fit", "1", "--apply"])
        with patch("inuke_cli.rew_cli.RewClient"), self.assertRaises(SystemExit):
            from inuke_cli import rew_cli

            rew_cli.run(args)


@unittest.skipUnless(os.environ.get("INUKE_REW_LIVE"), "set INUKE_REW_LIVE=1 with REW running (-api) to run")
class AcceptHeaderTests(unittest.TestCase):
    """REW's API is served by Spark, which routes on the Accept header: a request
    without "application/json" gets a 404 even for a path that exists. --simulate
    never exercises the transport, so only a real server catches a missing header."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's name
            if "application/json" not in (self.headers.get("Accept") or ""):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"<html><body><h2>404 Not found</h2></body></html>")
                return
            body = json.dumps({"message": "5.40 Beta 135 API 0.9.8"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    def setUp(self):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), self.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_version_sends_accept_json(self):
        rew = RewClient(f"http://127.0.0.1:{self.server.server_address[1]}", timeout_s=10)
        self.assertEqual(rew.version(), "5.40 Beta 135 API 0.9.8")


class LiveRewTests(unittest.TestCase):
    """End-to-end against a real REW, with a simulated room and amp.
    Adds measurements to REW."""

    def test_simulated_loop(self):
        rew = RewClient()
        try:
            rew.version()
        except RewUnavailable as err:
            self.skipTest(str(err))
        rew.enable_blocking()
        amp = room_eq.SimulatedAmp()
        settings = room_eq.FitSettings(shape="Full range", lf_cutoff_hz=30, lo_hz=20, hi_hz=500, flatness_db=1)
        s = room_eq.RoomEqSession(rew, amp, 1, room_eq.SimulatedRoom(amp, 1), settings, out=lambda *_: None)
        s.measure("live test baseline")
        fit = s.fit()
        self.assertLess(fit.predicted.rms_db, fit.before.rms_db)
        s.apply(fit.mapped.bands)
        v = s.verify(s.measure("live test verify"), fit)
        self.assertLess(v.vs_prediction.rms_db, 1.5)
        self.assertLess(v.vs_target.rms_db, fit.before.rms_db)


if __name__ == "__main__":
    unittest.main()
