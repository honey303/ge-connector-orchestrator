"""Shared validation for the GCP project/location a data source is provisioned into.

Both the Jira and SharePoint sub-agents call this before building a request,
so the "which project, which location, do I have the right role" checks live
in one place instead of being duplicated per connector.
"""

import re

from .. import references

_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")

# Gemini Enterprise data stores/collections are created in one of these
# multi-region locations. See references.CONNECTORS_INTRO.
VALID_LOCATIONS = {"global", "us", "eu"}


def validate_gcp_target(project_id: str, location: str) -> dict:
    """Validate a GCP project id and Gemini Enterprise location before provisioning.

    Args:
        project_id: The target Google Cloud project id, e.g. "my-company-prod".
        location: The Gemini Enterprise/Discovery Engine location -- one of
            "global", "us", or "eu".

    Returns:
        A dict with keys: valid (bool), errors (list[str]),
        required_iam_role (str), reference (str, doc URL).
    """
    errors = []

    if not project_id or not _PROJECT_ID_RE.match(project_id):
        errors.append(
            f"'{project_id}' does not look like a valid GCP project id "
            "(lowercase letters, digits, hyphens, 6-30 chars, starting with "
            "a letter)."
        )

    if location not in VALID_LOCATIONS:
        errors.append(
            f"'{location}' is not a supported location. Choose one of: "
            f"{', '.join(sorted(VALID_LOCATIONS))}."
        )

    return {
        "valid": not errors,
        "errors": errors,
        "required_iam_role": references.REQUIRED_IAM_ROLE,
        "reference": references.CONNECTORS_INTRO,
        "note": (
            "The caller also needs an active Gemini Enterprise instance "
            "provisioned in this project -- this tool does not create one."
        ),
    }
