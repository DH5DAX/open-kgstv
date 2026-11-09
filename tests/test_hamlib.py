"""Protocol, lifecycle and PTT tests. TCP peers and audio are simulated.

KGSTV_RIGCTLD enables extra tests against the real executable's Dummy backend.
No test opens a physical radio, soundcard or serial port.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import socketserver
import threading
import time
import unittest
from unittest.mock import Mock, patch, call
import numpy as np

from kgstv.hamlib import (HamlibError, PTTReleaseError, RadioConfig, RadioSession,
                          RigctldClient, LocalDaemon, list_models)
from kgstv.live import play_audio


class FakeRig:
    def __init__(self, *, vfo=False, legacy=False):
        self.vfo, self.legacy = vfo, legacy
        self.frequency, self.mode, self.width, self.ptt = 14230000, "USB", 2400, 0
        self.commands = []
        self.hooks = {}
        self.fragment = False

    @staticmethod
    def response(command, fields="", code=0):
        return f"{command}:\n{fields}RPRT {code}\n"

    def answer(self, request):
        self.commands.append(request)
        if request == "\\chk_vfo":
            return ("CHKVFO " if self.legacy else "")+str(int(self.vfo))+"\n"
        tokens = request.split()
        name = tokens.pop(0)[2:]
        if self.vfo:
            if not tokens or tokens.pop(0) != "currVFO":
                return self.response(name, code=-16)
        if name in self.hooks:
            return self.hooks[name](tokens)
        if name == "get_freq":
            return self.response(name, f"Frequency: {self.frequency}\n")
        if name == "set_freq":
            self.frequency = float(tokens[0])
        elif name == "get_mode":
            return self.response(name, f"Mode: {self.mode}\nPassband: {self.width}\n")
        elif name == "set_mode":
            self.mode, self.width = tokens[0], int(tokens[1])
        elif name == "get_ptt":
            return self.response(name, f"PTT: {self.ptt}\n")
        elif name == "set_ptt":
            self.ptt = int(tokens[0])
        return self.response(name)


@contextmanager
def fake_server(rig=None):
    rig = rig or FakeRig()
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(2)
            try:
                for data in self.rfile:
                    response = rig.answer(data.decode("ascii").strip())
                    if response is None:
                        return
                    encoded = response.encode("ascii")
                    if rig.fragment:
                        for offset in range(0, len(encoded), 3):
                            self.connection.sendall(encoded[offset:offset+3])
                    else:
                        self.connection.sendall(encoded)
            except (OSError, ValueError):
                pass
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True
    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda:server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield rig, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


class ProtocolTests(unittest.TestCase):
    def test_fragmented_responses_and_both_vfo_handshakes(self):
        for vfo in (False, True):
            for legacy in (False, True):
                with self.subTest(vfo=vfo, legacy=legacy), fake_server(FakeRig(vfo=vfo, legacy=legacy)) as (rig, port):
                    rig.fragment = True
                    client = RigctldClient(port=port)
                    try:
                        client.connect()
                        client.set_frequency(7074000)
                        client.set_mode("PKTUSB", 2800)
                        client.set_ptt(1)
                        state = client.snapshot()
                        self.assertEqual((state.frequency, state.mode, state.passband, state.ptt),
                                         (7074000, "PKTUSB", 2800, 1))
                        client.set_ptt(0)
                        self.assertEqual(client.get_ptt(), 0)
                    finally:
                        client.close()

    def test_connect_and_read_never_change_radio(self):
        with fake_server() as (rig, port):
            client = RigctldClient(port=port)
            try:
                client.connect()
                client.snapshot()
            finally:
                client.close()
            self.assertFalse(any("set_" in command for command in rig.commands))

    def test_unsupported_optional_readbacks_do_not_fake_values(self):
        with fake_server() as (rig, port):
            rig.hooks["get_mode"] = lambda _:rig.response("get_mode", code=-4)
            rig.hooks["get_ptt"] = lambda _:rig.response("get_ptt", code=-11)
            client = RigctldClient(port=port)
            try:
                client.connect()
                state = client.snapshot()
                self.assertEqual(state.frequency, 14230000)
                self.assertIsNone(state.mode)
                self.assertIsNone(state.ptt)
            finally:
                client.close()

    def test_negative_ack_is_visible_and_socket_stays_synchronized(self):
        with fake_server() as (rig, port):
            rig.hooks["set_mode"] = lambda _:rig.response("set_mode", code=-9)
            client = RigctldClient(port=port)
            try:
                client.connect()
                with self.assertRaises(HamlibError) as error:
                    client.set_mode("PKTUSB")
                self.assertEqual(error.exception.code, -9)
                self.assertEqual(client.snapshot().mode, "USB")
            finally:
                client.close()

    def test_bad_reply_disconnects_and_does_not_retry_commands(self):
        for reply in (None, "get_mode:\nRPRT 0\n", "get_freq:\n"+"x"*70000,
                      "get_freq:\nFrequency: 10\nRPRT bad\n"):
            with self.subTest(reply=str(reply)[:30]), fake_server() as (rig, port):
                rig.hooks["get_freq"] = lambda _, reply=reply:reply
                client = RigctldClient(port=port, timeout=.1)
                client.connect()
                with self.assertRaises(HamlibError):
                    client.snapshot()
                self.assertIsNone(client.socket)
                self.assertEqual(sum("get_freq" in command for command in rig.commands), 1)

    def test_timeout_discards_late_reply(self):
        with fake_server() as (rig, port):
            def slow(_):
                time.sleep(.2)
                return rig.response("get_freq", "Frequency: 1\n")
            rig.hooks["get_freq"] = slow
            client = RigctldClient(port=port, timeout=.04)
            client.connect()
            with self.assertRaises(HamlibError):
                client.snapshot()
            self.assertIsNone(client.socket)

    def test_concurrent_poll_and_control_are_serialized(self):
        with fake_server() as (_, port):
            client = RigctldClient(port=port)
            client.connect()
            try:
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(client.snapshot) for _ in range(20)]
                    for future in futures:
                        self.assertEqual(future.result().frequency, 14230000)
            finally:
                client.close()

    def test_invalid_parameters_never_reach_socket(self):
        client = RigctldClient()
        for frequency in (float("nan"), float("inf"), -1, 0):
            with self.assertRaises(ValueError):
                client.set_frequency(frequency)
        with self.assertRaises(ValueError):
            client.set_mode("USB\nT1")
        with self.assertRaises(ValueError):
            client.command("set_ptt", "1\nT")
        with self.assertRaises(ValueError):
            RadioConfig(device="").validate()
        RadioConfig(connection="network").validate()


class RadioSessionTests(unittest.TestCase):
    def connect(self, port, events=None):
        session = RadioSession(lambda event,data:(events.append((event,data)) if events is not None else None),
                               timeout=.15, poll_interval=.03)
        session.connect(RadioConfig(connection="network", port=port))
        return session

    def test_lost_ptt_on_ack_recovers_with_off_only(self):
        with fake_server() as (rig, port):
            def lost_ack(args):
                rig.ptt = int(args[0])
                return None if rig.ptt else rig.response("set_ptt")
            rig.hooks["set_ptt"] = lost_ack
            session = self.connect(port)
            try:
                with self.assertRaises(HamlibError):
                    session.ptt(True)
                self.assertTrue(session.ptt_may_be_on)
                session.ptt(False)
                self.assertEqual(rig.ptt, 0)
                self.assertFalse(session.ptt_may_be_on)
                self.assertEqual([s for s in rig.commands if "set_ptt" in s],
                                 ["+\\set_ptt 1", "+\\set_ptt 0"])
            finally:
                session.close()

    def test_failed_release_remains_explicit(self):
        with fake_server() as (rig, port):
            session = self.connect(port)
            session.ptt(True)
            rig.hooks["set_ptt"] = lambda _:None
            with self.assertRaises(PTTReleaseError):
                session.ptt(False)
            self.assertTrue(session.ptt_may_be_on)
            self.assertEqual(rig.ptt, 1)
            del rig.hooks["set_ptt"]
            session.close()
            self.assertEqual(rig.ptt, 0)

    def test_radio_already_transmitting_is_not_taken_over(self):
        with fake_server() as (rig, port):
            rig.ptt = 1
            session = self.connect(port)
            with self.assertRaises(HamlibError):
                session.ptt(True)
            session.ptt(False)
            session.close()
            self.assertEqual(rig.ptt, 1)
            self.assertFalse(any("set_ptt" in command for command in rig.commands))

    def test_close_keeps_owned_daemon_available_after_failed_ptt_release(self):
        with fake_server() as (rig, port):
            session = self.connect(port)
            daemon = session.daemon = Mock()
            session.ptt(True)
            rig.hooks["set_ptt"] = lambda _:None
            with self.assertRaises(PTTReleaseError):
                session.close()
            daemon.close.assert_not_called()
            self.assertTrue(session.ptt_may_be_on)
            del rig.hooks["set_ptt"]
            session.close()
            self.assertEqual(rig.ptt, 0)
            daemon.close.assert_called_once()

    def test_close_releases_owned_ptt_but_keeps_external_server(self):
        with fake_server() as (rig, port):
            session = self.connect(port)
            session.ptt(True)
            with self.assertRaises(HamlibError):
                session.set_frequency(7074000)
            session.close()
            self.assertEqual(rig.ptt, 0)
            other = RigctldClient(port=port)
            other.connect()
            other.snapshot()
            other.close()

    def test_link_loss_stops_monitor_without_reconnect(self):
        with fake_server() as (rig, port):
            events = []
            session = self.connect(port, events)
            rig.hooks["get_freq"] = lambda _:None
            session.thread.join(timeout=2)
            self.assertFalse(session.thread.is_alive())
            self.assertFalse(session.connected)
            self.assertTrue(any(event == "radio_lost" for event, _ in events))
            self.assertEqual(rig.commands.count("\\chk_vfo"), 1)
            session.close()

    def test_local_process_uses_argument_list_and_loopback(self):
        with patch("kgstv.hamlib.executable_path", return_value="/test/rigctld"), \
             patch("kgstv.hamlib.subprocess.Popen") as launch:
            daemon = LocalDaemon(RadioConfig(device="COM3", civ="98"))
            try:
                args = launch.call_args.args[0]
                self.assertIsInstance(args, list)
                self.assertEqual(args[args.index("-m")+1], "3078")
                self.assertEqual(args[args.index("-c")+1], "152")
                self.assertEqual(args[args.index("-T")+1], "127.0.0.1")
                self.assertNotIn("shell", launch.call_args.kwargs)
            finally:
                daemon.close()


class HamlibAudioTests(unittest.TestCase):
    def test_ptt_wraps_audio_and_is_released_after_cleanup_failure(self):
        for broken in (False, True):
            order = []
            audio = Mock()
            audio.get_stream.return_value.active = False
            audio.play.side_effect = lambda *a,**k:order.append("play")
            audio.wait.side_effect = lambda:order.append("wait")
            audio.stop.side_effect = RuntimeError("stop failed") if broken else lambda:order.append("stop")
            ptt = lambda active:order.append("on" if active else "off")
            with patch.dict("sys.modules", {"sounddevice":audio}):
                if broken:
                    with self.assertRaises(RuntimeError):
                        play_audio(np.zeros(20), ptt=ptt)
                else:
                    play_audio(np.zeros(20), ptt=ptt)
            self.assertEqual(order[0], "on")
            self.assertEqual(order[-1], "off")
            self.assertLess(order.index("play"), order.index("wait"))

    def test_cancel_during_lead_in_releases_ptt_without_playing(self):
        stop = threading.Event()
        ptt = Mock(side_effect=lambda active:stop.set() if active else None)
        audio = Mock()
        with patch.dict("sys.modules", {"sounddevice":audio}):
            play_audio(np.zeros(10), ptt=ptt, lead=.1, cancelled=stop.is_set)
        self.assertEqual(ptt.call_args_list, [call(True), call(False)])
        audio.play.assert_not_called()

    def test_failed_ptt_on_does_not_start_audio_and_still_attempts_off(self):
        ptt = Mock(side_effect=[HamlibError("Lost acknowledgement"), None])
        audio = Mock()
        with patch.dict("sys.modules", {"sounddevice":audio}), self.assertRaises(HamlibError):
            play_audio(np.zeros(10), ptt=ptt)
        audio.play.assert_not_called()
        self.assertEqual(ptt.call_args_list, [call(True), call(False)])


@unittest.skipUnless(os.environ.get("KGSTV_RIGCTLD"), "Set KGSTV_RIGCTLD to test real Hamlib's Dummy backend")
class RealHamlibTests(unittest.TestCase):
    def test_real_daemon_model_list_control_and_ptt_cleanup(self):
        executable = os.environ["KGSTV_RIGCTLD"]
        self.assertTrue(any(model == 3078 and "IC-7610" in name for model, name in list_models(executable)))
        session = RadioSession(lambda *_:None)
        try:
            session.connect(RadioConfig(executable=executable, model=1, device="", baud=0, civ=""))
            session.set_frequency(14230000)
            session.set_mode("PKTUSB", 2400)
            state = session.client.snapshot()
            self.assertEqual((state.frequency, state.mode), (14230000, "PKTUSB"))
            session.ptt(True)
            self.assertEqual(session.client.get_ptt(), 1)
            session.ptt(False)
            self.assertEqual(session.client.get_ptt(), 0)
            audio = Mock()
            audio.play.side_effect = RuntimeError("simulated soundcard failure")
            with patch.dict("sys.modules", {"sounddevice":audio}), self.assertRaises(RuntimeError):
                play_audio(np.zeros(10), ptt=session.ptt)
            self.assertEqual(session.client.get_ptt(), 0)
            process = session.daemon.process
        finally:
            session.close()
        self.assertIsNotNone(process.poll())


if __name__ == "__main__":
    unittest.main()
