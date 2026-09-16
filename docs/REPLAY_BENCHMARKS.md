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

## B1 — native C++ payload + network framing

Дата: 2026-09-16.

Слой: [`replay_engine`](../replay_engine), C++17. Один memory-mapped проход
включает outer framing, raw Snappy decompression, protobuf wire validation,
извлечение `CDemoFileHeader` / `CDemoFileInfo` и packed network framing
`{UBitVar type, varuint size, body}`. Также структурно декодируются `net_Tick`,
string-table сообщения и envelope `svc_PacketEntities`; сами entity field paths
на этом этапе ещё не декодируются.

Тот же fixture `1560315800.dem`:

| Параметр | Значение |
|---|---:|
| Outer commands | 53 611 |
| Snappy blocks | 26 068 |
| Decoded outer payload | 53 295 410 bytes |
| Packet data | 48 774 408 bytes |
| Network messages | 637 783 |
| Network message bodies | 47 106 875 bytes |
| Server classes | 666 |
| `svc_PacketEntities` | 53 581 |
| Declared entity updates | 2 827 099 |
| Entity bitstream bytes | 27 573 981 |

Среда: Darwin arm64, Apple Clang 14, `-O3 -std=c++17`. Два warm-up, затем пять
запусков отдельного процесса (то есть числа включают process startup):

```text
0.312568, 0.311688, 0.313122, 0.311910, 0.312275 s
median 0.312275 s
p95 nearest-rank 0.313122 s
peak child RSS 49 561 600 bytes
```

Это близко к Python container-only baseline B0, хотя B1 распаковывает payload,
разбирает 637 тысяч внутренних сообщений и валидирует 53 тысячи entity
envelope. Временный Python Snappy/protobuf prototype без этого entity-envelope
слоя занимал около 1.69 s; после выбора C++ он удалён, чтобы не вести два
production decoder. Следующий B2 обязан включать generated protobuf,
send-tables/string-tables и сами entity field paths.

## B2 — serializers, class baselines and field paths

Дата: 2026-09-16.

К B1 добавлены `DEM_SendTables`, flattened serializer catalog, классификация
типов полей, связь server classes, Valve LZSS/string-table decode для
`instancebaseline` и все 40 Huffman field-path operations. Fixture тот же — это
проверка старого Source 2 build, а не обещание совместимости с текущим патчем.

| Параметр | Значение |
|---|---:|
| Serializer symbols | 2 102 |
| Serializer definitions | 703 |
| Serializer fields | 1 303 |
| Linked server classes | 666 / 666 |
| Baseline classes | 76 / 76 linked |
| Baseline value bytes | 21 969 |
| Decoded baseline field paths | 9 657 |
| Maximum field-path depth | 4 |
| Invalid root paths | 0 |
| Unresolved nested serializers | 0 |

Apple Clang 14, `-O3 -std=c++17`: после cold run четыре отдельных запуска
заняли 0.3187–0.3375 s по внутреннему monotonic timer (медиана около 0.320 s).
Field-path слой не изменил порядок времени B1. Следующий B3 должен измерять уже
typed values и полное entity state на старом и свежем replay.
