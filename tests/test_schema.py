from agent_taskboard.models import CONTRACT_MODELS

EXPECTED_PATHS = {
    "/health",
    "/",
    "/tasks",
    "/tasks/{task_id}",
    "/events",
    "/artifacts/{artifact_id}",
}


def _operations(schema: dict) -> list[tuple[str, str, dict]]:
    found = []
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method in {"get", "put", "patch", "post", "delete"}:
                found.append((path, method, operation))
    return found


def test_openapi_routes_are_described(client):
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == EXPECTED_PATHS
    assert "scaffold" in schema["info"]["description"].lower()
    missing = []
    for path, method, operation in _operations(schema):
        if not operation.get("summary"):
            missing.append(f"{method} {path} summary")
        if not operation.get("description"):
            missing.append(f"{method} {path} description")
        if not operation.get("operationId"):
            missing.append(f"{method} {path} operationId")
        if not operation.get("responses"):
            missing.append(f"{method} {path} responses")
        for param in operation.get("parameters", []):
            name = f"{method} {path} {param.get('name')}"
            schema_bits = [param.get("schema") or {}]
            schema_bits.extend((param.get("schema") or {}).get("anyOf") or [])
            described = param.get("description") or any(bit.get("description") for bit in schema_bits)
            exemplified = any(
                "examples" in bit or "example" in bit for bit in [param, *schema_bits]
            )
            if not described:
                missing.append(f"{name} description")
            if not exemplified:
                missing.append(f"{name} examples")
    assert missing == []


def test_every_field_has_description_and_examples(client):
    for model in CONTRACT_MODELS:
        for name, field in model.model_fields.items():
            assert field.description, f"{model.__name__}.{name} description"
            assert field.examples, f"{model.__name__}.{name} examples"
    schema = client.get("/openapi.json").json()
    components = schema["components"]["schemas"]
    missing = []
    for model in CONTRACT_MODELS:
        body = components[model.__name__]
        for name in model.model_fields:
            prop = body["properties"][name]
            if not prop.get("description"):
                missing.append(f"{model.__name__}.{name} description")
            if "examples" not in prop and "example" not in prop:
                missing.append(f"{model.__name__}.{name} examples")
    assert missing == []
    assert "HTTPValidationError" not in components


def test_docs_page_is_served(client):
    response = client.get("/docs")
    assert response.status_code == 200
