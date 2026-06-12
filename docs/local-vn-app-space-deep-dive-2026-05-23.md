# Local VN App-Space Deep Dive

Status: first pass complete
Date: May 23, 2026

This note is separate from model feasibility research.

Model feasibility research asks:

- What text models can run locally?
- What image models can run locally?
- Which backends can run them fast enough?

App-space research asks:

- How do successful AI roleplay/story apps structure prompts?
- How do they store characters, personas, lore, memory, and chat state?
- What features are expected in this space?
- How should a local visual novel engine be architected so future features do not require a rewrite?

## Executive Conclusion

The app should be designed as a local visual novel/story engine with character-chat compatibility, not as a simple chatbot with image generation bolted on.

The core pattern across SillyTavern, Chub, NovelAI, Agnai, Kobold-style workflows, and related roleplay apps is:

- structured character/persona data
- prompt assembly from ordered blocks
- short-term chat context
- persistent memory or lorebook retrieval
- optional author note / reminder injection near the bottom
- backend abstraction
- import/export compatibility
- reroll/edit/branch workflows
- optional image generation, TTS, and visual modes

The app should not copy any one product exactly. It should internalize the common architecture:

- normalized profiles
- layered prompt builder
- explicit scene state
- model/backend abstraction
- saved/reviewable generation artifacts
- branchable story sessions
- image generation as a coordinated subsystem

## Research Track A: Existing App Families

### SillyTavern

Why it matters:

- power-user standard for character chat and roleplay
- supports many backends
- supports character cards, personas, World Info/lorebooks, Author's Note, group chats, prompt manager, extensions, image generation, TTS, and visual novel mode

Sources:

- https://docs.sillytavern.app/usage/prompts/
- https://docs.sillytavern.app/usage/prompts/prompt-manager/
- https://docs.sillytavern.app/usage/core-concepts/personas/
- https://docs.sillytavern.app/usage/core-concepts/worldinfo/
- https://docs.sillytavern.app/usage/core-concepts/authors-note/
- https://docs.sillytavern.app/usage/core-concepts/groupchats/
- https://docs.sillytavern.app/usage/characters/

Features to study:

- prompt manager block ordering
- character fields
- persona/user profile placement
- World Info/lorebook trigger mechanics
- Author's Note placement/frequency
- group chat mechanics
- Visual Novel mode
- image generation extension patterns
- prompt inspection/debugging

What to borrow:

- prompt blocks as first-class objects
- persona separate from character
- lorebook/world info as conditional context
- author note/reminder near the bottom
- group/multi-character support as a mode, not the default
- import/export compatibility with character cards

What not to copy blindly:

- too much UI/config complexity for v1
- fragile prompt presets that vary by user
- making users manage every token manually

### Chub AI

Why it matters:

- large character-card ecosystem
- focuses on character definitions, lorebooks, and prompt customization
- documents prompt order and character creation concepts clearly

Sources:

- https://docs.chub.ai/docs/advanced-setups/prompting
- https://docs.chub.ai/docs/advanced-setups/lorebooks
- https://docs.chub.ai/docs/the-basics/character-creation

Features to study:

- character definitions
- system prompt per character
- lorebooks / characterbooks
- prompt order
- persona/card ecosystem expectations

What to borrow:

- compatibility mindset
- characterbooks/lorebooks
- clear separation between system prompt, character definitions, chat history, and post-history instructions

Risk:

- imported cards can contain system prompts that override the app's desired VN behavior

### NovelAI

Why it matters:

- story-first product, not just chat
- mature Memory, Author's Note, Lorebook, phrase bias, text adventure, and story settings concepts
- closer to interactive fiction than many character-chat apps

Sources:

- https://docs.novelai.net/en/text/editor/storysettings
- https://docs.novelai.net/en/text/lorebook
- https://docs.novelai.net/faq.html

Features to study:

- Memory
- Author's Note
- Lorebook activation windows
- phrase bias
- text adventure mode
- generation history
- story exports

What to borrow:

- story-level memory separate from character card
- lorebook entries for conditional world facts
- author note/reminder as powerful but potentially risky near-context tool
- editing/retrying as normal writing workflow

Important insight:

- NovelAI-style systems treat the prompt as a story context, not a chat transcript only.

### Agnai / Agnaistic

Why it matters:

- open-source/self-hostable character chat platform
- supports memory books, long-term memory, personas, multiple schema formats, and multiple backends

Sources:

- https://github.com/agnaistic/agnai
- https://agnai.guide/docs/creating-a-character/
- https://agnai.guide/docs/memory/
- https://agnai.guide/docs/memory/memory-books.html
- https://agnai.guide/docs/vocabulary/
- https://agnai.guide/docs/chat-settings/

Features to study:

- memory books
- chat embeds and user embeds
- persona schema formats
- scenario overrides
- hidden events/prompts
- multi-user/multi-bot design

What to borrow:

- memory as combined system: memory books, character books, chat embeddings, user embeddings
- scenario overrides per chat
- hidden events for story steering
- support for multiple profile formats

### Kobold / Text Adventure Lineage

Why it matters:

- historically close to AI Dungeon / text adventure / story generation
- local-first culture
- often paired with SillyTavern

Features to study:

- adventure mode
- memory
- author's note
- world info
- context shifting
- storyteller rather than chatbot framing

What to borrow:

- text adventure command/story distinction
- story-first prompt framing
- user action -> narrator continuation loop

### Perchance

Why it matters:

- actual quality benchmark from the user
- combines character/profile text, chat/story replies, and image tags/prompts
- free tool currently sets the minimum bar

Features to study from exports:

- character/profile structure
- protagonist/user profile structure
- chat turns
- image tags/prompt text
- response style
- story continuation format
- how user actions are represented

What to borrow:

- input/output quality target
- narrative/action/dialogue balance
- image prompt relation to text

What not to assume:

- Perchance architecture
- exact system prompt
- image pipeline

The export is a gold sample, not a spec.

## Research Track B: Core Feature Inventory

The app should plan for these features even if v1 only implements some.

### Character/Profile Features

- character profile
- protagonist/user profile
- appearance profile
- voice/speech style
- example dialogue
- first message / opening scene
- alternate greetings/openings
- relationship frame
- special instructions / reminder note
- visual anchor for images
- character-specific lorebook
- import/export from Perchance, SillyTavern, Chub, plain text

### Story/Session Features

- new story
- continue story
- branch story
- rewind to earlier turn
- edit user message
- edit AI reply
- reroll text
- reroll image
- save checkpoint
- session summary
- scene state
- current location/time/mood
- active cast
- hidden state/secrets
- relationship state

### Memory/Lore Features

- pinned memory
- running summary
- scene summary
- character memory
- protagonist memory
- relationship memory
- world/lorebook entries
- keyword-triggered retrieval
- embedding retrieval
- manual memory editor
- automatic memory extraction
- memory review/approval before saving
- per-chat memory versus global memory

### Prompting Features

- prompt preset selection
- model-specific prompt templates
- direct character mode
- hybrid narrator mode
- storyteller mode
- group-chat mode
- author note / bottom reminder
- response length/style controls
- example dialogue placement
- prompt inspector
- rendered prompt export
- prompt A/B comparison

### Text Generation Features

- streaming text
- stop generation
- continue generation
- regenerate reply
- choose between swipes/rerolls
- lock preferred reply
- compare model outputs
- helper model for summaries/image prompts
- model-specific sampling presets

### Image Generation Features

- auto image after reply
- manual image button
- image prompt preview
- edit image prompt
- regenerate image
- keep same seed
- change seed
- prompt adapters per image model
- negative prompt presets
- style presets
- character visual anchors
- LoRA support
- upscaler/hires workflow
- save image metadata
- gallery per story/session

### Backend Features

- text backend abstraction
- image backend abstraction
- model registry
- backend health check
- explicit load/unload
- VRAM monitor
- path/cache validation
- benchmark runner
- failure recovery
- backend logs

### UI/UX Features

- VN/story panel layout
- chat/story transcript
- current image panel
- typewriter/streaming text
- branch/reroll controls
- model/backend status
- story library
- character library
- protagonist/persona library
- memory/lore editor
- prompt/debug inspector hidden behind dev mode

## Research Track C: Prompting Best Practices

Across roleplay/story tools, prompt construction is usually layered.

Common blocks:

- system/task prompt
- character definitions
- persona/user description
- scenario/setting
- lore/world info
- example dialogue
- chat/story history
- author note/reminder
- current user input

Sources:

- https://docs.sillytavern.app/usage/prompts/
- https://docs.sillytavern.app/usage/prompts/prompt-manager/
- https://docs.chub.ai/docs/advanced-setups/prompting

Research questions:

- Should the top task be "you are this character" or "you are a narrator/story engine"?
- Does smaller-model quality improve with direct embodiment?
- Does hybrid narrator mode improve multi-character VN prose?
- Where should example dialogue sit?
- How strong should the bottom reminder be?
- Should image prompts be hidden, separate, or inline?
- How much profile text is too much for 8B/9B?

Initial hypothesis:

- v1 should test direct character mode and hybrid narrator mode.
- production likely uses hybrid narrator mode for VN scenes.
- direct character mode may remain for one-on-one companion scenes.

## Research Track D: Memory And Context Management

The common pattern is not "dump everything into context."

It is:

- always include small critical facts
- include recent chat/story history
- include summaries
- retrieve only relevant lore/memory
- use author notes/reminders sparingly near the bottom

Sources:

- https://docs.sillytavern.app/usage/core-concepts/worldinfo/
- https://docs.novelai.net/en/text/lorebook
- https://agnai.guide/docs/memory/
- https://agnai.guide/docs/memory/memory-books.html

Research questions:

- What belongs in pinned memory?
- What belongs in scene state?
- What belongs in running summary?
- What belongs in lorebook?
- What belongs in character memory?
- What belongs in protagonist memory?
- Should memory be keyword-triggered, embedding-triggered, or both?
- Should auto-written memories require user approval?

Initial hypothesis:

- v1 should implement pinned memory, scene state, and manual lore entries first.
- automatic long-term memory should wait until outputs are stable.

## Research Track E: Multi-Character And Cast Management

This is a feature inside the app-space, not the whole research scope.

Research questions:

- One narrator call for all active characters?
- One call per active speaker?
- Separate narrator card?
- Speaker selector?
- How many active characters before quality drops?
- How to prevent the model from controlling the protagonist?

Initial hypothesis:

- v1 should use one model call with active cast profiles and hybrid narrator instructions.
- group-chat simulation should be a later experiment.
- multiple loaded model copies per character should not be used on current hardware.

## Research Track F: Image Integration

The apps in this space treat image generation as either:

- extension/plugin
- separate backend
- generated prompt from chat context
- manual prompt from user
- visual novel panel mode

Research questions:

- Should text model generate image tags inline?
- Should helper model extract image prompt after the reply?
- Should deterministic scene-state-to-prompt assembly be used?
- Should image prompt be visible to user?
- How do character visual anchors remain stable?
- How should LoRAs/styles be attached to characters?

Initial hypothesis:

- v1 should not show raw image tags in story text.
- story reply should be clean prose.
- image prompt should be generated separately and saved.
- model-specific prompt adapters are required.

## Research Track G: Backend And Storage Practices

Research questions:

- How do apps abstract many text backends?
- How do they abstract image backends?
- How do they handle backend-specific prompt templates?
- How do they handle cache/model paths?
- How do they expose logs/debugging?

Initial hypothesis:

- backend adapters should be swappable
- all rendered prompts and generation metadata should be saved
- path hygiene should be validated at startup

## Research Track H: Evaluation And Review

The app needs evaluation workflow, not just generation.

For text:

- compare model replies against Perchance reference
- score story-desire, character adherence, user agency, prose quality, continuity

For images:

- compare generated images against target quality
- score scene fit, identity, composition, anatomy, style, emotional usefulness

For full loop:

- measure latency
- measure VRAM
- inspect output
- decide if user would keep playing

## Revised High-Level Plan

There are two parallel research streams:

### Stream 1: Local Model/Runtime Feasibility

This asks:

- What text models can run?
- What image models can run?
- What text backends are viable?
- What image backends are viable?
- What orchestration keeps the loop responsive?

Documents:

- `docs/local-vn-current-space-research-2026-05-23.md`
- `docs/local-vn-small-model-adversarial-pass-2026-05-23.md`

### Stream 2: App-Space/Product Architecture

This asks:

- What features are expected?
- How do roleplay/story apps build prompts?
- How do they handle memory/lore/personas/cards?
- How should VN-specific text/image flow work?
- What should we build now so future features fit later?

Documents:

- this file
- `docs/local-vn-prompting-multichar-research-2026-05-23.md` as a sub-note
- `docs/local-vn-end-to-end-plan-2026-05-23.md` as the execution spine

## Bottom Line

The missing scope was real.

The project should not only ask "which model?" It should ask:

- What is the local app pattern that makes the model useful?
- What data structures let characters, protagonists, stories, memory, and images work together?
- What prompt assembly strategy turns raw profiles into Perchance-quality-or-better turns?
- What feature architecture avoids a rewrite when adding branches, lorebooks, multiple characters, rerolls, or image prompt adapters?

The next implementation step remains the same:

- build the gold-sample harness

But the harness must now evaluate both:

- model/runtime feasibility
- prompt/app-space architecture choices
