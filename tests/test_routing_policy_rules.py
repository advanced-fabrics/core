import ast
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_make_api_transaction():
    path = ROOT / "charts/re8ch-advanced-fabric/files/controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "make_api_transaction")
    namespace = {"hashlib": hashlib, "json": json}
    exec(compile(ast.Module(body=[selected], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["make_api_transaction"]


class RoutingPolicyRulesTest(unittest.TestCase):
    def test_rules_are_checksum_bound(self):
        rule = {
            "priority": 11520,
            "destination": "10.250.0.0/24",
            "protocol": "tcp",
            "destinationPort": "2379-2380",
            "table": "main",
        }
        transaction = load_make_api_transaction()(
            "spine-a", {"vip": "10.250.0.1/32"}, {"routingPolicyRules": [rule]}, True
        )
        self.assertEqual([rule], transaction["spec"]["routingPolicyRules"])
        canonical = json.dumps(transaction["spec"], sort_keys=True, separators=(",", ":"))
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), transaction["checksum"])

    def test_agent_reconciles_rules_before_dynamic_routes(self):
        script = (ROOT / "charts/re8ch-advanced-fabric/files/host-agent.sh").read_text(encoding="utf-8")
        rules = script.split("manage_routing_policy_rules()", 1)[1].split("manage_frr_import_prefixes()", 1)[0]
        self.assertIn('ip rule add priority "${priority}" to "${destination}"', rules)
        self.assertIn('ipproto "${protocol}" dport "${port}" lookup "${table}"', rules)
        self.assertIn('/var/lib/advanced-fabric/routing-policy-rules.json', rules)
        self.assertIn('ip rule show priority "${priority}"', rules)
        self.assertIn('while host ip rule del priority "${priority}"', rules)
        apply = script.split('if [ "${apply}" != true ]; then', 1)[1].split('if [ "${guarded}"', 1)[0]
        self.assertLess(apply.index("manage_fallback_routes apply"), apply.index("manage_routing_policy_rules apply"))
        self.assertLess(apply.index("manage_routing_policy_rules apply"), apply.index("manage_wireguard_allowed_ips apply"))

    def test_schema_requires_complete_rule_contract(self):
        schema = json.loads((ROOT / "charts/re8ch-advanced-fabric/values.schema.json").read_text(encoding="utf-8"))
        operations = schema["properties"]["advancedFabric"]["properties"]["controlPlaneApi"]["properties"]["nodeOperations"]
        rule = operations["items"]["properties"]["routingPolicyRules"]["items"]
        self.assertTrue(operations["items"]["properties"]["routingPolicyRules"]["uniqueItems"])
        self.assertFalse(rule["additionalProperties"])
        self.assertEqual({"priority", "destination", "protocol", "destinationPort", "table"}, set(rule["required"]))
