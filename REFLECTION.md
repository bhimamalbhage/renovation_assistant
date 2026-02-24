# Reflection — Challenges & How I'd Improve

## Reducing voice latency 

1. For this assignment, I used deepgram over whisper for STT for latency purpose and for the whole voice pipeline too, I would measure each provider's metrics with latency, accuracy and make decision based on that. For Ex: Right now I used OpenAI for TTS but cartesia would further reduce latency. I would also evaluate whether moving TTS from a cloud provider (e.g., OpenAI or ElevenLabs) to a locally hosted engine such as Piper TTS meaningfully reduces end-to-end latency (as mentioned in recent 2026 benchmarks)

2. I would experiment if Parallel Orchestarion would help here, as LiveKit recently introduced a preemptive_generation flag. I would enable this so the LLM starts "thinking" about a response based on partial transcripts before the user even finishes their sentence.

3. To mask the remaining latency, I would implement Audio "Nodding" and Buffer: For Ex: While the LLM is generating a complex technical answer for Alice, the system can immediately play a pre-cached "filler" like "Hmm, let me look at the structural requirements for that..."

## Making transfers more reliable

Some of the challenges I faced or thought while testing - 

1. Intent Misclassification - LLMs often interpret general curiosity as a hard request for a transfer even if the user wanted to keep chatting with him. so given more time, I would solve this by better prompting or/and by transfer confidence scoring and structured reasons.

2. I added transfer guardrail such as minimum engagement turns, cooldown windows, and transfer logging but couldn't test it all and transfer intent still ultimately depends on the LLM invoking a tool, which makes it probabilistic rather than policy-driven. So Given more time, I would introduce a hybrid routing layer.

## Conversational Memory

1. One challenge is my current background async approach to extract information might enter race condition or the extraction task might not have finished yet when next agent starts talking so to solve this I would add buffer or audio nodding till agent gets the extracted information.

2. Right now both agents share state through a simple dataclass inside LiveKit's session, which works fine for two agents. But if we add more agents (like a Budget Estimator), the hand-written transfer logic between every pair of agents gets messy fast. LangGraph would let us define agents as nodes in a graph with shared state flowing between them, plus it gives us free state persistence so users can resume conversations across sessions. 

3. I would use the LLM's structured output mode (JSON schema) instead of parsing free-form text, which would make extraction more reliable. 

4. For very long sessions, I'd store state externally so users could come back days later and resume.

## Interruptions and Real-Time Dialogue

I used Silero VAD to handle the interruptions but given more time, I would test its edge cases and also learn about Semantic Turn Detection.

## UX and Observability

With more time I'd add structured logging with OpenTelemetry traces spanning the full VAD → STT → LLM → TTS pipeline, so we can see exactly where time is spent. I would also track metrics such as p50 and p95 end-to-end response latency, transfer success and misclassification rates.
