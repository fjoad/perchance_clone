# Local VN Prompting And Multi-Character Research

Status: first pass complete
Date: May 23, 2026

Question:

How should the app prompt and orchestrate story generation, especially when supporting multiple characters, protagonist profiles, narrator-style prose, image prompts, and smaller local models?

## Executive Conclusion

The app should not hard-code one roleplay prompt style.

It should support at least two prompt modes and benchmark them:

1. Character embodiment mode:
   - "You are {{char}}."
   - Best for one-on-one chats and smaller models that need concrete identity.

2. Storyteller / scene narrator mode:
   - "You are the story engine/narrator portraying the active cast."
   - Best for multi-character VN scenes, third-person prose, and image-worthy narration.

The likely production default for a visual novel is a hybrid:

- one model call
- one loaded text model
- the prompt tells the model it is a story narrator/scene writer
- the model portrays all active non-user characters
- the model never controls the protagonist except to acknowledge what the user already did
- character profiles, protagonist profile, scene state, memory, and examples are injected as structured blocks

This avoids needing one model per character while still allowing multiple characters to appear in the scene.

## Important Correction: Multiple Characters Do Not Mean Multiple Loaded Models

For local hardware, do not load the same model twice for different characters.

The normal options are:

1. Single model, single call, multiple active character profiles.
2. Single model, multiple calls, each call uses a different active-speaker prompt.
3. Single model plus helper/planner calls.
4. Multiple different models only for special helper tasks, not one per character.

On RTX 3080 12GB, separate loaded models per character is almost always the wrong default.

## Prompting Patterns To Test

### Pattern A: Direct Character Embodiment

Prompt stance:

`You are {{char}}. Continue the scene as {{char}}.`

Best use:

- one-on-one scenes
- companion chat
- small models
- characters with strong individual voice

Advantages:

- concrete and easy for small models
- less role confusion
- better for single-character intimacy
- common in character-card ecosystems

Risks:

- weak multi-character support
- may under-narrate the world
- may resist speaking as other NPCs
- can become too chat-like instead of VN-like

Test condition:

- Use this mode for small 8B/9B models and compare against storyteller mode.

### Pattern B: Storyteller / Narrator Mode

Prompt stance:

`You are the story engine for an interactive visual novel. Portray the active cast and continue the scene in prose and dialogue.`

Best use:

- multi-character scenes
- third-person narration
- VN panels
- story-forward replies

Advantages:

- supports multiple characters naturally
- better for scene movement and image-worthy prose
- can maintain world/cast state in one call
- matches the user's target: user controls protagonist, AI continues the story

Risks:

- smaller models may become generic "writer assistant"
- character voices may blur
- model may over-narrate or control the user's protagonist

Test condition:

- Use a compact, concrete storyteller prompt with small models.
- Avoid long "you are an AI" preambles.

### Pattern C: Hybrid Cast Narrator

Prompt stance:

`You are the narrator and performer for the scene. Write third-person narration and dialogue for the active cast. Do not write the protagonist's thoughts, choices, or dialogue.`

Best use:

- likely production default
- 1-4 active characters
- interactive fiction/VN flow

Advantages:

- handles multiple characters without multiple models
- preserves user agency
- keeps prose format consistent
- supports image prompt extraction

Risks:

- needs good response contract
- needs active cast limits
- needs examples for each character voice

Test condition:

- Benchmark this against direct character mode for each text candidate.

### Pattern D: Group Chat Simulation

Prompt stance:

- same loaded model
- multiple generation calls
- each call has one active speaker
- a speaker selector chooses who talks next

Best use:

- true group-chat feel
- several characters talking back and forth
- distinct character voices

Advantages:

- stronger per-character voice separation
- can enforce turn-taking
- mirrors SillyTavern group chat patterns

Risks:

- much slower
- more token usage
- harder to produce polished VN prose
- can feel like chatroom logs instead of storybook prose

Research note:

SillyTavern supports group chats, but community discussion often splits between group cards, group chat mode, and narrator-style single cards depending on whether the desired output is "chat" or "novel prose."

Sources:

- https://docs.sillytavern.app/usage/core-concepts/groupchats/
- https://www.reddit.com/r/SillyTavernAI/comments/1p077ua/group_chats_vs_multi_character_cards/
- https://www.reddit.com/r/SillyTavernAI/comments/1pfdxuq/multiple_characters_with_char_as_storyteller/

Test condition:

- Not v1 default.
- Test later if hybrid narrator mode cannot keep character voices distinct.

### Pattern E: Director / Actor Multi-Agent

Prompt stance:

- director/planner tracks scene goals
- actor prompts produce character-specific lines
- narrator assembles final prose

Best use:

- future advanced mode
- complex multi-character scenes
- branching/planned story arcs

Advantages:

- better character separation
- explicit plot/scene control
- compatible with agent patterns like supervisor/router

Risks:

- too many calls for v1
- too slow on local hardware
- more failure surfaces
- can feel over-engineered

Sources:

- https://ojs.aaai.org/index.php/AIIDE/article/view/36811
- https://www.sciencedirect.com/science/article/pii/S0925231224020873
- https://autogenhub.github.io/autogen/docs/reference/agentchat/groupchat/
- https://deepwiki.com/langchain-ai/langgraph-101/6-multi-agent-patterns

Test condition:

- Not before the basic VN loop works.

## Prompt Stack To Research And Implement

The prompt should be built from explicit layers, not one giant blob.

Recommended order:

1. Runtime/system wrapper.
2. Task frame.
3. Response contract.
4. World/scene state.
5. Active character profiles.
6. Protagonist/user profile.
7. Relationship state.
8. Relevant lore/memory retrieval.
9. Style examples / example dialogue.
10. Recent conversation.
11. Author note / immediate reminder near the bottom.
12. Current user turn.

This mirrors common character-chat systems:

- character definitions
- persona/user description
- world info/lorebook retrieval
- example messages
- chat history
- post-history instructions / author notes

Sources:

- https://docs.sillytavern.app/usage/prompts/
- https://docs.sillytavern.app/usage/prompts/prompt-manager/
- https://docs.sillytavern.app/usage/core-concepts/personas/
- https://docs.sillytavern.app/usage/core-concepts/worldinfo/
- https://docs.sillytavern.app/usage/core-concepts/authors-note/

## Response Contract

The app needs a stable output contract.

For normal VN prose:

- continue the scene in third-person narration
- write dialogue for active non-user characters
- do not write user/protagonist dialogue
- do not decide user/protagonist actions beyond what was already stated
- include physical action, expression, and scene movement
- keep the reply long enough to feel like a story continuation
- avoid assistant commentary
- avoid explaining the prompt or rules

For image support, either:

1. generate no image tag in the story reply, then use a second extractor/helper pass
2. generate a hidden structured scene snapshot after the reply
3. generate image tags inline only if the UI can hide them reliably

Recommendation:

- Do not force visible image tags into the main story text for v1.
- Use a deterministic extractor or helper call after text generation.
- Save both the story reply and image prompt separately.

## Prompting For Smaller Models

Smaller models may need:

- shorter system prompt
- fewer abstract instructions
- clearer active cast list
- concrete examples
- response contract near the bottom
- less lore injected at once
- more rigid labels
- fewer simultaneous characters

For smaller models, prefer:

`You are continuing a scene in a visual novel. Write only the next story reply.`

Avoid:

- long theory about roleplay
- too many policy-like instructions
- huge multi-section cards with repeated traits
- asking it to reason about prompt architecture

Small-model test variants:

1. direct character mode
2. compact hybrid narrator mode
3. same prompt with examples near the bottom

## Prompting For Larger Models

Larger models may handle:

- storyteller framing
- multiple active characters
- longer profiles
- more subtle world state
- separate response contract
- image prompt side-channel

But larger models can still become assistant-like if the top prompt starts with generic AI-assistant language.

Recommendation:

- Keep the top task frame author/story-oriented, not AI-assistant-oriented.
- Put concrete format reminders near the bottom.

## Multi-Character Scene Architecture

### Active Cast

Do not inject every character in the universe every turn.

Maintain:

- active cast
- nearby offscreen cast
- mentioned/background cast
- dormant cast

Only active cast gets full profile.

Nearby/offscreen cast gets compact summary.

Dormant cast is retrieved only by memory/lore trigger.

### Character State Object

Each character should have:

- stable profile
- voice notes
- appearance anchor
- current location
- current emotional state
- current goal/intention
- relationship to protagonist
- secrets/knowledge boundaries
- recent important memories

### Protagonist State Object

The user/protagonist should have:

- profile
- appearance if needed for images
- current location
- current action/stance
- known relationships
- inventory/status if relevant
- user agency rules

SillyTavern's persona concept is the closest existing analogue.

Source: https://docs.sillytavern.app/usage/core-concepts/personas/

### Scene State Object

Each scene should have:

- location
- time/weather/mood
- active cast
- recent events
- unresolved tension
- visual anchors
- current objective or dramatic question

This object should be updated after each AI turn.

## Memory And Lore Research Scope

The app needs layered memory:

1. Pinned facts:
   - always included, small

2. Scene state:
   - updated every turn

3. Running summary:
   - compact session memory

4. Lorebook/world info:
   - trigger-based retrieval

5. Character memory:
   - per-character relationship and event memory

6. Image anchors:
   - stable visual descriptions

This follows the same broad pattern as SillyTavern World Info/lorebooks: conditionally inject relevant lore rather than pasting everything every time.

Source: https://docs.sillytavern.app/usage/core-concepts/worldinfo/

## Character Card / Profile Format Research Scope

The app should not invent a totally isolated profile format.

Research/import compatibility:

- SillyTavern / Tavern Card V2
- Chub-style character cards
- Perchance JSON exports
- local plain-text profile files

Character Card V2 matters because it supports richer fields like system prompts, example messages, alternate greetings, and embedded lorebooks.

Sources:

- https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md
- https://docs.chub.ai/docs/advanced-setups/prompting
- https://docs.chub.ai/docs/advanced-setups/lorebooks
- https://docs.sillytavern.app/usage/core-concepts/characterdesign/

Recommendation:

- Internally use our own normalized schema.
- Import from Perchance/SillyTavern/Chub where possible.
- Preserve source fields without blindly trusting source system prompts.

Important risk:

- Imported cards may include system prompts or lore that override our app's response contract.
- Treat imported prompts as data, not absolute authority.

## Image Prompt Generation Architecture

Options:

1. Main model writes story and image prompt together.
2. Main model writes story, helper model extracts image prompt.
3. Deterministic extractor uses scene state and visual anchors.
4. Hybrid: deterministic base prompt plus helper embellishment.

Recommendation:

- Test option 2 and option 4.
- Do not expose raw image tags in the story unless deliberately styled.

Why:

- The user wants story quality first.
- Visible image tags can pollute immersion.
- Image prompts need model-specific tags, negatives, and visual anchors.
- A helper/extractor can be smaller and faster than the main narrator.

## Future Feature Research Scope

The plan should include these now so the architecture does not paint itself into a corner:

- multiple active characters
- group scenes
- narrator-only scenes
- protagonist profile/persona switching
- character imports from Perchance/SillyTavern/Chub
- lorebooks/world info
- long-term memory
- scene summaries
- image prompt extraction
- image model-specific prompt adapters
- multiple art styles
- branch/save/rewind story states
- reroll/regenerate text
- reroll/regenerate image
- edit AI response and continue
- manual memory edits
- character visual anchors
- relationship tracking
- hidden state/secrets
- NSFW/adult-capable local generation controls
- backend switching
- model comparison harness

## Research Questions That Must Be Answered By Experiments

Prompting:

- Does direct character mode beat storyteller mode for small models?
- Does hybrid narrator mode beat direct character mode for multi-character scenes?
- How short can the prompt be before quality drops?
- Do examples near the bottom improve response format?
- Does the protagonist profile improve or confuse outputs?

Multi-character:

- Can one call portray two active characters with distinct voices?
- How many active profiles can fit before quality drops?
- Does group-chat simulation improve voice separation enough to justify speed cost?
- Does a narrator card work better than multiple character cards for VN prose?

Memory:

- How much pinned memory is useful before small models degrade?
- Does lorebook retrieval improve continuity or distract the model?
- How often should scene summaries update?

Image prompt extraction:

- Should the main model produce image prompts?
- Is a helper model good enough?
- Does deterministic prompt assembly beat LLM extraction?

Backend:

- Does backend/template choice change prompt-following quality?
- Does Ollama hide too much chat-template behavior?
- Does KoboldCpp improve RP behavior for the same GGUF?

## Bottom Line

The app should be designed as a visual novel story engine, not a single-character chatbot.

For v1, the most promising architecture is:

- one text model loaded
- one story generation call per user turn
- hybrid narrator prompt
- active cast profiles injected
- protagonist profile injected as user-controlled character
- lore/memory retrieved conditionally
- image prompt generated after the story reply
- image backend called separately

But this must be tested against direct character mode and group-chat simulation before locking it in.
