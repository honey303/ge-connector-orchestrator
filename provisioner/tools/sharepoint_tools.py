"""Tools for provisioning a Microsoft SharePoint data source in Gemini Enterprise.

Grounded on:
  - references.SHAREPOINT_SETUP (federated search / data-store setup)
  - references.SHAREPOINT_INGESTION (data-ingestion connector)
  - references.ENTRA_ID_SETUP (the Entra ID OAuth app registration SharePoint
    connectors depend on)
  - references.DATACONNECTOR_REST_REFERENCE, references.SETUP_DATA_CONNECTOR_RPC

SharePoint Online must first be registered as an OAuth 2.0 application in
Microsoft Entra ID, which yields a client ID, client secret, and tenant ID.
As with the Jira tools, the client secret is only ever referenced by the
name of an environment variable -- never passed as a literal value.
"""

import os

from .. import references

_VALID_CONNECTION_MODES = {"federated_search", "data_ingestion"}


def build_sharepoint_data_source_request(
    project_id: str,
    location: str,
    collection_id: str,
    collection_display_name: str,
    connection_mode: str,
    instance_uri: str,
    tenant_id: str,
    client_id: str,
    client_secret_env_var: str,
) -> dict:
    """Build the setUpDataConnector request for a SharePoint data source, without sending it.

    Args:
        project_id: Target GCP project id.
        location: Gemini Enterprise location ("global", "us", or "eu").
        collection_id: Id for the new Collection that will hold this data source.
        collection_display_name: Human-readable name for the Collection,
            shown in the console. Required top-level field on the
            SetUpDataConnectorRequest (collectionDisplayName) -- confirmed
            against discoveryengine's own API discovery document.
        connection_mode: "federated_search" (query-time federation, GA) or
            "data_ingestion" (indexes content into Gemini Enterprise, GA).
        instance_uri: SharePoint site URL, e.g.
            "https://yourcompany.sharepoint.com" for all first-level sites,
            or "https://yourcompany.sharepoint.com/sites/YourSite" for one.
        tenant_id: The Microsoft Entra ID tenant id.
        client_id: The application (client) id of the Entra ID app
            registration created for Gemini Enterprise.
        client_secret_env_var: Name of an environment variable, already
            exported in the operator's shell, that holds the Entra ID app's
            client secret. The secret value itself is never passed here.

    Returns:
        A dict describing the HTTP request that would be sent (method, url,
        request_body with the secret redacted), or a dict with status
        "error" and a message if inputs are invalid.
    """
    if connection_mode not in _VALID_CONNECTION_MODES:
        return {
            "status": "error",
            "message": (
                f"connection_mode must be one of {sorted(_VALID_CONNECTION_MODES)}, "
                f"got '{connection_mode}'."
            ),
        }

    if not instance_uri.startswith("https://") or "sharepoint.com" not in instance_uri:
        return {
            "status": "error",
            "message": (
                "instance_uri should look like "
                "'https://yourcompany.sharepoint.com' or "
                "'https://yourcompany.sharepoint.com/sites/YourSite'."
            ),
        }

    if not os.environ.get(client_secret_env_var):
        return {
            "status": "error",
            "message": (
                f"Environment variable '{client_secret_env_var}' is not set "
                "(or empty) in this shell. Export it with the Entra ID app's "
                f"client secret before continuing, e.g.: export "
                f"{client_secret_env_var}=your-client-secret"
            ),
        }

    parent = f"projects/{project_id}/locations/{location}"
    data_source = (
        "sharepoint_federated_search"
        if connection_mode == "federated_search"
        else "sharepoint"
    )

    # entities[].entityName is an enum-like value specific to each data
    # source, not a free label. discoveryengine's DataConnectorSourceEntity
    # schema only documents supported values for Salesforce, Jira, and
    # Confluence -- SharePoint isn't listed, so "sites"/"documents" below
    # are an unverified guess, the same kind of mistake that made
    # dataStoreDisplayName fail for Jira. Confirm against
    # references.SHAREPOINT_SETUP before relying on this in production.
    request_body = {
        "collectionId": collection_id,
        "collectionDisplayName": collection_display_name,
        "dataConnector": {
            "dataSource": data_source,
            "params": {
                "instance_uri": instance_uri,
                "tenant_id": tenant_id,
                "client_id": client_id,
                "client_secret": "<REDACTED: read from "
                f"${client_secret_env_var} at execution time, never logged>",
            },
            "refreshInterval": "86400s",
            "entities": [{"entityName": "sites"}, {"entityName": "documents"}],
        },
    }

    url = f"{references.DISCOVERY_ENGINE_API_HOST}/v1alpha/{parent}:setUpDataConnector"

    return {
        "status": "ok",
        "http_method": "POST",
        "url": url,
        "request_body": request_body,
        "curl_dry_run": (
            f"curl -X POST '{url}' "
            "-H 'Authorization: Bearer $(gcloud auth print-access-token)' "
            "-H 'Content-Type: application/json' "
            "-d '<request_body above, with the real secret substituted>'"
        ),
        "required_iam_role": references.REQUIRED_IAM_ROLE,
        "reference": (
            references.SHAREPOINT_INGESTION
            if connection_mode == "data_ingestion"
            else references.SHAREPOINT_SETUP
        ),
        "prerequisite_reference": references.ENTRA_ID_SETUP,
        "warning": (
            "entities[].entityName values ('sites', 'documents') are "
            "unverified for SharePoint -- discoveryengine's schema only "
            "confirms entity names for Salesforce/Jira/Confluence."
        ),
    }


def create_sharepoint_data_source(
    project_id: str,
    location: str,
    collection_id: str,
    collection_display_name: str,
    connection_mode: str,
    instance_uri: str,
    tenant_id: str,
    client_id: str,
    client_secret_env_var: str,
    dry_run: bool = True,
) -> dict:
    """Create (or dry-run) a SharePoint data source in Gemini Enterprise.

    Defaults to dry_run=True: it builds and returns the exact request that
    would be sent, but never calls the Discovery Engine API. Pass
    dry_run=False only when the user has explicitly confirmed they want to
    execute the call for real against live GCP infrastructure.

    Args: same as build_sharepoint_data_source_request, plus:
        dry_run: If True (default), do not call the API -- just return the
            request that would be sent. If False, actually call
            setUpDataConnector using Application Default Credentials.

    Returns:
        A dict with the built request plus an "executed" key, and on a live
        run, "http_status" and "response".
    """
    built = build_sharepoint_data_source_request(
        project_id=project_id,
        location=location,
        collection_id=collection_id,
        collection_display_name=collection_display_name,
        connection_mode=connection_mode,
        instance_uri=instance_uri,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret_env_var=client_secret_env_var,
    )
    if built["status"] != "ok":
        return built

    if dry_run:
        return {
            **built,
            "executed": False,
            "note": (
                "DRY RUN: no request was sent. Ask the user to confirm "
                "before re-calling this tool with dry_run=False."
            ),
        }

    try:
        import google.auth
        import google.auth.transport.requests
        import requests
    except ImportError as exc:
        return {
            "status": "error",
            "message": (
                "Live execution requires 'google-auth' and 'requests' to "
                f"be installed ({exc})."
            ),
        }

    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
    except Exception as exc:  # noqa: BLE001 -- surface any ADC failure to the agent
        return {
            "status": "error",
            "message": f"Could not obtain Application Default Credentials: {exc}",
        }

    body = built["request_body"]
    body["dataConnector"]["params"]["client_secret"] = os.environ[client_secret_env_var]

    try:
        resp = requests.post(
            built["url"],
            json=body,
            headers={"Authorization": f"Bearer {credentials.token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    # Never echo the secret back out, even in an error response.
    body["dataConnector"]["params"]["client_secret"] = "<REDACTED>"

    return {
        **built,
        "executed": True,
        "http_status": resp.status_code,
        "response": resp.json() if resp.content else None,
    }
