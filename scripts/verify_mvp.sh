#!/usr/bin/env bash
set -euo pipefail

namespace="${1:-advanced-fabric}"
timeout="${ADVFAB_VERIFY_TIMEOUT:-180s}"
instance="${ADVFAB_INSTANCE:-advanced-fabric}"
service="${ADVFAB_OBSERVATION_SERVICE:-advanced-fabric-observation-api}"

command -v kubectl >/dev/null 2>&1 || {
  echo "kubectl is required" >&2
  exit 2
}

echo "Checking AdvFab CRDs"
kubectl get crd advancedfabrics.networking.advfab.org >/dev/null
kubectl get crd networkpathassessments.networking.advfab.org >/dev/null

echo "Waiting for controller and node observers"
kubectl -n "$namespace" rollout status deployment/advanced-fabric-controller --timeout="$timeout"
kubectl -n "$namespace" rollout status daemonset/advanced-fabric-agent --timeout="$timeout"
kubectl -n "$namespace" rollout status daemonset/advanced-fabric-pod-conformance --timeout="$timeout"

echo "Checking observe-only safety boundary"
document="$(kubectl get advancedfabric.networking.advfab.org "$instance" -o json)"
ADVANCED_FABRIC_DOCUMENT="$document" python3 - <<'PY'
import json
import os

document = json.loads(os.environ["ADVANCED_FABRIC_DOCUMENT"])
spec = document.get("spec", {})
if spec.get("mode") != "observe-only" or spec.get("applyEnabled") is not False:
    raise SystemExit("MVP verification refuses a mutation-enabled AdvancedFabric")
api = document.get("status", {}).get("observationAPI", {})
service_ref = api.get("serviceRef", {})
if api.get("ready") is not True or not service_ref.get("name"):
    raise SystemExit("AdvancedFabric has not advertised a ready status.observationAPI.serviceRef")
print("observe-only=True observation-service=%s" % service_ref["name"])
PY

proxy="/api/v1/namespaces/${namespace}/services/http:${service}:8080/proxy"
echo "Checking the public Observation API"
health="$(kubectl get --raw "${proxy}/healthz")"
ADVFAB_RESPONSE="$health" python3 - <<'PY'
import json
import os

response = json.loads(os.environ["ADVFAB_RESPONSE"])
if response.get("ready") is not True or response.get("apiVersion") != "v1":
    raise SystemExit("Observation API health contract is not ready")
PY

subjects="$(kubectl get --raw "${proxy}/api/v1/subjects")"
ADVFAB_RESPONSE="$subjects" python3 - <<'PY'
import json
import os

response = json.loads(os.environ["ADVFAB_RESPONSE"])
items = response.get("items")
if response.get("apiVersion") != "v1" or not isinstance(items, list):
    raise SystemExit("Observation API subjects contract is invalid")
if not items:
    raise SystemExit("Observation API is ready but no node observation has been published")
states = {item.get("state", "Unknown") for item in items}
print("subjects=%d states=%s" % (len(items), ",".join(sorted(states))))
PY

echo "AdvFab external MVP is ready"
