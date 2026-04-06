# New Chat Handoff

Status: current canonical handoff for future chats and future engineers  
Last updated: April 6, 2026  
Read this first before using older docs.

## 1. What This Project Is

This repo is a local-first AI companion / roleplay app inspired by Candy.ai and Perchance, but it is **not** trying to become a perfect clone of either one.

The real product goal is:

- a persistent companion character
- story-first roleplay and chat
- layered memory and continuity
- local image generation that matches the current scene and character
- an experience that feels like an ongoing relationship rather than isolated prompts

The current MVP direction is closer to:

- one active character at a time
- story timeline UI
- text replies first
- manual image generation per scene beat
- one heavy model on the GPU at a time

This file is meant to be usable as:

- a project onboarding summary
- a future-chat context seed
- a practical "what matters now" guide

The older [project-master-dossier.md](/f:/projects/perchance_clone/perchance_clone/docs/project-master-dossier.md) still exists, but it is now historical background and partially outdated. Start here first.

## 2. Current Working State

### What already works

- FastAPI app with Jinja/HTMX-style server-rendered timeline UI
- multi-character database-backed app shell
- character modal/editor
- user profile storage
- story timeline with separate user, text, and image blocks
- per-image `Regenerate Image` and `Delete Image`
- per-text-block `Regenerate` and `Delete Block`
- model runtime coordinator that switches between text and image ownership of the GPU
- Qwen-based text roleplay path that now produces much stronger in-character replies after prompt restructuring
- local SDXL image generation using the selected working hires recipe
- standalone terminal roleplay testers for stock Qwen, uncensored Qwen, Meissa, and Llama comparison
- Hugging Face cache safely rooted on `F:\huggingface\models`

### What is good enough and frozen for now

- image backend recipe:
  - SDXL two-stage hires flow
  - default preset `768 -> 1536`
  - latent hires path
  - `DPM++ 2M`
  - `CFG 7`
  - `denoise 0.7`
  - A1111-style img2img step math
- text model baseline:
  - `Qwen/Qwen2.5-7B-Instruct`
  - 4-bit NF4 runtime quantization through `bitsandbytes`
- core prompt architecture:
  - generic roleplay task contract
  - generic format contract
  - stitched context blocks for user, character, dossier, memory, lore, and recent chat
- one-model-at-a-time runtime strategy on the 12 GB RTX 3080

### What is still experimental

- uncensored Qwen comparison
- Meissa comparison
- Meta Llama comparison
- exact best text model for longform roleplay
- final memory quality / continuity tuning
- final load/unload UX feedback in the UI

## 3. Current Product Shape

### User-facing flow

The intended loop right now is:

1. choose a character
2. send a message
3. receive a roleplay/story reply
4. optionally generate an image for that exact scene beat
5. continue the story

Images are **not** auto-generated on every turn in the current MVP. They are attached manually to a specific assistant/text block.

### Current MVP goal

Finish a believable local roleplay companion loop with:

- strong in-character text responses
- stable continuity across turns
- usable model switching on one GPU
- scene-appropriate image generation
- enough UI clarity that the experience feels coherent

## 4. Architecture Snapshot

### App stack

- backend: FastAPI
- UI: Jinja templates + custom JS/CSS
- persistence: SQLite
- text model: local Hugging Face Transformers path
- image model: local SDXL pipeline
- runtime model switching: app-managed, not external orchestration software

### Runtime and DB layout

- DB path: `runtime/companion_v1_app.sqlite3`
- runtime/temp/cache/log-like data: `runtime/`
- app-generated images: `outputs/app/`
- experimental image parity outputs: `outputs/repro/` and related output folders

### Text pipeline

The text side currently works like this:

1. build a generic roleplay task prompt
2. build a generic format/writing contract
3. stitch in:
   - user profile
   - character profile shell
   - full character dossier
   - pinned memory
   - rolling summary
   - lore entries if any
   - recent chat window
4. render macros such as `{{char}}` and `{{user}}`
5. send the final assembled prompt to the text model

Important design choice:

- the core prompt stays generic
- character/world facts are stitched in dynamically
- do **not** hardcode world-specific content into the reusable task prompt

### Image pipeline

The image side currently uses a local SDXL two-stage hires flow:

1. stage 1 base render
2. latent upscale
3. stage 2 refinement with A1111-style step math

The default live preset is:

- `768 -> 1536`
- latent hires
- `DPM++ 2M`
- `CFG 7`
- `denoise 0.7`
- `clip_skip 2`

### Model coordination

The runtime coordinator currently follows this rule:

- only one heavy model owns the GPU at a time

Behavior:

- app startup preloads text
- text generation keeps text loaded
- image generation unloads text, loads image, generates, unloads image, then starts reloading text

This is intentional because the local 12 GB RTX 3080 does not comfortably hold the full text and image stacks at once.

### Memory and prompt structure

Current layered memory stack:

- pinned memory
- rolling summary
- optional lorebook retrieval
- recent chat window

Current defaults:

- recent messages window: 12
- lore recent turns: 4
- lore max retrieved entries: 3
- summary refresh cadence: every 6 user turns

## 5. Repo Map

### Primary source files to work in

- [app/main.py](/f:/projects/perchance_clone/perchance_clone/app/main.py)
  - FastAPI routes and app flow
- [app/config.py](/f:/projects/perchance_clone/perchance_clone/app/config.py)
  - model IDs, image defaults, HF paths, runtime settings
- [app/db.py](/f:/projects/perchance_clone/perchance_clone/app/db.py)
  - schema helpers, seeding, characters, user profile, memory storage
- [app/services/prompts.py](/f:/projects/perchance_clone/perchance_clone/app/services/prompts.py)
  - text prompt assembly and stitched blocks
- [app/services/text_generation.py](/f:/projects/perchance_clone/perchance_clone/app/services/text_generation.py)
  - local text model loading and reply generation
- [app/services/image_generation.py](/f:/projects/perchance_clone/perchance_clone/app/services/image_generation.py)
  - SDXL hires flow and image progress handling
- [app/services/runtime_coordinator.py](/f:/projects/perchance_clone/perchance_clone/app/services/runtime_coordinator.py)
  - text/image load/unload ownership
- [app/services/memory.py](/f:/projects/perchance_clone/perchance_clone/app/services/memory.py)
  - lore retrieval and related memory helpers
- [app/static/app.js](/f:/projects/perchance_clone/perchance_clone/app/static/app.js)
  - timeline interactions, generation actions, client-side status handling
- [app/static/style.css](/f:/projects/perchance_clone/perchance_clone/app/static/style.css)
  - app styling
- [app/templates/partials/story_timeline.html](/f:/projects/perchance_clone/perchance_clone/app/templates/partials/story_timeline.html)
  - main timeline block rendering
- [app/templates/partials/right_panel_v2.html](/f:/projects/perchance_clone/perchance_clone/app/templates/partials/right_panel_v2.html)
  - profile/status side panel
- [app/templates/partials/character_form.html](/f:/projects/perchance_clone/perchance_clone/app/templates/partials/character_form.html)
  - character editor

### Important test and support scripts

- [scripts/test_roleplay_chat.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_roleplay_chat.py)
  - generic standalone roleplay chat harness
- [scripts/test_roleplay_chat_qwen.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_roleplay_chat_qwen.py)
  - stock Qwen wrapper
- [scripts/test_roleplay_chat_qwen_uncensored.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_roleplay_chat_qwen_uncensored.py)
  - uncensored Qwen wrapper
- [scripts/test_roleplay_chat_meissa.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_roleplay_chat_meissa.py)
  - Meissa wrapper
- [scripts/test_roleplay_chat_llama.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_roleplay_chat_llama.py)
  - Meta Llama comparison wrapper
- [scripts/test_text_model_load.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_text_model_load.py)
  - text load sanity checker
- [scripts/test_nova_hires_repro.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_nova_hires_repro.py)
  - image recipe reproduction test
- [scripts/test_nova_resolution_sweep.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_nova_resolution_sweep.py)
  - resolution sweep for image tradeoff testing
- [scripts/test_a1111_api_hires.py](/f:/projects/perchance_clone/perchance_clone/scripts/test_a1111_api_hires.py)
  - A1111 API comparison path

### Supporting docs

- [docs/companion-v1-runbook.md](/f:/projects/perchance_clone/perchance_clone/docs/companion-v1-runbook.md)
  - app/runtime basics
- [docs/text-roleplay-runbook.md](/f:/projects/perchance_clone/perchance_clone/docs/text-roleplay-runbook.md)
  - current text baseline and comparison commands
- [docs/image-parity-tests.md](/f:/projects/perchance_clone/perchance_clone/docs/image-parity-tests.md)
  - image recipe and parity tests
- [docs/project-master-dossier.md](/f:/projects/perchance_clone/perchance_clone/docs/project-master-dossier.md)
  - older historical dossier

## 6. What To Edit, What To Ignore

### Safe / intended places to work

- `app/`
- `scripts/`
- `docs/`
- launchers:
  - `run_companion_v1.cmd`
  - `run_companion_v1.ps1`

### Reference-only or generated areas

- `outputs/`
  - generated images and test artifacts
  - do not treat as source of truth
- `runtime/`
  - DB, temp/cache/runtime state
  - do not treat as source
- `playground.ipynb`
  - useful archaeology, not current product truth
- `tags/` and `tags_build/`
  - old/reference assets, currently ignored
- loose root images such as `*.png`, `*.jpg`, `*.jpeg`
  - experimental artifacts, not source files

### Do not browse first

If starting a new chat or debugging a feature, do **not** start by opening:

- generated image folders under `outputs/`
- loose image artifacts in the repo root
- runtime DB/cache/temp files
- notebooks as the main current reference

Start with:

1. this handoff
2. the runbooks
3. `app/`
4. `scripts/`

## 7. Model Status

### Current text baseline

- model: `Qwen/Qwen2.5-7B-Instruct`
- load style: runtime 4-bit NF4 quantization via `bitsandbytes`
- current status: best working baseline so far

### Current image baseline

- SDXL-based local image path
- selected default preset:
  - `768 -> 1536`
  - latent hires
  - `DPM++ 2M`
  - `CFG 7`
  - `denoise 0.7`
- current status: good enough for MVP while text work continues

### Comparison models already set up

- stock Qwen baseline
- `Orion-zhen/Qwen2.5-7B-Instruct-Uncensored`
- `Orion-zhen/Meissa-Qwen2.5-7B-Instruct`
- `meta-llama/Meta-Llama-3.1-8B-Instruct`
- historical reference / fallback benchmark:
  - `PygmalionAI/Pygmalion-3-12B`

### VRAM lessons learned

- Qwen fits much better than Llama on the current full prompt stack
- Llama 3.1 8B did not look like a model reload bug; peak VRAM showed generation-time spikes close to the 12 GB ceiling
- Qwen also spikes, but with more headroom
- current conclusion:
  - keep Qwen as default
  - treat Llama as comparison-only unless a more efficient backend is introduced

## 8. Known Issues and Historical Fixes

Each item below captures:

- symptom
- cause
- fix or mitigation
- current status

### 8.1 Early repo state was mostly notebooks and artifacts

- Symptom:
  - no coherent app foundation
  - progress existed mainly in notebooks and chat history
- Cause:
  - project evolved through long chat sessions and notebook experimentation
- Fix:
  - built a real `app/` structure with runtime DB, services, templates, and scripts
- Status:
  - solved structurally, but old artifacts remain as reference only

### 8.2 App template crash: `image_cfg` undefined

- Symptom:
  - app loaded with a 500 error from Jinja
- Cause:
  - template expected `image_cfg` but route context did not provide it
- Fix:
  - updated route/template flow so the context is always passed where needed
- Status:
  - solved

### 8.3 Image generation parity rabbit hole

- Symptom:
  - repeated quality mismatches between local Python image path and A1111 expectations
- Cause:
  - many interacting variables:
    - scheduler
    - denoise
    - latent vs PIL upscale
    - img2img step math
    - base resolution
- Fix:
  - isolated tests in `scripts/`
  - resolution sweep
  - A1111-style parameter reproduction
  - selected the current `768 -> 1536` default as the time/quality sweet spot
- Status:
  - solved enough for MVP; exact parity chasing should stop unless absolutely needed

### 8.4 A1111 API misunderstanding

- Symptom:
  - user asked whether A1111 could be imported as a clean Python library instead of calling a running API
- Cause:
  - A1111 is an application with internals plus an HTTP API, not a clean reusable official library package
- Fix:
  - clarified supported path vs ugly embed path
  - added direct A1111 API test script
- Status:
  - clarified; local app is not currently using A1111 API as the main backend

### 8.5 Runtime VRAM conflict between text and image

- Symptom:
  - text and image models could not comfortably coexist on the 12 GB GPU
- Cause:
  - two heavy local model stacks on one card
- Fix:
  - runtime coordinator now enforces one active heavy model at a time
- Status:
  - structurally solved, UX still needs clearer feedback

### 8.6 Model load/unload UI is still too opaque

- Symptom:
  - button is clicked, but the app can sit visually "idle" while models are unloading/loading
- Cause:
  - coordinator state exists, but UI feedback does not yet surface all pre-generation and reload phases clearly enough
- Fix:
  - partial status work already exists
  - not yet fully polished
- Status:
  - still open

### 8.7 Polling spam in terminal

- Symptom:
  - terminal flooded with repeated `GET /status` lines
- Cause:
  - frontend polling approach was too noisy
- Fix:
  - moved toward a single status stream / lighter status handling
- Status:
  - largely solved

### 8.8 Image blocks were initially nested incorrectly

- Symptom:
  - multiple images were piling up inside a single text block and could not be independently deleted/regenerated
- Cause:
  - image data was attached as nested content instead of first-class timeline blocks
- Fix:
  - each image is now its own block with its own controls
- Status:
  - solved

### 8.9 Resolution control readability

- Symptom:
  - inline resolution dropdown was hard to read
- Cause:
  - Windows select styling on dark theme
- Fix:
  - explicit dark option styling
- Status:
  - solved enough

### 8.10 Prompt architecture originally made Qwen look worse than it was

- Symptom:
  - responses were flat, assistant-like, too short, or too dialogue-only
- Cause:
  - prompt was too weak, too generic, badly ordered, and introduced character/world facts before clearly defining the task
- Fix:
  - rewrote the task prompt as a detailed generic roleplay contract
  - added strong format contract
  - re-ordered prompt so the model understands the job before stitched data arrives
- Status:
  - major improvement; this was one of the biggest breakthroughs

### 8.11 Character data was over-compressed

- Symptom:
  - rich character sheets were being flattened into short summaries, reducing voice/identity quality
- Cause:
  - too much of the card was collapsed into compact fields
- Fix:
  - added `character_dossier`
  - made the full dossier authoritative
  - reduced the shorter `CHARACTER_PROFILE` to a minimal identity shell
- Status:
  - mostly solved, though future tuning may still further reduce redundancy

### 8.12 Text roleplay initially lacked scene action and continuity

- Symptom:
  - too much dialogue, weak narration, weak memory feeling
- Cause:
  - prompt structure and writing contract were underspecified
- Fix:
  - stronger roleplay task/format prompts
  - full user profile and full character dossier
  - layered memory structure
- Status:
  - improved significantly, still needs tuning and validation in longer sessions

### 8.13 Llama looked promising but hit a VRAM cliff

- Symptom:
  - first turn worked, second turn often maxed VRAM and crashed
- Cause:
  - generation-time peak memory on full prompt stack, not a second model load
- Fix:
  - added peak VRAM tracking to the standalone tester
  - concluded Llama is comparison-only for now
- Status:
  - understood, not selected as main app model

### 8.14 Standalone tester showed stray `cmd`/typeahead input

- Symptom:
  - REPL sometimes started as if a first user message had already been entered
- Cause:
  - likely Windows console/typeahead junk in the input buffer, not an intentional seeded conversation turn
- Fix:
  - added buffer flush handling around REPL input in the shared tester harness
- Status:
  - mitigated

### 8.15 Hugging Face cache/download safety on `F:` vs `C:`

- Symptom:
  - earlier fear and prior experience that model downloads could fill `C:` and destabilize the machine
- Cause:
  - default HF/Transformers cache behavior if not explicitly redirected
- Fix:
  - hard-set:
    - `HF_HOME=F:\huggingface\models`
    - `HF_HUB_CACHE=F:\huggingface\models\hub`
    - `HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub`
  - launchers and testers use these paths
- Status:
  - solved operationally, but future model downloads should still be checked carefully

## 9. Current Character and World Status

### Current seeded live-test characters

- Astra Vale
- Test Mira
- Atago

### Most important live test setup

The current best roleplay test character is Atago, with:

- full dossier
- source media awareness (`Azur Lane`)
- full Anon profile/background
- generic roleplay task contract + stitched context

This is currently the main path for validating text quality.

## 10. What Is Still Left To Do

### Core work still left before MVP feels solid

- finish text quality tuning
  - stronger continuity over longer sessions
  - verify pinned memory, rolling summary, and lore behavior
  - confirm scene/action balance stays good outside the current best examples
- improve model load/unload UX
  - immediate feedback when a generation request is accepted
  - show loading/unloading/reloading states clearly
- compare stock Qwen vs uncensored Qwen vs Meissa
  - choose the best practical text model
- add more app-side telemetry if needed
  - token counts
  - peak VRAM
  - timing visibility

### Secondary / polish work

- further UI refinement toward a stronger visual-novel / Perchance-style presentation
- improve editability of user/character fields
- smoother progress feedback on image generation finalization
- possible longer-session memory behavior tuning

### Things that are intentionally not the current priority

- perfect image parity with A1111
- dual-model simultaneous residency on the GPU
- turning old notebooks into product code
- digging through output images as if they were source files

## 11. Quick Start Commands

### Launch the app

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
run_companion_v1.cmd
```

PowerShell alternative:

```powershell
.\run_companion_v1.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

### Mock mode

Text + image mocked:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set COMPANION_USE_MOCK_TEXT=1
set COMPANION_USE_MOCK_IMAGE=1
run_companion_v1.cmd
```

Mock text, real image:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set COMPANION_USE_MOCK_TEXT=1
set COMPANION_USE_MOCK_IMAGE=
run_companion_v1.cmd
```

### Standalone text tests

Stock Qwen:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
python scripts\test_roleplay_chat_qwen.py --character atago --disable-warmup --local-only
```

Uncensored Qwen:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
python scripts\test_roleplay_chat_qwen_uncensored.py --character atago --disable-warmup
```

Meissa:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
python scripts\test_roleplay_chat_meissa.py --character atago --disable-warmup
```

Llama comparison:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
python scripts\test_roleplay_chat_llama.py --character atago --disable-warmup --local-only
```

Print the exact stitched prompt:

```cmd
cd /d F:\projects\perchance_clone\perchance_clone
conda activate companion_v1
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
python scripts\test_roleplay_chat_qwen.py --character atago --disable-warmup --show-system-prompt
```

### Image test references

See:

- [docs/image-parity-tests.md](/f:/projects/perchance_clone/perchance_clone/docs/image-parity-tests.md)

### Cache safety reminder

Always keep model/cache env vars on `F:` when downloading or testing new models:

- `HF_HOME=F:\huggingface\models`
- `HF_HUB_CACHE=F:\huggingface\models\hub`
- `HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub`

## 12. Final Guidance For Future Chats

If opening a fresh chat:

1. read this file first
2. treat it as the current canonical handoff
3. use the runbooks for detail
4. treat [project-master-dossier.md](/f:/projects/perchance_clone/perchance_clone/docs/project-master-dossier.md) as archival background only
5. do not waste time browsing generated image artifacts or old notebook content unless the task explicitly requires archaeology

The main current truth of the project lives in:

- `app/`
- `scripts/`
- `docs/`

The main current unresolved problems are:

- final text quality/model choice
- final memory/continuity behavior
- clear load/unload UI feedback

Everything else should be treated as secondary.

## 13. Starter Prompt For The Next Chat

Use this as the opening prompt for a fresh chat:

```text
Read F:\projects\perchance_clone\perchance_clone\docs\new-chat-handoff.md first and treat it as the current canonical project handoff.

Then help me continue work on this local-first AI companion / roleplay app without re-deriving the project from scratch.

Important:
- Prefer the current app code and docs over old notebooks or generated artifacts.
- Do not start by browsing loose images, outputs, runtime files, or other generated media unless the task explicitly requires it.
- Treat F:\projects\perchance_clone\perchance_clone\docs\project-master-dossier.md as historical background only.
- The current text baseline is Qwen/Qwen2.5-7B-Instruct with the stitched roleplay prompt architecture.
- The current image baseline is the local SDXL latent hires flow at 768 -> 1536.
- The current hardware constraint is one heavy model on the GPU at a time on a 12 GB RTX 3080.

After reading the handoff, summarize:
1. what the project is
2. what currently works
3. what is still left before the MVP feels solid
4. the exact files you expect to work in for the requested task

Then continue with the task I give you next.
```
