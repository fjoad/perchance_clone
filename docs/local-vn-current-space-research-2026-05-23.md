# Local VN Current-Space Research

Status: first pass complete
Date: May 23, 2026

This memo answers the active project question:

Given a fully local/offline, zero-budget, unrestricted visual novel engine target on an RTX 3080 12GB, what current text models, image models, runtimes, and orchestration patterns are realistic?

This is not asking whether offline is desirable. Offline is already a project constraint.

Follow-up correction:

- The full research synthesis is `docs/local-vn-full-research-synthesis-2026-05-23.md`.
- The end-to-end execution plan is `docs/local-vn-end-to-end-plan-2026-05-23.md`.
- The broader app-space/product architecture deep dive is `docs/local-vn-app-space-deep-dive-2026-05-23.md`.
- A separate adversarial small-model pass challenges the 12B anchoring risk: `docs/local-vn-small-model-adversarial-pass-2026-05-23.md`.

## Current Progress

- Part 1: Text model landscape: complete first pass.
- Part 2: Image model landscape: complete first pass.
- Part 3: Runtime/backend landscape: complete first pass.
- Part 4: Experiment matrix: complete first pass.

## Part 1: Text Model Landscape

### Executive Text Conclusion

The text side should be treated as three separate lanes:

- Co-resident lane: 7B-9B models and maybe Gemma 4 E4B. These are the only plausible "keep text hot while image backend is warm" candidates.
- Main quality lane: 12B Mistral Nemo roleplay/story models. This is still the strongest practical tier for Perchance-quality VN prose on this hardware, especially with one-GPU-owner swapping.
- Quality ceiling lane: Gemma 4 26B-A4B, Qwen3.6 27B, Qwen3.6 35B-A3B, and Mistral Small 24B. These are not first-choice runtime models on a 12GB card, but they can answer whether larger local models produce meaningfully better writing.

The immediate text research result is: do not jump straight from Dolphin-Nemo to another huge MoE. First test one strong 8B roleplay candidate and two or three strong 12B Nemo roleplay/story candidates against the Perchance gold sample.

### Important Constraint: Roleplay Quality Is Not Benchmark Quality

The project needs interactive-fiction quality:

- character profile adherence
- protagonist profile awareness
- emotionally responsive dialogue
- third-person action and body language
- strong scene momentum
- multi-turn continuity
- unrestricted/adult-capable behavior

Reasoning benchmarks, coding benchmarks, and long context specs are useful, but they do not prove VN prose quality.

### Lane A: Co-Resident Text Candidates

These are candidates for keeping text responsive while an image backend remains resident or semi-resident.

#### Current Baselines

- `dolphin-llama3`: already installed; fast local baseline.
- `qwen-uncensored`: already installed; permissive small baseline.

Local measured behavior from prior runs:

- `dolphin-llama3` can exceed 100 tok/s in clean swap tests.
- `qwen-uncensored` can exceed 120 tok/s in clean swap tests.
- Both are plausible co-resident experiments, but writing quality still must be judged against the Perchance sample.

#### Llama 3.1 / Dark Planet / Stheno / Lumimaid-Style 8B

The strongest 8B lead found is `DavidAU/Llama-3.1-128k-Dark-Planet-Uncensored-8B-GGUF`.

Why it matters:

- It is GGUF.
- It is explicitly uncensored.
- The model card shows direct `llama-server`, `llama-cli`, and Ollama usage.
- It is built from roleplay/creative-writing adjacent 8B models including Stheno and Lumimaid lineage.

Source: https://huggingface.co/DavidAU/Llama-3.1-128k-Dark-Planet-Uncensored-8B-GGUF

Research judgment:

- This is a high-priority co-resident text candidate.
- It should be tested at Q4_K_M or Q5_K_M against the Perchance gold sample.
- It may not beat 12B prose, but it is one of the best bets for a fast always-hot text model.

#### Gemma 4 E4B

Ollama lists Gemma 4 E4B:

- `gemma4:e4b-it-q4_K_M`: 9.6GB, 128K context, text/image input
- `gemma4:e4b-it-q8_0`: 12GB, 128K context, text/image input

Source: https://registry.ollama.com/library/gemma4/tags

Research judgment:

- Gemma 4 E4B is interesting because it is a newer small local model with unusually large context and multimodal-capable packaging.
- Official Gemma 4 is not an uncensored roleplay model.
- It may be useful as a helper model for summarization, image prompt extraction, or state extraction.
- It should get one main-text trial only as a "small model surprise" test, not because it is expected to beat tuned RP models.

### Lane B: Main Quality Text Candidates

This is the likely production tier if co-resident 8B quality is not good enough.

The practical pattern is:

- Use a 12B model for story prose.
- Keep text loaded during normal chat.
- Unload text before full image generation.
- Generate image.
- Unload image and reload/prewarm text.

This matches the clean swap policy already measured locally.

#### Current Baseline: Dolphin-Nemo

`dolphin-nemo` is already installed and should remain the baseline.

Research judgment:

- It is a known uncensored Mistral Nemo 12B derivative.
- It fits the current swap policy.
- It should be compared against newer 12B roleplay/story models, not discarded prematurely.

#### MN-12B-Celeste-V1.9

Celeste V1.9 is a Mistral Nemo 12B story-writing and roleplay model.

Why it matters:

- The model card describes it as trained on Mistral Nemo 12B Instruct at 8K context.
- It uses roleplay and writing datasets including Reddit WritingPrompts, DirtyWritingPrompts, Opus instruct data, and cleaned chat logs.
- The card explicitly mentions improved NSFW, smarter and more active narration.
- It recommends ChatML.
- It has GGUF quantizations.

Source: https://huggingface.co/mav23/MN-12B-Celeste-V1.9-GGUF

Research judgment:

- This is one of the best matches for the target text style.
- It is specifically about story writing and roleplay, not just generic chat.
- It should be first or second in the 12B test queue.

#### Mistral-Nemo-12B-ArliAI-RPMax

ArliAI RPMax is a Mistral Nemo 12B roleplay model focused on creativity and repetition reduction.

Why it matters:

- The model card says RPMax is trained on curated creative-writing and RP datasets.
- It emphasizes variety and deduplication so the model does not latch onto a narrow repeated personality/situation pattern.
- GGUF versions exist.

Source: https://huggingface.co/Triangle104/Mistral-Nemo-12B-ArliAI-RPMax-v1.3-Q4_K_S-GGUF

Research judgment:

- This is a strong 12B candidate for reducing generic/repetitive local prose.
- It should be tested against Celeste and Dolphin-Nemo.
- It may need prompt/template care, because some community reports mention model-format sensitivity with Nemo derivatives.

#### Darkness-Incarnate-12B-Nemo-v3.5

Darkness Incarnate is a 12B Nemo GGUF model explicitly tagged for NSFW, roleplay, unaligned, ERP, and conversational use.

Source: https://huggingface.co/ReadyArt/Darkness-Incarnate-12B-Nemo-v3.5-GGUF

Research judgment:

- It is highly relevant to the unrestricted/adult-capable requirement.
- It is worth testing as an "unfiltered roleplay energy" candidate.
- It may be less controlled than Celeste/RPMax, so the benchmark should judge whether it stays coherent and character-faithful over multiple turns.

#### Writing-Roleplay 20K Context Nemo 12B

There are GGUF releases for `writing-roleplay-20k-context-nemo-12b-v1.0`.

Why it matters:

- It is explicitly positioned as writing/roleplay.
- The 20K-context framing is relevant because this project needs multi-turn continuity, though we should not rely on huge raw context forever.

Sources:

- https://huggingface.co/bartowski/writing-roleplay-20k-context-nemo-12b-v1.0-GGUF
- https://huggingface.co/QuantFactory/writing-roleplay-20k-context-nemo-12b-v1.0-GGUF

Research judgment:

- This is a second-wave 12B candidate after Celeste/RPMax/Darkness.
- It is most interesting if the first three fail to produce enough prose continuity.

#### Mistral-Helcyon-Mercury-12B

Helcyon Mercury is described as a Mistral Nemo 12B GGUF model with companion, roleplay, conversational, unfiltered, and uncensored tags.

Source: https://socket.dev/huggingface/package/xeyonai/mistral-helcyon-mercury-12b-gguf

Research judgment:

- Interesting, but lower priority because the source surfaced through a package mirror rather than a directly inspected Hugging Face card.
- Keep as a later candidate if the main 12B shortlist is weak.

### Lane C: Quality-Ceiling Text Candidates

These models are not first-choice runtime models for a 12GB single-GPU VN app, but they should be tested if the 8B/12B candidates cannot meet the Perchance-quality bar.

#### Gemma 4 26B-A4B

Ollama lists:

- `gemma4:26b-a4b-it-q4_K_M`: 18GB, 256K context, text/image input
- `gemma4:26b-a4b-it-q8_0`: 28GB, 256K context, text/image input

Source: https://registry.ollama.com/library/gemma4/tags

HauhauCS also has an uncensored Gemma4-26B-A4B GGUF release.

Why it matters:

- It is tagged uncensored.
- It is a MoE-style Gemma 4 large candidate.
- The model card provides llama.cpp usage with Q4_K_M.

Source: https://huggingface.co/HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced

Research judgment:

- This is a better large-model quality-ceiling candidate than many 30B+ options because it is smaller than Qwen3.6 35B-A3B at comparable quants.
- It likely cannot co-reside with SDXL on 12GB VRAM.
- It should be tested only after the 12B lane, or if we need a quality ceiling.

#### Qwen3.6 27B and 35B-A3B

Ollama lists:

- `qwen3.6:27b-q4_K_M`: 17GB, 256K context
- `qwen3.6:27b-q8_0`: 30GB, 256K context
- `qwen3.6:35b-a3b-q4_K_M`: 24GB, 256K context
- `qwen3.6:35b-a3b-q8_0`: 39GB, 256K context

Source: https://ollama.com/library/qwen3.6/tags

Research judgment:

- Qwen3.6 is a serious current-generation local model family.
- The 35B-A3B active-parameter advantage helps compute, but total memory footprint is still large.
- Local prior test with Fred IQ4_XS produced about 6.9 tok/s with no image model loaded, which is likely too slow for the normal VN loop.
- Treat Qwen3.6 as a quality ceiling and runtime stress test, not as the next production default.

#### Mistral Small 3.2 24B

Ollama lists:

- `mistral-small3.2:24b-instruct-2506-q4_K_M`: 15GB, 128K context, text/image input
- `mistral-small3.2:24b-instruct-2506-q8_0`: 26GB

Source: https://ollama.com/library/mistral-small3.2/tags

Research judgment:

- Mistral Small 24B is a plausible middle ground between Nemo 12B and huge Qwen/Gemma models.
- It is still too large for comfortable text+image co-residency on 12GB.
- It is worth a quality-ceiling test if 12B Nemo variants are close but not quite good enough.

### Runtime Notes For Text

Ollama remains useful for installed baselines and straightforward GGUF tests.

For larger or format-sensitive models, llama.cpp or KoboldCpp may be worth testing because they expose more direct control over:

- GPU layer/offload behavior
- context/KV cache settings
- chat template handling
- prompt formatting
- server logs

TabbyAPI/EXL2 can be faster when the model fits fully in VRAM, but it is less attractive for this project because CPU offload and one-GPU text/image juggling matter.

### Text Shortlist To Test

Test in this order:

1. Existing `dolphin-nemo` baseline.
2. `MN-12B-Celeste-V1.9-GGUF` Q4_K_M or Q5_K_M.
3. `Mistral-Nemo-12B-ArliAI-RPMax` Q4/Q5.
4. `Darkness-Incarnate-12B-Nemo-v3.5-GGUF` Q4_K_M.
5. `Llama-3.1-128k-Dark-Planet-Uncensored-8B-GGUF` Q4_K_M as co-resident candidate.
6. `Gemma4:e4b-it-q4_K_M` as small-model/helper surprise test.
7. `Gemma4-26B-A4B-Uncensored` as large quality ceiling.
8. `Qwen3.6 35B-A3B` only if runtime experiments improve beyond the previous slow result.

### Text Experiment Needed

Build a text gold-sample harness before downloading too many models.

Inputs:

- Character Profile from Perchance export.
- Protagonist Profile from Perchance export.
- Empty-start scenario and selected continuation turns.
- Several user turns from the gold sample.

Outputs:

- rendered prompt/messages
- full model reply
- first-token latency if streaming
- total generation time
- tokens/sec
- model name, quant, runtime
- manual quality notes

Judging criteria:

- Would the user want to reply?
- Does it feel like story continuation rather than assistant response?
- Does it use character and protagonist profiles?
- Does it balance action, atmosphere, body language, and dialogue?
- Does it avoid generic trait-list behavior?
- Does it maintain continuity over several turns?

### Text Bottom Line

The most likely text answer is still a 12B Nemo roleplay/story model under a stable swap policy.

The best near-term discovery is not "find one giant model." It is:

- prove whether a strong 8B can hit the quality bar for co-residency
- prove whether a better 12B Nemo model beats Dolphin-Nemo
- use Gemma/Qwen/Mistral Small only as quality ceilings

## Part 2: Image Model Landscape

### Executive Image Conclusion

The image side should not be treated as "Diffusers versus A1111" yet. The first question is simpler:

Which local anime/VN image family can produce Perchance-quality-or-better scene panels on a 12GB RTX 3080 in about 30-60 seconds, while leaving the text loop usable?

The current practical answer is:

- Keep Nova Anime XL as the measured baseline, because the clean-swap benchmark already gives about 39-44 seconds per image.
- Test a newer Illustrious/NoobAI/WAI-style SDXL checkpoint next, because the anime ecosystem has moved hard in that direction.
- Test one fast distilled SDXL workflow separately, because few-step generation could be the difference between "cute demo" and "usable VN loop".
- Do not make FLUX the default image path yet. It is interesting, but likely too heavy or too workflow-sensitive for the first stable local VN release on 12GB.

### What We Already Know Locally

The clean-swap real-flow benchmark is the strongest local evidence so far.

Measured with the app-style two-pass image flow:

- image model: `F:\huggingface\models\novaAnimeXL_ilV120.safetensors`
- flow: load image model, generate image, unload image model, then load/run text
- image timing: roughly 39-44 seconds per image
- text timing after image unload:
  - `qwen-uncensored`: about 126-128 tok/s
  - `dolphin-llama3`: about 120-121 tok/s
  - `dolphin-nemo`: about 86-89 tok/s

Research judgment:

- The "one GPU owner at a time" strategy is not just a theory. It already works.
- The production question is not whether SDXL can run. It can.
- The real question is whether a better/newer image checkpoint or faster workflow can beat Nova Anime XL without sacrificing visual quality.

### Image Lane A: Current Baseline

#### Nova Anime XL

Current local baseline:

- `novaAnimeXL_ilV120.safetensors`
- SDXL-family anime checkpoint
- already integrated into the current app pipeline
- already measured in the real app flow

Research judgment:

- Keep it as the control model.
- Do not delete or replace it until a candidate beats it on both visual quality and timing.
- It may still be a good "default art style" even if another model becomes the experimental high-quality option.

### Image Lane B: Current Anime SDXL Ecosystem

The best current image candidates are still SDXL-derived anime checkpoints. This matters because:

- SDXL fits 12GB much better than FLUX-class models.
- The LoRA/control ecosystem is mature.
- Anime/VN character prompting is strongest in SDXL anime lineages.
- Existing app code already works with single-file SDXL checkpoints.

#### Illustrious XL

Illustrious XL is a major open anime/illustration SDXL base.

Relevant facts:

- `OnomaAIResearch/Illustrious-XL-v1.1` is available on Hugging Face.
- The file listing shows a 6.94GB safetensors checkpoint.
- The model card describes v1.1 as a more natural-language-focused refined model with better character understanding than v1.0.

Sources:

- https://huggingface.co/OnomaAIResearch/Illustrious-XL-v1.1
- https://huggingface.co/OnomaAIResearch/Illustrious-XL-v1.1/tree/main

Research judgment:

- Illustrious itself is more of a base/foundation than the first production checkpoint.
- Its value is the ecosystem: WAI, NoobAI, many LoRAs, and newer anime merges.
- It should shape the model search and prompt format tests.

#### WAI Illustrious

WAI-Illustrious is one of the most relevant current anime checkpoint families for this project.

Relevant facts:

- WAI is built on the Illustrious ecosystem.
- Current public listings show fp16 checkpoint size around 6.46GB.
- The model guidance commonly points to anime upscalers and hires settings such as R-ESRGAN 4x+ Anime6B, 20 hires steps, and denoise around 0.35-0.5.
- Community discussion in 2026 still treats WAI-Illustrious as one of the strongest 2D/anime SDXL families.

Sources:

- https://civitai.com/models/827184/wai-nsfw-illustrious-sdxl
- https://illustriousxl.org/wai-illustrious-sdxl

Research judgment:

- This is a high-priority image candidate.
- It is especially relevant because the project needs adult-capable local generation.
- Test it as a direct Nova replacement at the same sizes first, then test its recommended hires settings.

#### NoobAI XL

NoobAI XL is another high-priority current anime checkpoint family.

Relevant facts:

- Laxhar hosts `noobai-XL-1.1` and `noobai-XL-Vpred-1.0` on Hugging Face.
- Both are SDXL-family text-to-image models.
- The repositories are marked Not-For-All-Audiences.
- The NoobAI ecosystem is specifically anime-oriented and widely discussed for character knowledge and prompt adherence.

Sources:

- https://huggingface.co/Laxhar/noobai-XL-1.1
- https://huggingface.co/Laxhar/noobai-XL-Vpred-1.0
- https://huggingface.co/Laxhar/models

Research judgment:

- This is probably the most important non-Nova candidate to test.
- Test `noobai-XL-Vpred-1.0` and/or `noobai-XL-1.1` if disk/time allows.
- Expect prompt-format sensitivity. The benchmark must preserve each model's recommended tag structure instead of forcing one universal prompt style.

#### Animagine XL 4.0

Animagine XL 4.0 is a mature anime SDXL model from Cagliostro Research Lab.

Relevant facts:

- The official Hugging Face card says Animagine XL 4.0 is retrained from SDXL 1.0 on 8.4M anime-style images.
- It recommends tag-structured prompts.
- It recommends around 25-28 steps, CFG 4-7, and anime-style quality/score tags.
- It explicitly supports tags such as `safe`, `sensitive`, `nsfw`, and `explicit`.
- It lists recommended portrait resolutions such as 832x1216, 896x1152, and 768x1344.

Source: https://huggingface.co/cagliostrolab/animagine-xl-4.0

Research judgment:

- Animagine XL 4.0 is a useful comparison point because it is cleaner and more documented than many Civitai merges.
- It may be less flexible than Illustrious/NoobAI for current-character LoRA ecosystems, but it is a strong baseline for stable anime output.
- Test it if WAI/NoobAI are unstable or too prompt-sensitive.

#### Pony Diffusion V6 XL

Pony V6 XL remains relevant, especially for stylized/cartoon/anime-adjacent character art.

Relevant facts:

- Pony Diffusion V6 XL is an SDXL-family finetune.
- The Open Laboratory listing describes a 6.3GB fp16 checkpoint.
- It has a very large ecosystem and many LoRAs.
- There are GGUF/quantized SDXL variants for ComfyUI, including a Pony Diffusion V6 XL GGUF listing that claims much lower UNet VRAM during processing.

Sources:

- https://openlaboratory.com/models/pony-diffusion-v6-xl/
- https://huggingface.co/morikomorizz/Pony-Diffusion-V6-XL-GGUF

Research judgment:

- Pony is worth keeping in the candidate pool, but not first.
- It has its own prompt conventions and can be finicky if treated like normal SDXL.
- A quantized ComfyUI Pony workflow is interesting later if co-residency becomes more important than pure image quality.

### Image Lane C: Few-Step SDXL Acceleration

The current app's two-pass image flow is about 40 seconds. That is acceptable for a local VN, but barely. Few-step SDXL could make the experience feel much more alive if quality stays close enough.

#### SDXL-Lightning

Relevant facts:

- ByteDance open-sourced SDXL-Lightning.
- It provides 1-step, 2-step, 4-step, and 8-step distilled models.
- The Hugging Face card says the 2-step, 4-step, and 8-step models have strong quality, while 1-step is experimental.
- It provides both full UNet and LoRA checkpoints.
- It requires matching inference steps to the checkpoint and uses low/zero CFG settings depending on workflow.

Sources:

- https://huggingface.co/ByteDance/SDXL-Lightning
- https://arxiv.org/abs/2402.13929

Research judgment:

- This is the first acceleration path to test.
- Do not test 1-step first. Test 4-step or 8-step.
- The important experiment is not generic SDXL-Lightning. It is: can Lightning LoRA or a Lightning-style checkpoint work with the anime checkpoint while preserving VN image quality?

#### Hyper-SD

Relevant facts:

- ByteDance also hosts Hyper-SD on Hugging Face.
- It includes fast SDXL text-to-image assets.

Source: https://huggingface.co/ByteDance/Hyper-SD

Research judgment:

- Hyper-SD is a second acceleration path after SDXL-Lightning.
- It belongs in the experiment queue, but not ahead of testing current anime checkpoints.

#### LCM-LoRA

Relevant facts:

- Hugging Face's LCM-LoRA article presents SDXL generation in about 4 steps using an LCM scheduler.
- Diffusers documentation describes LCM as enabling high-quality 768x768 generation in 2-4 steps or even one step.
- The general tradeoff is speed versus fine control and detail.

Sources:

- https://huggingface.co/blog/lcm_lora
- https://huggingface.co/docs/diffusers/v0.23.0/using-diffusers/lcm

Research judgment:

- LCM-LoRA is useful for fast drafts and maybe live previews.
- It is not automatically a production-quality replacement for full SDXL hires.
- It should be tested as "fast preview while final image renders" or "low-latency image mode", not as the only image path.

### Image Lane D: FLUX and Newer Heavy Families

FLUX is important in the broader image space, but it is not the obvious first production path for this project.

Relevant facts:

- FLUX workflows exist in ComfyUI.
- ComfyUI community workflows and GGUF/FP8 variants can make FLUX possible on 12GB cards.
- Community reports repeatedly show that FLUX on 12GB can be workflow-sensitive, low-VRAM-mode-sensitive, and slow when it spills.

Sources:

- https://comfyui-wiki.com/en/tutorial/advanced/image/flux/flux-1-dev-t2i
- https://insiderllm.com/guides/flux-locally-complete-guide/
- https://www.reddit.com/r/comfyui/comments/1qxu1sr/flux1dev_fp8_extremely_slow_on_rtx_3060_20/

Research judgment:

- FLUX should not be ignored, but it is not the next v1 candidate.
- The anime ecosystem is thinner than SDXL/Illustrious/NoobAI for this target.
- Treat FLUX as a later "can we get better hands/composition/text rendering?" investigation, not as the core VN loop.

### Image Experiment Recommendation

The image test queue should be:

1. Baseline repeat: Nova Anime XL, current app settings, same gold prompts.
2. WAI-Illustrious: same prompt translated into its expected tag style.
3. NoobAI XL V-Pred or 1.1: same scene prompts, model-native prompt style.
4. Animagine XL 4.0: documented settings, model-native tags.
5. SDXL-Lightning 4-step or 8-step: first with base SDXL, then with the best anime candidate if feasible.
6. LCM-LoRA: only if Lightning is not good enough or if we want a fast-preview mode.
7. Pony V6 XL: only if WAI/NoobAI/Animagine do not cover a desired style or LoRA ecosystem.
8. FLUX GGUF/FP8: later quality experiment, not the main path.

The benchmark should save:

- final image
- exact positive prompt
- exact negative prompt
- model/checkpoint
- sampler/scheduler
- steps
- CFG
- base resolution
- hires/upscale settings
- seed
- total generation time
- peak VRAM
- whether text model was loaded before/after
- manual quality note

The most important manual question is:

Would this panel make the user want to continue the scene?

If the answer is no, the speed does not matter.

## Part 3: Runtime And Backend Landscape

### Executive Runtime Conclusion

The app should not assume that raw Diffusers is the final image backend.

Raw Diffusers is good for isolated tests because it is transparent and scriptable. But the project goal is a full VN loop with text streaming, image generation, unload/reload behavior, saved artifacts, and repeatable quality. Mature image backends already provide optimized samplers, model switching, unload endpoints, memory settings, and workflow serialization.

The runtime decision should be tested like this:

- Keep Ollama for installed text baselines and simple GGUF testing.
- Test llama.cpp or KoboldCpp only when we need more explicit text offload/template control.
- Test A1111/Forge as the fastest path to "better image backend with API and unload endpoints".
- Test ComfyUI as the most future-proof path, especially after its 2026 Dynamic VRAM work.
- Keep raw Diffusers as the control harness, not necessarily the production image engine.

### Text Runtime Options

#### Ollama

Current status:

- Already integrated.
- Already has installed models.
- Already supports OpenAI-compatible chat and native API calls.
- Already supports model unload via `keep_alive: 0`.
- Already exposes timing fields such as `load_duration`, `prompt_eval_duration`, `eval_count`, and `eval_duration`.

Source: https://docs.ollama.com/api/generate

Research judgment:

- Ollama is still the right default text runtime for the app while we test model quality.
- Its API timing fields are enough for basic tok/s benchmarking.
- Its unload behavior is simple enough for the one-GPU-owner coordinator.
- The weakness is limited visibility/control over exact offload behavior, chat templates, and experimental architectures.

Settings worth preserving:

- `OLLAMA_FLASH_ATTENTION=1`
- `OLLAMA_KV_CACHE_TYPE=q8_0`
- `OLLAMA_NUM_PARALLEL=1`
- `OLLAMA_MAX_LOADED_MODELS=1`
- `OLLAMA_MODELS=F:\ollama\models`

#### llama.cpp Direct

Why it matters:

- It exposes direct control over GPU layers/offload, flash attention, batch size, context, and KV behavior.
- It can run GGUF models without Ollama's model packaging layer.
- It is useful when Ollama hides the thing we need to inspect.

Sources:

- https://www.jan.ai/docs/desktop/local-engine/llama-cpp
- https://en.wikipedia.org/wiki/Llama.cpp

Research judgment:

- llama.cpp should be the text debugging runtime, not necessarily the app default.
- It is especially relevant for Qwen/Gemma/MoE experiments where Ollama may underperform or hide offload details.
- If a model is slow in Ollama but promising in quality, rerun it through llama.cpp before rejecting it.

#### KoboldCpp

Why it matters:

- It is widely used in local roleplay communities.
- It exposes GPU layer offload in a roleplay-oriented interface.
- It can be easier to experiment with story/roleplay sampling than raw llama.cpp.

Source: https://llmhardware.io/guides/koboldcpp-guide

Research judgment:

- KoboldCpp is worth a targeted roleplay-quality comparison if Ollama prompt/template handling seems to be hurting a model.
- It should not be integrated into the app before the model shortlist is clearer.

#### EXL2 / TabbyAPI

Research judgment:

- EXL2 can be very fast when a model fits fully in VRAM.
- It is less attractive for this project because the app needs CPU/GPU split behavior and one-GPU image/text juggling.
- Keep it out of the first experiment wave unless a specific 7B-9B co-resident model looks amazing and fits fully.

### Image Runtime Options

#### Raw Diffusers

Current status:

- Already used by the app.
- Easy to script.
- Easy to keep fully local.
- Produced the existing clean-swap benchmark.

Weaknesses:

- We own all model loading/unloading logic.
- We own all cache path correctness.
- We own sampler/scheduler/hires behavior.
- It can lag behind WebUI/Comfy workflows that the image community actively tunes.
- It made it easy to accidentally touch `C:\Users\...\huggingface` until env vars were set correctly before imports.

Research judgment:

- Keep raw Diffusers as a simple truth harness.
- Do not assume it is the production image backend.
- If A1111/Forge or ComfyUI produces better images faster, use them through an API instead of reimplementing everything.

#### AUTOMATIC1111

Why it matters:

- It has a mature API.
- It can run with `--api`.
- It exposes `/sdapi/v1/txt2img`, `/sdapi/v1/img2img`, `/sdapi/v1/options`, and model management endpoints.
- API docs can be viewed from the running server at `/docs`.
- The API includes unload/reload checkpoint behavior through `/sdapi/v1/unload-checkpoint` and `/sdapi/v1/reload-checkpoint`.

Sources:

- https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/API
- https://deepwiki.com/AUTOMATIC1111/stable-diffusion-webui/8.2-request-and-response-formats/

Research judgment:

- A1111 is a serious candidate because the user already saw better/faster images there.
- It may be the shortest path to production-quality images without rewriting the whole app.
- The unload endpoint maps well to the one-GPU-owner design.
- The downside is that A1111 is less workflow-native than ComfyUI and may be less future-proof for newer model formats.

#### Stable Diffusion WebUI Forge

Why it matters:

- Forge is built around better resource management and faster inference for constrained VRAM.
- Community reports describe major speed and VRAM improvements on lower-VRAM machines.
- It is A1111-like enough that API integration may remain familiar.

Sources:

- https://github.com/lllyasviel/stable-diffusion-webui-forge
- https://www.reddit.com/r/StableDiffusion/comments/1ajxus6/stable_diffusion_webui_forge_for_low_vram_machines_huge_vram_and_speed_improvements/

Research judgment:

- Forge is probably the best A1111-family backend to test first if the goal is speed on 12GB.
- It should be tested with the same checkpoint, same prompt, and same hires settings as the current Diffusers pipeline.
- If Forge reproduces the "A1111 looks better and faster" observation, use Forge as the practical image backend candidate.

#### ComfyUI

Why it matters:

- ComfyUI is workflow-native.
- It is the most flexible backend for SDXL, Flux, quantized diffusion models, LoRAs, ControlNet, upscalers, and multi-stage pipelines.
- It has a queue/API model that can be driven by the app.
- It is likely the most future-proof local image runtime.

The 2026 change that matters:

- ComfyUI introduced Dynamic VRAM, available in stable for Nvidia hardware on Windows and Linux.
- The official ComfyUI blog says Dynamic VRAM changes how model weights are handled, avoids large committed RAM copies, and keeps uncommitted file-backed mappings for model weights.
- The blog also says ComfyUI no longer unloads models from VRAM back to RAM in the old way; instead, model weights are held in a file-backed form and faulted/reused as needed.

Source: https://blog.comfy.org/p/dynamic-vram-in-comfyui-saving-local

Research judgment:

- ComfyUI is the most important runtime to test next.
- Dynamic VRAM may directly address our "why does image loading/unloading feel wasteful?" problem.
- But Dynamic VRAM is not automatically a win. It must be measured locally because some users report workflow-specific slowdowns or different VRAM behavior.
- It may also change the architecture: instead of constantly killing/reloading the image backend, we might keep ComfyUI running and let its memory manager handle inactive workflows.

#### ComfyUI GGUF / Quantized Diffusion

Why it matters:

- GGUF/quantized SDXL and FLUX workflows may reduce image-model VRAM enough to make text/image co-residency more plausible.
- Pony Diffusion V6 XL GGUF listings claim much lower UNet VRAM during processing than the default fp16 checkpoint.

Source: https://huggingface.co/morikomorizz/Pony-Diffusion-V6-XL-GGUF

Research judgment:

- Quantized image models are an important later experiment.
- Do not start there. First test full-quality fp16/bf16 SDXL-family checkpoints in ComfyUI/Forge.
- If speed/VRAM remain bad, test quantized SDXL/Illustrious/Pony variants as a co-residency path.

### Backend Architecture Implications

The app should move toward a runtime coordinator with explicit states:

- `TEXT_HOT`: text model loaded; text can stream immediately.
- `IMAGE_HOT`: image backend/model loaded; image generation is in progress or ready.
- `CLEAN_GPU`: neither large model should be resident.
- `SWAPPING_TO_IMAGE`: unload/prewarm image path.
- `SWAPPING_TO_TEXT`: unload image path and prewarm text.

This matters because most failures came from implicit ownership:

- text model resident while image tries to load
- image model resident while text spills
- Windows shared GPU memory hiding the real problem
- notebook cells holding Python objects longer than expected
- server processes persisting after tests

### Runtime Experiment Recommendation

Run these backend experiments before any app rebuild:

1. Raw Diffusers clean-swap repeat.
   - Same Nova checkpoint.
   - Same current app prompt/settings.
   - Confirms the known baseline still holds.

2. A1111 API clean-swap.
   - Launch with `--api`.
   - Use `/sdapi/v1/txt2img` or `/sdapi/v1/img2img`.
   - Use `/sdapi/v1/unload-checkpoint` after each image.
   - Compare image quality and time against Diffusers.

3. Forge API clean-swap.
   - Same prompt/settings/checkpoint as A1111.
   - Compare speed, VRAM, output quality.
   - If it beats Diffusers clearly, Forge becomes a serious production candidate.

4. ComfyUI Dynamic VRAM workflow.
   - Same checkpoint first.
   - Then WAI/NoobAI if install time allows.
   - Measure first-run load, second-run warm generation, peak VRAM, and text reload time after completion.

5. ComfyUI kept-running experiment.
   - Keep ComfyUI server alive but idle.
   - Run text generation before and after an image.
   - Determine whether ComfyUI's idle memory state blocks text performance.

6. Quantized ComfyUI diffusion experiment.
   - Only after full-quality ComfyUI/Forge tests.
   - Test if quantized SDXL/Pony/Illustrious makes co-residency plausible.

### Runtime Bottom Line

The likely production path is not a total rewrite from scratch.

The likely path is:

- keep the app shell and story/data concepts
- replace fragile hand-rolled image runtime behavior with a proper local image backend API
- keep text on Ollama until a model/runtime test proves another text backend is better
- make the coordinator explicit and measurable

If Forge or ComfyUI can generate images at the same or better quality than Diffusers while handling memory better, the app should call that backend instead of continuing to grow a custom image engine.

## Part 4: Experiment Matrix

### Executive Experiment Conclusion

The next work should not be a new app and should not be another vague benchmark spiral.

The next work should be a gold-sample harness that answers two questions:

1. Which text model produces Perchance-quality-or-better VN prose from the same Character Profile, Protagonist Profile, and user turns?
2. Which image backend/model produces Perchance-quality-or-better panels fast enough for the local VN loop?

Only after those answers should we decide whether to keep, refactor, or rebuild the app shell.

### Gold Sample Inputs

Use the Perchance export as the benchmark seed.

Required inputs:

- Character Profile.
- Protagonist Profile.
- Several representative user turns from the Perchance chat.
- Matching Perchance model outputs as quality references.
- At least one empty-start scene.
- At least one mid-story continuation scene.
- At least one emotionally reactive turn.
- At least one visually rich turn that should trigger an image.

The harness should not judge against one character only forever, but Echidna is a good first gold sample because the user already supplied it as the minimum quality bar.

### Text Experiment Matrix

#### Text Test 1: Current Baseline

Runtime:

- Ollama

Models:

- `dolphin-nemo`
- `dolphin-llama3`
- `qwen-uncensored`

Purpose:

- Establish current local baseline quality.
- Confirm speed and streaming behavior.
- Save prompt, output, timing, and manual notes.

Pass condition:

- At least one baseline feels close enough that the user would want to continue replying.

Fail condition:

- Outputs feel assistant-like, generic, overly short, profile-blind, or weak compared with Perchance.

#### Text Test 2: 12B Nemo Roleplay Shortlist

Runtime:

- Ollama first.
- llama.cpp or KoboldCpp only if Ollama formatting/offload seems suspect.

Models:

- `MN-12B-Celeste-V1.9-GGUF`
- `Mistral-Nemo-12B-ArliAI-RPMax`
- `Darkness-Incarnate-12B-Nemo-v3.5-GGUF`

Purpose:

- Determine whether a better 12B story/RP model beats Dolphin-Nemo.
- Keep the model size practical for the existing clean-swap runtime.

Pass condition:

- Text quality is clearly better than current Dolphin-Nemo and close to or better than the Perchance sample.
- Speed remains usable in the clean-swap loop.

Fail condition:

- No meaningful quality gain versus Dolphin-Nemo.
- Model becomes too repetitive, too explicit without story control, or too prompt-template-sensitive.

#### Text Test 3: Co-Resident 8B Candidate

Runtime:

- Ollama first.

Model:

- `Llama-3.1-128k-Dark-Planet-Uncensored-8B-GGUF`

Purpose:

- See whether a modern uncensored 8B can meet the writing bar while staying fast enough for co-residency experiments.

Pass condition:

- Text is good enough to continue a scene and speed is much faster/easier than 12B.

Fail condition:

- Fast but noticeably worse than Perchance or 12B Nemo candidates.

#### Text Test 4: Large Quality Ceiling

Runtime:

- llama.cpp direct if Ollama is slow or opaque.
- Ollama only if the model is already installed and stable.

Models:

- `Gemma4-26B-A4B-Uncensored`
- Qwen3.6 35B-A3B IQ4_XS, already installed, only if we want a comparison.
- Mistral Small 3.2 24B if a local/uncensored path is practical.

Purpose:

- Determine whether going bigger actually improves story quality enough to justify slow speed.

Pass condition:

- Output is dramatically better than 12B and can stream acceptably.

Fail condition:

- Quality gain is modest or speed is below the user's tolerance.

### Image Experiment Matrix

#### Image Test 1: Current Diffusers Control

Backend:

- raw Diffusers

Model:

- Nova Anime XL

Purpose:

- Reproduce the known 39-44 second clean-swap baseline.
- Save images and prompts for direct comparison.

Pass condition:

- Similar timing and image quality to previous real-flow benchmark.

#### Image Test 2: A1111/Forge Backend With Current Model

Backend:

- Forge first if install/setup is clean.
- A1111 if Forge API/setup blocks.

Model:

- Nova Anime XL

Purpose:

- Answer the user observation: why did A1111 seem faster/better than our pipeline?
- Test whether the backend alone improves quality/speed without changing the model.

Pass condition:

- Same or better image quality than Diffusers.
- Same or faster image generation.
- Clean unload behavior through API.

#### Image Test 3: New Anime Checkpoints

Backend:

- whichever wins Image Test 2.
- ComfyUI if model-specific workflows are easier there.

Models:

- WAI-Illustrious
- NoobAI XL V-Pred or 1.1
- Animagine XL 4.0

Purpose:

- Determine whether the current anime ecosystem beats Nova.

Pass condition:

- One candidate is visibly better than Nova for VN panels at acceptable speed.

Fail condition:

- Better still images but worse character/story panel usefulness.
- Too prompt-sensitive for automated image prompt generation.

#### Image Test 4: Few-Step Acceleration

Backend:

- ComfyUI preferred.

Models/workflows:

- SDXL-Lightning 4-step or 8-step.
- Hyper-SD after Lightning.
- LCM-LoRA only as fast-preview candidate.

Purpose:

- Test whether image generation can move from about 40 seconds to closer to 10-25 seconds without unacceptable quality loss.

Pass condition:

- Images are good enough for the VN loop and substantially faster.

Fail condition:

- Images are fast but look like previews, not final panels.

#### Image Test 5: ComfyUI Dynamic VRAM

Backend:

- ComfyUI current stable.

Models:

- Nova first.
- Then best WAI/NoobAI candidate.

Purpose:

- Determine whether ComfyUI can stay running without blocking text performance.
- Determine whether Dynamic VRAM changes the load/unload architecture.

Pass condition:

- ComfyUI idle does not meaningfully hurt text tok/s.
- Image generation remains stable.
- VRAM behavior is predictable enough for the coordinator.

Fail condition:

- Dynamic VRAM causes inconsistent timing, shared-memory spill, or unpredictable text slowdowns.

### Full VN Loop Experiment

Once the individual text/image tests have one leading candidate each, run the full loop:

1. Load text.
2. Stream text reply from a gold user turn.
3. Extract or generate image prompt from the text.
4. Unload/prep text as required.
5. Generate image.
6. Save image and metadata.
7. Return to text-hot state.
8. Repeat for three consecutive turns.

The full loop should save:

- `turn_001_user.txt`
- `turn_001_prompt.json`
- `turn_001_reply.txt`
- `turn_001_image_prompt.txt`
- `turn_001_image.png`
- `turn_001_metrics.json`

Metrics:

- first-token latency
- full text time
- output tokens/sec
- image generation time
- text reload/prewarm time
- peak dedicated VRAM
- peak shared GPU memory
- total turn wall time

Manual quality notes:

- text: better/same/worse than Perchance
- image: better/same/worse than Perchance
- continuity: good/weak/broken
- user-desire score: would I keep chatting? yes/no

### Decision Gate

After the experiments, decide architecture using evidence:

- If current app plus better prompts/models works: refactor the existing app.
- If image backend is the bottleneck: keep app shell, replace image runtime with Forge or ComfyUI API.
- If text prompting/data model is the bottleneck: keep runtime, rebuild story/profile/message orchestration.
- If both are broken: start a new repo, but only after preserving working benchmark scripts and model/runtime findings.

### Immediate Next Implementation Step

Build the gold-sample harness, not the UI.

The harness should:

- read a Perchance-style JSON export
- extract Character Profile, Protagonist Profile, and selected turns
- run selected text models
- optionally run selected image backends
- save all outputs and metrics under `outputs/research_runs/<timestamp>/`

This gives us a clean research loop:

- add candidate
- run harness
- inspect output
- keep/drop candidate

That is how we stop spiraling.
