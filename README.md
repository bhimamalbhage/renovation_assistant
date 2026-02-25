# Renovation Assistant

The Renovation Assistant is a voice-based AI assistant for home renovation planning. It guides homeowners through the renovation process using two specialized agents that work together seamlessly:

- **Bob** — Your friendly intake agent who gathers information about your renovation goals, constraints, budget, timeline, and DIY preferences. He asks clarifying questions and creates an initial checklist and plan.
- **Alice** — Your technical specialist who handles detailed risk assessment, permit requirements, material specifications, cost breakdowns, trade-off analysis, and sequencing advice.

You can transfer between Bob and Alice at any time by voice command (e.g., "Transfer me to Alice" or "Go back to Bob"), and the conversation continues seamlessly with full context preserved.

## How the Voice Agents Work

The system uses **LiveKit Agents** with WebRTC for real-time voice communication:

- **Speech Recognition**: Deepgram nova-2 listens to your voice and converts it to text
- **Intelligence**: GPT-4o processes your request and generates a response
- **Voice Output**: OpenAI TTS reads the response back to you in natural speech
- **Seamless Transfers**: When you request an agent switch, the new agent instantly receives the full conversation history and continues without repetition

The frontend provides a visual interface showing:
- The active agent name (Bob or Alice)
- A real-time chat transcript of the conversation
- An animated orb indicating when the assistant is listening or speaking

## Setup Steps

1. Clone the repository and navigate to the project folder.
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Environment Variables

Create a `.env` file in the root directory and add your API keys. An example is provided in `.env.example`:

```env
# LiveKit server credentials (from LiveKit Cloud)
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=your_livekit_key
LIVEKIT_API_SECRET=your_livekit_secret

# Deepgram (STT)
DEEPGRAM_API_KEY=your_deepgram_key

# OpenAI (LLM + TTS)
OPENAI_API_KEY=sk-your_openai_key
```

## How to Run

You need to run two separate processes to start the application.

1. **Start the LiveKit Agent Worker:**
   Open a terminal, ensure your virtual environment is active, and run:
   ```bash
   python agent.py dev
   ```

2. **Start the Frontend Server:**
   Open a second terminal, ensure your virtual environment is active, and run:
   ```bash
   python frontend.py
   ```

3. Open your browser and go to http://localhost:8000. Click "Connect & Talk" to start the conversation!

## Demo Commands (Test Flow)

Here are the required test scenarios to verify the dynamic agent transferring and context sharing:

**Test 1 — Intake and planning (Bob)**
1. Start the app (Bob is active by default).
2. Say: *"Hi Bob, I want to remodel my kitchen. Budget is around $25k. I want new cabinets and countertops, and maybe open up a wall."*
3. Answer any clarifying questions Bob asks.

**Test 2 — Transfer to specialist (Alice)**
1. Say: *"Transfer me to Alice."*
2. Answer any clarifying questions Alice asks.

**Test 3 — Transfer back to Bob**
1. Say: *"Go back to Bob."*
2. Answer any clarifying questions Bob asks.
