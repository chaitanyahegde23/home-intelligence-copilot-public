from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, create_app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_capabilities_report_enabled_defaults() -> None:
    configured_client = TestClient(create_app(Settings(ai_enabled=False)))
    response = configured_client.get("/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "documents": True,
        "document_copilot": False,
        "financial_features": True,
    }


def test_disabled_financial_routes_are_not_exposed() -> None:
    settings = Settings(financial_features_enabled=False)
    disabled_client = TestClient(create_app(settings))

    assert disabled_client.get("/capabilities").json()["financial_features"] is False
    assert disabled_client.get("/transactions").status_code == 404
    assert disabled_client.get("/health").status_code == 200


def test_production_does_not_expose_api_schema_or_documentation() -> None:
    production_client = TestClient(
        create_app(
            Settings(
                app_env="production",
                api_docs_enabled=False,
                auth_mode="secure",
                auth_allowed_origin="https://hic.example.com",
                auth_allowed_hosts=["hic.example.com"],
            )
        )
    )

    assert production_client.get("/docs").status_code == 404
    assert production_client.get("/redoc").status_code == 404
    assert production_client.get("/openapi.json").status_code == 404


def test_production_can_explicitly_expose_api_documentation() -> None:
    production_client = TestClient(
        create_app(
            Settings(
                app_env="production",
                api_docs_enabled=True,
                api_root_path="/api",
                auth_mode="secure",
                auth_allowed_origin="https://hic.example.com",
                auth_allowed_hosts=["hic.example.com"],
            )
        )
    )

    assert production_client.get("/docs").status_code == 200
    assert production_client.get("/openapi.json").status_code == 200
    assert "/api/openapi.json" in production_client.get("/docs").text
