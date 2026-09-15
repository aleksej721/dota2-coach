"""Process boundary between the Python product and the native replay engine."""

import json
import os
import pathlib
import shutil
import subprocess
from typing import Any, Dict, Optional, Union


class NativeReplayError(RuntimeError):
    pass


def find_native_engine(explicit: Optional[Union[str, pathlib.Path]] = None) -> pathlib.Path:
    candidates = []
    if explicit is not None:
        candidates.append(pathlib.Path(explicit))
    configured = os.environ.get("DOTA2_REPLAY_ENGINE_BIN")
    if configured:
        candidates.append(pathlib.Path(configured))
    candidates.append(
        pathlib.Path(__file__).resolve().parents[2]
        / "replay_engine" / "build" / "dota2-replay-engine"
    )
    on_path = shutil.which("dota2-replay-engine")
    if on_path:
        candidates.append(pathlib.Path(on_path))

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise NativeReplayError(
        "C++ replay engine не собран. Запусти `make -C replay_engine`, "
        "либо задай DOTA2_REPLAY_ENGINE_BIN."
    )


def native_scan(path: Union[str, pathlib.Path], *, timeout: float = 120,
                engine: Optional[Union[str, pathlib.Path]] = None) -> Dict[str, Any]:
    """Run one bounded native scan and return its machine-readable report."""
    replay = pathlib.Path(path).expanduser().resolve()
    if not replay.is_file():
        raise NativeReplayError(f"replay file is not readable: {replay}")
    executable = find_native_engine(engine)
    try:
        completed = subprocess.run(
            [str(executable), "scan", str(replay)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise NativeReplayError(f"C++ decoder превысил лимит {timeout:g} с") from exc
    except OSError as exc:
        raise NativeReplayError(f"не удалось запустить C++ decoder: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise NativeReplayError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise NativeReplayError("C++ decoder вернул некорректный JSON") from exc
    if not isinstance(payload, dict):
        raise NativeReplayError("C++ decoder вернул неожиданный результат")
    if payload.get("schema_version") != 1:
        raise NativeReplayError(
            f"несовместимая версия native schema: {payload.get('schema_version')!r}"
        )
    return payload
