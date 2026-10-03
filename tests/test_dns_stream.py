import ast
import time
from pathlib import Path
from unittest.mock import Mock
import unittest

source = Path(__file__).resolve().parents[1] / "charts/re8ch-advanced-fabric/files/conformance-probe.py"
tree = ast.parse(source.read_text())
ns = {"time": time}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "recv_exact"], type_ignores=[]), str(source), "exec"), ns)


class DNSStreamTest(unittest.TestCase):
    def test_fragmented_tcp_length_is_reassembled(self):
        client = Mock()
        client.recv.side_effect = [b"\x00", b"\x20"]
        assert ns["recv_exact"](client, 2, time.monotonic() + 2) == b"\x00\x20"


    def test_eof_is_failure_instead_of_unbounded_cpu_loop(self):
        client = Mock()
        client.recv.side_effect = [b"x", b""]
        with self.assertRaisesRegex(ValueError, "truncated"):
            ns["recv_exact"](client, 10, time.monotonic() + 2)
        assert client.recv.call_count == 2


    def test_total_deadline_is_bounded_even_with_trickle_bytes(self):
        client = Mock()
        with self.assertRaises(TimeoutError):
            ns["recv_exact"](client, 10, time.monotonic() - 1)
        client.recv.assert_not_called()
