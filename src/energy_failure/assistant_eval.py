"""Reproduce the local rules-based behavioral, scope and grounding evaluation."""
import argparse
import json
from pathlib import Path
import platform
import statistics
from urllib.parse import parse_qs, urlparse

from .assistant import EvidenceAssistant


def run(root):
    root = Path(root).resolve()
    cases = json.loads((root / "evals/assistant_cases.json").read_text())
    results, traces = [], []
    for case in cases:
        engine = EvidenceAssistant(root, case["principal"])
        answer = engine.ask(case["question"])
        checks = {"status": answer["status"] == case["status"], "row_count": len(answer["records"]) == case["rows"], "schema": answer["trace"]["schema_valid"] is not False, "citation_presence": bool(answer["citations"]) == (answer["status"] == "answered")}
        if "action" in case:
            checks["action"] = answer["trace"]["query"]["action"] == case["action"]
        if "only_sites" in case:
            checks["scope"] = all(r["site"] in case["only_sites"] for r in answer["records"])
        predictive = next((r for r in answer["records"] if r.get("policy") == "predictive"), {})
        if "expected_predictive_cost" in case:
            checks["numeric_cost"] = abs(predictive.get("annualized_cost_cad", -1) - case["expected_predictive_cost"]) < .02
        if "expected_predictive_caught" in case:
            checks["numeric_caught"] = predictive.get("caught") == case["expected_predictive_caught"]
        for cite in answer["citations"]:
            params = {k: v[0] for k, v in parse_qs(urlparse(cite["url"]).query).items()}
            evidence = engine.evidence(**params)
            checks["citation_resolves_" + cite["id"]] = bool(evidence.get("rows") or evidence.get("curated_facts"))
            checks["citation_scope_" + cite["id"]] = all(r["site"] in engine.sites for r in evidence.get("rows", []))
        results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks, "latency_ms": answer["trace"]["latency_ms"]})
        traces.append({"case": case["id"], "status": answer["status"], **answer["trace"]})
    latencies = sorted(r["latency_ms"] for r in results)
    summary = {"mode": "rules-based; no live LLM calls", "cases": len(results), "passed": sum(r["passed"] for r in results), "failed": sum(not r["passed"] for r in results), "pass_rate": sum(r["passed"] for r in results) / len(results), "latency_ms": {"samples": len(latencies), "min": min(latencies), "median": statistics.median(latencies), "p95_nearest_rank": latencies[__import__('math').ceil(.95 * len(latencies)) - 1], "max": max(latencies)}, "latency_scope": "Single-machine mixed-workload engine calls, including immediate refusals and CSV reads; excludes process/engine initialization, browser/HTTP and model-network latency. Not a production SLO.", "runtime": {"python": platform.python_version(), "platform": platform.system()}, "live_openai_evaluated": False, "cases_detail": results}
    (root / "reports/assistant-evaluation.json").write_text(json.dumps(summary, indent=2) + "\n")
    (root / "reports/assistant-traces.jsonl").write_text("\n".join(json.dumps(r) for r in traces) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    result = run(parser.parse_args().root)
    print(json.dumps({k: v for k, v in result.items() if k != "cases_detail"}, indent=2))
    if result["failed"]:
        raise SystemExit(1)
