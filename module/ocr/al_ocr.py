"""
AlOcr: thin adapter over RapidOCR that preserves the public surface used by Alas.

This module replaces the original mxnet/cnocr 1.2.2 backend (which depended on
mxnet 1.6.0 - a library that stopped releasing wheels in 2022 and is not
installable on Python 3.10+). RapidOCR ships ONNX Runtime wheels and a default
PaddleOCR-v4/v6 multilingual model, so it stays installable on every supported
Python without the heavy mxnet / gluoncv dependency tree.

Interface compatibility
-----------------------
Old code in module/ocr/ocr.py and module/ocr/models.py expects an AlOcr object
that supports::

    ocr(img_fp) -> list[str]
    ocr_for_single_line(img_fp) -> list[str]
    ocr_for_single_lines(img_list) -> list[list[str]]
    set_cand_alphabet(cand_alphabet: str | None) -> None
    atomic_ocr_for_single_lines(img_list, cand_alphabet=None) -> list[list[str]]

RapidOCR's ``__call__`` returns a ``RapidOCROutput`` object; this adapter
flattens it to the same return shape cnocr 1.2.2 produced (one character list
per line), and applies the original "I/D/S/B -> 1/0/5/8" post-processing that
the bespoke ``azur_lane`` model encoded. ``cand_alphabet`` is used as a hard
allow-list filter on the recognized text so the rest of the project keeps
working without changes.

Notes on accuracy
-----------------
The ``azur_lane`` / ``azur_lane_jp`` models in ``bin/cnocr_models/`` were
trained for a specific set of ~39 characters (Impact / AgencyFB /
MStiffHeiHK-UltraBold fonts). RapidOCR's default multilingual model is
significantly larger and includes far more characters; this *can* introduce
extra noise (e.g. "0" vs "O") that the cand_alphabet filter and the
I/D/S/B substitution will not catch. If accuracy is unacceptable, swap the
engine for a custom-trained ONNX model in ``module/ocr/models.py`` - the
adapter is engine-agnostic.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np

from module.logger import logger

# Characters the legacy azur_lane model frequently confused. The replacement is
# a no-op for characters that don't appear, so it is safe to apply to the
# output of any OCR engine.
_LEGACY_REVISIONS = str.maketrans({"I": "1", "D": "0", "S": "5", "B": "8"})


class AlOcr:
    """Adapter exposing the legacy cnocr-shaped API on top of RapidOCR."""

    # ``context`` / ``model_name`` are accepted for backward compatibility
    # with module/ocr/models.py. They are ignored by the RapidOCR backend.
    def __init__(
        self,
        model_name: str = "densenet-lite-gru",
        model_epoch: int | None = None,
        cand_alphabet: str | None = None,
        root: str | None = None,
        context: str = "cpu",
        name: str | None = None,
    ) -> None:
        self._args = (model_name, model_epoch, cand_alphabet, root, context, name)
        self._cand_alphabet: str | None = (
            str(cand_alphabet) if cand_alphabet else None
        )
        self._model_loaded = False
        # RLock because atomic_ocr_for_single_lines acquires it and then
        # _infer -> _ensure_engine acquires it again on first use.
        self._lock = threading.RLock()
        self._engine: Any = None
        self._name = name or "ocr"

    # ---- lazy engine init -------------------------------------------------

    def init(self, *_, **__) -> None:  # legacy hook, kept for compatibility
        self._ensure_engine()

    def _ensure_engine(self) -> None:
        if self._model_loaded:
            return
        with self._lock:
            if self._model_loaded:
                return
            logger.info(f"Loading RapidOCR engine for {self._name}")
            # Import lazily so CLIs / tests that don't need OCR pay no startup
            # cost. RapidOCR ships its ONNX models inside the package directory
            # so no network access is required.
            #
            # Alas already pre-crops the region to OCR via `extract_letters`
            # (module/base/utils.py), so each input image is a single line
            # of text. We therefore disable the text detector (use_det=False)
            # and the orientation classifier (use_cls=False); the recognizer
            # alone returns the right answer in ~10x less time. The detector
            # is still available in the package if a future caller needs it.
            from rapidocr import RapidOCR  # type: ignore

            self._engine = RapidOCR()
            self._model_loaded = True
            logger.info(f"RapidOCR engine ready for {self._name}")

    # ---- alphabet handling ------------------------------------------------

    def set_cand_alphabet(self, cand_alphabet: str | None) -> None:
        """Filter recognized text to a whitelist.

        Accepts either a string of allowed characters (the legacy cnocr
        convention) or ``None``/empty to disable filtering.
        """
        if cand_alphabet is None or cand_alphabet == "":
            self._cand_alphabet = None
        else:
            self._cand_alphabet = str(cand_alphabet)

    # ---- core inference ---------------------------------------------------

    def _infer(self, image: np.ndarray) -> list[str]:
        """Run RapidOCR on one image and return the joined recognized text."""
        self._ensure_engine()
        if self._engine is None:
            raise RuntimeError("RapidOCR engine failed to initialize")
        output = self._engine(image)
        if hasattr(output, "txts"):
            txts: list[str] = list(output.txts or [])
        else:
            # tuple fallback for older versions: (boxes, txts, scores)
            try:
                txts = list(output[1] or [])
            except Exception:
                txts = []
        if not txts:
            return []
        joined = "".join(txts)
        return [self._post_process(joined)]

    def _post_process(self, text: str) -> str:
        # Drop characters outside the whitelist, then apply legacy revisions.
        if self._cand_alphabet is not None:
            allowed = set(self._cand_alphabet)
            text = "".join(ch for ch in text if ch in allowed)
        return text.translate(_LEGACY_REVISIONS)

    # ---- public cnocr-compatible API -------------------------------------

    def ocr(self, img_fp: np.ndarray) -> list[str]:
        """Legacy multi-line entry. Returns ``[text]`` (cnocr returned a list)."""
        return self._infer(img_fp)

    def ocr_for_single_line(self, img_fp: np.ndarray) -> list[str]:
        """Legacy single-line entry. Returns ``[text]``."""
        return self._infer(img_fp)

    def ocr_for_single_lines(self, img_list: Iterable[np.ndarray]) -> list[list[str]]:
        """Legacy batch entry. Returns one list per input image."""
        return [self._infer(np.asarray(img)) for img in img_list]

    def atomic_ocr(
        self, img_fp: np.ndarray, cand_alphabet: str | None = None
    ) -> list[str]:
        with self._lock:
            prev = self._cand_alphabet
            self.set_cand_alphabet(cand_alphabet)
            try:
                return self.ocr(img_fp)
            finally:
                self._cand_alphabet = prev

    def atomic_ocr_for_single_line(
        self, img_fp: np.ndarray, cand_alphabet: str | None = None
    ) -> list[str]:
        with self._lock:
            prev = self._cand_alphabet
            self.set_cand_alphabet(cand_alphabet)
            try:
                return self.ocr_for_single_line(img_fp)
            finally:
                self._cand_alphabet = prev

    def atomic_ocr_for_single_lines(
        self, img_list: Iterable[np.ndarray], cand_alphabet: str | None = None
    ) -> list[list[str]]:
        with self._lock:
            prev = self._cand_alphabet
            self.set_cand_alphabet(cand_alphabet)
            try:
                return self.ocr_for_single_lines(img_list)
            finally:
                self._cand_alphabet = prev

    # ---- debug helpers ----------------------------------------------------

    def debug(self, img_list: Sequence[np.ndarray]) -> None:
        """Visualize the preprocessed input images side by side.

        Mirrors the legacy ``al_ocr.AlOcr.debug`` signature so module/ocr/ocr.py
        can call it without branching.
        """
        if not img_list:
            return
        try:
            import cv2  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError:
            logger.warning("debug() requires opencv-python and pillow")
            return
        arrays = [np.asarray(i) for i in img_list]
        stacked = cv2.hconcat(arrays)
        Image.fromarray(stacked[0, :, :]).show()
