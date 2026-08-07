"""Справочники OpenDota: имена героев, режимов, патчей.

OpenDota отдаёт в матче числовые id (hero_id, game_mode, patch). Читаемые имена
лежат в /constants/<resource>. Тянем их один раз и кэшируем на диск (.cache/),
чтобы не дёргать сеть на каждый запуск.

Всё сделано best-effort: если сети нет или ресурс не скачался, методы возвращают
разумный fallback (напр. "hero_5"), и приложение продолжает работать. Это же
свойство позволяет гонять офлайн-тесты через StubConstants.
"""

import json
import pathlib
from typing import Any, Dict, Optional

import requests


class Constants:
    """Базовый интерфейс справочника — чтобы можно было подменить заглушкой в тестах."""

    def hero_name(self, hero_id: Optional[int]) -> str:
        return f"hero_{hero_id}"

    def hero_npc(self, hero_id: Optional[int]) -> Optional[str]:
        return None

    def npc_to_hero(self, npc_name: Optional[str]) -> str:
        return (npc_name or "").replace("npc_dota_hero_", "") or "unknown"

    def game_mode_name(self, gm_id: Optional[int]) -> str:
        return f"mode_{gm_id}"

    def lobby_type_name(self, lobby_id: Optional[int]) -> str:
        return f"lobby_{lobby_id}"

    def patch_name(self, patch_id: Optional[int]) -> str:
        return str(patch_id)

    def ability_name(self, ability_id: Optional[int]) -> str:
        return f"ability_{ability_id}"

    def item_name(self, key: Optional[str]) -> str:
        return (key or "").replace("item_", "")


class ConstantsRepo(Constants):
    BASE = "https://api.opendota.com/api/constants"

    def __init__(self, session: requests.Session, rate_limiter, api_key: Optional[str] = None,
                 cache_dir: str = ".cache"):
        self._session = session
        self._rate = rate_limiter
        self._api_key = api_key
        self._cache_dir = pathlib.Path(cache_dir)
        self._cache_dir.mkdir(exist_ok=True)
        self._mem: Dict[str, Any] = {}          # ресурс -> распарсенный JSON
        self._npc_index: Optional[Dict[str, str]] = None  # npc_name -> localized_name

    # --- загрузка ресурса с трёхуровневым фолбэком: память -> файл -> сеть -> {} ---
    def _load(self, resource: str) -> Any:
        if resource in self._mem:
            return self._mem[resource]

        cache_file = self._cache_dir / f"constants_{resource}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self._mem[resource] = data
                return data
            except (OSError, ValueError):
                pass  # битый кэш — перекачаем

        try:
            self._rate.acquire()
            params = {"api_key": self._api_key} if self._api_key else None
            resp = self._session.get(f"{self.BASE}/{resource}", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            data = {}  # best-effort: без справочника используем fallback-имена
        self._mem[resource] = data
        return data

    def hero_name(self, hero_id: Optional[int]) -> str:
        heroes = self._load("heroes")
        entry = heroes.get(str(hero_id)) if isinstance(heroes, dict) else None
        if entry and entry.get("localized_name"):
            return entry["localized_name"]
        return f"hero_{hero_id}"

    def hero_npc(self, hero_id: Optional[int]) -> Optional[str]:
        heroes = self._load("heroes")
        entry = heroes.get(str(hero_id)) if isinstance(heroes, dict) else None
        return entry.get("name") if entry else None

    def npc_to_hero(self, npc_name: Optional[str]) -> str:
        if not npc_name:
            return "unknown"
        if self._npc_index is None:
            heroes = self._load("heroes")
            self._npc_index = {}
            if isinstance(heroes, dict):
                for entry in heroes.values():
                    if entry.get("name"):
                        self._npc_index[entry["name"]] = entry.get("localized_name", entry["name"])
        return self._npc_index.get(npc_name, npc_name.replace("npc_dota_hero_", ""))

    def game_mode_name(self, gm_id: Optional[int]) -> str:
        modes = self._load("game_mode")
        entry = modes.get(str(gm_id)) if isinstance(modes, dict) else None
        if entry and entry.get("name"):
            return entry["name"].replace("game_mode_", "").replace("_", " ")
        return f"mode_{gm_id}"

    def lobby_type_name(self, lobby_id: Optional[int]) -> str:
        lobbies = self._load("lobby_type")
        entry = lobbies.get(str(lobby_id)) if isinstance(lobbies, dict) else None
        if entry and entry.get("name"):
            return entry["name"].replace("lobby_type_", "").replace("_", " ")
        return f"lobby_{lobby_id}"

    def patch_name(self, patch_id: Optional[int]) -> str:
        patches = self._load("patch")
        if isinstance(patches, list):
            for item in patches:
                if item.get("id") == patch_id and item.get("name"):
                    return item["name"]
        return str(patch_id)

    def ability_name(self, ability_id: Optional[int]) -> str:
        # ability_ids: {id -> internal_name}; abilities: {internal_name -> {dname}}
        ids = self._load("ability_ids")
        internal = ids.get(str(ability_id)) if isinstance(ids, dict) else None
        if internal:
            abilities = self._load("abilities")
            entry = abilities.get(internal) if isinstance(abilities, dict) else None
            if entry and entry.get("dname"):
                return entry["dname"]
            return internal
        return f"ability_{ability_id}"

    def item_name(self, key: Optional[str]) -> str:
        if not key:
            return ""
        clean = key.replace("item_", "")
        items = self._load("items")
        entry = items.get(clean) if isinstance(items, dict) else None
        if entry and entry.get("dname"):
            return entry["dname"]
        return clean
