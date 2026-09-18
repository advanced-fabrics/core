import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "charts/re8ch-advanced-fabric/files/virtual-ingress-controller.py"
spec = importlib.util.spec_from_file_location("virtual_ingress", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def ingress(annotations=None, path_type="Prefix"):
    return {"metadata": {"name": "studio", "namespace": "supabase", "uid": "uid-1",
                         "annotations": annotations or {}},
            "spec": {"ingressClassName": "advanced-fabric", "rules": [{"host": "supabase.example.com",
                      "http": {"paths": [{"path": "/", "pathType": path_type, "backend": {"service": {
                          "name": "kong", "port": {"number": 8000}}}}]}}]}}


class VirtualIngressTest(unittest.TestCase):
    def test_chart_exposes_virtual_ingress_placement_and_disruption_contract(self):
        template = (SCRIPT.parents[1] / "templates/virtual-ingress.yaml").read_text()
        values = (SCRIPT.parents[1] / "values.yaml").read_text()
        for field in ("replicas", "pdbMinAvailable", "nodeSelector", "affinity",
                      "tolerations", "topologySpreadConstraints"):
            self.assertIn(field, template)
            self.assertIn(field + ":", values)
        self.assertIn("maxUnavailable: 1, maxSurge: 0", template)

    def test_runtime_rbac_can_read_the_adoption_gateway(self):
        runtime = (SCRIPT.parents[1] / "templates/advanced-fabric-runtime.yaml").read_text()
        self.assertIn("resources: [gateways]", runtime)
        self.assertIn("verbs: [get, list, watch]", runtime)

    def test_translates_standard_ingress_to_owned_httproute(self):
        route = module.translate(ingress({"traefik.ingress.kubernetes.io/router.tls": "true"}))
        self.assertEqual(route["metadata"]["ownerReferences"][0]["uid"], "uid-1")
        self.assertEqual(route["spec"]["parentRefs"][0]["name"], "re8ch-gateway-canary")
        self.assertEqual(route["spec"]["hostnames"], ["supabase.example.com"])
        self.assertEqual(route["spec"]["rules"][0]["backendRefs"], [{"name": "kong", "port": 8000}])

    def test_rejects_traefik_middleware_instead_of_silently_changing_behavior(self):
        with self.assertRaisesRegex(ValueError, "unsupported Traefik annotations"):
            module.translate(ingress({"traefik.ingress.kubernetes.io/router.middlewares": "auth@kubernetescrd"}))

    def test_rejects_implementation_specific_path(self):
        item = ingress(path_type="ImplementationSpecific")
        item["spec"]["rules"][0]["http"]["paths"][0]["path"] = "/literal"
        route = module.translate(item)
        self.assertEqual(route["spec"]["rules"][0]["matches"][0]["path"],
                         {"type": "PathPrefix", "value": "/literal"})

    def test_rejects_regex_like_implementation_specific_path(self):
        item = ingress(path_type="ImplementationSpecific")
        item["spec"]["rules"][0]["http"]["paths"][0]["path"] = "/items/(.*)"
        with self.assertRaisesRegex(ValueError, "not a literal prefix"):
            module.translate(item)

    def test_gateway_parent_refs_select_matching_http_and_https_listeners(self):
        gateway = {"spec": {"listeners": [
            {"name": "http", "protocol": "HTTP"},
            {"name": "supabase-https", "protocol": "HTTPS", "hostname": "supabase.example.com"},
            {"name": "other-https", "protocol": "HTTPS", "hostname": "other.example.com"}]}}
        refs = module.gateway_parent_refs(gateway, ["supabase.example.com"])
        self.assertEqual([item["sectionName"] for item in refs], ["http", "supabase-https"])

    def test_route_ready_requires_accepted_and_resolved_refs_for_current_generation(self):
        route = {"metadata": {"generation": 2}, "status": {"parents": [{"conditions": [
            {"type": "Accepted", "status": "True", "observedGeneration": 2},
            {"type": "ResolvedRefs", "status": "True", "observedGeneration": 2}]}]}}
        self.assertTrue(module.route_ready(route))
        route["status"]["parents"][0]["conditions"][1]["status"] = "False"
        self.assertFalse(module.route_ready(route))

    def test_accepts_route_owned_by_exact_source_ingress_during_controller_migration(self):
        desired = module.translate(ingress())
        existing = {"metadata": {"ownerReferences": [{
            "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
            "name": "studio", "uid": "uid-1", "controller": True
        }]}}
        self.assertTrue(module.owned_by_source_ingress(existing, desired))

    def test_rejects_route_owned_by_different_ingress_uid(self):
        desired = module.translate(ingress())
        existing = {"metadata": {"ownerReferences": [{
            "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
            "name": "studio", "uid": "recreated-uid", "controller": True
        }]}}
        self.assertFalse(module.owned_by_source_ingress(existing, desired))

    def test_managed_label_remains_valid_owner_signal(self):
        desired = module.translate(ingress())
        existing = {"metadata": {"labels": {module.MANAGED_LABEL: "true"}}}
        self.assertTrue(module.owned_by_source_ingress(existing, desired))
