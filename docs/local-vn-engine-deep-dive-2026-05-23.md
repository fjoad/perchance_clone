# Local VN Engine Deep Dive

Status: broader current-space research pass
Date: May 23, 2026

This is the broader landscape pass that the project needs before another benchmark spiral. It is not a final stack decision. It is a map of what is possible, what is probably a trap, and what should be tested.

The core target remains: local/offline illustrated VN turns with high-quality story text, character/protagonist profiles, matching images, and roughly sub-minute user-perceived latency.

## 1. Is Offline Still The Right Constraint?

Short answer: yes for this project, unless the product goal changes.

Cloud/API models would make the text quality problem easier, and possibly the image problem easier, but they violate multiple current constraints:

- zero recurring cost
- offline runtime
- unrestricted/adult-capable usage
- private local story/character data
- repeatable local experimentation without vendor policy changes

Cloud can be used as a reference point for quality, but it should not be part of the v1 architecture under the current requirements.

Practical conclusion:

- Build local-first.
- Use cloud/frontier outputs only as a benchmark sample if needed.
- Do not spend time building a cloud fallback until local viability is proven or disproven.

## 2. The Real Bottleneck Is Not Just Model Size

The trap in this project is asking "what is the best model?" instead of "what full turn can we run?"

For the VN loop, the relevant bottlenecks are:

- text model load time
- first-token latency
- decode speed
- context/prompt length
- image model load time
- active image generation VRAM spike
- image backend cache/offload behavior
- whether text and image are co-resident, swapped, or partially offloaded
- whether second and third turns degrade after CUDA memory fragmentation or backend cache churn

So the right unit of measurement is:

`story turn = text generation + image generation + next text generation + next image generation`

Single-model tokens/sec tests are useful, but only as supporting evidence.

## 3. Current Text Model Landscape

### 3.1 Cloud Frontier Models

Cloud models are the quality/speed reference, not the implementation target.

Examples:

- Gemini 3.5 Flash is recent and fast, but it is a hosted Gemini model, not an open-weight Gemma model.
- Claude/GPT/Gemini cloud models would likely beat local roleplay models in coherence and instruction following.

Source: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5/

Project implication:

- Useful for "what quality should local beat?"
- Not viable for the product because of cost, privacy, offline, and unrestricted-content constraints.

### 3.2 Huge Open-Weight Flagships

These are impressive but mostly irrelevant to a 12GB single-GPU VN app.

Llama 4:

- Ollama's Llama 4 tags show very large local artifacts: Scout Q8 around 117GB and Maverick Q8 around 428GB.
- These are not realistic for this hardware.

Source: https://registry.ollama.com/library/llama4/tags

DeepSeek/Kimi/MiniMax/GLM-style frontier open weights:

- Often too large for local consumer single-GPU use.
- Useful as ecosystem signals, not first-line candidates.

Project implication:

- Do not chase flagship open-weight models for v1.
- If a distilled/quantized small derivative appears, evaluate that derivative separately.

### 3.3 Large Local Quality-Ceiling Models

These are potentially useful for checking whether bigger models materially improve story quality.

Qwen3.6:

- Qwen3.6-35B-A3B is an open-weight MoE model with about 35B total parameters and about 3B active parameters per token.
- Qwen positions it around agentic coding and long-context capability.
- Ollama lists Qwen3.6 27B and 35B-A3B variants, but Q4 sizes are still large enough to force GPU/RAM split on 12GB VRAM.

Sources:

- https://qwen.ai/blog?id=qwen3.6-35b-a3b
- https://ollama.com/library/qwen3.6/tags

Observed locally:

- Fred Qwen3.6 35B-A3B IQ4_XS produced about 6.9 tok/s with no image model loaded.
- That is too slow for the normal VN loop unless quality is dramatically better.

Gemma 4:

- Google describes Gemma 4 as an open-weight family with effective 2B, effective 4B, 26B MoE, and 31B dense sizes.
- Ollama lists Gemma4 E4B, 26B-A4B, and 31B tags.
- Gemma4 E4B Q4_K_M is around 9.6GB, which is unusually interesting for this project because it might fit more comfortably than 12B models.

Sources:

- https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/
- https://registry.ollama.com/library/gemma4/tags

Uncensored Gemma 4:

- HauhauCS has Gemma4-26B-A4B Uncensored Balanced GGUF, including IQ4_XS around 14GB and Q4_K_M around 17GB.
- This is a better large-model quality-ceiling candidate than many 20GB+ options, but it still probably cannot co-reside with SDXL.

Source: https://huggingface.co/HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced

Mistral Small / 24B class:

- Mistral Small 3.2 / 24B-class models are stronger than 12B but too large to co-reside easily.
- Roleplay fine-tunes exist in this size class, such as Cydonia/Harbinger-style 24B models, but they are likely swap-policy or quality-ceiling candidates.

Source: https://openlaboratory.com/models/mistral-small-3_2-24b-instruct-2506/

Project implication:

- Treat 24B-35B models as Lane C: quality ceiling.
- Do not assume they are production candidates until they beat 8B/12B quality by a lot.

### 3.4 Practical Main Text Tier: 8B-12B

This is the most important text tier for v1.

Why:

- Fits or nearly fits on a 12GB GPU.
- Can use GGUF/Ollama/llama.cpp.
- Enough speed for streaming.
- Many roleplay/uncensored fine-tunes exist.
- Can use swap policy with SDXL image generation.

Current baseline:

- `dolphin-llama3` 8B: fast local baseline.
- `dolphin-nemo` 12B: current higher-quality local baseline.
- `qwen-uncensored` 7B: permissive small baseline.

12B Mistral Nemo roleplay candidates:

- Darkness-Incarnate-12B-Nemo-v3.5 GGUF: explicitly marked roleplay/NSFW/unaligned.
- Mistral-Nemo-12B-ArliAI-RPMax: trained on curated creative writing and RP datasets, with stated focus on variety and avoiding repetitive "GPT-isms".
- MN-12B-Celeste-V1.9: Mistral Nemo 12B roleplay/storywriting model; model card notes improved NSFW, narration, and long-context behavior.

Sources:

- https://huggingface.co/ReadyArt/Darkness-Incarnate-12B-Nemo-v3.5-GGUF
- https://huggingface.co/Triangle104/Mistral-Nemo-12B-ArliAI-RPMax-v1.3-Q4_K_S-GGUF
- https://huggingface.co/mav23/MN-12B-Celeste-V1.9-GGUF

8B roleplay candidates:

- L3 Stheno 8B GGUF: model card describes it as made for 1-on-1 roleplay, scenarios, RPGs, and storywriting, and uncensored during actual roleplay scenarios.
- Dark Planet / Stheno / Lumimaid-style Llama 3.1 8B merges are potential co-residency candidates.

Source: https://huggingface.co/backyardai/L3-8B-Stheno-v3.3-32K-GGUF

Project implication:

- Test at least one new 8B RP model and one new 12B RP model before testing another giant model.
- 8B is the co-residency hope.
- 12B is the likely quality/speed swap-policy winner.

### 3.5 Small Models: 2B-4B

Small models are not automatically bad anymore, but they are risky as the main story engine.

Potential roles:

- image prompt extraction
- memory summarization
- scene state extraction
- safety-free helper tasks
- maybe main text if Gemma4 E4B surprises us

Candidates:

- Gemma4 E4B official or uncensored derivative if available
- Qwen small instruct/abliterated derivatives
- Phi/Ministral-style small instruction models for helper tasks

Project implication:

- Small models are important for architecture, not necessarily main prose.
- If an 8B or 12B main model writes prose, a 4B helper model may be unnecessary; a rules parser may be enough.

## 4. Text Runtime Landscape

### Ollama

Strengths:

- easiest setup
- local HTTP API
- model management
- GGUF/llama.cpp lineage
- good enough for simple benchmark loops

Weaknesses:

- hides some placement details
- less direct control over exotic offload/tensor placement
- new architectures can lag or behave oddly

Source: https://docs.sillytavern.app/usage/api-connections/

Project implication:

- Keep Ollama for baseline tests and app integration.
- Do not assume Ollama is the best runtime for Qwen3.6/Gemma4 large experiments.

### llama.cpp / llama-server

Strengths:

- closest to the metal for GGUF
- direct control of GPU layers and runtime flags
- fast-moving support for new quantization/runtime features

Weaknesses:

- more manual
- app integration needs more care

Project implication:

- Use llama.cpp directly when we need placement visibility, MTP branches, or architecture support that Ollama hides.

### KoboldCpp

Strengths:

- GGUF
- streaming
- explicit GPU layer allocation
- commonly used for local roleplay
- CPU offload helpful for low VRAM

Source: https://koboldcpp.com/

Project implication:

- Strong candidate for the roleplay text backend if Ollama becomes a black box.

### TabbyAPI / ExLlamaV2

Strengths:

- very fast if the model fits VRAM
- good for EXL2/GPTQ/FP16

Weaknesses:

- less suitable when CPU offload is required
- not ideal for a 12GB GPU if we depend on swapping or partial CPU RAM usage

Source: https://docs.sillytavern.app/usage/api-connections/tabbyapi/

Project implication:

- Consider TabbyAPI only for fully GPU-resident 8B/12B experiments, not for 20GB split models.

## 5. Current Image Model Landscape

### 5.1 Cloud Image Models

Cloud image models are not the target for v1.

They may be faster or higher quality, but they violate:

- zero budget
- offline runtime
- unrestricted/adult-capable local usage
- privacy/control

Project implication:

- Use cloud images only as external quality references if needed.

### 5.2 SDXL Anime / Illustration Models

This remains the practical local quality floor.

Relevant families:

- Nova Anime XL: current baseline.
- Illustrious / NoobAI / WAI-Illustrious: strong anime/illustration direction.
- Pony-family models: huge LoRA ecosystem, stylized character/body interaction, but prompt format and LoRA ecosystem differ.
- Animagine XL and older anime SDXL models: still useful baselines.

Community guides still point to SDXL anime models as the strongest practical local anime/illustration tier in early 2026.

Sources:

- https://www.insiderllm.com/guides/best-anime-stylized-checkpoints-local-image-generation/
- https://offlinecreator.com/best-anime-nsfw-models

Project implication:

- Do not assume Nova is the final image model.
- Test Nova against WAI/NoobAI/Illustrious/Pony candidates with the same prompts and speed constraints.

### 5.3 SD 1.5

Strengths:

- fastest
- enormous LoRA ecosystem
- much easier co-residency
- strong character LoRA availability

Weaknesses:

- lower native resolution
- generally weaker composition/fidelity than SDXL
- may not beat Perchance image quality without heavy prompt/LoRA work

Project implication:

- Worth one speed/quality test as a fallback lane.
- Not the default unless SDXL cannot hit latency.

### 5.4 FLUX / Newer Image Families

Strengths:

- strong prompt following
- high quality
- modern workflows

Weaknesses:

- often larger/slower
- anime/NSFW ecosystem may be less mature than SDXL/Pony/Illustrious for our exact target
- may rely on quantized/offloaded workflows on 12GB

Project implication:

- Not the first v1 image target.
- Revisit only if SDXL alternatives fail quality.

### 5.5 Few-Step SDXL Acceleration

This is a high-priority research path.

SDXL-Lightning:

- Designed for one-step/few-step 1024px generation based on SDXL.

Source: https://arxiv.org/abs/2402.13929

Hyper-SD:

- Few-step acceleration for SDXL and related models.

Source: https://arxiv.org/abs/2404.13686

Project implication:

- The current 20+20 two-pass flow may be overkill.
- Test 4-step/8-step fast SDXL against the current baseline.
- Quality must be manually reviewed; speed alone does not win.

## 6. Image Runtime / Backend Landscape

### Current Diffusers Pipeline

Strengths:

- already integrated
- controlled from Python
- easy to script

Weaknesses:

- may be weaker than Forge/ComfyUI at real-world VRAM choreography
- our hand-built unload/load logic may be reinventing backend features

Project implication:

- Keep it as baseline.
- Do not spend much more time optimizing it until Forge/ComfyUI are tested.

### A1111 / Forge

Forge reworks the A1111 backend for better resource management. Documentation and mirrors mention:

- SDXL can run with low VRAM.
- old medvram/lowvram flags are removed or less relevant.
- `--always-offload-from-vram` can reduce risk but slow things down.
- CUDA stream / malloc options may help 30xx/40xx cards.

Sources:

- https://huggingface.co/spaces/fluxdev/stable-diffusion-webui-forge/blame/main/README.md
- https://deepwiki.com/lllyasviel/stable-diffusion-webui-forge/

Project implication:

- Forge is a strong candidate for image backend if it gives A1111-like speed with lower VRAM pain.
- Test through API, not GUI.

### ComfyUI

ComfyUI is highly relevant because of Dynamic VRAM.

ComfyUI's March 2026 Dynamic VRAM work changes how model weights are mapped and faulted into VRAM. The official Comfy post describes it as a major improvement for memory-constrained hardware.

Source: https://blog.comfy.org/p/dynamic-vram-in-comfyui-saving-local

Caveat:

- Community reports are mixed: Dynamic VRAM can help avoid OOM but may also slow workflows if it over-offloads or reloads too aggressively.

Source: https://github.com/Comfy-Org/ComfyUI/discussions/12699

Project implication:

- ComfyUI should be tested because it may solve the "image model loaded does not mean 10GB permanently occupied" problem.
- It may also make things slower. We need measured local results.

## 7. Co-Resident Versus Swap: Current Best Guess

Co-resident stack:

- Best UX if it works.
- Likely requires 4B-8B text and efficient image backend.
- May need ComfyUI/Forge memory manager rather than raw Diffusers.
- Text quality risk is the main concern.

Swap-policy stack:

- More stable based on our current local tests.
- Allows 12B text and SDXL image quality.
- User sees text streaming first, then image.
- Reload overhead can be hidden or reduced with prewarm, but must be measured.

Large split stack:

- 20GB+ text model with GPU/RAM split.
- Likely too slow for interactive story unless new runtime features dramatically improve speed.
- Use only as a quality ceiling.

Current recommendation:

- Lane A: try to make co-residency work with 8B or smaller text.
- Lane B: treat 12B swap policy as the likely v1.
- Lane C: test 20GB+ models only to learn whether quality justifies pain.

## 8. Specific Model/Backend Shortlist

### Text Lane A: Co-Resident Candidates

Test these because they might stay responsive while image backend is warm:

- `dolphin-llama3` current 8B baseline
- L3 Stheno 8B or Dark Planet/Stheno-style 8B
- Gemma4 E4B official as a small-model quality surprise test
- any credible uncensored Gemma4 E4B derivative if found

### Text Lane B: Main Quality Candidates

Test these for likely v1:

- `dolphin-nemo` current 12B baseline
- `MN-12B-Celeste-V1.9-GGUF`
- `Mistral-Nemo-12B-ArliAI-RPMax`
- `Darkness-Incarnate-12B-Nemo-v3.5-GGUF`
- MistralNemoDionysusV3 if a stable GGUF is available

### Text Lane C: Quality Ceilings

Test only after Lane A/B:

- Gemma4-26B-A4B Uncensored Balanced IQ4_XS
- Qwen3.6 35B-A3B uncensored with llama.cpp/KoboldCpp if Ollama remains poor
- Mistral Small 24B RP derivatives

### Image Lane A: Fast/Co-Resident

Test:

- current Nova single-pass
- SDXL-Lightning/Hyper/LCM accelerated workflow
- SD 1.5 anime fallback
- ComfyUI Dynamic VRAM or Forge API

### Image Lane B: Quality

Test:

- current Nova two-pass baseline
- WAI-Illustrious / NoobAI / Illustrious-family checkpoint
- Pony-family checkpoint if prompt/LoRA ecosystem fits

## 9. What Would Change The Strategy?

Change to co-resident-first if:

- an 8B or E4B model matches the Perchance text quality over multiple turns
- ComfyUI/Forge keeps image generation under 30-45s with text warmed
- second-turn slowdown disappears

Change to swap-policy-first if:

- 12B models clearly beat 8B text quality
- image quality needs SDXL two-pass or a heavier model
- reload/unload overhead remains predictable

Change to large-model-first only if:

- Gemma4/Qwen3.6/Mistral Small quality is obviously much better than 12B
- runtime reaches acceptable first-token and total latency
- it can still coexist with image generation through a practical workflow

## 10. Next Research-To-Experiment Bridge

The next work should produce artifacts, not another opinion.

Build two harnesses:

1. Text Gold-Sample Harness
   - parse the Perchance export
   - use character profile and protagonist profile
   - replay selected user turns
   - run each candidate model
   - save visible text outputs, timings, and prompts

2. Image Backend Harness
   - run fixed scene/image prompts through Diffusers, Forge, and/or ComfyUI
   - compare Nova, fast SDXL, and one newer anime checkpoint
   - save images, prompts, timings, and VRAM snapshots

Then run a real two-turn VN harness with the best candidates.

## 11. Bottom Line

Offline is still the right direction for the stated product.

The likely answer is not "one giant model". The likely answer is:

- 8B if co-residency quality is surprisingly good
- 12B Nemo RP model if text quality matters more
- SDXL-family image model through a smarter backend
- swap policy unless ComfyUI/Forge proves co-residency works

The next decisive step is not more abstract research. It is artifact-generating evaluation using the Perchance export as the text gold sample and saved image panels as the visual gold sample.

