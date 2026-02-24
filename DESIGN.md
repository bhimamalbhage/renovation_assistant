# Design Note — Bob ↔ Alice Renovation Voice Assistant

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser (Web UI)                      │
│  ┌──────────────┐  ┌────────────────────────────────────┐   │
│  │  Voice Panel  │  │         Chat Transcript            │   │
│  │  (Orb + Name) │  │   user/bob/alice bubbles + metrics │   │
│  └──────┬───────┘  └──────────────┬─────────────────────┘   │
│         │   WebRTC audio + data   │                          │
└─────────┼─────────────────────────┼──────────────────────────┘
          │                         │
          ▼                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     LiveKit Cloud (SFU)                       │
│          routes audio/data between browser & agent           │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   agent.py (Python worker)                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              AgentSession (single session)           │    │
│  │   VAD: Silero  │  STT: Deepgram  │  TTS: OpenAI    │    │
│  │                │     nova-2      │  alloy / shimmer │    │
│  └────────┬───────┴────────┬────────┴──────────────────┘    │
│           │                │                                 │
│  ┌────────▼──────┐  ┌──────▼───────┐                        │
│  │   BobAgent    │  │  AliceAgent   │   ← session.update_   │
│  │  (planner)    │◄─┤  (specialist) │     agent() swaps     │
│  │               ├─►│              │     the active agent    │
│  └───────┬───────┘  └──────┬───────┘                        │
│          │                 │                                  │
│          ▼                 ▼                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │            RenovationState (shared dataclass)        │    │
│  │  rooms, budget, scope, risks, transfer_history, ...  │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Background extraction (gpt-4o-mini, non-blocking)   │    │
│  │  + Handoff summary generation on every transfer      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  frontend.py ─ HTTP server: serves HTML, issues JWT tokens   │
└─────────────────────────────────────────────────────────────┘
```

---

## Transfer Intent Detection

I used **LLM function-calling** (tool use) for transfer intent detection.

Each agent has a `@function_tool` that the LLM can invoke: Bob has `transfer_to_alice()` and Alice has `transfer_to_bob()`

The LLM decides when to call the tool based on the system prompt instructions. This gives us flexibility — it handles paraphrases ("let me talk to the specialist", "can Alice help?") without any regex or keyword list.

Also added some Guardrails to prevent bad transfers for example to block rapid ping-pong transfers.

---

## State & Memory Across Transfers

When transferring between agents, context is preserved seamlessly through three interconnected memory layers. First, the complete conversation history is passed to the new agent, with automatic summarization used for older messages to manage context size efficiently. Second, important project details like the budget and constraints are continuously extracted into a shared state in the background to avoid any voice lag. Finally, a brief handoff summary is generated at the exact moment of transfer so the incoming agent knows precisely where to pick up.

---

## Tradeoffs & Options Considered

For transfer intent detection, I chose LLM function calling over matching static keywords. While function calling adds slight latency and can occasionally trigger falsely, it handles natural language and paraphrasing much better than rigid rules.
And if a user says "my budget is 25k$ and I want to talk to Alice" a regex would not update the memory.

For state memory, I chose fast extraction in background using a smaller model over adding extraction to the main voice prompt. This keeps the voice response fast, even though the extraction might lag a second or two behind the live audio.

For context sharing between agents, I chose to pass the full chat history plus extracted state notes. This guarantees that nothing is lost and users don't have to repeat themselves. But, to stop the context from growing indefinitely, I added periodic summarization for long conversations.

For the agent swapping mechanism, I chose a single session where the active agent's profile is hot-swapped over maintaining two separate connections. This provides a perfectly seamless experience for the user with no audio drops.

## Next steps and Challenges that I faced, I have mentioned in @REFLECTIONS.md
