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


async def send(runner: Runner, session_id: str, text: str) -> bool:
    """Send one user turn. Returns True if any agent text was printed.

    Prints text from every event, not just is_final_response() ones,
    because a turn that also makes a tool/transfer call can carry visible
    narration on a non-final event.
    """
    content = types.Content(role="user", parts=[types.Part(text=text)])
    printed = False
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=content
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"\nagent> {part.text}\n")
                    printed = True
    return printed


MAX_HANDOFF_HOPS = 3


async def turn(runner: Runner, session_id: str, text: str) -> None:
    """Send text, following silent hand-offs until an agent actually replies.

    ADK's transfer_to_agent ends a turn with no text at all (the framework
    tells the model not to say anything else when transferring), and the
    sub-agent it hands off to only starts responding on the *next*
    run_async call -- it doesn't continue automatically within the same
    one. So a turn that produced nothing usually just means control moved
    to a specialist sub-agent; re-sending the same message lets that
    sub-agent pick it up and reply, instead of the CLI looking stuck.
    """
    for _ in range(MAX_HANDOFF_HOPS):
        if await send(runner, session_id, text):
            return
    print(
        "\n[no reply after following a hand-off -- something may be "
        "misconfigured; try rephrasing or type 'exit']\n"
    )


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

    await turn(runner, session_id, "Hello.")

    while True:
        try:
            user_input = input("you> ").strip()
        except EOFError:
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break
        await turn(runner, session_id, user_input)


if __name__ == "__main__":
    asyncio.run(main())
