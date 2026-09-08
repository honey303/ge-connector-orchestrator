"""Tools for provisioning a Jira data source in Gemini Enterprise.

Grounded on:
  - Jira Cloud setup: references.JIRA_CLOUD_SETUP
  - Jira Data Center setup: references.JIRA_DATA_CENTER_SETUP
  - The DataConnector resource / setUpDataConnector RPC:
    references.DATACONNECTOR_REST_REFERENCE, references.SETUP_DATA_CONNECTOR_RPC

Gemini Enterprise provisions a connector-backed data source by calling
`projects.locations:setUpDataConnector` on the Discovery Engine API, which
creates a Collection and a DataConnector under it in one call. The Jira
API token is never accepted as a literal argument here -- only the *name*
of an environment variable that already holds it, so the secret never
enters the agent's conversation transcript or LLM context.
"""

import os

from .. import references

_VALID_DEPLOYMENTS = {"cloud", "data_center"}


def _reference_for(jira_deployment: str) -> str:
    return (
        references.JIRA_CLOUD_SETUP
        if jira_deployment == "cloud"
        else references.JIRA_DATA_CENTER_SETUP
    )


def build_jira_data_source_request(
    project_id: str,
    location: str,
    collection_id: str,
    data_store_display_name: str,
    jira_deployment: str,
    site_url: str,
    user_email: str,
    api_token_env_var: str,
    project_keys: list[str],
) -> dict:
    """Build the setUpDataConnector request for a Jira data source, without sending it.

    Args:
        project_id: Target GCP project id.
        location: Gemini Enterprise location ("global", "us", or "eu").
        collection_id: Id for the new Collection that will hold this data source.
        data_store_display_name: Human-readable name shown in the console.
        jira_deployment: "cloud" (Jira Cloud) or "data_center" (Jira Data Center).
        site_url: The Jira site URL, e.g. "https://yourcompany.atlassian.net"
            for Jira Cloud, or the Data Center base URL.
        user_email: The email address associated with the Jira API token.
        api_token_env_var: Name of an environment variable, already exported
            in the operator's shell, that holds the Jira API token. The
            token value itself is never passed to this tool.
        project_keys: Jira project keys to index, e.g. ["ENG", "SUPPORT"].

    Returns:
        A dict describing the HTTP request that would be sent (method, url,
        request_body with the token redacted), or a dict with status "error"
        and a message if inputs are invalid.
    """
    if jira_deployment not in _VALID_DEPLOYMENTS:
        return {
            "status": "error",
            "message": (
                f"jira_deployment must be one of {sorted(_VALID_DEPLOYMENTS)}, "
                f"got '{jira_deployment}'."
            ),
        }

    if not os.environ.get(api_token_env_var):
        return {
            "status": "error",
            "message": (
                f"Environment variable '{api_token_env_var}' is not set (or "
                "empty) in this shell. Export it with your Jira API token "
                "before continuing, e.g.: export "
                f"{api_token_env_var}=your-jira-api-token"
            ),
        }

    if not project_keys:
        return {
            "status": "error",
            "message": "At least one Jira project key is required.",
        }

    parent = f"projects/{project_id}/locations/{location}"
    data_source = "jira" if jira_deployment == "cloud" else "jira_data_center"

    request_body = {
        "collectionId": collection_id,
        "dataConnector": {
            "dataSource": data_source,
            "params": {
                "instance_uri": site_url,
                "user_email": user_email,
                "api_token": "<REDACTED: read from "
                f"${api_token_env_var} at execution time, never logged>",
                "project_keys": project_keys,
            },
            "refreshInterval": "86400s",
            "entities": [
                {"entityName": "issues"},
                {"entityName": "comments"},
                {"entityName": "users"},
            ],
        },
        "dataStoreDisplayName": data_store_display_name,
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
            "-d '<request_body above, with the real token substituted>'"
        ),
        "required_iam_role": references.REQUIRED_IAM_ROLE,
        "reference": _reference_for(jira_deployment),
    }


def create_jira_data_source(
    project_id: str,
    location: str,
    collection_id: str,
    data_store_display_name: str,
    jira_deployment: str,
    site_url: str,
    user_email: str,
    api_token_env_var: str,
    project_keys: list[str],
    dry_run: bool = True,
) -> dict:
    """Create (or dry-run) a Jira data source in Gemini Enterprise.

    Defaults to dry_run=True: it builds and returns the exact request that
    would be sent, but never calls the Discovery Engine API. Pass
    dry_run=False only when the user has explicitly confirmed they want to
    execute the call for real against live GCP infrastructure.

    Args: same as build_jira_data_source_request, plus:
        dry_run: If True (default), do not call the API -- just return the
            request that would be sent. If False, actually call
            setUpDataConnector using Application Default Credentials.

    Returns:
        A dict with the built request plus an "executed" key, and on a live
        run, "http_status" and "response".
    """
    built = build_jira_data_source_request(
        project_id=project_id,
        location=location,
        collection_id=collection_id,
        data_store_display_name=data_store_display_name,
        jira_deployment=jira_deployment,
        site_url=site_url,
        user_email=user_email,
        api_token_env_var=api_token_env_var,
        project_keys=project_keys,
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
    body["dataConnector"]["params"]["api_token"] = os.environ[api_token_env_var]

    try:
        resp = requests.post(
            built["url"],
            json=body,
            headers={"Authorization": f"Bearer {credentials.token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    # Never echo the token back out, even in an error response.
    body["dataConnector"]["params"]["api_token"] = "<REDACTED>"

    return {
        **built,
        "executed": True,
        "http_status": resp.status_code,
        "response": resp.json() if resp.content else None,
    }
