"""BundleBuilder — превращает Features в текстовый промпт.

Разделение обязанностей:
  * Policy   — какие данные показать (тиры, глубина, фокус);
  * i18n     — на каком языке их подписать;
  * scaffold — по какой методике модель должна готовить разбор;
  * render   — во что это упаковать (markdown или XML-теги под Claude);
  * bundle   — собрать всё вместе, ничего не решая самостоятельно.

Своих текстов у модуля нет: каждая подпись приходит из словаря по ключу.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from . import i18n, scaffold
from .anomalies import Anomaly
from .features import Features
from .policy import EXPANDED, Policy
from .render import Group, Section, profile, renderer_for

if TYPE_CHECKING:  # только для аннотаций: profile импортирует features, не bundle
    from .profile import MatchDigest, ProfileFeatures


def _k(value: Optional[int]) -> str:
    """12345 -> 12.3k: в сводке важен порядок величины, а не последняя цифра."""
    if value is None:
        return "?"
    return f"{value / 1000:.1f}k" if abs(value) >= 1000 else str(value)


def _signed(value: Any) -> str:
    if value is None:
        return "?"
    return f"+{value}" if value > 0 else str(value)


class BundleBuilder:
    def build(self, features: Features, policy: Policy) -> str:
        s = i18n.load(policy.lang)
        if policy.whole_game:
            s = s.overlay("game.")
        if policy.followup:
            return self._unstar(self._followup(features, policy, s), policy)

        data = Group("match_data")
        data.add(s("sec.meta"), self._meta(features.meta, policy, s))
        # Окно идёт сразу после меты: игрок попросил именно этот отрезок, и он
        # должен стоять до сжатых секций, а не теряться под ними.
        if features.window:
            data.add(s("sec.window", start=features.window["start"],
                       end=features.window["end"]),
                     self._window(features.window, s))
        if features.facts:
            facts = (self._game_facts(features.facts, s) if features.facts.get("whole_game")
                     else self._facts(features.facts, s))
            data.add(s("sec.facts"), facts)
        if features.role_impact:
            data.add(s("sec.role_impact"), self._role_impact(features.role_impact, s))
        if policy.shows("anomalies"):
            data.add(s("sec.anomalies"), self._anomalies(features.anomalies, s))
        if features.draft:
            data.add(s("sec.draft"), self._draft(features.draft, s))
        data.add(s("sec.scoreboard"), self._scoreboard(features.scoreboard, s))
        if features.benchmarks:
            data.add(s("sec.benchmarks"), self._benchmarks(features.benchmarks, policy, s))
        if features.networth:
            data.add(s("sec.networth"), self._networth(features.networth, s))
        if features.items:
            data.add(s("sec.items"), self._items(features.items, s))
        if features.abilities:
            data.add(s("sec.abilities"), self._abilities(features.abilities, s))
        if features.laning:
            data.add(s("sec.laning"), self._laning(features.laning, s))
        if features.combat:
            data.add(s("sec.combat"), self._combat(features.combat, s))
        if features.buffs:
            data.add(s("sec.buffs"), self._buffs(features.buffs, s))
        if features.teamfights:
            data.add(s("sec.teamfights"), self._teamfights(features.teamfights, policy, s))
        if features.damage:
            data.add(s("sec.damage"), self._damage(features.damage))
        if features.objectives:
            data.add(s("sec.objectives"), self._objectives(features.objectives, s))

        groups = [Group("role", [Section(None, self._role(policy, s))]), data]

        limits = Group("data_limitations")
        limits.add(s("sec.limits"), self._limitations(features, s))
        groups.append(limits)

        if policy.has_note:
            note = Group("player_question")
            note.add(s("sec.note"), self._note(policy))
            groups.append(note)

        method = Group("method")
        method.add(s("sec.method"), scaffold.game_method_lines(policy, s) if policy.whole_game
                   else scaffold.method_lines(policy, s))
        groups.append(method)

        answer = Group("output_format")
        answer.add(s("sec.format"), scaffold.game_format_lines(policy, s) if policy.whole_game
                   else scaffold.format_lines(policy, s))
        groups.append(answer)

        body = renderer_for(policy.model).document(groups)
        return self._unstar(f"{s('header.title')}\n\n{body}", policy)

    @staticmethod
    def _unstar(text: str, policy: Policy) -> str:
        """В разборе игры целиком «моего» игрока нет — звёздочка не нужна."""
        if not policy.whole_game:
            return text
        return text.replace("★ ", "").replace("★", "")

    def _followup(self, f: Features, policy: Policy, s: i18n.Strings) -> str:
        """Промпт-уточнение по отрезку матча — для того же чата, что и основной.

        Без роли тренера, драфта, картины матча и методики: модель всё это уже
        получила первым промптом, и повтор только съел бы её внимание. Здесь
        ровно то, чего в первом промпте не было, — отрезок без прореживания.
        """
        start, end = policy.window
        meta = f.meta
        intro = Group("context")
        intro.add(None, [s("followup.intro", match_id=meta["match_id"], start=start, end=end,
                           hero=meta.get("hero", ""))])
        data = Group("match_window")
        # Пояснения внутри окна — свои: «остальной матч дан сводкой» здесь неправда,
        # сводки в уточнении нет вовсе, она осталась в первом промпте.
        data.add(s("sec.window", start=start, end=end),
                 self._window(f.window, s.overlay("followup.")))
        groups = [intro, data]
        if policy.has_note:
            note = Group("player_question")
            note.add(s("sec.note"), self._note(policy))
            groups.append(note)
        task = Group("task")
        task.add(s("followup.sec_task"),
                 [s("followup.task"), s("method.language", language=s("answer_language"))])
        groups.append(task)
        body = renderer_for(policy.model).document(groups)
        return f"{s('followup.title', match_id=meta['match_id'], start=start, end=end)}\n\n{body}"

    # --- общие помощники ------------------------------------------------------

    @staticmethod
    def _position(s: i18n.Strings, position_key: str, lane_key: str) -> str:
        if position_key in ("1", "2", "3", "4", "5"):
            return s(f"pos.{position_key}")
        return s(f"pos.{position_key}", lane=s(f"lane.{lane_key}"))

    # --- секции ---------------------------------------------------------------

    def _role(self, policy: Policy, s: i18n.Strings) -> List[str]:
        out = [s("header.role")]
        if policy.has_role:
            source = s(f"role.source.{policy.role_source}")
            out.append(s("header.role_profile", role=s(f"role.{policy.role}.name"),
                         source=source))
        if policy.has_note:
            # Указатель в самом начале: у игрока есть конкретный вопрос, он ниже.
            # Сам текст вопроса не дублируем, чтобы не размывать приоритет.
            out.append(s("header.note_pointer"))
        return out

    def _role_impact(self, r: Dict[str, Any], s: i18n.Strings) -> List[str]:
        role = r["role"]
        out = [
            s("role.impact.header", role=s(f"role.{role}.name"),
              source=s(f"role.source.{r['role_source']}")),
        ]
        metrics = []
        for metric in r["metrics"]:
            key, value = metric["key"], metric["value"]
            if value is None:
                value = "?"
            elif key == "kill_participation":
                value = f"{value}%"
            elif key == "stuns":
                value = s("role.metric.seconds", value=value)
            metrics.append(f"{s(f'role.metric.{key}')} {value}")
        if metrics:
            out.append("  " + " | ".join(metrics))

        if role == "1":
            late = ", ".join(r["late_death_times"]) or s("dash")
            out.append(s("role.late_deaths", times=late))
        if role == "2":
            early = ", ".join(r["early_kill_times"]) or s("dash")
            out.append(s("role.early_kills", times=early))

        for key, timings in (("key_items", r["key_items"]),
                             ("utility_items", r["utility_items"])):
            if not timings:
                continue
            listed = ", ".join(f"{x['time']} {x['item']}" for x in timings)
            out.append(s(f"role.{key}", items=listed))
        return out

    def _window(self, w: Dict[str, Any], s: i18n.Strings) -> List[str]:
        out = [s("window.note", start=w["start"], end=w["end"])]
        if w["empty"]:
            out.append(f"  {s('window.quiet')}")

        out += ["", s("window.team")]
        for t in w["team"]:
            out.append(f"  m{t['m']:>2}: " + s("nw.row", gold=_signed(t["gold"]),
                                               xp=_signed(t["xp"])))

        out += ["", s("window.series")]
        for row in w["series"]:
            points = ", ".join(
                "m{m}={nw}g/{xp}xp/{lh}-{dn}".format(**p) for p in row["rows"]
                if p["nw"] is not None or p["xp"] is not None)
            out.append(f"  {row['who']}: {points or s('dash')}")

        out += ["", s("window.kills")]
        out += [f"  " + s("window.kill_row", time=k["time"], killer=k["killer"],
                          victim=k["victim"]) for k in w["kills"]] or [f"  {s('dash')}"]

        out += ["", s("window.purchases")]
        out += [f"  {p['time']} {p['who']}: {p['item']}"
                for p in w["purchases"]] or [f"  {s('dash')}"]

        if w["fights"]:
            out += ["", s("window.fights")]
            for i, tf in enumerate(w["fights"], 1):
                me = tf["me"]
                mine = s("tf.me", damage=me["damage"], deaths=me["deaths"],
                         gold=_signed(me["gold_delta"]))
                if me["killed"]:
                    mine += ", " + s("tf.me_killed", heroes=", ".join(me["killed"]))
                out.append(s("tf.header", n=i, start=tf["start"], end=tf["end"], lane="",
                             score=s("tf.score", mine=tf["my_losses"],
                                     theirs=tf["enemy_losses"]),
                             verdict=s(tf["verdict"]), me=mine))
                out.append("    " + self._presence(tf["presence"], s))
                out.append("    " + s("tf.fallen",
                                      heroes=", ".join(tf["fallen"]) or s("dash")))
                for p in tf["participants"]:
                    out.append("    " + s("tf.detail", who=p["who"],
                                          gold=_signed(p["gold_delta"]),
                                          xp=_signed(p["xp_delta"]), deaths=p["deaths"],
                                          damage=p["damage"], healing=p["healing"]))

        if w["objectives"]:
            out += ["", s("window.objectives")]
            out += self._objectives(w["objectives"], s)
        return out

    @staticmethod
    def anomaly_text(key: str, params: Dict[str, Any], s: i18n.Strings) -> str:
        """Текст одного отклонения. Публичный: тем же кодом печатает профиль."""
        params = dict(params)
        # Метрики бенчмарков подписываются общим словарём bench.*: иначе одна и
        # та же метрика называлась бы в двух секциях по-разному.
        for src, dst in (("metric_key", "metric"), ("high_key", "high_metric"),
                         ("low_key", "low_metric")):
            if src in params:
                params[dst] = s(f"bench.{params.pop(src)}")
        return s(key, **params)

    def _anomalies(self, rows: List[Anomaly], s: i18n.Strings) -> List[str]:
        """Отклонения списком, каждое — с осью гипотезы в квадратных скобках.

        Пустой список тоже печатаем: «ничего необычного» — это факт, и без него
        модель начнёт додумывать аномалии, которых в данных нет.
        """
        if not rows:
            return [s("anom.intro"), f"  {s('anom.none')}"]

        out = [s("anom.intro")]
        for a in rows:
            out.append(f"  - [{s('anom.axis.' + a.axis)}] "
                       + self.anomaly_text(a.key, a.params, s))
        return out

    def _meta(self, m: Dict[str, Any], policy: Policy, s: i18n.Strings) -> List[str]:
        out = [
            s("meta.line", match_id=m["match_id"], patch=m["patch"], mode=m["mode"],
              lobby=m["lobby"], duration=m["duration"]),
            s("meta.date", date=m["date"] or "?"),
            s("meta.result", result=s("meta.win" if m["win"] else "meta.lose"),
              side=m["my_side"], winner=m["winner"]),
            s("meta.export", depth=policy.depth, focus=policy.focus,
              model=profile(policy.model).label),
        ]
        if not policy.whole_game:
            out.insert(3, s("meta.me", hero=m["hero"],
                            position=self._position(s, m["position_key"], m["lane_key"]),
                            level=m["level"], k=m["kills"], d=m["deaths"], a=m["assists"]))
        if policy.mmr:
            out.append(s("meta.level", mmr=policy.mmr))
        if policy.has_window:
            out.append(s("meta.window", start=policy.window[0], end=policy.window[1]))
        return out

    _RANKS = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon", 5: "Legend",
              6: "Ancient", 7: "Divine", 8: "Immortal"}

    def _facts(self, f: Dict[str, Any], s: i18n.Strings) -> List[str]:
        out = [s("facts.note")]

        rank = f.get("rank")
        rank_text = (f"{self._RANKS.get(rank // 10, '?')} {rank % 10 or ''}".strip()
                     if rank else s("facts.unknown"))
        party = f.get("party")
        party_text = (s("facts.solo") if party == 1 else
                      s("facts.party", n=party) if party else s("facts.unknown"))
        out.append(s("facts.player", rank=rank_text, party=party_text))
        out.append(s("facts.team", ours=f["kills"][0], theirs=f["kills"][1],
                     my=f["my_deaths"], team=f["team_deaths"],
                     nw=f["nw_share"], dmg=f["dmg_share"]))

        if f["pairs"]:
            out += ["", s("facts.pairs")]
            for pair in f["pairs"]:
                points = ", ".join(
                    f"{x['m']}' {_k(x['mine'])}/{_k(x['theirs'])}" for x in pair["earned"])
                out.append("  " + s("facts.pair_row", role=pair["role"], mine=pair["mine"],
                                    theirs=pair["theirs"], points=points or s("dash"),
                                    nw_mine=_k(pair["nw"][0]), nw_theirs=_k(pair["nw"][1])))

        if f["gold"]:
            out += ["", s("facts.gold")]
            for g in f["gold"]:
                rows = ", ".join(f"{s('facts.gold.' + r['key'])} {r['pct']}%" for r in g["rows"])
                out.append(f"  {g['who']} ({_k(g['total'])}): {rows}")

        out += ["", s("facts.deaths", n=len(f["deaths"]))]
        for d in f["deaths"]:
            where = s("facts.in_fight" if d["in_fight"] else "facts.pickoff")
            killer = d["killer"] or "?"
            dead = ", " + s("facts.dead_for", sec=d["dead_for"]) if d.get("dead_for") else ""
            out.append(f"  {d['time']} — {killer}, {where}{dead}")

        dt = f.get("damage_taken")
        if dt:
            types = ", ".join(f"{s('facts.dmg.' + k)} {v}%" for k, v in dt["by_type"].items())
            out += ["", s("facts.damage_taken", total=_k(dt["total"]), types=types,
                          through=dt["through_bkb"], blocked=dt["blocked_by_bkb"])]
            for src in dt["sources"]:
                name = s("facts.attacks") if src["attack"] else src["name"]
                mark = (s("facts.through_bkb") if src["through_bkb"] is True else
                        s("facts.blocked_bkb") if src["through_bkb"] is False else "")
                kind = s("facts.dmg." + src["type"])
                out.append(f"  {name}: {_k(src['value'])} ({kind}{', ' + mark if mark else ''})")
        return out

    def _game_facts(self, f: Dict[str, Any], s: i18n.Strings) -> List[str]:
        out = [s("facts.note"),
               s("game.facts.teams", rk=f["kills"][0], dk=f["kills"][1],
                 rnw=_k(f["nw"][0]), dnw=_k(f["nw"][1]))]
        if f["pairs"]:
            out += ["", s("facts.pairs")]
            for pair in f["pairs"]:
                points = ", ".join(
                    f"{x['m']}' {_k(x['mine'])}/{_k(x['theirs'])}" for x in pair["earned"])
                out.append("  " + s("facts.pair_row", role=pair["role"], mine=pair["mine"],
                                    theirs=pair["theirs"], points=points or s("dash"),
                                    nw_mine=_k(pair["nw"][0]), nw_theirs=_k(pair["nw"][1])))
        out += ["", s("game.facts.players", fights=f["fights_total"])]
        for p in f["players"]:
            gold = ", ".join(f"{s('facts.gold.' + r['key'])} {r['pct']}%" for r in p["gold"])
            out.append("  " + s("game.facts.player_row", who=p["who"], pos=p["position"],
                                nw=_k(p["nw"]), nw_share=p["nw_share"],
                                dmg_share=p["dmg_share"], towers=_k(p["tower_damage"]),
                                deaths=p["deaths"], fight_deaths=p["deaths_in_fights"],
                                fights=p["fights"], total=f["fights_total"], gold=gold))
        return out

    def _draft(self, d: Dict[str, Any], s: i18n.Strings) -> List[str]:
        out: List[str] = []
        if not d["rows"]:
            out.append(s("draft.no_stages"))
        elif d["chronological"]:
            out.append(s("draft.chronological", mode=d["mode"]))
            for r in d["rows"]:
                kind = s("draft.pick" if r["is_pick"] else "draft.ban")
                out.append(f"  #{r['order']:>2} {r['side']:<7} {kind:<3} {r['hero']}")
        else:
            out.append(s("draft.grouped", mode=d["mode"]))
            listed = ", ".join(f"{r['side'][0]}:{r['hero']}" for r in d["bans"]) or s("dash")
            out.append(f"  {s('draft.bans')}: {listed}")
            if d.get("phased"):
                # Фазы, а не сквозная очередь: внутри фазы соперник выбирает
                # вслепую, и «кто за кем» внутри неё ничего не значит.
                out.append(f"  {s('draft.phased_intro')}")
                def heroes(phase: int, side: str) -> str:
                    return ", ".join(r["hero"] for r in d["picks"]
                                     if r.get("phase") == phase and r["side"] == side) or s("dash")

                for phase in (1, 2, 3):
                    row = s("draft.phase_row", n=phase, radiant=heroes(phase, "Radiant"),
                            dire=heroes(phase, "Dire"))
                    out.append(f"    {row}")
            else:
                out.append(f"  {s('draft.picks_ordered')}")
                for n, r in enumerate(d["picks"], 1):
                    out.append(f"    #{n:>2} {r['side'][0]} {r['hero']}")

        out += self._my_pick(d.get("my_pick"), s)
        out += self._lanes(d.get("lanes") or [], s)

        for side, rows in (("Radiant", d["radiant"]), ("Dire", d["dire"])):
            out.append(f"{side}:")
            out += [f"  - {p['hero']} | {self._position(s, p['position_key'], p['lane_key'])}"
                    for p in rows]
        return out

    def _my_pick(self, my: Optional[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        """Во что я пикнулся: что было на экране, когда я подтверждал выбор."""
        if not my:
            return []
        if my["phased"]:
            out = ["", s("draft.my_pick_phased", phase=my["phase"], n=my["team_order"],
                         tag=s(f"draft.phase_tag.{my['phase']}"))]
            keys = ("enemies_visible", "allies_before", "enemies_blind", "enemies_after")
        else:
            out = ["", s("draft.my_pick", n=my["order"], total=my["total"],
                         tag=s("draft.pick_tag." + my["tag"]))]
            keys = ("enemies_before", "allies_before", "enemies_after")
        for key in keys:
            heroes = ", ".join(my[key]) or s("dash")
            out.append(f"  {s('draft.' + key, heroes=heroes)}")
        return out

    def _lanes(self, lanes: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        if not lanes:
            return []
        out = ["", s("draft.lanes")]
        for row in lanes:
            out.append("  " + s("draft.lane_row", lane=s(f"draft.lane.{row['lane']}"),
                                radiant=", ".join(row["radiant"]) or s("dash"),
                                dire=", ".join(row["dire"]) or s("dash")))
        return out

    def _scoreboard(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        out = [s("scoreboard.columns")]
        for r in rows:
            out.append(f"  {r['who']} | {r['lvl']} | {r['kda']} | {r['lh_dn']} | {r['gpm_xpm']} | "
                       f"{r['nw']} | {r['hd']} | {r['td']} | {r['heal']} | {r['dt']}")
        return out

    def _benchmarks(self, rows: List[Dict[str, Any]], policy: Policy,
                    s: i18n.Strings) -> List[str]:
        out = []
        for r in rows:
            if not r["rows"]:
                continue
            metrics = "; ".join(
                "{label} {raw} ({pct})".format(
                    label=s(f"bench.{x['metric']}"), raw=x["raw"],
                    pct=s("bench.percentile", pct=x["pct"]) if x["pct"] is not None else "?")
                for x in r["rows"])
            out.append(f"  {r['who']}: {metrics}")
        if not policy.at_least("benchmarks", EXPANDED):
            out.append(f"  {s('bench.more')}")
        return out

    def _networth(self, nw: Dict[str, Any], s: i18n.Strings) -> List[str]:
        out = [s("nw.note", step=nw["step"]), "", s("nw.team")]
        for t in nw["team"]:
            row = s("nw.row", gold=_signed(t["gold"]), xp=_signed(t["xp"]))
            out.append(f"  m{t['m']:>2}: {row}")

        out.append(s("nw.swings"))
        out += [f"  " + s("nw.swing_row", m=x["m"], text=s(x["key"]), gold=_signed(x["gold"]))
                for x in nw["swings"]] or [f"  {s('nw.no_swings')}"]

        if nw.get("peak"):
            best, worst = nw["peak"]["best"], nw["peak"]["worst"]
            out.append(s("nw.peak", best=_signed(best["gold"]), best_m=best["m"],
                         worst=_signed(worst["gold"]), worst_m=worst["m"]))

        out += ["", s("nw.curves")]
        for c in nw["curves"]:
            series = ", ".join(f"m{p['m']}={p['nw']}" for p in c["series"] if p["nw"] is not None)
            out.append(f"  {c['who']}: {series}")
        return out

    def _items(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        out = []
        for r in rows:
            timings = ", ".join(f"{t['time']} {t['item']}" for t in r["timings"]) or s("dash")
            out.append(f"  {r['who']} [{s('items.kind.' + r['kind'])}]: {timings}")
        return out

    def _abilities(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        out = []
        for r in rows:
            build = ", ".join(
                "#{n} {name}".format(
                    n=b["n"],
                    name=s("abilities.talent", name=b["name"]) if b["talent"] else b["name"])
                for b in r["build"]) or s("dash")
            out.append(f"  {r['who']}: {build}")
        return out

    def _laning(self, ln: Dict[str, Any], s: i18n.Strings) -> List[str]:
        eff = ln["me_eff_pct"] if ln["me_eff_pct"] is not None else "?"
        out = [s("laning.me", position=self._position(s, ln["position_key"], ln["lane_key"]),
                 eff=eff)]

        out.append(s("laning.cs"))
        out.append("  " + ", ".join(f"m{c['min']}:{c['lh']}/{c['dn']}" for c in ln["cs_by_min"]))

        if ln["my_gold_xp"]:
            out.append(s("laning.gold_xp"))
            out.append("  " + ", ".join(f"m{c['min']}:{c['gold']}g/{c['xp']}xp"
                                        for c in ln["my_gold_xp"]))

        if ln["opponents"]:
            out.append(s("laning.opponents"))
            for o in ln["opponents"]:
                line = "  " + s("laning.opponent", who=o["who"],
                                position=self._position(s, o["position_key"], o["lane_key"]),
                                eff=o["eff_pct"] if o["eff_pct"] is not None else "?")
                if ln["detailed"]:
                    line += "\n    " + s("laning.opponent_cs") + ", ".join(
                        f"m{c['min']}:{c['lh']}/{c['dn']}" for c in o["cs_by_min"])
                out.append(line)

        out.append(s("laning.my_kills"))
        out += [f"  " + s("laning.killed", time=k["time"], victim=k["victim"])
                for k in ln["my_kills"]] or [f"  {s('dash')}"]
        out.append(s("laning.my_deaths"))
        out += [f"  " + s("laning.died", time=d["time"], killer=d["killer"])
                for d in ln["my_deaths"]] or [f"  {s('dash')}"]

        if ln["lane_efficiency_all"]:
            out.append(s("laning.eff_all"))
            out.append("  " + ", ".join(f"{e['who']}={e['eff_pct']}%"
                                        for e in ln["lane_efficiency_all"]))
        return out

    def _combat(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        out = []
        for r in rows:
            line = "  {who}: {body}".format(who=r["who"], body=s(
                "combat.row", streak=r["best_streak"], multi=r["best_multikill"],
                stuns=r["stuns_sec"], camps=r["camps_stacked"], runes=r["runes"],
                obs=r["obs"], sen=r["sen"], buybacks=r["buybacks"], dead=r["time_dead"]))

            killed = ", ".join(f"{s('kills.' + name)}:{val}"
                               for name, val in r["kills_by_type"].items() if val)
            if killed:
                line += " | " + s("combat.killed", items=killed)

            extra = r.get("extra") or {}
            if extra:
                bits = [s("combat.apm", apm=extra["apm"]), s("combat.pings", pings=extra["pings"])]
                if extra.get("max_hero_hit"):
                    bits.append(s("combat.max_hit", value=extra["max_hero_hit"]))
                line += " | " + ", ".join(bits)
            out.append(line)
        return out

    def _buffs(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        out = []
        for r in rows:
            buffs = ", ".join(
                f"{x['name']} ×{x['stacks']}"
                + (" " + s("buffs.since", time=x["since"]) if x["since"] else "")
                for x in r["buffs"])
            out.append(f"  {r['who']}: {buffs}")
        return out

    def _teamfights(self, tfs: List[Dict[str, Any]], policy: Policy,
                    s: i18n.Strings) -> List[str]:
        if not tfs:
            return [f"  {s('tf.none')}"]

        detailed = policy.at_least("teamfights", EXPANDED)
        out = []
        for i, tf in enumerate(tfs, 1):
            me = tf["me"]
            mine = s("tf.me", damage=me["damage"], deaths=me["deaths"],
                     gold=_signed(me["gold_delta"]))
            if me["killed"]:
                mine += ", " + s("tf.me_killed", heroes=", ".join(me["killed"]))

            out.append(s("tf.header", n=i, start=tf["start"], end=tf["end"],
                         lane=s("tf.lane_tag") if tf["in_lane"] else "",
                         score=s("tf.score", mine=tf["my_losses"], theirs=tf["enemy_losses"]),
                         verdict=s(tf["verdict"]), me=mine))
            out.append("    " + self._presence(tf["presence"], s))

            if tf["fallen"] or detailed:
                out.append("    " + s("tf.fallen",
                                      heroes=", ".join(tf["fallen"]) or s("dash")))
            for p in tf["participants"]:
                out.append("    " + s("tf.detail", who=p["who"], gold=_signed(p["gold_delta"]),
                                      xp=_signed(p["xp_delta"]), deaths=p["deaths"],
                                      damage=p["damage"], healing=p["healing"]))
        if not detailed:
            out.append(f"  {s('tf.more')}")
        return out

    def _presence(self, pr: Dict[str, Any], s: i18n.Strings) -> str:
        line = s("tf.presence", mine=pr["mine"], theirs=pr["theirs"])
        if pr["absent_mine"]:
            line += "; " + s("tf.absent_mine", heroes=", ".join(pr["absent_mine"]))
        if pr["absent_theirs"]:
            line += "; " + s("tf.absent_theirs", heroes=", ".join(pr["absent_theirs"]))
        return line

    def _damage(self, rows: List[Dict[str, Any]]) -> List[str]:
        out = []
        for r in rows:
            if not r["targets"]:
                continue
            targets = ", ".join(f"{x['hero']}:{x['dmg']}" for x in r["targets"])
            out.append(f"  {r['who']}: {targets}")
        return out

    def _objectives(self, objs: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        return [f"  {o['time']} {self._objective_text(o, s)}" for o in objs]

    @staticmethod
    def _objective_text(o: Dict[str, Any], s: i18n.Strings) -> str:
        kind, p = o["kind"], o.get("params") or {}
        if kind == "building":
            if p.get("hero"):
                by = s("obj.by_hero", hero=p["hero"])
            elif p.get("by_creeps"):
                by = s("obj.by_creeps")
            else:
                by = ""
            return s("obj.building", attacker=p["attacker"], victim=p["victim"],
                     kind=s(f"obj.{p['building']}"), short=p["short"], by=by)
        if kind in ("roshan", "tormentor", "courier"):
            return s(f"obj.{kind}", team=p.get("team", "?"))
        return s(f"obj.{kind}")

    def _limitations(self, features: Features, s: i18n.Strings) -> List[str]:
        out = [s("limit.granularity"), s("limit.positions"), s("limit.hp"), s("limit.roles")]
        out += [s(key, **params) for key, params in features.caveats]
        if not features.meta.get("parsed"):
            out.append(s("limit.unparsed"))
        return out

    @staticmethod
    def _note(policy: Policy) -> List[str]:
        # В markdown вопрос нужно выделить визуально, иначе он теряется среди
        # заголовков. В XML границу уже задаёт тег — рамка была бы лишним шумом.
        framed = profile(policy.model).wrapper != "xml"
        body = [f"  {line.strip()}" if line.strip() else ""
                for line in (policy.note or "").splitlines()]
        if not framed:
            return [line.strip() for line in body]
        rule = "=" * 74
        return [rule, *body, rule]


class ProfileBundleBuilder:
    """ProfileFeatures -> текст мульти-матчевого промпта.

    Отдельный класс, а не режим BundleBuilder: секции здесь другие (средние,
    тренды, паттерны, стадии), и попытка обслужить оба случая одним набором
    методов быстро превратилась бы в ветвления «если профиль» на каждом шаге.

    Общее переиспользуется: упаковка под модель (render), словари (i18n), текст
    отклонений (BundleBuilder.anomaly_text) и правило «своих текстов у модуля нет».
    """

    def build(self, features: "ProfileFeatures", policy: Policy) -> str:
        s = i18n.load(policy.lang)

        data = Group("profile_data")
        data.add(s("sec.profile_meta"), self._meta(features, policy, s))
        data.add(s("sec.profile_averages"), self._averages(features, s))
        if features.trends:
            data.add(s("sec.profile_trends"), self._trends(features.trends, s))
        data.add(s("sec.profile_patterns"), self._patterns(features.patterns, s))
        if features.stages:
            data.add(s("sec.profile_stages"), self._stages(features.stages, s))
        if features.heroes:
            data.add(s("sec.profile_heroes"), self._heroes(features.heroes, s))
        data.add(s("sec.profile_matches"), self._matches(features.digests, s))

        groups = [Group("role", [Section(None, self._role(features, policy, s))]), data]

        limits = Group("data_limitations")
        limits.add(s("sec.limits"), [s(key, **params) for key, params in features.caveats])
        groups.append(limits)

        if policy.has_note:
            note = Group("player_question")
            note.add(s("sec.note"), BundleBuilder._note(policy))
            groups.append(note)

        method = Group("method")
        method.add(s("sec.method"),
                   scaffold.profile_method_lines(policy, features.analyzed, s))
        groups.append(method)

        answer = Group("output_format")
        answer.add(s("sec.format"), scaffold.profile_format_lines(policy, s))
        groups.append(answer)

        body = renderer_for(policy.model).document(groups)
        return f"{s('profile.header.title')}\n\n{body}"

    # --- секции ---------------------------------------------------------------

    def _role(self, features: "ProfileFeatures", policy: Policy,
              s: i18n.Strings) -> List[str]:
        out = [s("profile.header.role", matches=features.analyzed)]
        if policy.has_role:
            out.append(s("header.role_profile", role=s(f"role.{policy.role}.name"),
                         source=s(f"role.source.{policy.role_source}")))
        if policy.has_note:
            out.append(s("header.note_pointer"))
        return out

    def _meta(self, f: "ProfileFeatures", policy: Policy, s: i18n.Strings) -> List[str]:
        out = [s("profile.meta.line", account_id=f.account_id, analyzed=f.analyzed,
                 requested=f.requested)]
        filters = []
        if f.hero_filter:
            filters.append(s("profile.meta.filter_hero", hero=f.hero_filter))
        if f.role_filter:
            filters.append(s("profile.meta.filter_role",
                             role=s(f"role.{f.role_filter}.name")))
        out.append(s("profile.meta.filters",
                     filters="; ".join(filters) if filters else s("profile.meta.no_filters")))
        out.append(s("meta.export", depth=policy.depth, focus=policy.focus,
                     model=profile(policy.model).label))
        if policy.mmr:
            out.append(s("meta.level", mmr=policy.mmr))
        return out

    def _averages(self, f: "ProfileFeatures", s: i18n.Strings) -> List[str]:
        a = f.averages
        dash = s("dash")
        out = [
            s("profile.avg.result", wins=a["wins"], losses=a["losses"],
              winrate=a["winrate"], duration=a["duration"]),
            s("profile.avg.econ", gpm=a["gpm"] or dash, xpm=a["xpm"] or dash,
              cs10=a["cs10"] if a["cs10"] is not None else dash,
              nw=a["net_worth"] or dash),
            s("profile.avg.fight", kills=a["kills"], deaths=a["deaths"],
              assists=a["assists"], kp=a["kill_participation"],
              worst=a["deaths_max"] if a["deaths_max"] is not None else dash),
        ]
        if a["lane_eff"] is not None:
            out.append(s("profile.avg.lane", eff=a["lane_eff"]))
        return out

    def _trends(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        out = [s("profile.trends.note")]
        for r in rows:
            out.append("  " + s("profile.trends.row",
                                metric=s(f"bench.{r['metric']}"), avg=r["avg"],
                                low=r["low"], high=r["high"], samples=r["samples"],
                                direction=s(f"profile.trend.{r['direction']}",
                                            delta=r["delta"])))
        return out

    def _patterns(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        if not rows:
            return [s("profile.patterns.note"), f"  {s('profile.patterns.none')}"]

        out = [s("profile.patterns.note")]
        for r in rows:
            # Короткая подпись обязательна: без неё строка начинается со счётчика
            # («в 5 из 5 матчей»), и что именно повторилось, читателю неясно.
            out.append("  - [{axis}] {label} — {head}".format(
                axis=s("anom.axis." + r["axis"]),
                label=s("anom.short." + r["key"].split(".", 1)[1]),
                head=s("profile.patterns.row", count=r["count"], total=r["total"],
                       share=r["share"])))
            for example in r["examples"]:
                out.append("      " + s("profile.patterns.example",
                                        text=BundleBuilder.anomaly_text(r["key"],
                                                                        example, s)))
        return out

    def _stages(self, st: Dict[str, Any], s: i18n.Strings) -> List[str]:
        out = [s("profile.stages.note", step=st["step"])]
        for r in st["rows"]:
            out.append("  " + s("profile.stages.row", start=r["start"], end=r["end"],
                                change=_signed(r["change"]), samples=r["samples"]))
        if st.get("thin"):
            # Поминутных данных хватило на один матч — это не система, и делать
            # вид, что «стабильно проседаешь тут», было бы прямым вымыслом.
            out.append(s("profile.stages.thin", coverage=st["coverage"]))
            return out
        if st["weak"]:
            listed = ", ".join(f"{r['start']}–{r['end']}" for r in st["weak"])
            out.append(s("profile.stages.weak", stages=listed))
        else:
            out.append(s("profile.stages.no_weak"))
        if st["strong"]:
            out.append(s("profile.stages.strong", start=st["strong"]["start"],
                         end=st["strong"]["end"], change=_signed(st["strong"]["change"])))
        return out

    def _heroes(self, rows: List[Dict[str, Any]], s: i18n.Strings) -> List[str]:
        listed = ", ".join(s("profile.heroes.row", hero=r["hero"], games=r["games"],
                             wins=r["wins"]) for r in rows)
        return [s("profile.heroes.note"), f"  {listed}"]

    def _matches(self, digests: List["MatchDigest"], s: i18n.Strings) -> List[str]:
        out = [s("profile.matches.note"), s("profile.matches.columns")]
        for d in digests:
            axes = ", ".join(s("anom.axis." + a) for a in d.axes) or s("dash")
            out.append("  " + s("profile.matches.row",
                                match_id=d.match_id, hero=d.hero,
                                result=s("meta.win" if d.win else "meta.lose"),
                                duration=d.duration, kda=d.kda, gpm=d.gpm,
                                cs10=d.cs10 if d.cs10 is not None else s("dash"),
                                kp=d.kill_participation, axes=axes))
        return out
