# Local VN Small-Model Adversarial Pass

Status: first pass complete
Date: May 23, 2026

Question:

Are we anchoring too hard on 12B text models? Can smaller models hit or exceed the target VN/roleplay quality if they are better tuned, faster, or easier to keep resident alongside image generation?

Short answer:

Yes, there is a real 12B anchoring risk. Smaller models cannot be dismissed.

The better conclusion is:

- 12B is a practical quality tier, not a proven winner.
- 8B/9B roleplay-specialized models may beat generic or weakly tuned 12B models for this project.
- 4B/E4B models are probably not first-choice main narrators, but they are too interesting to ignore because they could enable a much faster architecture.
- The next harness must explicitly test small specialized models against 12B models using the same Perchance gold sample.

## Why The 12B Bias Happened

The first-pass conclusion kept circling 12B for understandable but incomplete reasons:

- `dolphin-nemo` is already installed and works.
- 12B is about the largest normal dense tier that can run reasonably on RTX 3080 12GB under a clean-swap policy.
- Mistral Nemo has a large roleplay/story ecosystem.
- 20B+ models are clearly difficult when image generation is also required.

But those are runtime-fit arguments, not quality proof.

The quality risk is:

- A tuned 8B with the right roleplay data can beat a mediocre 12B.
- A smaller model can stay hot, stream sooner, and leave more GPU room for image/runtime overhead.
- A faster model can afford retries, rerolls, or two-stage prompting.
- A model trained specifically to avoid assistant-like responses may outperform a larger model that keeps falling into assistant prose.

## What Smaller Models Need To Prove

For this project, a smaller model does not need to win abstract benchmarks.

It needs to prove:

- It writes like an interactive-fiction continuation, not an assistant.
- It uses both Character Profile and Protagonist Profile.
- It balances dialogue, action, body language, and scene movement.
- It can handle unrestricted/adult-capable roleplay without collapsing into crude repetition.
- It maintains continuity over several turns.
- It streams fast enough that the VN loop feels alive.
- It can coexist with, or quickly return after, image generation.

## Strong 8B Candidates

### Dolphin X1 8B

Dolphin X1 8B is a recent direct uncensoring/fine-tune of Llama 3.1 8B.

Relevant facts:

- Model card describes it as an effort to directly uncensor Llama 3.1 8B Instruct while preserving or improving abilities.
- The model card says the system prompt is used to set tone, character, mood, and behavior rules.
- GGUF quants are available.
- Listed GGUF sizes include Q4_K_M around 4.92GB, Q5_K_M around 5.73GB, Q6_K around 6.6GB, and Q8_0 around 8.54GB.
- It reports a 95.96% pass rate on a Dolphin refusal benchmark.

Source: https://huggingface.co/dphn/Dolphin-X1-8B-GGUF

Why it matters:

- This may be a better version of our existing 8B Dolphin lane.
- It is not a specialized romance/RP model, but it is current, uncensored, and system-prompt controllable.
- It should be tested before assuming 12B is necessary.

Priority: high.

Recommended quant:

- Q5_K_M first.
- Q6_K if Q5 quality is close but slightly thin.

### Llama 3.1 8B Stheno v3.4

Stheno remains one of the most relevant 8B roleplay lineages.

Relevant facts:

- Search results for Stheno v3.4 GGUF note 55% more roleplaying examples based on Gryphe's Sonnet3.5 Charcard roleplay sets.
- It is explicitly positioned around roleplay/creative writing.
- Community listings describe Stheno as improving roleplay awareness and nuanced dialogue compared with base Llama 3.1 8B.

Sources:

- https://huggingface.co/DarqueDante/Llama-3.1-8B-Stheno-v3.4-Q5_K_M-GGUF
- https://openrouter.ai/sao10k/l3-stheno-8b/api?tab=parameters

Why it matters:

- This is directly aimed at character-card roleplay, which is extremely close to our input shape.
- The Perchance export is basically a character/protagonist/profile-driven roleplay benchmark.
- It may beat larger generic models on format and character behavior.

Priority: high.

Recommended quant:

- Q5_K_M or Q6_K.

### Lumimaid v0.2 8B

Lumimaid v0.2 8B is a roleplay/conversational 8B model from NeverSleep.

Relevant facts:

- Hugging Face marks it Not-For-All-Audiences, NSFW, and conversational.
- GGUF is available.
- The model can be run via llama.cpp, LM Studio, Jan, Docker, and Ollama.
- Lewdiculous imatrix quants describe it with roleplay and SillyTavern presets, and recommend lower temperatures.

Sources:

- https://huggingface.co/NeverSleep/Lumimaid-v0.2-8B-GGUF
- https://huggingface.co/Lewdiculous/Lumimaid-v0.2-8B-GGUF-IQ-Imatrix

Why it matters:

- This is one of the clearest small-model candidates for unrestricted roleplay energy.
- It may be less generally intelligent than Dolphin X1, but more tuned toward the target vibe.
- It should be judged on actual Perchance-style output, not benchmark assumptions.

Priority: high.

Recommended quant:

- Q5_K_M or imatrix Q5/Q6 if available.

### Roleplay-Hermes-3 Llama 3.1 8B

Roleplay-Hermes-3 Llama 3.1 8B is especially relevant because it targets "assistant slop" directly.

Relevant facts:

- The GGUF card describes it as DPO-tuned Hermes 3 Llama 3.1 8B.
- It is tuned to behave more "humanish" and avoid AI-assistant-like or overly neutral responses.
- It includes RP-format steering through datasets such as NSFW_RP_Format_DPO.
- The card says it works best if the first message naturally uses the desired RP format.

Source: https://huggingface.co/Triangle104/Roleplay-Hermes-3-Llama-3.1-8B-Q4_K_M-GGUF

Why it matters:

- The user specifically dislikes assistant-ish output.
- This model's training goal maps directly to our biggest text-style failure mode.
- Even if prose is not as rich as 12B, it may produce the right interaction feel.

Priority: high.

Recommended quant:

- Q4_K_M is available, but look for Q5/Q6 or imatrix if possible.

### Dark Planet / RP-Hero 8B Family

DavidAU's Dark Planet and RP-Hero style 8B models remain relevant.

Relevant facts:

- `Llama-3.1-128k-Dark-Planet-Uncensored-8B-GGUF` is GGUF and explicitly uncensored.
- Search results and model metadata place related DavidAU 8B models in roleplay/creative-writing territory.

Source: https://huggingface.co/DavidAU/Llama-3.1-128k-Dark-Planet-Uncensored-8B-GGUF

Why it matters:

- This line is built for uncensored creative writing/RP behavior.
- It is a good "weird but maybe alive" test candidate.
- It should not be over-prioritized over Dolphin X1, Stheno, Lumimaid, or Roleplay-Hermes, but it belongs in the queue.

Priority: medium-high.

## Strong 9B Candidates

### Peach 2.0 9B 8K Roleplay

Peach 2.0 9B is a dedicated compact roleplay model.

Relevant facts:

- It is based on Yi-1.5-9B.
- QuantFactory's GGUF card describes Peach-9B as fine-tuned on more than 100K roleplay conversations from a synthetic-data approach.
- Peach 2.0 is described as a compact roleplay-focused language model from ClosedCharacter.
- Research and benchmark pages mention Peach in the context of role-playing models and role-aware evaluation.

Sources:

- https://huggingface.co/QuantFactory/Peach-9B-8k-Roleplay-GGUF
- https://huggingface.co/mradermacher/Peach-2.0-9B-8k-Roleplay-GGUF
- https://www.promptlayer.com/models/peach-20-9b-8k-roleplay

Why it matters:

- This is one of the best "smaller than 12B but explicitly roleplay-first" candidates.
- It may be the strongest anti-12B-bias test.
- The 8K context limit may be acceptable if we use summaries/pinned memory instead of huge raw context.

Priority: very high.

Recommended quant:

- Q5_K_M or Q6_K if available.

### Qwen3.5 9B Uncensored / Abliterated Variants

Qwen3.5 9B is a new-ish 9B family with many uncensored/abliterated variants.

Relevant facts:

- Hugging Face search shows many Qwen3.5-9B GGUF variants with very high download counts.
- Uncensored/abliterated variants include Huihui, LuffyTheFox, HauhauCS, DavidAU, and null-space lines.
- Search snippets list Q4_K_M around 5.3-6.1GB for some Qwen3.5 9B uncensored/abliterated variants, and Q8_0 around 8.9GB for HauhauCS 9B.
- Some community discussion flags Qwen 9B as promising for roleplay/prompt crafting but potentially prone to thinking loops or creativity issues depending on variant.

Sources:

- https://huggingface.co/models?search=Qwen+3.5+9B+GGUF&sort=downloads
- https://huggingface.co/tutuchen2000/Qwen3.5-9B-abliterated-GGUF
- https://huggingface.co/mradermacher/Qwen3.5-9B-Uncensored-cyber-v3-GGUF
- https://huggingface.co/mradermacher/qwen3.5-9b-null-space-abliterated-i1-GGUF/tree/main

Why it matters:

- This is the most important "newer small model family" to test.
- It may bring better base intelligence than old Llama 3.1 8B roleplay models.
- But it may need thinking disabled and careful template handling.

Priority: high, but choose one specific variant carefully.

Recommended first variant:

- A Qwen3.5-9B uncensored/abliterated Q5/Q6 if available.
- Avoid reasoning-heavy/distilled variants as the first VN prose test unless they can cleanly disable thinking.

## 4B / E4B Candidates

### Gemma 4 E4B

Gemma 4 E4B is not likely to be the final main storyteller, but it is too important to ignore.

Relevant facts:

- Ollama lists `gemma4:e4b-it-q4_K_M` at 9.6GB with 128K context and text/image input.
- Uncensored Gemma 4 E4B variants exist from HauhauCS/tripolskypetr-style releases.
- Search results list multiple Gemma 4 E4B quants including Q8_K_P, Q6_K_P, Q5_K_M, Q4_K_M, IQ4_XS, and lower quants.
- Community reports are mixed for RP coherence, which makes it a test candidate rather than an assumption.

Sources:

- https://ollama.com/library/gemma4/tags
- https://huggingface.co/tripolskypetr/Gemma-4-Uncensored-Aggressive-GGUF
- https://www.reddit.com/r/SillyTavernAI/comments/1sxjjrg/gemma_4_e4b_seems_a_bit_incoherent_for_rp_am_i/

Why it matters:

- It could enable a very fast, very low-overhead architecture.
- It may be useful as a helper model even if it fails as main narrator.
- Its text/image capability may become useful for image-prompt extraction or image-review features later.

Priority: medium.

Recommended test:

- One main-narrator trial only.
- If it fails, try it as helper for summarization/image prompt extraction, not as story engine.

### Gemma 3 4B RP/Uncensored Variants

Relevant facts:

- Search results show Gemma 3 4B uncensored and RP-writer GGUF variants.
- Tags include roleplaying, fiction writing, storytelling, and uncensored use cases.
- A `gemma-3-4b-null-space-abliterated-RP-writer-GGUF` exists.

Sources:

- https://huggingface.co/mradermacher/Gemma-3-4b-it-Uncensored-DBL-X-i1-GGUF
- https://huggingface.co/jwest33/gemma-3-4b-null-space-abliterated-RP-writer-GGUF/tree/main

Why it matters:

- This is the "can a tiny tuned model surprise us?" lane.
- It is unlikely to beat 8B/9B on rich VN prose, but it is cheap enough to test.

Priority: low-medium.

## Why Smaller Models Might Win In The Actual App

Smaller models could win even if their raw prose is slightly weaker because the full VN loop is more than one generation.

Advantages:

- Faster first-token latency.
- More likely to remain fully in VRAM.
- More room for image backend overhead.
- Lower risk of Windows shared GPU memory spill.
- Cheaper retries/regenerations.
- Faster prompt iteration during development.
- Possible co-residency with ComfyUI/Forge idle state.
- Practical room for two-model architecture, e.g. main storyteller plus prompt extractor.

This matters because a slightly weaker but always-responsive model may feel better than a richer model that causes the app to stall.

## Why Smaller Models Might Lose

Risks:

- Shallow emotional continuity over many turns.
- More repetition.
- More likely to ignore subtle details from both profiles.
- More likely to overfit to common RP tropes.
- More likely to lose scene geography and protagonist agency.
- 4B/E4B may be fast but too thin for the target "Perchance-or-better" prose bar.

This means smaller models should be tested hard, not assumed good.

## Revised Text Test Order

The earlier text shortlist should be changed.

New adversarial order:

1. Current `dolphin-nemo` baseline.
2. `Dolphin-X1-8B-GGUF` Q5_K_M.
3. `Peach-2.0-9B-8k-Roleplay-GGUF` Q5/Q6.
4. `Lumimaid-v0.2-8B-GGUF` Q5/Q6 or imatrix.
5. `Llama-3.1-8B-Stheno-v3.4` Q5/Q6.
6. `Roleplay-Hermes-3-Llama-3.1-8B` Q4/Q5.
7. One selected Qwen3.5-9B uncensored/abliterated variant.
8. `MN-12B-Celeste-V1.9-GGUF`.
9. `Mistral-Nemo-12B-ArliAI-RPMax`.
10. `Darkness-Incarnate-12B-Nemo-v3.5-GGUF`.
11. Gemma 4 E4B uncensored as a small-model surprise/helper test.
12. Large quality ceiling only after the above.

This order intentionally tries to disprove the 12B assumption before spending more time on larger models.

## What Would Change The Architecture

If an 8B/9B model reaches 85-95% of the best 12B quality while being much faster:

- Use the smaller model as the production text engine.
- Keep it hot whenever possible.
- Use better image backend work to solve visual quality.
- Consider a helper model only if needed.

If 8B/9B output is alive but slightly weak:

- Use the smaller model for draft/fast mode.
- Keep 12B as high-quality mode.
- Or use smaller model for image-prompt extraction/summarization.

If 8B/9B fails clearly:

- Return to 12B Nemo roleplay models without guilt.
- The test will have earned the conclusion instead of assuming it.

## Bottom Line

The smaller-model path is real.

The project should not say "12B is the answer" until Dolphin X1 8B, Peach 9B, Lumimaid 8B, Stheno 8B, Roleplay-Hermes 8B, and one Qwen3.5 9B uncensored candidate are tested against the same Perchance gold sample.

If one of those hits the quality bar, it may be a better production choice than 12B because it improves the entire text-image loop, not just isolated prose quality.
