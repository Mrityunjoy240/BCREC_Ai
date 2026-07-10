import asyncio
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from livekit import api


async def dispatch_to_room(room_name: str):
    # Get URL and keys from .env
    from dotenv import load_dotenv

    load_dotenv("backend/.env")

    url = os.getenv("LIVEKIT_URL", "wss://ai-voice-agent-64sbd6v0.livekit.cloud")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not api_key or not api_secret:
        print("❌ Error: LiveKit API Key or Secret not found in backend/.env")
        return

    # Use the correct 'agent_dispatch' attribute identified via inspection
    lkapi = api.LiveKitAPI(url, api_key, api_secret)

    try:
        print(f"🚀 Inviting agent to room: {room_name}...")

        # In this SDK version, it's .agent_dispatch.create_dispatch
        await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(room=room_name, agent_name="bcrec-agent")
        )
        print(f"✅ Success! The agent should appear in the Playground now.")
    except Exception as e:
        print(f"❌ Failed to dispatch: {e}")
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    room = sys.argv[1] if len(sys.argv) > 1 else "console-962f1ee3"
    asyncio.run(dispatch_to_room(room))
