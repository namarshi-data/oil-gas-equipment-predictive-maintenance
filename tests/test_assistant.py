"""Behavioral evidence, allow-list and untrusted planner boundary checks."""
import csv
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest
from energy_failure.assistant import EvidenceAssistant, QueryError, TOOL, openai_plan, rule_plan, validate_plan
from energy_failure.assistant_server import make_server
import energy_failure.assistant as assistant_module

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "evals/assistant_cases.json").read_text())
PEACE = "peace.manager@portfolio.example"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_behavioral_cases(case):
    result = EvidenceAssistant(ROOT, case["principal"]).ask(case["question"])
    assert result["status"] == case["status"]
    assert len(result["records"]) == case["rows"]
    assert bool(result["citations"]) == (case["status"] == "answered")
    if "action" in case:
        assert result["trace"]["query"]["action"] == case["action"]
    if "only_sites" in case:
        assert all(r["site"] in case["only_sites"] for r in result["records"])
    if "expected_predictive_cost" in case:
        row = next(r for r in result["records"] if r["policy"] == "predictive")
        assert row["annualized_cost_cad"] == pytest.approx(case["expected_predictive_cost"], abs=.02)


@pytest.mark.parametrize("case", [c for c in CASES if c.get("shared_scope_gate")], ids=lambda c: c["id"])
@pytest.mark.parametrize("mode", ["rules", "openai"])
def test_unsupported_scope_precedes_asset_matching_and_optional_model(case, mode, monkeypatch):
    def must_not_call_model(*args, **kwargs):
        raise AssertionError("Unsupported request must not reach the optional model")
    monkeypatch.setattr(assistant_module, "openai_plan", must_not_call_model)
    result = EvidenceAssistant(ROOT, PEACE, mode=mode, model="explicit-test-model").ask(case["question"])
    assert result["status"] == "unsupported"
    assert result["records"] == []
    assert result["citations"] == []
    assert result["trace"]["unsupported_intent_guard"] is True
    assert result["trace"]["live_llm_used"] is False
    assert "Power BI" in result["answer"]


def test_shared_gate_preserves_legitimate_optional_planner_question(monkeypatch):
    requests = []
    def mock_planner(question, **kwargs):
        requests.append(question)
        return rule_plan(question)
    monkeypatch.setattr(assistant_module, "openai_plan", mock_planner)
    result = EvidenceAssistant(ROOT, PEACE, mode="openai", model="explicit-test-model").ask("Compare policy costs")
    assert requests == ["Compare policy costs"]
    assert result["status"] == "answered"
    assert result["trace"]["unsupported_intent_guard"] is False


def test_latest_asset_score_comes_from_latest_date_not_maximum():
    with (ROOT / "data/processed/dashboard/scored_readings.csv").open() as handle:
        history = [r for r in csv.DictReader(handle) if r["asset_id"] == "AB-001"]
    expected = max(history, key=lambda r: r["date"])
    result = EvidenceAssistant(ROOT, PEACE).ask("Latest risk for AB-001")["records"][0]
    assert result["date"] == expected["date"]
    assert result["risk_score"] == float(expected["risk_score"])


def test_unknown_and_other_site_assets_are_indistinguishable():
    engine = EvidenceAssistant(ROOT, PEACE)
    assert engine.ask("AB-002")["answer"] == engine.ask("AB-999")["answer"]
    for source in ("assets", "readings", "events", "visits"):
        assert {r["site"] for r in engine.evidence(source)["rows"]} == {"Peace River"}


def test_openai_request_contract_and_deterministic_answer_boundary():
    plan = rule_plan("Compare policy costs")
    captured = []
    def transport(payload):
        captured.append(payload)
        return {"output": [{"type": "function_call", "name": TOOL["name"], "arguments": json.dumps(plan)}, {"type": "message", "content": "Invented savings are $99999999"}]}
    chosen = openai_plan("Compare policy costs", model="explicit-test-model", api_key="test-placeholder", transport=transport)
    result = EvidenceAssistant(ROOT, PEACE).execute(chosen)
    assert "99999999" not in result["answer"]
    assert captured[0]["tools"][0]["strict"] is True
    assert captured[0]["parallel_tool_calls"] is False
    assert captured[0]["store"] is False
    assert "principal" not in json.dumps(captured)
    assert captured[0]["tool_choice"] == {"type": "function", "name": TOOL["name"]}


@pytest.mark.parametrize("changes", [{"principal": "fleet.reviewer@portfolio.example"}, {"sql": "select * from events"}, {"top_n": 100}, {"top_n": True}, {"asset_id": "../../secrets"}, {"action": "run_python"}])
def test_query_schema_rejects_arbitrary_capabilities(changes):
    with pytest.raises(QueryError):
        validate_plan({**rule_plan("show asset risk"), **changes})


def test_valid_but_unauthorized_llm_plan_is_denied_after_schema_validation():
    plan = {**rule_plan("show asset risk"), "site": "Grande Prairie"}
    validate_plan(plan)
    with pytest.raises(QueryError, match="unavailable"):
        EvidenceAssistant(ROOT, PEACE).execute(plan)


@pytest.mark.parametrize("output", [{"output": []}, {"output": [{"type": "function_call", "name": "run_code", "arguments": "{}"}]}, {"output": [{"type": "function_call", "name": TOOL["name"], "arguments": "not json"}]}])
def test_optional_planner_fails_closed(output):
    with pytest.raises(QueryError):
        openai_plan("cost", model="explicit-test-model", api_key="test-placeholder", transport=lambda _: output)


@pytest.fixture
def server():
    instance = make_server(ROOT, PEACE, port=0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{instance.server_address[1]}"
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=2)


def test_http_request_cannot_choose_identity(server):
    request = Request(server + "/api/ask", json.dumps({"question": "cost", "principal": "fleet.reviewer@portfolio.example"}).encode(), {"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc:
        urlopen(request)
    assert exc.value.code == 400
    assert json.load(urlopen(server + "/api/context"))["principal"] == PEACE


def test_http_origin_and_host_reject_cross_site_requests(server):
    for headers in ({"Origin": "https://other.example"}, {"Host": "evil.example"}):
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(server + "/api/context", headers=headers))
        assert exc.value.code == 403


def test_http_evidence_is_scoped_and_no_arbitrary_file_route(server):
    assert {r["site"] for r in json.load(urlopen(server + "/api/evidence?source=events"))["rows"]} == {"Peace River"}
    for path, status in (("/api/evidence?source=events&site=Grande%20Prairie", 403), ("/api/evidence?source=../../secrets", 403), ("/data/processed/dashboard/scored_readings.csv", 404)):
        with pytest.raises(HTTPError) as exc:
            urlopen(server + path)
        assert exc.value.code == status


def test_http_success_is_grounded_and_has_defensive_headers(server):
    request = Request(server + "/api/ask", json.dumps({"question": "Compare policy costs"}).encode(), {"Content-Type": "application/json"})
    with urlopen(request) as response:
        data = json.load(response)
        assert response.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert data["status"] == "answered"
    assert len(data["citations"]) == 4
    assert data["assigned_sites"] == ["Peace River"]
