"""Interactive CLI for the Gemini Enterprise data-source provisioning agent.

Usage:
    export GOOGLE_API_KEY=...   # or configure Vertex AI application-default credentials
    python cli.py

Chat with the orchestrator; it will ask which system to connect (Jira or
SharePoint) and hand off to the matching specialist sub-agent. All
provisioning defaults to a dry run -- it prints the request that would be
sent to Google Cloud without sending it. Type 'exit' or press Ctrl-D to quit.
"""

import asyncio
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from provisioner.agent import root_agent

APP_NAME = "gemini_enterprise_provisioner"
USER_ID = "local-dev"


async def send(runner: Runner, session_id: str, text: str) -> None:
    content = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            reply = event.content.parts[0].text
            if reply:
                print(f"\nagent> {reply}\n")


async def main() -> None:
    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )

    print(
        "Gemini Enterprise data-source provisioning agent\n"
        "(dry run by default -- nothing is created against real GCP "
        "infrastructure unless you explicitly confirm).\n"
        "Type 'exit' to quit.\n"
    )

    await send(runner, session_id, "Hello.")

    while True:
        try:
            turn = input("you> ").strip()
        except EOFError:
            break
        if not turn:
            continue
        if turn.lower() in {"exit", "quit"}:
            break
        await send(runner, session_id, turn)


if __name__ == "__main__":
    asyncio.run(main())
