"""End-to-end route tests against the in-memory warehouse fixture."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok_with_build_timestamp(client: TestClient) -> None:
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["warehouse_built_at"]  # non-empty ISO timestamp.


def test_list_meetings_returns_seeded_rows(client: TestClient) -> None:
    r = client.get("/v1/seb/meetings")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["limit"] == 50
    # Newest first per ORDER BY meeting_date DESC.
    assert body["results"][0]["meeting_id"] == 2
    assert body["results"][1]["meeting_id"] == 1


def test_list_meetings_pagination_respects_limit(client: TestClient) -> None:
    r = client.get("/v1/seb/meetings?limit=1")
    body = r.json()
    assert body["count"] == 1
    assert body["limit"] == 1


def test_list_meetings_rejects_oversized_limit(client: TestClient) -> None:
    r = client.get("/v1/seb/meetings?limit=10000")
    assert r.status_code == 422


def test_get_meeting_returns_detail_plus_videos(client: TestClient) -> None:
    r = client.get("/v1/seb/meetings/1")
    assert r.status_code == 200
    body = r.json()
    assert body["meeting"]["meeting_id"] == 1
    assert len(body["videos"]) == 1
    assert body["videos"][0]["video_id"] == "v1"


def test_get_meeting_404_for_unknown_id(client: TestClient) -> None:
    r = client.get("/v1/seb/meetings/9999")
    assert r.status_code == 404


def test_get_meeting_422_for_non_integer_id(client: TestClient) -> None:
    r = client.get("/v1/seb/meetings/not-an-int")
    assert r.status_code == 422


def test_county_registration_returns_aggregates(client: TestClient) -> None:
    r = client.get("/v1/voter/county-registration")
    assert r.status_code == 200
    body = r.json()
    # Fulton has 2 voters, Bibb has 1. One status (Active) for each.
    assert body["count"] == 2
    counties = {row["county"]: row["voter_count"] for row in body["results"]}
    assert counties == {"Fulton": 2, "Bibb": 1}


def test_county_registration_filter(client: TestClient) -> None:
    r = client.get("/v1/voter/county-registration?county=Fulton")
    body = r.json()
    assert body["count"] == 1
    assert body["results"][0]["county"] == "Fulton"
    assert body["filter"]["county"] == "Fulton"


def test_seb_voter_overlap_returns_cross_pipeline_view(client: TestClient) -> None:
    r = client.get("/v1/analytics/seb-voter-overlap")
    assert r.status_code == 200
    body = r.json()
    # Cross-join: 2 SEB (year, quarter, compliance_status) buckets ×
    # 2 (county, voter_status) buckets = 4 rows.
    assert body["count"] == 4
    for row in body["results"]:
        assert row["year"] == 2024
        assert row["county"] in {"Fulton", "Bibb"}


def test_seb_voter_overlap_year_filter(client: TestClient) -> None:
    r = client.get("/v1/analytics/seb-voter-overlap?year=2023")
    body = r.json()
    assert body["count"] == 0


def test_cache_control_set_on_successful_get(client: TestClient) -> None:
    r = client.get("/v1/seb/meetings")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=3600"


def test_openapi_doc_lists_only_v1_routes(client: TestClient) -> None:
    """All public routes must be prefixed with /v1/ per ADR-0005 §8."""
    r = client.get("/openapi.json")
    paths = r.json()["paths"].keys()
    assert all(p.startswith("/v1/") for p in paths), (
        f"Non-versioned routes in OpenAPI: {[p for p in paths if not p.startswith('/v1/')]}"
    )
