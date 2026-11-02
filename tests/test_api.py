"""Tests for Nonna's API.

Each test runs inside a database transaction that is rolled back at the end,
so even the tests that approve clauses never change your real data.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nonna.api import app
from nonna.database import engine, get_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    connection = engine.connect()
    transaction = connection.begin()
    # Commits inside the API become savepoints, and everything is rolled back after.
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )

    def session_for_tests() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = session_for_tests
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def castellan_id(client: TestClient) -> int:
    counterparties = client.get("/counterparties").json()
    return next(c["id"] for c in counterparties if c["name"] == "Castellan Bioprocessing")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_counterparties(client: TestClient) -> None:
    counterparties = client.get("/counterparties").json()
    counts = {c["name"]: c["contract_count"] for c in counterparties}
    assert counts == {"Castellan Bioprocessing": 5, "Halvorsen Scientific": 1}


def test_counterparty_detail(client: TestClient, castellan_id: int) -> None:
    detail = client.get(f"/counterparties/{castellan_id}").json()

    assert len(detail["entities"]) == 2
    types_in_order = [c["contract_type"] for c in detail["contracts"]]
    assert types_in_order == ["NDA", "MSA", "SOW", "amendment", "SOW"]
    assert detail["contracts"][0]["signed_by_entity"] == "Castellan Bioprocessing AG"


def test_unknown_counterparty_returns_404(client: TestClient) -> None:
    assert client.get("/counterparties/999999").status_code == 404


def test_current_positions(client: TestClient, castellan_id: int) -> None:
    positions = client.get(f"/counterparties/{castellan_id}/positions").json()

    cap = next(p for p in positions if p["clause_type"] == "liability_cap")
    cap_amount = next(t for t in cap["clause"]["terms"] if t["term_key"] == "cap_amount")
    assert float(cap_amount["value"]) == 2_000_000
    assert cap["source"]["contract_type"] == "amendment"
    assert all(p["is_current"] for p in positions)


def test_positions_can_include_superseded(client: TestClient, castellan_id: int) -> None:
    positions = client.get(
        f"/counterparties/{castellan_id}/positions", params={"include_superseded": True}
    ).json()

    caps = [p for p in positions if p["clause_type"] == "liability_cap"]
    assert len(caps) == 2
    assert [p["is_current"] for p in caps] == [False, True]


def test_clause_history(client: TestClient, castellan_id: int) -> None:
    history = client.get(f"/counterparties/{castellan_id}/history/liability_cap").json()

    assert [h["clause"]["presence"] for h in history] == [
        "absent",
        "present",
        "incorporated_by_reference",
        "present",
        "incorporated_by_reference",
    ]
    amendment = history[3]
    assert amendment["decisions"][0]["action"] == "approved_change"


def test_unknown_clause_type_is_rejected(client: TestClient, castellan_id: int) -> None:
    response = client.get(f"/counterparties/{castellan_id}/history/vibes")
    assert response.status_code == 422


def test_review_queue(client: TestClient) -> None:
    queue = client.get("/review-queue").json()
    assert len(queue) == 2
    assert {item["source"]["title"] for item in queue} == {
        "Statement of Work No. 2: Tech Transfer"
    }


# ---------------------------------------------------------------------------
# Reviewing
# ---------------------------------------------------------------------------

def test_approving_a_clause_removes_it_from_the_queue(client: TestClient) -> None:
    queue = client.get("/review-queue").json()
    clause_id = next(i["clause"]["id"] for i in queue if i["clause"]["clause_type"] == "liability_cap")

    response = client.post(
        f"/clauses/{clause_id}/reviews", json={"action": "approved", "reviewer": "pytest"}
    )
    assert response.status_code == 201
    assert response.json()["action"] == "approved"
    assert len(client.get("/review-queue").json()) == 1


def test_approved_change_needs_a_note(client: TestClient) -> None:
    queue = client.get("/review-queue").json()
    clause_id = queue[0]["clause"]["id"]

    response = client.post(
        f"/clauses/{clause_id}/reviews",
        json={"action": "approved_change", "reviewer": "pytest"},
    )
    assert response.status_code == 422
    assert len(client.get("/review-queue").json()) == 2


def test_unknown_review_action_is_rejected(client: TestClient) -> None:
    queue = client.get("/review-queue").json()
    clause_id = queue[0]["clause"]["id"]

    response = client.post(
        f"/clauses/{clause_id}/reviews", json={"action": "yolo", "reviewer": "pytest"}
    )
    assert response.status_code == 422


def test_reviewing_unknown_clause_returns_404(client: TestClient) -> None:
    response = client.post(
        "/clauses/999999/reviews", json={"action": "approved", "reviewer": "pytest"}
    )
    assert response.status_code == 404
