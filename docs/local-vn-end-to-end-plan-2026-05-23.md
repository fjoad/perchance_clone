# Local VN End-To-End Research And Experiment Plan

Status: research-complete first pass, experiment-ready
Date: May 23, 2026

This is the spine document for the next phase.

The goal is not to keep debating tools. The goal is to prove, with saved outputs and timings, which fully local text/image stack can deliver a Perchance-quality-or-better visual novel loop on the current hardware.

Related research notes:

- Full research synthesis: `docs/local-vn-full-research-synthesis-2026-05-23.md`
- Current-space survey: `docs/local-vn-current-space-research-2026-05-23.md`
- Small-model adversarial pass: `docs/local-vn-small-model-adversarial-pass-2026-05-23.md`
- App-space deep dive: `docs/local-vn-app-space-deep-dive-2026-05-23.md`
- Prompting and multi-character pass: `docs/local-vn-prompting-multichar-research-2026-05-23.md`

This plan has two research streams:

1. Local model/runtime feasibility:
   - text models
   - image models
   - text backends
   - image backends
   - GPU/RAM orchestration

2. App-space/product architecture:
   - expected features
   - prompt assembly best practices
   - character/persona/lore/memory structures
   - story branching and reroll workflows
   - image prompt integration
   - future feature compatibility

## 0. Project Target

Build a local/offline, zero-budget, unrestricted visual novel/storybook engine.

Core loop:

1. User sends a message as their protagonist.
2. AI streams a story continuation quickly.
3. AI output feels like interactive fiction, not assistant chat.
4. The system generates a matching VN-style image panel.
5. The user can continue the story.
6. The loop remains responsive over multiple turns.

Target latency:

- first text tokens: ideally under 10 seconds
- full text reply: roughly under 60 seconds
- image after text: roughly 30-60 seconds
- full turn: acceptable if text streams early and image follows without freezing the app

Target quality:

- text should match or beat the supplied Perchance sample quality
- image should match or beat Perchance-style visual usefulness after manual review
- unrestricted/adult-capable behavior is required
- everything must remain local/offline

Hardware constraint:

- RTX 3080 12GB
- system RAM can be used, but shared GPU memory spill should be treated as a warning unless measured acceptable
- no paid cloud services

## 1. Non-Negotiables

Do not re-litigate these unless the user explicitly changes constraints:

- local/offline is required
- zero ongoing cost is required
- unrestricted/adult-capable model behavior is required
- text and images are both core, because this is a visual novel engine
- benchmark outputs must be saved for review
- manual quality review matters more than synthetic benchmark scores
- Perchance export/sample is a quality bar, not an architecture spec

## 2. Anti-Spiral Rules

Before adding or changing app code:

- write the test target
- run the harness
- save outputs and metrics
- compare against the gold sample
- decide keep/drop/continue

Avoid:

- downloading huge models without a test slot
- optimizing a backend before proving output quality
- changing prompts without saving before/after outputs
- rebuilding the UI before the core loop is proven
- mixing research, app refactor, and model hunting in the same task

## 3. Artifacts We Need

### 3.1 Gold Sample Dataset

Source:

- Perchance export JSON, e.g. `D:\Downloads\Devouring_Devotion_-_Echidna.json`

Extract:

- Character Profile
- Protagonist Profile
- existing chat turns
- selected user turns
- selected Perchance assistant replies
- any image prompt tags if present

Save normalized benchmark data under:

`outputs/research_gold_samples/<sample_name>/`

Files:

- `character_profile.md`
- `protagonist_profile.md`
- `turns.json`
- `reference_replies.md`
- `notes.md`

### 3.2 Text Harness

Purpose:

- run the same gold sample against many text models/backends
- save exact prompt/messages, output, timings, and metadata

Output path:

`outputs/research_runs/<timestamp>/text/<model_slug>/`

Save:

- `rendered_messages.json`
- `reply.txt`
- `metrics.json`
- `model_info.json`
- `manual_review.md`

Metrics:

- load time
- first-token latency if streaming is available
- total generation time
- prompt tokens if available
- output tokens
- tokens/sec
- peak dedicated VRAM
- peak shared GPU memory
- backend name/version
- quantization
- context size
- sampler/settings

### 3.3 Image Harness

Purpose:

- run the same scene/image prompts against image models/backends
- save images and exact generation settings

Output path:

`outputs/research_runs/<timestamp>/image/<backend>/<model_slug>/`

Save:

- `positive_prompt.txt`
- `negative_prompt.txt`
- `image.png`
- `metadata.json`
- `manual_review.md`

Metrics:

- backend startup time if relevant
- model load time if measurable
- generation time
- unload time if relevant
- peak dedicated VRAM
- peak shared GPU memory
- base resolution
- hires/upscale settings
- sampler/scheduler
- CFG
- steps
- seed

### 3.4 Full Loop Harness

Purpose:

- test the actual VN sequence: text -> image -> text -> image
- answer whether the stack feels usable, not just fast in isolation

Output path:

`outputs/research_runs/<timestamp>/full_loop/<stack_slug>/`

For each turn save:

- `turn_001_user.txt`
- `turn_001_text_prompt.json`
- `turn_001_reply.txt`
- `turn_001_image_prompt.txt`
- `turn_001_image.png`
- `turn_001_metrics.json`

Full-loop metrics:

- first text token latency
- full text time
- image prompt extraction time
- image generation time
- reload/prewarm time
- total wall time
- peak dedicated VRAM
- peak shared GPU memory
- failures/retries

## 4. Text Model Research Plan

### 4.1 Research Question

Can a smaller 8B/9B roleplay-specialized model hit the quality bar better than, or close enough to, 12B models while improving the whole text-image loop?

### 4.2 Candidate Lanes

#### Lane A: Current Baselines

Test first because they are already available:

- `dolphin-nemo`
- `dolphin-llama3`
- `qwen-uncensored`

Purpose:

- establish baseline quality and speed
- verify harness correctness

#### Lane B: Small Specialized Roleplay Models

Test before assuming 12B is required:

- `Dolphin-X1-8B-GGUF`
- `Peach-2.0-9B-8k-Roleplay-GGUF`
- `Lumimaid-v0.2-8B-GGUF`
- `Llama-3.1-8B-Stheno-v3.4`
- `Roleplay-Hermes-3-Llama-3.1-8B`
- one Qwen3.5 9B uncensored/abliterated variant

Purpose:

- challenge the 12B anchoring bias
- find fast always-hot candidates
- find models trained against assistant-slop and for RP formatting

#### Lane C: 12B Roleplay/Story Models

Test after the small-model lane:

- `MN-12B-Celeste-V1.9-GGUF`
- `Mistral-Nemo-12B-ArliAI-RPMax`
- `Darkness-Incarnate-12B-Nemo-v3.5-GGUF`
- current `dolphin-nemo`

Purpose:

- determine whether 12B meaningfully improves prose quality
- identify practical high-quality clean-swap model

#### Lane D: Small New General Models

Test as surprises or helpers:

- Gemma 4 E4B official
- Gemma 4 E4B uncensored
- Gemma 3 4B RP/uncensored variants

Purpose:

- see if newer small models can surprise us
- evaluate helper use for summaries/image prompts/state extraction

#### Lane E: Large Quality Ceiling

Only after lanes A-D:

- Gemma4 26B-A4B uncensored
- Qwen3.6 35B-A3B
- Mistral Small 24B if practical/uncensored path exists

Purpose:

- establish whether larger models are dramatically better
- do not assume production viability

### 4.3 Text Quality Rubric

Manual review questions:

- Would the user want to reply?
- Does it feel like story continuation rather than assistant response?
- Does it use the Character Profile naturally?
- Does it use the Protagonist Profile naturally?
- Does it preserve user agency?
- Does it balance narration, action, body language, and dialogue?
- Does it avoid generic trait-list behavior?
- Does it maintain continuity over three turns?
- Does it avoid speaking for the user unless prompted?
- Does it produce image-worthy scene detail?

Score each:

- 0 = fail
- 1 = weak
- 2 = acceptable
- 3 = strong
- 4 = excellent

Do not pick a model on tok/s alone.

## 5. Text Backend Research Plan

### 5.1 Research Question

Which local text backend gives the best combination of quality control, speed, streaming, unload behavior, cache control, and debuggability?

### 5.2 Backends To Research And Test

#### Ollama

Why test:

- already integrated
- simple API
- already has model store on `F:\ollama\models`
- easy unload with `keep_alive: 0`
- returns timing fields

Questions:

- Does it apply the right chat template for each model?
- Can it expose enough streaming metrics?
- Can it avoid unwanted thinking fields for Qwen/Gemma-style models?
- Can it reliably unload before image generation?
- Does it hide too much offload behavior?

Decision:

- keep as default unless another backend clearly wins

#### llama.cpp server

Why test:

- direct GGUF runtime
- explicit GPU layer/offload controls
- direct control of context, batch, KV, flash attention
- useful for diagnosing Ollama problems

Questions:

- Is it faster/slower than Ollama for the same GGUF?
- Does it handle Qwen/Gemma/MoE formats better?
- Can it expose offload and timing clearly enough?
- Is integration complexity worth it?

Decision:

- use as diagnostic backend first
- promote only if it clearly beats Ollama

#### KoboldCpp

Why test:

- roleplay community standard
- good GGUF support
- story/RP-oriented runtime options
- may handle context shifting and prompt formats well

Questions:

- Does it produce better RP behavior from the same model/settings?
- Is API integration clean enough?
- Does it stream reliably?
- Does it control VRAM/offload better than Ollama?

Decision:

- serious test if Ollama outputs feel prompt/template damaged

#### LM Studio

Why research:

- convenient local model runner
- good for manual experiments

Questions:

- Can it be scripted cleanly?
- Can cache/model paths be forced to `F:\` reliably?
- Does it add value over Ollama/llama.cpp?

Decision:

- likely manual exploration only, not app backend unless it surprises us

#### TabbyAPI / exllamav2 / EXL2

Why test:

- very fast when model fits fully in VRAM

Questions:

- Can 8B/9B EXL2 models stay hot with image backend requirements?
- Is CPU offload needed or absent?
- Does EXL2 speed justify maintaining a separate model format?

Decision:

- only test after a small 8B/9B model proves high quality
- avoid for 12B+ split/offload use unless evidence says otherwise

### 5.3 Text Backend Test Matrix

For the top three text models from the model harness:

1. Run in Ollama.
2. Run same quant/settings in llama.cpp server if possible.
3. Run in KoboldCpp if model is roleplay-format-sensitive.
4. Optional: run top small model in EXL2/TabbyAPI if it fits fully in VRAM.

Compare:

- output quality
- first-token latency
- total tok/s
- unload behavior
- VRAM behavior
- template correctness
- integration complexity

## 6. Image Model Research Plan

### 6.1 Research Question

Which local image model family gives the best VN panel quality on RTX 3080 12GB within roughly 30-60 seconds, and can any fast workflow reduce that without unacceptable quality loss?

### 6.2 Candidate Lanes

#### Lane A: Current Control

- Nova Anime XL

Purpose:

- current visual baseline
- current measured timing control

#### Lane B: Current Anime SDXL Families

Research/test:

- WAI-Illustrious
- NoobAI XL V-Pred / NoobAI XL 1.1
- Animagine XL 4.0
- Pony V6 XL if needed

Purpose:

- test current anime checkpoint ecosystem against Nova
- preserve high image quality

#### Lane C: Acceleration

Research/test:

- SDXL-Lightning 4-step and 8-step
- Hyper-SD
- LCM-LoRA

Purpose:

- see if image time can drop meaningfully below current ~40s baseline
- distinguish final-quality path from fast-preview path

#### Lane D: Quantized Diffusion

Research/test later:

- ComfyUI GGUF/quantized SDXL/Pony/Illustrious/FLUX workflows

Purpose:

- determine if co-residency becomes practical
- only after full-quality image candidates are known

#### Lane E: Heavy/New Families

Research/test later:

- FLUX GGUF/FP8
- other new high-quality families if anime/VN ecosystem is strong enough

Purpose:

- quality ceiling, not first production path

### 6.3 Image Quality Rubric

Manual review questions:

- Would this image make the user want to continue the scene?
- Does it fit the generated text?
- Does it preserve character identity?
- Does it preserve protagonist/user viewpoint if relevant?
- Is anatomy acceptable?
- Is expression/body language emotionally useful?
- Is composition VN-panel useful?
- Does it avoid generic pinup/static pose when the scene needs action?
- Are hands/faces/tails/ears/outfit stable enough?
- Does the style fit the desired app experience?

Score each:

- 0 = fail
- 1 = weak
- 2 = acceptable
- 3 = strong
- 4 = excellent

## 7. Image Backend Research Plan

### 7.1 Research Question

Which backend should actually generate images for the app: raw Diffusers, A1111, Forge, ComfyUI, or something else?

### 7.2 Backends To Research And Test

#### Raw Diffusers

Why test:

- already in app
- transparent
- easy to script

Questions:

- Can it match A1111/Forge image quality with correct settings?
- Is load/unload too slow or too fragile?
- Are we reimplementing too much backend behavior?

Decision:

- keep as control and fallback
- promote only if it matches backend quality/speed without complexity

#### AUTOMATIC1111

Why test:

- user observed better/faster results
- mature API
- has txt2img/img2img/options/model endpoints
- has checkpoint unload/reload endpoints

Questions:

- Does it reproduce better images than Diffusers with same checkpoint?
- Can it unload cleanly after each image?
- Can we force all models/cache/output to `F:\`?
- Is API stable enough for app integration?

Decision:

- serious candidate if it beats Diffusers quickly

#### Forge

Why test:

- A1111-like but focused on memory/speed improvements
- likely strong on 12GB VRAM

Questions:

- Does it run the same models faster than A1111/Diffusers?
- Does API match A1111 enough?
- Does it handle SDXL hires better?
- Can unload/reload be controlled?

Decision:

- likely first image-backend candidate to test if setup is clean

#### ComfyUI

Why test:

- workflow-native
- best future-proof backend
- strong SDXL/FLUX/LoRA/upscale/control ecosystem
- 2026 Dynamic VRAM may directly help this project

Questions:

- Can it remain running without hurting text performance?
- Does Dynamic VRAM reduce load/unload pain?
- Can we call workflows via API cleanly?
- Can it save exact workflow metadata?
- Does it beat raw Diffusers visually?

Decision:

- likely best long-term backend if API orchestration is manageable

### 7.3 Image Backend Test Matrix

Use the same image prompt and current Nova checkpoint first:

1. Raw Diffusers current pipeline.
2. A1111 API.
3. Forge API.
4. ComfyUI workflow.

Then repeat with best candidate checkpoint:

1. WAI/NoobAI/Animagine in winning backend.
2. Same scene prompts.
3. Same saved metadata.

Compare:

- image quality
- generation time
- model load/unload time
- peak dedicated VRAM
- peak shared GPU memory
- ease of API integration
- cache path control
- repeatability

## 8. Orchestration Research Plan

### 8.1 Research Question

How should the app coordinate text and image generation on one GPU?

### 8.2 Candidate Architectures

#### Architecture A: Clean Swap

Flow:

1. text model hot
2. stream reply
3. unload text
4. load/generate image
5. unload image
6. reload/prewarm text

Pros:

- already measured stable
- avoids shared VRAM fights
- works with 12B text

Cons:

- text reload cost after image
- image cannot start until text finishes
- more orchestration complexity

#### Architecture B: Text Hot, Image Backend Idle

Flow:

1. keep text loaded
2. keep image backend server running but model unloaded/offloaded
3. generate image on demand
4. return to text hot

Pros:

- app feels more like a persistent service
- backend startup cost avoided

Cons:

- must prove idle backend does not steal VRAM
- backend-specific memory behavior

#### Architecture C: Co-Resident Small Text Model

Flow:

1. keep 8B/9B text model loaded
2. keep image backend/model partially resident or quickly loadable
3. accept <=50% text speed hit if quality remains good

Pros:

- fastest user-facing text loop
- smaller model may enable smoother UX

Cons:

- text quality may fail
- image quality/speed still needs proof

#### Architecture D: Two-Stage Text

Flow:

1. main narrator produces reply
2. smaller/helper model extracts image prompt, summary, memory, or tags
3. image backend generates panel

Pros:

- cleaner outputs
- may avoid burdening main model with image tags

Cons:

- more moving parts
- helper model must be fast and reliable

### 8.3 Orchestration Decision Gate

Choose architecture based on full-loop harness:

- If small text model is good enough: prioritize co-resident or text-hot architecture.
- If only 12B text is good enough: prioritize clean swap.
- If ComfyUI/Forge idle is cheap: keep backend server alive.
- If image backend idle blocks text: unload image aggressively.
- If image prompt extraction is weak: add helper model or deterministic extractor.

## 8.5 Prompting And Multi-Character Research Plan

This section is a sub-area of the broader app-space research track, not the whole track.

Full app-space research is tracked in `docs/local-vn-app-space-deep-dive-2026-05-23.md`.

The app is a visual novel story engine, not only a one-character chatbot. The prompt architecture must support:

- one-on-one scenes
- multi-character scenes
- narrator-style prose
- distinct character voices
- protagonist/user agency
- image-worthy scene narration
- memory/lore injection
- future group scenes

### Prompt Modes To Test

#### Direct Character Mode

Prompt stance:

- "You are {{char}}."

Use for:

- one-on-one companion scenes
- small models
- direct character intimacy

Risk:

- weak multi-character support
- can become chat-like instead of VN-like

#### Storyteller Mode

Prompt stance:

- "You are the story engine/narrator for an interactive visual novel."

Use for:

- multi-character scenes
- scene movement
- image-worthy narration

Risk:

- smaller models may become generic or assistant-like

#### Hybrid Cast Narrator Mode

Prompt stance:

- "You are the narrator and performer for the active scene. Portray all active non-user characters. Do not control the protagonist."

Use for:

- likely production default
- VN prose with multiple characters
- preserving user agency

Risk:

- needs good examples and explicit response contract

#### Group Chat Simulation

Prompt stance:

- same loaded model
- multiple calls
- one active speaker per call
- speaker selector controls turn order

Use for:

- later experiments if voice separation fails

Risk:

- slower
- can feel like chatroom logs rather than storybook prose

#### Director / Actor Multi-Agent Mode

Prompt stance:

- planner/director tracks scene
- actor calls produce lines
- narrator assembles final prose

Use for:

- future advanced mode only

Risk:

- too slow and complex for v1

### Prompt Stack To Implement

The prompt builder should support explicit layers:

1. runtime/system wrapper
2. task frame
3. response contract
4. world/scene state
5. active character profiles
6. protagonist/user profile
7. relationship state
8. retrieved lore/memory
9. examples/style samples
10. recent conversation
11. author note/immediate reminder near the bottom
12. current user turn

### Multi-Character State Objects

The app should eventually maintain:

- active cast
- nearby/offscreen cast
- dormant cast
- character state objects
- protagonist state object
- scene state object
- relationship state
- hidden/secrets state

Do not inject every character every turn.

Only active cast gets full profile. Nearby/offscreen cast gets compact summaries. Dormant cast is retrieved only when relevant.

### Prompting Experiment Questions

The harness must answer:

- Does direct character mode beat storyteller mode for small models?
- Does hybrid narrator mode beat direct character mode for multi-character scenes?
- Do examples near the bottom improve style adherence?
- How many active characters can one call handle?
- Does group-chat simulation improve character voice enough to justify cost?
- Does the protagonist profile help or confuse the model?
- Does image-prompt extraction belong in the main generation or a helper pass?

### Recommendation For V1

The likely v1 architecture is:

- one loaded text model
- one story generation call per user turn
- hybrid narrator prompt
- active cast profiles injected
- protagonist profile injected as user-controlled character
- lore/memory injected conditionally
- image prompt generated after the story reply
- image backend called separately

But the harness must test this against direct character mode before locking it in.

## 9. Storage And Cache Hygiene Plan

Everything must stay on `F:\`.

Required environment variables before running model/image code:

- `OLLAMA_MODELS=F:\ollama\models`
- `HF_HOME=F:\huggingface\models`
- `HF_HUB_CACHE=F:\huggingface\models\hub`
- `HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub`
- backend-specific model/output/cache paths for A1111/Forge/ComfyUI

Rules:

- no Hugging Face cache on `C:\Users\<user>\.cache\huggingface`
- no Ollama model store on `C:\Users\<user>\.ollama\models`
- no LM Studio model cache on C if LM Studio is tested
- all benchmark outputs under project `outputs/`
- all downloaded model files under `F:\huggingface\models`, `F:\ollama\models`, or an explicitly named `F:\models\...`

Before installing/testing a backend:

- identify where it stores models
- identify where it stores outputs
- identify where it stores temp/cache files
- set or document all path overrides

## 10. Execution Order

### Phase 1: Build Gold Sample Harness

Deliverable:

- script that reads Perchance-style JSON and extracts benchmark-ready profile/turn data

Why first:

- all model/backend choices need the same target

### Phase 2: Text Harness With Existing Models

Deliverable:

- run current models against gold sample
- save outputs and metrics

Why second:

- establishes baseline
- validates harness

### Phase 3: Small-Model Text Tests

Deliverable:

- test Dolphin X1 8B, Peach 9B, Lumimaid 8B, Stheno 8B, Roleplay-Hermes 8B, one Qwen3.5 9B

Why third:

- directly addresses 12B bias

### Phase 4: 12B Text Tests

Deliverable:

- test Celeste, RPMax, Darkness, Dolphin-Nemo

Why fourth:

- compare practical quality tier after small models get a fair shot

### Phase 5: Text Backend Tests

Deliverable:

- top 2-3 text models tested under Ollama and at least one alternate backend

Why fifth:

- no point testing every backend for bad models

### Phase 6: Image Backend Control Tests

Deliverable:

- same Nova prompt through Diffusers, A1111/Forge, ComfyUI

Why sixth:

- answers whether backend alone caused A1111 quality/speed difference

### Phase 7: Image Model Tests

Deliverable:

- WAI/NoobAI/Animagine tested through best backend

Why seventh:

- model testing should happen after backend baseline is understood

### Phase 8: Acceleration Tests

Deliverable:

- SDXL-Lightning/Hyper-SD/LCM tests against quality bar

Why eighth:

- speed only matters after baseline quality is understood

### Phase 9: Full VN Loop Tests

Deliverable:

- 3-turn text-image-text-image loop saved with outputs and metrics

Why ninth:

- this is the actual product behavior

### Phase 10: Architecture Decision

Deliverable:

- decide whether to keep/refactor/rebuild

Decision options:

- keep current app shell and swap backend
- keep app shell and rewrite orchestration
- rebuild in new repo only if evidence says the current shell blocks progress

## 11. Final Decision Criteria

Text model wins if:

- user wants to continue the story
- quality matches/beats Perchance
- speed is compatible with loop target
- model can be run locally with controllable paths
- backend can stream and unload reliably

Image stack wins if:

- images make the user want to continue the scene
- quality matches/beats Perchance
- generation time is acceptable
- backend is scriptable/API-controllable
- memory behavior is predictable
- all caches/models/outputs can stay on `F:\`

Architecture wins if:

- first tokens arrive quickly
- image generation does not poison next text turn
- three-turn loop is stable
- metrics are reproducible
- code complexity is maintainable

## 12. Immediate Next Task

Build Phase 1:

- parse the Perchance export
- extract Character Profile, Protagonist Profile, turns, and reference replies
- save normalized gold sample files under `outputs/research_gold_samples/`

Then build Phase 2:

- run existing installed models through the text harness
- save outputs
- manually review against Perchance

Only after that should we download more text models or install image backends.
