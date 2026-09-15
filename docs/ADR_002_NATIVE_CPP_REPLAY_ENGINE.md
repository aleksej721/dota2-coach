# ADR-002 — нативное ядро Replay Engine на C++

Статус: **accepted**.

Дата: 2026-09-16.

## Решение

Полный Dota 2 replay decoder реализуется как отдельное C++-ядро. Python остаётся
слоем продукта: API, OpenDota fallback, prompt/evidence assembly и запуск
ограниченного subprocess. Canonical contracts из `dota2coach/replay` не зависят
от языка decoder.

Причины выбора C++ для этого проекта:

* memory-mapped последовательное чтение больших `.dem` без Python object churn;
* контроль аллокаций и повторное использование scratch buffers;
* естественная реализация Source 2 bitstream, field paths и entity deltas;
* доступ к SIMD/parallel decode там, где benchmark покажет реальную пользу;
* один компактный worker без GIL и без JVM.

Manta и Clarity остаются correctness-oracle и источниками сопоставления coverage,
но не production runtime. Python-прототип контейнера остаётся независимой
проверкой framing и безопасным preflight; дальнейший Snappy/protobuf/entity код
в Python не дублируется.

## Граница процесса

`dota2-replay-engine` читает недоверенный replay и пишет versioned JSON/бинарные
canonical chunks. Приложение запускает его без shell, с timeout и отдельным
cache-каталогом. Следующий production hardening — лимиты CPU/RSS и sandbox
worker-процесса.

Текущий native slice уже выполняет:

1. mmap и строгий `PBDEMS2` framing;
2. bounded raw Snappy decode;
3. protobuf wire validation и metadata (`FileHeader`, `FileInfo`);
4. packed `CDemoPacket` framing через Valve `UBitVar`;
5. coverage counts для outer и network message IDs.

Следующая граница — generated Valve protobuf, send tables, serializers,
string tables и `svc_PacketEntities`, после чего entity deltas поступают в
canonical store.
