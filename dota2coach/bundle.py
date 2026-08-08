"""BundleBuilder — превращает Features в текстовый промпт.

Разделение обязанностей:
  * Policy   — какие данные показать (тиры, глубина, фокус);
  * i18n     — на каком языке их подписать;
  * scaffold — по какой методике модель должна готовить разбор;
  * render   — во что это упаковать (markdown или XML-теги под Claude);
  * bundle   — собрать всё вместе, ничего не решая самостоятельно.

Своих текстов у модуля нет: каждая подпись приходит из словаря по ключу.
"""

from typing import Any, Dict, List, Optional

from . import i18n, scaffold
from .features import Features
from .policy import EXPANDED, Policy
from .render import Group, Section, profile, renderer_for


def _signed(value: Any) -> str:
    if value is None:
        return "?"
    return f"+{value}" if value > 0 else str(value)


class BundleBuilder:
    def build(self, features: Features, policy: Policy) -> str:
        s = i18n.load(policy.lang)

        data = Group("match_data")
        data.add(s("sec.meta"), self._meta(features.meta, policy, s))
        if features.role_impact:
            data.add(s("sec.role_impact"), self._role_impact(features.role_impact, s))
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
        method.add(s("sec.method"), scaffold.method_lines(policy, s))
        groups.append(method)

        answer = Group("output_format")
        answer.add(s("sec.format"), scaffold.format_lines(policy, s))
        groups.append(answer)

        body = renderer_for(policy.model).document(groups)
        return f"{s('header.title')}\n\n{body}"

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

    def _meta(self, m: Dict[str, Any], policy: Policy, s: i18n.Strings) -> List[str]:
        out = [
            s("meta.line", match_id=m["match_id"], patch=m["patch"], mode=m["mode"],
              lobby=m["lobby"], duration=m["duration"]),
            s("meta.result", result=s("meta.win" if m["win"] else "meta.lose"),
              side=m["my_side"], winner=m["winner"]),
            s("meta.me", hero=m["hero"],
              position=self._position(s, m["position_key"], m["lane_key"]),
              level=m["level"], k=m["kills"], d=m["deaths"], a=m["assists"]),
            s("meta.export", depth=policy.depth, focus=policy.focus,
              model=profile(policy.model).label),
        ]
        if policy.mmr:
            out.append(s("meta.level", mmr=policy.mmr))
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
            for label, rows in ((s("draft.bans"), d["bans"]), (s("draft.picks"), d["picks"])):
                listed = ", ".join(f"{r['side'][0]}:{r['hero']}" for r in rows) or s("dash")
                out.append(f"  {label}: {listed}")

        for side, rows in (("Radiant", d["radiant"]), ("Dire", d["dire"])):
            out.append(f"{side}:")
            out += [f"  - {p['hero']} | {self._position(s, p['position_key'], p['lane_key'])}"
                    for p in rows]
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
