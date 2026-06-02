"""Generate per-show podcast cover art using SDXL on the local GPU.

Writes assets/cover-{slug}.jpg at 3000x3000 (Spotify-recommended size) for each
digest show defined in SHOWS below.

First run downloads ~7 GB of SDXL weights into D:/FLUX (cache dir reused from
the original FLUX plan — name kept for continuity). Subsequent runs hit the
cache and only re-do inference.

Why SDXL not FLUX-schnell: FLUX-schnell is Apache 2.0 but its HF repo is gated
(requires `huggingface-cli login` + accepting terms on the model page). SDXL is
unrestricted and produces editorial-grade abstract covers without that friction.
To switch to FLUX later: HF login, then swap MODEL_ID + use FluxPipeline with
num_inference_steps=4, guidance_scale=0.0.

Usage:
    python scripts/gen_covers.py                # all three shows
    python scripts/gen_covers.py mfm            # just MFM Rounds
    python scripts/gen_covers.py mfm fetal      # any subset

Iterate by editing the (seed, prompt) tuple for a show and re-running just
that slug — output overwrites assets/cover-{slug}.jpg.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Route Hugging Face cache to D:\ (laptop C:\ is tight). Must be set BEFORE
# importing diffusers / transformers / huggingface_hub.
os.environ.setdefault("HF_HOME", r"D:\FLUX")

import torch  # noqa: E402
from diffusers import (  # noqa: E402
    StableDiffusionXLImg2ImgPipeline,
    StableDiffusionXLPipeline,
)
from PIL import Image  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"

# Each show: (seed, prompt). Seed is fixed for reproducibility — bump it (or
# tweak the prompt) to regenerate a different variation.
SHOWS: dict[str, tuple[int, str]] = {
    "mfm": (
        42,
        "Editorial podcast cover, two-panel medical monitor layout, top "
        "panel flat minimalist silhouette of symmetric fetal brain, bottom "
        "panel smooth rolling contraction wave curves, thin grid "
        "background, deep navy and warm cream palette",
    ),
    "fetal": (
        11,
        "Editorial podcast cover art, abstract topographic ridge lines "
        "transitioning into branching neural and vascular patterns, deep "
        "indigo and electric coral palette, futuristic frontier medical "
        "aesthetic, minimalist composition, square format, high contrast, "
        "no text",
    ),
    # NOTE: the deployed assets/cover-ai.jpg is externally sourced (GPT-image,
    # 2026-06-01) — SDXL fought every "classic neural-net diagram" attempt
    # across multiple seeds. Lines on the deployed cover were thickened via
    # scripts/thicken_lines.py for thumbnail legibility. This prompt is kept
    # as a last-known SDXL attempt for reference; rerunning `gen_covers.py ai`
    # will NOT reproduce the deployed cover.
    "ai": (
        42,
        "Editorial podcast cover, classic abstract neural network diagram "
        "with layered columns of circular nodes connected by thin lines, "
        "mint green and graphite palette, technical AI radiology "
        "aesthetic, minimalist composition",
    ),
}

MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
NATIVE_SIZE = 1024  # SDXL's native training size; upscale after.
TARGET_SIZE = 3000  # Spotify-recommended podcast cover dimension.
NEGATIVE_PROMPT = (
    "text, letters, words, typography, watermark, logo, signature, "
    "low quality, blurry, jpeg artifacts, cluttered, busy, ugly, "
    "amateur, oversaturated, cartoon, illustration of person, faces, hands, "
    "sharp spikes, jagged peaks, narrow points, spiky waveform, "
    "detailed gyri, anatomical wrinkles"
)


def _load_pipe() -> StableDiffusionXLPipeline:
    print(f"[gen_covers] HF_HOME={os.environ['HF_HOME']}")
    print(f"[gen_covers] loading {MODEL_ID} (first run downloads ~7 GB)…")
    t0 = time.time()
    pipe = StableDiffusionXLPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
        variant="fp16",
        use_safetensors=True,
    )
    # Stage modules onto GPU only when running — fits 16 GB VRAM with headroom.
    pipe.enable_model_cpu_offload()
    print(f"[gen_covers] pipeline ready in {time.time() - t0:.1f}s")
    return pipe


def _load_img2img_pipe() -> StableDiffusionXLImg2ImgPipeline:
    print(f"[gen_covers] HF_HOME={os.environ['HF_HOME']}")
    print(f"[gen_covers] loading {MODEL_ID} img2img (reuses cache)…")
    t0 = time.time()
    pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
        variant="fp16",
        use_safetensors=True,
    )
    pipe.enable_model_cpu_offload()
    print(f"[gen_covers] img2img pipeline ready in {time.time() - t0:.1f}s")
    return pipe


def _gen_one(pipe: StableDiffusionXLPipeline, slug: str, seed: int, prompt: str) -> Path:
    out = ASSETS / f"cover-{slug}.jpg"
    print(f"[gen_covers] {slug}: seed={seed}")
    t0 = time.time()
    generator = torch.Generator(device="cuda").manual_seed(seed)
    image = pipe(
        prompt=prompt,
        negative_prompt=NEGATIVE_PROMPT,
        num_inference_steps=35,
        guidance_scale=7.0,
        height=NATIVE_SIZE,
        width=NATIVE_SIZE,
        generator=generator,
    ).images[0]
    print(f"[gen_covers] {slug}: inference {time.time() - t0:.1f}s, upscaling…")
    image = image.resize((TARGET_SIZE, TARGET_SIZE), Image.LANCZOS)
    ASSETS.mkdir(parents=True, exist_ok=True)
    image.save(out, "JPEG", quality=92, optimize=True)
    size_kb = out.stat().st_size // 1024
    print(f"[gen_covers] {slug}: wrote {out.name} ({size_kb} KB)")
    return out


def _edit_one(
    pipe: StableDiffusionXLImg2ImgPipeline,
    slug: str,
    seed: int,
    prompt: str,
    strength: float = 0.65,
) -> Path:
    """Img2img edit: use the existing cover-{slug}.jpg as the init image.

    Preserves rough composition (color blocking, layout) while pushing the
    content toward the new prompt. strength ~0.5 keeps original tight, ~0.8
    becomes nearly a new generation. 0.65 is a moderate edit.
    """
    out = ASSETS / f"cover-{slug}.jpg"
    if not out.exists():
        raise FileNotFoundError(
            f"no existing cover at {out}; run without --edit first to generate one"
        )
    init = Image.open(out).convert("RGB").resize(
        (NATIVE_SIZE, NATIVE_SIZE), Image.LANCZOS
    )
    print(f"[gen_covers] {slug}: editing existing cover (seed={seed}, strength={strength})")
    t0 = time.time()
    generator = torch.Generator(device="cuda").manual_seed(seed)
    image = pipe(
        prompt=prompt,
        negative_prompt=NEGATIVE_PROMPT,
        image=init,
        num_inference_steps=40,
        guidance_scale=7.5,
        strength=strength,
        generator=generator,
    ).images[0]
    print(f"[gen_covers] {slug}: inference {time.time() - t0:.1f}s, upscaling…")
    image = image.resize((TARGET_SIZE, TARGET_SIZE), Image.LANCZOS)
    image.save(out, "JPEG", quality=92, optimize=True)
    size_kb = out.stat().st_size // 1024
    print(f"[gen_covers] {slug}: wrote {out.name} ({size_kb} KB)")
    return out


def main(argv: list[str]) -> int:
    raw = argv[1:]
    edit_mode = "--edit" in raw
    strength = 0.65
    requested: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok == "--edit":
            pass
        elif tok == "--strength":
            i += 1
            strength = float(raw[i])
        else:
            requested.append(tok)
        i += 1
    requested = requested or list(SHOWS.keys())
    unknown = [s for s in requested if s not in SHOWS]
    if unknown:
        print(
            f"[gen_covers] unknown shows: {unknown}; valid: {list(SHOWS)}",
            file=sys.stderr,
        )
        return 2
    if edit_mode:
        pipe = _load_img2img_pipe()
        for slug in requested:
            seed, prompt = SHOWS[slug]
            _edit_one(pipe, slug, seed, prompt, strength=strength)
    else:
        pipe = _load_pipe()
        for slug in requested:
            seed, prompt = SHOWS[slug]
            _gen_one(pipe, slug, seed, prompt)
    print("[gen_covers] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
