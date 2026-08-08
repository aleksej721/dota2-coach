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
import re
from typing import Any, Dict, List, Optional

import requests

# Токен локализации Valve вида {s:bonus_rot_slow} с необязательным знаком и
# прилипшей единицей измерения сразу после скобки ("%" или "s" = секунды).
# Единица ловится только вплотную к "}", иначе съели бы 's' у следующего слова.
_LOC_TOKEN = re.compile(r"[+-]?\{[sfvd]:[^}]*\}(?:%|s(?=\s|$))?")


def strip_loc_tokens(text: str) -> str:
    """Срезает неразрешённые токены локализации, оставляя читаемое название.

    Значений талантов OpenDota не отдаёт (в constants/abilities у них есть
    только dname с шаблоном), поэтому подставить число неоткуда. Вместо мусора
    «+{s:bonus_rot_slow}% Rot Slow» отдаём чистое «Rot Slow».
    """
    if "{" not in text:
        return text
    cleaned = _LOC_TOKEN.sub(" ", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned.strip(" +-/,")


def _prettify(internal: str) -> str:
    """npc-имя как запасной вариант: pudge_flesh_heap -> Pudge Flesh Heap."""
    return internal.replace("_", " ").title()


class Constants:
    """Базовый интерфейс справочника — чтобы можно было подменить заглушкой в тестах."""

    def hero_name(self, hero_id: Optional[int]) -> str:
        return f"hero_{hero_id}"

    def hero_npc(self, hero_id: Optional[int]) -> Optional[str]:
        return None

    def hero_id_by_name(self, name: Optional[str]) -> Optional[int]:
        """Имя героя -> id. Нужен режиму профиля: OpenDota фильтрует по id."""
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

    def is_talent(self, ability_id: Optional[int]) -> bool:
        return False

    def item_name(self, key: Optional[str]) -> str:
        return (key or "").replace("item_", "")

    def item_cost(self, key: Optional[str]) -> int:
        return 0

    def item_components(self, key: Optional[str]) -> List[str]:
        return []

    def item_is_consumable(self, key: Optional[str]) -> bool:
        return False

    def permanent_buff_name(self, buff_id: Optional[int]) -> str:
        return f"buff#{buff_id}"


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

    def hero_id_by_name(self, name: Optional[str]) -> Optional[int]:
        """Терпимо к вводу: «pl», «phantom lancer», «Phantom_Lancer» найдут одного героя.

        Сначала точное совпадение, потом подстрока — и только если она однозначна.
        «Phantom» отдаст None (Phantom Lancer и Phantom Assassin), и вызывающий код
        честно попросит уточнить, вместо того чтобы молча взять первого.
        """
        needle = " ".join((name or "").replace("_", " ").split()).lower()
        if not needle:
            return None

        heroes = self._load("heroes")
        if not isinstance(heroes, dict):
            return None

        names = {}
        for key, entry in heroes.items():
            localized = (entry.get("localized_name") or "").lower()
            if localized:
                names[localized] = int(key)

        if needle in names:
            return names[needle]
        hits = {hero_id for label, hero_id in names.items() if needle in label}
        return hits.pop() if len(hits) == 1 else None

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

    def _ability_internal(self, ability_id: Optional[int]) -> Optional[str]:
        # ability_ids: {id -> internal_name}; abilities: {internal_name -> {dname}}
        ids = self._load("ability_ids")
        return ids.get(str(ability_id)) if isinstance(ids, dict) else None

    def ability_name(self, ability_id: Optional[int]) -> str:
        internal = self._ability_internal(ability_id)
        if not internal:
            return f"ability_{ability_id}"
        abilities = self._load("abilities")
        entry = abilities.get(internal) if isinstance(abilities, dict) else None
        dname = (entry or {}).get("dname")
        if not dname:
            return internal
        # У талантов dname — шаблон с {s:...}; значения в OpenDota отсутствуют.
        return strip_loc_tokens(dname) or internal

    def is_talent(self, ability_id: Optional[int]) -> bool:
        return (self._ability_internal(ability_id) or "").startswith("special_bonus")

    # --- предметы -------------------------------------------------------------

    def _item_entry(self, key: Optional[str]) -> Dict[str, Any]:
        if not key:
            return {}
        items = self._load("items")
        if not isinstance(items, dict):
            return {}
        return items.get(key.replace("item_", "")) or {}

    def item_name(self, key: Optional[str]) -> str:
        if not key:
            return ""
        clean = key.replace("item_", "")
        return self._item_entry(clean).get("dname") or clean

    def item_cost(self, key: Optional[str]) -> int:
        return int(self._item_entry(key).get("cost") or 0)

    def item_components(self, key: Optional[str]) -> List[str]:
        comps = self._item_entry(key).get("components") or []
        return [c for c in comps if c]  # в справочнике встречаются пустые строки

    def item_is_consumable(self, key: Optional[str]) -> bool:
        qual = self._item_entry(key).get("qual") or ""
        return "consumable" in qual

    # --- постоянные баффы -----------------------------------------------------

    def permanent_buff_name(self, buff_id: Optional[int]) -> str:
        """permanent_buffs: {id -> internal}; internal может быть и предметом, и способностью."""
        buffs = self._load("permanent_buffs")
        internal = buffs.get(str(buff_id)) if isinstance(buffs, dict) else None
        if not internal:
            return f"buff#{buff_id}"
        item = self._item_entry(internal).get("dname")
        if item:
            return item
        abilities = self._load("abilities")
        entry = abilities.get(internal) if isinstance(abilities, dict) else None
        if entry and entry.get("dname"):
            return strip_loc_tokens(entry["dname"])
        return _prettify(internal)
