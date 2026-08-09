"""English texts. Keys mirror ru.py — run the self-test after adding new ones."""

PROMPT = {
    "answer_language": "English",
    "dash": "—",

    "header.title": "=== DOTA 2 MATCH REVIEW REQUEST ===",
    "header.role":
        "You are an experienced personal Dota 2 coach. Below are structured FACTS from one "
        "of my matches, taken from OpenDota (my player is marked ★; [R]=Radiant, [D]=Dire). "
        "Rely ONLY on these facts; if something is missing, say so instead of inventing it.",
    "header.note_pointer":
        "IMPORTANT: there is a \"PLAYER'S MAIN QUESTION\" block below — start the review with it.",
    "header.role_profile": "Evaluate my player as {role} ({source}).",

    "sec.meta": "META",
    "meta.line": "Match {match_id} | patch {patch} | {mode} / {lobby} | duration {duration}",
    "meta.result": "Result: {result} (my side — {side}, winner — {winner})",
    "meta.win": "WIN",
    "meta.lose": "LOSS",
    "meta.me": "Me: {hero} | {position} | lvl {level} | KDA {k}/{d}/{a}",
    "meta.export": "Export mode: depth={depth}, focus={focus}, model={model}",
    "meta.level": "My skill level: {mmr}",
    "meta.window":
        "Requested analysis window: {start}–{end} min (see its own section; the rest of "
        "the match is given as a summary).",

    "sec.window": "WINDOW {start}–{end} MIN — MAXIMUM DETAIL",
    "window.note":
        "I asked to look at the {start}–{end} min stretch under a magnifier: below are the "
        "actions of ALL heroes inside that window, undecimated. The rest of the match is "
        "deliberately given as a summary in this prompt — lean on the window and use the "
        "rest as background.",
    "window.quiet":
        "(no kills, purchases, fights or objectives recorded inside this window — that is "
        "a fact too: the stretch was empty)",
    "window.team": "My team's advantage, per minute of the window:",
    "window.series": "All players per minute (net worth / xp / last hits-denies):",
    "window.kills": "Kills inside the window:",
    "window.kill_row": "{time} {killer} killed {victim}",
    "window.purchases":
        "Purchases inside the window (consumables included — they show who was preparing "
        "for a fight):",
    "window.fights": "Fights overlapping the window (player by player):",
    "window.objectives": "Objectives inside the window:",

    "sec.role_impact": "ROLE-SPECIFIC METRICS ★",
    "role.1.name": "Pos 1 Carry",
    "role.2.name": "Pos 2 Mid",
    "role.3.name": "Pos 3 Offlane",
    "role.4.name": "Pos 4 Soft Support",
    "role.5.name": "Pos 5 Hard Support",
    "role.source.selected": "player-selected; overrides the heuristic",
    "role.source.heuristic": "lane/net-worth heuristic",
    "role.source.auto": "auto",
    "role.impact.header": "{role}; role source: {source}.",
    "role.metric.cs10": "CS@10",
    "role.metric.gpm": "GPM",
    "role.metric.xpm": "XPM",
    "role.metric.networth": "final net worth",
    "role.metric.hero_damage": "hero damage",
    "role.metric.damage_taken": "damage taken",
    "role.metric.kill_participation": "kill participation",
    "role.metric.early_kills": "kills by 15:00",
    "role.metric.runes": "runes picked up",
    "role.metric.stuns": "control",
    "role.metric.fight_involvement": "major fights involved in",
    "role.metric.fight_deaths": "deaths in major fights",
    "role.metric.assists": "assists",
    "role.metric.camps_stacked": "camps stacked",
    "role.metric.creeps_stacked": "creeps stacked",
    "role.metric.wards": "wards obs/sen",
    "role.metric.dewards": "wards destroyed",
    "role.metric.healing": "healing",
    "role.metric.seconds": "{value}s",
    "role.late_deaths": "Deaths after 40:00 (especially costly for a carry): {times}",
    "role.early_kills": "Kill timings by 15:00 as the available early-tempo signal: {times}",
    "role.key_items": "Key power-spike items: {items}",
    "role.utility_items": "Team/utility items: {items}",

    "profile.header.title": "=== DOTA 2 PLAYER PROFILE ANALYSIS REQUEST ===",
    "profile.header.role":
        "You are an experienced personal Dota 2 coach. Below is an AGGREGATED digest of my "
        "{matches} most recent matches: averages, trends, repeating deviations and a "
        "one-line summary per match. Full match data is deliberately NOT here. Your job is "
        "to find what REPEATS, not to break down a single game. Rely only on these facts.",

    "sec.profile_meta": "SAMPLE",
    "profile.meta.line":
        "Player {account_id} | matches analyzed: {analyzed} of {requested} requested",
    "profile.meta.filters": "Filters: {filters}",
    "profile.meta.no_filters": "none (most recent matches as they are)",
    "profile.meta.filter_hero": "hero — {hero}",
    "profile.meta.filter_role": "position — {role}",

    "sec.profile_averages": "SAMPLE AVERAGES",
    "profile.avg.result":
        "Result: {wins} wins / {losses} losses ({winrate}% win rate), average duration "
        "{duration}",
    "profile.avg.econ": "Economy: GPM {gpm} | XPM {xpm} | CS@10 {cs10} | net worth {nw}",
    "profile.avg.fight":
        "Fights: KDA {kills}/{deaths}/{assists} | kill participation {kp}% | worst match by "
        "deaths: {worst}",
    "profile.avg.lane": "Average lane efficiency: {eff}%",

    "sec.profile_trends": "PERCENTILE TRENDS (compared to typical results on these heroes)",
    "profile.trends.note":
        "Average percentile across the sample, its spread and the direction (recent matches "
        "against older ones). Per-match percentiles are not listed: on a sample this size "
        "the dynamics matter, not individual points.",
    "profile.trends.row":
        "{metric}: {avg} on average (from {low} to {high}, sample {samples}) — {direction}",
    "profile.trend.up": "{delta} points higher in recent matches",
    "profile.trend.down": "{delta} points lower in recent matches",
    "profile.trend.flat": "no pronounced dynamics",

    "sec.profile_patterns": "REPEATING DEVIATIONS",
    "profile.patterns.note":
        "Deviations found in individual matches that repeated across a significant share of "
        "the sample. One-off deviations are excluded — they are noise, not a habit. This is "
        "the main material for the analysis: what repeats is what can be fixed.",
    "profile.patterns.none":
        "— (no deviation repeated across a significant share of matches; look for causes in "
        "the averages and stages below, but do not invent a pattern where there is none)",
    "profile.patterns.row": "in {count} of {total} matches ({share}%)",
    "profile.patterns.example": "e.g.: {text}",

    "sec.profile_stages": "PROFILE BY GAME STAGE",
    "profile.stages.note":
        "Average CHANGE in my team's gold advantage per {step} min, averaged across the "
        "sample (>0 — we gain on that stretch, <0 — we lose). The change is used rather than "
        "the level: the level carries over from earlier stages and would blur the picture.",
    "profile.stages.row": "{start}–{end} min: {change} gold (sample {samples})",
    "profile.stages.thin":
        "Per-minute series exist for only {coverage} match(es) in the sample — too few "
        "to speak of a system. Read the table above as a single observation rather than "
        "a regularity, and do not conclude \"I consistently sag here\" from it.",
    "profile.stages.weak": "Systematically sagging stretches: {stages} min.",
    "profile.stages.no_weak":
        "No stretch loses the advantage systematically — look for causes outside the stages.",
    "profile.stages.strong": "Strongest stretch: {start}–{end} min ({change} gold).",

    "sec.profile_heroes": "SAMPLE COMPOSITION BY HERO",
    "profile.heroes.note":
        "Without this the averages cannot be read honestly: different heroes have different "
        "norms.",
    "profile.heroes.row": "{hero} ×{games} (wins {wins})",

    "sec.profile_matches": "MATCHES IN THE SAMPLE (one line each)",
    "profile.matches.note":
        "Most recent first. One line per match — enough to point at a specific game; full "
        "data for it is not here.",
    "profile.matches.columns":
        "  match_id | hero | result | duration | K/D/A | GPM | CS@10 | participation | deviation axes",
    "profile.matches.row":
        "{match_id} | {hero} | {result} | {duration} | {kda} | {gpm} | {cs10} | {kp}% | {axes}",

    "caveat.profile_aggregated":
        "- This is an AGGREGATE over {analyzed} matches, not full data. Per-minute series, "
        "fight logs and item timings are not here. If a conclusion needs a specific match, "
        "name its match_id and say it should be analyzed separately.",
    "caveat.profile_short":
        "- {requested} matches were requested, {analyzed} were analyzed: some matches are "
        "unavailable (private profile, expired replay or a filter mismatch).",
    "caveat.profile_unparsed":
        "- Matches without full parsing: {count}. They have no percentiles, per-minute "
        "series or timings, so they contribute only partially to averages and trends.",
    "caveat.profile_mixed_roles":
        "- Positions in the sample: {count}. The averages mix different duties — keep that "
        "in mind and do not compare core and support metrics directly.",
    "caveat.profile_patches":
        "- The sample spans several patches ({patches}). Some differences may come from "
        "balance changes rather than from play.",

    "profile.method.intro":
        "Rules for analysing the profile ({matches} matches), all mandatory:",
    "profile.method.repeating":
        "Analyse what REPEATS, not an individual match. A single event is not a pattern, "
        "however striking it is. Lean primarily on the repeating-deviations block and on the "
        "game stages.",
    "profile.method.sample":
        "The sample is {matches} matches. That is small for statistics: do not present an "
        "observation as a law. If a conclusion rests on two or three matches, say so plainly "
        "and suggest how many games are needed to verify it.",
    "profile.method.no_raw":
        "Full match data is not in this prompt. Do not invent timings, per-minute values or "
        "fight details: there is nowhere here to get them. If they are needed — name the "
        "match_id and ask for that match to be analyzed separately.",

    "profile.format.intro": "Follow this order and these section headings:",
    "profile.format.p0.title": "0. Answer to the main request",
    "profile.format.p0.body":
        "A direct answer to the player's question from the sample data. If the aggregates "
        "are not enough for a full answer, say what exactly is missing and which match to "
        "analyze separately.",
    "profile.format.p1.title": "1. Portrait of the player from this sample",
    "profile.format.p1.body":
        "3–4 lines of connected prose: what kind of player these matches show, and the ONE "
        "main thing that holds them back most often. No bullet list.",
    "profile.format.p2.title": "2. What works consistently",
    "profile.format.p2.body":
        "1–2 strengths visible across the sample rather than in a single match — with "
        "numbers. The player must know what to keep doing.",
    "profile.format.p3.title": "3. The main repeating leak",
    "profile.format.p3.body":
        "One most expensive habit. Mandatory: in how many matches it appeared, numbers from "
        "the deviations block, and the mechanism — why it costs so much. Do not dump "
        "everything here: there is one leak.",
    "profile.format.p4.title": "4. Where the game breaks in time",
    "profile.format.p4.body":
        "Analysis by stage: on which stretches the advantage is lost systematically and what "
        "happens in the game at that time. If no stretch sags — say so and explain where the "
        "games are lost instead.",
    "profile.format.p5.title": "5. Plan for the next matches",
    "profile.format.p5.body":
        "2–4 measurable goals with checkable numbers and how many matches are needed to see "
        "a shift. Bad: \"play more actively\". Good: \"CS@10 ≥ 45 in three matches in a "
        "row\". The goals must hit the leak from section 3, not be a generic list.",
    "profile.format.p6.title": "6. Hypotheses: what is behind these patterns",
    "profile.format.p6.body":
        "2–3 COMPETING explanations for the repeating problems, from different areas: hero "
        "choice and draft, build habits, behaviour in fights, farm time management, "
        "positioning. For each: evidence from the sample, what would confirm or refute it, "
        "and how confident you are.",
    "profile.format.p7.title": "7. Questions for me",
    "profile.format.p7.body":
        "2–3 short diagnostic questions that would narrow things down: about intent, the "
        "plan for the game, party composition, a change of role or patch — that is, about "
        "what is NOT in the aggregates. You may also ask for a specific match_id from the "
        "sample to be analyzed, explaining why that one.",

    "sec.anomalies": "STATISTICALLY UNUSUAL IN THE DATA",
    "anom.intro":
        "Deviations found by automatically comparing this match against hero percentiles, "
        "against my own build pace and against the other players. This is RAW MATERIAL for "
        "hypotheses, not conclusions: each deviation may have several explanations, "
        "including a harmless one. In square brackets — the axis it belongs to.",
    "anom.none":
        "— (no notable deviations found; build hypotheses from the match data above and do "
        "not invent anomalies that are not listed here)",
    "anom.short.item_lag": "item lags behind the build pace",
    "anom.short.bench_low": "percentile at the bottom of the distribution",
    "anom.short.bench_high": "percentile at the top of the distribution",
    "anom.short.bench_spread": "gap between metrics",
    "anom.short.farm_stall": "income dip",
    "anom.short.death_cluster": "deaths bunched into one episode",
    "anom.short.dead_share": "a lot of time spent dead",
    "anom.short.lane_gap_behind": "behind in the lane",
    "anom.short.lane_gap_ahead": "ahead in the lane",
    "anom.short.kp_low": "low kill participation",
    "anom.short.kp_high": "high kill participation",
    "anom.short.gold_collapse": "fast swing of the lead",
    "anom.axis.draft": "draft",
    "anom.axis.build": "build",
    "anom.axis.farm": "farm",
    "anom.axis.fights": "fights",
    "anom.axis.position": "positioning",
    "anom.axis.lane": "lane",
    "anom.item_lag":
        "{item} completed at {at} — roughly {excess} min later than my income ({gpm} GPM) "
        "and the pace of the rest of my build imply (about {expected} was expected). The "
        "comparison is against my own build, so consumables and wards do not skew it.",
    "anom.bench_low": "{metric}: percentile {pct} — bottom of the distribution for this hero.",
    "anom.bench_high": "{metric}: percentile {pct} — top of the distribution for this hero.",
    "anom.bench_spread":
        "Gap between metrics: {high_metric} is at percentile {high}, while {low_metric} is "
        "only at {low}. One direction is pulled much further than the other.",
    "anom.farm_stall":
        "Income dip over m{start}–m{end}: about {rate} gold per minute against my match "
        "average of {average}.",
    "anom.death_cluster":
        "{count} of my {total} deaths fall inside {start}–{end} — that is one episode, not "
        "scattered trades.",
    "anom.dead_share":
        "Time spent dead: {dead} — {pct}% of match duration, against {typical} for a "
        "typical player in this match.",
    "anom.lane_gap_behind":
        "Lane efficiency {mine}% against {theirs}% for my lane opponents — {gap} points "
        "behind.",
    "anom.lane_gap_ahead":
        "Lane efficiency {mine}% against {theirs}% for my lane opponents — {gap} points "
        "ahead.",
    "anom.kp_low":
        "Kill participation {pct}% ({kills}+{assists} of {team_kills} team kills) — low: a "
        "significant part of the fights happened without me.",
    "anom.kp_high":
        "Kill participation {pct}% ({kills}+{assists} of {team_kills} team kills) — nearly "
        "every team fight involved me.",
    "anom.gold_collapse":
        "Fastest swing of the lead: between m{start} and m{end} my team lost {gold} gold of "
        "relative advantage.",

    "sec.draft": "DRAFT",
    "draft.no_stages":
        "OpenDota does not expose draft stages (picks/bans) for this mode. Final line-ups:",
    "draft.chronological": "Draft order ({mode}), chronological:",
    "draft.grouped":
        "Draft ({mode}). The source returns picks and bans as separate groups — "
        "the true order between them is unknown.",
    "draft.bans": "Bans",
    "draft.picks": "Picks",
    "draft.pick": "pick",
    "draft.ban": "BAN",

    "sec.scoreboard": "SCOREBOARD (final)",
    "scoreboard.columns":
        "hero | lvl | K/D/A | LH/DN | GPM/XPM | net worth | hero dmg | building dmg | "
        "healing | damage taken",

    "sec.benchmarks": "BENCHMARKS (vs typical values on this hero; percentile 0–100)",
    "bench.more": "(benchmarks for the other players — in --depth deep)",
    "bench.percentile": "percentile {pct}",
    "bench.gold_per_min": "GPM",
    "bench.xp_per_min": "XPM",
    "bench.kills_per_min": "kills/min",
    "bench.last_hits_per_min": "last hits/min",
    "bench.hero_damage_per_min": "hero damage/min",
    "bench.hero_healing_per_min": "healing/min",
    "bench.tower_damage": "building damage",
    "bench.stuns_per_min": "stun/min",

    "sec.networth": "ECONOMY: TEAM ADVANTAGE AND NET WORTH CURVES",
    "nw.note":
        "Points every {step} min plus the final minute; swings are listed separately. "
        "Source granularity is 1 point per minute (OpenDota's maximum).",
    "nw.team": "My team's advantage (>0 — we are ahead), gold / xp:",
    "nw.row": "gold {gold}, xp {xp}",
    "nw.swings": "Swings (minutes where the gold advantage changed sign):",
    "nw.swing_ahead": "my team took the lead",
    "nw.swing_behind": "the lead went to the opponents",
    "nw.no_swings": "— (the advantage never changed sign)",
    "nw.swing_row": "m{m}: {text} ({gold} gold)",
    "nw.peak": "Peak: {best} at m{best_m}; low: {worst} at m{worst_m}",
    "nw.curves": "Net worth curves:",

    "sec.items": "ITEMS AND TIMINGS (assembled items; components and consumables hidden)",
    "items.kind.key": "key items",
    "items.kind.major": "major items",
    "items.kind.full": "full purchase log",

    "sec.abilities": "ABILITY BUILD (#N is the upgrade order, not the hero level)",
    "abilities.talent": "talent: {name}",

    "sec.laning": "LANING 0–10",
    "laning.me": "My lane/role: {position} | lane efficiency: {eff}%",
    "laning.cs": "My last hits/denies per minute:",
    "laning.gold_xp": "My gold/xp per minute:",
    "laning.opponents": "My lane opponents:",
    "laning.opponent": "{who} | {position} | lane efficiency {eff}%",
    "laning.opponent_cs": "last hits/denies: ",
    "laning.my_kills": "My kills during laning:",
    "laning.my_deaths": "My deaths during laning:",
    "laning.killed": "{time} killed {victim}",
    "laning.died": "{time} died to {killer}",
    "laning.eff_all": "Lane efficiency of everyone (to compare lanes):",

    "sec.combat": "COMBAT AND ECONOMY (extra counters)",
    "combat.row":
        "best streak {streak}, multi-kill x{multi}, stuns {stuns}s, camps stacked {camps}, "
        "runes {runes}, wards {obs}obs/{sen}sen, buybacks {buybacks}, time dead {dead}",
    "combat.killed": "killed: {items}",
    "combat.apm": "APM {apm}",
    "combat.pings": "pings {pings}",
    "combat.max_hit": "max_hero_hit (largest single hit on a hero) {value}",
    "kills.neutrals": "neutrals",
    "kills.ancients": "ancients",
    "kills.towers": "towers",
    "kills.roshan": "roshan",
    "kills.courier": "courier",
    "kills.observers": "observers",
    "kills.sentries": "sentries",

    "sec.buffs": "PERMANENT BUFFS (only genuinely accumulated stacks)",
    "buffs.since": "(since {time})",

    "sec.teamfights": "TEAMFIGHTS",
    "tf.none": "— (no major teamfights detected in this match)",
    "tf.header": "Fight {n}: {start}–{end}{lane} | {score} — {verdict} | {me}",
    "tf.lane_tag": " (laning)",
    "tf.score": "losses: us {mine} / them {theirs}",
    "tf.win": "my team won it",
    "tf.lose": "the opponents won it",
    "tf.even": "even trade",
    "tf.me": "me: damage {damage}, deaths {deaths}, Δgold {gold}",
    "tf.me_killed": "killed: {heroes}",
    "tf.fallen": "died: {heroes}",
    "tf.detail":
        "{who}: Δgold={gold}, Δxp={xp}, deaths={deaths}, damage={damage}, healing={healing}",
    "tf.more": "(per-player breakdown — in --depth deep or --focus fights)",

    "sec.damage": "HERO DAMAGE (top targets)",

    "sec.objectives": "OBJECTIVES (buildings / Roshan / Tormentor / first blood)",
    "obj.firstblood": "first blood",
    "obj.building": "{attacker} destroyed: {victim}'s {kind} ({short}){by}",
    "obj.by_hero": " (by {hero})",
    "obj.by_creeps": " (by creeps)",
    "obj.tower": "tower",
    "obj.rax": "barracks",
    "obj.throne": "THRONE",
    "obj.roshan": "{team} killed Roshan",
    "obj.aegis": "Aegis picked up",
    "obj.tormentor": "{team} killed the Tormentor",
    "obj.courier": "courier lost ({team})",

    "pos.1": "pos. 1 — carry (safe lane)",
    "pos.2": "pos. 2 — mid",
    "pos.3": "pos. 3 — offlane",
    "pos.4": "pos. 4 — support (off lane)",
    "pos.5": "pos. 5 — hard support (safe lane)",
    "pos.core": "core ({lane})",
    "pos.support": "support ({lane})",
    "lane.safe": "safe lane",
    "lane.mid": "mid",
    "lane.off": "off lane",
    "lane.jungle": "jungle",
    "lane.roaming": "roaming",
    "lane.unknown": "unknown lane",

    "sec.limits": "DATA LIMITATIONS (important — do not fill these in yourself)",
    "limit.granularity":
        "- Net worth/xp/CS come at 1 point per minute — that is OpenDota's maximum.",
    "limit.positions":
        "- Player positions are an aggregated heatmap only, NOT a time series of coordinates.",
    "limit.hp":
        "- HP over time and second-by-second trades are unavailable (Tier 3, own replay parser).",
    "limit.roles":
        "- Other players' positions are a lane/net-worth heuristic. ★ may have a "
        "player-selected role, which overrides the heuristic for that player only.",
    "limit.unparsed":
        "- WARNING: the match is not fully parsed — some detailed fields may be empty.",
    "caveat.draft_grouped":
        "- Mode \"{mode}\": OpenDota returns picks and bans as separate groups rather than in "
        "true draft order. The DRAFT section shows them that way — do not draw conclusions "
        "about what came after what.",
    "caveat.items_filtered":
        "- Items: assembled ones only (mine from {mine} gold, others from {others}); "
        "components, consumables and wards are hidden.",
    "caveat.abilities_order":
        "- Ability build: #N is the upgrade order, NOT the hero level (the source gives no "
        "timings). OpenDota has no numeric talent values — only their names.",
    "caveat.window_compressed":
        "- A {start}–{end} min window was requested, so every other section is compressed "
        "to a summary. If a conclusion needs a fact outside the window and it is not in "
        "the prompt, say so instead of filling the gap yourself.",
    "caveat.saves_unavailable":
        "- OpenDota has no reliable save-event counter. Use healing, fight involvement and "
        "defensive-item timings as evidence, but do not invent a save count.",

    "sec.note": "PLAYER'S MAIN QUESTION",

    "sec.method": "HOW TO PREPARE THE REVIEW",
    "method.intro": "Rules you must follow:",
    "method.evidence":
        "Back every claim with a number or a timestamp from the data above. "
        "No number — no claim.",
    "method.no_generic":
        "Generic advice not tied to THIS match is FORBIDDEN: \"ward more\", \"communicate "
        "with your team\", \"farm better\", \"play safer\". If a piece of advice cannot be "
        "backed by a number from the data, do not give it at all.",
    "method.impact_first":
        "Sort by the cost of the mistake, not by time: start with what was most expensive "
        "(gold, xp, objectives, lost fights), then the small stuff.",
    "method.explain_why":
        "Explain the mechanism instead of handing out a rule. The player must understand "
        "WHY it happened, otherwise the advice will not transfer to the next game.",
    "method.no_invention":
        "If the data is insufficient for a conclusion, say so plainly and name the missing "
        "fact. Do not invent it.",
    "method.balance":
        "Do not turn the review into a list of complaints: name the strengths as "
        "specifically as the mistakes.",
    "method.calibrate":
        "Player's level: {level}. Calibrate the advice to it — suggest what is realistically "
        "executable at that level, and if you recommend something above it, explain why it "
        "matters and where to start.",
    "method.anomalies":
        "The \"STATISTICALLY UNUSUAL IN THE DATA\" block already lists the deviations. Work "
        "through each one: either explain it with an in-game cause, or honestly dismiss it "
        "if the match context makes it normal (for example, the role or the flow of the "
        "game). Silently ignoring a deviation is not allowed. Do not invent deviations that "
        "are not listed there.",
    "method.dialogue":
        "This is the START of the analysis, not a final verdict. Do not present conclusions "
        "as settled: finish with 2–3 competing hypotheses and 2–3 questions for me (the "
        "\"Hypotheses\" and \"Questions for me\" sections), so the analysis can be narrowed "
        "down in the next message.",
    "method.language": "Answer in {language}.",
    "method.note_priority":
        "The player has a specific question (the \"PLAYER'S MAIN QUESTION\" block). It is the "
        "top priority: the answer starts there, and the rest of the review only appears if "
        "it adds to that answer.",
    "method.role.1":
        "Evaluate the player as Pos 1 Carry: prioritize CS@10, GPM, the net-worth curve, "
        "power-spike timings, damage and survival in late fights. A late carry death, "
        "especially after 40:00, is costly; do not reduce the judgment to raw KDA.",
    "method.role.2":
        "Evaluate the player as Pos 2 Mid: prioritize tempo, runes, early impact, XPM, "
        "the matchup, kill participation, rotations and timings. Kills and participation "
        "matter more than pure farming; do not judge mid only by GPM/CS.",
    "method.role.3":
        "Evaluate the player as Pos 3 Offlane: prioritize initiation, frontlining, space "
        "creation, damage taken and fight impact. A death is forgivable when it creates "
        "a good initiation or favorable trade. Do not apply carry logic that fewer deaths "
        "always means better play.",
    "method.role.4":
        "Evaluate the player as Pos 4 Soft Support: prioritize rotations, early tempo, "
        "assists/participation, control, stacks, vision and utility timings. Farm and CS "
        "are NOT success metrics. A death is acceptable when it enables a favorable fight "
        "or saves a core.",
    "method.role.5":
        "Evaluate the player as Pos 5 Hard Support: prioritize vision/detection, save "
        "potential supported by available data, stacks, assists/participation, healing, "
        "control and team items. Farm is irrelevant; a sacrifice that enables a good fight "
        "is acceptable. Do not apply carry logic that fewer deaths always means better play.",
    "method.focus": "Review focus: {focus}",

    "focus.full": "the whole match, without over-weighting a single stage.",
    "focus.laning":
        "laning 0–10. Last hits per minute, lane efficiency against my lane opponents, "
        "trades, and what I came out of the lane with.",
    "focus.fights":
        "teamfights. My contribution, positioning, the cost of my deaths, and which fights "
        "swung the match.",
    "focus.farm":
        "farming and items. Net worth pace, key item timings, and flat stretches in the "
        "gold curve.",
    "focus.draft":
        "the draft. How the line-ups shaped the outcome and what exactly that meant for my hero.",
    "focus.vision":
        "vision and detection. Observer/sentry wards, dewards, objective information and "
        "the value created by map information.",
    "focus.tempo":
        "tempo. Runes, early kills, participation, lane exit, first item timings and objectives.",
    "focus.initiation":
        "initiation and space. Fight entries, damage taken, control, trades and the "
        "conditions created for the team.",
    "focus.enable":
        "team enablement. Stacks, vision, healing, control, participation and team/defensive "
        "item timings.",

    "sec.format": "ANSWER FORMAT",
    "format.intro": "Keep the order and the section headings:",
    "format.s0.title": "0. Answer to the main question",
    "format.s0.body":
        "A direct answer to the player's question, with numbers from the data. If the data "
        "is not enough for a full answer, say exactly what is missing.",
    "format.s1.title": "1. Verdict",
    "format.s1.body":
        "2–3 lines: how the player did overall and the ONE main thing to fix. "
        "Prose, not a list.",
    "format.s2.title": "2. What went well",
    "format.s2.body":
        "1–2 points with concrete numbers. This is not politeness: the player needs to know "
        "what to repeat in the next games.",
    "format.s3.title": "3. The main leak",
    "format.s3.body":
        "The single most expensive problem — with evidence: concrete timings, numbers and "
        "their consequences in this match. Show the chain \"what happened → what it cost\".",
    "format.s4.title": "4. Stage-by-stage review — ordered by impact",
    "format.s4.body":
        "Not chronologically, but from the most influential to the least. Every claim carries "
        "a number or a timestamp. A stage that went fine gets one line and you move on.",
    "format.s5.title": "5. What to do in the next games",
    "format.s5.body":
        "2–4 measurable actions. Bad: \"farm better\". Good: \"CS@10 ≥ 55 — by staying on your "
        "own creep wave after the support leaves instead of walking into the jungle\". "
        "Each action carries a number the player can check themselves against.",
    "format.s5.body.role.3":
        "2–4 measurable offlane actions: first-entry timing, targets controlled, damage "
        "absorbed or a favorable trade. Each action needs a number/timing from this match; "
        "do not make simply dying less the goal.",
    "format.s5.body.role.4":
        "2–4 measurable soft-support actions: a rotation/stack timing, participation, "
        "control, vision or a utility item. Each needs a number/timing from this match. "
        "Do not set CS or GPM targets; they are irrelevant to this role.",
    "format.s5.body.role.5":
        "2–4 measurable hard-support actions: a stack/ward timing, participation, healing, "
        "control or a defensive item. Each needs a number/timing from this match. Do not "
        "set CS/GPM targets or demand fewer deaths without context.",
    "format.s6.title": "6. Hypotheses: why the match ended this way",
    "format.s6.body":
        "2–3 COMPETING explanations of the outcome, drawn from different areas: draft, "
        "build and timings, key fights, farm, positioning. Each needs: (a) evidence from "
        "the data — a number or a timing, preferably tied to the deviations block; (b) what "
        "would confirm or refute it; (c) how confident you are. The hypotheses must differ "
        "in substance, not be restatements of one idea. If the data clearly points at one "
        "cause, say so — but still name what would refute it.",
    "format.s7.title": "7. Questions for me",
    "format.s7.body":
        "2–3 short diagnostic questions whose answers would narrow the analysis down. Ask "
        "about what is NOT in the data: intent, the plan for the game, communication, what "
        "was visible on screen. For example: \"did the game go wrong in a fight or already "
        "in the draft?\", \"is there a moment you are unsure about yourself?\", \"did you "
        "have the enemy carry in sight before that 28:00 engage?\". Do not ask about things "
        "already answered by the numbers above.",
}

UI = {
    "lang_name": "English",
    "title": "dota2coach",
    "tagline": "Dota 2 match → a ready-made prompt for an LLM",
    "group.player": "Match and player",
    "group.analysis": "Review setup",
    "group.request": "Player context",

    "field.match": "Match ID or link",
    "field.match.ph": "match ID or link",
    "field.account": "My account_id",
    "field.account.ph": "86745912",
    "field.hero_toggle": "don't know my ID — I'll name my hero",
    "field.hero": "My hero in this match",
    "field.hero.ph": "hero name from the match",

    "mode.help": "how do the modes differ?",
    "mode.match": "Single match",
    "mode.profile": "Profile",
    "mode.match.sub": "one game in depth",
    "mode.profile.sub": "patterns across N matches",
    "group.profile": "Player and sample",
    "advanced.toggle": "Advanced settings",
    "advanced.summary": "role, focus, depth, model, window, question",
    "advanced.summary.profile": "hero, position, model, question, level",

    "field.matches": "How many recent matches",
    "field.matches.ph": "10",
    "field.hero_filter": "This hero only",
    "field.hero_filter.ph": "hero name (optional)",
    "field.role_filter": "This position only",
    "role.any": "Any — as played",
    "submit.profile": "Analyze profile",
    "submit.busy.profile": "Building the profile…",
    "pstage.0": "Fetching the player's match list…",
    "pstage.4": "Pulling matches one by one: OpenDota allows about one request per second.",
    "pstage.25": "Still pulling. More matches take longer — you can leave the page alone.",
    "pstage.90": "Almost there. Folding the sample into patterns.",
    "result.matches": "matches: {analyzed}/{requested}",
    "result.unparsed": "unparsed: {n}",
    "result.window": "window: {range} min",

    "field.window": "Game window",
    "field.window.enable": "analyze a specific stretch",
    "window.off": "whole match",
    "window.range": "{start}–{end} min",
    "window.start": "window start, minutes",
    "window.end": "window end, minutes",
    "field.depth": "Depth",
    "field.role": "My role",
    "field.focus": "Focus",
    "field.model": "Model",
    "field.note": "Question for the review",
    "field.note.optional": "— optional",
    "field.note.ph.1":
        "why did I finish Manta so late, and was Diffusal better against Ursa",
    "field.note.ph.2": "where is my BF on Anti-Mage by minute 30",
    "field.note.ph.3": "I play support — were my wards and stacks right",
    "field.mmr": "My level / MMR",
    "field.mmr.optional": "— optional",
    "field.mmr.ph": "e.g. 3500 / Legend (or 300 — no judgement)",

    "role.auto": "Auto — detect from match",
    "role.1": "Pos 1 — Carry",
    "role.2": "Pos 2 — Mid",
    "role.3": "Pos 3 — Offlane",
    "role.4": "Pos 4 — Soft Support",
    "role.5": "Pos 5 — Hard Support",

    "focus.full": "full — overall review",
    "focus.laning": "laning — lane 0–10",
    "focus.fights": "fights — teamfights",
    "focus.farm": "farm — farming and items",
    "focus.draft": "draft — the draft",
    "focus.vision": "vision — vision and detection",
    "focus.tempo": "tempo — runes and early impact",
    "focus.initiation": "initiation — entries and space",
    "focus.enable": "enable — team enablement",
    "focus.adjusted": "Focus reset to full: the previous option is not primary for this role.",

    "submit": "Analyze",
    "submit.busy": "Building the prompt…",

    "stage.0": "Fetching the match from OpenDota…",
    "stage.6": "Match found, processing the data…",
    "stage.14": "The match isn't parsed yet — parsing requested from OpenDota.",
    "stage.40": "Parsing is running. It usually takes up to three minutes; you can wait here.",
    "stage.seconds": "s",

    "result.copy": "Copy",
    "result.copied": "Copied",
    "result.selected": "Selected — Cmd+C",
    "result.download": "Download .txt",
    "result.tokens": "~{n} tokens",
    "result.with_note": "with player's question",
    "result.side.radiant": "Radiant",
    "result.side.dire": "Dire",
    "result.win": "win",
    "result.lose": "loss",
    "result.winrate": "win rate {pct}%",
    "result.role": "role: {role}",

    "feedback.question": "Was this analysis useful?",
    "feedback.up": "Yes, useful",
    "feedback.down": "No, weak",
    "feedback.comment.ph": "what went wrong or what to improve — optional",
    "feedback.send": "Send",
    "feedback.sending": "Sending…",
    "feedback.thanks": "Thank you! This helps make the analyses sharper.",
    "feedback.thanks_more": "Thanks, noted.",
    "feedback.error": "Could not send. Please try again.",

    "disclaimer":
        "This tool gives you DATA and a structured prompt. The quality of the REVIEW depends "
        "on the AI model you paste it into: a weak free chatbot will do noticeably worse than "
        "ChatGPT Plus / Claude Pro / Gemini Advanced.",

    "err.match": "Check the match ID",
    "err.match.body":
        "Enter a match ID (a whole number) or a match link from Dotabuff, OpenDota or STRATZ.",
    "err.who": "Which player are you?",
    "err.who.body": "Enter your account_id or the hero you played in this match.",
    "err.account": "Check the account_id",
    "err.account.body": "It must be a positive whole number (Steam32 ID).",
    "err.offline": "The server is not responding",
    "err.offline.body":
        "The local server looks stopped. Start it again: python -m dota2coach serve",
    "err.warn_title": "Incomplete data",
    "err.400": "Which player are you?",
    "err.404": "Match not found",
    "err.422": "Check the form fields",
    "err.429": "OpenDota rate limit",
    "err.502": "OpenDota is unavailable",
    "err.504": "The match is still being parsed",
    "err.generic": "That didn't work",

    "warn.unparsed":
        "OpenDota has not fully parsed this match — the replay may have expired. The "
        "scoreboard and draft are there, but per-minute series, teamfights and item "
        "timings will be incomplete.",
    "err.body.not_found":
        "OpenDota has no such match. Check the ID — it must be a match number from your "
        "game history, not a lobby or profile ID.",
    "err.body.player_not_found":
        "Neither the account_id nor the hero name matched any of the ten players.",
    "err.body.player_not_specified":
        "Enter your account_id or the hero you played in this match.",
    "err.body.rate_limited":
        "OpenDota is rate-limiting requests. Wait a minute and try again — or set the "
        "OPENDOTA_API_KEY environment variable for higher limits.",
    "err.body.network":
        "Could not reach OpenDota. Check your connection and try again.",
    "err.body.unavailable":
        "OpenDota is unavailable or returning errors right now. Try again a bit later.",
    "warn.profile_unparsed":
        "OpenDota did not fully parse some matches in the sample: they have no percentiles or "
        "per-minute data, so they only partially feed the averages and trends. How many "
        "exactly is stated in the prompt, in the limitations section.",
    "warn.profile_short":
        "Fewer matches made it in than requested: some are unavailable or did not match the "
        "filter. Conclusions from a small sample are shaky — that is noted in the prompt too.",
    "err.body.no_matches":
        "No matches found for these filters. Relax the hero or position filter — and if there "
        "are no matches at all, check that \"Expose Public Match Data\" is enabled in Dota 2: "
        "without it OpenDota cannot see your history.",
    "err.body.hero_unknown":
        "The hero name was not recognised, or it matches several heroes. Write it out more "
        "fully — for example, \"Phantom Lancer\" instead of \"Phantom\".",
    "err.body.profile_timeout":
        "The sample is taking too long to collect. Reduce the number of matches or try again: "
        "some matches are already in the local cache, so a second run will be faster.",
    "err.body.bad_window":
        "The end of the window must be greater than its start. Adjust the slider.",
    "err.body.parse_timeout":
        "OpenDota is still parsing this match. Wait a minute and retry — the second "
        "attempt usually finds the data ready.",
    "err.roster": "Players in this match:",

    "info.open": "What this is and how to use it",
    "info.close": "Close",
    "info.title": "What this is and how to use it",
    "info.what.title": "What this is",
    "info.what.body":
        "The tool pulls the detailed statistics of your Dota 2 match and packs them into a "
        "ready-made prompt for an AI (ChatGPT, Claude, Gemini). You paste it into your AI "
        "chat — and it breaks your game down like a coach. Far more accurate than "
        "describing the game to an AI from memory.",
    "info.can.title": "What you can do",
    "info.can.1": "Break down a single match (laning, fights, timings, benchmarks).",
    "info.can.2": "Build a profile from your last N games and find repeating mistakes.",
    "info.can.3": "Focus on a role, a stage, or a specific stretch of the game.",
    "info.can.4": "Add your own question — the analysis will be about it.",
    "info.important.title": "Worth understanding",
    "info.important.body":
        "The tool gives you DATA and a prompt; the quality of the analysis depends on the "
        "AI you paste it into. The first answer is the start of a conversation, not the "
        "end: the AI will ask you follow-up questions itself.",
    "info.tips.title": "3 tips",
    "info.tips.1":
        "Use a strong model (ChatGPT Plus / Claude Pro / Gemini Advanced) — a weak bot gets "
        "lost in the volume and produces waffle.",
    "info.tips.2":
        "Write your question into the note field — a pointed request lands harder than a "
        "general one.",
    "info.tips.3":
        "Do not stop at the first answer: reply to the follow-up questions and dig deeper; "
        "and pick the right role — a carry and a support are analysed differently.",

    "theme.toggle": "Switch theme",
    "lang.toggle": "Interface and prompt language",
    "hint.close": "Close",

    "hint.match":
        "The match ID from your game history. You can paste a whole link — from Dotabuff, "
        "OpenDota or STRATZ — and the number will be extracted for you.",
    "hint.account":
        "Your Steam32 ID — it tells the tool which of the ten players you are. You can see it "
        "in your profile URL on Dotabuff or OpenDota. If you don't know it, click "
        "\"don't know my ID\" and name the hero you played instead.",
    "hint.role":
        "The selected position overrides automatic detection for your hero only. It changes "
        "the evaluation criteria and which evidence is prioritized. Leave Auto selected when "
        "the match-derived position is correct.",
    "hint.depth":
        "quick — the skeleton of the match only: draft, scoreboard, benchmarks, team gold "
        "advantage, your items and your lane. deep — the same expanded across all ten players: "
        "per-minute series, per-player fight breakdowns, damage split. Start with quick; reach "
        "for deep when you want maximum context and the model can take a long prompt.",
    "hint.focus":
        "What the review is tuned for. Focus not only expands its own section but also mutes "
        "the others so the model doesn't spread thin. full — overall review; the rest narrow "
        "down to one topic.",
    "hint.model":
        "Only the packaging changes, the data is identical. Claude reads structure better "
        "through XML tags, ChatGPT and Gemini prefer plain markdown. A sensible default depth "
        "comes with the model, but your own choice in the Depth field always wins.",
    "hint.note":
        "Your own question for the review. If it is set, the review starts with it and the "
        "generic sections move to the background. Be specific: \"why did I lose the lane "
        "against Pudge and Hoodwink?\" works far better than \"how do I play better?\".",
    "hint.mode":
        "\"Single match\" breaks down one game in detail. \"Profile\" takes the last N "
        "matches and looks for what REPEATS: averages, trends, recurring deviations. Full "
        "match data is not in the profile — otherwise the prompt would not fit any model.",
    "hint.matches":
        "How many recent matches to fold into the profile. Fewer is faster but the "
        "conclusions are shaky; more is sturdier but slower and risks mixing patches. "
        "Matches are pulled one per second or so: 10 matches means about 15 seconds.",
    "hint.hero_filter":
        "Optional. Keeps only matches on this hero, which makes the averages and patterns "
        "far more meaningful than an average across all heroes. The name can be partial but "
        "must be unambiguous: \"Phantom\" will not do, \"Phantom Lancer\" will.",
    "hint.role_filter":
        "Optional. Keeps only matches on this position. The position is derived heuristically "
        "from lane and net worth, so some matches may drop out — how many actually made it "
        "is stated in the prompt itself.",
    "hint.window":
        "Pick a stretch if you want to examine a specific point of the game in maximum "
        "detail — the actions of every hero inside that window. Inside the window nothing is "
        "thinned out: all ten heroes per minute, purchases, kills and fights. The rest of the "
        "match is compressed to a summary — otherwise the window's detail would drown in it.",
    "hint.advanced":
        "Everything you can leave alone. The defaults are tuned for an ordinary review; open "
        "this when you need a specific slice.",
    "hint.mmr":
        "Optional. Give an MMR or a bracket (Herald, Legend, Ancient…) and the model will "
        "calibrate its advice to that level instead of suggesting moves you can't execute yet.",
}
