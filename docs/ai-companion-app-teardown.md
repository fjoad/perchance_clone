# Public Teardown of AI Companion App Engineering

Research date: April 1, 2026

Primary reference: Candy.ai
Secondary reference: Perchance
Comparables: Kindroid, Nomi, Replika, Character.AI

## Summary

This report is a public-source teardown of how modern AI companion apps appear to be engineered.

It is deliberately split into:

- `documented`: stated directly in official docs, help centers, blogs, policies, APIs, or app listings
- `strong inference`: not directly stated, but strongly implied by official behavior, product affordances, and comparable products
- `weak inference`: plausible, but not strongly evidenced by public materials

Important limitation:

- `[documented]` None of these companies publish a full internal architecture spec.
- `[strong inference]` This report is therefore a build-oriented public reconstruction, not a claim of private internal access.

## Executive Take

- `[documented]` The best-known companion apps are not exposing one giant "secret prompt". They expose a combination of persona setup, memory controls, image tools, and media features.
- `[documented]` The clearest public pattern is a layered system: persistent character metadata, recent chat context, medium/long-term memory, and a separate image-generation path.
- `[strong inference]` The strongest products do not rely on chat text alone to make images match the character. They almost certainly combine chat-derived scene prompts with a persistent identity anchor.
- `[strong inference]` In 2025-2026, the dominant production pattern is vendor-orchestrated multimodal infrastructure, not one monolithic in-house model doing everything.
- `[strong inference]` For a local-first MVP, the closest practical architecture is: roleplay LLM + structured character/memory layer + image prompt composer + reference-image/adapter-based identity conditioning. A per-character LoRA is usually overkill for v1.

## 1. Market Map

### Product Clusters

#### Companion-first

- Candy.ai
- Kindroid
- Nomi
- Replika

These products center the ongoing relationship with one or more persistent companions. Their core product is continuity: memory, emotional tone, persona tuning, and recurring visual identity.

#### Character/roleplay-first

- Character.AI
- Perchance

These products center more on open-ended characters, scenarios, and tooling. They can overlap with companions, but the public product shape is broader and less tightly optimized around one persistent romantic companion loop.

### Public Surface Comparison

| Product | Cluster | Persona creation | Memory controls | Image generation | Voice / video | Custom avatar / reference image | API / automation | Moderation model |
|---|---|---|---|---|---|---|---|---|
| Candy.ai | Companion-first | Yes | Yes | Yes | Yes | Yes | No public API found | Adult product with moderation providers |
| Kindroid | Companion-first | Yes | Yes, extensive | Yes | Yes | Yes | Yes | Web/app moderation split; more permissive on web |
| Nomi | Companion-first | Yes | Yes, extensive | Yes | Yes | Yes | Yes | Standard app-platform constraints; details less explicit |
| Replika | Companion-first | Yes | Yes, user-visible | Selfies only | Yes | Avatar-first | No public general API found | More tightly constrained consumer app |
| Character.AI | Roleplay-first | Yes | Yes | Yes | Yes | Character-specific, but less avatar-first | No public consumer API | More safety-constrained mainstream platform |
| Perchance | Roleplay-first | Yes | Limited publicly documented companion memory controls | Yes | Some AI chat variants; less clear for voice | Limited public evidence | Generator/plugin oriented, not a stable companion API | Public web platform with less visible companion-specific policy surface |

## 2. Per-App Technical Teardown

## Candy.ai

Candy.ai is the main reference, but it is also one of the most opaque products technically. The official sources reveal a lot about product behavior and very little about the exact internal model stack.

### Documented Public Facts

- `[documented]` Paid users get unlimited chat and monthly tokens for image generation, video generation, creating custom AIs, and other premium features.
- `[documented]` Candy markets "advanced personality modeling and memory retention" and says the companion learns what the user likes and adapts tone and style over time.
- `[documented]` Candy offers chat, images, voice, and video as part of the product surface.
- `[documented]` Candy exposes custom AI creation rather than only fixed house characters.
- `[documented]` Candy's privacy policy states that it uses third-party service providers including hosting providers, moderation providers, and "third-party LLM providers and/or hosters", and explicitly notes those parties may receive chatbot message content.
- `[documented]` Candy's web help center and token system imply that media generation is asynchronous, metered, and operationally distinct from plain text chat.

### What This Strongly Implies

- `[strong inference]` Candy is very likely not running one single proprietary end-to-end stack for all chat behavior. The privacy policy strongly suggests an orchestration layer over third-party LLMs and hosting.
- `[strong inference]` The chat system is almost certainly assembled from: character definition, relationship framing, recent history, user metadata, memory store, policy layer, and model selection/routing.
- `[strong inference]` Because Candy sells "custom AIs" and persistent companions, it almost certainly stores a per-character record with at least: name, appearance traits, personality/backstory, relationship state, and memory metadata.
- `[strong inference]` Because media is token-gated while chat is comparatively cheap/unlimited, Candy likely treats images/video as separate queued jobs with a different GPU path and possibly different providers.

### Likely Chat Stack

- `[documented]` Personality modeling and memory retention are core product claims.
- `[strong inference]` The companion response path likely looks like:
  1. load character card
  2. load user profile / relationship context
  3. load recent chat turns
  4. retrieve pinned or summarized memories
  5. apply hidden prompt/policy templates
  6. call one or more third-party LLM endpoints
  7. post-process for safety, formatting, or upsell/media hooks

### Likely Memory Model

- `[documented]` Candy publicly claims memory retention.
- `[strong inference]` A modern companion app with paid persistent companions is unlikely to rely on the raw context window alone. It likely uses at least:
  - short-term chat context
  - pinned user/character facts
  - rolling summaries or extracted memory items
  - per-character persistent storage
- `[weak inference]` Candy may use a hidden "memory slots" or profile-fact system similar to other apps, but the exact UI/public docs are less explicit than Kindroid or Nomi.

### Likely Prompt / Orchestration Model

- `[strong inference]` Candy likely maintains a hidden system-layer prompt with:
  - character persona
  - relationship framing
  - style / tone instructions
  - safety and policy rules
  - memory insertions
  - product experiments / ranking instructions
- `[strong inference]` It likely also has modality-specific prompt composers, because text chat, images, and video do not behave like one shared prompt surface in the product.

### Likely Image Generation Workflow

- `[documented]` Images and videos are premium token-consuming features.
- `[documented]` Candy exposes custom companions and visual media generation in the same product.
- `[strong inference]` Candy likely does not generate images from user chat text alone. The more likely path is:
  1. persistent character appearance record
  2. current scene or requested pose/action
  3. hidden prompt composer
  4. image model invocation
  5. optional face or identity preservation pass
- `[strong inference]` Video is likely generated from an image or short identity-conditioned visual seed rather than from long-form text-to-video only. That is the most common production pattern because it is cheaper and more identity-stable.

### Identity Consistency Strategy

- `[strong inference]` Candy almost certainly uses something stronger than prompt-only identity control.
- `[strong inference]` The most likely options are:
  - structured appearance sheet plus hidden prompt templates
  - reference-image conditioning
  - adapter-based identity preservation
  - curated house-character fine-tunes for some official characters
- `[weak inference]` A dedicated LoRA per user-created character is possible but unlikely at scale because it is expensive operationally, increases latency, and creates storage/training complexity. A reference-image or adapter path is more plausible.

### Voice / Video Pipeline Hints

- `[documented]` Voice and video are first-class product features, not one-off experiments.
- `[strong inference]` Voice is likely standard TTS plus optional speech-to-text for user audio, with the companion state shared back into the chat/memory layer.
- `[strong inference]` Short videos are likely image-to-video or identity-conditioned motion generation, not an entirely separate long-context character simulation engine.

### Likely Infrastructure Pattern

- `[documented]` Candy discloses third-party LLM providers/hosters and moderation providers.
- `[strong inference]` This points to a cloud orchestration stack with:
  - web/mobile frontend
  - companion metadata service
  - memory store
  - text-generation router
  - media-generation queue
  - moderation/abuse pipeline
  - billing/token service

### Direct Answer: How likely does Candy make images match the text?

- `[strong inference]` Not by raw text alone.
- `[strong inference]` Most likely by mixing:
  - persistent character appearance data
  - current scene description
  - hidden prompt enhancement
  - identity-preserving visual conditioning

That is the closest public reconstruction of the Candy.ai stack.

## Perchance

Perchance is useful as a reference for accessible public AI generators, but it is much less revealing as a "companion app architecture" source than Candy, Kindroid, or Nomi.

### Documented Public Facts

- `[documented]` Perchance exposes public generators including AI Character Chat, AI Group Chat, AI Image Generator, AI Story tools, and related generator pages.
- `[documented]` Public Perchance generator pages market themselves as free, browser-based generators with no-friction access.
- `[documented]` Perchance's public surface looks generator-centric: separate tools for image generation, character chat, group chat, story generation, and related functions.

### What This Strongly Implies

- `[strong inference]` Perchance appears to be a lightweight orchestration layer over AI text/image services rather than a deep, identity-rich companion stack.
- `[strong inference]` The product shape suggests separate tools with lighter shared state, not the heavy persistent memory and identity architecture seen in dedicated companion products.
- `[weak inference]` Perchance may rely more heavily on prompt engineering and tool wrappers than on deep per-character memory or per-character image identity infrastructure.

### Likely Chat Stack

- `[strong inference]` Likely a simpler chat orchestration path than Candy/Kindroid/Nomi.
- `[weak inference]` There is little public evidence of a sophisticated long-term memory model for Perchance characters.

### Likely Image Workflow

- `[documented]` Perchance exposes dedicated AI image generator tools.
- `[strong inference]` The image path appears more direct-prompt oriented and less companion-specific than Candy.ai.
- `[weak inference]` Character-image consistency is probably weaker and more prompt-driven than identity-conditioned.

### Why Perchance Still Matters

- `[strong inference]` Perchance is useful as a reminder that low-friction creation matters.
- `[strong inference]` Its architecture appears closer to "good wrappers over AI services" than "deep relationship simulator", which is valuable as a contrast against Candy.ai.

## Kindroid

Kindroid is one of the most useful public sources because it is unusually explicit about memory structure, image behavior, and companion customization.

### Documented Public Facts

- `[documented]` Kindroid documents three memory types: persistent, cascaded, and retrievable.
- `[documented]` Kindroid says these memories are split across multiple systems including backstory, key memories, example messages, directives, group context, chat history, and journal entries.
- `[documented]` Kindroid describes cascaded memory as a proprietary medium-term memory system that expands effective conversation history to hundreds or thousands of messages.
- `[documented]` Kindroid documents retrievable memory through long-term memory recall and journal entries.
- `[documented]` Kindroid exposes API endpoints for sending messages and performing a chat break.
- `[documented]` Kindroid's selfie system explicitly says the image engine does not know character names or conversation context by default.
- `[documented]` Kindroid provides an "enhance prompt" feature for selfies.
- `[documented]` Auto-selfies derive prompts from conversation context.
- `[documented]` Custom avatars are used for selfies, and users can write an avatar description that the selfies engine uses.
- `[documented]` Kindroid offers "avatar boost", which trains an adapter from at least four images to improve consistency and likeness.
- `[documented]` Video selfies use a first-frame image and optional motion prompt, and aim to preserve identity/faces.
- `[documented]` The web version is more permissive than the app version for NSFW selfie prompting due to app-store rules.

### What This Means

- `[documented]` Kindroid is not hiding the key architectural point: chat memory and image identity are separate systems.
- `[strong inference]` Kindroid is one of the clearest examples of a modern companion stack:
  - structured persona fields
  - layered memory
  - image-specific prompt composition
  - reference/avatar conditioning
  - optional conversation-to-image prompt conversion
- `[strong inference]` This is very likely close to the industry best practice for high-consistency companion products.

### Chat Stack

- `[documented]` Kindroid exposes persistent persona inputs such as backstory, key memories, example messages, and directives.
- `[documented]` It exposes a chat break to reset short-term context.
- `[strong inference]` The runtime prompt assembly likely includes:
  - backstory and directives
  - selective persistent fields
  - recent turns
  - cascaded memory material
  - retrieved journals/long-term memory
  - model/version-specific formatting

### Memory Model

- `[documented]` Multi-layer memory is explicit and productized.
- `[documented]` Journal entries act like a lorebook with trigger phrases.
- `[documented]` Long-term memory is automatically consolidated over time.
- `[strong inference]` Kindroid is operationalizing memory as multiple cooperating stores, not one summary blob.

### Prompt / Orchestration Model

- `[strong inference]` Kindroid likely treats prompt construction as a first-class product subsystem, even if it does not describe that layer in the same depth as Character.AI.
- `[strong inference]` The companion behavior is shaped by explicit fields and runtime selection, not only a long hidden system prompt.

### Image Generation Workflow

- `[documented]` Single selfies use a user prompt.
- `[documented]` Group selfies split prompting into avatar-level prompts and an overall prompt.
- `[documented]` Auto-selfies create prompts from chat context.
- `[documented]` Avatar description is fed into the selfies engine.
- `[documented]` Avatar boost trains an adapter from multiple images.

### Identity Consistency Strategy

- `[documented]` Custom avatar + avatar description + optional avatar boost is the identity system.
- `[strong inference]` This is much closer to adapter/reference-image conditioning than to "prompt-only" generation.
- `[strong inference]` It is also a stronger signal than a per-character LoRA because the product lets users swap avatars and tune weights dynamically.

### Voice / Video Pipeline Hints

- `[documented]` Calls and voice exist.
- `[documented]` Video selfies use a first frame and motion prompt.
- `[strong inference]` Kindroid is running separate generation services for text, voice, image, and video, all bound to the same character record.

### Likely Infrastructure Pattern

- `[strong inference]` Kindroid likely has one of the more sophisticated orchestration layers in the category:
  - multi-version LLM routing
  - large context tiers
  - memory services
  - image and video queues
  - per-character avatar assets
  - API exposure for external integrations

## Nomi

Nomi is another extremely useful reference because it publicly exposes how it thinks about memory and image prompting.

### Documented Public Facts

- `[documented]` Nomi markets short-, medium-, and long-term memory.
- `[documented]` Nomi exposes shared notes and backstory-style customization for the companion.
- `[documented]` Nomi exposes a "Mind Map" system and publicly describes it as a memory-related feature.
- `[documented]` Nomi's public guidance says appearance traits should live in appearance shared notes, while the image prompt should focus on the scene.
- `[documented]` Nomi's art prompting guidance uses short structured prompts with action/outfit, setting, framing, and lighting/mood.
- `[documented]` Nomi's legacy art guidance says the companion will closely resemble the initial profile picture by default across selfies and art.
- `[documented]` Nomi allows appearance shared notes to affect image generation.
- `[documented]` Nomi supports voice, selfies, videos, roleplay, and API features.

### What This Means

- `[documented]` Nomi explicitly separates appearance identity from per-image scene prompting.
- `[strong inference]` That separation is one of the most important clues in the entire category: the best systems keep stable identity in a persistent channel and use the live prompt for the scene.
- `[strong inference]` Nomi's Mind Map appears to be a higher-order retrieval layer above raw conversation memory, not just a simple note field.

### Chat Stack

- `[documented]` Nomi combines backstory/shared notes with conversation-derived memory.
- `[documented]` Mind Maps are automatically updated by the system rather than manually maintained only by the user.
- `[strong inference]` The chat prompt likely includes a selected slice of shared notes plus dynamically retrieved Mind Map entries and recent context.

### Memory Model

- `[documented]` Shared notes persist and are always available.
- `[documented]` Mind Map entries are dynamically recalled, while shared notes are always available.
- `[documented]` Nomi treats user-edited facts and auto-generated memory as different memory classes.
- `[strong inference]` This is one of the strongest public examples of "persistent facts + dynamic retrieval" in the companion category.

### Prompt / Orchestration Model

- `[strong inference]` Nomi likely uses a hidden prompt assembly layer that blends:
  - companion identity
  - shared notes
  - retrieved memory/Mind Map entries
  - recent roleplay/chat context
  - style and safety instructions

### Image Generation Workflow

- `[documented]` Nomi asks for short prompts with action/outfit, setting, framing, and lighting/mood.
- `[documented]` Appearance belongs in appearance notes, not in every image prompt.
- `[documented]` The initial profile picture influences future selfies/art.
- `[strong inference]` Nomi is likely using profile/reference-image conditioning plus structured prompt composition.

### Identity Consistency Strategy

- `[documented]` Initial profile picture plus appearance shared notes are key identity controls.
- `[strong inference]` This strongly suggests identity anchoring through reference imagery and persistent appearance descriptions, not merely prompt tags.
- `[weak inference]` Nomi may use adapters or an internal identity encoder, but there is no public proof of the exact mechanism.

### Voice / Video Pipeline Hints

- `[documented]` Nomi supports voice chats, videos, and art.
- `[strong inference]` Like Kindroid and Candy, this implies separate media pipelines attached to one companion state.

## Replika

Replika is older and more mainstream than the other products, which makes it a useful contrast case.

### Documented Public Facts

- `[documented]` Replika supports natural chat plus explicit commands such as "Facts about me", which returns something it remembers from past conversations.
- `[documented]` Replika publicly says user feedback helps improve future conversations.
- `[documented]` Replika cannot send arbitrary photos or videos, except selfies.
- `[documented]` Replika supports songs, selfies, and voice-related features rather than open scene image generation.
- `[documented]` Replika is heavily avatar-centric compared with Candy.ai, Kindroid, and Nomi.

### What This Means

- `[documented]` Replika clearly has some user memory layer.
- `[strong inference]` Replika's memory/UI model appears simpler and more consumer-facing than Kindroid/Nomi's more explicit memory systems.
- `[strong inference]` Replika's image system is much narrower: it is a selfie/avatar pipeline, not a fully general scene generator.

### Chat Stack

- `[strong inference]` Replika likely uses:
  - persistent user profile facts
  - relationship/emotional state
  - recent history
  - a proprietary prompt/ranking layer
- `[weak inference]` It may also use diary-style summaries or extracted memories internally, but the public docs are less explicit than Kindroid/Nomi.

### Image Generation Workflow

- `[documented]` Replika is limited to selfies rather than open-ended photo/video sending.
- `[strong inference]` Images are probably generated from avatar state and a constrained selfie pipeline, which is cheaper and safer than open scene generation.

### Identity Consistency Strategy

- `[documented]` The avatar is central.
- `[strong inference]` Replika gets identity consistency mostly from a constrained avatar system rather than a broad promptable visual engine.

### Why Replika Matters

- `[strong inference]` Replika shows one valid product strategy: constrain the image problem. That lowers complexity but also limits realism and scene richness.

## Character.AI

Character.AI is not a romance-first companion product, but it is a major reference for prompt assembly, memory scaffolding, and large-scale orchestration.

### Documented Public Facts

- `[documented]` Character.AI originally described itself as being powered by its own deep learning models built for conversation.
- `[documented]` Character.AI later stated that it had shifted toward building on open-source model foundations.
- `[documented]` Character.AI's Prompt Poet post says production prompt construction includes conversation modalities, experiments, characters, chat types, user attributes, pinned memories, user personas, and the full conversation history.
- `[documented]` Character.AI describes building billions of prompts per day.
- `[documented]` Character.AI added pinned memories, auto memories, and chat memories.
- `[documented]` Character.AI has "Imagine" features that turn conversations into visuals.
- `[documented]` Character.AI operates at very large inference scale and publicly discussed production inference on large models in 2026.

### What This Means

- `[documented]` Character.AI openly confirms that prompt assembly itself is a major engineering system.
- `[strong inference]` This is one of the strongest public confirmations that "the product" is not the base model; it is the orchestration layer around the model.
- `[strong inference]` Character.AI's memory and persona systems are closest to industrial-strength prompt assembly rather than simple chatbot wrappers.

### Chat Stack

- `[documented]` Character.AI uses persona, memories, conversation history, user attributes, and experiment flags in prompt construction.
- `[strong inference]` The runtime stack likely includes a sophisticated prompt DSL, retrieval/memory selection, and traffic/model routing.

### Memory Model

- `[documented]` Pinned memories, auto memories, and later chat memories are explicit product features.
- `[strong inference]` Character.AI is blending user-fixed memory with system-generated memory, similar in structure to Nomi and Kindroid.

### Image Workflow

- `[documented]` Character.AI offers conversation-to-image features through Imagine.
- `[strong inference]` Character.AI likely uses hidden prompt composition derived from the ongoing conversation and character state rather than exposing image-prompt engineering directly to the user.

### Identity Consistency Strategy

- `[weak inference]` Character.AI likely cares less about photorealistic identity locking than Candy.ai, Kindroid, and Nomi, because its main public product is broader roleplay and entertainment.
- `[strong inference]` Its main relevance to this project is prompt assembly and memory architecture, not avatar consistency.

## 3. Cross-App Engineering Pattern Extraction

The strongest shared pattern across the category is not "one model plus a prompt". It is a layered orchestration architecture.

### 3.1 Character Card / Persona Layer

- `[documented]` Every serious product exposes some persistent character/persona configuration.
- `[strong inference]` This layer usually contains:
  - name and role
  - personality and style
  - relationship framing
  - appearance traits
  - boundaries / preferences
  - example messages or dialogue style

### 3.2 System-Prompt and Policy Layer

- `[documented]` Character.AI explicitly confirms rich prompt assembly in production.
- `[strong inference]` The rest of the category almost certainly does the same, even when they do not say so publicly.
- `[strong inference]` This layer likely includes:
  - product policy
  - safety/moderation instructions
  - character instructions
  - response style rules
  - business logic flags
  - experiment and ranking variants

### 3.3 Short-Term Conversational Context

- `[documented]` All chat products depend on recent history.
- `[documented]` Kindroid explicitly exposes chat break behavior, which proves short-term context is a distinct memory layer.
- `[strong inference]` All apps manage the tradeoff between recent-turn fidelity and longer-term continuity.

### 3.4 Medium-Term Memory Summarization

- `[documented]` Kindroid has cascaded memory.
- `[documented]` Nomi has Mind Map and medium/long-term memory distinctions.
- `[documented]` Character.AI has auto-memories and pinned/chat memories.
- `[strong inference]` Medium-term memory is the "bridge layer" that prevents total forgetting without stuffing entire histories into the context window.

### 3.5 Long-Term Retrieval / Lorebook Memory

- `[documented]` Kindroid has journals and retrievable memories.
- `[documented]` Nomi has shared notes and dynamic Mind Map retrieval.
- `[strong inference]` Long-term memory is usually a retrieval store, not a massive always-on prompt dump.

### 3.6 Image Prompt Composer

- `[documented]` Kindroid auto-selfies generate prompts from conversation context.
- `[documented]` Nomi separates appearance notes from scene prompt text.
- `[strong inference]` The best products do not ask the user to manually repeat every appearance detail in every prompt. They compose a scene prompt from:
  - persistent appearance / identity metadata
  - current scene/action
  - mood / framing / lighting
  - optional prompt enhancement

### 3.7 Image Identity Anchor

- `[documented]` Kindroid uses custom avatars, avatar descriptions, and adapter-like avatar boost.
- `[documented]` Nomi uses initial profile picture plus appearance notes.
- `[strong inference]` This is one of the category's most important hidden truths: consistent companion images require a persistent identity anchor outside the raw text prompt.
- `[strong inference]` The common mechanisms are likely:
  - reference image conditioning
  - adapter modules
  - profile-image encoders
  - structured appearance sheets
- `[weak inference]` Dedicated LoRAs probably exist in some curated-house-character cases, but are less likely to be the default mechanism for arbitrary user-generated companions.

### 3.8 Asynchronous Media Services

- `[documented]` Candy token-gates images and videos.
- `[documented]` Kindroid and Nomi expose separate image/video flows.
- `[strong inference]` Media generation is usually queue-driven and operationally separate from chat inference.

### 3.9 Where the Category Converges

- `[strong inference]` Companion apps converge on:
  - persistent persona fields
  - layered memory
  - hidden prompt assembly
  - image generation as a separate service
  - some identity anchor beyond prompt-only generation

### 3.10 Where the Category Diverges

- `[strong inference]` They diverge on:
  - how explicit the memory controls are
  - how constrained or open the image system is
  - how permissive moderation is
  - whether they expose APIs
  - how much they let users tune the companion directly

## 4. Reference Architecture for Our Build

This section translates the research into a buildable local-first Candy.ai-style architecture.

## 4.1 Design Principle

The product is not "a chatbot that can also call an image model".

The product is:

- a persistent character system
- with layered memory
- and a separate visual identity system
- tied together by orchestration

## 4.2 What Must Exist in v1

### Character Schema

Use structured fields, not one giant free-text prompt.

Recommended v1 character card:

- name
- role / relationship type
- personality traits
- speaking style
- backstory summary
- boundaries / hard constraints
- appearance sheet
- example dialogue
- visual style default

### Memory Layer

Recommended v1 memory stack:

1. recent chat history
2. pinned facts
3. rolling summary
4. retrievable journal / lore entries

Do not start with a full graph/Mind Map clone. Start with a simpler but explicit layered design.

### Chat Orchestrator

At inference time, assemble:

1. system prompt
2. character card slice
3. pinned facts
4. rolling summary
5. retrieved journal items
6. recent turns
7. current message

### Image System

Separate image generation from chat generation.

The image request should be built from:

1. persistent appearance sheet
2. optional reference images
3. scene summary derived from current chat state
4. framing / lighting / pose defaults
5. model-specific prompt composer

### Identity Conditioning

For a Candy-style product, use:

- persistent appearance sheet
- plus reference-image conditioning / adapter-based identity preservation

This is the most realistic path to companion consistency in v1.

## 4.3 What Can Be Deferred

- group chat
- native mobile app
- video generation
- voice cloning
- full Mind Map / graph memory
- per-character fine-tuning pipeline
- marketplace / social layer
- complex automation API

## 4.4 What Should Stay Hidden From the User

- the raw system prompt
- the rolling memory summary
- the full assembled image prompt
- model-routing logic
- safety / policy scaffolding

Users should control the companion, not babysit the internal prompt stack.

## 4.5 What Should Be Structured Data, Not Free Text

- appearance
- relationship state
- pinned memory facts
- personality traits
- scene state
- wardrobe / recurring visual props
- user preferences

Free text is still useful for backstory and custom notes, but the product becomes much easier to control once the critical state is structured.

## 4.6 Direct Answer: How do the best apps make images match the text?

- `[strong inference]` The best apps do not rely on the current user message alone.
- `[strong inference]` They combine:
  - a persistent appearance anchor
  - a scene prompt derived from the current conversation
  - hidden prompt enhancement
  - model-specific image generation logic
  - identity-preserving conditioning when consistency matters

If you only use prompt text, the images will drift.

## 4.7 Candidate Implementations

### A. Pure prompt-only

- Pros: simplest
- Cons: weak consistency, high drift, poor "companion" feel
- Verdict: not recommended for a Candy-style product

### B. Prompt + persistent appearance sheet

- Pros: much better control with low complexity
- Cons: still weaker than visual reference conditioning
- Verdict: good minimum baseline

### C. Prompt + reference image / adapter

- Pros: strong identity consistency without per-character training overhead
- Cons: more engineering complexity
- Verdict: best v1 path for a serious companion product

### D. Per-character LoRA or fine-tune

- Pros: strongest identity/style lock when done well
- Cons: expensive, slow, complex, hard to scale, awkward for user-created characters
- Verdict: overkill for v1

### E. Hybrid approach

- appearance sheet
- reference images
- scene composer
- prompt enhancer

- Verdict: recommended

## 5. Decision Memo

### What these apps are most likely doing today

- `[strong inference]` Using one or more foundation LLMs behind a heavy orchestration layer
- `[strong inference]` Maintaining per-character metadata separate from raw chat history
- `[strong inference]` Using layered memory, not context window alone
- `[strong inference]` Converting chat state into image-ready scene descriptions
- `[strong inference]` Preserving image identity through avatar/reference-image/adapters rather than prompt text alone
- `[strong inference]` Running voice, image, and video as separate pipelines attached to the same character record

### What is realistic for us to build locally

- a roleplay-tuned local LLM or high-quality API-backed LLM
- a structured character card
- pinned facts + rolling summary + retrieval memory
- a hidden prompt builder
- a realistic image model with reference-image conditioning
- optional prompt enhancer for images

This is realistic.

### What we should copy

- Kindroid/Nomi-style separation of appearance identity from scene prompt
- layered memory instead of one giant context dump
- hidden orchestration instead of exposing raw prompt plumbing to the user
- asynchronous media generation
- product-first simplification rather than academic overengineering

### What we should ignore

- perfect reverse-engineering of hidden competitor prompts
- exact parity with every commercial product feature
- per-character training before the core loop works
- prompt-only identity consistency

### What is overkill for MVP

- per-character LoRA training
- video generation
- elaborate graph memory systems
- mobile app first
- marketplace / social layers

### What we should build first

Build this in order:

1. character schema
2. chat orchestrator with layered memory
3. scene-state extractor / image prompt composer
4. image generation with reference-image conditioning
5. minimal local UI

That captures the real product essence of Candy.ai without chasing the hardest and least necessary parts first.

## Direct Answers to the Required Questions

### How are companion apps structuring chat memory in practice?

- `[documented]` The clearest public evidence points to multiple memory layers: persistent fields, recent context, medium-term summaries, and long-term retrieval.

### How are they keeping characters consistent over long conversations?

- `[strong inference]` By combining persistent character metadata with memory retrieval and prompt assembly, not by relying on raw chat history alone.

### How are they getting scene images to match chat context?

- `[strong inference]` By composing a scene prompt from chat state and pairing it with a persistent visual identity anchor.

### Are they likely using base models, fine-tunes, LoRAs, reference images, or some combination?

- `[strong inference]` Some combination.
- `[strong inference]` The most plausible default stack is base/foundation models plus orchestration plus reference-image/adapters.
- `[weak inference]` LoRAs are more likely for curated or specialized cases than for every user-generated companion.

### Which parts are truly companion-specific versus standard LLM-app engineering?

- `[strong inference]` Standard LLM-app engineering:
  - prompt assembly
  - memory retrieval
  - model routing
  - moderation
  - media queues
- `[strong inference]` Truly companion-specific:
  - relationship continuity
  - persistent persona tuning
  - image identity consistency
  - voice/visual embodiment of one recurring character

### What is the smallest architecture that captures the real product essence of Candy.ai?

- `[strong inference]` Structured character card + layered memory + hidden prompt builder + reference-conditioned image generation + simple local UI.

## Sources

### Candy.ai

- Candy AI Help Center, "What can I do as a paid user?":
  https://everai.zendesk.com/hc/en-us/articles/44102896051481-What-can-I-do-as-a-paid-user
- Candy AI Privacy Policy:
  https://candy.ai/es/privacy-policy
- Candy AI marketing/search landing surface:
  https://candy.ai/

### Kindroid

- Memory:
  https://docs.kindroid.ai/memory
- Selfies, video selfies, & avatars:
  https://docs.kindroid.ai/selfies-video-selfies-and-avatars
- API documentation:
  https://docs.kindroid.ai/api-documentation
- FAQs:
  https://docs.kindroid.ai/faqs
- Product landing page:
  https://kindroid.ai/

### Nomi

- Product site:
  https://nomi.ai/
- Art Prompting Basics Quick Guide:
  https://wiki.nomi.ai/Art_Prompting_Basics_Quick_Guide
- Legacy AI Art & Appearance Prompting Basics:
  https://nomi.ai/nomi-knowledge/nomi-legacy-ai-art-appearance-prompting-basics/
- Mind Map reference:
  https://wiki.nomi.ai/Are_Mind_Map_Entries_Memories_And_How_Are_They_Unique
- Misc Mind Map questions:
  https://wiki.nomi.ai/Misc_Mind_Map_Questions

### Replika

- What commands can I use with Replika?:
  https://help.replika.com/hc/en-us/articles/115001094611-What-commands-can-I-use-with-Replika
- Replika can't send photo/video:
  https://help.replika.com/hc/en-us/articles/4705307921933-Replika-can-t-send-photo-video

### Character.AI

- What is Character.AI?:
  https://support.character.ai/hc/en-us/articles/14997389547931-What-is-Character-AI
- Helping Characters Remember What Matters Most:
  https://blog.character.ai/helping-characters-remember-what-matters-most/
- AMA Recap and January 2024 FAQ:
  https://blog.character.ai/ama-recap-and-january-2024-faq/
- Introducing Prompt Poet:
  https://blog.character.ai/introducing-prompt-poet/
- Character.AI blog:
  https://blog.character.ai/

### Perchance

- AI Character Generator:
  https://perchance.org/ai-character
- AI Chatbot / Perchat:
  https://perchance.org/perchat
- AI text-to-image:
  https://perchance.org/ai-text-to-image
- Perchance FAQ:
  https://perchance.org/6l0h3smi30
