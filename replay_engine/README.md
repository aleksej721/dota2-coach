# Dota 2 native replay engine

Нативное C++17-ядро точного replay analysis. Это не отдельный продуктовый API:
Python-приложение вызывает бинарь через `dota2coach.replay.native` и преобразует
его versioned output в canonical replay store.

## Build and test

```bash
make -C replay_engine test all
replay_engine/build/dota2-replay-engine scan replay-cache/match.dem
```

Также есть `CMakeLists.txt` для CI/production toolchain. Текущий локальный Makefile
не требует protobuf или Snappy packages: bounded wire decoders реализованы в
ядре. Когда начнётся schema-generated слой, `.proto` фиксируются по конкретному
SteamTracking revision и генерируются на build step — сетевой fetch во время
production build не допускается.

## Implemented boundary

* mmap + strict `PBDEMS2` frames and header offsets;
* raw Snappy decompression with output limits;
* protobuf wire validation;
* stable demo metadata;
* packed network message framing (`UBitVar`);
* structural decoding for ticks, string tables and `svc_PacketEntities`.

Следующая ступень: flattened serializers/send tables, class baselines and entity
field-path deltas. До неё текущий output не называется «координатами» или
«посекундными событиями».
