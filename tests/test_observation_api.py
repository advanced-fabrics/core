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
