"""
Frontend for the Renovation Assistant (Bob).
Serves a split voice + chat transcript UI and generates LiveKit tokens.

Run:
    python frontend.py
Then open http://localhost:8000 in your browser.
"""

import os
import uuid
import json
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from livekit.api import AccessToken, VideoGrants

load_dotenv()

LIVEKIT_URL = os.environ["LIVEKIT_URL"]
LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
ROOM_PREFIX = "renovation-room"
PORT = 8000

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Renovation Assistant</title>
  <script src="https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    html, body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      height: 100%;
      overflow: hidden;
    }}

    /* ── Shell ────────────────────────────────── */
    .shell {{
      display: flex;
      width: 100vw;
      height: 100vh;
      background: white;
      overflow: hidden;
    }}

    /* ── Left: Voice Panel ───────────────────── */
    .voice-panel {{
      width: 280px;
      flex-shrink: 0;
      background: linear-gradient(160deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 32px 24px;
      gap: 20px;
    }}

    .avatar-ring {{
      width: 72px; height: 72px;
      border-radius: 50%;
      background: linear-gradient(135deg, #667eea, #764ba2);
      box-shadow: 0 0 0 4px rgba(102,126,234,0.3);
    }}

    .agent-name {{
      color: white;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0.5px;
    }}
    .agent-sub {{
      color: rgba(255,255,255,0.5);
      font-size: 12px;
      text-align: center;
      line-height: 1.4;
    }}

    /* Orb */
    .orb-wrap {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
    }}
    .orb {{
      width: 72px; height: 72px;
      border-radius: 50%;
      background: rgba(255,255,255,0.08);
      transition: background 0.3s ease, box-shadow 0.3s ease;
    }}
    .orb.bob-speaking {{
      background: radial-gradient(circle at 35% 35%, #a78bfa, #7c3aed);
      box-shadow: 0 0 24px 6px rgba(124,58,237,0.55);
      animation: pulse 0.9s ease-in-out infinite;
    }}
    .orb.user-speaking {{
      background: radial-gradient(circle at 35% 35%, #34d399, #059669);
      box-shadow: 0 0 24px 6px rgba(5,150,105,0.5);
      animation: pulse 0.5s ease-in-out infinite;
    }}
    .orb.alice-speaking {{
      background: radial-gradient(circle at 35% 35%, #67e8f9, #0891b2);
      box-shadow: 0 0 24px 6px rgba(8,145,178,0.55);
      animation: pulse 0.9s ease-in-out infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ transform: scale(1);    opacity: 1; }}
      50%        {{ transform: scale(1.1); opacity: 0.8; }}
    }}

    .orb-label {{
      font-size: 12px;
      color: rgba(255,255,255,0.45);
      letter-spacing: 0.3px;
      min-height: 16px;
      text-align: center;
    }}

    /* Connect button */
    .connect-btn {{
      width: 100%;
      padding: 12px;
      border: none;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.2s, transform 0.1s;
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: white;
      letter-spacing: 0.3px;
    }}
    .connect-btn:hover:not(:disabled) {{ opacity: 0.88; transform: translateY(-1px); }}
    .connect-btn:disabled {{ opacity: 0.5; cursor: default; }}
    .connect-btn.end {{ background: linear-gradient(135deg, #f87171, #dc2626); }}

    /* ── Right: Chat Panel ───────────────────── */
    .chat-panel {{
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}

    .chat-header {{
      padding: 18px 24px 14px;
      border-bottom: 1px solid #f0f0f0;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .chat-header-dot {{
      width: 8px; height: 8px;
      border-radius: 50%;
      background: #d1d5db;
      transition: background 0.3s;
    }}
    .chat-header-dot.live {{ background: #22c55e; box-shadow: 0 0 6px #22c55e; }}
    .chat-header-title {{
      font-size: 15px;
      font-weight: 600;
      color: #111;
    }}
    .chat-header-sub {{
      font-size: 12px;
      color: #9ca3af;
      margin-left: auto;
    }}

    .messages {{
      flex: 1;
      overflow-y: auto;
      padding: 20px 24px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      scroll-behavior: smooth;
    }}

    .empty-state {{
      margin: auto;
      text-align: center;
      color: #d1d5db;
    }}
    .empty-state .icon {{ font-size: 40px; margin-bottom: 10px; }}
    .empty-state p {{ font-size: 14px; }}

    /* Message bubbles */
    .msg {{
      display: flex;
      gap: 10px;
      max-width: 82%;
      animation: fadeUp 0.2s ease;
    }}
    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(6px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}

    .msg.bob, .msg.alice {{ align-self: flex-start; }}
    .msg.user {{
      align-self: flex-end;
      flex-direction: row-reverse;
    }}

    .msg-icon {{
      width: 3px;
      border-radius: 4px;
      flex-shrink: 0;
      align-self: stretch;
      margin-top: 2px;
    }}
    .msg.bob   .msg-icon {{ background: #667eea; }}
    .msg.alice .msg-icon {{ background: #0891b2; }}
    .msg.user  .msg-icon {{ background: #059669; }}

    .msg-body {{ display: flex; flex-direction: column; gap: 3px; }}
    .msg-sender {{
      font-size: 11px;
      font-weight: 600;
      color: #9ca3af;
      letter-spacing: 0.4px;
      text-transform: uppercase;
    }}
    .msg.user .msg-sender {{ text-align: right; }}

    .bubble {{
      padding: 10px 14px;
      border-radius: 16px;
      font-size: 14px;
      line-height: 1.55;
      color: #1f2937;
      background: #f3f4f6;
      word-break: break-word;
    }}
    .msg.bob   .bubble {{ border-top-left-radius: 4px; background: #f3f4f6; }}
    .msg.alice .bubble {{ border-top-left-radius: 4px; background: #ecfeff; color: #164e63; }}
    .msg.user  .bubble {{ border-top-right-radius: 4px; background: #ede9fe; color: #4c1d95; }}

    .bubble.interim {{
      opacity: 0.55;
      font-style: italic;
    }}

    /* Typing dots shown while Bob is "thinking" */
    .typing-dots span {{
      display: inline-block;
      width: 6px; height: 6px;
      border-radius: 50%;
      background: #9ca3af;
      margin: 0 2px;
      animation: dot 1.2s ease-in-out infinite;
    }}
    .typing-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
    .typing-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
    @keyframes dot {{
      0%, 80%, 100% {{ transform: scale(0.7); opacity: 0.4; }}
      40%            {{ transform: scale(1);   opacity: 1; }}
    }}

    /* Scrollbar */
    .messages::-webkit-scrollbar {{ width: 4px; }}
    .messages::-webkit-scrollbar-track {{ background: transparent; }}
    .messages::-webkit-scrollbar-thumb {{ background: #e5e7eb; border-radius: 4px; }}
  </style>
</head>
<body>
<div class="shell">

  <!-- ── Voice panel ── -->
  <div class="voice-panel">
    <div class="avatar-ring"></div>
    <div>
      <div class="agent-name">Bob</div>
    </div>
    <p class="agent-sub">Renovation Planning<br>Assistant</p>

    <div class="orb-wrap">
      <div class="orb" id="orb"></div>
      <div class="orb-label" id="orbLabel">—</div>
    </div>

    <button class="connect-btn" id="connectBtn" onclick="toggle()">
      Connect &amp; Talk
    </button>
  </div>

  <!-- ── Chat panel ── -->
  <div class="chat-panel">
    <div class="chat-header">
      <div class="chat-header-dot" id="liveDot"></div>
      <span class="chat-header-title">Conversation</span>
      <span class="chat-header-sub" id="chatSub">Not connected</span>
    </div>
    <div class="messages" id="messages">
      <div class="empty-state" id="emptyState">
        <div class="icon">💬</div>
        <p>Connect to start your renovation chat</p>
      </div>
    </div>
  </div>
</div>

<script>
const LIVEKIT_URL = "{LIVEKIT_URL}";
let room = null;
let currentAgent = "bob";
// Map: segmentId -> {{ role, bubbleEl }}
const segments = new Map();

const AGENT_CONFIG = {{
  bob:   {{ name: "Bob",   sub: "Renovation Planning<br>Assistant",
            gradient: "linear-gradient(135deg, #667eea, #764ba2)",
            shadow: "0 0 0 4px rgba(102,126,234,0.3)",
            speakClass: "bob-speaking", speakLabel: "Bob is speaking",
            listenLabel: "Bob is listening" }},
  alice: {{ name: "Alice", sub: "Technical Specialist<br>& Risk Advisor",
            gradient: "linear-gradient(135deg, #67e8f9, #0891b2)",
            shadow: "0 0 0 4px rgba(8,145,178,0.3)",
            speakClass: "alice-speaking", speakLabel: "Alice is speaking",
            listenLabel: "Alice is listening" }}
}};

function updateAgentUI(agent) {{
  const cfg = AGENT_CONFIG[agent];
  if (!cfg) return;
  document.querySelector(".agent-name").textContent = cfg.name;
  document.querySelector(".agent-sub").innerHTML = cfg.sub;
  document.querySelector(".avatar-ring").style.background = cfg.gradient;
  document.querySelector(".avatar-ring").style.boxShadow = cfg.shadow;
  // Update orb label if connected
  if (room) setOrb("", cfg.listenLabel);
}}

/* ── Helpers ── */
function $(id) {{ return document.getElementById(id); }}

function setOrb(state, label) {{
  $("orb").className = "orb" + (state ? " " + state : "");
  $("orbLabel").textContent = label || "—";
}}

function setChatSub(text) {{ $("chatSub").textContent = text; }}

function scrollBottom() {{
  const m = $("messages");
  m.scrollTop = m.scrollHeight;
}}

/* ── Message rendering ── */
function hideEmpty() {{
  const e = $("emptyState");
  if (e) e.remove();
}}

function addOrUpdateSegment(segId, role, text, isFinal) {{
  if (segments.has(segId)) {{
    const {{ bubbleEl }} = segments.get(segId);
    bubbleEl.textContent = text;
    if (isFinal) bubbleEl.classList.remove("interim");
    return;
  }}

  hideEmpty();
  const isUser = role === "user";
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;

  const icon = document.createElement("div");
  icon.className = "msg-icon";

  const body = document.createElement("div");
  body.className = "msg-body";

  const sender = document.createElement("div");
  sender.className = "msg-sender";
  sender.textContent = isUser ? "You" : AGENT_CONFIG[role]?.name || role;

  const bubble = document.createElement("div");
  bubble.className = "bubble" + (isFinal ? "" : " interim");
  bubble.textContent = text;

  body.appendChild(sender);
  body.appendChild(bubble);
  wrap.appendChild(icon);
  wrap.appendChild(body);
  $("messages").appendChild(wrap);

  segments.set(segId, {{ role, bubbleEl: bubble }});
  scrollBottom();
}}

/* ── Connect / Disconnect ── */
async function toggle() {{
  if (room) {{ await disconnect(); }} else {{ await connect(); }}
}}

async function connect() {{
  const btn = $("connectBtn");
  btn.disabled = true;
  setOrb("", "Connecting…");
  setChatSub("Connecting…");

  try {{
    const res  = await fetch("/token");
    const {{ token }} = await res.json();

    room = new LivekitClient.Room({{ adaptiveStream: true, dynacast: true }});

    /* Agent audio → attach to page */
    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {{
      if (track.kind === "audio") track.attach();
    }});
    room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {{
      track.detach();
    }});

    /* Speaking detection → orb state */
    room.on(LivekitClient.RoomEvent.ActiveSpeakersChanged, (speakers) => {{
      const ids = speakers.map(s => s.identity);
      const localId = room.localParticipant.identity;
      const cfg = AGENT_CONFIG[currentAgent];
      const agentSpeaking = ids.some(id => id !== localId);
      const userSpeaking  = ids.includes(localId);

      if (agentSpeaking)     {{ setOrb(cfg.speakClass,  cfg.speakLabel); }}
      else if (userSpeaking) {{ setOrb("user-speaking", "Listening…");   }}
      else                   {{ setOrb("",              cfg.listenLabel); }}
    }});

    /* Agent switch data messages */
    room.on(LivekitClient.RoomEvent.DataReceived, (payload, participant, kind, topic) => {{
      if (topic !== "agent.info") return;
      try {{
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg.type === "agent_switch" && AGENT_CONFIG[msg.agent]) {{
          currentAgent = msg.agent;
          updateAgentUI(currentAgent);
        }}
      }} catch(e) {{ console.warn("Bad agent data message", e); }}
    }});

    /* Transcriptions → chat bubbles */
    room.on(LivekitClient.RoomEvent.TranscriptionReceived, (segs, participant) => {{
      const isUser = participant && participant.identity === room.localParticipant.identity;
      const role   = isUser ? "user" : currentAgent;
      for (const seg of segs) {{
        if (seg.text.trim()) addOrUpdateSegment(seg.id, role, seg.text, seg.final);
      }}
    }});

    /* Disconnect */
    room.on(LivekitClient.RoomEvent.Disconnected, () => {{
      room = null;
      currentAgent = "bob";
      setOrb("", "—");
      setChatSub("Disconnected");
      $("liveDot").classList.remove("live");
      updateAgentUI("bob");
      btn.textContent = "Connect & Talk";
      btn.classList.remove("end");
      btn.disabled = false;
    }});

    await room.connect(LIVEKIT_URL, token);
    await room.localParticipant.setMicrophoneEnabled(true);

    setOrb("", AGENT_CONFIG[currentAgent].listenLabel);
    setChatSub("Live");
    $("liveDot").classList.add("live");
    btn.textContent = "End Conversation";
    btn.classList.add("end");
    btn.disabled = false;

  }} catch (e) {{
    setOrb("", "Error");
    setChatSub("Error: " + e.message);
    btn.disabled = false;
    room = null;
  }}
}}

async function disconnect() {{
  if (room) await room.disconnect();
}}
</script>
</body>
</html>
"""


def make_token(identity: str, room_name: str) -> str:
    return (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name("Homeowner")
        .with_grants(VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} – {fmt % args}")

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/token":
            identity = f"user-{uuid.uuid4().hex[:6]}"
            room_name = f"{ROOM_PREFIX}-{uuid.uuid4().hex[:8]}"
            token = make_token(identity, room_name)
            body = json.dumps({"token": token, "room": room_name}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Frontend running → http://localhost:{PORT}")
    print(f"Room prefix: {ROOM_PREFIX} (unique room per session)")
    print("(Make sure `python agent.py dev` is also running)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
