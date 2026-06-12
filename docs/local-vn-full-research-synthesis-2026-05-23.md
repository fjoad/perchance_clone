# Local VN Full Research Synthesis

Status: first full research pass complete
Date: May 23, 2026

This is the consolidated answer to:

Given local/offline-only, zero budget, RTX 3080 12GB, unrestricted/adult-capable requirements, Perchance-quality-or-better text, and visual novel image panels, what should we build and test?

This synthesizes:

- text model research
- image model research
- text backend research
- image backend research
- app-space/product architecture research
- prompting/memory/lore best practices
- orchestration constraints

## 1. Core Conclusion

The project should be treated as a local visual novel story engine, not a chatbot plus images.

The correct next phase is not a UI rebuild and not another random model download. It is a gold-sample harness that tests:

- model quality
- backend speed
- prompt architecture
- image quality
- full text-image loop stability

The most likely production shape is:

- one local text model loaded at a time
- one local image backend coordinated through an API
- a normalized story/profile/memory schema
- a layered prompt builder
- a hybrid narrator prompt for VN scenes
- direct character prompt mode retained for one-on-one scenes
- image prompt generated after the story reply, not visibly embedded in prose
- explicit runtime coordinator controlling text/image GPU ownership

## 2. Research Streams

There are two separate streams.

### Stream A: Local Model And Runtime Feasibility

Questions:

- Which text models can run locally with enough quality?
- Which image models can run locally with enough quality?
- Which text backend should serve them?
- Which image backend should generate panels?
- How should GPU/RAM ownership be coordinated?

### Stream B: App-Space And Product Architecture

Questions:

- How do successful roleplay/story apps structure prompts?
- How do they represent characters, user personas, lorebooks, memory, and sessions?
- What features are expected in this product space?
- How should prompt assembly support future features without rewrites?

Both streams matter. A better model will not save a bad story architecture, and a good app shell will not save weak model output.

## 3. What Existing Apps Teach Us

### SillyTavern

SillyTavern is the most relevant power-user reference for character chat.

Important concepts:

- character cards
- personas
- World Info/lorebooks
- Author's Note
- Prompt Manager
- group chats
- image generation extensions
- Visual Novel mode
- prompt inspection/debugging

Sources:

- https://docs.sillytavern.app/usage/prompts/
- https://docs.sillytavern.app/usage/prompts/prompt-manager/
- https://docs.sillytavern.app/usage/core-concepts/personas/
- https://docs.sillytavern.app/usage/core-concepts/worldinfo/
- https://docs.sillytavern.app/usage/core-concepts/authors-note/
- https://docs.sillytavern.app/usage/core-concepts/groupchats/
- https://docs.sillytavern.app/usage/user-settings/visual-novel/
- https://docs.sillytavern.app/usage/characters/

Takeaway:

- Use prompt blocks, personas, world info, and author notes as first-class concepts.
- Do not copy SillyTavern's entire UI complexity into v1.

### Chub

Chub documents the character-chat prompt structure clearly.

Important concepts:

- system prompt
- character definitions
- chat history
- post-history instructions
- prompt note
- assistant prefill
- lorebook macros
- alternate greetings
- per-character system prompt

Sources:

- https://docs.chub.ai/docs/advanced-setups/prompting
- https://docs.chub.ai/docs/advanced-setups/lorebooks
- https://docs.chub.ai/docs/the-basics/character-creation

Takeaway:

- The app should support structured character/profile/lore data and flexible prompt ordering.
- Imported card-specific system prompts should be treated as data, not allowed to override the app's response contract blindly.

### NovelAI

NovelAI is the strongest story-first reference.

Important concepts:

- story settings
- Memory
- Author's Note
- Lorebook
- Text Adventure mode
- exportable story data
- model/preset selection

Sources:

- https://docs.novelai.net/en/text/editor/storysettings
- https://docs.novelai.net/en/text/lorebook
- https://docs.novelai.net/faq.html

Takeaway:

- VN/story generation should think in terms of story context, not only chat messages.
- Memory, Author's Note, and Lorebook are separate context instruments with different purposes.

### Agnai / Agnaistic

Agnai is relevant because it is open/self-hostable and supports many memory/profile patterns.

Important concepts:

- memory books
- chat embeds
- user embeds
- personas
- scenario overrides
- multiple backend support

Sources:

- https://github.com/agnaistic/agnai
- https://agnai.guide/docs/creating-a-character/
- https://agnai.guide/docs/memory/
- https://agnai.guide/docs/memory/memory-books.html
- https://agnai.guide/docs/chat-settings/

Takeaway:

- Memory should not be one blob. It should be layered: manual memory, keyword memory, embeddings later, persona memory, character memory.

### Perchance

Perchance is the user's quality benchmark, not the architecture spec.

Use Perchance exports to measure:

- character/profile structure
- protagonist/user structure
- user turns
- assistant replies
- story style
- image prompt behavior

Do not assume:

- Perchance's exact hidden prompt
- Perchance's backend
- Perchance's image model

## 4. Feature Surface We Should Design For

V1 does not need every feature, but the architecture should not block them.

### Profiles And Characters

- Character Profile
- Protagonist/User Profile
- appearance anchors
- voice/speech style
- example dialogue
- alternate greetings/openings
- relationship frame
- reminder note / author note
- character-specific lorebook
- image anchor summary
- import from Perchance, SillyTavern, Chub, plain text

### Story And Session

- new story
- continue story
- branch story
- rewind
- edit user message
- edit AI reply
- reroll text
- reroll image
- save checkpoint
- scene state
- active cast
- hidden state/secrets
- relationship state

### Memory And Lore

- pinned memory
- scene state
- running summary
- lorebook/world info
- character memory
- protagonist memory
- relationship memory
- manual memory editor
- automatic memory extraction later

### Image Features

- auto image after reply
- manual image button
- image prompt preview/edit
- regenerate image
- keep/change seed
- negative prompt presets
- style presets
- character visual anchors
- LoRA support
- upscaler/hires workflows
- gallery per story

### Developer/Evaluation Features

- rendered prompt inspector
- saved generation metadata
- backend logs
- VRAM monitor
- model comparison harness
- prompt A/B tests

## 5. Prompt Architecture

The app should support multiple prompt modes.

### Mode A: Direct Character

Frame:

- "You are {{char}}."

Use for:

- one-on-one scenes
- smaller models
- companion-style direct interaction

Risk:

- weaker multi-character story support
- can become chat-like

### Mode B: Storyteller

Frame:

- "You are the story engine/narrator for an interactive visual novel."

Use for:

- multi-character scenes
- storybook/VN prose

Risk:

- smaller models can become generic or assistant-like

### Mode C: Hybrid Cast Narrator

Frame:

- "You are the narrator and performer for the active scene. Portray all active non-user characters. Do not control the protagonist."

Likely v1 default.

Why:

- supports multiple characters in one model call
- preserves user agency
- keeps text in VN prose format
- does not require one loaded model per character

### Mode D: Group Chat Simulation

Frame:

- one model
- multiple calls
- one active speaker per call

Use later if:

- hybrid narrator cannot keep character voices distinct

Do not start here because it is slower and more complex.

### Prompt Stack

The prompt builder should support ordered layers:

1. runtime/system wrapper
2. task frame
3. response contract
4. world/scene state
5. active character profiles
6. protagonist profile
7. relationship state
8. retrieved lore/memory
9. example dialogue/style samples
10. recent conversation
11. author note/immediate reminder
12. current user turn

This follows the same broad pattern seen in SillyTavern, Chub, NovelAI, and Agnai.

## 6. Text Model Findings

### Important Correction

12B is not automatically the answer.

12B keeps appearing because it is a practical upper tier for RTX 3080 12GB under clean swap, not because it is proven superior for this app.

Smaller specialized 8B/9B models may win the actual app if they:

- avoid assistant-slop
- follow roleplay action/dialogue format better
- stream faster
- stay fully VRAM-resident
- enable smoother image coordination

### Test Order

Test small specialized models before assuming 12B.

Recommended order:

1. Current `dolphin-nemo` baseline.
2. `Dolphin-X1-8B-GGUF`.
3. `Peach-2.0-9B-8k-Roleplay-GGUF`.
4. `Lumimaid-v0.2-8B-GGUF`.
5. `Llama-3.1-8B-Stheno-v3.4`.
6. `Roleplay-Hermes-3-Llama-3.1-8B`.
7. One Qwen3.5 9B uncensored/abliterated variant.
8. `MN-12B-Celeste-V1.9-GGUF`.
9. `Mistral-Nemo-12B-ArliAI-RPMax`.
10. `Darkness-Incarnate-12B-Nemo-v3.5-GGUF`.
11. Gemma 4 E4B as small-model/helper surprise.
12. Large quality ceilings only after the above.

Key sources:

- https://huggingface.co/dphn/Dolphin-X1-8B-GGUF
- https://huggingface.co/QuantFactory/Peach-9B-8k-Roleplay-GGUF
- https://huggingface.co/mradermacher/Peach-2.0-9B-8k-Roleplay-GGUF
- https://huggingface.co/NeverSleep/Lumimaid-v0.2-8B-GGUF
- https://huggingface.co/Triangle104/Roleplay-Hermes-3-Llama-3.1-8B-Q4_K_M-GGUF
- https://huggingface.co/mav23/MN-12B-Celeste-V1.9-GGUF
- https://huggingface.co/ReadyArt/Darkness-Incarnate-12B-Nemo-v3.5-GGUF

## 7. Text Backend Findings

### Ollama

Keep as default for now.

Why:

- already integrated
- simple HTTP API
- supports streaming
- supports `keep_alive`
- provides usage metrics such as `load_duration`, `prompt_eval_count`, `eval_count`, and `eval_duration`
- unload can be controlled with `keep_alive: 0`

Sources:

- https://docs.ollama.com/api/usage
- https://docs.ollama.com/api/generate
- https://github.com/ollama/ollama/blob/main/docs/api.md

Risks:

- hides exact chat template/offload behavior
- can be opaque for new architectures
- less direct than llama.cpp for diagnostics

### llama.cpp server

Use as diagnostic/alternate backend.

Why:

- direct GGUF runtime
- OpenAI-compatible server
- explicit GPU offload controls
- direct KV/context/flash-attn tuning

Source:

- https://www.mintlify.com/ggml-org/llama.cpp/inference/server

Use when:

- Ollama is slow
- Ollama template behavior is suspicious
- Qwen/Gemma/MoE models need lower-level runtime control

### KoboldCpp

Use as roleplay-runtime comparison.

Why:

- widely used in local roleplay
- GGUF-friendly
- exposes GPU layer and context behavior
- SillyTavern integrates with it

Sources:

- https://koboldcpp.com/
- https://docs.sillytavern.app/usage/api-connections/koboldcpp/

Use when:

- a model has good reputation in RP but weak output in Ollama
- we suspect prompt/context shifting behavior matters

### TabbyAPI / ExLlamaV2 / EXL2

Do not start here.

Why:

- strong when model fits fully in VRAM
- less ideal for CPU/GPU split and image juggling
- requires separate model format

Use only if:

- an 8B/9B model wins quality tests
- it fits fully in VRAM
- we want maximum text speed

## 8. Image Model Findings

### Current Baseline

Keep Nova Anime XL as control.

Why:

- already installed
- already integrated
- measured around 39-44 seconds per image under clean-swap app flow

### Current Anime SDXL Candidates

Highest priority:

1. WAI-Illustrious
2. NoobAI XL V-Pred / NoobAI XL 1.1
3. Animagine XL 4.0
4. Pony V6 XL later

Sources:

- https://civitai.green/models/827184/wai-%2A%2A%2A%2A-illustrious-sdxl
- https://illustriousxl.org/wai-illustrious-sdxl
- https://huggingface.co/Laxhar/noobai-XL-1.1
- https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0
- https://huggingface.co/cagliostrolab/animagine-xl-4.0
- https://openlaboratory.com/models/pony-diffusion-v6-xl/
- https://huggingface.co/morikomorizz/Pony-Diffusion-V6-XL-GGUF

Conclusion:

- SDXL anime/Illustrious/NoobAI/WAI is the practical main image lane.
- FLUX is not the first production lane on 12GB.

## 9. Image Acceleration Findings

Acceleration should be tested after quality baseline is known.

Candidates:

- SDXL-Lightning 4-step or 8-step
- Hyper-SD
- LCM-LoRA

Sources:

- https://huggingface.co/ByteDance/SDXL-Lightning
- https://arxiv.org/abs/2402.13929
- https://huggingface.co/ByteDance/Hyper-SD
- https://huggingface.co/blog/lcm_lora
- https://huggingface.co/docs/diffusers/main/using-diffusers/inference_with_lcm_lora

Conclusion:

- SDXL-Lightning 4/8-step is first acceleration test.
- LCM-LoRA is likely better as fast-preview mode unless quality surprises us.
- Do not optimize speed before choosing a quality baseline.

## 10. Image Backend Findings

### Raw Diffusers

Keep as control, not assumed production.

Why:

- transparent
- scriptable
- already works

Problem:

- we own all memory/load/scheduler behavior
- easier to accidentally misconfigure caches
- may lag behind tuned WebUI/Comfy workflows

### A1111

Test as image backend candidate.

Why:

- mature API
- `/sdapi/v1/txt2img`
- `/sdapi/v1/img2img`
- `/sdapi/v1/options`
- `/sdapi/v1/unload-checkpoint`
- `/sdapi/v1/reload-checkpoint`

Source:

- https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/API

Use to answer:

- Did A1111 look better/faster because backend settings differ from Diffusers?

### Forge

Test before or alongside A1111.

Why:

- A1111-like
- focused on resource management and inference speed
- relevant to low/mid VRAM

Source:

- https://github.com/lllyasviel/stable-diffusion-webui-forge

Use to answer:

- Is Forge the easiest way to get better image speed/quality on 12GB?

### ComfyUI

Most important future-proof backend to test.

Why:

- workflow-native
- strong ecosystem
- API workflow queue
- supports `/prompt`, `/ws`, `/system_stats`, etc.
- Dynamic VRAM may directly help with local memory pressure

Sources:

- https://docs.comfy.org/development/comfyui-server/comms_routes
- https://blog.comfy.org/p/dynamic-vram-in-comfyui-saving-local

Caution:

- Dynamic VRAM is promising, but must be measured locally because community reports show workflow-specific slowdowns and changed VRAM behavior.

## 11. Orchestration Findings

Do not load one model per character.

For local 12GB:

- one text model loaded
- one image backend coordinated
- one GPU owner at a time unless small-model/co-residency tests prove otherwise

Candidate architectures:

### Clean Swap

Flow:

- text hot
- stream reply
- unload text
- generate image
- unload image
- reload/prewarm text

Status:

- already measured stable locally

### Text Hot + Image Backend Idle

Flow:

- text model hot
- image backend server running but model unloaded/offloaded
- generate image on demand

Needs test:

- ComfyUI/Forge idle VRAM impact

### Co-Resident Small Text

Flow:

- keep 8B/9B text model hot
- image backend stays idle/warm

Needs test:

- whether small model quality is enough
- whether image backend idle does not destroy text speed

## 12. Data Model Recommendation

Internally normalize everything.

Core entities:

- CharacterProfile
- ProtagonistProfile
- StorySession
- SceneState
- CastState
- RelationshipState
- MemoryEntry
- LoreEntry
- ImageProfile
- GenerationRun
- BackendConfig

Import formats:

- Perchance JSON
- SillyTavern / Tavern Card V2
- Chub-style cards
- plain text

Source:

- https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md

Important rule:

- source system prompts are imported as fields, but the app owns the final response contract.

## 13. Evaluation Strategy

Text is judged by:

- would the user want to reply?
- does it match or beat Perchance?
- does it use Character Profile?
- does it use Protagonist Profile?
- does it preserve user agency?
- does it balance narration/action/dialogue?
- does it maintain continuity?

Image is judged by:

- would the panel make the user want to continue?
- does it match text?
- does it preserve character identity?
- is composition VN-useful?
- is anatomy acceptable?
- is expression/body language useful?
- does style fit?

Full loop is judged by:

- first-token latency
- full text time
- image time
- reload/prewarm time
- peak dedicated VRAM
- peak shared GPU memory
- stability over three turns

## 14. Final Recommendation

Do not rebuild yet.

Do not download more huge models yet.

Do not install every backend yet.

Next actual work:

1. Build the gold-sample extractor for the Perchance JSON.
2. Build the text harness against installed models.
3. Compare direct character prompt vs hybrid narrator prompt.
4. Test one or two small model candidates.
5. Only then test 12B candidates.
6. Separately test image backends with current Nova before changing image model.

This is the shortest path out of the spiral because every future decision will be tied to saved outputs and timings.

## 15. Research Coverage Status

Covered in first full pass:

- text model candidate space
- smaller-model anti-bias pass
- large-model quality ceilings
- text backend candidates
- image model candidates
- image acceleration candidates
- image backend candidates
- app-space reference patterns
- prompting modes
- memory/lore patterns
- multi-character/cast management
- storage/cache hygiene
- full-loop orchestration

Open because they require experiments, not more reading:

- which text model actually writes best for the gold sample
- whether small models beat 12B in practice
- whether Forge or ComfyUI beats Diffusers locally
- whether WAI/NoobAI beats Nova locally
- whether SDXL-Lightning is good enough for final panels
- whether co-residency is viable on the actual machine

Those cannot be settled by research alone. They need the harness.
