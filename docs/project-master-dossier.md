# Project Master Dossier

Status: canonical project context file
Last updated: May 27, 2026
Location: `docs/project-master-dossier.md`
Derivative export status: no PDF generated because no local PDF converter was found in the current environment without adding dependencies

## May 23, 2026 Target Refresh

The current product target has sharpened from a broad "AI companion app" into a local illustrated visual novel/storybook engine.

Read these first for current work:

- `docs/current-implementation-status-2026-05-28.md`: latest safe runtime baseline, guarded evidence, and immediate productization status
- `docs/local-vn-engine-target.md`: current product target, latency bar, quality bar, and evaluation standard
- `docs/local-vn-engine-research-2026-05.md`: current local model/backend research and experiment order
- `docs/local-vn-engine-deep-dive-2026-05-23.md`: broader current-space research across offline/cloud, text models, image models, runtimes, and backend strategy

The older companion-app framing below remains useful historical context, but the local VN engine target is now the active direction.

## May 27, 2026 Runtime Decision

The current app path has moved from experiments into implementation.

Proven local production loop:

- Text backend: `hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M` through Ollama `0.21.0`
- Text context: `8192`
- Image backend: A1111 API, not in-process Diffusers
- Image checkpoint: `novaAnimeXL_ilV120.safetensors`
- Default image preset: `640x640 -> 1280x1280`, `20` base steps, `10` hires steps, `DPM++ 2M`, `Automatic`, `Latent`, denoise `0.7`
- Runtime policy: keep A1111 hot, generate story text, make a small second text call for the image prompt, unload Ollama text, render image through A1111, then optionally preload text again
- Storage policy: all model/cache/temp paths must stay on `F:`

The full Echidna gold replay completed in `outputs/diags/gold_production_a1111_20260527_221206`.

Observed average over 7 full gold turns:

- first token: `6.53s`
- story generation: `9.12s`
- image prompt call: `3.63s`
- text unload: `4.09s`
- A1111 image render: `24.75s`
- total turn: `43.88s`
- text split: `6.04 GiB VRAM / 0.00 GiB CPU`

The actual FastAPI app now uses the A1111-backed image service. A full route-level smoke test succeeded with real text and real image generation on a temporary DB/output folder, then cleaned up all A1111/Ollama child processes and returned the GPU to idle.

## 1. Purpose and How to Use This File

This file is the single source of truth for the project going forward.

It exists so future work does not depend on scattered chat logs, notebook archaeology, or re-explaining the same backstory over and over again. If someone needs to understand what this project is, what happened to it, what was learned, and what the current direction is, this is the first file they should read.

This file supersedes ad hoc summaries as the preferred context handoff.

### Provenance Key

- `[repo-observed]`: confirmed directly from the current project folder and saved files
- `[from prior chat summaries]`: preserved from earlier project chats and historical summaries supplied in this workspace/session
- `[current recommendation]`: current judgment about what to do next based on the repo, the historical summaries, and the external teardown research

## 2. Project Goal

- `[from prior chat summaries]` The original goal was to build a local AI companion app in the spirit of `Candy.ai`.
- `[from prior chat summaries]` `Perchance` later became a secondary reference because it looked simpler and therefore more approachable as an MVP starting point.
- `[current recommendation]` The clearest current framing is: build a local-first companion app with a persistent character, long-running chat, layered memory, and matching image generation.

### Core Product Goal

The project is not just "a chatbot" and not just "an image generator". The intended product is a character-centric system where:

- the user creates or chooses a companion
- the companion has a stable persona and voice
- the companion remembers things over time
- the user can roleplay or chat naturally
- the system can generate images that match the companion and the current scene
- the whole experience feels like an ongoing relationship, not isolated one-off outputs

### Current Non-Goals

- `[current recommendation]` Perfect one-to-one cloning of any commercial app
- `[current recommendation]` Exact `Candy.ai` parity in every feature
- `[current recommendation]` Exact `A1111` or `Civitai` image reproduction
- `[current recommendation]` Premature mobile polish, cloud scaling, or production ops complexity
- `[current recommendation]` Building around hidden prompt obsession rather than product behavior

## 3. Project History

### The Original Start

- `[from prior chat summaries]` The project started years ago, before the current generation of coding agents and before modern large-context workflows were readily available.
- `[from prior chat summaries]` Work happened through long ChatGPT conversations, copy-pasting code in and out, carrying summaries from one chat to the next whenever the context window ran out.
- `[from prior chat summaries]` That made the project both productive and fragile: progress happened, but the memory of the project became scattered across chats instead of living in the repo.

### Original Product Vision

- `[from prior chat summaries]` The first real idea was simple: make a local version of `Candy.ai`.
- `[from prior chat summaries]` That meant a companion app with:
  - persistent character identity
  - roleplay/chat
  - generated images
  - possible future memory, voice, and richer embodiment
- `[from prior chat summaries]` NSFW capability mattered to the original concept, but the deeper technical problem was always the same: how to make the companion feel consistent and believable over time.

### Why Perchance Entered the Picture

- `[from prior chat summaries]` `Candy.ai` felt too large and too hard to reverse engineer at the start.
- `[from prior chat summaries]` `Perchance` looked like a simpler, more stripped-down cousin, so it became a useful historical reference for "maybe start smaller and still get something real working".
- `[current recommendation]` In retrospect, `Perchance` was never the actual end goal. It was a stepping stone and a contrast case.

### The Jupyter Prototype Phase

- `[from prior chat summaries]` When a full app felt too large, the project collapsed into a notebook-first prototype.
- `[repo-observed]` That notebook stage is still visible in:
  - [playground.ipynb](f:\projects\perchance_clone\perchance_clone\playground.ipynb)
  - [playground-Copy1.ipynb](f:\projects\perchance_clone\perchance_clone\playground-Copy1.ipynb)
- `[from prior chat summaries]` The notebooks became a laboratory for:
  - loading local text models
  - loading local image models
  - experimenting with SDXL prompt behavior
  - reproducing settings from public metadata
  - exploring memory and prompt ideas
  - eventually building tag datasets and prompt tooling

### What Was Actually Learned

- `[from prior chat summaries]` The project did not fail because the idea was bad. It stalled because a product problem kept turning into a research problem.
- `[from prior chat summaries]` Several important things were learned the hard way:
  - systems like `Candy.ai` are orchestrated stacks, not one magical model
  - persistent memory is an application design problem, not something an LLM solves on its own
  - image quality depends on prompt composition, identity anchoring, and pipeline choices more than people first assume
  - local hardware constraints shape architecture decisions immediately
  - a notebook can validate ideas, but it does not automatically become a product

### The Rabbit Holes

- `[from prior chat summaries]` The project split into too many subprojects at once:
  - local roleplay LLM experiments
  - SDXL / checkpoint / prompt reproduction work
  - tag ontology and whitelist engineering
  - future app architecture planning
- `[from prior chat summaries]` Several of those were valuable, but some became traps:
  - exact `A1111` parity chasing
  - over-indexing on Danbooru/tag pipelines before a usable product loop existed
  - using a roleplay model as a tag-generation utility model
  - relying on chat summaries as the main project memory

### The Current Restart Decision

- `[from prior chat summaries]` The project has now reached a clear conclusion: treat the old work as reference material, not as a coherent codebase to keep layering onto forever.
- `[current recommendation]` The right move is a clean restart of the actual product design, while preserving what was learned.

### Valuable Lessons to Preserve

- `[from prior chat summaries]` The core product is a believable companion experience, not prompt conversion.
- `[from prior chat summaries]` Character consistency matters more than any single model benchmark.
- `[from prior chat summaries]` Image generation for companions is not just "chat text into a diffusion model"; identity persistence is the real issue.
- `[current recommendation]` Future work should be biased toward product loops and decision-making, not open-ended research for its own sake.

## 4. Current Repo State

### What Is Actually Here

- `[repo-observed]` The current project folder is still mostly a notebook workspace plus generated assets and tag data.
- `[repo-observed]` The main files and folders are:
  - [playground.ipynb](f:\projects\perchance_clone\perchance_clone\playground.ipynb)
  - [playground-Copy1.ipynb](f:\projects\perchance_clone\perchance_clone\playground-Copy1.ipynb)
  - [tags](f:\projects\perchance_clone\perchance_clone\tags)
  - [tags_build](f:\projects\perchance_clone\perchance_clone\tags_build)
  - [outputs](f:\projects\perchance_clone\perchance_clone\outputs)
  - [docs/ai-companion-app-teardown.md](f:\projects\perchance_clone\perchance_clone\docs\ai-companion-app-teardown.md)

### What the Notebooks Represent

- `[repo-observed]` `playground.ipynb` is mostly an experimentation notebook for local LLM and SDXL image generation:
  - local GPU checks
  - Hugging Face cache setup
  - loading `Pygmalion-3-12B`
  - loading SDXL checkpoints such as `unholyDesireMixSinister_v60` and `novaAnimeXL`
  - long-prompt and chunking experiments
  - txt2img and 2-step hi-res tests
- `[repo-observed]` `playground-Copy1.ipynb` includes more project-shaped logic:
  - tag-source merging
  - whitelist/alias generation
  - shortlist generation
  - a local LLM attempt to turn natural requests into positive/negative image tags

### What the Tag Assets Represent

- `[repo-observed]` The `tags` and `tags_build` folders contain merged tag resources and generated prompt-support assets such as:
  - whitelist
  - aliases
  - metadata
  - shortlist
  - negative seeds
- `[from prior chat summaries]` This work came from a phase where the project drifted deep into the idea of converting natural language into Danbooru-style image prompts.
- `[current recommendation]` These assets are still potentially useful as support tools, but they should not define the product architecture by themselves.

### What the Images Represent

- `[repo-observed]` The repo contains many generated images and output experiments.
- `[current recommendation]` These are best understood as artifacts of experimentation and reproduction attempts, not as stable product assets.

### How to Treat This Repo Going Forward

- `[current recommendation]` This repo should be treated as **reference material / archaeology**, not as a coherent product codebase.
- `[current recommendation]` It contains useful knowledge, experiments, and support assets, but not a clean foundation for indefinite direct extension.

## 5. External Teardown Synthesis

- `[repo-observed]` A public-source teardown of companion-app engineering is already saved in [docs/ai-companion-app-teardown.md](f:\projects\perchance_clone\perchance_clone\docs\ai-companion-app-teardown.md).
- `[current recommendation]` The essential conclusions from that document are preserved here so this file stands alone.

### Product Categories

- `[current recommendation]` The market breaks into two useful clusters:
  - companion-first products: `Candy.ai`, `Kindroid`, `Nomi`, `Replika`
  - roleplay/character-first products: `Character.AI`, `Perchance`
- `[current recommendation]` Companion-first products optimize harder for continuity, relationship framing, and persistent identity.
- `[current recommendation]` Roleplay-first products are often broader and more open-ended, but can be less tightly optimized around one recurring companion loop.

### What Seems Publicly Documented vs Hidden

- `[current recommendation]` Companion apps are relatively open about:
  - persona creation
  - memory controls
  - image and media UX
  - platform feature boundaries
- `[current recommendation]` They are much less open about:
  - exact base models
  - exact prompt templates
  - exact retrieval/ranking logic
  - exact identity-conditioning internals

### The Shared Pattern Behind Modern Companion Apps

- `[current recommendation]` The clearest cross-product pattern is:
  1. persistent character metadata
  2. recent chat context
  3. medium-term memory
  4. long-term retrieval
  5. hidden prompt assembly
  6. separate image/media pipeline
  7. some kind of identity anchor for visuals

### Layered Memory Pattern

- `[current recommendation]` Serious companion apps do not appear to rely on the raw context window alone.
- `[current recommendation]` The strongest public evidence points to multiple cooperating memory layers:
  - always-on persistent fields
  - recent chat turns
  - medium-term summaries or abstracted memory
  - retrievable long-term facts or journals
- `[current recommendation]` This is one of the clearest recurring architectural truths across the category.

### Hidden Prompt Assembly

- `[current recommendation]` Companion apps are not just "users talk to model directly".
- `[current recommendation]` There is almost certainly a hidden orchestration layer that assembles:
  - system instructions
  - character persona
  - memory slices
  - user or relationship metadata
  - safety/product rules
  - current conversation context
- `[current recommendation]` `Character.AI` publicly confirms that prompt construction itself is a large engineering subsystem, which strongly supports the same inference for the rest of the category.

### Image Identity Anchoring

- `[current recommendation]` The strongest conclusion from the teardown is that good companion image generation does not rely on raw chat text alone.
- `[current recommendation]` The likely winning pattern is:
  - stable appearance/identity data
  - scene prompt derived from current context
  - model-specific prompt composition
  - visual identity anchoring via avatar/reference-image/adapter-like conditioning
- `[current recommendation]` This means image consistency is an identity-system problem, not just a prompt-writing problem.

### Asynchronous Media Generation

- `[current recommendation]` Images, voice, and especially video are likely served through separate operational pipelines or queues rather than through the plain chat path.
- `[current recommendation]` This matters because it means the architecture should treat media jobs as their own concern, not as a side effect of chat inference.

### What Candy.ai Likely Does

- `[current recommendation]` Publicly, `Candy.ai` is one of the most opaque products in the set.
- `[current recommendation]` Based on its policies, product surface, and category comparisons, it most likely uses:
  - a persistent character record
  - a hidden chat orchestration layer
  - memory beyond the raw context window
  - separate media-generation services
  - some form of visual identity conditioning stronger than prompt-only generation
- `[current recommendation]` It likely does **not** depend on one monolithic "romance model" that also directly solves every orchestration and media problem by itself.

## 6. Architecture Conclusions for Our Build

### Minimum Architecture That Captures the Real Product Essence

- `[current recommendation]` The smallest architecture that still feels like the intended product is:
  - structured character card
  - layered memory
  - hidden prompt/orchestration layer
  - separate image pipeline
  - identity conditioning beyond raw prompt text

### Character Card

- `[current recommendation]` The project should not use one giant free-text character blob as the main source of truth.
- `[current recommendation]` The character card should be structured enough to separate:
  - name
  - role / relationship type
  - personality traits
  - speaking style
  - backstory summary
  - boundaries / hard constraints
  - appearance sheet
  - example dialogue
  - default visual style

### Memory Stack

- `[current recommendation]` The memory system should start simple but layered:
  1. recent chat history
  2. pinned facts
  3. rolling summary
  4. retrievable journal/lore entries
- `[current recommendation]` This is the minimum practical stack that avoids both total forgetfulness and overcomplicated memory engineering.

### Hidden Orchestrator

- `[current recommendation]` The runtime system should build prompts internally from:
  - system rules
  - character data
  - pinned facts
  - rolling summary
  - retrieved memory items
  - recent turns
  - current message
- `[current recommendation]` The user should not have to manage raw prompt plumbing.

### Separate Image Pipeline

- `[current recommendation]` Image generation should not be treated as "whatever the text model says, send it directly to the diffusion model".
- `[current recommendation]` The image request should be composed from:
  - appearance sheet
  - reference images or identity conditioning
  - current scene summary
  - framing / mood / lighting defaults
  - model-specific prompt composition logic

### What Should Stay Hidden From the User

- `[current recommendation]` Hidden from the user by default:
  - system prompt
  - rolling memory summary
  - model-routing choices
  - full assembled image prompt
  - internal orchestration logic

### What Should Be Structured Data Instead of Free Text

- `[current recommendation]` Prefer structured data for:
  - appearance
  - pinned character facts
  - relationship state
  - user preferences
  - scene state
  - recurring wardrobe / props
  - personality traits

## 7. Model Strategy Memo

This section answers the current question directly: should the roleplay model be a specialized roleplay fine-tune like `Pygmalion`, or should one general-purpose foundation model handle roleplay plus orchestration tasks?

### Locked Default Recommendation

- `[current recommendation]` v1 should start with **one general foundation text model** handling:
  - roleplay/chat
  - memory extraction
  - summarization
  - scene extraction
  - image-prompt composition
- `[current recommendation]` `Pygmalion` remains the **benchmark and fallback**, not the locked final text engine.
- `[current recommendation]` Do **not** default to a second always-loaded text model for "orchestration" in v1.

### Why Two Separate Text Models Are Not the Default

- `[current recommendation]` Orchestration tasks like summarization, scene extraction, memory extraction, and prompt composition are usually cheap sub-prompts, not separate model requirements.
- `[current recommendation]` Loading and juggling multiple text models on a local 12 GB RTX 3080 adds real complexity immediately:
  - more VRAM pressure
  - more model swapping
  - more latency spikes
  - more brittle tooling
  - more opportunities for quality inconsistency between subsystems
- `[current recommendation]` The real architectural question is not "text model plus orchestration model?"
- `[current recommendation]` The real question is: **is one strong general model good enough to do both believable roleplay and structured utility tasks well enough for v1?**

### Why a General Model Is Worth Testing First

- `[current recommendation]` A strong general instruct model may already be good enough for:
  - persona adherence
  - stylized long-form roleplay
  - memory summarization
  - scene extraction
  - structured image-prompt composition
- `[current recommendation]` If that is true, the architecture becomes much simpler.
- `[current recommendation]` If it is not true, the product can still introduce a specialized RP model later without having designed the entire system around that assumption from day one.

### Why Pygmalion Still Matters

- `[repo-observed]` `Pygmalion` is the actual roleplay model family currently explored in the notebooks.
- `[from prior chat summaries]` It was chosen because roleplay quality mattered and because it was explicitly roleplay-oriented.
- `[current recommendation]` That still makes it useful, but in a new role:
  - benchmark for RP quality
  - fallback if general models feel too sterile or too assistant-like
  - comparison point during evaluation

### Staged Decision Rule

- `[current recommendation]` Stage 1: test one strong general foundation model.
- `[current recommendation]` Keep the single-model text architecture if:
  - roleplay quality is good enough
  - persona adherence is stable
  - utility tasks are reliable
  - latency/VRAM fit is acceptable
- `[current recommendation]` Introduce a specialized RP model only if measured evaluation shows a persistent quality gap in roleplay or tone that cannot be closed with prompting and character-structure improvements.

### Planned Evaluation Candidates

- `[current recommendation]` First general-model family to evaluate: **Qwen instruct family**
- `[current recommendation]` Secondary comparison family: **Llama instruct family**
- `[current recommendation]` Specialized roleplay comparison: **Pygmalion**

### Why Qwen First

- `[current recommendation]` Qwen is the current first-choice family because it is known for strong general instruction following, tool/structured-task competence, and long-context friendliness.
- `[current recommendation]` Those strengths matter for this product because the model has to do more than flirt or roleplay. It also has to:
  - obey hidden orchestration instructions
  - summarize memory
  - extract scene state
  - compose prompt-ready outputs when asked

### Why Llama Second

- `[current recommendation]` Llama instruct models are still worth comparing because they are common, well-supported, and likely to remain relevant across tooling stacks.
- `[current recommendation]` They are a comparison family, not the first pick at the moment.

### Evaluation Criteria

- `[current recommendation]` Every text-model candidate should be tested on:
  - persona adherence
  - long-chat consistency
  - emotional and narrative roleplay quality
  - memory-summary quality
  - scene extraction quality
  - structured image-prompt generation reliability
  - latency and VRAM fit on the local machine

### Current Bottom Line on the Model Question

- `[current recommendation]` Do not start with:
  - one specialized RP model
  - plus one separate utility/orchestration model
- `[current recommendation]` Start with:
  - one strong general model for all text-side tasks
  - plus `Pygmalion` as the benchmark/fallback
- `[current recommendation]` Split later only if the evaluation says it is truly necessary.

## 8. Immediate Next Direction

- `[current recommendation]` After documentation, the next step is not "start coding randomly."
- `[current recommendation]` The next step should be definition work for the clean restart:
  1. define the character schema
  2. define the memory stack
  3. define the chat orchestrator contract
  4. define the image prompt composer and identity approach

### What That Means Practically

- `[current recommendation]` Character schema:
  - exactly what fields exist
  - what is structured vs free text
  - what the UI will ask the user for
- `[current recommendation]` Memory stack:
  - what gets pinned
  - what gets summarized
  - what gets retrieved
  - when each layer updates
- `[current recommendation]` Chat orchestrator contract:
  - what inputs the text model receives
  - what the app prepares before every reply
  - how memory and scene state flow into generation
- `[current recommendation]` Image prompt composer:
  - what stable appearance data exists
  - what scene data is extracted from chat
  - how visual identity is anchored

## 9. Appendix: Preserved Historical Context

This appendix preserves the important historical context from earlier long summaries without dumping raw transcripts.

### Historical Throughline

- `[from prior chat summaries]` The project began as a local `Candy.ai` clone idea.
- `[from prior chat summaries]` `Perchance` became a temporary simplification target when `Candy.ai` felt too large.
- `[from prior chat summaries]` The work moved into Jupyter notebooks to reduce startup friction.
- `[from prior chat summaries]` The notebooks proved local LLM chat and local image generation were both feasible on the machine.
- `[from prior chat summaries]` The project then drifted into multiple deep technical side quests:
  - SDXL prompt handling
  - long-prompt chunking
  - image reproduction
  - tag generation
  - local RP model bring-up
  - memory speculation
- `[from prior chat summaries]` Eventually it became clear that the project had become a pile of experiments rather than a product path.

### Key Historical Technical Findings

- `[from prior chat summaries]` A local text model can run on the current machine.
- `[from prior chat summaries]` Local SDXL image generation can run too, but text and image models do not comfortably coexist in VRAM at the same time.
- `[from prior chat summaries]` Prompt-only image reproduction is an unreliable foundation for a companion product.
- `[from prior chat summaries]` Tag engineering can be useful, but it became a distraction when it started replacing the product problem itself.

### The Most Important Preserved Lesson

- `[from prior chat summaries]` The project’s real value is not "prompt conversion" or "reproducing Civitai outputs".
- `[from prior chat summaries]` The real value is building a believable local companion experience with stable identity across text and images.

### What Future Work Should Not Forget

- `[current recommendation]` The old work should inform the new system, not trap it.
- `[current recommendation]` Build around the companion loop:
  - character
  - memory
  - conversation
  - scene state
  - matching image generation
- `[current recommendation]` Avoid restarting the old pattern of endlessly optimizing internals before a real user-facing loop exists.

## 10. Current Productization State

- `[repo-observed]` The app now uses the A1111-backed image service and Ollama text service as the practical v1 runtime direction.
- `[repo-observed]` The real app image prompt composer now anchors visual identity with:
  - character display name
  - source media when present, e.g. `Echidna from Re:Zero`
  - filtered active-character visual card
  - scene summary
  - style and positive/negative additions
- `[repo-observed]` Multi-character visual cards from Perchance-style exports are filtered before image prompting. Example: if a field contains both `Echidna:` and `Mirajane:`, only the active character block is used for Echidna.
- `[repo-observed]` The chat composer now has an opt-in `Generate image after reply` control. This supports the production loop without forcing every text reply to become a long image-rendering request.
- `[repo-observed]` The lightweight smoke script `scripts/smoke_app_identity_prompt.py` verifies both:
  - manual image generation from an assistant message
  - chat submission with auto-image enabled
- `[repo-observed]` The smoke test is intentionally mock-only and should not start A1111 or Ollama.
- `[repo-observed]` Diagnostic smoke scripts now copy run-id-named image/settings files in addition to short aliases like `image.png`, so experiment images are identifiable even outside their folder.
- `[repo-observed]` `scripts/import_gold_sample_character.py` imports research gold samples into the app database as usable characters. Echidna has been imported from `outputs/research_gold_samples/echidna` with source media `Re:Zero` and the gold turn history.
- `[repo-observed]` `scripts/stop_companion_backends.ps1` is the preferred recovery/cleanup command for stopping Ollama, A1111, and benchmark backends without touching unrelated Jupyter kernels unless `-IncludeJupyter` is explicitly passed.
- `[repo-observed]` `scripts/audit_storage_paths.py` verifies HuggingFace, Torch, CUDA, temporary, SQLite temporary, and Ollama model paths are on `F:` and checks that risky `C:` cache folders are absent.
- `[repo-observed]` The UI status stream now exposes clearer text/image phases: story reply generation, image prompt composition, text-model handoff, and A1111 rendering.
- `[repo-observed]` Speed-mode auto-image now uses a deterministic image prompt path instead of a second LLM call. It anchors character identity/source media, filters the assistant reply into visual fragments, merges existing style/negative additions, and records `image_prompt_strategy: deterministic_speed` in the story-frame metadata.
- `[repo-observed]` Latest browser-driven real replay after deterministic Speed prompt integration: `outputs/diags/browser_prompt_replay_20260601_013907`.
- `[repo-observed]` That replay covered `sample-companion`, `atago`, `ahri`, `echidna`, and `mirajane` through the actual browser UI with auto-image enabled. Average text-visible time was ~22.3s, average image-visible time was ~55.4s, and average post-text image wait was ~33.1s.
- `[repo-observed]` Previous browser baseline with the LLM image-prompt composer had average image-visible time ~68.3s and average post-text image wait ~48.1s, so deterministic Speed saved about ~15.0s after text became visible without changing the `512 -> 1024` A1111 preset.
- `[repo-observed]` Latest browser-driven real replay after startup readiness gating: `outputs/diags/browser_prompt_replay_20260601_201202`.
- `[repo-observed]` That replay pre-warmed text and image backends before accepting chat input, then replayed `sample-companion`, `atago`, `ahri`, `echidna`, and `mirajane` through the browser with auto-image enabled. Average text-visible time was ~18.6s, average image-visible time was ~55.7s, and average post-text image wait was ~37.1s.
- `[repo-observed]` The readiness-gated run improved first-use cold-start behavior substantially: the warmup image-visible path was ~60.4s versus ~127.6s in the previous deterministic Speed replay.
- `[repo-observed]` The app now exposes a Runtime diagnostics drawer backed by `/diagnostics`, plus a startup readiness panel that disables chat submission until configured preload work is complete. Browser probe evidence: `outputs/diags/diagnostics_drawer_probe_20260601_202901`.
- `[repo-observed]` `/status` and `/diagnostics` now avoid repeatedly probing Ollama on every UI heartbeat by caching the text-model loaded check briefly. Mock timing probe after the fix: `/status` ~0.01s and `/diagnostics` ~0.09s.

### Safety Rule After BSOD

- `[repo-observed]` A full real-backend FastAPI/TestClient image smoke caused a Windows `MEMORY_MANAGEMENT` BSOD on 2026-05-28.
- `[repo-observed]` The route has since been recovered under `scripts/run_real_app_route_image_guarded.ps1`, which watches free system RAM, Windows commit ratio, and VRAM and kills companion backends if thresholds are exceeded.
- `[repo-observed]` The app now defaults to a hard text-to-image handoff: after text/image-prompt composition, Ollama is unloaded and stopped before A1111 renders. This is controlled by `COMPANION_STOP_OLLAMA_BEFORE_IMAGE` and defaults to enabled.
- `[repo-observed]` Latest passing real route smoke: `outputs/diags/real_app_route_smoke_20260528_021142`.
- `[repo-observed]` Latest passing route used 704 -> 1408 A1111 settings, rendered in ~20.3s, peaked around 11862 MiB VRAM, kept at least 13.34 GB system RAM free, and ended with idle memory restored.
- `[repo-observed]` Latest passing full chat + auto-image sequence at the balanced preset after in-app resource guard integration: `outputs/diags/real_app_chat_auto_sequence_20260528_052242`.
- `[repo-observed]` The latest 640 -> 1280 sequence completed turn 1 in ~77.7s and turn 2 in ~56.0s, with A1111 renders at ~15.7s and ~15.6s. External watchdog peak was ~12034 MiB VRAM, lowest free RAM was ~13.67 GiB, and final cleanup returned VRAM to about 240 MiB used.
- `[repo-observed]` Latest passing speed-mode sequence after in-app resource guard integration: `outputs/diags/real_app_chat_auto_sequence_20260528_051941`.
- `[repo-observed]` The latest 512 -> 1024 sequence completed turn 1 in ~90.1s and turn 2 in ~50.5s, with A1111 renders at ~24.6s and ~10.3s. External watchdog peak was ~11962 MiB VRAM, lowest free RAM was ~12.53 GiB, and final cleanup returned VRAM to about 230 MiB used.
- `[repo-observed]` Both latest sequences generated image prompts containing `Echidna from Re:Zero`, did not include `Mirajane`, and kept scene narrative out of the negative prompt.
- `[repo-observed]` Latest single-turn real chat + auto-image check after prompt cleanup: `outputs/diags/real_app_chat_auto_smoke_20260528_053121`.
- `[repo-observed]` That run completed in ~77.8s total with a ~15.6s A1111 render, peaked around 12032 MiB VRAM, kept at least 15.69 GiB free system RAM, and produced a cleaner visual-only image prompt with run-id-named artifacts.
- `[repo-observed]` Latest non-blocking auto-image route check: `outputs/diags/real_app_chat_auto_smoke_20260528_054343`.
- `[repo-observed]` That run returned the assistant text route in ~22.0s while the background image completed at ~79.0s, with a ~15.7s A1111 render. Peak VRAM was ~12030 MiB and lowest free RAM was ~14.85 GiB.
- `[current recommendation]` Keep the non-blocking auto-image behavior. It better matches the target user experience because text appears first and the image arrives afterward.
- `[current recommendation]` Use 640 -> 1280 as the balanced app default. Keep 512 -> 1024 as speed mode and 704 -> 1408+ as quality modes.
- `[current recommendation]` Do not run full real-backend TestClient checks without the guarded runner.
- `[current recommendation]` Real-backend checks should use the safe runner scripts or manual app launch with one clear backend lifecycle, explicit process cleanup, and resource checks before/after.
- `[current recommendation]` Keep using mock route tests for app wiring and reserve real A1111/Ollama runs for benchmark harnesses that already pre-clean and final-clean processes.
- `[current recommendation]` Before any heavy run, use:
  `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_companion_backends.ps1`

## Quick Reference

If a future session needs the shortest possible summary, it is this:

- `[current recommendation]` The project goal is a local-first `Candy.ai`-style companion app.
- `[current recommendation]` The current repo is valuable reference material and is now also the active prototype path for the proven A1111/Ollama loop.
- `[current recommendation]` Modern companion apps appear to rely on layered memory, hidden prompt assembly, and image identity anchoring.
- `[current recommendation]` Our minimum viable architecture is:
  - structured character card
  - layered memory
  - hidden chat orchestrator
  - separate image pipeline
  - identity conditioning beyond prompt-only generation
- `[current recommendation]` For text, start with one strong general model first, benchmark against `Pygmalion`, and only split into specialized text models later if evaluation proves it is necessary.

## Related File

- Supporting external teardown and source-driven market analysis:
  [docs/ai-companion-app-teardown.md](f:\projects\perchance_clone\perchance_clone\docs\ai-companion-app-teardown.md)
