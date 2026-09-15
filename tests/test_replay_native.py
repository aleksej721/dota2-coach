import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from dota2coach.replay.native import NativeReplayError, find_native_engine, native_scan


class NativeReplayTest(unittest.TestCase):
    def test_explicit_executable_is_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "engine"
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(0o700)
            self.assertEqual(path.resolve(), find_native_engine(path))

    @mock.patch("dota2coach.replay.native.find_native_engine")
    @mock.patch("dota2coach.replay.native.subprocess.run")
    def test_scan_uses_no_shell_and_decodes_json(self, run, find_engine):
        find_engine.return_value = pathlib.Path("/safe/engine")
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "schema_version": 1, "status": "payloads_decoded", "command_count": 7
            }),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory:
            replay = pathlib.Path(directory) / "match.dem"
            replay.write_bytes(b"demo")
            result = native_scan(replay, timeout=9)
        self.assertEqual(7, result["command_count"])
        args, kwargs = run.call_args
        self.assertEqual(["/safe/engine", "scan", str(replay.resolve())], args[0])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(9, kwargs["timeout"])

    @mock.patch("dota2coach.replay.native.find_native_engine")
    @mock.patch("dota2coach.replay.native.subprocess.run")
    def test_native_failure_is_reported_without_json_traceback(self, run, find_engine):
        find_engine.return_value = pathlib.Path("/safe/engine")
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="replay rejected: corrupt",
        )
        with tempfile.TemporaryDirectory() as directory:
            replay = pathlib.Path(directory) / "match.dem"
            replay.write_bytes(b"demo")
            with self.assertRaisesRegex(NativeReplayError, "corrupt"):
                native_scan(replay)


if __name__ == "__main__":
    unittest.main()
