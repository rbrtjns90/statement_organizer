#!/usr/bin/env python3
"""
Gemma 4 Model Downloader
========================
Interactive CLI that detects your hardware, recommends the best Gemma 4 model
variant + quantization, and downloads it (plus the vision mmproj) into models/.

Usage:
    python download_model.py                # interactive: detect HW, pick, download
    python download_model.py --list         # just show recommendations, no download
    python download_model.py --variant 12B --quant Q4_K_M   # non-interactive
    python download_model.py --no-vision    # skip the mmproj (text-only)

The downloaded model is then picked up automatically by the AIClient
(config/ai_settings.json is updated with the chosen paths).
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bank_parsers.model_catalog import (
    CATALOG,
    Recommendation,
    best_recommendation,
    detect_hardware,
    interactive_pick,
    mmproj_url,
    model_url,
    recommend_models,
)
from bank_parsers.ai_client import load_ai_settings, save_ai_settings

_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def _download(url: str, dest: str) -> None:
    """Download a file with a progress bar."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"  ⬇️  {os.path.basename(dest)} ...")
    try:
        # urllib doesn't have a built-in progress bar; use a callback.
        def _reporthook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(100, downloaded * 100 / total_size)
                bar = "█" * int(pct / 2) + "-" * (50 - int(pct / 2))
                sys.stdout.write(f"\r     [{bar}] {pct:5.1f}% ")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, dest, reporthook=_reporthook)
        sys.stdout.write("\n")
        size_gb = os.path.getsize(dest) / 1e9
        print(f"  ✅ Saved {dest} ({size_gb:.2f} GB)")
    except Exception as exc:
        print(f"\n  ❌ Download failed: {exc}")
        # Clean up partial file.
        if os.path.exists(dest):
            os.remove(dest)
        raise


def _find_variant(variant_id: str):
    for v in CATALOG:
        if v.id.lower() == variant_id.lower():
            return v
    return None


def _update_settings(model_path: str, mmproj_path: str, want_vision: bool) -> None:
    """Persist the chosen model paths into config/ai_settings.json."""
    settings = load_ai_settings()
    settings["local_model_path"] = model_path
    if want_vision and mmproj_path:
        settings["local_mmproj_path"] = mmproj_path
        settings["local_supports_vision"] = True
    else:
        settings["local_supports_vision"] = False
    save_ai_settings(settings)
    print(f"\n  ⚙️  Updated config/ai_settings.json:")
    print(f"     local_model_path = {model_path}")
    if want_vision and mmproj_path:
        print(f"     local_mmproj_path = {mmproj_path}")
        print(f"     local_supports_vision = True")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="show recommendations only, no download")
    ap.add_argument("--variant", default=None, help="model variant ID (E2B, E4B, 12B, 26B-A4B, 31B)")
    ap.add_argument("--quant", default=None, help="quantization name (e.g. Q4_K_M)")
    ap.add_argument("--no-vision", action="store_true", help="skip the vision mmproj")
    args = ap.parse_args()

    want_vision = not args.no_vision
    hw = detect_hardware()

    # --- Select model ---
    if args.variant and args.quant:
        # Non-interactive: explicit choice.
        variant = _find_variant(args.variant)
        if not variant:
            print(f"❌ Unknown variant '{args.variant}'. Choose from: {[v.id for v in CATALOG]}")
            return 1
        quant = next((q for q in variant.quants if q.name.lower() == args.quant.lower()), None)
        if not quant:
            print(f"❌ Unknown quant '{args.quant}' for {variant.label}. "
                  f"Choose from: {[q.name for q in variant.quants]}")
            return 1
        rec = None
        for r in recommend_models(hw, want_vision):
            if r.variant.id == variant.id and r.quant.name == quant.name:
                rec = r
                break
        if rec is None:
            rec = Recommendation(variant, quant, quant.size_gb, quant.size_gb + 2, True, "explicit")
    else:
        # Interactive picker.
        rec = interactive_pick(hw, want_vision)
        if rec is None:
            return 1

    print(f"\n  Selected: {rec.variant.label} {rec.quant.name}")
    print(f"  {rec.reason}")
    if not rec.fits:
        print(f"  ⚠️  Warning: this may exceed your available memory "
              f"(needs {rec.required_ram_gb:.1f} GB, {_available_str(hw)} available).")
        try:
            ans = input("  Continue anyway? [y/N]: ").strip().lower()
            if ans != "y":
                print("  Aborted.")
                return 0
        except (EOFError, KeyboardInterrupt):
            return 0

    if args.list:
        print("\n  (--list mode: not downloading)")
        return 0

    # --- Download model ---
    model_dest = os.path.join(_MODELS_DIR, rec.quant.filename)
    if os.path.exists(model_dest):
        print(f"\n  ✓ Model already present: {model_dest} ({os.path.getsize(model_dest)/1e9:.2f} GB)")
    else:
        print(f"\n  Downloading {rec.variant.label} {rec.quant.name} ({rec.quant.size_gb:.1f} GB)...")
        _download(model_url(rec.variant, rec.quant), model_dest)

    # --- Download mmproj (vision) ---
    mmproj_dest = ""
    if want_vision:
        mmproj_dest = os.path.join(_MODELS_DIR, rec.variant.mmproj_filename)
        if os.path.exists(mmproj_dest):
            print(f"  ✓ mmproj already present: {mmproj_dest}")
        else:
            print(f"\n  Downloading vision projector ({rec.variant.mmproj_size_gb:.1f} GB)...")
            _download(mmproj_url(rec.variant), mmproj_dest)

    # --- Persist settings ---
    _update_settings(model_dest, mmproj_dest, want_vision)
    print("\n  🎉 Done. The local AI model is ready to use.")
    return 0


def _available_str(hw) -> str:
    from bank_parsers.model_catalog import _available_memory
    return f"{_available_memory(hw):.0f} GB"


if __name__ == "__main__":
    raise SystemExit(main())
