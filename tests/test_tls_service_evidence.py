import ast
import copy
import datetime
import hashlib
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "charts/re8ch-advanced-fabric/files/controller.py"
tree = ast.parse(SOURCE.read_text())
ns = {"datetime": datetime, "hashlib": hashlib, "time": time,
      "API_GROUP": "networking.advfab.org", "MANAGED_BY": "advanced-fabric"}
exec(compile(ast.Module(body=[fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
    and fn.name in {"parse_time", "condition", "tls_service_evidence_documents"}], type_ignores=[]),
    str(SOURCE), "exec"), ns)
build = ns["tls_service_evidence_documents"]
NOW = 1800000000
AT = datetime.datetime.fromtimestamp(NOW - 10, datetime.timezone.utc).isoformat()
TARGET = {"name": "api", "targetService": "default/kubernetes", "endpoint": "192.0.2.1",
          "serverName": "kubernetes.default.svc", "sourceNodes": ["node-a"], "required": True}


def measurements():
    return {("node-a", plane): {"fresh": True, "tlsTransfers": [{
        "measurementDefinitionId": "tls-transfer-v1", "targetId": "api", "sourceNode": "node-a",
        "sourcePlane": plane, "targetService": TARGET["targetService"], "endpoint": "192.0.2.1",
        "port": 443, "serverName": TARGET["serverName"], "path": "/version", "paddingBytes": size,
        "observedAt": AT, "success": True, "totalMs": 80} for size in (0, 2048)]} for plane in ("host", "pod")}


def assess(target=None, data=None):
    return list(build([target or TARGET], ["node-a"], data or measurements(), 120, NOW))[0]


def test_complete_two_plane_two_size_transfer_publishes_precise_service_scope():
    document, status = assess()
    assert document["spec"]["subjectRef"] == {"apiVersion": "v1", "kind": "Service",
                                               "namespace": "default", "name": "kubernetes"}
    assert document["spec"]["scope"]["sourceNode"] == "node-a"
    assert document["spec"]["scope"]["endpoint"] == "192.0.2.1"
    assert status["state"] == "Ready"
    assert status["pathEvidence"]["reachable"] is True
    assert len(status["serviceEvidence"]["transfers"]) == 4


def test_endpoint_change_invalidates_old_success_without_waiting_for_its_expiry():
    target = dict(TARGET, endpoint="192.0.2.2")
    old_document, _ = assess()
    document, status = assess(target)
    assert document["metadata"]["name"] == old_document["metadata"]["name"]
    assert status["state"] == "Unknown"
    assert status["pathEvidence"]["reachable"] is None
    assert status["conditions"][0]["status"] == "False"


def test_one_failed_large_transfer_cannot_be_hidden_by_tcp_or_small_success():
    data = measurements()
    data[("node-a", "pod")]["paths"] = [{"lossRatio": 0}]
    data[("node-a", "pod")]["tlsTransfers"][1]["success"] = False
    _, status = assess(data=data)
    assert status["serviceEvidence"]["complete"] is True
    assert status["pathEvidence"]["reachable"] is False
    assert status["conditions"][0]["status"] == "False"


def test_missing_plane_stale_row_wrong_scope_and_wrong_size_remain_unknown():
    for change in ("stale", "future", "node", "sni", "size", "missing-plane"):
        data = measurements()
        row = data[("node-a", "pod")]["tlsTransfers"][1]
        if change == "stale": row["observedAt"] = "2020-01-01T00:00:00Z"
        elif change == "future": row["observedAt"] = "2099-01-01T00:00:00Z"
        elif change == "node": row["sourceNode"] = "other"
        elif change == "sni": row["serverName"] = "other.example"
        elif change == "size": row["paddingBytes"] = 1
        else: data[("node-a", "pod")]["fresh"] = False
        _, status = assess(data=data)
        assert status["pathEvidence"]["reachable"] is None, change
        assert status["conditions"][0]["status"] == "False", change


def test_unassigned_sources_and_unconfigured_services_publish_no_assessment():
    assert list(build([dict(TARGET, sourceNodes=[])], ["node-a"], measurements(), 120, NOW)) == []
    assert list(build([], ["node-a"], measurements(), 120, NOW)) == []
    assert list(build([dict(TARGET, targetService="unscoped")], ["node-a"], measurements(), 120, NOW)) == []


def test_slow_success_is_not_healthy_when_service_latency_budget_is_exceeded():
    data = measurements()
    data[("node-a", "pod")]["tlsTransfers"][1]["totalMs"] = 3300
    _, status = assess(data=data)
    assert status["serviceEvidence"]["complete"] is True
    assert status["pathEvidence"]["reachable"] is True
    assert status["serviceEvidence"]["withinLatencyBudget"] is False
    assert status["conditions"][0]["status"] == "False"
