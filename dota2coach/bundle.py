"""BundleBuilder — превращает Features в текстовый промпт для LLM.

Секции идут от общего к частному: мета -> драфт -> скорборд -> бенчмарки ->
нетворт -> предметы -> раскачка -> лайнинг -> бой -> баффы -> тимфайты ->
урон -> объективы -> ограничения -> задача.

Что именно и с какой детализацией печатается, решает Policy (см. policy.py):
builder только форматирует то, что ему дали, и нигде не принимает решений
«показывать/не показывать» сам.
"""

from typing import Any, Dict, List

from .features import Features
from .policy import EXPANDED, Policy


def _fmt_signed(value: Any) -> str:
    if value is None:
        return "?"
    return f"+{value}" if value > 0 else str(value)


class BundleBuilder:
    def build(self, features: Features, policy: Policy) -> str:
        L: List[str] = []
        L += self._header()
        L += self._meta(features.meta, policy)
        if features.draft:
            L += self._draft(features.draft, policy)
        L += self._scoreboard(features.scoreboard)
        if features.benchmarks:
            L += self._benchmarks(features.benchmarks, policy)
        if features.networth:
            L += self._networth(features.networth)
        if features.items:
            L += self._items(features.items)
        if features.abilities:
            L += self._abilities(features.abilities)
        if features.laning:
            L += self._laning(features.laning)
        if features.combat:
            L += self._combat(features.combat)
        if features.buffs:
            L += self._buffs(features.buffs)
        if features.teamfights:
            L += self._teamfights(features.teamfights, policy)
        if features.damage:
            L += self._damage(features.damage)
        if features.objectives:
            L += self._objectives(features.objectives)
        L += self._limitations(features)
        L += self._task(policy)
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

    def _meta(self, m: Dict[str, Any], policy: Policy) -> List[str]:
        return [
            "## МЕТА",
            f"Матч {m['match_id']} | патч {m['patch']} | {m['mode']} / {m['lobby']} | "
            f"длительность {m['duration']}",
            f"Результат: {m['result']} (моя сторона — {m['my_side']}, победила — {m['winner']})",
            f"Я: {m['me']}",
            f"Режим экспорта: depth={policy.depth}, focus={policy.focus}",
            "",
        ]

    def _draft(self, d: Dict[str, Any], policy: Policy) -> List[str]:
        out = ["## ДРАФТ"]
        if not d["rows"]:
            out.append("Стадии драфта (пики/баны) OpenDota для этого режима не отдаёт. "
                       "Ниже — итоговые составы:")
        elif d["chronological"]:
            out.append(f"Порядок драфта ({d['mode']}), хронологический:")
            for r in d["rows"]:
                out.append(f"  #{r['order']:>2} {r['side']:<7} {r['kind']:<3} {r['hero']}")
        else:
            out.append(f"Драфт ({d['mode']}). Источник отдаёт пики и баны отдельными "
                       "группами — истинный порядок между ними неизвестен.")
            out.append("  Баны: " + (", ".join(f"{r['side'][0]}:{r['hero']}"
                                               for r in d["bans"]) or "—"))
            out.append("  Пики: " + (", ".join(f"{r['side'][0]}:{r['hero']}"
                                               for r in d["picks"]) or "—"))
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

    def _benchmarks(self, rows: List[Dict[str, Any]], policy: Policy) -> List[str]:
        out = ["## БЕНЧМАРКИ (сравнение с типичными на этом герое; перцентиль 0–100)"]
        for r in rows:
            if not r["rows"]:
                continue
            metrics = "; ".join(f"{x['metric']} {x['raw']} ({x['pct']})" for x in r["rows"])
            out.append(f"  {r['who']}: {metrics}")
        if not policy.at_least("benchmarks", EXPANDED):
            out.append("  (бенчмарки остальных игроков — в режиме --depth deep)")
        out.append("")
        return out

    def _networth(self, nw: Dict[str, Any]) -> List[str]:
        out = ["## ЭКОНОМИКА: ПЕРЕВЕС КОМАНД И КРИВЫЕ НЕТВОРТА", nw["note"], ""]

        out.append("Перевес моей команды (>0 — впереди мы), золото / опыт:")
        for t in nw["team"]:
            out.append(f"  m{t['m']:>2}: золото {_fmt_signed(t['gold'])}, "
                       f"опыт {_fmt_signed(t['xp'])}")

        out.append("Переломы (минуты, где перевес по золоту менял знак):")
        out += [f"  m{s['m']}: {s['text']} ({_fmt_signed(s['gold'])} золота)"
                for s in nw["swings"]] or ["  — (перевес не менял знак)"]

        if nw.get("peak"):
            best, worst = nw["peak"]["best"], nw["peak"]["worst"]
            out.append(f"Максимум: {_fmt_signed(best['gold'])} на m{best['m']}; "
                       f"минимум: {_fmt_signed(worst['gold'])} на m{worst['m']}")

        out.append("")
        out.append("Кривые нетворта:")
        for c in nw["curves"]:
            series = ", ".join(f"m{s['m']}={s['nw']}" for s in c["series"] if s["nw"] is not None)
            out.append(f"  {c['who']}: {series}")
        out.append("")
        return out

    def _items(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## ПРЕДМЕТЫ И ТАЙМИНГИ (собранные предметы; компоненты и расходники скрыты)"]
        for r in rows:
            timings = ", ".join(f"{t['time']} {t['item']}" for t in r["timings"]) or "—"
            out.append(f"  {r['who']} [{r['kind']}]: {timings}")
        out.append("")
        return out

    def _abilities(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## РАСКАЧКА СПОСОБНОСТЕЙ (#N — порядок прокачки, не уровень героя)"]
        for r in rows:
            build = ", ".join(f"#{b['n']} {b['ability']}" for b in r["build"]) or "—"
            out.append(f"  {r['who']}: {build}")
        out.append("")
        return out

    def _laning(self, ln: Dict[str, Any]) -> List[str]:
        out = ["## ЛАЙНИНГ 0–10",
               f"Моя линия/роль: {ln['me_lane']} | лайн-эффективность: "
               f"{ln['me_eff_pct'] if ln['me_eff_pct'] is not None else '?'}%"]

        out.append("Мои добивания/денаи по минутам:")
        out.append("  " + ", ".join(f"m{c['min']}:{c['lh']}/{c['dn']}" for c in ln["cs_by_min"]))

        if ln["my_gold_xp"]:
            out.append("Мои золото/опыт по минутам:")
            out.append("  " + ", ".join(f"m{c['min']}:{c['gold']}g/{c['xp']}xp"
                                        for c in ln["my_gold_xp"]))

        if ln["opponents"]:
            out.append("Соперники по моей линии:")
            for o in ln["opponents"]:
                line = (f"  {o['who']} | {o['pos']} | лайн-эффективность "
                        f"{o['eff_pct'] if o['eff_pct'] is not None else '?'}%")
                if ln["detailed"]:
                    line += "\n    добивания/денаи: " + ", ".join(
                        f"m{c['min']}:{c['lh']}/{c['dn']}" for c in o["cs_by_min"])
                out.append(line)

        out.append("Мои киллы в лайнинге:")
        out += [f"  {k['time']} убил {k['victim']}" for k in ln["my_kills"]] or ["  —"]
        out.append("Мои смерти в лайнинге:")
        out += [f"  {d['time']} погиб от {d['killer']}" for d in ln["my_deaths"]] or ["  —"]

        if ln["lane_efficiency_all"]:
            out.append("Лайн-эффективность всех (для сравнения линий):")
            out.append("  " + ", ".join(f"{e['who']}={e['eff_pct']}%"
                                        for e in ln["lane_efficiency_all"]))
        out.append("")
        return out

    def _combat(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## БОЙ И ЭКОНОМИКА (доп. счётчики)"]
        for r in rows:
            kt = ", ".join(f"{name}:{val}" for name, val in r["kills_by_type"].items() if val)
            line = (f"  {r['who']}: серия {r['best_streak']}, мультикилл x{r['best_multikill']}, "
                    f"стан {r['stuns_sec']}с, стак лагерей {r['camps_stacked']}, "
                    f"руны {r['runes']}, варды {r['obs']}обс/{r['sen']}сен, "
                    f"выкупы {r['buybacks']}, мёртв {r['time_dead']}")
            if kt:
                line += f" | добито: {kt}"
            extra = r.get("extra") or {}
            if extra:
                bits = [f"APM {extra['apm']}", f"пинги {extra['pings']}"]
                if extra.get("max_hero_hit"):
                    bits.append(f"max_hero_hit (крупнейший одиночный удар по герою) "
                                f"{extra['max_hero_hit']}")
                line += " | " + ", ".join(bits)
            out.append(line)
        out.append("")
        return out

    def _buffs(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## ПОСТОЯННЫЕ БАФФЫ (только реально накопленные стаки)"]
        for r in rows:
            b = ", ".join(f"{x['name']} ×{x['stacks']}"
                          + (f" (с {x['since']})" if x["since"] else "")
                          for x in r["buffs"])
            out.append(f"  {r['who']}: {b}")
        out.append("")
        return out

    def _teamfights(self, tfs: List[Dict[str, Any]], policy: Policy) -> List[str]:
        out = ["## ТИМФАЙТЫ"]
        if not tfs:
            return out + ["  — (в матче не выделено крупных тимфайтов)", ""]

        detailed = policy.at_least("teamfights", EXPANDED)
        for i, tf in enumerate(tfs, 1):
            tag = " (лайнинг)" if tf["in_lane"] else ""
            me = tf["me"]
            mine = (f"я: урон {me['damage']}, смертей {me['deaths']}, "
                    f"Δgold {_fmt_signed(me['gold_delta'])}")
            if me["killed"]:
                mine += f", убил: {', '.join(me['killed'])}"

            header = (f"Бой {i}: {tf['start']}–{tf['end']}{tag} | {tf['score']} — "
                      f"{tf['verdict']} | {mine}")
            if detailed:
                out.append(header)
                out.append(f"    погибли: {', '.join(tf['fallen']) or '—'}")
                for p in tf["participants"]:
                    out.append(f"    {p['who']}: Δgold={_fmt_signed(p['gold_delta'])}, "
                               f"Δxp={_fmt_signed(p['xp_delta'])}, смертей={p['deaths']}, "
                               f"урон={p['damage']}, лечение={p['healing']}")
            else:
                out.append(header)
                if tf["fallen"]:
                    out.append(f"    погибли: {', '.join(tf['fallen'])}")
        if not detailed:
            out.append("  (поимённая раскладка боёв — в --depth deep или --focus fights)")
        out.append("")
        return out

    def _damage(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = ["## УРОН ПО ГЕРОЯМ (топ-цели)"]
        for r in rows:
            if not r["targets"]:
                continue
            t = ", ".join(f"{x['hero']}:{x['dmg']}" for x in r["targets"])
            out.append(f"  {r['who']}: {t}")
        out.append("")
        return out

    def _objectives(self, objs: List[Dict[str, Any]]) -> List[str]:
        out = ["## ОБЪЕКТИВЫ (строения / Рошан / Тормантор / первая кровь)"]
        out += [f"  {o['time']} {o['event']}" for o in objs] or ["  —"]
        out.append("")
        return out

    def _limitations(self, features: Features) -> List[str]:
        note = [
            "## ОГРАНИЧЕНИЯ ДАННЫХ (важно, не додумывай)",
            "- Нетворт/опыт/CS доступны с гранулярностью 1 точка в минуту — это максимум OpenDota.",
            "- Позиции игроков — только агрегированный хитмап, НЕ временной ряд координат.",
            "- HP-по-времени и посекундные размены недоступны (появятся в Тир 3, свой парсер).",
            "- Позиции 1–5 и роли — эвристика по линии и нетворту, а не факт из источника.",
        ]
        note += features.caveats
        if not features.meta.get("parsed"):
            note.append("- ВНИМАНИЕ: матч распарсен не полностью — часть детальных полей "
                        "может быть пустой.")
        note.append("")
        return note

    def _task(self, policy: Policy) -> List[str]:
        out = ["## ЗАДАЧА"]
        out += [f"{i}. {t}" for i, t in enumerate(policy.tasks(), 1)]
        out.append("Опирайся на цифры выше и будь конкретным.")
        return out
