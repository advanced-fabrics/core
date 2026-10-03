"""The HA controller can reach its local API without the Service datapath."""

from pathlib import Path
import subprocess

import yaml


CHART = Path(__file__).resolve().parents[1] / "charts/re8ch-advanced-fabric"


def controller_env(node_local):
    output = subprocess.check_output(
        [
            "helm", "template", "advanced-fabric", str(CHART),
            "--set", "advancedFabric.enabled=true",
            "--set", f"advancedFabric.controller.useNodeLocalAPI={str(node_local).lower()}",
        ],
        text=True,
    )
    deployment = next(
        resource for resource in yaml.safe_load_all(output)
        if resource and resource.get("kind") == "Deployment"
        and resource["metadata"]["name"] == "advanced-fabric-controller"
    )
    return {
        item["name"]: item
        for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }


def test_node_local_api_uses_pod_host_ip_and_direct_port():
    env = controller_env(True)
    assert env["API_HOST"]["valueFrom"]["fieldRef"]["fieldPath"] == "status.hostIP"
    assert env["API_PORT"]["value"] == "6443"


def test_default_keeps_kubernetes_service_discovery():
    env = controller_env(False)
    assert "API_HOST" not in env
    assert "API_PORT" not in env
