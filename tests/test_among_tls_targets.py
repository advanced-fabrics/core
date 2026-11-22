"""Contract tests for exact Among references and collector handoff."""
import ast
import copy
import datetime
import hashlib
import ipaddress
import json
import re
import time
import unittest
import urllib.error
import subprocess
import tempfile
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOW = 1800000000
AT = datetime.datetime.fromtimestamp(NOW - 10, datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
TARGET = {'name': 'canary', 'sourceNodes': ['r640'], 'discovery': {
    'source': 'AmongCluster', 'clusterRef': 'publisher',
    'serviceRef': 'spiffe://re8ch.internal/ns/af-canary/service/transfer', 'protocol': 'https',
    'endpointId': 'cn', 'advertisementRef': {'namespace': 'peering', 'name': 'ad', 'uid': 'ad-uid'},
    'importedServiceRef': {'namespace': 'peering', 'name': 'import', 'uid': 'import-uid'}}}
EXPORT = {'endpoints': [{'id': 'cn', 'site': 'r640', 'region': 'cn', 'protocol': 'https',
    'address': '192.0.2.1', 'port': 443, 'hostname': 'canary.example.com', 'path': '/transfer', 'revision': 'one'}]}
AD = {'metadata': {'namespace': 'peering', 'name': 'ad', 'uid': 'ad-uid', 'generation': 3, 'annotations': {'peering.re8ch.com/last-published-at': AT}},
      'spec': {'publisherRef': 'publisher', 'serviceIdentity': TARGET['discovery']['serviceRef'],
               'protocol': 'https', 'targetPeers': ['peer'], 'ttlSeconds': 60, 'publicIngress': EXPORT}}
IMPORTED = {'metadata': {'namespace': 'peering', 'name': 'import', 'uid': 'import-uid', 'generation': 2},
            'spec': {'advertisementRef': 'ad', 'peerRef': 'peer'},
            'status': {'state': 'Ready', 'observedGeneration': 2, 'advertisementGeneration': 3,
                       'advertisementUID': 'ad-uid', 'publicIngress': EXPORT}}

def load(file, names):
    source = ROOT / 'charts/re8ch-advanced-fabric/files' / file
    ns = dict(datetime=datetime, hashlib=hashlib, ipaddress=ipaddress, json=json, re=re,
              time=time, urllib=__import__('urllib'), API_GROUP='networking.advfab.org',
              MANAGED_BY='advanced-fabric', TIMEOUT=2)
    tree = ast.parse(source.read_text())
    exec(compile(ast.Module(body=[fn for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name in names],
                            type_ignores=[]), str(source), 'exec'), ns)
    return ns

C = load('controller.py', {'resolve_among_tls_targets', 'parse_time', 'condition',
    'withdrawn_among_tls_documents', 'tls_target_configuration_digest', 'tls_service_evidence_documents'})
P = load('conformance-probe.py', {'tls_targets', 'planned_tls_targets', 'parse_observed_time'})

class AmongTLSContract(unittest.TestCase):
    def setUp(self):
        self.ad, self.imported = copy.deepcopy(AD), copy.deepcopy(IMPORTED)
        self.calls = []
    def get(self, path):
        self.calls.append(path)
        return self.ad if '/serviceadvertisements/' in path else self.imported
    def resolve(self, targets=None, now=NOW):
        return C['resolve_among_tls_targets'](targets or [TARGET], self.get, now)
    def test_address_revision_change_creates_new_probe_and_digest_without_rv_binding(self):
        first, failures = self.resolve()
        self.assertFalse(failures)
        self.assertEqual(first[0]['targetService'], 'af-canary/transfer')
        self.ad['metadata']['resourceVersion'] = 'heartbeat-only'
        self.assertEqual(self.resolve()[0], first)
        self.ad['spec']['publicIngress']['endpoints'][0].update(address='192.0.2.2', revision='two')
        self.imported['status']['publicIngress'] = copy.deepcopy(self.ad['spec']['publicIngress'])
        second, failures = self.resolve()
        self.assertFalse(failures)
        self.assertNotEqual(first[0]['pathId'], second[0]['pathId'])
        self.assertNotEqual(C['tls_target_configuration_digest'](first[0]), C['tls_target_configuration_digest'](second[0]))
    def test_round_cache_limits_shared_references_to_two_gets(self):
        other = copy.deepcopy(TARGET); other['name'] = 'second'
        targets, failures = self.resolve([TARGET, other])
        self.assertEqual(len(targets), 2)
        self.assertEqual(len(self.calls), 2)
    def test_invalid_or_withdrawn_ad_never_returns_previous_target(self):
        changes = [lambda: self.ad['spec'].update(revoked=True),
                   lambda: self.ad['metadata'].update(uid='replaced'),
                   lambda: self.imported['status'].update(observedGeneration=1),
                   lambda: self.ad['spec']['publicIngress']['endpoints'][0].update(id='missing'),
                   lambda: self.imported['status'].update(publicIngress={}),
                   lambda: self.ad['spec'].update(serviceIdentity='spiffe://wrong/ns/a/service/b')]
        for change in changes:
            with self.subTest(change=change):
                self.setUp(); change()
                targets, failures = self.resolve()
                self.assertEqual(targets, [])
                docs = list(C['withdrawn_among_tls_documents'](failures, ['r640']))
                self.assertEqual(docs[0][0]['spec']['subjectRef']['namespace'], 'af-canary')
                self.assertEqual(docs[0][1]['state'], 'Stale')
                self.assertEqual(docs[0][1]['conditions'][0]['status'], 'False')
    def test_expiry_and_read_failure_fail_closed(self):
        self.assertEqual(self.resolve(now=NOW + 60)[0], [])
        def unavailable(path): raise urllib.error.URLError('timeout')
        targets, failures = C['resolve_among_tls_targets']([TARGET], unavailable, NOW)
        self.assertEqual(targets, []); self.assertEqual(failures[0]['reason'], 'AmongReadFailed')
    def test_plan_expiry_and_unavailable_plan_never_fall_back(self):
        targets, _ = self.resolve()
        plan = {'generatedAt': AT, 'tlsValidUntil': NOW + 10,
                'tlsTargets': [{k: v for k, v in target.items() if k != '_expiresAt'} for target in targets]}
        self.assertEqual(P['planned_tls_targets'](plan, NOW)[0]['endpoint'], '192.0.2.1')
        self.assertEqual(P['planned_tls_targets'](plan, NOW + 10), [])
        self.assertEqual(P['planned_tls_targets'](None, NOW), [])
    def test_old_endpoint_measurements_cannot_make_new_revision_ready(self):
        old = self.resolve()[0][0]
        record = {'measurementDefinitionId': 'tls-transfer-v1', 'targetId': 'canary',
            'targetService': old['targetService'], 'endpoint': old['endpoint'], 'port': 443,
            'serverName': old['serverName'], 'path': old['path'], 'sourceNode': 'r640',
            'observedAt': AT, 'success': True, 'totalMs': 1, 'statusCode': 200,
            'targetConfigurationDigest': C['tls_target_configuration_digest'](old)}
        measurements = {( 'r640', plane): {'fresh': True, 'tlsTransfers': [dict(record,
            sourcePlane=plane, paddingBytes=size) for size in (0, 2048)]} for plane in ('host', 'pod')}
        build = C['tls_service_evidence_documents']
        self.assertEqual(list(build([old], ['r640'], measurements, 120, NOW))[0][1]['state'], 'Ready')
        self.ad['spec']['publicIngress']['endpoints'][0]['revision'] = 'two'
        self.imported['status']['publicIngress'] = copy.deepcopy(self.ad['spec']['publicIngress'])
        new = self.resolve()[0][0]
        self.assertEqual(list(build([new], ['r640'], measurements, 120, NOW))[0][1]['state'], 'Unknown')
    def test_render_grants_only_exact_read_refs_and_defaults_disabled(self):
        chart = ROOT / 'charts/re8ch-advanced-fabric'
        values = {'advancedFabric': {'enabled': True, 'networkQuality': {'amongTlsTargets': [TARGET]}}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as file:
            yaml.safe_dump(values, file); file.flush()
            docs = list(yaml.safe_load_all(subprocess.check_output(['helm', 'template', 'test', str(chart), '-f', file.name], text=True)))
        role = next(doc for doc in docs if doc and doc.get('kind') == 'Role' and doc['metadata']['name'] == 'advanced-fabric-among-0')
        self.assertEqual(role['metadata']['namespace'], 'peering')
        self.assertEqual(role['rules'], [
            {'apiGroups': ['peering.re8ch.com'], 'resources': ['serviceadvertisements'], 'resourceNames': ['ad'], 'verbs': ['get']},
            {'apiGroups': ['peering.re8ch.com'], 'resources': ['importedservices'], 'resourceNames': ['import'], 'verbs': ['get']}])

if __name__ == '__main__': unittest.main()
