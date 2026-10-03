"""Fail-closed Lease election for the Advanced Fabric reconciler.

Only the elected pod may write. The local write window is much shorter than
the Kubernetes Lease lifetime, so a stopped renewer cannot overlap a successor.
"""

import datetime
import email.utils
import json
import threading
import time
import urllib.error
import urllib.request


LEASE_NAME = "advanced-fabric-controller"
LEASE_SECONDS = 30
WRITE_WINDOW_SECONDS = 8


class LeaderLease:
    def __init__(self, base, token, context, namespace, identity):
        if not namespace or not identity:
            raise ValueError("pod namespace and name are required for Lease election")
        self.base = base
        self.token = token
        self.context = context
        self.namespace = namespace
        self.identity = identity
        self.path = f"/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases/{LEASE_NAME}"
        self.collection = f"/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases"
        self.deadline = 0.0
        self.lock = threading.Lock()

    def may_write(self):
        with self.lock:
            return time.monotonic() < self.deadline

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, context=self.context, timeout=5) as response:
            server_date = response.headers.get("Date")
            if not server_date:
                raise RuntimeError("API server omitted Date; cannot evaluate Lease expiry")
            server_now = email.utils.parsedate_to_datetime(server_date).astimezone(datetime.timezone.utc)
            return json.load(response), server_now

    def tick(self):
        try:
            lease, now = self._request("GET", self.path)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                self._clear()
                return False
            # A create conflict simply means another pod won this round.
            try:
                _, now = self._request("GET", "/version")
                body = self._body(now)
                self._request("POST", self.collection, body)
            except (urllib.error.HTTPError, OSError, ValueError, RuntimeError):
                self._clear()
                return False
            self._grant()
            return True
        except (OSError, ValueError, RuntimeError):
            self._clear()
            return False

        spec = lease.get("spec", {})
        holder = spec.get("holderIdentity", "")
        renew = spec.get("renewTime") or spec.get("acquireTime")
        try:
            renewed_at = datetime.datetime.fromisoformat(renew.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            renewed_at = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        lifetime = int(spec.get("leaseDurationSeconds") or LEASE_SECONDS)
        expired = (now - renewed_at).total_seconds() > lifetime + 5
        if holder != self.identity and not expired:
            self._clear()
            return False
        body = self._body(now, lease)
        try:
            self._request("PUT", self.path, body)
        except (urllib.error.HTTPError, OSError, ValueError, RuntimeError):
            self._clear()
            return False
        self._grant()
        return True

    def _body(self, now, previous=None):
        spec = (previous or {}).get("spec", {})
        holder = spec.get("holderIdentity")
        metadata = {"name": LEASE_NAME, "namespace": self.namespace}
        if previous:
            metadata["resourceVersion"] = previous["metadata"]["resourceVersion"]
        return {"apiVersion": "coordination.k8s.io/v1", "kind": "Lease",
                "metadata": metadata,
                "spec": {"holderIdentity": self.identity,
                         "leaseDurationSeconds": LEASE_SECONDS,
                         "acquireTime": spec.get("acquireTime") if holder == self.identity else now.isoformat(),
                         "renewTime": now.isoformat(),
                         "leaseTransitions": int(spec.get("leaseTransitions") or 0) +
                         (1 if holder and holder != self.identity else 0)}}

    def _grant(self):
        with self.lock:
            self.deadline = time.monotonic() + WRITE_WINDOW_SECONDS

    def _clear(self):
        with self.lock:
            self.deadline = 0.0

    def run(self):
        while True:
            self.tick()
            time.sleep(3)
