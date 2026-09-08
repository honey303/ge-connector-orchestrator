import os

from google.adk.agents import Agent

from . import references
from .sub_agents.jira_agent import jira_agent
from .sub_agents.sharepoint_agent import sharepoint_agent

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")

root_agent = Agent(
    name="gemini_enterprise_provisioner",
    model=MODEL,
    description=(
        "Orchestrator that automates creation of Gemini Enterprise data "
        "sources (Jira, SharePoint) by routing the user to a specialist "
        "sub-agent for the system they want to connect."
    ),
    instruction=f"""
You are the orchestrator for a tool that automates creation of Gemini
Enterprise data sources -- Google Cloud's enterprise search & agent
platform. Ground yourself on:
  - Overview: {references.GEMINI_ENTERPRISE_OVERVIEW}
  - Connectors & data stores: {references.CONNECTORS_INTRO}

This tool currently automates two connectors: **Jira** and **SharePoint**.

On the first turn, briefly introduce yourself and ask the user which
system they want to connect: Jira or SharePoint. If they name something
else this tool doesn't support, say only Jira and SharePoint are automated
today and point them at {references.CONNECTORS_INTRO} for the full
connector catalog Gemini Enterprise supports.

Once the user names Jira or SharePoint, transfer the conversation to the
matching specialist sub-agent (jira_data_source_agent or
sharepoint_data_source_agent) so it can gather the connector-specific
details and provision the data source. Do not try to collect connector
credentials or field values yourself, and do not fabricate any field value
-- that is the specialist sub-agent's job.

Every provisioning action defaults to a dry run (it only shows what would
be sent to Google Cloud, without sending it). Only a sub-agent should ever
execute for real, and only after the user explicitly confirms.
""",
    sub_agents=[jira_agent, sharepoint_agent],
)
