# ADR-001 — decoder boundary и canonical replay store

Статус: **accepted for implementation; decoder winner pending benchmark**.

Дата: 2026-09-15.

## Контекст

Продукту нужны координаты, состояния, casts, orders, damage, cooldowns, крипы и
экономика в произвольном коротком окне. OpenDota этого не даёт. При этом нельзя
связать весь продукт с именами protobuf-полей одной сторонней библиотеки: Dota
обновляется, decoder можно заменить, а coaching/evidence semantics должны
оставаться нашими.

## Решение

Replay Engine делится на четыре границы:

1. **Decoder adapter** читает `.dem` потоково и сообщает исходные ticks,
   entity changes и events вместе с provenance.
2. **Dota normalizer** переводит нестабильные protobuf/send-table имена в
   versioned canonical поля.
3. **Canonical Replay Store** хранит checkpoints, state deltas и discrete events.
4. **Query/Evidence API** отвечает на узкие time-range запросы; LLM не получает
   полный replay dump.

Первый reference store реализован в [`dota2coach/replay`](../dota2coach/replay).
Это correctness oracle в памяти: бинарный или columnar backend позже обязан
давать тот же наблюдаемый результат запросов.

Первый decoder-independent слой также реализован: `replay/framing.py` владеет
внешним контейнером `PBDEMS2`. Он потоково читает фиксированный header и кадры
`command/tick/size/body`, проверяет offsets, uint32 varints, лимиты и truncation,
считает неизвестные command ID и строит seek-index по `DEM_SyncTick` и
`DEM_FullPacket`. Payload при индексировании не удерживается в памяти. Это ещё
не Dota decoder: Snappy/protobuf, send tables и entities остаются за адаптером.

Каждый факт имеет `TruthLevel`:

* `observed` — прочитан прямо из replay;
* `derived` — детерминированно вычислен из observed;
* `inferred` — гипотеза, которую нельзя выдавать за факт.

Время хранится как source `tick` и pause-aware `game_time_ms`. Отрицательное
время разрешено для pre-game. Простой `tick / 30` запрещён как источник игрового
времени: draft, pre-game и pauses делают его неверным.

## Кандидаты decoder bake-off

**Manta — основной первый spike.** Это низкоуровневый Source 2 parser на Go,
который намеренно не навязывает структуру данных и отдаёт callbacks/raw data.
Go-бинарь удобен как изолированный local worker и не требует JVM во время
работы приложения. Проект и API: [dotabuff/manta](https://github.com/dotabuff/manta).

**Clarity — обязательный контрольный spike.** Clarity 4 предоставляет entities,
combat log, modifiers, user/game events и raw protobuf; в официальных examples
есть entity lifecycle и cooldown tracking. Это сильная проверка coverage и
корректности Manta-адаптера. Проекты:
[skadistats/clarity](https://github.com/skadistats/clarity) и
[clarity-examples](https://github.com/skadistats/clarity-examples).

Победитель **не выбран заранее**. В репозитории пока нет `.dem`-корпуса, поэтому
любое число скорости сейчас было бы выдумкой.

Container-only baseline уже измерен на публичном fixture Manta и хранится в
[REPLAY_BENCHMARKS.md](REPLAY_BENCHMARKS.md). Он проверяет наш framing/index,
но не заменяет decoder bake-off: для него по-прежнему нужен свежий replay
текущего build и одинаковый canonical output Manta/Clarity.

## Один контракт bake-off

Оба spike обязаны на одном наборе replay выдавать:

* manifest: SHA-256, size, match/build, tick range, tick rate, decoder version;
* lifecycle hero/creep/building entities;
* position, facing, HP/mana, life state;
* inventories, abilities/modifiers и cooldown state;
* casts, orders, damage/heal/death, purchases и objectives;
* неизвестные raw fields в coverage report, а не молчаливое отбрасывание.

Сравниваются wall time, peak RSS, output volume, coverage, точность golden
эпизодов, поддержка текущего build, простота обновления protobuf и качество
ошибки на повреждённом файле. Замер после одного warm-up, минимум пять прогонов;
фиксируются median и p95.

## Безопасность

Replay — недоверенный файл. Decoder запускается отдельным процессом с лимитами
размера, времени и памяти. До запуска проверяются magic `PBDEMS2`, размер и
SHA-256. Временные и итоговые файлы создаются внутри выделенного replay cache;
путь пользователя не используется как выходной путь.

## Следствия

* Текущий `Match` не раздувается миллионами tick-событий; из store строится его
  компактная совместимая проекция.
* UI может заменить OpenDota minute series на replay series без смены смысла
  графиков и явно показать гранулярность.
* Fight/Laning Intelligence развивается поверх query API, независимо от языка
  decoder.
* Следующая необходимая внешняя входная информация — небольшой разрешённый
  корпус реальных `.dem`, включая один свежий replay и один матч с известным
  ключевым файтом.
