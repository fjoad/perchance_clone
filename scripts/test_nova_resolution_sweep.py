from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
REPRO_SCRIPT = ROOT_DIR / "scripts" / "test_nova_hires_repro.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a square 2x resolution sweep for the Nova hires repro test.")
    parser.add_argument(
        "--base-sizes",
        type=int,
        nargs="+",
        default=[512, 640, 768, 896, 1024],
        help="Square base resolutions to test. Final resolution is base * 2.",
    )
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--hires-steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--denoise", type=float, default=0.7)
    parser.add_argument("--clip-skip", type=int, default=2)
    parser.add_argument("--scheduler", default="dpmpp_2m")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--prefix", default="nova_a1111_resolution_sweep")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not REPRO_SCRIPT.exists():
        raise FileNotFoundError(f"Could not find repro script: {REPRO_SCRIPT}")

    base_sizes = sorted(dict.fromkeys(args.base_sizes))
    print("[sweep] using fixed settings:")
    print(
        f"[sweep] scheduler={args.scheduler} upscale_mode=latent "
        f"a1111_img2img_step_math=True steps={args.steps} hires_steps={args.hires_steps} "
        f"cfg={args.cfg} denoise={args.denoise} clip_skip={args.clip_skip} seed={args.seed}"
    )

    for base in base_sizes:
        target = base * 2
        prefix = f"{args.prefix}_{base}to{target}"
        cmd = [
            sys.executable,
            str(REPRO_SCRIPT),
            "--upscale-mode",
            "latent",
            "--a1111-img2img-step-math",
            "--scheduler",
            args.scheduler,
            "--steps",
            str(args.steps),
            "--hires-steps",
            str(args.hires_steps),
            "--cfg",
            str(args.cfg),
            "--denoise",
            str(args.denoise),
            "--base-width",
            str(base),
            "--base-height",
            str(base),
            "--width",
            str(target),
            "--height",
            str(target),
            "--clip-skip",
            str(args.clip_skip),
            "--seed",
            str(args.seed),
            "--prefix",
            prefix,
        ]
        print()
        print(f"[sweep] running {base} -> {target}")
        print("[sweep] " + " ".join(cmd))
        if args.dry_run:
            continue
        subprocess.run(cmd, check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
