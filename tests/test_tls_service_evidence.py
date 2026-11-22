import unittest
import ast
import copy
import datetime
import hashlib
import ipaddress
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "charts/re8ch-advanced-fabric/files/controller.py"
tree = ast.parse(SOURCE.read_text())
ns = {"datetime": datetime, "hashlib": hashlib, "time": time,
      "ipaddress": ipaddress, "json": json,
      "API_GROUP": "networking.advfab.org", "MANAGED_BY": "advanced-fabric"}
exec(compile(ast.Module(body=[fn for fn in tree.body if isinstance(fn, ast.FunctionDef)
    and fn.name in {"parse_time", "condition", "tls_target_configuration_digest", "tls_service_evidence_documents"}], type_ignores=[]),
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
        "observedAt": AT, "success": True, "totalMs": 80, "statusCode": 200,
        "targetConfigurationDigest": ns["tls_target_configuration_digest"](TARGET)} for size in (0, 2048)]} for plane in ("host", "pod")}


def assess(target=None, data=None):
    return list(build([target or TARGET], ["node-a"], data or measurements(), 120, NOW))[0]



class TLSServiceEvidenceTest(unittest.TestCase):
    def test_complete_two_plane_two_size_transfer_publishes_precise_service_scope(self):
        document, status = assess()
        assert document["spec"]["subjectRef"] == {"apiVersion": "v1", "kind": "Service",
                                                   "namespace": "default", "name": "kubernetes"}
        assert document["spec"]["scope"]["sourceNode"] == "node-a"
        assert document["spec"]["scope"]["endpoint"] == "192.0.2.1"
        assert status["state"] == "Ready"
        assert status["pathEvidence"]["reachable"] is True
        assert len(status["serviceEvidence"]["transfers"]) == 4


    def test_endpoint_change_invalidates_old_success_without_waiting_for_its_expiry(self):
        target = dict(TARGET, endpoint="192.0.2.2")
        old_document, _ = assess()
        document, status = assess(target)
        assert document["metadata"]["name"] == old_document["metadata"]["name"]
        assert status["state"] == "Unknown"
        assert status["pathEvidence"]["reachable"] is None
        assert status["conditions"][0]["status"] == "False"


    def test_one_failed_large_transfer_cannot_be_hidden_by_tcp_or_small_success(self):
        data = measurements()
        data[("node-a", "pod")]["paths"] = [{"lossRatio": 0}]
        data[("node-a", "pod")]["tlsTransfers"][1]["success"] = False
        _, status = assess(data=data)
        assert status["serviceEvidence"]["complete"] is True
        assert status["pathEvidence"]["reachable"] is False
        assert status["conditions"][0]["status"] == "False"


    def test_missing_plane_stale_row_wrong_scope_and_wrong_size_remain_unknown(self):
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


    def test_unassigned_sources_and_unconfigured_services_publish_no_assessment(self):
        assert list(build([dict(TARGET, sourceNodes=[])], ["node-a"], measurements(), 120, NOW)) == []
        assert list(build([], ["node-a"], measurements(), 120, NOW)) == []
        assert list(build([dict(TARGET, targetService="unscoped")], ["node-a"], measurements(), 120, NOW)) == []


    def test_slow_success_is_not_healthy_when_service_latency_budget_is_exceeded(self):
        data = measurements()
        data[("node-a", "pod")]["tlsTransfers"][1]["totalMs"] = 3300
        _, status = assess(data=data)
        assert status["serviceEvidence"]["complete"] is True
        assert status["pathEvidence"]["reachable"] is True
        assert status["serviceEvidence"]["withinLatencyBudget"] is False
        assert status["conditions"][0]["status"] == "False"


    def test_changed_trust_status_or_path_identity_does_not_reuse_old_success(self):
        for changes in ({"caFile": "/new-ca.crt"}, {"expectedStatuses": [401]}, {"pathId": "new-route"}):
            _, status = assess(dict(TARGET, **changes))
            assert status["state"] == "Unknown", changes
            assert status["conditions"][0]["status"] == "False", changes


    def test_executed_transport_failures_are_preserved_instead_of_disappearing(self):
        data = measurements()
        for measurement in data.values():
            for row in measurement["tlsTransfers"]:
                row.update(success=False, statusCode=None, category="tls")
        _, status = assess(data=data)
        assert status["state"] == "Partial"
        assert status["serviceEvidence"]["complete"] is True
        assert len(status["serviceEvidence"]["transfers"]) == 4
        assert status["pathEvidence"]["reachable"] is False

    def test_ipv6_configuration_and_collector_canonicalization_match(self):
        target = dict(TARGET, endpoint="2001:0db8:0000:0000:0000:0000:0000:0001")
        data = measurements()
        for measurement in data.values():
            for row in measurement["tlsTransfers"]:
                row.update(endpoint="2001:db8::1", targetConfigurationDigest=ns["tls_target_configuration_digest"](target))
        document, status = assess(target, data)
        assert status["state"] == "Ready"
        assert document["spec"]["scope"]["endpoint"] == "2001:db8::1"
