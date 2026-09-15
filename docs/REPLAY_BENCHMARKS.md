# Replay Engine benchmarks

Здесь фиксируются воспроизводимые измерения по слоям. Нельзя сравнивать
container scan с полным entity decode: у них разная работа и разный объём
выходных данных.

## B0 — PBDEMS2 framing/index baseline

Дата: 2026-09-16.

Слой: [`replay/framing.py`](../dota2coach/replay/framing.py), без Snappy
decompression, protobuf и entity decode. Scanner читает весь файл, считает
SHA-256, валидирует frames и строит seek-index; payload не сохраняется.

Fixture: публичный replay из тестового корпуса
[dotabuff/manta](https://github.com/dotabuff/manta/blob/master/manta_test.go):
`1560315800.dem`.

| Параметр | Значение |
|---|---:|
| Размер | 46 663 851 bytes |
| SHA-256 | `30088400a91518ae61867380ff5dd0544e76979088c7e1674027d15c77f8d350` |
| Команд | 53 611 |
| Compressed commands | 26 068 |
| Distinct nonnegative ticks | 53 521 |
| Tick range | 2–107 108 |
| FullPacket seek points | 60 |
| Unknown command IDs | 0 |

Среда: Darwin arm64, Python 3.14.2. Один warm-up, затем пять проходов в одном
процессе:

```text
0.2685, 0.2669, 0.2709, 0.2698, 0.2683 s
median 0.2685 s
p95 nearest-rank 0.2709 s
peak process RSS 32 178 176 bytes
```

CLI cold-start (`python -m dota2coach replay scan ... --json`) занял 0.53 s.
Эти числа являются baseline контейнера, а не заявлением о производительности
полного replay engine. Следующий сопоставимый benchmark должен добавить
Snappy/protobuf decode и canonical event/entity output на этом же fixture и на
свежем replay текущего build Dota 2.
