"""Exercise the actual shell pipeline and real jq, including bounded heap use."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'charts/re8ch-advanced-fabric/files/service-traffic-window.sh'
CHART = ROOT / 'charts/re8ch-advanced-fabric'


@unittest.skipUnless(shutil.which('jq'), 'real jq required')
class ServiceTrafficWindowTests(unittest.TestCase):
    def run_window(self, payload, rc=124):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / 'observation.json'
            previous = b'{"previous":"must survive failed collection"}\n'
            target.write_bytes(previous)
            (base / 'payload').write_bytes(payload)
            executable = base / 'timeout'
            executable.write_text('#!' + sys.executable + '\n' + '''
import os,pathlib,time,sys
p=pathlib.Path(os.environ['FIXTURE_DIR'])
marker=p/'calls'
if marker.exists():
 (p/'second-call').touch()
 time.sleep(60)
else:
 marker.touch()
 with (p/'payload').open('rb') as source:
  while chunk := source.read(8192):
   sys.stdout.buffer.write(chunk)
 sys.stdout.buffer.flush()
 sys.exit(int(os.environ['FIXTURE_RC']))
''')
            executable.chmod(0o755)
            date = base / 'date'
            date.write_text('#!' + sys.executable + '\n' + '''
import os,pathlib,sys
if '+%s' in sys.argv:
 p=pathlib.Path(os.environ['FIXTURE_DIR'])/'epoch'
 value=int(p.read_text())+1 if p.exists() else 100
 p.write_text(str(value));print(value)
else: print('2026-11-23T04:00:00Z')
''')
            date.chmod(0o755)
            env = dict(os.environ, PATH=str(base)+os.pathsep+os.environ['PATH'],
                       FIXTURE_DIR=str(base), FIXTURE_RC=str(rc),
                       SERVICE_TRAFFIC_TARGET=str(target), NODE_NAME='fixture-node',
                       SERVICE_TRAFFIC_WINDOW_SECONDS='1')
            process = subprocess.Popen(['sh', str(SCRIPT)], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                       start_new_session=True)
            try:
                deadline = time.monotonic()+8
                while not (base/'second-call').exists() and time.monotonic()<deadline:
                    if process.poll() is not None:
                        self.fail('collector unexpectedly exited: '+process.stderr.read().decode())
                    time.sleep(.02)
                self.assertTrue((base/'second-call').exists(), 'first window must finish')
                return target.read_bytes(), previous
            finally:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=3)

    def test_completed_window_counts_http_and_preserves_schema(self):
        payload = b'\n'.join([b'{"flow":{"l7":{"type":"REQUEST","http":{"method":"GET"}}}}',
                                b'{"flow":{"l7":{"type":1,"http":{"method":"POST"}}}}',
                                b'{"flow":{"l7":{"type":"RESPONSE","http":{"code":200}}}}',
                                b'{"flow":{"l7":{"type":3,"http":{"code":200}}}}',
                                b'{"flow":{"l4":{"TCP":{}}}}',
                                b'{"node_status":{"state":"connected"}}'])+b'\n'
        actual, _ = self.run_window(payload)
        result = json.loads(actual)
        self.assertEqual(result['schemaVersion'], 'networking.re8ch.com/service-traffic-window-v1alpha1')
        self.assertEqual(result['windowSeconds'], 1)
        self.assertEqual(result['samples'], [{'node':'fixture-node','receivedFlowEvents':5,
                         'requests':2,'observationPlane':'hubble',
                         'availableDimensions':['flowEvents','requests']}])

    def test_empty_completed_window_is_legitimate_zero(self):
        actual, _ = self.run_window(b'')
        self.assertEqual(json.loads(actual)['samples'][0]['receivedFlowEvents'], 0)

    def test_parse_errors_and_incomplete_capture_do_not_refresh_previous_state(self):
        for payload, rc in [(b'{"flow":{}}\nnot-json\n',124),
                            (b'{"flow":{}}\n{"flow":',124),
                            (b'{"flow":{}}\n{"lost_events":{"num_events_lost":3}}\n',124),
                            (b'{"lostEvents":{"numEventsLost":1}}\n',124),
                            (b'{"unexpected":"new-event-type"}\n',124),
                            (b'{"flow":{"l7":{"http":{}}}}\n',124),
                            (b'{"flow":{}}\n',1), (b'',0)]:
            with self.subTest(payload=payload, rc=rc):
                actual, previous = self.run_window(payload, rc)
                self.assertEqual(actual, previous)

    def test_real_jq_heap_does_not_scale_with_total_window_bytes(self):
        # Extract the actual product reducer, rather than reimplementing it.
        program = re.search(r"\| jq -n '(.*?)' >", SCRIPT.read_text(), re.S).group(1)
        event = json.dumps({'flow':{'l7':{'type':'REQUEST','http':{'method':'GET'}},'padding':'x'*768}}).encode()+b'\n'
        def measure(count):
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(['jq','-n',program], stdin=subprocess.PIPE,
                                           stdout=output, stderr=errors)
                failures=[]
                def feed():
                    try:
                        for _ in range(count): process.stdin.write(event)
                        process.stdin.close()
                    except BaseException as error: failures.append(error)
                writer=threading.Thread(target=feed);writer.start()
                _, status, usage=os.wait4(process.pid,0)
                process.returncode=os.waitstatus_to_exitcode(status)
                writer.join();self.assertEqual(failures,[])
                self.assertEqual(process.returncode,0)
                output.seek(0);self.assertEqual(json.load(output),{'flowEvents':count,'requests':count})
                return usage.ru_maxrss if sys.platform=='darwin' else usage.ru_maxrss*1024
        small, large = measure(1000), measure(250000)
        print(f'real jq peak RSS: 1000 events={small}B; 250000 events={large}B; '
              f'large input={len(event)*250000}B')
        # >200MB valid input, no event cap/sampling, with an 8MiB heap delta budget.
        self.assertLess(large, small+8*1024*1024, (small,large))


class ServiceTrafficResourcesTests(unittest.TestCase):
    def test_real_render_resource_override_never_leaks_into_instance_spec(self):
        output=subprocess.check_output(['helm','template','advanced-fabric',str(CHART),
            '--include-crds','--set','advancedFabric.enabled=true',
            '--set','advancedFabric.serviceTrafficWindow.resources.requests.memory=256Mi',
            '--set','advancedFabric.serviceTrafficWindow.resources.limits.memory=2Gi'],text=True)
        docs=[d for d in yaml.safe_load_all(output) if d]
        instance=next(d for d in docs if d['kind']=='AdvancedFabric')
        self.assertNotIn('serviceTrafficWindow',instance['spec'])
        agent=next(d for d in docs if d['kind']=='DaemonSet' and d['metadata']['name']=='advanced-fabric-agent')
        container=next(c for c in agent['spec']['template']['spec']['containers'] if c['name']=='service-traffic-window')
        self.assertEqual(container['resources'],{'requests':{'cpu':'100m','memory':'256Mi'},
                                               'limits':{'cpu':'2','memory':'2Gi'}})


if __name__ == '__main__':
    unittest.main()
