import unittest
"""Multi-pool changes must converge without promoting legacy CIDRs or stale reads."""
import ast
import copy
import ipaddress
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "charts/re8ch-advanced-fabric/files/controller.py"
tree = ast.parse(SOURCE.read_text())
namespace = {"ipaddress": ipaddress}
exec(compile(ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                             and node.name == "allocation_inventory"], type_ignores=[]),
             str(SOURCE), "exec"), namespace)
observe = namespace["allocation_inventory"]


def node(allocated=None, rv="1"):
    ipam = {"podCIDRs": ["10.42.1.0/24"]}
    if allocated is not None:
        ipam["pools"] = {"allocated": allocated,
                         "requested": [{"pool": "unused", "needed": {"ipv4-addrs": 8}}]}
    return {"metadata": {"name": "node-a", "uid": "uid-a", "resourceVersion": rv},
            "spec": {"ipam": ipam}}


DECLARED = [{"name": "node-a", "podCIDR": "10.42.1.0/24", "role": "spine"}]



class AllocationInventoryTest(unittest.TestCase):
    def test_allocation_add_release_and_empty_converge_without_spec_rewrite(self):
        source = copy.deepcopy(DECLARED)
        first = node([{"pool": "apps", "cidrs": ["10.68.1.0/24"]}])
        a = observe(source, [first], "t1")[0]
        assert a["podCIDR"] == "10.42.1.0/24"
        assert a["podCIDRs"] == ["10.68.1.0/24"]
        first["spec"]["ipam"]["pools"]["allocated"].append(
            {"pool": "system", "cidrs": ["10.64.1.0/24", "fd00:1::/64"]})
        first["metadata"]["resourceVersion"] = "2"
        b = observe(source, [first], "t2")[0]
        assert b["podCIDRs"] == ["10.64.1.0/24", "10.68.1.0/24", "fd00:1::/64"]
        assert b["allocationEvidence"]["sourceRef"]["resourceVersion"] == "2"
        first["spec"]["ipam"]["pools"]["allocated"] = []
        c = observe(source, [first], "t3")[0]
        assert c["podCIDRs"] == []
        assert c["allocationEvidence"]["state"] == "Observed"
        assert source == DECLARED
        assert a["podCIDRs"] == ["10.68.1.0/24"]


    def test_read_failure_missing_deleted_and_invalid_are_unknown_not_legacy_fallback(self):
        deleted = node()
        deleted["metadata"]["deletionTimestamp"] = "now"
        invalid = node([{"pool": "apps", "cidrs": ["0.0.0.1/24"]}])
        for items, error in [([], None), ([deleted], None), ([node()], "AllocationReadUnavailable"),
                             ([invalid], None)]:
            result = observe(DECLARED, items, "now", error)[0]
            assert result["podCIDRs"] == []
            assert result["allocationEvidence"]["state"] == "Unknown"


    def test_legacy_only_cilium_ipam_is_explicitly_attributed(self):
        result = observe(DECLARED, [node()], "now")[0]
        assert result["podCIDRs"] == ["10.42.1.0/24"]
        assert result["allocationEvidence"]["sourceField"] == "spec.ipam.podCIDRs"
        assert result["allocationEvidence"]["sourceRef"]["uid"] == "uid-a"


    def test_recreated_node_uses_new_identity_and_allocations_not_cached_state(self):
        old = node([{"pool": "apps", "cidrs": ["10.68.1.0/24"]}])
        observe(DECLARED, [old], "before")
        new = node([{"pool": "apps", "cidrs": ["10.68.9.0/24"]}], "1")
        new["metadata"]["uid"] = "uid-recreated"
        result = observe(DECLARED, [new], "after")[0]
        assert result["podCIDRs"] == ["10.68.9.0/24"]
        assert result["allocationEvidence"]["sourceRef"]["uid"] == "uid-recreated"
