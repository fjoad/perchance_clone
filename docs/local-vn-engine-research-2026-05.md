# Local VN Engine Research Snapshot

Status: initial research pass
Created: May 23, 2026

This document translates the current research into testable choices for the local visual novel engine target in `docs/local-vn-engine-target.md`.

## The Decision We Actually Need

The project does not need "the best model" in the abstract. It needs a local stack that can repeatedly do this:

1. Accept a character profile, protagonist profile, current scene, and recent turns.
2. Stream story-quality text quickly.
3. Generate a matching illustrated panel.
4. Continue for multiple turns without quality collapse or multi-minute stalls.

The right stack is whichever one hits the quality bar under the hardware and latency constraints.

## Current Local Baseline

Already observed in our local experiments:

- The RTX 3080 12GB can run the current SDXL/Nova image flow if text and image take turns owning the GPU.
- The corrected swap policy was stable: unload text before image, unload image before text.
- In that swap policy, current image generation was roughly 39-44 seconds per panel.
- Text speed under swap was roughly:
  - `qwen-uncensored`: about 126-128 tok/s
  - `dolphin-llama3`: about 120-121 tok/s
  - `dolphin-nemo`: about 86-89 tok/s
- Co-resident text plus image was unstable: sometimes fast, sometimes catastrophic.
- Qwen3.6 35B-A3B IQ4_XS reached about 6.9 tok/s in GPU/RAM split with no image model loaded. That is likely too slow for the target unless quality is dramatically better.

Working hypothesis: for this hardware, stable swapping is more promising than keeping large text and SDXL resident together.

## Text Model Landscape

### Qwen3.6

Qwen3.6 is real and relevant. Ollama lists:

- `qwen3.6:27b-q4_K_M`: 17GB, 256K context, text/image input
- `qwen3.6:27b-q8_0`: 30GB
- `qwen3.6:35b-a3b-q4_K_M`: 24GB, 256K context, text/image input
- `qwen3.6:35b-a3b-q8_0`: 39GB

Source: https://ollama.com/library/qwen3.6/tags

The 35B-A3B MoE has about 35B total parameters but only a small active set per token. That lowers compute, not total model memory. On a 12GB card, Q4 still means GPU/RAM split.

Implication:

- Qwen3.6 is worth testing for quality.
- It is not the first production candidate for sub-minute illustrated turns unless we find a faster runtime, lower quant, or MTP path.
- The official models are not uncensored by default.

### Qwen3.6 Uncensored Variants

There are third-party uncensored Qwen3.6 variants. The most relevant one found is LuffyTheFox's Qwen3.6-35B-A3B Uncensored Genesis V2 APEX MTP GGUF. Its card says it is based on HauhauCS's Qwen3.6-35B-A3B uncensored model, reports 0/465 refusals for the base uncensored source, and recommends APEX/APEX Compact quants.

Source: https://huggingface.co/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-V2-APEX-MTP-GGUF

Implication:

- This is a better Qwen3.6 candidate than the current Fred IQ4_XS if we keep testing huge MoE models.
- It should be tested through llama.cpp or LM Studio if Ollama keeps struggling with Qwen3.6 MoE placement.
- The model card itself notes RTX 3060 12GB regular chatting may be faster without MTP, so MTP is not automatically a win for our workload.

### Gemma 4

Gemma 4 is also real and relevant. Google describes four sizes:

- Effective 2B
- Effective 4B
- 26B MoE
- 31B dense

Google says the 26B MoE activates 3.8B parameters during inference, the 31B dense is the raw-quality model, the larger models have up to 256K context, and Gemma 4 is Apache 2.0.

Source: https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/

Google also announced MTP drafters for Gemma 4 with up to 3x speedup in supported runtimes.

Source: https://blog.google/innovation-and-ai/technology/developers-tools/multi-token-prediction-gemma-4/

Implication:

- Gemma 4 is promising for local speed/quality research.
- The official models are safety-aligned and not the first choice for unrestricted VN roleplay.
- Gemma 4 becomes interesting if a strong uncensored/roleplay fine-tune appears, especially E4B for helper tasks or 26B MoE for main text.

### Gemma Versus Gemini Flash Naming

The search did not turn up an official open-weight model named "Gemma 3.5 Flash". The naming appears to be a collision between Google's open-weight Gemma family and the hosted Gemini Flash family.

Implication:

- Gemini Flash-style models are relevant as quality/speed references, but they are cloud/API products and do not satisfy the offline/no-budget target.
- Gemma 4 is the local/open-weight branch to research.
- If a community page says "Gemma Flash", verify whether it is actually an open-weight Gemma checkpoint before treating it as downloadable.

### Gemma 3 / Existing Gemma

Ollama's Gemma 3 page lists QAT variants for 1B, 4B, 12B, and 27B. The page says QAT preserves similar quality to half precision while lowering memory footprint.

Source: https://ollama.com/library/gemma3

Implication:

- Gemma 3/4 small models are candidates for helper tasks like image prompt extraction, memory summarization, or scene state extraction.
- They are not automatically good main roleplay models because alignment and tone matter more than benchmark strength.

### Mistral Nemo 12B Roleplay Family

The 12B Nemo family remains the most practical near-term tier for this GPU. We already have Dolphin-Nemo. Newer roleplay/uncensored Nemo derivatives are worth testing because they may improve prose without the Qwen3.6 speed penalty.

Candidates found:

- `ReadyArt/Darkness-Incarnate-12B-Nemo-v3.5-GGUF`
- `mav23/MN-12B-Celeste-V1.9-GGUF`
- `Aratako/Mistral-Nemo-12B-RP-GGUF`

Source for Darkness Incarnate GGUF and Ollama/llama.cpp usage: https://huggingface.co/ReadyArt/Darkness-Incarnate-12B-Nemo-v3.5-GGUF

Implication:

- This is the first place to look for a better production text model.
- A strong 12B RP fine-tune at Q4/Q5 likely fits the latency target far better than a 35B MoE split across RAM.

## Image Model Landscape

### SDXL Is Still the Quality Floor

SDXL uses a larger UNet and second text encoder versus earlier Stable Diffusion models. It was built for high-resolution image synthesis and stronger visual fidelity.

Source: https://arxiv.org/abs/2307.01952

Implication:

- SDXL-class anime models are still the likely quality floor for Perchance-plus visual panels.
- SD 1.5 may be faster, but likely needs testing to prove it can meet the desired image quality.

### Fast SDXL Distillation

SDXL-Lightning is explicitly designed for one-step/few-step 1024px generation and is available as LoRA or full UNet.

Source: https://arxiv.org/abs/2402.13929

Implication:

- We should test a fast SDXL path before assuming the current 20+20 two-pass flow is necessary.
- A 4-8 step Lightning/Hyper/LCM style path may beat the current flow on total turn latency if image quality is acceptable.

### Forge Backend

Forge's backend documentation says it reworked resource management, removed old medvram/lowvram flags, and can run SDXL with 4GB VRAM without flags. It also documents:

- `--always-offload-from-vram`: slower but safer, useful when sharing VRAM with other software.
- `--cuda-stream`: can speed SDXL on 30xx/40xx small-VRAM devices by about 15-25%, but riskier.
- `--pin-shared-memory`: can further speed SDXL with CUDA stream, but can crash if shared GPU memory OOMs.

Source: https://github.com/Totsukawaii/SD-webui-forge

Implication:

- Forge is worth testing as an image backend because it may do the exact GPU/RAM choreography we were trying to hand-build.
- It should be tested through its API with the same prompt, resolution, hires/upscale path, and unload behavior.

### ComfyUI Backend

The ComfyUI user guide recommends 12GB+ VRAM for SDXL comfort and documents highvram, lowvram, async offload, and model reload behavior. It also flags repeated load/unload cycles as a cause of slow generation.

Source: https://doccompiler.ai/api/v1/jobs/shared/job_1776340060827_2f9250e5/download/Comfy-Org__ComfyUI__UserGuide.pdf

Implication:

- ComfyUI is powerful for workflow experiments and explicit model unload/reload tests.
- It may not be the fastest path if we constantly force unloads, but it gives good observability and control.

## Key Correction: "Image Model Loaded" Is Not One State

We need to stop saying "the image model is loaded" as if that means one fixed VRAM number.

There are several different states:

- checkpoint file on disk
- model components instantiated in CPU RAM
- UNet/text encoders/VAE resident in VRAM
- model partly offloaded by backend memory manager
- tensors allocated during active generation
- cached CUDA allocations after generation
- Windows shared GPU memory spill

That explains why an idle image pipeline may not use the same VRAM as an active full-resolution two-pass image generation.

The only benchmark that matters is active generation followed by active text generation, with VRAM and backend logs captured at each stage.

## Shortlist To Test Next

Text candidates:

- Baseline: `dolphin-nemo`
- Current speed reference: `dolphin-llama3`
- Current permissive small reference: `qwen-uncensored`
- New 12B RP candidate: `ReadyArt/Darkness-Incarnate-12B-Nemo-v3.5-GGUF:Q4_K_M`
- Optional 12B RP candidates: MN-12B-Celeste and Mistral-Nemo-12B-RP
- Large quality experiment: LuffyTheFox Qwen3.6 Genesis APEX Compact through llama.cpp or LM Studio, not necessarily Ollama

Image candidates:

- Baseline: current Nova Anime XL two-pass flow
- Faster baseline: current Nova Anime XL single-pass 1024 or 1152
- Fast SDXL: current or compatible anime checkpoint with SDXL-Lightning/Hyper/LCM style acceleration
- Backend comparison: current Diffusers vs Forge API vs ComfyUI workflow
- Model comparison: Nova vs NoobAI/WAI/Pony-family candidate if manually downloaded later

## Experiment Order

### Phase 1: Text Gold-Sample Harness

Build a script that:

- loads the Perchance gold sample structure
- uses the character profile and protagonist profile
- replays selected user turns
- runs each candidate model with the same prompt format
- saves each output to disk
- records first-token latency if streaming is available
- records total latency and tokens/sec

Purpose: decide whether text quality is solved by 12B models or whether a larger model is required.

### Phase 2: Image Backend Harness

Build a script that:

- uses fixed image prompts extracted from the gold sample and our generated text
- generates images with current Diffusers flow
- generates comparable images through Forge or ComfyUI if available
- tests full two-pass, single-pass, and fast SDXL variants
- saves all images and timing reports

Purpose: determine whether the current 40-second image path can be improved without visible quality loss.

### Phase 3: Real Turn Harness

Build a script that:

- runs two or three complete story turns
- streams or measures text
- generates image panels after each text turn
- tests swap policy versus any promising co-resident/offload policy
- saves text, image prompts, images, timings, and VRAM snapshots

Purpose: select the actual architecture.

## Current Recommendation

Do not start a new product repo yet.

Use this repo as the lab for one more focused sprint:

1. Build the text gold-sample harness.
2. Test Dolphin-Nemo against at least one newer 12B RP Nemo model.
3. Test the current Qwen3.6 MoE only as a quality ceiling, not as the expected runtime winner.
4. Test current Nova two-pass against faster SDXL image paths.
5. Pick the stack based on saved artifacts, not model reputation.

If a candidate stack meets the target, then start a clean product repo around that stack.

## Expanded Scan: May 23, 2026

The important reframing after the latest discussion is that 12B may be too large for comfortable text/image co-residency, even if it is not too large for a swap policy. We should treat "best text model" and "best full illustrated-turn stack" as different questions.

### Gemini 3.5 Flash Versus Gemma

The user-mentioned "Gemma 3.5 Flash" appears to be a naming mix-up:

- Gemini 3.5 Flash is real and very recent.
- Google describes it as available through the Gemini app, Search AI Mode, Google Antigravity, Gemini API, AI Studio, Android Studio, and enterprise products.
- It is a cloud/API model family, not an offline open-weight Gemma checkpoint.

Source: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5/

Implication:

- Gemini 3.5 Flash is useful as a speed/quality reference, but it violates the local/offline/no-budget target.
- For local work, research Gemma 4, not "Gemma 3.5 Flash".

### Gemma 4 Is Now Relevant

Google's local/open-weight branch is Gemma 4. Google describes four sizes:

- Effective 2B
- Effective 4B
- 26B Mixture of Experts
- 31B Dense

Google says the larger models are competitive open models for their size, with 31B ranking #3 and 26B ranking #6 on the Arena AI text leaderboard at launch.

Source: https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/

Ollama currently lists the practical downloadable Gemma 4 tags:

- `gemma4:e4b-it-q4_K_M`: 9.6GB, 128K context, text/image input
- `gemma4:e4b-it-q8_0`: 12GB, 128K context, text/image input
- `gemma4:26b-a4b-it-q4_K_M`: 18GB, 256K context, text/image input
- `gemma4:31b-it-q4_K_M`: 20GB, 256K context, text/image input

Source: https://registry.ollama.com/library/gemma4/tags

Implication:

- Gemma 4 E4B is the first serious "small enough to maybe stay loaded" candidate.
- Gemma 4 E4B may be useful as a helper model for image prompt extraction, memory, summaries, or state tracking.
- Gemma 4 E4B should be tested as a main story model only to see how far small models have come, not because we expect it to beat roleplay-tuned 12B models.
- Gemma 4 26B-A4B and 31B are not co-resident candidates on a 12GB GPU with SDXL; they are split/offload quality experiments.

### Gemma 4 Uncensored Variants

HauhauCS has a Gemma4-26B-A4B Uncensored Balanced GGUF release. The model card reports 0/465 refusals and provides multiple quants:

- IQ4_XS: 14GB
- Q4_K_M: 17GB
- Q5_K_M: 19GB
- Q8_K_P: 27GB

Source: https://huggingface.co/HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced

Implication:

- Gemma4-26B-A4B Uncensored Balanced IQ4_XS is a more realistic large-model experiment than Qwen3.6 35B-A3B Q4 because it is smaller on disk.
- It still likely cannot co-reside with SDXL on 12GB VRAM.
- It should be tested as a text quality ceiling against Dolphin-Nemo and new 12B roleplay models.

### Qwen3.6 Still Matters, But Not First

Ollama lists Qwen3.6 official tags:

- `qwen3.6:27b-q4_K_M`: 17GB
- `qwen3.6:35b-a3b-q4_K_M`: 24GB
- `qwen3.6:35b-a3b-q8_0`: 39GB

Source: https://ollama.com/library/qwen3.6/tags

There are uncensored Qwen3.6 releases, including HauhauCS and LuffyTheFox variants. The HauhauCS Qwen3.6 35B-A3B uncensored release is widely mirrored and discussed, but the key practical warning remains: Ollama can be more difficult with these models, and our local Fred IQ4_XS run was only about 6.9 tok/s with no image model loaded.

Source: https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/blob/main/README.md

Implication:

- Qwen3.6 is not discarded, but it should be treated as a quality ceiling and runtime stress test.
- It is not the first candidate for the under-60-second illustrated turn loop.

### 8B-12B Roleplay Models Are Still The Practical Text Tier

Community roleplay guidance remains noisy, but the pattern is consistent:

- 8B models are the best co-residency candidates.
- 12B Nemo derivatives are the practical quality/speed sweet spot for 12GB VRAM when using a swap policy.
- 24B+ models can be tried through GPU/RAM split, but their latency is unlikely to work for the target unless quality is dramatically better.

Specific models worth testing:

- `dolphin-nemo`: current 12B baseline
- `L3-8B-Stheno-v3.2` or a current 8B Dark Planet/Stheno-style uncensored model: co-residency candidate
- `Darkness-Incarnate-12B-Nemo-v3.5-GGUF`: roleplay/NSFW Nemo candidate
- `Mistral-Nemo-12B-ArliAI-RPMax`: roleplay-focused Nemo candidate
- `MN-12B-Celeste` / `Mag-Mell` / `Impish_Nemo`: community RP Nemo candidates

Source for Darkness Incarnate GGUF and direct llama.cpp/Ollama usage: https://huggingface.co/ReadyArt/Darkness-Incarnate-12B-Nemo-v3.5-GGUF

Implication:

- The next text experiment should not jump straight to another 20GB model.
- First test one strong 8B and one strong 12B roleplay-tuned candidate against the Perchance gold sample.

### Backend Choice Matters More Now

SillyTavern's official docs are useful as a reality check, even if we are not simply adopting SillyTavern:

- llama.cpp is the base runtime family.
- Ollama is the easiest llama.cpp-based API.
- TabbyAPI is fast for EXL2/GPTQ/FP16 but does not support CPU offload and is not recommended for low VRAM.
- SillyTavern's image extension supports ComfyUI workflows and model placeholders, including GGUF-quantized UNets.

Sources:

- https://docs.sillytavern.app/usage/api-connections/
- https://docs.sillytavern.app/extensions/stable-diffusion/

Implication:

- Ollama remains reasonable for simple GGUF tests.
- llama.cpp/KoboldCpp may be worth testing if Ollama hides too much placement/control detail.
- TabbyAPI is probably not ideal for this 12GB one-GPU text+image problem because CPU offload matters.
- ComfyUI workflows are worth testing if we want product-like visual novel image orchestration without rebuilding every image feature ourselves.

### Image Model Direction

Current public/community guidance still points to SDXL-family anime models for quality:

- Illustrious / NoobAI / WAI-Illustrious for anime quality and prompt adherence
- Pony-family models for broad LoRA ecosystem and complex character/body interactions
- SDXL-Lightning or other fast SDXL distillation paths for few-step generation

SDXL-Lightning is specifically designed for one-step/few-step 1024px generation and is available as LoRA/full UNet.

Source: https://arxiv.org/abs/2402.13929

Community sources still rank WAI-Illustrious, NoobAI, and Pony-family SDXL models highly for anime/NSFW workflows.

Source: https://offlinecreator.com/best-anime-nsfw-models

Implication:

- The next image tests should not assume the current Nova 20+20 two-pass flow is required.
- We need compare:
  - current Nova two-pass
  - current Nova single-pass
  - WAI/NoobAI/Illustrious/Pony candidate at normal steps
  - same candidate with Lightning/Hyper/LCM-style acceleration

### ComfyUI Dynamic VRAM Is Highly Relevant

ComfyUI's March 2026 Dynamic VRAM work directly targets our problem: model weights are mapped without immediately consuming physical VRAM, then faulted in just-in-time as needed. The post says weights can stay in VRAM for speed but be freed under pressure, and that safetensors loading now avoids committed memory allocations.

Source: https://blog.comfy.org/p/dynamic-vram-in-comfyui-saving-local

Implication:

- ComfyUI may be better than our current Diffusers service for text/image sharing behavior.
- We should test ComfyUI Dynamic VRAM with an SDXL anime workflow before spending more time hand-optimizing Diffusers.
- This may answer the user's core confusion: "image model loaded" does not equal "all weights permanently occupying VRAM."

## Revised Test Strategy

The next sprint should test three lanes, not one:

### Lane A: Co-Resident Candidate

Goal: keep text fast while image is available.

Text candidates:

- Gemma 4 E4B uncensored if available in GGUF
- strong 8B RP model such as Stheno/Dark Planet style
- current `dolphin-llama3`

Image candidates:

- fast SDXL anime model or current Nova single-pass
- ComfyUI Dynamic VRAM or Forge memory manager

Success condition:

- text remains above roughly 60 tok/s
- image remains under roughly 30-45s
- no catastrophic second-turn slowdown
- quality is not obviously below Perchance

### Lane B: Swap Policy Quality Candidate

Goal: best realistic quality under stable text/image swapping.

Text candidates:

- current `dolphin-nemo`
- one new 12B Nemo RP model
- one 12B alternate RP model if the first is weak

Image candidates:

- current Nova two-pass
- WAI/NoobAI/Illustrious/Pony SDXL alternative
- fast distilled variant

Success condition:

- text first token begins quickly after image unload
- text total under roughly 60s
- image under roughly 30-60s
- saved output beats current app quality

### Lane C: Quality Ceiling

Goal: learn whether larger models are worth pursuing.

Text candidates:

- Gemma4-26B-A4B Uncensored Balanced IQ4_XS or Q4_K_M
- Qwen3.6 35B-A3B uncensored only if runtime support is stable

Image:

- no image during first test
- only add image if text quality is clearly superior

Success condition:

- quality is obviously better than 12B
- speed is not so slow that it breaks the product

Current expectation:

- Lane B is most likely to produce the actual v1 stack.
- Lane A is the dream if small text quality is good enough.
- Lane C is research only unless the results surprise us.
