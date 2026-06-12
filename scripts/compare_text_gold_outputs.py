from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_TAG_RE = re.compile(r"<image>.*?</image>", re.IGNORECASE | re.DOTALL)
DIALOGUE_RE = re.compile(r'"[^"\n]{8,}"')
PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}|\b(user|char)\b", re.IGNORECASE)
ASSISTANT_SLOP_RE = re.compile(
    r"\b(as an ai|i can't|i cannot|i'm unable|i apologize|how can i assist|"
    r"let me know if|is there anything else)\b",
    re.IGNORECASE,
)
USER_SPEAK_RE = re.compile(
    r"\b(you say|you reply|you ask|you whisper|you murmur|you think|you feel|"
    r"your thoughts|you decide|you realize)\b",
    re.IGNORECASE,
)


@dataclass
class Scores:
    total: float
    length: float
    image_tag: float
    dialogue: float
    narration: float
    agency: float
    cleanliness: float
    completion: float


def words(text: str) -> list[str]:
    return re.findall(r"\b[\w'-]+\b", text)


def image_tag_score(reply: str, reference: str) -> float:
    ref_has = bool(IMAGE_TAG_RE.search(reference))
    out_has = bool(IMAGE_TAG_RE.search(reply))
    if ref_has and out_has:
        return 1.0
    if not ref_has and not out_has:
        return 1.0
    return 0.0


def length_score(reply: str, reference: str) -> float:
    ref_len = max(len(words(reference)), 1)
    out_len = len(words(reply))
    ratio = out_len / ref_len
    if 0.65 <= ratio <= 1.35:
        return 1.0
    if 0.40 <= ratio < 0.65 or 1.35 < ratio <= 1.80:
        return 0.65
    if 0.25 <= ratio < 0.40 or 1.80 < ratio <= 2.40:
        return 0.35
    return 0.1


def dialogue_score(reply: str) -> float:
    quoted = DIALOGUE_RE.findall(reply)
    if len(quoted) >= 2:
        return 1.0
    if len(quoted) == 1:
        return 0.65
    # Some RP models use bare first-person prose; partial credit if there is a colon style line.
    if re.search(r"\b[A-Z][A-Za-z0-9_-]{1,20}:\s+", reply):
        return 0.45
    return 0.0


def narration_score(reply: str) -> float:
    has_action = bool(re.search(r"\*[^*]{12,}\*", reply)) or bool(
        re.search(r"\b(her|she|Echidna|Atago)\b.{0,80}\b(steps|leans|touches|smiles|tilts|moves|watches|traces|settles|kneels)\b", reply, re.IGNORECASE)
    )
    has_atmosphere = bool(
        re.search(r"\b(light|shadow|fire|room|scent|warm|air|silence|tea|door|floor|candle|lamplight)\b", reply, re.IGNORECASE)
    )
    if has_action and has_atmosphere:
        return 1.0
    if has_action or has_atmosphere:
        return 0.55
    return 0.15


def agency_score(reply: str) -> float:
    hits = USER_SPEAK_RE.findall(reply)
    if not hits:
        return 1.0
    if len(hits) <= 1:
        return 0.65
    return 0.25


def cleanliness_score(reply: str) -> float:
    penalties = 0
    if ASSISTANT_SLOP_RE.search(reply):
        penalties += 2
    if PLACEHOLDER_RE.search(reply):
        penalties += 1
    if reply.count("<image>") != reply.count("</image>"):
        penalties += 1
    if re.search(r"\b(system prompt|character profile|response contract)\b", reply, re.IGNORECASE):
        penalties += 2
    return max(0.0, 1.0 - penalties * 0.25)


def completion_score(reply: str, metrics: dict[str, Any]) -> float:
    reason = (metrics.get("done_reason") or "").lower()
    if reason in {"stop", "eos"}:
        return 1.0
    if reason == "length":
        # Some candidates hit length because they are usefully verbose, but it is still a product risk.
        return 0.55
    return 0.75 if reply.strip() else 0.0


def score_reply(reply: str, reference: str, metrics: dict[str, Any]) -> Scores:
    parts = {
        "length": length_score(reply, reference),
        "image_tag": image_tag_score(reply, reference),
        "dialogue": dialogue_score(reply),
        "narration": narration_score(reply),
        "agency": agency_score(reply),
        "cleanliness": cleanliness_score(reply),
        "completion": completion_score(reply, metrics),
    }
    total = (
        parts["length"] * 0.15
        + parts["image_tag"] * 0.12
        + parts["dialogue"] * 0.16
        + parts["narration"] * 0.20
        + parts["agency"] * 0.13
        + parts["cleanliness"] * 0.14
        + parts["completion"] * 0.10
    ) * 100
    return Scores(total=total, **parts)


def safe_preview(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def iter_turn_dirs(run_dirs: list[Path]) -> list[Path]:
    found: list[Path] = []
    for run_dir in run_dirs:
        found.extend(path.parent for path in run_dir.rglob("reply.txt"))
    return sorted(set(found))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare generated text replies against Perchance gold references.")
    parser.add_argument("run_dirs", nargs="+", type=Path, help="One or more text_gold/<sample> run dirs.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for turn_dir in iter_turn_dirs(args.run_dirs):
        reply_path = turn_dir / "reply.txt"
        ref_path = turn_dir / "reference_reply.txt"
        metrics_path = turn_dir / "metrics.json"
        if not reply_path.exists() or not ref_path.exists() or not metrics_path.exists():
            continue
        reply = reply_path.read_text(encoding="utf-8")
        reference = ref_path.read_text(encoding="utf-8")
        metrics = read_json(metrics_path)
        score = score_reply(reply, reference, metrics)
        rows.append(
            {
                "model": metrics.get("model"),
                "mode": metrics.get("mode"),
                "turn": metrics.get("user_turn_index", 0) + 1,
                "score": round(score.total, 1),
                "length": round(score.length, 2),
                "image_tag": round(score.image_tag, 2),
                "dialogue": round(score.dialogue, 2),
                "narration": round(score.narration, 2),
                "agency": round(score.agency, 2),
                "cleanliness": round(score.cleanliness, 2),
                "completion": round(score.completion, 2),
                "tokens_per_second": round(float(metrics.get("tokens_per_second") or 0.0), 1),
                "first_token_latency_s": round(float(metrics.get("first_token_latency_s") or 0.0), 2),
                "wall_time_s": round(float(metrics.get("wall_time_s") or 0.0), 2),
                "output_tokens": metrics.get("eval_count"),
                "done_reason": metrics.get("done_reason"),
                "reply_path": str(reply_path),
                "reference_path": str(ref_path),
                "reply_preview": safe_preview(reply),
            }
        )

    rows.sort(key=lambda row: (str(row["model"]), str(row["mode"]), int(row["turn"])))
    if args.output is None:
        common = args.run_dirs[-1]
        args.output = common / "quality_report.md"
    args.output.parent.mkdir(parents=True, exist_ok=True)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["model"]), str(row["mode"])), []).append(row)

    lines = [
        "# Text Gold Quality Report",
        "",
        "Scores are heuristic screeners, not final human judgment. Use them to find likely winners and obvious failures.",
        "",
        "## Aggregate",
        "",
        "| Model | Mode | Avg Score | Avg tok/s | Avg first token s | Turns |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for (model, mode), group in sorted(grouped.items()):
        avg_score = sum(row["score"] for row in group) / len(group)
        avg_tps = sum(row["tokens_per_second"] for row in group) / len(group)
        avg_ft = sum(row["first_token_latency_s"] for row in group) / len(group)
        lines.append(f"| `{model}` | `{mode}` | {avg_score:.1f} | {avg_tps:.1f} | {avg_ft:.2f} | {len(group)} |")

    lines.extend(
        [
            "",
            "## Per Reply",
            "",
            "| Model | Mode | Turn | Score | tok/s | First token s | Done | Reply |",
            "|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            f"`{row['model']}` | `{row['mode']}` | {row['turn']} | {row['score']} | "
            f"{row['tokens_per_second']} | {row['first_token_latency_s']} | {row['done_reason']} | "
            f"[reply]({Path(row['reply_path']).as_posix()}) |"
        )

    lines.extend(["", "## Previews", ""])
    for row in rows:
        lines.extend(
            [
                f"### {row['model']} / {row['mode']} / turn {row['turn']}",
                "",
                f"Score: {row['score']} | tok/s: {row['tokens_per_second']} | first token: {row['first_token_latency_s']}s",
                "",
                row["reply_preview"],
                "",
            ]
        )

    args.output.write_text("\n".join(lines), encoding="utf-8")
    (args.output.with_suffix(".json")).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
