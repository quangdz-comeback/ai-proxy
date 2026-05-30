"""Budget mode trigger detection."""


def is_budget_mode(payload: dict) -> bool:
    """Check if budget compression/cache mode should be activated.

    Triggered when reasoning_effort is set to "budget" in the request payload.
    This is a custom value not recognized by upstream -- the proxy intercepts it.

    Args:
        payload: The request payload dict

    Returns:
        True if budget mode should be activated
    """
    return payload.get("reasoning_effort") == "budget"
