import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


class ExternalMVPTests(unittest.TestCase):
    def test_profile_is_observe_only_and_publishes_measurements(self):
        values = yaml.safe_load((ROOT / "examples/mvp-values.yaml").read_text())
        advanced = values["advancedFabric"]
        self.assertTrue(advanced["enabled"])
        self.assertEqual(advanced["mode"], "observe-only")
        self.assertFalse(advanced["applyEnabled"])
        self.assertTrue(advanced["networkQuality"]["enabled"])
        self.assertFalse(advanced["networkQuality"]["enforcementEnabled"])
        self.assertFalse(values["routerOS"]["enabled"])
        self.assertFalse(values["mihomoGateway"]["enabled"])

    def test_verifier_checks_live_api_and_rejects_empty_subjects(self):
        script = (ROOT / "scripts/verify_mvp.sh").read_text()
        self.assertIn("rollout status deployment/advanced-fabric-controller", script)
        self.assertIn("services/http:${service}:8080/proxy", script)
        self.assertIn("no node observation has been published", script)
        self.assertIn('spec.get("mode") != "observe-only"', script)

    def test_quickstart_does_not_claim_missing_evidence_is_healthy(self):
        guide = (ROOT / "docs/MVP-QUICKSTART.md").read_text()
        self.assertIn("Partial", guide)
        self.assertIn("never substitutes demo values", guide)


if __name__ == "__main__":
    unittest.main()
