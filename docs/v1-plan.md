# Companion App V1 Vertical Slice

## Summary

Build one complete local-first companion app slice end to end before doing any model comparisons. Use the existing repo as the umbrella project, but start the real app in a new clean subfolder and new clean conda env on `F:`. Freeze the stack for v1:

- Text model: `Qwen2.5-7B-Instruct`
- Roleplay benchmark/fallback only: `Pygmalion-3-12B`
- Image checkpoint: `F:\huggingface\models\novaAnimeXL_ilV120.safetensors`
- Hugging Face root: `F:\huggingface\models`
- UI: FastAPI + Jinja + HTMX + custom modern CSS
- Image generation: A1111 `Hires.fix` equivalent by default

The image pipeline must follow the official A1111 pattern: generate at a lower base resolution, upscale, then run a second `img2img` refinement pass. Do not ship v1 with one-stage `txt2img` as the default path.

## Key Changes

### Foundation

- Keep the current repo at `F:\projects\perchance_clone\perchance_clone`.
- Treat the existing notebooks and generated assets as reference only.
- Build the app in new directories:
  - `app/` for source code
  - `runtime/` for SQLite, logs, and generated summaries
  - `outputs/app/` for app-created images
- Create a fresh env such as `F:\anaconda3\envs\companion_v1`.
- Keep all intentional assets on `F:`:
  - HF cache/downloads continue under `F:\huggingface\models\hub`
  - local `.safetensors` checkpoints continue directly under `F:\huggingface\models`

### UI and App Shape

- Do not use React for v1.
- Use a Python-first local web app:
  - FastAPI
  - Uvicorn
  - Jinja templates
  - HTMX for partial updates
  - custom dark modern CSS with a polished Candy-like feel
- Reason for the decision:
  - no Node toolchain is currently on PATH
  - the machine is already biased toward Python/conda
  - the first milestone is a working product loop, not frontend infrastructure
- Revisit React only after the first vertical slice works and only if the UI complexity actually justifies the split frontend.

### Character System

Implement the app as multi-character from the start.

Native character schema:

- `id`
- `slug`
- `display_name`
- `persona_summary`
- `personality_traits`
- `speaking_style`
- `backstory`
- `relationship_frame`
- `boundaries`
- `appearance`
- `example_dialogue`
- `default_visual_style`
- `is_active`

Behavior:

- character list in sidebar
- basic create/edit form in v1
- no formal Perchance parser in v1
- user-provided Perchance cards will be manually adapted into this schema
- the implementation should assume multiple characters already, even if only one real card is available initially

### Chat and Memory

Persist everything in SQLite under `runtime/`.

Core records:

- `Character`
- `Conversation`
- `Message`
- `MemorySnapshot`
- `ImageRequest`

Memory design for v1:

- recent message history
- pinned facts
- rolling summary
- optional manually managed notes later, but not in v1

Per-message flow:

1. load active character
2. load conversation
3. load pinned memory
4. load latest rolling summary
5. assemble hidden prompt from system rules + character fields + memory + recent turns + current user message
6. generate assistant reply with `Qwen2.5-7B-Instruct`
7. save reply
8. update rolling summary on a fixed cadence such as every 6 user turns

Do not add vector search, embeddings, or multi-model orchestration in v1.

### Text Model Strategy

- Use one general model first for:
  - roleplay/chat
  - memory summarization
  - scene extraction
  - image prompt composition
- Keep `Pygmalion-3-12B` only as the evaluation fallback if the implemented loop shows a clear RP-quality deficit.
- Do not load a second always-on orchestration model.

### Image Pipeline

Implement the official `Hires.fix` equivalent as the default generation path.

Use the notebook’s proven SDXL pattern, aligned with A1111’s documented behavior:

1. build scene summary from active character + current conversation context
2. compose positive/negative prompts internally
3. stage 1 `txt2img` at lower base resolution
4. upscale the stage-1 image
5. stage 2 `img2img` refinement at target resolution using the same prompt conditioning
6. save final image and generation metadata

Initial defaults:

- checkpoint: `novaAnimeXL_ilV120.safetensors`
- stage 1 base size: `512x512`
- target size: `1024x1024`
- upscale method: latent/simple upscale path for v1
- second pass enabled by default
- denoise strength and hires settings centralized in one config object, not scattered in code
- sampler/steps/CFG also centralized in config

Important implementation constraint:

- the app must expose image generation as a companion-aware feature, not a raw prompt playground
- the image request should always combine:
  - persistent appearance data
  - current scene summary
  - hidden prompt composition
- identity consistency should be designed into the flow now, even if v1 starts with prompt-based appearance anchoring before stronger reference conditioning is added

### Routes and Behavior

Internal app routes should cover:

- app shell
- character list
- character create/edit
- conversation view per character
- send message
- trigger image generation
- serve generated images

The app should feel like one product shell:

- left sidebar for characters
- center pane for chat
- right pane or drawer for companion info and image generation/output

## Test Plan

The first milestone is complete when all of these are true:

- The app starts from the new clean env on `F:`.
- All intentional runtime data stays on `F:`.
- `HF_HOME` is set to `F:\huggingface\models`.
- The app can load the chosen text model and SDXL checkpoint from the expected locations.
- The user can create, edit, and select characters.
- The user can chat with a selected character across multiple turns.
- Conversations persist after restart.
- Rolling summaries are created and reused.
- The user can generate an image from the active character and current scene.
- The image path uses the two-stage hires workflow, not one-stage `txt2img` only.
- The UI looks like a modern product shell rather than a notebook wrapper or generic admin page.
- No model comparison work is required to reach this milestone.

## Assumptions

- The current real HF layout is correct and should be preserved:
  - cache/downloads under `F:\huggingface\models\hub`
  - `.safetensors` checkpoints directly under `F:\huggingface\models`
- The existing notebook code is the reference source for local model loading and the SDXL two-stage flow.
- The user will provide one or more Perchance companion cards after the schema is in place.
- Those cards will be manually adapted into the native schema in v1.
- React is intentionally deferred to avoid setup friction and keep the first build slice focused on shipping the actual companion loop.
