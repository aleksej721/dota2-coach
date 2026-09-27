"""PrefetchedSource: разбор проходит на данных браузера, даже когда IP сервера в 429.

Запуск: python -m unittest tests/test_prefetched_source.py
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dota2coach.sources.base import KIND_RATE_LIMITED, DataSourceError  # noqa: E402
from dota2coach.sources.prefetched import MAX_PREFETCHED, PrefetchedSource, valid_raw  # noqa: E402


def raw(match_id, players=10):
    return {"match_id": match_id, "players": [{"player_slot": i} for i in range(players)]}


class RateLimitedServer:
    """Серверный источник в том состоянии, в каком он был на проде: любой запрос — 429."""

    def __init__(self, cached=None):
        self.cached = cached or {}
        self.stored = []

    def cached_parsed(self, match_id):
        return self.cached.get(match_id)

    def from_raw(self, data):
        return ("normalized", data["match_id"], data.get("origin", "browser"))

    def fetch_match(self, match_id, allow_parse=True):
        raise DataSourceError("429", KIND_RATE_LIMITED)

    def fetch_player_matches(self, *args, **kwargs):
        raise DataSourceError("429", KIND_RATE_LIMITED)

    def _store_match(self, *args):  # пишущий путь не должен вызываться вовсе
        self.stored.append(args)


class PrefetchedSourceTest(unittest.TestCase):
    def test_serves_browser_copy_when_server_is_rate_limited(self):
        server = RateLimitedServer()
        source = PrefetchedSource(server, [raw(1)])
        self.assertEqual(source.fetch_match(1), ("normalized", 1, "browser"))
        self.assertEqual(server.stored, [], "данные браузера не должны попадать в общий кэш")

    def test_parsed_server_cache_wins_over_browser_copy(self):
        server = RateLimitedServer(cached={1: {**raw(1), "origin": "server"}})
        source = PrefetchedSource(server, [raw(1)])
        self.assertEqual(source.fetch_match(1)[2], "server")

    def test_missing_match_falls_back_to_server(self):
        source = PrefetchedSource(RateLimitedServer(), [raw(1)])
        with self.assertRaises(DataSourceError) as ctx:
            source.fetch_match(2)
        self.assertEqual(ctx.exception.kind, KIND_RATE_LIMITED)

    def test_match_list_from_browser_including_empty(self):
        self.assertEqual(PrefetchedSource(RateLimitedServer(), [], [5, 4, 3])
                         .fetch_player_matches(1, 2), [5, 4])
        # Пустой список — честный ответ «матчей нет», а не повод идти в 429.
        self.assertEqual(PrefetchedSource(RateLimitedServer(), [], [])
                         .fetch_player_matches(1, 10), [])
        with self.assertRaises(DataSourceError):
            PrefetchedSource(RateLimitedServer(), []).fetch_player_matches(1, 10)

    def test_garbage_is_ignored(self):
        self.assertFalse(valid_raw("x"))
        self.assertFalse(valid_raw({"match_id": "abc", "players": []}))
        self.assertFalse(valid_raw({"match_id": 1, "players": [1, 2]}))
        self.assertFalse(valid_raw(raw(1, players=11)))
        self.assertFalse(valid_raw(raw(1), match_id=2))
        source = PrefetchedSource(RateLimitedServer(), ["x", {"match_id": 1}, raw(3)])
        self.assertEqual(source.count, 1)

    def test_upload_is_capped(self):
        source = PrefetchedSource(RateLimitedServer(), [raw(i) for i in range(1, 100)])
        self.assertEqual(source.count, MAX_PREFETCHED)


if __name__ == "__main__":
    unittest.main()
