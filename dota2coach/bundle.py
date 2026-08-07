"""BundleBuilder — превращает Features в текстовый промпт для LLM.

Секции идут от общего к частному: мета -> драфт -> скорборд -> бенчмарки ->
нетворт-таймлайн -> предметы -> скиллбилд -> лайнинг -> бой/экономика ->
тимфайты -> объективы -> ограничения -> задача.

depth:
  quick — компактно: командные/мои данные, детальные по-игроку логи свёрнуты;
  deep  — всё по всем 10 игрокам (рекомендуется для максимального контекста).
"""

from typing import Any, Dict, List

from .features import Features


class BundleBuilder:
    def build(self, features: Features, depth: str) -> str:
        deep = depth == "deep"
        L: List[str] = []

        L += self._header()
        L += self._meta(features.meta)
        L += self._draft(features.draft)
        L += self._scoreboard(features.scoreboard)
        L += self._benchmarks(features.benchmarks, deep)
        L += self._networth(features.networth, deep)
        L += self._items(features.items, deep)
        if deep:
            L += self._abilities(features.abilities)
        L += self._laning(features.laning)
        L += self._combat(features.combat, deep)
        if deep and features.buffs:
            L += self._buffs(features.buffs)
        L += self._teamfights(features.teamfights, deep)
        if deep:
            L += self._damage(features.damage)
        L += self._objectives(features.objectives)
        L += self._limitations(features.meta)
        L += self._task()
        return "\n".join(L) + "\n"

    # --- секции ---------------------------------------------------------------

    def _header(self) -> List[str]:
        return [
            "=== ЗАПРОС НА РАЗБОР МАТЧА DOTA 2 ===",
            "",
            "Ты — опытный персональный тренер по Dota 2. Ниже — структурированные ФАКТЫ "
            "одного моего матча из OpenDota (мой игрок помечен ★Я; [R]=Radiant, [D]=Dire). "
            "Разбери мою игру. Опирайся ТОЛЬКО на эти факты; если данных не хватает — так "
            "и скажи, не выдумывай.",
            "",
        ]

    def _meta(self, m: Dict[str, Any]) -> List[str]:
        return [
            "## МЕТА",
            f"Матч {m['match_id']} | патч {m['patch']} | {m['mode']} / {m['lobby']} | "
            f"длительность {m['duration']}",
            f"Результат: {m['result']} (моя сторона — {m['my_side']}, победила — {m['winner']})",
            f"Я: {m['me']}",
            "",
        ]

    def _draft(self, d: Dict[str, Any]) -> List[str]:
        out = ["## ДРАФТ"]
        if d["picks_bans"]:
            out.append("Порядок пиков/банов (Captains Mode):")
            for pb in d["picks_bans"]:
                out.append(f"  #{pb['order']:>2} {pb['side']:<7} {pb['kind']:<3} {pb['hero']}")
        else:
            out.append("Пофазовый порядок пиков/банов недоступен для этого режима "
                       "(All Pick — OpenDota не отдаёт стадии драфта). Ниже — итоговые составы:")
        out.append("Radiant:")
        out += [f"  - {p['hero']} | {p['pos']}" for p in d["radiant"]]
        out.append("Dire:")
        out += [f"  - {p['hero']} | {p['pos']}" for p in d["dire"]]
        out.append("")
        return out

    def _scoreboard(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## СКОРБОРД (итог)",
               "герой | ур | K/D/A | LH/DN | GPM/XPM | нетворт | урон-героям | урон-строениям | "
               "лечение | получено урона"]
        for r in rows:
            out.append(f"  {r['who']} | {r['lvl']} | {r['kda']} | {r['lh_dn']} | {r['gpm_xpm']} | "
                       f"{r['nw']} | {r['hd']} | {r['td']} | {r['heal']} | {r['dt']}")
        out.append("")
        return out

    def _benchmarks(self, rows: List[Dict[str, Any]], deep: bool) -> List[str]:
        out = ["## БЕНЧМАРКИ (сравнение с типичными на этом герое; перцентиль 0–100)"]
        shown = rows if deep else [r for r in rows if "★Я" in r["who"]]
        for r in shown:
            if not r["rows"]:
                continue
            metrics = "; ".join(f"{x['metric']} {x['raw']} ({x['pct']})" for x in r["rows"])
            out.append(f"  {r['who']}: {metrics}")
        if not deep:
            out.append("  (полные бенчмарки по всем игрокам — в режиме --depth deep)")
        out.append("")
        return out

    def _networth(self, nw: Dict[str, Any], deep: bool) -> List[str]:
        out = ["## НЕТВОРТ ПО МИНУТАМ", nw["note"], "", "Баланс команд (нетворт, >0 — моя команда впереди):"]
        for t in nw["team"]:
            out.append(f"  m{t['m']:>2}: R={t['radiant']}  D={t['dire']}  мой_перевес={t['my_adv']}")
        if deep:
            out += ["", "Нетворт каждого игрока по минутам:"]
            for pp in nw["per_player"]:
                series = ", ".join(f"m{s['m']}={s['nw']}" for s in pp["series"])
                out.append(f"  {pp['who']}: {series}")
        out.append("")
        return out

    def _items(self, rows: List[Dict[str, Any]], deep: bool) -> List[str]:
        out = ["## ПРЕДМЕТЫ И ТАЙМИНГИ"]
        shown = rows if deep else [r for r in rows if "★Я" in r["who"]]
        for r in shown:
            timings = ", ".join(f"{t['time']} {t['item']}" for t in r["timings"]) or "—"
            out.append(f"  {r['who']}: {timings}")
        if not deep:
            out.append("  (предметы всех игроков — в режиме --depth deep)")
        out.append("")
        return out

    def _abilities(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## РАСКАЧКА СПОСОБНОСТЕЙ (по уровням)"]
        for r in rows:
            build = ", ".join(f"{b['lvl']}:{b['ability']}" for b in r["build"]) or "—"
            out.append(f"  {r['who']}: {build}")
        out.append("")
        return out

    def _laning(self, ln: Dict[str, Any]) -> List[str]:
        out = ["## ЛАЙНИНГ 0–10",
               f"Моя линия/роль: {ln['me_lane']} | лайн-эффективность: "
               f"{ln['me_eff_pct'] if ln['me_eff_pct'] is not None else '?'}%"]
        out.append("Мои добивания/денаи по минутам:")
        out.append("  " + ", ".join(f"m{c['min']}:{c['lh']}/{c['dn']}" for c in ln["cs_by_min"]))
        out.append("Мои киллы в лайнинге:")
        out += [f"  {k['time']} убил {k['victim']}" for k in ln["my_kills"]] or ["  —"]
        out.append("Мои смерти в лайнинге:")
        out += [f"  {d['time']} погиб от {d['killer']}" for d in ln["my_deaths"]] or ["  —"]
        if ln["lane_efficiency_all"]:
            out.append("Лайн-эффективность всех (для сравнения линий):")
            out.append("  " + ", ".join(f"{e['who']}={e['eff_pct']}%" for e in ln["lane_efficiency_all"]))
        out.append("")
        return out

    def _combat(self, rows: List[Dict[str, Any]], deep: bool) -> List[str]:
        out = ["## БОЙ И ЭКОНОМИКА (доп. счётчики)"]
        shown = rows if deep else [r for r in rows if "★Я" in r["who"]]
        for r in shown:
            kt = r["kills_by_type"]
            kt_txt = ", ".join(f"{name}:{val}" for name, val in kt.items() if val)
            out.append(
                f"  {r['who']}: серия {r['best_streak']}, мультикилл x{r['best_multikill']}, "
                f"стан {r['stuns_sec']}с, стак лагерей {r['camps_stacked']}, руны {r['runes']}, "
                f"варды {r['obs']}обс/{r['sen']}сен, выкупы {r['buybacks']}, APM {r['apm']}, "
                f"мёртв {r['time_dead']}, пинги {r['pings']}"
                + (f", макс.удар {r['max_hit']}" if r["max_hit"] else "")
                + (f" | добито: {kt_txt}" if kt_txt else "")
            )
        if not deep:
            out.append("  (по всем игрокам — в режиме --depth deep)")
        out.append("")
        return out

    def _buffs(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## ПОСТОЯННЫЕ БАФФЫ / СТАКИ (Flesh Heap и т.п.)"]
        for r in rows:
            b = ", ".join(f"buff#{x['buff_id']}×{x['stacks']}" for x in r["buffs"])
            out.append(f"  {r['who']}: {b}")
        out.append("")
        return out

    def _teamfights(self, tfs: List[Dict[str, Any]], deep: bool) -> List[str]:
        out = ["## ТИМФАЙТЫ"]
        if not tfs:
            return out + ["  — (в матче не выделено крупных тимфайтов)", ""]
        for i, tf in enumerate(tfs, 1):
            tag = " (в фазе лайнинга)" if tf["in_lane"] else ""
            out.append(f"Бой {i}: {tf['start']}–{tf['end']}, всего смертей {tf['deaths']}{tag}")
            if deep:
                for p in tf["participants"]:
                    out.append(f"    {p['who']}: Δgold={p['gold_delta']}, Δxp={p['xp_delta']}, "
                               f"смертей={p['deaths']}, урон={p['damage']}, лечение={p['healing']}")
        if not deep:
            out.append("  (поимённая раскладка боёв — в режиме --depth deep)")
        out.append("")
        return out

    def _damage(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## УРОН ПО ГЕРОЯМ (топ-цели каждого)"]
        for r in rows:
            if not r["targets"]:
                continue
            t = ", ".join(f"{x['hero']}:{x['dmg']}" for x in r["targets"])
            out.append(f"  {r['who']}: {t}")
        out.append("")
        return out

    def _objectives(self, objs: List[Dict[str, Any]]) -> List[str]:
        out = ["## ОБЪЕКТИВЫ (башни / Рошан / первая кровь)"]
        out += [f"  {o['time']} {o['event']}" for o in objs] or ["  —"]
        out.append("")
        return out

    def _limitations(self, meta: Dict[str, Any]) -> List[str]:
        note = [
            "## ОГРАНИЧЕНИЯ ДАННЫХ (важно, не додумывай)",
            "- Нетворт/опыт/CS доступны с гранулярностью 1 точка в минуту — это максимум OpenDota.",
            "- Позиции игроков — только агрегированный хитмап, НЕ временной ряд координат.",
            "- HP-по-времени и посекундные размены недоступны (появятся в Тир 3, свой парсер).",
        ]
        if not meta.get("parsed"):
            note.append("- ВНИМАНИЕ: матч распарсен не полностью — часть детальных полей может быть пустой.")
        note.append("")
        return note

    def _task(self) -> List[str]:
        return [
            "## ЗАДАЧА",
            "1. Оцени мою фазу лайнинга 0–10 (CS, лайн-эффективность, размены, тайминги).",
            "2. Разбери мой мид-/лейт-гейм по нетворт-кривой, таймингам предметов и тимфайтам: "
            "где я усиливал команду, где проседал.",
            "3. Сопоставь мои бенчмарки с типичными — что заметно ниже/выше нормы.",
            "4. Назови 2–3 переломных момента матча по объективам и балансу команд.",
            "5. Дай 3 конкретных совета на следующие игры на этом герое/позиции.",
            "Опирайся на цифры выше и будь конкретным.",
        ]
