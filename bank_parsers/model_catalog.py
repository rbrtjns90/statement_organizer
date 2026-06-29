"""
Gemma 4 Model Catalog & Hardware-Aware Picker
==============================================
Lets users choose among all five Gemma 4 size variants (E2B, E4B, 12B,
26B-A4B, 31B) and quantizations, with recommendations based on their actual
hardware (RAM, GPU/VRAM, chip).

Data sources (all verified via Hugging Face API + Google model card, June 2026):
  - Official model card: https://ai.google.dev/gemma/docs/core/model_card_4
  - GGUF host: unsloth/gemma-4-{variant}-it-GGUF

The catalog covers the full family. The recommendation engine picks the best
model+quant that fits comfortably in the user's RAM (with overhead for context +
OS + vision mmproj), preferring higher quality when hardware allows.

RAM rule of thumb: file_size + ~2GB overhead (llama.cpp context, OS, app) +
~1GB for the vision mmproj when vision is enabled.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_BASE_URL = "https://huggingface.co/unsloth/gemma-4-{repo}-it-GGUF/resolve/main/"


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
@dataclass
class QuantOption:
    """One quantization of a model variant."""

    name: str          # "Q4_K_M"
    filename: str      # "gemma-4-E2B-it-Q4_K_M.gguf"
    size_gb: float     # file size
    quality: str       # "high" | "medium" | "low" (relative, for sorting)


@dataclass
class ModelVariant:
    """One Gemma 4 size variant (E2B, E4B, 12B, 26B-A4B, 31B)."""

    id: str            # "E2B"
    repo: str          # repo slug, e.g. "E2B" or "12b" (lowercase for 12B)
    label: str         # "Gemma 4 E2B"
    params: str        # "2.3B effective"
    description: str
    quants: List[QuantOption] = field(default_factory=list)
    mmproj_size_gb: float = 0.92   # vision projector size (F16)
    mmproj_filename: str = "mmproj-F16.gguf"
    notes: str = ""


def _build_catalog() -> List[ModelVariant]:
    """The verified Gemma 4 catalog (sizes from HF API, June 2026)."""
    return [
        ModelVariant(
            id="E2B", repo="E2B", label="Gemma 4 E2B",
            params="2.3B effective (5.1B total)",
            description="Smallest. Fast, low RAM. Great for laptops and entry-level machines. Native text + image + audio.",
            mmproj_size_gb=0.92,
            quants=[
                QuantOption("Q4_K_M", "gemma-4-E2B-it-Q4_K_M.gguf", 2.89, "medium"),
                QuantOption("Q5_K_M", "gemma-4-E2B-it-Q5_K_M.gguf", 3.13, "high"),
                QuantOption("Q6_K", "gemma-4-E2B-it-Q6_K.gguf", 4.19, "high"),
                QuantOption("Q8_0", "gemma-4-E2B-it-Q8_0.gguf", 4.70, "high"),
            ],
        ),
        ModelVariant(
            id="E4B", repo="E4B", label="Gemma 4 E4B",
            params="4.5B effective (8B total)",
            description="Balanced small model. Better quality than E2B, still laptop-friendly. Text + image + audio.",
            mmproj_size_gb=0.92,
            quants=[
                QuantOption("Q4_K_M", "gemma-4-E4B-it-Q4_K_M.gguf", 4.64, "medium"),
                QuantOption("Q5_K_M", "gemma-4-E4B-it-Q5_K_M.gguf", 5.11, "high"),
                QuantOption("Q6_K", "gemma-4-E4B-it-Q6_K.gguf", 6.59, "high"),
                QuantOption("Q8_0", "gemma-4-E4B-it-Q8_0.gguf", 7.63, "high"),
            ],
        ),
        ModelVariant(
            id="12B", repo="12b", label="Gemma 4 12B",
            params="11.95B",
            description="Strong all-rounder. Encoder-free unified multimodal (tiny mmproj). Text + image + audio. Best quality/RAM for mid-range machines.",
            mmproj_size_gb=0.16,
            notes="Unified architecture: very small vision projector.",
            quants=[
                QuantOption("Q4_K_M", "gemma-4-12b-it-Q4_K_M.gguf", 6.63, "medium"),
                QuantOption("Q5_K_M", "gemma-4-12b-it-Q5_K_M.gguf", 7.84, "high"),
                QuantOption("Q6_K", "gemma-4-12b-it-Q6_K.gguf", 9.11, "high"),
                QuantOption("Q8_0", "gemma-4-12b-it-Q8_0.gguf", 11.80, "high"),
            ],
        ),
        ModelVariant(
            id="26B-A4B", repo="26B-A4B", label="Gemma 4 26B-A4B (MoE)",
            params="25.2B total / 3.8B active",
            description="Mixture-of-Experts: only 3.8B params active per token (fast inference) but full 25.2B weights must fit in RAM. High quality, needs ample memory. Text + image.",
            mmproj_size_gb=1.11,
            notes="MoE: fast inference but full weights in RAM. Uses Unsloth-Dynamic quants.",
            quants=[
                QuantOption("UD-Q3_K_M", "gemma-4-26B-A4B-it-UD-Q3_K_M.gguf", 11.85, "medium"),
                QuantOption("UD-Q4_K_M", "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf", 15.78, "high"),
                QuantOption("UD-Q5_K_M", "gemma-4-26B-A4B-it-UD-Q5_K_M.gguf", 19.70, "high"),
                QuantOption("Q8_0", "gemma-4-26B-A4B-it-Q8_0.gguf", 25.02, "high"),
            ],
        ),
        ModelVariant(
            id="31B", repo="31B", label="Gemma 4 31B",
            params="30.7B",
            description="Largest dense model. Highest quality, needs a high-RAM workstation. Text + image (no audio).",
            mmproj_size_gb=1.12,
            notes="Highest quality; no audio support.",
            quants=[
                QuantOption("Q4_K_M", "gemma-4-31B-it-Q4_K_M.gguf", 17.07, "medium"),
                QuantOption("Q5_K_M", "gemma-4-31B-it-Q5_K_M.gguf", 20.17, "high"),
                QuantOption("Q6_K", "gemma-4-31B-it-Q6_K.gguf", 23.47, "high"),
                QuantOption("Q8_0", "gemma-4-31B-it-Q8_0.gguf", 30.39, "high"),
            ],
        ),
    ]


CATALOG: List[ModelVariant] = _build_catalog()


# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------
@dataclass
class HardwareProfile:
    """Detected hardware capabilities relevant to model selection."""

    total_ram_gb: float
    os: str                # "Darwin", "Windows", "Linux"
    arch: str              # "arm64", "x86_64"
    cpu_cores: int
    gpu_type: str          # "apple-silicon", "nvidia-cuda", "amd-rocm", "none"
    gpu_vram_gb: float = 0.0   # dedicated VRAM (0 for unified-memory Apple Silicon)
    chip_name: str = ""
    is_unified_memory: bool = False  # True for Apple Silicon (RAM = VRAM)


def detect_hardware() -> HardwareProfile:
    """Detect the host's hardware for model-size recommendations.

    Cross-platform: macOS, Linux, Windows. GPU/VRAM detection is best-effort
    (Apple Silicon unified memory; NVIDIA via nvidia-smi; else CPU-only).
    """
    os_name = platform.system()
    arch = platform.machine()
    cores = os.cpu_count() or 4

    # --- RAM ---
    ram_gb = _detect_ram_gb(os_name)

    # --- GPU ---
    gpu_type, gpu_vram, chip, unified = _detect_gpu(os_name, arch)

    return HardwareProfile(
        total_ram_gb=ram_gb,
        os=os_name,
        arch=arch,
        cpu_cores=cores,
        gpu_type=gpu_type,
        gpu_vram_gb=gpu_vram,
        chip_name=chip,
        is_unified_memory=unified,
    )


def _detect_ram_gb(os_name: str) -> float:
    try:
        if os_name == "Darwin":
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3)
        elif os_name == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / 1024 / 1024
        elif os_name == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass
    return 8.0  # conservative fallback


def _detect_gpu(os_name: str, arch: str) -> Tuple[str, float, str, bool]:
    """Returns (gpu_type, vram_gb, chip_name, is_unified_memory)."""
    # Apple Silicon: unified memory, Metal acceleration.
    if os_name == "Darwin" and arch == "arm64":
        try:
            import subprocess

            out = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
            return "apple-silicon", 0.0, out, True
        except Exception:
            return "apple-silicon", 0.0, "Apple Silicon", True

    # NVIDIA CUDA (Linux/Windows): probe nvidia-smi for VRAM.
    try:
        import subprocess

        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            text=True,
        ).strip()
        if out:
            line = out.splitlines()[0]
            parts = line.split(",")
            vram = float(parts[0].strip()) / 1024  # MiB -> GiB
            name = parts[1].strip() if len(parts) > 1 else "NVIDIA GPU"
            return "nvidia-cuda", vram, name, False
    except Exception:
        pass

    return "none", 0.0, "", False


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------
# Overhead beyond the model file: llama.cpp context/KV cache, the Python process,
# the OS, and the vision mmproj. Conservative to avoid OOM crashes.
_CONTEXT_OVERHEAD_GB = 2.0


@dataclass
class Recommendation:
    """A model+quant recommendation for a given hardware profile."""

    variant: ModelVariant
    quant: QuantOption
    total_size_gb: float       # model + mmproj
    required_ram_gb: float     # total_size + overhead
    fits: bool                 # does it fit in available RAM?
    reason: str


def _available_memory(hw: HardwareProfile) -> float:
    """Effective memory available for the model.

    Apple Silicon uses unified memory (RAM = VRAM), but ~25% is reserved for the
    OS/display, so budget ~75% of total. Dedicated GPUs use their VRAM directly.
    CPU-only systems use system RAM (budget ~70% to leave room for the OS).
    """
    if hw.is_unified_memory:
        return hw.total_ram_gb * 0.75
    if hw.gpu_vram_gb > 0:
        return hw.gpu_vram_gb
    return hw.total_ram_gb * 0.70


def recommend_models(hw: HardwareProfile, want_vision: bool = True) -> List[Recommendation]:
    """Rank all model+quant combos by (fits, quality, size) for the hardware.

    Returns the full ranked list; callers typically take the first that fits.
    """
    avail = _available_memory(hw)
    recs: List[Recommendation] = []
    for variant in CATALOG:
        for quant in variant.quants:
            mmproj = variant.mmproj_size_gb if want_vision else 0.0
            total = quant.size_gb + mmproj
            required = total + _CONTEXT_OVERHEAD_GB
            fits = required <= avail
            recs.append(
                Recommendation(
                    variant=variant, quant=quant, total_size_gb=total,
                    required_ram_gb=required, fits=fits,
                    reason=(
                        f"{variant.label} {quant.name} needs {required:.1f} GB "
                        f"({avail:.0f} GB available) — {'fits' if fits else 'too large'}"
                    ),
                )
            )
    # Sort: fits first, then highest quality, then smaller (faster).
    quality_rank = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: (not r.fits, quality_rank.get(r.quant.quality, 1), -r.total_size_gb))
    return recs


def best_recommendation(hw: HardwareProfile, want_vision: bool = True) -> Optional[Recommendation]:
    """The single best model+quant that fits the hardware (highest quality that fits)."""
    for r in recommend_models(hw, want_vision):
        if r.fits:
            return r
    return None  # nothing fits


# ---------------------------------------------------------------------------
# URLs & download helpers
# ---------------------------------------------------------------------------
def model_url(variant: ModelVariant, quant: QuantOption) -> str:
    """Full Hugging Face download URL for a model file."""
    base = _BASE_URL.format(repo=variant.repo)
    return base + quant.filename


def mmproj_url(variant: ModelVariant) -> str:
    """Full download URL for the variant's vision mmproj."""
    base = _BASE_URL.format(repo=variant.repo)
    return base + variant.mmproj_filename


# ---------------------------------------------------------------------------
# Interactive picker (CLI)
# ---------------------------------------------------------------------------
def interactive_pick(hw: Optional[HardwareProfile] = None, want_vision: bool = True) -> Optional[Recommendation]:
    """Interactive CLI model picker. Returns the user's choice or None.

    Shows hardware, the recommended model, and all options ranked by fit.
    """
    if hw is None:
        hw = detect_hardware()
    print("=" * 70)
    print("  Gemma 4 Model Selection")
    print("=" * 70)
    gpu_desc = hw.chip_name or hw.gpu_type
    print(f"  Hardware: {hw.os} {hw.arch} | {hw.total_ram_gb:.0f} GB RAM | {gpu_desc}")
    if hw.is_unified_memory:
        print(f"  (Apple Silicon unified memory — ~{_available_memory(hw):.0f} GB usable for models)")
    elif hw.gpu_vram_gb > 0:
        print(f"  (NVIDIA GPU with {hw.gpu_vram_gb:.1f} GB VRAM)")
    print()

    recs = recommend_models(hw, want_vision)
    best = best_recommendation(hw, want_vision)
    if best:
        print(f"  ⭐ Recommended: {best.variant.label} {best.quant.name} "
              f"({best.total_size_gb:.1f} GB, needs {best.required_ram_gb:.1f} GB)")
        print(f"     {best.variant.description}")
        print()

    print("  Available models (ranked by fit + quality):")
    print(f"  {'#':>3}  {'Model':<26} {'Quant':<10} {'Size':>7} {'Need':>7}  Fit")
    print("  " + "-" * 66)
    fitting = [r for r in recs if r.fits]
    for i, r in enumerate(fitting, 1):
        flag = " ⭐" if (best and r.variant.id == best.variant.id and r.quant.name == best.quant.name) else ""
        print(f"  {i:>3}  {r.variant.label:<26} {r.quant.name:<10} "
              f"{r.total_size_gb:>5.1f}GB {r.required_ram_gb:>5.1f}GB  ✓{flag}")
    if len(fitting) < len(recs):
        print("  " + "-" * 66)
        print("  (too large for this hardware — not shown)")

    if not fitting:
        print("\n  ⚠️ No models fit comfortably in your available memory.")
        print("     Consider a machine with more RAM, or use the OpenAI backend instead.")
        return None

    try:
        choice = input(f"\n  Select model [1-{len(fitting)}, or Enter for recommended]: ").strip()
        if not choice:
            return best
        idx = int(choice) - 1
        if 0 <= idx < len(fitting):
            return fitting[idx]
        print("  Invalid choice.")
        return None
    except (ValueError, EOFError, KeyboardInterrupt):
        return best
