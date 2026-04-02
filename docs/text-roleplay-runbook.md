# Text Roleplay Runbook

Status: working baseline for text-roleplay tuning  
Last updated: April 2, 2026

## Baseline

The current text baseline is:

- model family: `Qwen/Qwen2.5-7B-Instruct`
- quantization: 4-bit NF4 through `bitsandbytes`
- prompt style: generic longform roleplay contract plus stitched context blocks
- context layers:
  - task contract
  - format contract
  - user profile
  - character profile shell
  - full character dossier
  - pinned memory
  - rolling summary
  - retrieved lore entries
  - recent chat window

## Important Prompt Decision

The core task prompt stays generic.

It should describe:

- what a roleplay model is supposed to do
- how to write
- how to handle narration, dialogue, and continuity
- how to avoid assistant-style output

It should **not** hardcode world facts or character facts.

Those are supplied dynamically by the stitched blocks:

- `USER_PROFILE`
- `CHARACTER_PROFILE`
- `CHARACTER_DOSSIER`
- `PINNED_MEMORY`
- `ROLLING_SUMMARY`
- `LOREBOOK`

## Working Character Focus

The current best live test character is `Atago`.

Important note:

- the full Atago dossier should be treated as the authoritative characterization
- the shorter profile shell is only there as identity metadata
- the full dossier is the main roleplay source

## Current Runtime Behavior

- app startup preloads text
- image generation unloads text, loads image, generates, unloads image, then begins reloading text
- only one heavy model should own the GPU at a time on the 12 GB RTX 3080

## Hugging Face Cache Safety

Text and image model downloads must stay on `F:`.

Current cache roots:

- `HF_HOME=F:\huggingface\models`
- `HF_HUB_CACHE=F:\huggingface\models\hub`
- `HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub`

Do not allow model downloads to spill onto `C:` again.

## Terminal Test Commands

### Qwen baseline

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_roleplay_chat_qwen.py --character atago --disable-warmup
```

### Show the exact stitched prompt

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_roleplay_chat_qwen.py --character atago --disable-warmup --show-system-prompt
```

### Generic tester

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
python scripts\test_roleplay_chat.py --character atago --disable-warmup
```

## Comparison Goal

The next model comparison target is the official Meta Llama 3.1 8B instruct model.

Planned comparison candidate:

- `meta-llama/Meta-Llama-3.1-8B-Instruct`

Important:

- this model is gated on Hugging Face
- use a local Hugging Face login or token on the machine
- keep the cache rooted on `F:\huggingface\models`

## What "Good" Looks Like

A good reply should:

- stay in character
- include narration and dialogue, not dialogue-only text
- move the scene forward
- remember emotional and factual continuity
- avoid generic assistant tone
- feel vivid and specific rather than abstract

## Known Next Work

- more text-quality tuning against live Atago outputs
- better model load/unload UI feedback
- Llama-family side-by-side comparison
