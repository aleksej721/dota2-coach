import hashlib
import pathlib
import tempfile
import unittest

from dota2coach.cli import main
from dota2coach.replay.ingest import (SOURCE2_MAGIC, ReplayInputError,
                                      inspect_replay_file)


class ReplayIngestTest(unittest.TestCase):
    def test_valid_source2_file_is_streamed_and_identified(self):
        payload = SOURCE2_MAGIC + b"fixture-packet-data"
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "match.dem"
            path.write_bytes(payload)
            info = inspect_replay_file(path)
        self.assertEqual(len(payload), info.size_bytes)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), info.content_sha256)
        self.assertEqual("PBDEMS2", info.magic)

    def test_rejects_wrong_magic_and_oversized_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "not-a-replay.dem"
            path.write_bytes(b"NOTADEM!payload")
            with self.assertRaises(ReplayInputError):
                inspect_replay_file(path)

            path.write_bytes(SOURCE2_MAGIC + b"0123456789")
            with self.assertRaises(ReplayInputError):
                inspect_replay_file(path, max_bytes=8)

    def test_cli_rejects_missing_file_without_traceback(self):
        self.assertEqual(1, main(["replay", "inspect", "/missing/replay.dem"]))


if __name__ == "__main__":
    unittest.main()
