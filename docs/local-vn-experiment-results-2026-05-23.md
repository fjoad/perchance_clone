# Local VN Experiment Results

Status: first end-to-end experiment pass complete
Date: May 23, 2026

## Goal

Test whether the local/offline visual-novel loop can meet the practical target:

- Perchance-style roleplay text quality or better
- first token within roughly 10 seconds
- text fast enough to stream comfortably
- image panels saved for manual review
- all model/cache storage on `F:`
- no new Conda/Python environment unless required

## Environment

Primary Python environment:

```text
F:\anaconda3\envs\companion_v1\python.exe
```

Primary model/cache storage:

```text
F:\ollama\models
F:\huggingface\models
```

F-only guardrail:

```text
scripts/f_only_env.py
scripts/audit_storage_paths.py
```

## Text Gold Sample

Gold sample extracted from Perchance export:

```text
outputs/research_gold_samples/echidna
```

The sample includes:

- character profile
- protagonist profile
- reminder note
- image prompt prefix/suffix/triggers
- user/assistant turn history
- reference assistant replies

## Text Models Tested

Practical models tested over three Perchance turns, two prompt modes:

- `qwen-uncensored`
- `dolphin-llama3`
- `dolphin-nemo`
- `hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M`
- `hf.co/mradermacher/Peach-2.0-9B-8k-Roleplay-GGUF:Q5_K_M`

Large experimental model tested over one turn:

- `fredrezones55/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:IQ4_XS`

## Text Output Locations

Full practical text run:

```text
outputs/research_runs/20260523_202918/text_gold/echidna
```

Qwen3.6 MoE one-turn check:

```text
outputs/research_runs/20260523_203524/text_gold/echidna
```

Combined quality report:

```text
outputs/research_runs/combined_text_quality_20260523.md
outputs/research_runs/combined_text_quality_20260523.json
```

## Text Results

Heuristic scores are screeners, not final human judgment. They reward similarity to the gold structure:

- good length
- dialogue/action balance
- image tag behavior
- no assistant slop
- no placeholders
- no obvious protagonist agency violations
- clean completion

| Model | Prompt Mode | Avg Score | Avg tok/s | Avg first token |
|---|---:|---:|---:|---:|
| `dolphin-llama3` | `direct_character` | 94.0 | 104.1 | 6.59s |
| `dolphin-nemo` | `direct_character` | 93.0 | 78.7 | 10.80s |
| `qwen-uncensored` | `hybrid_narrator` | 90.3 | 113.7 | 5.42s |
| `dolphin-nemo` | `hybrid_narrator` | 89.8 | 78.7 | 6.31s |
| `Peach-2.0-9B` | `hybrid_narrator` | 89.7 | 85.6 | 5.48s |
| `dolphin-llama3` | `hybrid_narrator` | 88.8 | 104.4 | 5.51s |
| `Peach-2.0-9B` | `direct_character` | 86.6 | 85.7 | 6.47s |
| `Dolphin-X1-8B` | `direct_character` | 86.4 | 104.3 | 6.52s |
| `Dolphin-X1-8B` | `hybrid_narrator` | 82.7 | 104.7 | 5.56s |
| `qwen-uncensored` | `direct_character` | 77.6 | 113.9 | 6.33s |
| `Qwen3.6-35B-A3B` | `hybrid_narrator` | 70.0 | 6.4 | 59.20s |
| `Qwen3.6-35B-A3B` | `direct_character` | 70.0 | 6.0 | 92.45s |

## Manual Read Notes

### `dolphin-llama3`

Best current balance of speed, structure, and direct character continuation.

Strengths:

- fastest high-scoring practical model
- consistently follows the gold structure
- writes compactly enough for the app loop
- keeps image tags and roleplay shape fairly well

Weaknesses:

- prose can be flatter than the target
- sometimes less vivid than the Perchance gold

### `dolphin-nemo`

Strong text quality, slower than `dolphin-llama3`.

Strengths:

- good continuity and atmosphere
- stronger prose density in some turns
- viable if quality beats speed in manual review

Weaknesses:

- lower tok/s
- cold first turn can be slow

### `Peach-2.0-9B`

Most interesting new specialized roleplay candidate.

Strengths:

- naturally roleplay-shaped
- good action/dialogue rhythm
- better "character chat" feel than many generic models
- fully VRAM-resident in real-flow tests

Weaknesses:

- occasional spacing/punctuation oddities
- can lean into format/style quirks
- slower than 8B Dolphin models, but still fast enough

### `Dolphin-X1-8B`

Fast and clean, but not clearly better than existing `dolphin-llama3`.

Strengths:

- fast
- fully VRAM-resident
- modern uncensored 8B candidate

Weaknesses:

- first real-flow reply was too short/flat
- one gold turn hit max length

### `qwen-uncensored`

Very fast but inconsistent prompt-mode behavior.

Strengths:

- fastest practical model
- hybrid narrator mode scored well

Weaknesses:

- direct character mode was weaker
- can be less stable as a roleplay engine

### `Qwen3.6-35B-A3B`

Not viable for current hardware/runtime target.

Strengths:

- richer opening prose in manual spot-check

Weaknesses:

- first token 59-92s
- about 6 tok/s
- both tested replies hit max token length
- not compatible with under-one-minute interactive loop on RTX 3080 12GB

## Image/Text Real App Flow

Run folder:

```text
outputs/diags/real_app_flow_20260523_201412
```

Policy:

```text
swap
```

Meaning:

- unload text before image generation
- unload image before text generation
- one GPU owner at a time

Results:

| Model | Image 1 | Text 1 | Image 2 | Text 2 | Text VRAM |
|---|---:|---:|---:|---:|---:|
| `Dolphin-X1-8B Q5_K_M` | 45.47s | 115.5 tok/s | 41.73s | 113.0 tok/s | 5.53 GiB |
| `Peach-2.0-9B Q5_K_M` | 27.58s | 96.4 tok/s | 41.40s | 96.0 tok/s | 6.14 GiB |

Both text models were fully VRAM-resident during text generation:

```text
CPU/RAM spill: 0.00 GiB
```

Manual image preference from review:

1. `hf_co_mradermacher_peach_2_0_9b_8k_roleplay_gguf_q5_k_m_image1_final.png`
2. `hf_co_dphn_dolphin_x1_8b_gguf_q5_k_m_image2_final.png`
3. `hf_co_dphn_dolphin_x1_8b_gguf_q5_k_m_image1_final.png`
4. `hf_co_mradermacher_peach_2_0_9b_8k_roleplay_gguf_q5_k_m_image2_final.png`

Important caveat: this was an Atago smoke test for the real image/text flow, not the final Perchance gold-image parity test. The final image test should use the extracted Echidna gold assets:

```text
outputs/research_gold_samples/echidna/image_prompt_prefix.txt
outputs/research_gold_samples/echidna/image_prompt_suffix.txt
outputs/research_gold_samples/echidna/image_prompt_triggers.txt
outputs/research_gold_samples/echidna/reference_replies.md
```

The image prompt should be constructed from:

- Perchance prefix: `painterly anime artwork`
- the generated or reference `<image>...</image>` scene description
- relevant character trigger text, especially Echidna's appearance
- Perchance suffix, including quality tags and the embedded negative prompt

This matters because the current image ranking may be mostly prompt/seed/layout driven, not text-model driven.

## Current Architecture Implication

The best current runtime strategy is **swap mode**, not co-residency.

Why:

- text remains fast when fully loaded after image unload
- image generation improved substantially with clean VRAM
- avoiding stale GPU ownership prevents weird slowdowns and failed runs

For now:

- use `dolphin-llama3` or `Peach-2.0-9B` as primary text candidates
- keep `dolphin-nemo` as quality challenger
- do not use Qwen3.6 MoE for the interactive loop
- run manual image review on saved `real_app_flow` outputs

## Storage Outcome

After experiments:

```text
F: about 28.9 GB free
C: recovered to about 24.1 GB free after clearing pip cache, NVIDIA shader cache, and one Python crash dump
```

The final audit showed no risky model/cache paths on `C:`.

## Next Decision

Manual review should choose between:

1. `dolphin-llama3 direct_character` as the speed/default baseline.
2. `Peach-2.0-9B hybrid_narrator` as the roleplay-specialized challenger.
3. `dolphin-nemo direct_character` as the larger-quality challenger.

After that, wire the chosen model/prompt mode into the app and keep swap-mode GPU ownership as the runtime coordinator policy.
