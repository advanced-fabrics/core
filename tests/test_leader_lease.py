import datetime
import copy
import importlib.util
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "charts/re8ch-advanced-fabric/files/leader_lease.py"
spec = importlib.util.spec_from_file_location("leader_lease", SCRIPT)
lease_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lease_module)
NOW = datetime.datetime(2026, 10, 3, 12, 0, tzinfo=datetime.timezone.utc)


class FakeLease(lease_module.LeaderLease):
    def __init__(self, current=None, fail_update=False):
        super().__init__("https://api", "token", None, "advanced-fabric", "pod-a")
        self.current = current
        self.fail_update = fail_update
        self.writes = []

    def _request(self, method, path, body=None):
        if method == "GET" and path == self.path:
            if self.current is None:
                raise urllib.error.HTTPError(path, 404, "missing", {}, None)
            return self.current, NOW
        if method == "GET":
            return {}, NOW
        self.writes.append((method, body))
        if self.fail_update:
            raise urllib.error.HTTPError(path, 409, "conflict", {}, None)
        self.current = copy.deepcopy(body)
        self.current["metadata"]["resourceVersion"] = "2"
        return body, NOW


def existing(holder, age):
    return {"metadata": {"name": "advanced-fabric-controller", "resourceVersion": "1"},
            "spec": {"holderIdentity": holder, "leaseDurationSeconds": 30,
                     "renewTime": (NOW - datetime.timedelta(seconds=age)).isoformat()}}


class LeaderLeaseTest(unittest.TestCase):
    def test_only_one_pod_can_acquire_unexpired_lease(self):
        lease = FakeLease(existing("pod-b", 10))
        self.assertFalse(lease.tick())
        self.assertFalse(lease.may_write())
        self.assertEqual(lease.writes, [])

    def test_expired_lease_can_be_taken_with_resource_version(self):
        lease = FakeLease(existing("pod-b", 40))
        self.assertTrue(lease.tick())
        self.assertTrue(lease.may_write())
        method, body = lease.writes[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(body["metadata"]["resourceVersion"], "1")
        self.assertEqual(body["spec"]["holderIdentity"], "pod-a")

    def test_conflict_revokes_write_permission(self):
        lease = FakeLease(existing("pod-a", 1))
        self.assertTrue(lease.tick())
        lease.fail_update = True
        self.assertFalse(lease.tick())
        self.assertFalse(lease.may_write())

    def test_local_write_window_expires_before_server_lease(self):
        lease = FakeLease()
        with patch.object(lease_module.time, "monotonic", return_value=100):
            self.assertTrue(lease.tick())
        with patch.object(lease_module.time, "monotonic", return_value=109):
            self.assertFalse(lease.may_write())

    def test_kubernetes_microtime_includes_fractional_seconds(self):
        lease = FakeLease()
        body = lease._body(NOW)
        self.assertEqual(body["spec"]["acquireTime"], "2026-10-03T12:00:00.000000Z")
        self.assertEqual(body["spec"]["renewTime"], "2026-10-03T12:00:00.000000Z")


if __name__ == "__main__":
    unittest.main()
