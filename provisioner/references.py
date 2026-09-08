"""Canonical Google Cloud documentation this agent is grounded on.

Every field, IAM role, and request shape the sub-agents ask about or build
traces back to one of these pages. If Google renames or moves the Gemini
Enterprise docs, update the URLs here rather than scattering them through
the agent instructions and tools.
"""

GEMINI_ENTERPRISE_OVERVIEW = "https://docs.cloud.google.com/gemini/enterprise/docs"
CONNECTORS_INTRO = (
    "https://docs.cloud.google.com/gemini/enterprise/docs/connectors/"
    "introduction-to-connectors-and-data-stores"
)

JIRA_CLOUD_SETUP = (
    "https://docs.cloud.google.com/gemini/enterprise/docs/connectors/"
    "jira-cloud/set-up-data-store"
)
JIRA_DATA_CENTER_SETUP = (
    "https://docs.cloud.google.com/gemini/enterprise/docs/connectors/"
    "jira-dc/set-up-data-store"
)

SHAREPOINT_SETUP = (
    "https://docs.cloud.google.com/gemini/enterprise/docs/connectors/"
    "ms-sharepoint/set-up-data-store"
)
SHAREPOINT_INGESTION = (
    "https://cloud.google.com/gemini/enterprise/docs/"
    "connect-sharepoint-online-ingestion"
)
ENTRA_ID_SETUP = (
    "https://docs.cloud.google.com/gemini/enterprise/docs/connectors/"
    "entra-id/connect-entra-id"
)

DATACONNECTOR_REST_REFERENCE = (
    "https://docs.cloud.google.com/generative-ai-app-builder/docs/reference/"
    "rest/v1/DataConnector"
)
SETUP_DATA_CONNECTOR_RPC = (
    "https://docs.cloud.google.com/gemini/enterprise/docs/reference/rest/v1/"
    "projects.locations/setUpDataConnector"
)

REQUIRED_IAM_ROLE = "roles/discoveryengine.editor"
DISCOVERY_ENGINE_API_HOST = "https://discoveryengine.googleapis.com"

# The API's own machine-readable schema, served directly by the API host
# rather than a docs site. This is the primary source of truth for the
# *shape* of setUpDataConnector's request (SetUpDataConnectorRequest,
# DataConnector, DataConnectorSourceEntity) -- e.g. it is what caught
# dataStoreDisplayName being wrong (the real field is the request's
# top-level collectionDisplayName) and entityName needing the literal
# value "Issue" for Jira. It does NOT cover connector-specific `params`
# keys (client_id, instance_uri, etc.), which remain sourced from the
# per-connector setup docs above and are noted as unverified where not
# confirmed there.
DISCOVERY_ENGINE_API_DISCOVERY_DOC = (
    f"{DISCOVERY_ENGINE_API_HOST}/$discovery/rest?version=v1alpha"
)
