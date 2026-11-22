import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "charts/re8ch-advanced-fabric/files/observation-api.py"
SPEC = importlib.util.spec_from_file_location("observation_api", MODULE_PATH)
observation_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observation_api)


def point(timestamp, values):
    return {"observedAt": timestamp, "values": {
        symbol: {"value": value, "unit": "raw"} for symbol, value in values.items()
    }}


def complete_values(offset):
    symbols = set(observation_api.STRUCTURE_SYMBOLS["R"] +
                  observation_api.STRUCTURE_SYMBOLS["D"] +
                  observation_api.STRUCTURE_SYMBOLS["C"])
    return {symbol: index + offset for index, symbol in enumerate(sorted(symbols))}


def test_relationship_series_is_bounded_and_has_three_producer_coordinates():
    history = [point("2026-09-11T00:0%d:00Z" % index, complete_values(index)) for index in range(6)]
    samples = observation_api.relationship_series(history, ["R", "D", "C"], maximum=3)
    assert len(samples) == 3
    assert [sample["time"] for sample in samples] == sorted(sample["time"] for sample in samples)
    for sample in samples:
        assert set(sample["coordinates"]) == {"R", "D", "C"}
        assert all(0 <= value <= 1 for value in sample["coordinates"].values())


def test_relationship_series_prefers_complete_synchronized_slices():
    history = []
    for index in range(10):
        values = complete_values(index)
        if index < 3:
            values.pop("d_mode")
        history.append(point(f"2026-09-11T00:00:{index:02d}Z", values))

    samples = observation_api.relationship_series(history, ["R", "D", "C"], maximum=7)

    assert len(samples) == 7
    assert all(sample["coordinates"]["D"] is not None for sample in samples)


def test_missing_and_right_censored_values_remain_null_not_zero():
    values = complete_values(0)
    values.pop("n_alt")
    samples = observation_api.relationship_series(
        [point("2026-09-11T00:00:00Z", values)], ["R", "D", "C"]
    )
    assert samples[0]["coordinates"]["R"] is None
    assert samples[0]["coordinates"]["D"] is None
    assert samples[0]["evidence"]["R"]["state"] == "Partial"
    assert "n_alt" in samples[0]["evidence"]["D"]["missingSymbols"]


def test_bounded_times_preserves_endpoints_deterministically():
    assert observation_api.bounded_times(range(10), 4) == [0, 3, 6, 9]
    assert observation_api.bounded_times(range(10), 1) == [9]


def test_public_api_has_no_environment_specific_storage_endpoint():
    source = MODULE_PATH.read_text()
    assert "vmselect" not in source
    assert "vmsingle" not in source
    assert "observability-system" not in source


def test_snapshot_includes_all_agent_network_quality_payloads(monkeypatch):
    documents = {
        "structural-observation": [{"data": {"observations.json": '{"nodes":{"r640":{}}}'}}],
        "node-status": [{"data": {"status.json": '{"node":"r640","frr":{"state":"active"}}'}}],
        "node-measurement": [{"data": {"measurement.json": '{"node":"r640","measurements":[{"symbol":"n_peer","value":3}]}'}}],
        "network-quality": [
            {"data": {"result.json": '{"sourceNode":"r640","sourcePlane":"pod","dns":[{"protocol":"udp"}]}' }},
            {"data": {"result.json": '{"sourceNode":"r640","sourcePlane":"host","paths":[{"targetNode":"peer"}]}' }},
        ],
    }
    monkeypatch.setattr(observation_api, "configmaps", lambda component: documents[component])

    node = observation_api.load_observations()["nodes"]["r640"]

    assert node["networkStatus"]["frr"]["state"] == "active"
    assert node["measurement"]["measurements"][0]["symbol"] == "n_peer"
    assert [item["sourcePlane"] for item in node["networkQuality"]] == ["host", "pod"]
    assert node["networkQuality"][1]["dns"][0]["protocol"] == "udp"


def test_observation_cache_coalesces_page_requests(monkeypatch):
    calls = []
    observation_api._CACHE.clear()
    monkeypatch.setattr(observation_api, "load_observations", lambda: calls.append(1) or {"nodes": {}})

    assert observation_api.observations() == {"nodes": {}}
    assert observation_api.observations() == {"nodes": {}}
    assert calls == [1]


def service_npa():
    return {"metadata": {"name": "tls-scoped", "uid": "npa-uid", "generation": 4, "resourceVersion": "51"},
            "spec": {"subjectRef": {"apiVersion": "v1", "kind": "Service", "namespace": "canary", "name": "api"},
                     "scope": {"sourceNode": "domain-ex", "targetId": "canary-cn", "endpoint": "192.0.2.1",
                               "paddingBytes": [0, 2048], "targetConfigurationDigest": "digest"}},
            "status": {"state": "Ready", "observedAt": "2026-11-23T00:00:00Z", "validUntil": "2026-11-23T00:01:00Z",
                       "conditions": [{"type": "EvidenceReady", "status": "True", "reason": "Complete"}],
                       "serviceEvidence": {"definition": "tls-transfer-v1", "complete": True},
                       "pathEvidence": {"currentPathMeasured": True, "reachable": True}}}


def test_service_snapshot_retains_actual_scope_revisions_and_independent_expiry(monkeypatch):
    item = service_npa()
    monkeypatch.setattr(observation_api, "service_assessments", lambda: {"items": [item], "truncated": False})
    now = observation_api.parse_time("2026-11-23T00:00:30Z")
    result = observation_api.service_snapshot("canary", "api", now)
    assessment = result["assessments"][0]
    assert assessment["assessmentRef"]["uid"] == "npa-uid"
    assert assessment["scope"] == item["spec"]["scope"]
    assert assessment["fresh"] is True
    expired = observation_api.service_snapshot("canary", "api", now + 60)["assessments"][0]
    assert expired["state"] == "Stale" and expired["fresh"] is False
    # Raw producer condition is never renamed to an admission/eligibility verdict.
    assert expired["reportedEvidenceReady"] is True
    assert "eligible" not in expired
    assert observation_api.service_snapshot("other", "api", now)["state"] == "Unknown"
    item["metadata"]["deletionTimestamp"] = "2026-11-23T00:00:30Z"
    assert observation_api.service_snapshot("canary", "api", now)["assessments"][0]["state"] == "Deleting"


def test_service_reader_uses_formal_api_and_preserves_incomplete_list(monkeypatch):
    observation_api._CACHE.clear()
    paths = []
    monkeypatch.setattr(observation_api, "kube_get", lambda path: paths.append(path) or
                        {"items": [service_npa(), {"spec": {"subjectRef": {"kind": "Node"}}}],
                         "metadata": {"continue": "next"}})
    document = observation_api.service_assessments()
    assert len(document["items"]) == 1 and document["truncated"] is True
    assert paths == ["/apis/networking.advfab.org/v1alpha2/networkpathassessments?limit=200"]


def test_service_http_contract_does_not_require_node_inventory(monkeypatch):
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    monkeypatch.setattr(observation_api, "service_assessments", lambda: {"items": [service_npa()], "truncated": False})
    monkeypatch.setattr(observation_api, "observations", lambda: (_ for _ in ()).throw(AssertionError("local Node lookup")))
    server = ThreadingHTTPServer(("127.0.0.1", 0), observation_api.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:%d" % server.server_port
        with urllib.request.urlopen(base + "/api/v1/subjects?kind=Service") as response:
            assert json.load(response)["items"] == [{"kind": "Service", "namespace": "canary", "name": "api"}]
        with urllib.request.urlopen(base + "/api/v1/subjects/service/canary/api/snapshot") as response:
            document = json.load(response)
        assert document["kind"] == "Service"
        assert document["assessments"][0]["scope"]["sourceNode"] == "domain-ex"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
