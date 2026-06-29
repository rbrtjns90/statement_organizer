"""
OCR-to-Geometry Bridge
======================
Bridges OCR output back into the geometry extraction pipeline, for image-only
(scanned) PDFs that have no text layer.

WHY THIS EXISTS
---------------
The geometry extractor (geometry_extractor.py) needs per-word coordinates
(x0, x1, top) to detect columns and parse transaction lines. Native text-layer
PDFs provide these via pdfplumber's `extract_words()`. But for IMAGE-ONLY PDFs,
there's no text layer — only OCR'd text, which loses positional information.

This module runs OCR with word-level bounding boxes and converts the results
into the same word-dict format pdfplumber produces:
    {"text": str, "x0": float, "x1": float, "top": float, "bottom": float, ...}

The geometry extractor can then consume these exactly as if they came from a
text-layer PDF. This closes the image-only gap: scanned statements now go
through OCR → geometry → reconciliation, the same proven path as native PDFs.

Backends (auto-selected; Vision preferred for accuracy, Tesseract as the
cross-platform fallback)
--------------------------------------------------------------
- macOS Vision: native, fast, high-accuracy. Normalized bottom-left coords.
- Tesseract: cross-platform (Linux/Windows/macOS), requires the `tesseract`
  binary + `pytesseract`. Top-left pixel coords (simpler conversion).

Coordinate conversion
---------------------
Both backends are converted to pdfplumber's POINTS, TOP-LEFT-ORIGIN system
(y increases downward, values in points = 1/72 inch):
  - Vision: scale normalized (0-1) by image px → flip y → px-to-points.
  - Tesseract: px are already top-left → just px-to-points (no y-flip).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# --- macOS Vision framework (guarded import) ---
try:
    import Quartz  # noqa: F401
    import Vision
    from Foundation import NSURL
    from CoreFoundation import CGRect  # noqa: F401

    VISION_AVAILABLE = True
except Exception:
    VISION_AVAILABLE = False

# --- Tesseract (cross-platform; guarded import) ---
try:
    import pytesseract
    from PIL import Image  # noqa: F401

    # Confirm the tesseract binary is actually callable, not just the Python pkg.
    try:
        pytesseract.get_tesseract_version()
        TESSERACT_AVAILABLE = True
    except Exception:
        TESSERACT_AVAILABLE = False
except Exception:
    TESSERACT_AVAILABLE = False


def is_available() -> bool:
    """True if ANY OCR backend (Vision or Tesseract) is available."""
    return VISION_AVAILABLE or TESSERACT_AVAILABLE


def active_backend() -> str:
    """Which backend will be used: 'vision', 'tesseract', or 'none'."""
    if VISION_AVAILABLE:
        return "vision"
    if TESSERACT_AVAILABLE:
        return "tesseract"
    return "none"


def _vision_words_for_image(image_path: str) -> List[Dict[str, Any]]:
    """Run Vision OCR on one image, returning raw observations with boxes.

    Each observation: {"text", "norm_x", "norm_y", "norm_w", "norm_h"}
    where (norm_x, norm_y) is the BOTTOM-LEFT corner (Vision convention).
    """
    if not VISION_AVAILABLE:
        return []
    try:
        url = NSURL.fileURLWithPath_(image_path)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(True)
        success, _err = handler.performRequests_error_([req], None)
        if not success:
            return []
        out = []
        for obs in req.results():
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue
            text = candidates[0].string()
            if not text or not text.strip():
                continue
            bb = obs.boundingBox()
            out.append(
                {
                    "text": text.strip(),
                    "norm_x": float(bb.origin.x),
                    "norm_y": float(bb.origin.y),
                    "norm_w": float(bb.size.width),
                    "norm_h": float(bb.size.height),
                }
            )
        return out
    except Exception as exc:
        print(f"⚠️ Vision OCR word extraction failed: {exc}")
        return []


def _vision_to_pdfplumber_words(
    vision_obs: List[Dict[str, Any]],
    img_width_px: int,
    img_height_px: int,
    dpi: int,
) -> List[Dict[str, Any]]:
    """Convert Vision observations to pdfplumber-style word dicts.

    Vision: normalized, bottom-left origin.
    pdfplumber: points (1/72"), top-left origin.
    """
    px_to_pt = 72.0 / dpi
    page_w_pt = img_width_px * px_to_pt
    page_h_pt = img_height_px * px_to_pt

    words = []
    for o in vision_obs:
        # Vision box: (norm_x, norm_y) is bottom-left; convert to pixel space.
        left_px = o["norm_x"] * img_width_px
        bottom_px = o["norm_y"] * img_height_px
        width_px = o["norm_w"] * img_width_px
        height_px = o["norm_h"] * img_height_px
        right_px = left_px + width_px
        top_px = img_height_px - (bottom_px + height_px)  # flip y to top-left
        bottom_from_top_px = img_height_px - bottom_px

        # Vision sometimes returns one multi-word string per observation. Split
        # it into individual words, distributing x evenly across the box, so the
        # geometry extractor's column clustering works on per-word granularity.
        text = o["text"]
        tokens = text.split()
        if len(tokens) == 1:
            words.append(
                {
                    "text": tokens[0],
                    "x0": left_px * px_to_pt,
                    "x1": right_px * px_to_pt,
                    "top": top_px * px_to_pt,
                    "bottom": bottom_from_top_px * px_to_pt,
                }
            )
        else:
            # Distribute tokens across the box width.
            token_w_px = width_px / len(tokens)
            for i, tok in enumerate(tokens):
                tok_left_px = left_px + i * token_w_px
                words.append(
                    {
                        "text": tok,
                        "x0": tok_left_px * px_to_pt,
                        "x1": (tok_left_px + token_w_px) * px_to_pt,
                        "top": top_px * px_to_pt,
                        "bottom": bottom_from_top_px * px_to_pt,
                    }
                )
    return words


def extract_words_from_pdf(
    pdf_path: str, dpi: int = 150, max_pages: int = 0
) -> List[List[Dict[str, Any]]]:
    """OCR every page of an image-only PDF, returning per-page word lists.

    Returns a list (one entry per page) of pdfplumber-style word dicts. An empty
    inner list means that page had no OCR text. Auto-selects the best available
    backend: macOS Vision (preferred for accuracy) or Tesseract (cross-platform).

    Args:
        pdf_path: path to the PDF.
        dpi: render resolution for OCR. 150 is a good accuracy/speed balance.
        max_pages: 0 = all pages; else cap (for speed during probing).
    """
    if not is_available():
        return []
    try:
        import pdfplumber

        backend = active_backend()
        all_pages: List[List[Dict[str, Any]]] = []
        with pdfplumber.open(pdf_path) as pdf:
            n = len(pdf.pages) if not max_pages else min(len(pdf.pages), max_pages)
            for idx in range(n):
                page = pdf.pages[idx]
                pix = page.to_image(resolution=dpi)
                img = pix.original
                w_px, h_px = img.size
                if backend == "vision":
                    # Vision needs a file URL.
                    import tempfile

                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp_path = tmp.name
                    img.save(tmp_path, format="PNG")
                    try:
                        obs = _vision_words_for_image(tmp_path)
                        words = _vision_to_pdfplumber_words(obs, w_px, h_px, dpi)
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                elif backend == "tesseract":
                    words = _tesseract_words_for_image(img, dpi)
                else:
                    words = []
                all_pages.append(words)
        return all_pages
    except Exception as exc:
        print(f"⚠️ OCR word extraction from PDF failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Tesseract backend (cross-platform)
# ---------------------------------------------------------------------------
def _tesseract_words_for_image(img: Any, dpi: int) -> List[Dict[str, Any]]:
    """Run Tesseract OCR on a PIL image, returning pdfplumber-style word dicts.

    Tesseract returns per-word boxes in PIXELS with a TOP-LEFT origin — the
    same orientation as pdfplumber, so conversion is just px → points (no y-flip,
    unlike Vision). We also drop low-confidence words to reduce OCR noise that
    would corrupt column clustering.
    """
    if not TESSERACT_AVAILABLE:
        return []
    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception as exc:
        print(f"⚠️ Tesseract OCR failed: {exc}")
        return []

    px_to_pt = 72.0 / dpi
    words: List[Dict[str, Any]] = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        # Drop low-confidence words (<30) — they're usually OCR noise that would
        # pollute column detection. -1 means Tesseract didn't score it.
        conf = data["conf"][i]
        try:
            conf_val = int(conf)
        except (ValueError, TypeError):
            conf_val = -1
        if conf_val >= 0 and conf_val < 30:
            continue
        left = data["left"][i]
        top = data["top"][i]
        width = data["width"][i]
        height = data["height"][i]
        words.append(
            {
                "text": text,
                "x0": left * px_to_pt,
                "x1": (left + width) * px_to_pt,
                "top": top * px_to_pt,
                "bottom": (top + height) * px_to_pt,
            }
        )
    return words
