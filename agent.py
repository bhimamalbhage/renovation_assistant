import asyncio
import logging
from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import deepgram, openai, silero

load_dotenv()

logger = logging.getLogger("renovation-agent")
logger.setLevel(logging.DEBUG)

INSTRUCTIONS = """You are Bob, a friendly and knowledgeable renovation planning assistant.
You help homeowners plan their home renovation projects. You can assist with:

- Budgeting and cost estimation for different renovation types
- Prioritizing renovation projects based on ROI and urgency
- Suggesting materials, finishes, and design ideas
- Explaining renovation timelines and what to expect
- Recommending when to hire professionals vs. DIY
- Helping navigate permits and building codes at a high level
- Flagging common renovation mistakes to avoid

Keep your responses conversational, concise, and practical. Ask clarifying questions
to better understand the homeowner's needs, budget, and goals. Always be encouraging
but honest about challenges and costs."""

GREETING = (
    "Hi there! I'm Bob, your renovation planning assistant. "
    "What project are you thinking about tackling?"
)


class RenovationAgent(Agent):
    def __init__(self):
        super().__init__(instructions=INSTRUCTIONS)

    async def on_enter(self):
        logger.info("on_enter — dispatching greeting")
        self.session.say(GREETING)


async def entrypoint(ctx: JobContext):
    logger.info("Entrypoint started, connecting to room...")
    await ctx.connect()
    logger.info("Connected, waiting for participant...")

    participant = await ctx.wait_for_participant()
    logger.info(f"Participant joined: {participant.identity}")

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-2"),
        llm=openai.LLM(model="gpt-4o"),
        tts=openai.TTS(voice="alloy"),
    )

    await session.start(
        agent=RenovationAgent(),
        room=ctx.room,
    )
    logger.info("Session started")


def main():
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            num_idle_processes=1,
        )
    )


if __name__ == "__main__":
    main()
