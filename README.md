# Renovation Assistant


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
