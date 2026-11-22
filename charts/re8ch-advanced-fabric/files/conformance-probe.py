#!/usr/bin/env python3
"""Directed host/pod-path and DNS conformance probe for Advanced Fabric."""

import json
import os
import random
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request
import statistics
import concurrent.futures
import ipaddress
import re


NODE = os.environ["NODE_NAME"]
PLANE = os.environ["SOURCE_PLANE"]
INTERVAL = int(os.environ.get("PROBE_INTERVAL_SECONDS", "30"))
TIMEOUT = float(os.environ.get("PROBE_TIMEOUT_SECONDS", "2"))
SAMPLES = int(os.environ.get("PROBE_SAMPLES", "3"))
PORT = int(os.environ.get("PROBE_PORT", "4241"))
NAMESPACE = os.environ.get("PUBLISH_NAMESPACE", os.environ.get("POD_NAMESPACE", "default"))
API_GROUP = os.environ.get("ADVANCED_FABRIC_API_GROUP", "networking.advfab.org")
INSTANCE_NAME = os.environ.get("ADVANCED_FABRIC_INSTANCE", "advanced-fabric")
TEXTFILE_DIR = os.environ.get("TEXTFILE_DIR", "/metrics")
DOH_URL = os.environ.get("DOH_URL", "")
DOH_CA_FILE = os.environ.get("DOH_CA_FILE", "/doh-ca/tls.crt")
SHADOW_DNS_SERVICE = os.environ.get("SHADOW_DNS_SERVICE", "")
DNS_SERVICE = os.environ.get("DNS_SERVICE", "advanced-fabric-dns")
HISTORY_SIZE = int(os.environ.get("PROBE_HISTORY_SIZE", "20"))
HISTORY = []
MAX_CONCURRENCY = int(os.environ.get("PROBE_MAX_CONCURRENCY", "24"))
BASE = "https://%s:%s" % (os.environ["KUBERNETES_SERVICE_HOST"], os.environ["KUBERNETES_SERVICE_PORT_HTTPS"])
TOKEN = open("/var/run/secrets/kubernetes.io/serviceaccount/token", encoding="utf-8").read().strip()
CONTEXT = ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
TLS_MAX_REQUEST_BYTES = 8192
TLS_MAX_RESPONSE_BYTES = 32768
TLS_MAX_HEADER_BYTES = 8192


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/merge-patch+json" if method == "PATCH" else "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, context=CONTEXT, timeout=15) as response:
        return json.load(response) if response.length != 0 else {}


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * quantile))], 3)


def history_summary(history):
    """Summarize repeated snapshots; freshness is deliberately evaluated by consumers."""
    losses = [item["lossRatio"] for item in history]
    latencies = [item["p95Ms"] for item in history if item.get("p95Ms") is not None]
    longest, current = 0, 0
    for item in history:
        current = current + 1 if item["lossRatio"] > 0 else 0
        longest = max(longest, current)
    timestamps = [item.get("completedEpoch") for item in history if item.get("completedEpoch") is not None]
    window_seconds = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0
    return {"windowSamples": len(history), "windowSeconds": round(window_seconds, 3),
            "lossMean": round(statistics.fmean(losses), 4) if losses else None,
            "lossStdDev": round(statistics.pstdev(losses), 4) if len(losses) > 1 else None,
            "p95MeanMs": round(statistics.fmean(latencies), 3) if latencies else None,
            "p95StdDevMs": round(statistics.pstdev(latencies), 3) if len(latencies) > 1 else None,
            "lossBurstRatio": round(longest / len(history), 4) if history else None}


def tcp_probe(address, port=PORT):
    started = time.monotonic()
    try:
        with socket.create_connection((address, port), timeout=TIMEOUT) as connection:
            source_address = connection.getsockname()[0]
            return True, round((time.monotonic() - started) * 1000, 3), "", source_address
    except OSError as error:
        return False, round((time.monotonic() - started) * 1000, 3), error.__class__.__name__, None


def measure(address):
    attempts = [tcp_probe(address) for _ in range(SAMPLES)]
    latencies = [latency for ok, latency, _, _ in attempts if ok]
    successes = len(latencies)
    return {"address": address, "port": PORT, "attempts": len(attempts), "successes": successes,
            "lossRatio": round(1 - successes / len(attempts), 4), "p50Ms": percentile(latencies, .5),
            "p95Ms": percentile(latencies, .95), "selectedSourceAddresses": sorted({source for ok, _, _, source
            in attempts if ok and source}), "errors": sorted({error for ok, _, error, _ in attempts if not ok})}


def tls_targets(raw):
    """Validate explicit anonymous targets; never discover paths or credentials."""
    if len(raw) > 16384:
        raise ValueError("configuration")
    targets = json.loads(raw)
    if not isinstance(targets, list) or len(targets) > 4:
        raise ValueError("configuration")
    allowed = {"name", "targetService", "endpoint", "port", "serverName", "path", "pathId",
               "required", "caFile", "expectedStatuses", "paddingBytes", "timeoutSeconds", "sourceNodes"}
    result, names = [], set()
    for item in targets:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError("configuration")
        target = {"port": 443, "path": "/version", "required": False, "expectedStatuses": [200],
                  "paddingBytes": [0, 2048], "timeoutSeconds": min(TIMEOUT, 5), "sourceNodes": [], **item}
        for key in ("name", "targetService", "serverName"):
            if not isinstance(target.get(key), str) or not target[key] or len(target[key]) > 253:
                raise ValueError("configuration")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", target["name"]) or target["name"] in names:
            raise ValueError("configuration")
        names.add(target["name"])
        if any(char.isspace() for char in target["targetService"]):
            raise ValueError("configuration")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,251}[a-zA-Z0-9]", target["serverName"]):
            raise ValueError("configuration")
        target["endpoint"] = str(ipaddress.ip_address(target["endpoint"]))
        if type(target["port"]) is not int or not 1 <= target["port"] <= 65535:
            raise ValueError("configuration")
        if not isinstance(target["path"], str) or len(target["path"]) > 512 or not re.fullmatch(r"/[a-zA-Z0-9/._~-]*", target["path"]):
            raise ValueError("configuration")
        target.setdefault("pathId", target["name"])
        if not isinstance(target["pathId"], str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", target["pathId"]):
            raise ValueError("configuration")
        if type(target["required"]) is not bool:
            raise ValueError("configuration")
        sources = target["sourceNodes"]
        if not isinstance(sources, list) or len(sources) > 3 or any(
                not isinstance(node, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,252}", node)
                for node in sources) or len(set(sources)) != len(sources):
            raise ValueError("configuration")
        if type(target["timeoutSeconds"]) not in (int, float) or not 0 < target["timeoutSeconds"] <= 5:
            raise ValueError("configuration")
        if not isinstance(target["expectedStatuses"], list) or not 1 <= len(target["expectedStatuses"]) <= 4 or any(
                type(code) is not int or not 100 <= code <= 599 for code in target["expectedStatuses"]):
            raise ValueError("configuration")
        sizes = target["paddingBytes"]
        if not isinstance(sizes, list) or not 1 <= len(sizes) <= 2 or len(set(sizes)) != len(sizes) or any(
                type(size) is not int or not 0 <= size <= 4096 for size in sizes):
            raise ValueError("configuration")
        ca = target.get("caFile")
        if ca is not None and (not isinstance(ca, str) or not ca.startswith("/") or
                               not ca.endswith((".crt", ".pem")) or any(char.isspace() for char in ca)):
            raise ValueError("configuration")
        result.append(target)
    return result


def tls_transfer(target, padding, phase_deadline):
    """One strict-TLS, bounded, anonymous GET; no response content is evidence."""
    started = time.monotonic()
    deadline = min(phase_deadline, started + target["timeoutSeconds"])
    result = {"measurementDefinitionId": "tls-transfer-v1", "sourceNode": NODE, "sourcePlane": PLANE,
              "targetId": target["name"], "targetService": target["targetService"],
              "endpoint": target["endpoint"], "port": target["port"], "serverName": target["serverName"],
              "path": target["path"], "pathId": target["pathId"], "required": target["required"],
              "sourceNodes": target["sourceNodes"],
              "paddingBytes": padding, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "success": False, "state": "Failed", "category": "transport", "error": "",
              "statusCode": None, "connectMs": None, "handshakeMs": None, "requestResponseMs": None,
              "requestBytes": 0, "responseBytes": 0, "bodyBytes": 0}
    client = None

    def remaining():
        duration = deadline - time.monotonic()
        if duration <= 0:
            raise TimeoutError()
        if client is not None:
            client.settimeout(duration)
        return duration

    def receive():
        remaining()
        chunk = client.recv(min(4096, TLS_MAX_RESPONSE_BYTES + 1 - result["responseBytes"]))
        result["responseBytes"] += len(chunk)
        if result["responseBytes"] > TLS_MAX_RESPONSE_BYTES:
            raise ValueError("response-limit")
        return chunk

    try:
        if NODE not in target["sourceNodes"]:
            raise ValueError("configuration")
        remaining()
        context = ssl.create_default_context(cafile=target.get("caFile"))
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.set_alpn_protocols(["http/1.1"])
        request = ("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\nX-Diagnostic-Padding: %s\r\n\r\n" %
                   (target["path"], target["serverName"], "x" * padding)).encode("ascii")
        if len(request) > TLS_MAX_REQUEST_BYTES:
            raise ValueError("configuration")
        result["requestBytes"] = len(request)
        family = socket.AF_INET6 if ipaddress.ip_address(target["endpoint"]).version == 6 else socket.AF_INET
        client = socket.socket(family, socket.SOCK_STREAM)
        remaining()
        client.connect((target["endpoint"], target["port"]))
        result["sourceAddress"], result["sourcePort"] = client.getsockname()[:2]
        connected = time.monotonic()
        result["connectMs"] = round((connected - started) * 1000, 3)
        client = context.wrap_socket(client, server_hostname=target["serverName"], do_handshake_on_connect=False)
        remaining()
        client.do_handshake()
        handshaken = time.monotonic()
        result["handshakeMs"] = round((handshaken - connected) * 1000, 3)
        remaining()
        client.sendall(request)
        payload = b""
        while b"\r\n\r\n" not in payload:
            chunk = receive()
            if not chunk:
                raise ValueError("http-framing")
            payload += chunk
            if len(payload.split(b"\r\n\r\n", 1)[0]) > TLS_MAX_HEADER_BYTES:
                raise ValueError("response-limit")
        head, body = payload.split(b"\r\n\r\n", 1)
        lines = head.split(b"\r\n")
        status = re.fullmatch(rb"HTTP/1\.[01] ([0-9]{3})(?: .*)?", lines[0])
        if not status:
            raise ValueError("http-framing")
        result["statusCode"] = int(status[1])
        headers = {}
        for line in lines[1:]:
            if b":" not in line:
                raise ValueError("http-framing")
            key, value = line.split(b":", 1)
            key, value = key.strip().lower(), value.strip()
            if key in (b"content-length", b"transfer-encoding") and key in headers:
                raise ValueError("http-framing")
            headers[key] = value
        # Only an explicit length or connection-close frame can prove completion.
        if headers.get(b"transfer-encoding", b"identity").lower() != b"identity":
            raise ValueError("http-framing")
        length = headers.get(b"content-length")
        if length is not None:
            if not re.fullmatch(rb"[0-9]+", length):
                raise ValueError("http-framing")
            length = int(length)
            if length + len(head) + 4 > TLS_MAX_RESPONSE_BYTES:
                raise ValueError("response-limit")
        result["bodyBytes"] = len(body)
        while length is None or result["bodyBytes"] < length:
            chunk = receive()
            if not chunk:
                if length is not None:
                    raise ValueError("http-framing")
                break
            result["bodyBytes"] += len(chunk)
        if length is not None and result["bodyBytes"] != length:
            raise ValueError("http-framing")
        remaining()
        result["requestResponseMs"] = round((time.monotonic() - handshaken) * 1000, 3)
        if result["statusCode"] not in target["expectedStatuses"]:
            raise ValueError("http-status")
        result.update(success=True, state="Succeeded", category="ok")
    except (OSError, ValueError) as error:
        category = str(error) if isinstance(error, ValueError) and str(error) in (
            "configuration", "response-limit", "http-framing", "http-status") else (
            "deadline" if isinstance(error, TimeoutError) else "tls" if isinstance(error, ssl.SSLError) else "transport")
        result.update(category=category, error=error.__class__.__name__)
    finally:
        if client is not None:
            client.close()
    result["totalMs"] = round((time.monotonic() - started) * 1000, 3)
    result["observedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return result


def measure_tls_targets():
    try:
        targets = tls_targets(os.environ.get("TLS_PROBE_TARGETS", "[]"))
    except (ValueError, TypeError, KeyError, OverflowError):
        return [{"measurementDefinitionId": "tls-transfer-v1", "sourceNode": NODE, "sourcePlane": PLANE,
                 "success": False, "state": "Failed", "category": "configuration", "error": "InvalidTargetConfiguration",
                 "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}]
    jobs = [(target, padding) for target in targets if NODE in target["sourceNodes"]
            for padding in target["paddingBytes"]]
    deadline = time.monotonic() + 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda job: tls_transfer(*job, deadline), jobs))


def encode_name(name):
    parts = name.rstrip(".").split(".")
    return b"".join(bytes([len(part)]) + part.encode() for part in parts) + b"\0"


def dns_packet(name, qtype=1, query_id=None):
    query_id = random.randint(0, 65535) if query_id is None else query_id
    return query_id, struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + encode_name(name) + struct.pack("!HH", qtype, 1)


def dns_rcode(payload, query_id):
    if len(payload) < 12:
        raise ValueError("short DNS response")
    response_id, flags = struct.unpack("!HH", payload[:4])
    if response_id != query_id:
        raise ValueError("DNS transaction mismatch")
    return flags & 0xF


def recv_exact(client, size, deadline):
    payload = b""
    while len(payload) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("DNS frame deadline exceeded")
        client.settimeout(remaining)
        chunk = client.recv(size - len(payload))
        if not chunk:
            raise ValueError("truncated DNS TCP frame")
        payload += chunk
    return payload


def dns_query(server, name, protocol="udp"):
    query_id, packet = dns_packet(name)
    started = time.monotonic()
    try:
        socktype = socket.SOCK_DGRAM if protocol == "udp" else socket.SOCK_STREAM
        with socket.socket(socket.AF_INET, socktype) as client:
            client.settimeout(TIMEOUT)
            client.connect((server, 53))
            if protocol == "tcp":
                client.sendall(struct.pack("!H", len(packet)) + packet)
                deadline = started + TIMEOUT
                size = struct.unpack("!H", recv_exact(client, 2, deadline))[0]
                response = recv_exact(client, size, deadline)
            else:
                client.send(packet)
                response = client.recv(4096)
        rcode = dns_rcode(response, query_id)
        return {"ok": rcode == 0, "rcode": rcode, "latencyMs": round((time.monotonic() - started) * 1000, 3)}
    except (OSError, ValueError) as error:
        return {"ok": False, "rcode": None, "latencyMs": round((time.monotonic() - started) * 1000, 3),
                "error": error.__class__.__name__}


def dns_measure(server, protocol, name="kubernetes.default.svc.cluster.local", role="stable"):
    attempts = [dns_query(server, name, protocol) for _ in range(SAMPLES)]
    latencies = [item["latencyMs"] for item in attempts if item["ok"]]
    successes = len(latencies)
    return {"server": server, "serverRole": role, "protocol": protocol, "name": name, "attempts": len(attempts),
            "successes": successes, "failureRatio": round(1 - successes / len(attempts), 4),
            "p50Ms": percentile(latencies, .5), "p95Ms": percentile(latencies, .95),
            "rcodes": {str(code): sum(1 for item in attempts if item.get("rcode") == code)
                       for code in sorted({item.get("rcode") for item in attempts if item.get("rcode") is not None})}}


def doh_query(url, name):
    query_id, packet = dns_packet(name)
    started = time.monotonic()
    try:
        context = ssl.create_default_context(cafile=DOH_CA_FILE)
        request = urllib.request.Request(url, data=packet, method="POST", headers={
            "Accept": "application/dns-message", "Content-Type": "application/dns-message"})
        with urllib.request.urlopen(request, context=context, timeout=TIMEOUT) as response:
            payload = response.read(65536)
            content_type = response.headers.get_content_type()
        if content_type != "application/dns-message":
            raise ValueError("unexpected DoH content type")
        rcode = dns_rcode(payload, query_id)
        return {"ok": rcode == 0, "rcode": rcode, "latencyMs": round((time.monotonic() - started) * 1000, 3)}
    except (OSError, ValueError, urllib.error.URLError) as error:
        return {"ok": False, "rcode": None, "latencyMs": round((time.monotonic() - started) * 1000, 3),
                "error": error.__class__.__name__}


def doh_measure(url, name="kubernetes.default.svc.cluster.local"):
    attempts = [doh_query(url, name) for _ in range(SAMPLES)]
    latencies = [item["latencyMs"] for item in attempts if item["ok"]]
    successes = len(latencies)
    return {"url": url, "name": name, "attempts": len(attempts), "successes": successes,
            "failureRatio": round(1 - successes / len(attempts), 4), "p50Ms": percentile(latencies, .5),
            "p95Ms": percentile(latencies, .95), "rcodes": {str(code): sum(1 for item in attempts
            if item.get("rcode") == code) for code in sorted({item.get("rcode") for item in attempts
            if item.get("rcode") is not None})}}


def discover():
    fabric = api("GET", "/apis/%s/v1alpha1/advancedfabrics/%s" % (API_GROUP, INSTANCE_NAME))
    inventory = fabric.get("spec", {}).get("nodes", [])
    inventory_nodes = {item.get("name") for item in inventory}
    source_spec = next((item for item in inventory if item.get("name") == NODE), {})
    nodes = api("GET", "/api/v1/nodes").get("items", [])
    pods = api("GET", "/api/v1/namespaces/%s/pods?labelSelector=" % NAMESPACE +
               "app.kubernetes.io%2Fname%3Dadvanced-fabric-pod-conformance").get("items", [])
    pod_ips = {pod.get("spec", {}).get("nodeName"): pod.get("status", {}).get("podIP") for pod in pods
               if pod.get("status", {}).get("phase") == "Running"}
    targets = []
    for node in nodes:
        name = node.get("metadata", {}).get("name")
        addresses = node.get("status", {}).get("addresses", [])
        host_ip = next((item.get("address") for item in addresses if item.get("type") == "InternalIP"), None)
        if name in inventory_nodes:
            targets.append({"node": name, "hostIP": host_ip, "podIP": pod_ips.get(name)})
    service = api("GET", "/api/v1/namespaces/%s/services/%s" % (NAMESPACE, DNS_SERVICE))
    dns_servers = [("stable", service.get("spec", {}).get("clusterIP"))]
    # Service success cannot prove that each selectable replica is reachable.
    slices = api("GET", "/apis/discovery.k8s.io/v1/namespaces/%s/endpointslices?labelSelector=" % NAMESPACE +
                 "kubernetes.io%2Fservice-name%3D" + DNS_SERVICE).get("items", [])
    replicas = sorted({address for item in slices for endpoint in item.get("endpoints", [])
                       if endpoint.get("conditions", {}).get("ready") is True
                       for address in endpoint.get("addresses", [])})
    dns_servers.extend(("replica", address) for address in replicas)
    if DNS_SERVICE != "kube-dns":
        kube_dns = api("GET", "/api/v1/namespaces/%s/services/kube-dns" % NAMESPACE)
        dns_servers.append(("kube-dns", kube_dns.get("spec", {}).get("clusterIP")))

    if SHADOW_DNS_SERVICE:
        try:
            shadow = api("GET", "/api/v1/namespaces/%s/services/%s" % (NAMESPACE, SHADOW_DNS_SERVICE))
            dns_servers.append(("shadow", shadow.get("spec", {}).get("clusterIP")))
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    alternatives = [item for item in source_spec.get("alternativePaths", []) if item.get("address") and
                    item.get("targetNode") and item.get("targetPlane") in ("host", "pod")]
    return sorted(targets, key=lambda item: item["node"]), dns_servers, alternatives


def assigned_tasks():
    try:
        obj = api("GET", "/api/v1/namespaces/%s/configmaps/advanced-fabric-evidence-plan" % NAMESPACE)
        plan = json.loads(obj.get("data", {}).get("plan.json", "{}"))
        tasks = [task for task in plan.get("tasks", []) if task.get("sourceNode") == NODE and
                 task.get("sourcePlane") == PLANE]
        return plan.get("generation"), tasks
    except (urllib.error.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        return None, []


def serve():
    """Provide the same TCP health contract in the host and pod namespaces."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", PORT))
    listener.listen(64)
    while True:
        connection, _ = listener.accept()
        connection.close()


def snapshot():
    started_epoch = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_epoch))
    targets, dns_servers, alternatives = discover()
    plan_generation, tasks = assigned_tasks()
    requested_targets = {name for task in tasks for name in task.get("targetNodes", [])}
    if requested_targets:
        targets = [target for target in targets if target["node"] in requested_targets]
    specifications = []
    for target in targets:
        for destination_plane, key in (("host", "hostIP"), ("pod", "podIP")):
            if target.get(key):
                specifications.append((target, destination_plane, key))
    def measure_path(specification):
        target, destination_plane, key = specification
        return {"measurementDefinitionId": "path-quality-v1", "pathRole": "current",
                "sourceNode": NODE, "sourcePlane": PLANE, "targetNode": target["node"],
                "targetPlane": destination_plane, **measure(target[key])}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(MAX_CONCURRENCY, len(specifications)))) as pool:
        paths = list(pool.map(measure_path, specifications))
    def measure_alternative(alternative):
        return {"measurementDefinitionId": "path-quality-v1", "pathRole": "alternative", "feasible": True,
                "pathId": alternative.get("name"), "sourceNode": NODE, "sourcePlane": PLANE,
                "targetNode": alternative["targetNode"], "targetPlane": alternative["targetPlane"],
                **measure(alternative["address"])}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(MAX_CONCURRENCY, len(alternatives)))) as pool:
        paths.extend(pool.map(measure_alternative, alternatives))
    dns_jobs = [(role, server, protocol) for role, server in dns_servers
                if server and server != "None" for protocol in ("udp", "tcp")]
    def measure_dns(job):
        role, server, protocol = job
        return dns_measure(server, protocol, role=role)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(MAX_CONCURRENCY, len(dns_jobs)))) as pool:
        dns = list(pool.map(measure_dns, dns_jobs))
    doh = [doh_measure(DOH_URL)] if DOH_URL else []
    tls_transfers = measure_tls_targets()
    path_attempts = sum(item.get("attempts", 0) for item in paths)
    path_successes = sum(item.get("successes", 0) for item in paths)
    successful_p95 = [item["p95Ms"] for item in paths if item.get("p95Ms") is not None]
    completed_epoch = time.time()
    duration = completed_epoch - started_epoch
    validity = max(INTERVAL * 3, int(duration * 2 + INTERVAL))
    HISTORY.append({"lossRatio": round(1 - path_successes / path_attempts, 4) if path_attempts else 1,
                    "p95Ms": max(successful_p95) if successful_p95 else None, "completedEpoch": completed_epoch})
    del HISTORY[:-HISTORY_SIZE]
    return {"schemaVersion": "networking.advfab.org/network-quality-v1alpha2", "startedAt": started_at,
            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(completed_epoch)),
            "measurementDurationSeconds": round(duration, 3), "validitySeconds": validity,
            "sourceNode": NODE, "sourcePlane": PLANE,
            "targetsDiscovered": len(targets), "paths": paths, "dns": dns, "doh": doh,
            "tlsTransfers": tls_transfers,
            "history": history_summary(HISTORY),
            "measurementDefinitionIds": ["path-quality-v1", "dns-quality-v1"] +
                (["tls-transfer-v1"] if tls_transfers else []), "planGeneration": plan_generation,
            "completedTaskIds": sorted(task["id"] for task in tasks)}


def prometheus_escape(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labels(values):
    return "{" + ",".join('%s="%s"' % (key, prometheus_escape(value)) for key, value in sorted(values.items())) + "}"


def parse_observed_time(value):
    import datetime
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def prometheus_text(result):
    """Render the stable NWQ-1/DNSQ-1 Node Exporter textfile contract."""
    lines = [
        "# HELP advanced_fabric_quality_probe_info Static identity of a conformance probe source.",
        "# TYPE advanced_fabric_quality_probe_info gauge",
        "advanced_fabric_quality_probe_info%s 1" % labels({"source_node": NODE, "source_plane": PLANE,
                                                         "standard": "NWQ-1_DNSQ-1"}),
        "# HELP advanced_fabric_quality_observed_timestamp_seconds Unix time of the completed measurement.",
        "# TYPE advanced_fabric_quality_observed_timestamp_seconds gauge",
        "advanced_fabric_quality_observed_timestamp_seconds%s %d" % (labels({"source_node": NODE,
            "source_plane": PLANE}), int(parse_observed_time(result["observedAt"]))),
    ]
    path_metrics = (("attempts", "advanced_fabric_path_attempts"), ("successes", "advanced_fabric_path_successes"),
                    ("lossRatio", "advanced_fabric_path_loss_ratio"), ("p50Ms", "advanced_fabric_path_latency_p50_milliseconds"),
                    ("p95Ms", "advanced_fabric_path_latency_p95_milliseconds"))
    for entry in result.get("paths", []):
        common = {"source_node": entry["sourceNode"], "source_plane": entry["sourcePlane"],
                  "target_node": entry["targetNode"], "target_plane": entry["targetPlane"],
                  "target_address": entry["address"]}
        for field, metric in path_metrics:
            if entry.get(field) is not None:
                lines.append("%s%s %s" % (metric, labels(common), entry[field]))
        for source_address in entry.get("selectedSourceAddresses", []):
            lines.append("advanced_fabric_path_selected_source_info%s 1" % labels(dict(common,
                         selected_source_address=source_address)))
    dns_metrics = (("attempts", "advanced_fabric_dns_probe_attempts"), ("successes", "advanced_fabric_dns_probe_successes"),
                   ("failureRatio", "advanced_fabric_dns_probe_failure_ratio"), ("p50Ms", "advanced_fabric_dns_probe_latency_p50_milliseconds"),
                   ("p95Ms", "advanced_fabric_dns_probe_latency_p95_milliseconds"))
    for entry in result.get("dns", []):
        common = {"source_node": NODE, "source_plane": PLANE, "server": entry["server"],
                  "server_role": entry.get("serverRole", "stable"),
                  "protocol": entry["protocol"], "query": entry["name"]}
        for field, metric in dns_metrics:
            if entry.get(field) is not None:
                lines.append("%s%s %s" % (metric, labels(common), entry[field]))
        for rcode, count in entry.get("rcodes", {}).items():
            lines.append("advanced_fabric_dns_probe_responses%s %s" % (labels(dict(common, rcode=rcode)), count))
    doh_metrics = (("attempts", "advanced_fabric_doh_probe_attempts"), ("successes", "advanced_fabric_doh_probe_successes"),
                   ("failureRatio", "advanced_fabric_doh_probe_failure_ratio"), ("p50Ms", "advanced_fabric_doh_probe_latency_p50_milliseconds"),
                   ("p95Ms", "advanced_fabric_doh_probe_latency_p95_milliseconds"))
    for entry in result.get("doh", []):
        common = {"source_node": NODE, "source_plane": PLANE, "endpoint": entry["url"], "query": entry["name"]}
        for field, metric in doh_metrics:
            if entry.get(field) is not None:
                lines.append("%s%s %s" % (metric, labels(common), entry[field]))
        for rcode, count in entry.get("rcodes", {}).items():
            lines.append("advanced_fabric_doh_probe_responses%s %s" % (labels(dict(common, rcode=rcode)), count))
    for entry in result.get("tlsTransfers", []):
        common = {"source_node": NODE, "source_plane": PLANE, "target_id": entry.get("targetId", "configuration"),
                  "target_service": entry.get("targetService", ""), "endpoint": entry.get("endpoint", ""),
                  "port": entry.get("port", ""), "path_id": entry.get("pathId", ""),
                  "padding_bytes": entry.get("paddingBytes", ""), "category": entry["category"]}
        lines.append("advanced_fabric_tls_transfer_success%s %d" % (labels(common), int(entry["success"])))
        for field, metric in (("totalMs", "duration_milliseconds"), ("requestBytes", "request_bytes"),
                              ("responseBytes", "response_bytes"), ("bodyBytes", "body_bytes")):
            if entry.get(field) is not None:
                lines.append("advanced_fabric_tls_transfer_%s%s %s" % (metric, labels(common), entry[field]))
    return "\n".join(lines) + "\n"


def write_textfile(result):
    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    path = os.path.join(TEXTFILE_DIR, "advanced_fabric_%s.prom" % PLANE)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        stream.write(prometheus_text(result))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def publish(result):
    safe_node = NODE.lower().replace("_", "-").replace(".", "-")
    name = "advanced-fabric-probe-%s-%s" % (safe_node, PLANE)
    obj = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name, "namespace": NAMESPACE,
           "labels": {"app.kubernetes.io/name": "advanced-fabric", "app.kubernetes.io/component":
           "network-quality", "networking.advfab.org/source-node": NODE, "networking.advfab.org/source-plane": PLANE}},
           "data": {"result.json": json.dumps(result, separators=(",", ":"))}}
    path = "/api/v1/namespaces/%s/configmaps/%s" % (NAMESPACE, name)
    try:
        api("PATCH", path, obj)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        api("POST", "/api/v1/namespaces/%s/configmaps" % NAMESPACE, obj)


if __name__ == "__main__":
    threading.Thread(target=serve, name="conformance-health", daemon=True).start()
    while True:
        try:
            result = snapshot()
            write_textfile(result)
            publish(result)
        except Exception as error:
            print(json.dumps({"event": "network-quality-probe-error", "node": NODE, "plane": PLANE,
                              "error": str(error)}), flush=True)
        time.sleep(INTERVAL)
