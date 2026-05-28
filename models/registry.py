MODELS = [
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "mimo-v2-pro",
    "mimo-v2-flash",
    "mimo-v2-omni",
]

MODEL_SET = set(MODELS)


def resolve_model(name):
    """Validate model name against hardcoded list."""
    if not name:
        raise ValueError("Model name is required")
    if name not in MODEL_SET:
        raise ValueError(f"Unknown model: {name}. Available: {', '.join(MODELS)}")
    return name


def get_model_list():
    """Return model list in OpenAI format."""
    return [
        {
            "id": m,
            "object": "model",
            "created": 1700000000,
            "owned_by": "opengateway",
        }
        for m in MODELS
    ]
