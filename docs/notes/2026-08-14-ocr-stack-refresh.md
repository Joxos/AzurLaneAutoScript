# 2026-08-14 — OCR stack refresh

## What changed

- **Removed** `cnocr 1.2.2` + `mxnet 1.6.0` + `gluoncv 0.6.0` + `cigam 0.0.3`
  (all dead, no wheels for Python 3.10+).
- **Removed** `zerorpc 0.6.3` + `gevent 21.12.0` + `pyzmq 22.3.0` (zerorpc
  has not released since 2019; gevent 25+ is incompatible with zerorpc).
- **Removed** `module/ocr/rpc.py` (the IPC server was unnecessary; OCR now
  runs in-process).
- **Replaced** the engine in `module/ocr/al_ocr.py` with a thin adapter on
  `rapidocr 3.x` (PaddleOCR-v4/v6 multilingual, ONNX runtime). The public
  surface (`AlOcr.ocr`, `ocr_for_single_lines`, `atomic_ocr_for_single_lines`,
  `set_cand_alphabet`) is byte-for-byte compatible with the old cnocr-shaped
  contract, so the rest of the project compiles without changes.
- **Toolchain**: `requirements.txt` + `requirements-in.txt` deleted, replaced
  with a PEP-621 `pyproject.toml`. Lock generation moved to `uv lock`. `ruff`
  added with a conservative rule set (E/F/W/I/UP/B/C4/SIM); legacy campaign
  and generated files are excluded to avoid opening 9700+ unrelated fixes
  in one PR.
- **Backports dropped**: `cached_property` is now `functools.cached_property`
  (stdlib since 3.8).

## Accuracy caveats

The legacy `azur_lane` / `azur_lane_jp` models in `bin/cnocr_models/`
were trained for ~39 specific characters. RapidOCR's default multilingual
model is significantly larger; this can introduce extra noise (e.g. `0`
vs `O`) that the `cand_alphabet` filter and the `I/D/S/B -> 1/0/5/8`
substitution will not catch. The fix is to swap the engine in
`module/ocr/al_ocr.py` for a custom-trained ONNX model — the adapter is
engine-agnostic. For now, smoke tests pass; the true test is a real
game screenshot, which the user will run.

## Bug we hit and how we found it

While writing smoke tests, `atomic_ocr_for_single_lines` hung for 60+
seconds on first call. The root cause was a `threading.Lock` (non-
reentrant) guarding `_ensure_engine`. The call chain is::

  atomic_ocr_for_single_lines
    -> [self._lock] acquire
    -> self.ocr_for_single_lines
    -> [self._infer]
    -> self._ensure_engine
    -> [self._lock] acquire        <-- deadlock, same thread

`ocr_for_single_line` worked by itself because it acquires the lock
exactly once. `atomic_*` acquires it, then triggers the recursive
acquire via `_infer -> _ensure_engine`. Fix: switch to
`threading.RLock`. This was easy to miss in unit-style probes (which
don't go through the atomic wrapper) and only showed up in the full
`Ocr / Digit / Duration / DigitCounter` smoke run.

Lesson: when wrapping a public method in a lock + delegating to a
helper that re-enters the same lock, always use `RLock`.

## Smoke results

Sample test images (PIL-rendered text on a 30,50,90 background):
- `14/15`    -> `DigitCounter.ocr()` -> `(14, 1, 15)` ✅
- `01:30:00` -> `Duration.ocr()`     -> `timedelta(seconds=5400)` ✅
- `42`       -> `Digit.ocr()`        -> `42` ✅
- `12345/15` -> `Ocr.ocr()`          -> `'12345/15'` ✅
- `NEXT 12345` -> raw `atomic_ocr`   -> `'NEXT12345'` ✅

End-to-end ~2 s for a single image (first call). Subsequent calls
~1.5 s. Engine loads in <1 s after the first inference.

## Files touched

| File | Action |
| --- | --- |
| `module/ocr/al_ocr.py` | rewritten (RapidOCR adapter) |
| `module/ocr/ocr.py`    | fixed TYPE_CHECKING import, kept cnocr-shaped call site |
| `module/ocr/rpc.py`    | deleted |
| `module/base/resource.py`     | `UseOcrServer` branch now a no-op (preserved for YAML compat) |
| `module/webui/app.py`         | removed `start_ocr_server_process` / `stop_ocr_server_process` calls; preserved settings |
| `module/config/config_updater.py` | `cached_property` -> `functools.cached_property` |
| `alas.py`                | `cached_property` -> `functools.cached_property` |
| `pyproject.toml`         | new (PEP-621, ruff, uv) |
| `requirements.txt`       | deleted |
| `requirements-in.txt`    | deleted |
| `.pre-commit-config.yaml`| new (ruff hooks) |

## Verification commands the user can run

```bash
# 1. Environment
cd /home/Joxos/source/forks/AzurLaneAutoScript
uv sync --extra lint

# 2. Lint baseline for the new code only
uv run ruff check module/ocr/

# 3. Smoke test
uv run python /tmp/alas_poc/smoke.py
```
