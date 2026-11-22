"""Real local TLS and bounded-transfer contract; no cluster or credentials."""
import ast
import concurrent.futures
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'charts/re8ch-advanced-fabric/files/conformance-probe.py'
ns = dict(json=json, os=os, re=re, ipaddress=ipaddress, socket=socket, ssl=ssl, time=time,
          concurrent=__import__('concurrent'), NODE='node-a', PLANE='pod', TIMEOUT=2,
          TLS_MAX_REQUEST_BYTES=8192, TLS_MAX_RESPONSE_BYTES=32768, TLS_MAX_HEADER_BYTES=8192)
names = {'tls_targets', 'tls_transfer', 'measure_tls_targets', 'prometheus_text',
         'labels', 'prometheus_escape', 'parse_observed_time'}
exec(compile(ast.Module(body=[n for n in ast.parse(SOURCE.read_text()).body
                              if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]),
             str(SOURCE), 'exec'), ns)


class LocalTLS:
    def __init__(self, context, response=None, stall=False, trickle=False):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.context, self.response, self.stall, self.trickle = context, response, stall, trickle
        self.request = b''
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            with self.listener.accept()[0] as raw:
                raw.settimeout(1)
                if self.stall:
                    time.sleep(.25)
                    return
                with self.context.wrap_socket(raw, server_side=True) as client:
                    while b'\r\n\r\n' not in self.request:
                        part = client.recv(4096)
                        if not part:
                            return
                        self.request += part
                    response = self.response or b'HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\nhealthy'
                    if self.trickle:
                        for byte in response:
                            client.sendall(bytes([byte]))
                            time.sleep(.015)
                    else:
                        # Fragment the status line to exercise bounded reassembly.
                        client.sendall(response[:4])
                        client.sendall(response[4:])
        except (OSError, ssl.SSLError):
            pass
        finally:
            self.listener.close()

    def close(self):
        self.listener.close()
        self.thread.join(timeout=1)


class TLSTransferTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('openssl'):
            raise unittest.SkipTest('openssl required to generate ephemeral test certificate')
        cls.directory = tempfile.TemporaryDirectory()
        cls.ca = str(Path(cls.directory.name) / 'public-ca.crt')
        key = str(Path(cls.directory.name) / 'ephemeral-test.key')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key,
                        '-out', cls.ca, '-subj', '/CN=probe.example', '-addext',
                        'subjectAltName=DNS:probe.example', '-days', '1'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.load_cert_chain(cls.ca, key)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def target(self, port, **changes):
        item = dict(name='api', targetService='service://example/api', endpoint='127.0.0.1',
                    port=port, serverName='probe.example', caFile=self.ca, required=True, sourceNodes=['node-a'])
        item.update(changes)
        return ns['tls_targets'](json.dumps([item]))[0]

    def probe(self, server, padding=2048, **changes):
        try:
            return ns['tls_transfer'](self.target(server.port, **changes), padding, time.monotonic() + 2)
        finally:
            server.close()

    def test_verified_complete_transfer_carries_scope_and_no_content_or_credentials(self):
        server = LocalTLS(self.server_context)
        with patch.object(socket, 'getaddrinfo', side_effect=AssertionError('DNS not allowed')):
            result = self.probe(server)
        self.assertTrue(result['success'])
        self.assertEqual((result['sourceNode'], result['sourcePlane']), ('node-a', 'pod'))
        self.assertEqual(result['targetService'], 'service://example/api')
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(result['bodyBytes'], 7)
        self.assertGreater(result['requestBytes'], 2048)
        self.assertGreater(result['responseBytes'], 7)
        self.assertNotIn('healthy', json.dumps(result))
        self.assertNotIn(b'Authorization:', server.request)
        self.assertNotIn(b'Cookie:', server.request)
        self.assertIn(b'X-Diagnostic-Padding: ' + b'x' * 2048, server.request)
        self.assertEqual(result['state'], 'Succeeded')

    def test_wrong_sni_and_untrusted_ca_are_failures(self):
        for changes in ({'serverName': 'wrong.example'}, {'caFile': None}):
            with self.subTest(changes=changes):
                result = self.probe(LocalTLS(self.server_context), **changes)
                self.assertFalse(result['success'])
                self.assertEqual(result['category'], 'tls')
                self.assertEqual(result['error'], 'SSLCertVerificationError')

    def test_tcp_connect_without_tls_transfer_is_not_healthy(self):
        result = self.probe(LocalTLS(self.server_context, stall=True), timeoutSeconds=.08)
        self.assertFalse(result['success'])
        self.assertIsNotNone(result['connectMs'])
        self.assertIsNone(result['handshakeMs'])
        self.assertEqual(result['category'], 'deadline')
        self.assertLess(result['totalMs'], 250)

    def test_request_deadline_does_not_reset_for_trickle_response(self):
        result = self.probe(LocalTLS(self.server_context, trickle=True), timeoutSeconds=.12)
        self.assertFalse(result['success'])
        self.assertEqual(result['category'], 'deadline')
        self.assertLess(result['totalMs'], 300)

    def test_incomplete_oversized_chunked_and_unexpected_status_fail_closed(self):
        cases = [
            (b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nx', 'http-framing'),
            (b'HTTP/1.1 200 OK\r\nContent-Length: 50000\r\n\r\n', 'response-limit'),
            (b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n', 'http-framing'),
            (b'HTTP/1.1 302 Found\r\nLocation: https://other.invalid/\r\nContent-Length: 0\r\n\r\n', 'http-status'),
            (b'HTTP/1.1 200 OK\r\nX-Large: ' + b'x' * 8192 + b'\r\n\r\n', 'response-limit'),
            (b'HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nxx', 'http-framing'),
        ]
        for response, category in cases:
            with self.subTest(category=category):
                result = self.probe(LocalTLS(self.server_context, response=response))
                self.assertFalse(result['success'])
                self.assertEqual(result['category'], category)
                self.assertLessEqual(result['responseBytes'], 32769)

    def test_connection_close_frame_is_read_to_completion(self):
        result = self.probe(LocalTLS(self.server_context, response=b'HTTP/1.1 200 OK\r\n\r\npublic'))
        self.assertTrue(result['success'])
        self.assertEqual(result['bodyBytes'], 6)

    def test_configuration_is_bounded_and_cannot_add_auth_or_dns_targets(self):
        base = dict(name='api', targetService='service://example/api', endpoint='127.0.0.1',
                    serverName='probe.example')
        invalid = [{'headers': {'Authorization': 'not-a-real-token'}}, {'endpoint': 'dns.example'},
                   {'path': '/version?token=not-real'}, {'path': '/\r\nInjected: x'},
                   {'paddingBytes': [0, 1, 2]}, {'paddingBytes': [4097]}, {'timeoutSeconds': 6},
                   {'caFile': '/var/run/secrets/kubernetes.io/serviceaccount/token'},
                   {'expectedStatuses': []}, {'port': True}, {'required': 'yes'},
                   {'sourceNodes': ['a', 'b', 'c', 'd']}, {'sourceNodes': ['a', 'a']}]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                ns['tls_targets'](json.dumps([{**base, **changes}]))
        with self.assertRaises(ValueError):
            ns['tls_targets'](json.dumps([{**base, 'name': str(i)} for i in range(5)]))
        with patch.dict(os.environ, {'TLS_PROBE_TARGETS': json.dumps([{**base, **invalid[0]}])}), \
                patch.object(socket, 'socket') as dial:
            result = ns['measure_tls_targets']()
        dial.assert_not_called()
        self.assertEqual(result[0]['category'], 'configuration')
        self.assertFalse(result[0]['success'])
        self.assertNotIn('not-a-real-token', json.dumps(result))

    def test_disabled_targets_do_not_make_connections(self):
        with patch.dict(os.environ, {'TLS_PROBE_TARGETS': '[]'}), patch.object(socket, 'socket') as dial:
            self.assertEqual(ns['measure_tls_targets'](), [])
        dial.assert_not_called()

    def test_expired_phase_budget_never_dials(self):
        with patch.object(socket, 'socket') as dial:
            result = ns['tls_transfer'](self.target(443), 0, time.monotonic() - 1)
        dial.assert_not_called()
        self.assertEqual(result['category'], 'deadline')

    def test_phase_concurrency_and_shared_budget_are_bounded(self):
        active, maximum = 0, 0
        lock, deadlines = threading.Lock(), []
        def transfer(target, padding, deadline):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                deadlines.append(deadline)
            time.sleep(.01)
            with lock:
                active -= 1
            return {'success': False, 'category': 'deadline'}
        targets = [dict(name='api' + str(i), targetService='service://example/api', endpoint='127.0.0.1',
                        serverName='probe.example', sourceNodes=['node-a']) for i in range(4)]
        with patch.dict(os.environ, {'TLS_PROBE_TARGETS': json.dumps(targets)}), \
                patch.dict(ns, {'tls_transfer': transfer}):
            start = time.monotonic()
            results = ns['measure_tls_targets']()
        self.assertEqual(len(results), 8)
        self.assertEqual(maximum, 2)
        self.assertEqual(len(set(deadlines)), 1)
        self.assertLessEqual(deadlines[0] - start, 20.1)

    def test_failed_transfer_exports_zero_not_healthy(self):
        result = self.probe(LocalTLS(self.server_context, stall=True), timeoutSeconds=.05)
        metrics = ns['prometheus_text']({'observedAt': result['observedAt'], 'tlsTransfers': [result]})
        success = next(line for line in metrics.splitlines() if line.startswith('advanced_fabric_tls_transfer_success'))
        self.assertTrue(success.endswith(' 0'))
        self.assertIn('target_service="service://example/api"', success)
        self.assertIn('category="deadline"', success)

    def test_unassigned_or_other_source_never_dials_or_claims_health(self):
        base = dict(name='api', targetService='service://example/api', endpoint='127.0.0.1',
                    serverName='probe.example')
        for assignment in ({}, {'sourceNodes': ['node-b']}):
            with self.subTest(assignment=assignment), \
                    patch.dict(os.environ, {'TLS_PROBE_TARGETS': json.dumps([{**base, **assignment}])}), \
                    patch.object(socket, 'socket') as dial:
                self.assertEqual(ns['measure_tls_targets'](), [])
            dial.assert_not_called()

    def test_unbounded_connection_close_body_stops_at_hard_response_limit(self):
        server = LocalTLS(self.server_context, response=b'HTTP/1.1 200 OK\r\n\r\n' + b'x' * 40000)
        result = self.probe(server)
        self.assertFalse(result['success'])
        self.assertEqual(result['category'], 'response-limit')
        self.assertEqual(result['responseBytes'], 32769)
