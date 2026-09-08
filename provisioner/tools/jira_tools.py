"""Tools for provisioning a Jira data source in Gemini Enterprise.

Grounded on:
  - Jira Cloud setup: references.JIRA_CLOUD_SETUP
  - Jira Data Center setup: references.JIRA_DATA_CENTER_SETUP
  - The DataConnector resource / setUpDataConnector RPC:
    references.DATACONNECTOR_REST_REFERENCE, references.SETUP_DATA_CONNECTOR_RPC

Gemini Enterprise provisions a connector-backed data source by calling
`projects.locations:setUpDataConnector` on the Discovery Engine API, which
creates a Collection and a DataConnector under it in one call.

Jira Cloud and Jira Data Center authenticate completely differently, so
they get separate build/create function pairs rather than one function
branching on a `jira_deployment` flag:

  - Jira Cloud uses an OAuth 2.0 (3LO -- "three-legged") app registered in
    the Atlassian Developer Console: a Client ID/secret plus a one-time
    interactive browser consent step (see verify_jira_cloud_oauth). This
    is NOT the same as a personal Atlassian API token + email -- that is a
    real Atlassian auth method, just not the one this connector uses.
  - Jira Data Center's field names below (site URL + email + API token)
    are carried over from generic Atlassian REST API auth and have NOT
    been confirmed against the official Gemini Enterprise Jira Data
    Center connector docs. Data Center typically uses a bearer Personal
    Access Token rather than email + token. Treat
    build_jira_data_center_data_source_request as a rough placeholder
    until that's verified.

No secret is ever accepted here as a literal argument -- only the *name*
of an environment variable that already holds it, so it never enters the
agent's conversation transcript or LLM context.
"""

import http.server
import os
import secrets
import urllib.parse

from .. import references

ATLASSIAN_AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_ACCESSIBLE_RESOURCES_URL = (
    "https://api.atlassian.com/oauth/token/accessible-resources"
)

# Minimal read-only scopes for indexing issues/comments/users, plus
# offline_access so the resulting refresh token can be used for ongoing
# sync. Confirm against the Gemini Enterprise Jira Cloud configuration doc
# before relying on this in production -- the exact scopes Gemini
# Enterprise itself requests were not confirmed here.
JIRA_CLOUD_OAUTH_SCOPES = "read:jira-work read:jira-user offline_access"


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures exactly one OAuth redirect and stops the server."""

    def do_GET(self):  # noqa: N802 -- http.server's required method name
        query = urllib.parse.urlparse(self.path).query
        self.server.oauth_params = urllib.parse.parse_qs(query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body>Authentication complete. You can close this tab "
            b"and return to the terminal.</body></html>"
        )

    def log_message(self, format, *args):  # noqa: A002 -- silence default access log
        pass


def verify_jira_cloud_oauth(
    client_id: str,
    client_secret_env_var: str,
    redirect_port: int = 8765,
) -> dict:
    """Run Jira Cloud's OAuth 2.0 (3LO) consent flow and verify it succeeded.

    This is genuinely interactive, not a single silent API call: 3LO
    ("three-legged OAuth") requires a human to log into Atlassian in a
    browser and approve the app. This tool prints the authorization URL to
    the terminal, starts a one-shot local HTTP listener on
    http://localhost:{redirect_port}/callback, and BLOCKS for up to 120
    seconds waiting for Atlassian to redirect back to it with an
    authorization code. That exact redirect URI must be registered on the
    OAuth 2.0 (3LO) app in the Atlassian Developer Console beforehand.

    On success it exchanges the code for an access token and calls
    Atlassian's accessible-resources endpoint, which both confirms the
    token works and returns the Jira Cloud site(s) (instance_id +
    instance_uri) the app can now access -- so the operator does not need
    to already know their site's cloud id up front.

    Args:
        client_id: The OAuth 2.0 (3LO) app's Client ID, from the Atlassian
            Developer Console.
        client_secret_env_var: Name of an environment variable, already
            exported in the operator's shell, that holds the app's Client
            secret. The secret value itself is never passed here.
        redirect_port: Local port to listen on for the OAuth redirect.
            Must match the redirect URI registered on the Atlassian app
            (http://localhost:{redirect_port}/callback).

    Returns:
        A dict with keys: status ("ok"/"error"), authenticated (bool), and
        on success "accessible_sites" (a list of {instance_id,
        instance_uri, scopes} -- one per Jira Cloud site the app can now
        reach), or on failure "message" explaining what went wrong.
    """
    client_secret = os.environ.get(client_secret_env_var)
    if not client_secret:
        return {
            "status": "error",
            "authenticated": False,
            "message": (
                f"Environment variable '{client_secret_env_var}' is not "
                "set (or empty) in this shell. Export it with the OAuth "
                f"app's client secret first, e.g.: export "
                f"{client_secret_env_var}=your-client-secret"
            ),
        }

    try:
        import requests
    except ImportError as exc:
        return {
            "status": "error",
            "authenticated": False,
            "message": f"'requests' must be installed to verify authentication ({exc}).",
        }

    redirect_uri = f"http://localhost:{redirect_port}/callback"
    state = secrets.token_urlsafe(16)
    auth_url = (
        f"{ATLASSIAN_AUTHORIZE_URL}?audience=api.atlassian.com"
        f"&client_id={urllib.parse.quote(client_id)}"
        f"&scope={urllib.parse.quote(JIRA_CLOUD_OAUTH_SCOPES)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&state={state}&response_type=code&prompt=consent"
    )

    print(
        "\nOpen this URL in a browser and approve access "
        f"(waiting up to 120s at {redirect_uri}):\n\n  {auth_url}\n"
    )

    try:
        httpd = http.server.HTTPServer(("localhost", redirect_port), _OAuthCallbackHandler)
    except OSError as exc:
        return {
            "status": "error",
            "authenticated": False,
            "message": (
                f"Could not start the local OAuth callback listener on "
                f"port {redirect_port}: {exc}. Is something else already "
                "using that port?"
            ),
        }

    httpd.timeout = 120
    httpd.oauth_params = None
    try:
        httpd.handle_request()
    finally:
        httpd.server_close()

    params = httpd.oauth_params
    if params is None:
        return {
            "status": "error",
            "authenticated": False,
            "message": (
                "Timed out waiting for the OAuth redirect. Make sure "
                f"'{redirect_uri}' is registered as a redirect URI on the "
                "app in the Atlassian Developer Console, and that you "
                "approved the consent screen."
            ),
        }

    if "error" in params:
        return {
            "status": "error",
            "authenticated": False,
            "message": f"Atlassian returned an error: {params['error'][0]}",
        }

    if params.get("state", [None])[0] != state:
        return {
            "status": "error",
            "authenticated": False,
            "message": "OAuth state mismatch (possible CSRF) -- aborting.",
        }

    code = params.get("code", [None])[0]
    if not code:
        return {
            "status": "error",
            "authenticated": False,
            "message": "No authorization code was received from Atlassian.",
        }

    try:
        token_resp = requests.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "authenticated": False,
            "message": f"Token exchange failed: {exc}",
        }

    if token_resp.status_code != 200:
        return {
            "status": "error",
            "authenticated": False,
            "http_status": token_resp.status_code,
            "message": f"Token exchange rejected: {token_resp.text[:300]}",
        }

    access_token = token_resp.json().get("access_token")
    if not access_token:
        return {
            "status": "error",
            "authenticated": False,
            "message": "Token response did not include an access_token.",
        }

    try:
        resources_resp = requests.get(
            ATLASSIAN_ACCESSIBLE_RESOURCES_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "authenticated": False,
            "message": f"accessible-resources call failed: {exc}",
        }

    if resources_resp.status_code != 200:
        return {
            "status": "error",
            "authenticated": False,
            "http_status": resources_resp.status_code,
            "message": f"accessible-resources rejected: {resources_resp.text[:300]}",
        }

    resources = resources_resp.json()
    if not resources:
        return {
            "status": "error",
            "authenticated": False,
            "message": (
                "OAuth succeeded but no accessible Jira sites were "
                "returned -- check the app's scopes and that the "
                "consenting user has access to a Jira Cloud site."
            ),
        }

    return {
        "status": "ok",
        "authenticated": True,
        "accessible_sites": [
            {
                "instance_id": r.get("id"),
                "instance_uri": r.get("url"),
                "scopes": r.get("scopes"),
            }
            for r in resources
        ],
    }


def build_jira_cloud_data_source_request(
    project_id: str,
    location: str,
    collection_id: str,
    data_store_display_name: str,
    client_id: str,
    client_secret_env_var: str,
    instance_uri: str,
    instance_id: str,
    project_keys: list[str],
) -> dict:
    """Build the setUpDataConnector request for a Jira Cloud data source, without sending it.

    Call verify_jira_cloud_oauth first to confirm the OAuth app works and
    to obtain instance_id/instance_uri -- this function does not validate
    credentials itself, only shapes the request.

    Args:
        project_id: Target GCP project id.
        location: Gemini Enterprise location ("global", "us", or "eu").
        collection_id: Id for the new Collection that will hold this data source.
        data_store_display_name: Human-readable name shown in the console.
        client_id: The OAuth 2.0 (3LO) app's Client ID.
        client_secret_env_var: Name of an environment variable, already
            exported in the operator's shell, that holds the app's Client
            secret. The secret value itself is never passed here.
        instance_uri: The Jira Cloud site URL, e.g. "https://yourcompany.atlassian.net".
        instance_id: The Jira Cloud site's cloud id (from
            verify_jira_cloud_oauth's accessible_sites).
        project_keys: Jira project keys to index, e.g. ["ENG", "SUPPORT"].

    Returns:
        A dict describing the HTTP request that would be sent (method, url,
        request_body with the secret redacted), or a dict with status
        "error" and a message if inputs are invalid.
    """
    if not os.environ.get(client_secret_env_var):
        return {
            "status": "error",
            "message": (
                f"Environment variable '{client_secret_env_var}' is not "
                "set (or empty) in this shell. Export it with the OAuth "
                f"app's client secret before continuing, e.g.: export "
                f"{client_secret_env_var}=your-client-secret"
            ),
        }

    if not project_keys:
        return {
            "status": "error",
            "message": "At least one Jira project key is required.",
        }

    parent = f"projects/{project_id}/locations/{location}"

    request_body = {
        "collectionId": collection_id,
        "dataConnector": {
            "dataSource": "jira",
            "params": {
                "instance_uri": instance_uri,
                "instance_id": instance_id,
                "client_id": client_id,
                "client_secret": "<REDACTED: read from "
                f"${client_secret_env_var} at execution time, never logged>",
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
            "-d '<request_body above, with the real client secret substituted>'"
        ),
        "required_iam_role": references.REQUIRED_IAM_ROLE,
        "reference": references.JIRA_CLOUD_SETUP,
    }


def create_jira_cloud_data_source(
    project_id: str,
    location: str,
    collection_id: str,
    data_store_display_name: str,
    client_id: str,
    client_secret_env_var: str,
    instance_uri: str,
    instance_id: str,
    project_keys: list[str],
    dry_run: bool = True,
) -> dict:
    """Create (or dry-run) a Jira Cloud data source in Gemini Enterprise.

    Defaults to dry_run=True: it builds and returns the exact request that
    would be sent, but never calls the Discovery Engine API. Pass
    dry_run=False only when the user has explicitly confirmed they want to
    execute the call for real against live GCP infrastructure.

    Args: same as build_jira_cloud_data_source_request, plus:
        dry_run: If True (default), do not call the API -- just return the
            request that would be sent. If False, actually call
            setUpDataConnector using Application Default Credentials.

    Returns:
        A dict with the built request plus an "executed" key, and on a live
        run, "http_status" and "response".
    """
    built = build_jira_cloud_data_source_request(
        project_id=project_id,
        location=location,
        collection_id=collection_id,
        data_store_display_name=data_store_display_name,
        client_id=client_id,
        client_secret_env_var=client_secret_env_var,
        instance_uri=instance_uri,
        instance_id=instance_id,
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


def build_jira_data_center_data_source_request(
    project_id: str,
    location: str,
    collection_id: str,
    data_store_display_name: str,
    site_url: str,
    user_email: str,
    api_token_env_var: str,
    project_keys: list[str],
) -> dict:
    """Build the setUpDataConnector request for a Jira Data Center data source.

    UNVERIFIED: these field names (site URL + email + API token) are
    carried over from generic Atlassian REST API auth and have not been
    confirmed against the official Gemini Enterprise Jira Data Center
    connector docs (references.JIRA_DATA_CENTER_SETUP). Data Center
    typically authenticates with a bearer Personal Access Token rather
    than email + token -- treat this as a rough placeholder pending
    verification, not a fully grounded implementation like the Jira Cloud
    or SharePoint tools.

    Args:
        project_id: Target GCP project id.
        location: Gemini Enterprise location ("global", "us", or "eu").
        collection_id: Id for the new Collection that will hold this data source.
        data_store_display_name: Human-readable name shown in the console.
        site_url: The Jira Data Center base URL.
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

    request_body = {
        "collectionId": collection_id,
        "dataConnector": {
            "dataSource": "jira_data_center",
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
        "reference": references.JIRA_DATA_CENTER_SETUP,
        "warning": (
            "These field names are unverified for Jira Data Center -- "
            "confirm against the official docs before relying on this."
        ),
    }


def create_jira_data_center_data_source(
    project_id: str,
    location: str,
    collection_id: str,
    data_store_display_name: str,
    site_url: str,
    user_email: str,
    api_token_env_var: str,
    project_keys: list[str],
    dry_run: bool = True,
) -> dict:
    """Create (or dry-run) a Jira Data Center data source in Gemini Enterprise.

    See build_jira_data_center_data_source_request -- these field names are
    UNVERIFIED for Jira Data Center. Defaults to dry_run=True: it builds
    and returns the exact request that would be sent, but never calls the
    Discovery Engine API. Pass dry_run=False only when the user has
    explicitly confirmed they want to execute the call for real against
    live GCP infrastructure.

    Args: same as build_jira_data_center_data_source_request, plus:
        dry_run: If True (default), do not call the API -- just return the
            request that would be sent. If False, actually call
            setUpDataConnector using Application Default Credentials.

    Returns:
        A dict with the built request plus an "executed" key, and on a live
        run, "http_status" and "response".
    """
    built = build_jira_data_center_data_source_request(
        project_id=project_id,
        location=location,
        collection_id=collection_id,
        data_store_display_name=data_store_display_name,
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
