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
    "format.s6.title": "6. Where to dig deeper",
    "format.s6.body":
        "2–3 questions the player can send you next to go deeper. Phrase them from the "
        "player's point of view and tie them to this match — for example: \"Break down the "
        "fight at 39:00 where I died first\".",
}

UI = {
    "lang_name": "English",
    "title": "dota2coach",
    "tagline": "Dota 2 match → a ready-made prompt for an LLM",
    "group.player": "Match and player",
    "group.analysis": "Review setup",
    "group.request": "Player context",

    "field.match": "Match ID or link",
    "field.match.ph": "8931432366 or a Dotabuff / OpenDota link",
    "field.account": "My account_id",
    "field.account.ph": "964327319",
    "field.hero_toggle": "don't know my ID — I'll name my hero",
    "field.hero": "My hero in this match",
    "field.hero.ph": "Phantom Lancer",
    "field.depth": "Depth",
    "field.role": "My role",
    "field.focus": "Focus",
    "field.model": "Model",
    "field.note": "Question for the review",
    "field.note.optional": "— optional",
    "field.note.ph": "why did I finish Manta so late, and was Diffusal better against Ursa?",
    "field.mmr": "My level / MMR",
    "field.mmr.optional": "— optional",
    "field.mmr.ph": "3500 or Legend",

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
    "result.role": "role: {role}",

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
    "err.body.parse_timeout":
        "OpenDota is still parsing this match. Wait a minute and retry — the second "
        "attempt usually finds the data ready.",
    "err.roster": "Players in this match:",

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
    "hint.mmr":
        "Optional. Give an MMR or a bracket (Herald, Legend, Ancient…) and the model will "
        "calibrate its advice to that level instead of suggesting moves you can't execute yet.",
}
