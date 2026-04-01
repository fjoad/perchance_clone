from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from urllib import error, request


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = ROOT_DIR / "outputs" / "a1111_api_repro"
DEFAULT_PROMPT = (
    "Atago from azur lane in a sunlit grand estate kitchen, wearing a classic black-and-white maid uniform "
    "with delicate lace trim. Her straight hair is tied in a high side ponytail, loose strands framing her face. "
    "She's holding a silver tea tray with polished china, standing near a marble countertop where golden croissants "
    "rest on a porcelain plate. Sunlight streams through tall arched windows, illuminating copper pots hanging on the "
    "wall and casting warm highlights on her porcelain skin. Her amber eyes sparkle with playful warmth, and she has "
    "a gentle, inviting smile. Soft anime-style rendering, 4K detail, luminous natural lighting."
)
DEFAULT_NEGATIVE = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A1111 API hires-fix txt2img test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative", default=DEFAULT_NEGATIVE)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--sampler-name", default="DPM++ 2M")
    parser.add_argument("--scheduler", default="Automatic")
    parser.add_argument("--denoise", type=float, default=0.7)
    parser.add_argument("--hr-scale", type=float, default=2.0)
    parser.add_argument("--hr-second-pass-steps", type=int, default=0)
    parser.add_argument("--hr-upscaler", default="Latent")
    parser.add_argument("--clip-skip", type=int, default=2)
    parser.add_argument("--checkpoint-name", default="")
    parser.add_argument("--prefix", default="a1111_api_hires")
    return parser.parse_args()


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=3600) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    args = parse_args()
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUTS_DIR / f"{args.prefix}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    override_settings = {"CLIP_stop_at_last_layers": args.clip_skip}
    if args.checkpoint_name:
        override_settings["sd_model_checkpoint"] = args.checkpoint_name

    payload = {
        "prompt": args.prompt,
        "negative_prompt": args.negative,
        "steps": args.steps,
        "cfg_scale": args.cfg,
        "width": args.width,
        "height": args.height,
        "seed": args.seed,
        "sampler_name": args.sampler_name,
        "scheduler": args.scheduler,
        "enable_hr": True,
        "hr_scale": args.hr_scale,
        "hr_upscaler": args.hr_upscaler,
        "hr_second_pass_steps": args.hr_second_pass_steps,
        "denoising_strength": args.denoise,
        "save_images": False,
        "send_images": True,
        "override_settings": override_settings,
    }

    url = f"{args.base_url.rstrip('/')}/sdapi/v1/txt2img"
    print(f"[api] POST {url}")
    print(f"[cfg] sampler={args.sampler_name} scheduler={args.scheduler}")
    print(f"[cfg] base={args.width}x{args.height} hr_scale={args.hr_scale} denoise={args.denoise}")
    print(f"[cfg] hr_upscaler={args.hr_upscaler} hr_second_pass_steps={args.hr_second_pass_steps}")
    print(f"[cfg] clip_skip={args.clip_skip} checkpoint_name={args.checkpoint_name or '<current model>'}")

    try:
        start = time.perf_counter()
        response = post_json(url, payload)
        elapsed = time.perf_counter() - start
    except error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(
                "A1111 responded, but /sdapi/v1/txt2img was not found.\n"
                "That usually means A1111 is running without --api, or the base URL/port is wrong.\n"
                "Try launching A1111 with --api and then opening http://127.0.0.1:7860/docs in your browser.\n"
                f"Error: HTTP {exc.code}"
            )
        raise SystemExit(f"A1111 API returned HTTP {exc.code}: {exc.reason}")
    except error.URLError as exc:
        raise SystemExit(
            "Could not reach the A1111 API.\n"
            "WinError 10061 means nothing is listening on that host/port.\n"
            "Start A1111 with --api first, then rerun this test.\n"
            f"Error: {exc}"
        )

    images = response.get("images") or []
    if not images:
        raise SystemExit("A1111 API returned no images.")

    image_b64 = images[0]
    image_data = base64.b64decode(image_b64)
    image_path = run_dir / "final.png"
    image_path.write_bytes(image_data)

    settings_path = run_dir / "settings.txt"
    settings_path.write_text(
        "\n".join(
            [
                f"base_url={args.base_url}",
                f"sampler_name={args.sampler_name}",
                f"scheduler={args.scheduler}",
                f"width={args.width}",
                f"height={args.height}",
                f"steps={args.steps}",
                f"cfg={args.cfg}",
                f"seed={args.seed}",
                f"hr_scale={args.hr_scale}",
                f"hr_upscaler={args.hr_upscaler}",
                f"hr_second_pass_steps={args.hr_second_pass_steps}",
                f"denoise={args.denoise}",
                f"clip_skip={args.clip_skip}",
                f"checkpoint_name={args.checkpoint_name or '<current model>'}",
                "",
                "PROMPT:",
                args.prompt,
                "",
                "NEGATIVE:",
                args.negative,
                "",
                "INFO:",
                response.get("info", ""),
            ]
        ),
        encoding="utf-8",
    )

    raw_json_path = run_dir / "response.json"
    raw_json_path.write_text(json.dumps(response, indent=2), encoding="utf-8")

    print(f"[done] elapsed={elapsed:.1f}s")
    print(f"[save] final={image_path}")
    print(f"[save] settings={settings_path}")
    print(f"[save] response={raw_json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
