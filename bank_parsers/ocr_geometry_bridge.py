"""
OCR-to-Geometry Bridge
======================
Bridges macOS Vision OCR output back into the geometry extraction pipeline.

WHY THIS EXISTS
---------------
The geometry extractor (geometry_extractor.py) needs per-word coordinates
(x0, x1, top) to detect columns and parse transaction lines. Native text-layer
PDFs provide these via pdfplumber's `extract_words()`. But for IMAGE-ONLY PDFs,
there's no text layer — only OCR'd text, which loses all positional information.

This module runs macOS Vision OCR with bounding boxes and converts the results
into the same word-dict format pdfplumber produces:
    {"text": str, "x0": float, "x1": float, "top": float, "bottom": float, ...}

The geometry extractor can then consume these exactly as if they came from a
text-layer PDF. This closes the image-only gap: scanned statements now go
through OCR → geometry → reconciliation, the same proven path as native PDFs.

Coordinate conversion
---------------------
Vision uses a NORMALIZED, BOTTOM-LEFT-ORIGIN coordinate system (y increases
upward, values 0-1). pdfplumber uses a POINTS, TOP-LEFT-ORIGIN system (y
increases downward, values in points = 1/72 inch). We convert by:
    - scaling normalized (0-1) by the rendered image pixel dimensions
    - converting pixels to points (points = pixels / dpi * 72)
    - flipping y: pdfplumber_top = page_height_pts - vision_bottom_pts

macOS-only. On non-Mac systems this module is a no-op (VISION_AVAILABLE=False).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# macOS Vision framework (guarded import)
try:
    import Quartz
    import Vision
    from Foundation import NSURL
    from CoreFoundation import CGRect

    VISION_AVAILABLE = True
except Exception:
    VISION_AVAILABLE = False


def is_available() -> bool:
    """True if macOS Vision OCR is available on this system."""
    return VISION_AVAILABLE


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
    inner list means that page had no OCR text.

    Args:
        pdf_path: path to the PDF.
        dpi: render resolution for OCR. 150 is a good accuracy/speed balance.
        max_pages: 0 = all pages; else cap (for speed during probing).
    """
    if not VISION_AVAILABLE:
        return []
    try:
        import pdfplumber
        from PIL import Image
        import io
        import tempfile

        all_pages: List[List[Dict[str, Any]]] = []
        with pdfplumber.open(pdf_path) as pdf:
            n = len(pdf.pages) if not max_pages else min(len(pdf.pages), max_pages)
            for idx in range(n):
                page = pdf.pages[idx]
                # Render the page to a PNG in a temp file (Vision needs a URL).
                pix = page.to_image(resolution=dpi)
                img = pix.original
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                img.save(tmp_path, format="PNG")
                try:
                    w_px, h_px = img.size
                    obs = _vision_words_for_image(tmp_path)
                    words = _vision_to_pdfplumber_words(obs, w_px, h_px, dpi)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                all_pages.append(words)
        return all_pages
    except Exception as exc:
        print(f"⚠️ OCR word extraction from PDF failed: {exc}")
        return []
