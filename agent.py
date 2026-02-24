import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, function_tool, get_job_context
from livekit.agents.llm import ChatContext
from livekit.agents.metrics import LLMMetrics, TTSMetrics, log_metrics
from livekit.plugins import deepgram, openai, silero

load_dotenv()

logger = logging.getLogger("renovation-agent")
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Structured State
# ---------------------------------------------------------------------------

TRANSFER_COOLDOWN_SECONDS = 10
MIN_BOB_TURNS_BEFORE_TRANSFER = 1
MIN_ALICE_TURNS_BEFORE_TRANSFER = 1
SUMMARIZE_THRESHOLD = 20
KEEP_RECENT_MESSAGES = 15


@dataclass
class TransferRecord:
    timestamp: float
    from_agent: str
    to_agent: str
    reason: str
    turn_count: int


@dataclass
class RenovationState:
    rooms: list[str] = field(default_factory=list)
    budget: str | None = None
    scope: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    timeline: str | None = None
    diy_vs_contractor: str | None = None
    identified_risks: list[str] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    # Transfer tracking
    transfer_history: list[TransferRecord] = field(default_factory=list)
    last_transfer_time: float = 0.0
    bob_turn_count: int = 0
    alice_turn_count: int = 0
    last_handoff_summary: str = ""

    def to_summary(self) -> str:
        """Format state as readable text for injection into agent instructions."""
        lines = []
        if self.rooms:
            lines.append(f"Rooms: {', '.join(self.rooms)}")
        if self.budget:
            lines.append(f"Budget: {self.budget}")
        if self.scope:
            lines.append(f"Scope: {', '.join(self.scope)}")
        if self.constraints:
            lines.append(f"Constraints: {', '.join(self.constraints)}")
        if self.timeline:
            lines.append(f"Timeline: {self.timeline}")
        if self.diy_vs_contractor:
            lines.append(f"DIY vs Contractor: {self.diy_vs_contractor}")
        if self.identified_risks:
            lines.append(f"Risks: {', '.join(self.identified_risks)}")
        if self.decisions_made:
            lines.append(f"Decisions: {', '.join(self.decisions_made)}")
        if self.open_questions:
            lines.append(f"Open questions: {', '.join(self.open_questions)}")
        return "\n".join(lines) if lines else "No project details extracted yet."


# ---------------------------------------------------------------------------
# Background State Extraction (gpt-4o-mini, non-blocking)
# ---------------------------------------------------------------------------

_extraction_llm = openai.LLM(model="gpt-4o-mini")

EXTRACTION_PROMPT = """Extract renovation project details from this user message.
Return JSON with only fields that are explicitly mentioned:
{{"rooms": [...], "budget": "...", "scope": [...], "constraints": [...],
  "timeline": "...", "diy_or_contractor": "...", "risks": [...], "decisions": [...],
  "open_questions": [...]}}
Only include fields present in the text. Return {{}} if nothing relevant.

User said: "{user_text}"
"""


async def _extract_state_from_turn(session: AgentSession, user_text: str):
    """Background LLM extraction — runs off the voice-critical path."""
    state: RenovationState = session.userdata
    try:
        chat_ctx = ChatContext()
        chat_ctx.add_message(role="user", content=EXTRACTION_PROMPT.format(user_text=user_text))
        stream = _extraction_llm.chat(chat_ctx=chat_ctx)
        response = await stream.collect()
        raw = response.text
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)

        # Merge additively — never overwrite with empty
        if data.get("rooms"):
            for r in data["rooms"]:
                if r and r.lower() not in [x.lower() for x in state.rooms]:
                    state.rooms.append(r)
        if data.get("budget"):
            state.budget = data["budget"]
        if data.get("scope"):
            for s in data["scope"]:
                if s and s.lower() not in [x.lower() for x in state.scope]:
                    state.scope.append(s)
        if data.get("constraints"):
            for c in data["constraints"]:
                if c and c.lower() not in [x.lower() for x in state.constraints]:
                    state.constraints.append(c)
        if data.get("timeline"):
            state.timeline = data["timeline"]
        if data.get("diy_or_contractor"):
            state.diy_vs_contractor = data["diy_or_contractor"]
        if data.get("risks"):
            for r in data["risks"]:
                if r and r.lower() not in [x.lower() for x in state.identified_risks]:
                    state.identified_risks.append(r)
        if data.get("decisions"):
            for d in data["decisions"]:
                if d and d.lower() not in [x.lower() for x in state.decisions_made]:
                    state.decisions_made.append(d)
        if data.get("open_questions"):
            for q in data["open_questions"]:
                if q and q.lower() not in [x.lower() for x in state.open_questions]:
                    state.open_questions.append(q)

        logger.info(f"State extraction complete: {state.to_summary()}")
    except Exception as e:
        logger.warning(f"State extraction failed (non-critical): {e}")


# ---------------------------------------------------------------------------
# Transfer Guardrails
# ---------------------------------------------------------------------------

class TransferGuard:
    """Validates whether a transfer should proceed."""

    @staticmethod
    def check_transfer(state: RenovationState, from_agent: str, to_agent: str) -> str | None:
        """Returns an error message string if transfer should be blocked, None if OK."""
        # Cooldown check
        elapsed = time.time() - state.last_transfer_time
        if state.last_transfer_time > 0 and elapsed < TRANSFER_COOLDOWN_SECONDS:
            remaining = int(TRANSFER_COOLDOWN_SECONDS - elapsed)
            logger.info(f"Transfer blocked: cooldown ({remaining}s remaining)")
            return (
                f"Error: Transfer cooldown active ({remaining}s remaining). "
                "Continue the current conversation naturally."
            )

        # Readiness checks
        if from_agent == "bob" and state.bob_turn_count < MIN_BOB_TURNS_BEFORE_TRANSFER:
            logger.info("Transfer blocked: Bob hasn't engaged enough yet")
            return (
                "Error: You need to engage with the homeowner first. "
                "Ask at least one clarifying question before transferring."
            )

        if from_agent == "alice" and state.alice_turn_count < MIN_ALICE_TURNS_BEFORE_TRANSFER:
            logger.info("Transfer blocked: Alice hasn't addressed technical points yet")
            return (
                "Error: You need to address at least one technical point "
                "before transferring back to Bob."
            )

        return None

    @staticmethod
    def record_transfer(state: RenovationState, from_agent: str, to_agent: str, reason: str):
        """Log the transfer event."""
        turn_count = state.bob_turn_count if from_agent == "bob" else state.alice_turn_count
        record = TransferRecord(
            timestamp=time.time(),
            from_agent=from_agent,
            to_agent=to_agent,
            reason=reason,
            turn_count=turn_count,
        )
        state.transfer_history.append(record)
        state.last_transfer_time = time.time()
        logger.info(
            f"Transfer recorded: {from_agent} → {to_agent} "
            f"(reason={reason}, turns={turn_count}, total_transfers={len(state.transfer_history)})"
        )


# ---------------------------------------------------------------------------
# Handoff Summary Generation
# ---------------------------------------------------------------------------

_summary_llm = openai.LLM(model="gpt-4o-mini")


async def _generate_handoff_summary(
    session: AgentSession, from_agent: str, to_agent: str
) -> str:
    """Generate a concise handoff summary for the receiving agent."""
    state: RenovationState = session.userdata
    messages = session.history.items
    # Build a condensed version of recent conversation
    recent_turns = []
    for msg in messages[-10:]:
        role = msg.role if hasattr(msg, "role") else "unknown"
        text = msg.text_content if hasattr(msg, "text_content") else str(msg)
        if text:
            recent_turns.append(f"{role}: {text}")

    conversation_snippet = "\n".join(recent_turns)
    project_state = state.to_summary()

    prompt = f"""Summarize this renovation conversation for handoff from {from_agent} to {to_agent}.
Write 2-3 bullet points covering: what was discussed, key decisions, and what {to_agent} should focus on next.
Be concise — this goes into agent instructions.

Project state:
{project_state}

Recent conversation:
{conversation_snippet}
"""
    try:
        chat_ctx = ChatContext()
        chat_ctx.add_message(role="user", content=prompt)
        stream = _summary_llm.chat(chat_ctx=chat_ctx)
        response = await stream.collect()
        summary = response.text.strip()
        state.last_handoff_summary = summary
        logger.info(f"Handoff summary generated: {summary[:100]}...")
        return summary
    except Exception as e:
        logger.warning(f"Handoff summary generation failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Conversation History Summarization (for long sessions)
# ---------------------------------------------------------------------------

async def _maybe_summarize_history(session: AgentSession) -> ChatContext:
    """If conversation is long, summarize older messages and keep recent ones verbatim."""
    history = session.history.copy()
    messages = history.items
    if len(messages) <= SUMMARIZE_THRESHOLD:
        return history

    older = messages[:-KEEP_RECENT_MESSAGES]
    recent = messages[-KEEP_RECENT_MESSAGES:]

    # Build text of older messages for summarization
    older_text_parts = []
    for msg in older:
        role = msg.role if hasattr(msg, "role") else "unknown"
        text = msg.text_content if hasattr(msg, "text_content") else str(msg)
        if text:
            older_text_parts.append(f"{role}: {text}")

    if not older_text_parts:
        return history

    older_text = "\n".join(older_text_parts)

    try:
        prompt_ctx = ChatContext()
        prompt_ctx.add_message(
            role="user",
            content=(
                "Summarize this renovation conversation in 5-8 bullet points. "
                "Preserve all specific numbers, measurements, room names, and decisions.\n\n"
                f"{older_text}"
            ),
        )
        stream = _summary_llm.chat(chat_ctx=prompt_ctx)
        response = await stream.collect()
        summary_text = response.text.strip()

        # Build new ChatContext: summary message + recent messages
        summarized = ChatContext()
        summarized.add_message(role="assistant", content=f"[Conversation summary]\n{summary_text}")
        for msg in recent:
            summarized.add_message(
                role=msg.role,
                content=msg.text_content or "",
            )
        logger.info(f"History summarized: {len(messages)} msgs → 1 summary + {len(recent)} recent")
        return summarized
    except Exception as e:
        logger.warning(f"History summarization failed, using full history: {e}")
        return history


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Frontend Notification
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class BobAgent(Agent):
    def __init__(self, returning=False, chat_ctx=None, instructions_override=None):
        if instructions_override:
            instructions = instructions_override
        else:
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

    async def on_user_turn_completed(self, turn_ctx, new_message):
        state: RenovationState = self.session.userdata
        state.bob_turn_count += 1
        text = new_message.text_content if hasattr(new_message, "text_content") else str(new_message)
        if text:
            asyncio.create_task(_extract_state_from_turn(self.session, text))

    @function_tool
    async def transfer_to_alice(self):
        """Transfer the conversation to Alice, the technical renovation specialist.
        Use this when the user asks to talk to Alice or when questions are deeply technical
        (permits, structural, sequencing, risk, detailed costs)."""
        state: RenovationState = self.session.userdata

        # Existing returning guard
        if getattr(self, "_returning", False):
            logger.info("Blocked premature transfer to Alice (returning).")
            self._returning = False
            return "Error: Cannot transfer to Alice right now. You just returned and MUST give the homeowner-friendly action list first."

        # Transfer guardrails
        block_reason = TransferGuard.check_transfer(state, "bob", "alice")
        if block_reason:
            return block_reason

        logger.info("Transferring to Alice...")
        self.session.say("Let me bring Alice in for the technical side.")

        try:
            # Generate handoff summary concurrently with greeting TTS
            summary = await _generate_handoff_summary(self.session, "Bob", "Alice")
            history = await _maybe_summarize_history(self.session)

            # Build enriched instructions
            enriched = ALICE_INSTRUCTIONS
            if summary:
                enriched += f"\n\n## Handoff Notes from Bob\n{summary}"
            project_state = state.to_summary()
            if project_state != "No project details extracted yet.":
                enriched += f"\n\n## Current Project State\n{project_state}"

            TransferGuard.record_transfer(state, "bob", "alice", "user_request_or_technical")
            # Reset Alice turn count for new Alice session
            state.alice_turn_count = 0

            alice = AliceAgent(chat_ctx=history, instructions_override=enriched)
            self.session.update_agent(alice)
        except Exception as e:
            logger.error(f"Transfer to Alice failed: {e}")
            return "Sorry, I couldn't bring Alice in right now. Let me try to help you with that technical question instead."


class AliceAgent(Agent):
    def __init__(self, chat_ctx=None, instructions_override=None):
        instructions = instructions_override or ALICE_INSTRUCTIONS
        super().__init__(
            instructions=instructions,
            tts=openai.TTS(voice="shimmer"),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self):
        _notify_frontend("alice")
        logger.info("AliceAgent on_enter")
        self.session.say(ALICE_GREETING_TRANSFER)
        self.session.generate_reply()

    async def on_user_turn_completed(self, turn_ctx, new_message):
        state: RenovationState = self.session.userdata
        state.alice_turn_count += 1
        text = new_message.text_content if hasattr(new_message, "text_content") else str(new_message)
        if text:
            asyncio.create_task(_extract_state_from_turn(self.session, text))

    @function_tool
    async def transfer_to_bob(self):
        """Transfer the conversation back to Bob, the friendly renovation planner.
        Use this when the user asks to talk to Bob or wants a homeowner-friendly
        summary, next steps, or general planning help."""
        state: RenovationState = self.session.userdata

        # Transfer guardrails
        block_reason = TransferGuard.check_transfer(state, "alice", "bob")
        if block_reason:
            return block_reason

        logger.info("Transferring back to Bob...")
        self.session.say("Let me hand you back to Bob.")

        try:
            summary = await _generate_handoff_summary(self.session, "Alice", "Bob")
            history = await _maybe_summarize_history(self.session)

            enriched = BOB_RETURNING_INSTRUCTIONS
            if summary:
                enriched += f"\n\n## Handoff Notes from Alice\n{summary}"
            project_state = state.to_summary()
            if project_state != "No project details extracted yet.":
                enriched += f"\n\n## Current Project State\n{project_state}"

            TransferGuard.record_transfer(state, "alice", "bob", "user_request_or_summary")
            # Reset Bob turn count for new Bob session
            state.bob_turn_count = 0

            bob = BobAgent(returning=True, chat_ctx=history, instructions_override=enriched)
            self.session.update_agent(bob)
        except Exception as e:
            logger.error(f"Transfer to Bob failed: {e}")
            return "Sorry, I couldn't bring Bob back right now. I'll continue helping you — what else would you like to know?"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

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
        userdata=RenovationState(),
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
