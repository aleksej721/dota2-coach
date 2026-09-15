import contextlib
import hashlib
import io
import json
import pathlib
import struct
import tempfile
import unittest

from dota2coach.cli import main
from dota2coach.replay.framing import (COMPRESSED_FLAG, SOURCE2_MAGIC, DemoFormatError,
                                       DemoReader, scan_replay_file)


def uvarint(value):
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def frame(command, tick, body=b""):
    raw_tick = tick & 0xFFFFFFFF
    return uvarint(command) + uvarint(raw_tick) + uvarint(len(body)) + body


def indexed_fixture():
    sync = frame(3, -1)
    full = frame(13 | COMPRESSED_FLAG, 300, b"compressed-fixture")
    unknown = frame(31, 300, b"future")
    spawn = frame(15, 400, b"spawn")
    info = frame(2, 400, b"info")
    sync_offset = 16
    full_offset = sync_offset + len(sync)
    spawn_offset = full_offset + len(full) + len(unknown)
    info_offset = spawn_offset + len(spawn)
    header = SOURCE2_MAGIC + struct.pack("<II", info_offset, spawn_offset)
    return header + sync + full + unknown + spawn + info, full_offset, len(header + sync)


class ReplayFramingTest(unittest.TestCase):
    def test_stream_reader_decodes_outer_frames_and_signed_pregame_tick(self):
        payload = SOURCE2_MAGIC + struct.pack("<II", 0, 0) + frame(
            7 | COMPRESSED_FLAG, -1, b"abc"
        )
        reader = DemoReader(io.BytesIO(payload), file_size=len(payload))
        commands = list(reader.commands())
        self.assertEqual(1, len(commands))
        command = commands[0]
        self.assertEqual(7, command.command_id)
        self.assertEqual("DEM_Packet", command.command_name)
        self.assertEqual(-1, command.tick)
        self.assertTrue(command.compressed)
        self.assertEqual(b"abc", command.body)
        self.assertEqual(len(payload), command.end_offset)

    def test_scan_builds_seek_index_without_retaining_bodies(self):
        payload, full_offset, playback_offset = indexed_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "indexed.dem"
            path.write_bytes(payload)
            index = scan_replay_file(path)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), index.content_sha256)
        self.assertEqual(5, index.command_count)
        self.assertEqual(1, index.compressed_command_count)
        self.assertEqual((300, 400, 2),
                         (index.first_tick, index.last_tick, index.distinct_tick_count))
        self.assertEqual(playback_offset, index.playback_offset)
        self.assertEqual([(full_offset, 300)],
                         [(position.offset, position.tick) for position in index.full_packets])
        self.assertEqual({31: 1}, dict(index.unknown_command_counts))

    def test_rejects_truncated_overflowing_and_oversized_frames(self):
        header = SOURCE2_MAGIC + struct.pack("<II", 0, 0)
        cases = [
            (header + uvarint(7) + uvarint(1) + uvarint(5) + b"xx", None,
             "truncated command body"),
            (header + b"\xff\xff\xff\xff\x10", None, "overflows uint32"),
            (header + uvarint(7) + uvarint(1) + uvarint(6) + b"123456", 5,
             "exceeds limit"),
        ]
        for payload, max_frame, message in cases:
            with self.subTest(message=message):
                kwargs = {"file_size": len(payload)}
                if max_frame is not None:
                    kwargs["max_frame_bytes"] = max_frame
                reader = DemoReader(io.BytesIO(payload), **kwargs)
                with self.assertRaisesRegex(DemoFormatError, message):
                    list(reader.commands(read_bodies=False))

    def test_header_offsets_must_point_to_expected_commands(self):
        body = frame(7, 1, b"packet")
        payload = SOURCE2_MAGIC + struct.pack("<II", 16, 0) + body
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "wrong-target.dem"
            path.write_bytes(payload)
            with self.assertRaisesRegex(DemoFormatError, "does not point"):
                scan_replay_file(path)

    def test_cli_scan_emits_machine_readable_index(self):
        payload, _, _ = indexed_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "cli.dem"
            path.write_bytes(payload)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["replay", "scan", str(path), "--json"])
        self.assertEqual(0, code)
        result = json.loads(output.getvalue())
        self.assertEqual("container_indexed", result["status"])
        self.assertEqual(5, result["command_count"])
        self.assertEqual(1, result["full_packet_count"])
        self.assertEqual(1, result["command_counts"]["UNKNOWN_31"])


if __name__ == "__main__":
    unittest.main()
