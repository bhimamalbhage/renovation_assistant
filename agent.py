import asyncio
import json
import logging
from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, function_tool, get_job_context
from livekit.agents.metrics import LLMMetrics, TTSMetrics, log_metrics
from livekit.plugins import deepgram, openai, silero

load_dotenv()

logger = logging.getLogger("renovation-agent")
logger.setLevel(logging.DEBUG)

BOB_INSTRUCTIONS = """You are Bob, a friendly renovation planning assistant. This is a voice conversation — keep every response to 2–3 sentences maximum.

When a homeowner describes their project, ask 1–3 short clarifying questions. Focus on: is any wall load-bearing, timeline, DIY vs contractor, appliance or layout changes.

Once you have enough context, give a short 3–5 item checklist of next steps (e.g. get measurements, gather contractor quotes, research permits, finalize design choices).

If the user asks to talk to Alice, or raises technical questions about structural work, permits, or trade sequencing, call transfer_to_alice immediately — do not try to answer those yourself.

TRANSFER RULE: When calling transfer_to_alice, call the tool immediately — do not speak any text before the tool call."""

BOB_RETURNING_INSTRUCTIONS = """You are Bob, a friendly renovation planning assistant. This is a voice conversation — keep every response to 2–3 sentences maximum.

You are resuming after Alice handled the technical details. IMPORTANT: Do not say 'Bob back — let me pull together your next steps.' or any similar greeting. The system automatically plays your return greeting before you speak.

Your FIRST response MUST be a short, homeowner-friendly "what to do this week" action list — 3–5 concrete items drawn from everything discussed. Keep it simple and jargon-free. Do NOT call transfer_to_alice in your first response under any circumstances.

For follow-up questions answer briefly. Only call transfer_to_alice if the user explicitly asks for Alice after you have given the list.

TRANSFER RULE: When calling transfer_to_alice, call the tool immediately — do not speak any text before the tool call."""

ALICE_INSTRUCTIONS = """You are Alice, a technical renovation specialist. This is a voice conversation — keep responses tight: 2–4 sentences or a short bulleted list of 3–5 items. No lengthy explanations.

You already have full context from the conversation — do NOT ask the user to repeat anything. IMPORTANT: DO NOT say 'Alice here — I've got the full picture.' or any similar greeting. The system automatically plays your greeting before you speak.

Your FIRST response MUST immediately address the most critical technical risk in the project. If wall removal was mentioned, cover these three things in order: (1) whether a structural or load-bearing check is needed, (2) permit requirements, (3) the correct trade sequencing. Do NOT call transfer_to_bob in your first response under any circumstances.

Be direct and specific. Flag risks clearly. Only call transfer_to_bob if the user explicitly asks to go back to Bob after you have given your analysis.

TRANSFER RULE: When calling transfer_to_bob, call the tool immediately — do not speak any text before the tool call."""

BOB_GREETING = (
    "Hi! I'm Bob, your renovation planning assistant. "
    "What project are you thinking of tackling?"
)

ALICE_GREETING_TRANSFER = "Alice here — I've got the full picture."

BOB_RETURNING_GREETING = "Bob back — let me pull together your next steps."


def _notify_frontend(agent_name: str):
    """Publish a data message so the frontend can update the active agent UI."""
    try:
        ctx = get_job_context()
        payload = json.dumps({"type": "agent_switch", "agent": agent_name}).encode()
        asyncio.ensure_future(
            ctx.room.local_participant.publish_data(payload, topic="agent.info")
        )
    except Exception as e:
        logger.warning(f"Could not notify frontend of agent switch: {e}")


class BobAgent(Agent):
    def __init__(self, returning=False, chat_ctx=None):
        instructions = BOB_RETURNING_INSTRUCTIONS if returning else BOB_INSTRUCTIONS
        super().__init__(instructions=instructions, chat_ctx=chat_ctx)
        self._returning = returning

    async def on_enter(self):
        _notify_frontend("bob")
        greeting = BOB_RETURNING_GREETING if self._returning else BOB_GREETING
        logger.info(f"BobAgent on_enter (returning={self._returning})")
        self.session.say(greeting)
        if self._returning:
            self.session.generate_reply()

    @function_tool
    async def transfer_to_alice(self):
        """Transfer the conversation to Alice, the technical renovation specialist.
        Use this when the user asks to talk to Alice or when questions are deeply technical
        (permits, structural, sequencing, risk, detailed costs)."""
        if getattr(self, "_returning", False):
            logger.info("Blocked premature transfer to Alice.")
            self._returning = False
            return "Error: Cannot transfer to Alice right now. You just returned and MUST give the homeowner-friendly action list first."

        logger.info("Transferring to Alice...")
        self.session.say("Let me bring Alice in for the technical side.")
        history = self.session.history.copy()
        alice = AliceAgent(chat_ctx=history)
        self.session.update_agent(alice)


class AliceAgent(Agent):
    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions=ALICE_INSTRUCTIONS,
            tts=openai.TTS(voice="shimmer"),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self):
        _notify_frontend("alice")
        logger.info("AliceAgent on_enter")
        self.session.say(ALICE_GREETING_TRANSFER)
        self.session.generate_reply()

    @function_tool
    async def transfer_to_bob(self):
        """Transfer the conversation back to Bob, the friendly renovation planner.
        Use this when the user asks to talk to Bob or wants a homeowner-friendly
        summary, next steps, or general planning help."""
        logger.info("Transferring back to Bob...")
        self.session.say("Let me hand you back to Bob.")
        history = self.session.history.copy()
        bob = BobAgent(returning=True, chat_ctx=history)
        self.session.update_agent(bob)


async def entrypoint(ctx: JobContext):
    logger.info("Entrypoint started, connecting to room...")
    await ctx.connect()
    logger.info("Connected, waiting for participant...")

    participant = await ctx.wait_for_participant()
    logger.info(f"Participant joined: {participant.identity}")

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-2"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(voice="alloy"),
    )

    @session.on("metrics_collected")
    def _on_metrics(ev):
        m = ev.metrics
        log_metrics(m, logger=logger)
        data = None
        if isinstance(m, LLMMetrics):
            data = {"type": "llm_metrics", "ttft": round(m.ttft * 1000)}
        elif isinstance(m, TTSMetrics):
            data = {"type": "tts_metrics", "ttfb": round(m.ttfb * 1000)}
        if data:
            asyncio.ensure_future(
                ctx.room.local_participant.publish_data(
                    json.dumps(data).encode(), topic="agent.metrics"
                )
            )

    await session.start(
        agent=BobAgent(),
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
