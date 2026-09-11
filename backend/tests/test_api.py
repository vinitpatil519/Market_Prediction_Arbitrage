from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        # Let the simulator produce a few scans before asserting on state.
        deadline = time.time() + 10
        while time.time() < deadline:
            if test_client.get("/health").json()["markets"] > 0:
                break
            time.sleep(0.25)
        yield test_client


def _await_opportunity(client, timeout: float = 10.0) -> list[dict]:
    """Dislocations are transient, so poll rather than sampling one scan."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = client.get("/api/opportunities?limit=1").json()["opportunities"]
        if rows:
            return rows
        time.sleep(0.25)
    return []


def test_health_reports_both_venues(client):
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["markets"] > 0
    assert {feed["venue"] for feed in payload["feeds"]} == {"polymarket", "kalshi"}


def test_markets_endpoint_returns_two_sided_books(client):
    markets = client.get("/api/markets").json()["markets"]
    assert markets
    for market in markets:
        assert market["yesAsk"] is not None
        assert market["noAsk"] is not None
        assert not market["crossed"]


def test_market_filter_by_venue(client):
    markets = client.get("/api/markets?venue=kalshi").json()["markets"]
    assert markets
    assert {market["venue"] for market in markets} == {"kalshi"}


def test_book_endpoint_returns_cumulative_depth_and_cost_curve(client):
    market = client.get("/api/markets").json()["markets"][0]
    book = client.get(f"/api/markets/{market['venue']}/{market['marketId']}/book").json()
    cumulative = [row["cumulative"] for row in book["yes"]["asks"]]
    assert cumulative == sorted(cumulative)
    assert book["costCurve"]["yesBuy"]


def test_missing_book_is_a_404(client):
    assert client.get("/api/markets/kalshi/NOPE/book").status_code == 404


def test_opportunity_summary_is_internally_consistent(client):
    summary = client.get("/api/opportunities/summary").json()
    assert summary["live"] == sum(summary["byType"].values())
    assert summary["stats"]["scans"] > 0


def test_every_screened_opportunity_clears_the_edge_threshold(client):
    payload = client.get("/api/opportunities?limit=100").json()
    threshold = client.get("/api/config").json()["minNetEdge"]
    for opportunity in payload["opportunities"]:
        assert opportunity["netEdge"] >= threshold
        assert opportunity["kelly"]["stake"] <= payload["bankroll"]


def test_divergence_rows_name_both_venues(client):
    rows = client.get("/api/divergence").json()["rows"]
    for row in rows:
        assert len(row["mids"]) == 2
        assert row["divergence"] >= 0


def test_config_patch_reprices_the_screen(client):
    original = client.get("/api/config").json()["minNetEdge"]
    try:
        response = client.patch("/api/config", json={"minNetEdge": 0.5})
        assert response.json()["config"]["minNetEdge"] == 0.5
        time.sleep(1.0)
        # A 50c minimum edge cannot exist on a two-sided book.
        assert client.get("/api/opportunities").json()["count"] == 0
    finally:
        client.patch("/api/config", json={"minNetEdge": original})


def test_montecarlo_endpoint_returns_ordered_percentiles(client):
    result = client.post("/api/simulate/montecarlo", json={"paths": 100, "trades": 50}).json()
    assert result["stats"]["medianTerminal"] > 0
    assert result["curves"]["p5"][-1] <= result["curves"]["p95"][-1]


def test_execute_endpoint_hedges_a_live_opportunity(client):
    opportunities = _await_opportunity(client)
    if not opportunities:
        pytest.skip("no live opportunity in this simulator window")
    response = client.post(
        "/api/simulate/execute",
        json={"opportunityId": opportunities[0]["id"], "size": 25, "persist": False},
    )
    trade = response.json()["trade"]
    assert trade["hedged"]
    assert trade["pnlIfYes"] == pytest.approx(trade["pnlIfNo"], abs=1e-6)


def test_execute_on_an_expired_opportunity_is_a_404(client):
    response = client.post(
        "/api/simulate/execute", json={"opportunityId": "does-not-exist", "size": 10}
    )
    assert response.status_code == 404


def test_websocket_pushes_a_snapshot(client):
    with client.websocket_connect("/ws/stream") as socket:
        payload = socket.receive_json()
        assert payload["type"] == "snapshot"
        assert payload["books"]
        assert "config" in payload
