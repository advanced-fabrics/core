import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_component_standard", ROOT / "scripts/validate_component_standard.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ComponentStandardTests(unittest.TestCase):
    def test_repository_satisfies_declared_standard(self):
        result = MODULE.validate()
        self.assertEqual(result["component"], "advanced-fabric")
        self.assertEqual(result["status"], "valid")
        self.assertIn("helm-chart", result["artifacts"])


if __name__ == "__main__":
    unittest.main()
