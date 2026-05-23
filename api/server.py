import http.client
import json
import os
import socket
import ssl
import threading
import yaml
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

MAPA_PATH = '/app/mapa.yaml'
SERVER_ID  = os.environ.get('SERVER_ID', socket.gethostname())


def get_mapa():
    with open(MAPA_PATH) as f:
        mapa = yaml.safe_load(f)
    node = mapa.get(SERVER_ID, {})
    return {
        'hostname': SERVER_ID,
        'servidor': node.get('servidor', ''),
        'ip':       node.get('ip', ''),
        'sistemas': node.get('sistemas', {}),
    }

DOCKER_SOCK = '/var/run/docker.sock'


def docker_get(path):
    conn = http.client.HTTPConnection('localhost')
    conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.sock.connect(DOCKER_SOCK)
    conn.request('GET', path, headers={'Host': 'localhost'})
    r = conn.getresponse()
    return json.loads(r.read())


def container_stats(c):
    cid = c['Id']
    name = c['Names'][0].lstrip('/')
    try:
        s = docker_get(f'/containers/{cid}/stats?stream=false')
        cpu_stats = s.get('cpu_stats', {})
        precpu = s.get('precpu_stats', {})
        cpu_delta = (cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                     - precpu.get('cpu_usage', {}).get('total_usage', 0))
        sys_delta = (cpu_stats.get('system_cpu_usage', 0)
                     - precpu.get('system_cpu_usage', 0))
        num_cpus = cpu_stats.get('online_cpus') or len(
            cpu_stats.get('cpu_usage', {}).get('percpu_usage', [1]))
        cpu_pct = (cpu_delta / sys_delta) * num_cpus * 100 if sys_delta > 0 else 0

        mem = s.get('memory_stats', {})
        usage = mem.get('usage', 0)
        cache = mem.get('stats', {}).get('cache',
                mem.get('stats', {}).get('inactive_file', 0))
        mem_usage = max(0, usage - cache)
        mem_limit = mem.get('limit', 1)
        return {
            'name': name,
            'cpu_pct': round(cpu_pct, 2),
            'mem_bytes': mem_usage,
            'mem_limit': mem_limit,
        }
    except Exception as e:
        return {'name': name, 'cpu_pct': 0, 'mem_bytes': 0, 'mem_limit': 0, 'error': str(e)}


def get_stats():
    containers = docker_get('/containers/json?filters=%7B%22status%22%3A%5B%22running%22%5D%7D')
    results = []
    lock = threading.Lock()

    def fetch(c):
        r = container_stats(c)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=fetch, args=(c,)) for c in containers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=6)

    with open('/proc/meminfo') as f:
        mem_total = int([l for l in f if l.startswith('MemTotal')][0].split()[1]) * 1024

    return {
        'containers': sorted(results, key=lambda x: x['mem_bytes'], reverse=True),
        'system': {
            'mem_total': mem_total,
            'cpu_cores': os.cpu_count() or 1,
        },
    }


def probe_url(url, timeout=2.0):
    """Server-side probe: TCP connect + minimal HTTP HEAD. Ignora cert TLS."""
    try:
        u = urlparse(url)
        host = u.hostname
        port = u.port or (443 if u.scheme == 'https' else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout) as raw:
            if u.scheme == 'https':
                ctx = ssl._create_unverified_context()
                sock = ctx.wrap_socket(raw, server_hostname=host)
            else:
                sock = raw
            path = u.path or '/'
            req = f"HEAD {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n"
            sock.sendall(req.encode())
            data = sock.recv(64)
            return data.startswith(b'HTTP/')
    except Exception:
        return False


def get_probe(urls):
    results = {}
    lock = threading.Lock()

    def fetch(u):
        ok = probe_url(u)
        with lock:
            results[u] = ok

    threads = [threading.Thread(target=fetch, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)
    return results


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == '/stats':
                self._send_json(200, get_stats())
                return
            if u.path == '/probe':
                qs = parse_qs(u.query)
                urls = qs.get('url', [])
                self._send_json(200, get_probe(urls))
                return
            if u.path == '/mapa':
                self._send_json(200, get_mapa())
                return
            self.send_response(404)
            self.end_headers()
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, *args):
        pass


HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
