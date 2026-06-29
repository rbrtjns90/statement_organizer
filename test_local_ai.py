#!/usr/bin/env python3
"""
Local AI Smoke Test
-------------------
Verifies that the downloaded Gemma 4 GGUF + mmproj load correctly via the
AIClient and can actually generate a transaction category. Run this once the
download into models/ is complete.

Usage:
    python test_local_ai.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bank_parsers.ai_client import get_ai_client, reset_ai_client, load_ai_settings


def main():
    print("=== Local AI Smoke Test ===\n")

    # Force a fresh client (in case config changed since import).
    reset_ai_client()
    settings = load_ai_settings()
    print(f"local_model_path : {settings['local_model_path']}")
    print(f"  exists? {os.path.exists(settings['local_model_path'])}")
    if os.path.exists(settings["local_model_path"]):
        size_gb = os.path.getsize(settings["local_model_path"]) / 1e9
        print(f"  size: {size_gb:.2f} GB")
    print(f"local_mmproj_path: {settings.get('local_mmproj_path')}")
    print(f"  exists? {os.path.exists(settings.get('local_mmproj_path', ''))}")
    print(f"preferred_backend: {settings['preferred_backend']}")
    print(f"local_supports_vision (config): {settings['local_supports_vision']}")
    print()

    # Sanity: warn if files are missing or suspiciously small (partial download).
    issues = []
    for key in ("local_model_path", "local_mmproj_path"):
        p = settings.get(key, "")
        if not p or not os.path.exists(p):
            issues.append(f"{key} missing: {p}")
        elif os.path.getsize(p) < 50_000_000:  # < 50MB = clearly incomplete
            issues.append(f"{key} looks incomplete: {os.path.getsize(p)/1e6:.1f} MB")
    if issues:
        print("⚠️ Issues detected (wait for the download to finish):")
        for i in issues:
            print(f"   - {i}")
        print("\nRe-run this script once both files are fully downloaded.")
        return 1

    client = get_ai_client()

    # This is where the model actually loads (lazy).
    print("Loading model (first call may take ~30-60s)...")
    t0 = time.time()
    available = client.available
    print(f"  available: {available} ({time.time()-t0:.1f}s)")
    print(f"  describe:  {client.describe()}")
    print(f"  active_backend: {client.active_backend}")
    print(f"  local vision capable: {client._local.supports_vision}")
    if not available:
        print("\n❌ No backend became available. Check the model path and llama-cpp-python.")
        return 1

    # Real test: categorize one transaction via text.
    print("\n--- Text categorization test ---")
    from bank_parsers.categorizer import load_categories

    categories = load_categories()
    cat_list = list(categories.keys())
    prompt = (
        "Categorize this business transaction into exactly one category.\n"
        f"Allowed categories: {', '.join(cat_list)}\n"
        "Transaction: PP*APPLE.COM/BILL 402-935-7733 CA\n"
        'Return ONLY JSON: {"category": "<exact name>"}'
    )
    t0 = time.time()
    resp = client.chat_text(prompt, max_tokens=60, temperature=0)
    print(f"  backend: {resp.backend} ({time.time()-t0:.1f}s)")
    print(f"  raw response: {resp.text!r}")
    from bank_parsers.ai_client import extract_json_object

    payload = extract_json_object(resp.text)
    if payload and "category" in payload:
        print(f"  parsed category: {payload['category']}")
        print("\n✅ Local AI is working — text categorization succeeded.")
    else:
        print("\n⚠️ Model loaded but returned unparseable output.")
        print("   This is normal on a first run if the chat template needs tuning;")

    print("\nSmoke test complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
