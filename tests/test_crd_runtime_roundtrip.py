"""Render actual chart values through the CRD's structural pruning boundary."""
import copy
from pathlib import Path
import subprocess
import unittest

import yaml

CHART = Path(__file__).resolve().parents[1] / 'charts/re8ch-advanced-fabric'


def prune(value, schema):
    """Structural object/list pruning; preserve-unknown recurses at declared fields.

    This models the Kubernetes pruning rule, not API-server validation/defaulting.
    The roundtrip exercises the chart's real rendered spec and shipped CRD together.
    """
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        additional = schema.get('additionalProperties')
        result = {}
        for key, item in value.items():
            if key in properties:
                result[key] = prune(item, properties[key])
            elif isinstance(additional, dict):
                result[key] = prune(item, additional)
            elif schema.get('x-kubernetes-preserve-unknown-fields') or additional is True:
                result[key] = copy.deepcopy(item)
        return result
    if isinstance(value, list):
        return [prune(item, schema.get('items', {})) for item in value]
    return copy.deepcopy(value)


class RuntimeSchemaRoundtripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = subprocess.check_output([
            'helm', 'template', 'advanced-fabric', str(CHART), '--include-crds',
            '--set', 'advancedFabric.enabled=true',
            '--set', 'advancedFabric.dns.enabled=true',
            '--set', 'advancedFabric.virtualIngress.enabled=true',
            '--set', 'advancedFabric.componentAPI.port=9443',
            '--set', 'advancedFabric.componentAPI.serviceName=custom-observation-api',
        ], text=True)
        documents = [d for d in yaml.safe_load_all(output) if d]
        cls.spec = next(d['spec'] for d in documents if d['kind'] == 'AdvancedFabric')
        crd = next(d for d in documents if d['kind'] == 'CustomResourceDefinition'
                   and d['spec']['names']['kind'] == 'AdvancedFabric')
        cls.schema = next(v for v in crd['spec']['versions'] if v['storage'])[
            'schema']['openAPIV3Schema']['properties']['spec']

    def test_actual_rendered_spec_survives_structural_pruning(self):
        self.assertEqual(prune(self.spec, self.schema), self.spec)
        self.assertTrue(self.spec['dns']['enabled'])
        self.assertTrue(self.spec['virtualIngress']['enabled'])
        self.assertEqual(self.spec['componentAPI']['port'], 9443)
        self.assertEqual(self.spec['componentAPI']['serviceName'], 'custom-observation-api')

    def test_runtime_nested_configuration_is_preserved_but_unknown_root_is_not(self):
        spec = copy.deepcopy(self.spec)
        spec['dns']['futureProviderSetting'] = {'nested': ['example.invalid']}
        spec['virtualIngress']['futureAdapterSetting'] = {'nested': [True, 7]}
        spec['notDeclaredInSchema'] = {'mustBePruned': True}
        expected = copy.deepcopy(spec)
        del expected['notDeclaredInSchema']
        self.assertEqual(prune(spec, self.schema), expected)

    def test_regression_detects_each_previously_pruned_runtime_field(self):
        for path in [('dns',), ('virtualIngress',),
                     ('componentAPI', 'port'), ('componentAPI', 'serviceName')]:
            with self.subTest(path=path):
                schema = copy.deepcopy(self.schema)
                properties = schema['properties']
                for key in path[:-1]:
                    properties = properties[key]['properties']
                del properties[path[-1]]
                self.assertNotEqual(prune(self.spec, schema), self.spec)

    def test_component_api_port_has_tcp_port_bounds(self):
        port = self.schema['properties']['componentAPI']['properties']['port']
        self.assertEqual(port, {'type': 'integer', 'minimum': 1, 'maximum': 65535})
        self.assertEqual(self.schema['properties']['componentAPI']['properties'][
            'serviceName'], {'type': 'string'})


if __name__ == '__main__':
    unittest.main()
