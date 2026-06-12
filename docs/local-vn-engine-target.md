# Local VN Engine Target

Status: working target spec
Created: May 23, 2026

## Purpose

This project is a local-first illustrated visual novel engine powered by local text and image models.

The product is not "a chatbot with pictures" and not "an image generator with a chat box". The intended loop is closer to an interactive storybook or choose-your-own visual novel:

1. The user provides or selects a character profile.
2. The user provides or selects a protagonist profile.
3. The story may begin empty or from an opening scene.
4. The user sends a message, action, or mixed dialogue/action turn.
5. The system streams a high-quality story reply in character.
6. The system generates an image panel that matches the reply and current scene.
7. The user continues the story.

The architecture is open. The only thing that matters is whether the local system can reliably produce the target experience.

## Non-Negotiables

- Fully local and offline at runtime.
- Zero recurring cloud/API cost.
- Adult/unrestricted roleplay capability from local models.
- Text and images are both core product features.
- The app must support long-running multi-turn stories, not just single-shot demos.
- The system must preserve character voice, protagonist context, relationship state, and visual identity across turns.
- Output quality must match or beat the Perchance gold sample supplied by the user.

## Hardware Constraint

Current target hardware:

- GPU: NVIDIA RTX 3080 12GB
- Storage: model caches and app data must stay on `F:`
- Cloud fallback: not part of the core design

The system may use CPU RAM for overflow if the speed hit is acceptable, but the target design should avoid workflows that collapse into multi-minute stalls.

## Latency Targets

Text:

- First streamed text should begin within roughly 10 seconds.
- A normal reply should complete in roughly 60 seconds or less.
- Longer replies are acceptable only if streaming starts quickly and the delay feels intentional rather than stuck.

Image:

- Image generation begins after enough scene information exists.
- A normal image panel should complete in roughly 30 seconds when possible.
- A 30-60 second image panel is acceptable if quality is meaningfully better.

Turn:

- The ideal full turn is text streaming first, then image appearing shortly after the reply finishes.
- The user should not stare at a blank app while both models silently load.

## Quality Target

The Perchance export `Devouring_Devotion_-_Echidna.json` is the current gold sample for minimum text quality.

The target is not to copy its architecture or hidden prompt. The target is to match or beat its observed input/output behavior:

- Short user turns can produce rich, emotionally textured replies.
- The model writes character action in third person while the character speaks in first person dialogue.
- The user/protagonist can speak in first person and optionally describe actions or thoughts.
- Replies feel like story continuation, not assistant answers.
- The character profile and protagonist profile both matter.
- The model can maintain scene mood, physical placement, relationship tension, and implied continuity.
- The system can produce image prompts from the story state without degrading the prose.

## Input Contract

The app should eventually treat these as first-class inputs:

- Character Profile: identity, appearance, personality, voice, behavior rules, example dialogue, visual anchors.
- Protagonist Profile: who the user is in the story, social role, personality, relationship framing, persistent traits.
- Story State: current location, mood, relationship state, recent events, unresolved hooks.
- Recent Turns: exact conversation/story text from the active scene.
- Long Memory: summarized or retrieved prior story facts.
- Visual Memory: stable appearance anchors for recurring characters and locations.

These inputs do not have to mirror Perchance names. Internally, clearer names are preferred over "dossier".

## Output Contract

Each AI turn should produce:

- Story Text: the visible narrative/dialogue reply.
- Image Intent: a structured or tagged description of the image panel to generate.
- Optional State Updates: scene facts, relationship changes, memories, or continuity notes.

The visible text does not have to expose image tags if a better internal architecture exists. Perchance uses visible `<image>` tags, but our app can route image intent invisibly if that improves UX and reliability.

## Architecture Freedom

The text and image pipeline can be any of the following if it meets the target:

- One strong text model writes both prose and image prompt.
- One strong text model writes prose, and a smaller helper model extracts image prompt/state.
- A rules/template layer composes image prompts from structured scene data.
- Text and image models swap GPU ownership.
- Text remains loaded while image generation uses CPU/RAM spill if speed stays acceptable.
- Image model is unloaded after each panel if that produces stable total latency.
- A1111, Forge, ComfyUI, Diffusers, or a custom pipeline can be used if the measured flow works.

No implementation gets special status because we already built it. Existing code is reusable only if it helps reach the target faster.

## Evaluation Standard

Future tests should save artifacts, not just print numbers:

- prompt/profile inputs
- generated story text
- generated image prompt or image intent
- generated image files
- text first-token latency when available
- text total latency and tokens/second
- image load time
- image generation time
- GPU VRAM before and after each stage
- whether models were loaded, unloaded, or co-resident

The benchmark that matters is the real turn loop:

1. load or warm the chosen text setup
2. generate reply
3. generate matching image
4. continue the story
5. generate another reply
6. generate another image

Single-model microbenchmarks are useful only as supporting evidence.

## Current Working Hypotheses

- The most stable one-GPU strategy is likely one GPU owner at a time: text for chat, unload text before image, generate image, unload image, reload or prewarm text.
- Co-residency may be possible with smaller text/image models, but it must be proven with real image generation, not just idle model loading.
- Text quality is not solved until local outputs match the Perchance gold sample over multiple turns.
- Image quality is not solved until generated panels are manually reviewed against the intended VN style and character identity.
- The current repo should be treated as a lab until the stack is selected. A clean product repo can come later.

## Research Questions

- Which local text models in 2026 can produce the required story quality on or near this hardware?
- Which of those models have uncensored or abliterated GGUF/Ollama-compatible variants?
- Does a larger MoE model split across VRAM/RAM produce better quality at acceptable latency, or does it lose to smaller fully-resident models?
- Which image backend gives the best quality/speed/reload behavior on a 12GB RTX 3080?
- Can a smaller or faster anime image model meet the visual bar, or is SDXL quality required?
- Is the best product loop text-first then image, or can image intent be extracted early enough to overlap work?

