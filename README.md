# Gemini Enterprise Data Source Provisioning Agent

A CLI [Agent Development Kit (ADK)](https://google.github.io/adk-docs/)
application that automates creation of [Gemini Enterprise](https://docs.cloud.google.com/gemini/enterprise/docs)
data sources for **Jira** and **SharePoint**, built as an orchestrator with
specialist sub-agents rather than one monolithic agent.

## Architecture

```
                     ┌───────────────────────────┐
      user  ───────► │  gemini_enterprise_        │
                      │  provisioner (orchestrator)│
                      │  - asks: Jira or SharePoint│
                      └──────────┬────────────────┘
                                 │ delegates (sub_agents)
                 ┌───────────────┴────────────────┐
                 ▼                                 ▼
     ┌───────────────────────┐         ┌────────────────────────────┐
     │ jira_data_source_agent │         │ sharepoint_data_source_agent│
     │ - collects Jira fields │         │ - collects SharePoint fields│
     │ - validate_gcp_target  │         │ - validate_gcp_target       │
     │ - create_jira_data_    │         │ - create_sharepoint_data_   │
     │   source (dry-run      │         │   source (dry-run default)  │
     │   default)             │         │                              │
     └───────────────────────┘         └────────────────────────────┘
```

- **Orchestrator** (`provisioner/agent.py`): the single entry point. It asks
  the user which system to connect and routes (`sub_agents=[...]`) to the
  matching specialist -- it never collects credentials or builds requests
  itself.
- **`jira_data_source_agent`** (`provisioner/sub_agents/jira_agent.py`):
  conversationally collects Jira connection details. Jira Cloud and Jira
  Data Center authenticate completely differently, so they diverge:
  - **Jira Cloud** uses an OAuth 2.0 ("3LO") app from the Atlassian
    Developer Console (Client ID/secret). `verify_jira_cloud_oauth` in
    `provisioner/tools/jira_tools.py` runs the actual interactive consent
    flow -- it prints an authorization URL, waits for the browser redirect
    on a local listener, exchanges the code for a token, and calls
    Atlassian's `accessible-resources` endpoint to confirm it worked and
    discover the site's instance ID/URI -- before asking for the
    remaining fields.
  - **Jira Data Center** fields (site URL + email + API token) are an
    unverified placeholder pending confirmation against the official
    docs; there is no verification tool for it yet.
- **`sharepoint_data_source_agent`** (`provisioner/sub_agents/sharepoint_agent.py`):
  conversationally collects SharePoint Online connection details, then calls
  tools in `provisioner/tools/sharepoint_tools.py`.
- **Shared tool** `provisioner/tools/gcp_context.py`: validates the target
  GCP project id and Gemini Enterprise location before either connector
  tries to provision anything.

Both connector tools build a request for the Discovery Engine
[`projects.locations:setUpDataConnector`](https://docs.cloud.google.com/gemini/enterprise/docs/reference/rest/v1/projects.locations/setUpDataConnector)
RPC, which creates a Collection and a [DataConnector](https://docs.cloud.google.com/generative-ai-app-builder/docs/reference/rest/v1/DataConnector)
under it in one call.

## Grounding

Field names, required IAM role, and prerequisites are grounded on the
official Google Cloud docs, collected in `provisioner/references.py`:

- [Gemini Enterprise overview](https://docs.cloud.google.com/gemini/enterprise/docs)
- [Introduction to connectors and data stores](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/introduction-to-connectors-and-data-stores)
- [Set up a Jira Cloud data store](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/jira-cloud/set-up-data-store)
- [Set up a Jira Data Center data store](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/jira-dc/set-up-data-store)
- [Set up a Microsoft SharePoint data store](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/ms-sharepoint/set-up-data-store)
- [Connect Microsoft SharePoint Online with data ingestion](https://cloud.google.com/gemini/enterprise/docs/connect-sharepoint-online-ingestion)
- [Connect Microsoft Entra ID](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/entra-id/connect-entra-id) (prerequisite for SharePoint)
- [DataConnector REST reference](https://docs.cloud.google.com/generative-ai-app-builder/docs/reference/rest/v1/DataConnector)

Both connectors require the `roles/discoveryengine.editor` IAM role and an
active Gemini Enterprise instance in the target project.

## Safety: dry run by default

Neither `create_jira_data_source` nor `create_sharepoint_data_source` calls
the real Discovery Engine API unless `dry_run=False` is explicitly passed --
and the agent instructions only ever do that after the user has typed an
explicit confirmation ("actually create it", "go live", etc). By default
you get back the exact request body (secrets redacted) and an equivalent
`curl` command, so you can review before anything touches real
infrastructure.

Secrets (the Jira API token, the SharePoint client secret) are never passed
to a tool as a literal value -- only the *name* of an environment variable
the operator has already exported. This keeps them out of the LLM's
context/conversation transcript entirely; they're read from `os.environ`
only inside the tool, at the moment of a live (non-dry-run) call.

## Running it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export GOOGLE_API_KEY=...   # or configure Vertex AI application-default credentials
python cli.py
```

Example session (dry run, Jira Cloud):

```
you> I want to connect Jira
agent> ...asks deployment type, then the OAuth app's Client ID and the name of the env var holding the Client secret...
you> cloud, client id abc123, secret is in JIRA_CLOUD_CLIENT_SECRET
agent> [calls verify_jira_cloud_oauth -- prints an authorization URL and waits
        for you to approve it in a browser, then confirms the detected Jira
        site] ...asks for project id, location, collection id, display name,
        project keys...
you> project id my-company-prod, location us, collection id jira-eng, display name "Jira Engineering", ENG
agent> [shows the built request body with the client secret redacted, and the curl command -- nothing was sent]
```

To actually execute a call once you've reviewed the dry run, export the
real credential env var Jira/SharePoint needs and tell the agent to "go
live" / "actually create it" -- it will remind you of the IAM role
prerequisite first.

## Extending

Adding a third connector (e.g. Confluence, ServiceNow) means: add a
`<connector>_tools.py` with a `build_*` + `create_*` pair following the same
dry-run-by-default shape, a new sub-agent in `sub_agents/`, add it to
`root_agent`'s `sub_agents=[...]` list in `agent.py`, and add its doc URLs to
`references.py`. No changes needed to the orchestrator's routing logic
beyond mentioning the new option in its instruction.
