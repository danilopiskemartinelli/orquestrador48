import asyncio
import http.client
import json
import os
import socket
import ssl
import threading
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

MAPA_PATH       = '/app/mapa.yaml'
SERVER_ID       = os.environ.get('SERVER_ID', socket.gethostname())
NODE_PORT       = int(os.environ.get('NODE_PORT', '8900'))

_MASTER_NODES   = {'MTLADVL048'}
_master_env     = os.environ.get('MASTER', '')
MASTER          = (_master_env.lower() in ('1', 'true', 'yes')) if _master_env else (SERVER_ID in _MASTER_NODES)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])


# ── mapa ──────────────────────────────────────────────────────────────────────

def load_mapa():
    with open(MAPA_PATH) as f:
        return yaml.safe_load(f)

def mapa_local():
    mapa = load_mapa()
    node = mapa.get(SERVER_ID, {})
    return {
        'hostname': SERVER_ID,
        'servidor': node.get('servidor', ''),
        'ip':       node.get('ip', ''),
        'sistemas': node.get('sistemas', {}),
    }


# ── docker stats ──────────────────────────────────────────────────────────────

DOCKER_SOCK = '/var/run/docker.sock'

def docker_get(path):
    conn = http.client.HTTPConnection('localhost')
    conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.sock.connect(DOCKER_SOCK)
    conn.request('GET', path, headers={'Host': 'localhost'})
    r = conn.getresponse()
    return json.loads(r.read())

def container_stats(c):
    cid  = c['Id']
    name = c['Names'][0].lstrip('/')
    try:
        s        = docker_get(f'/containers/{cid}/stats?stream=false')
        cpu_s    = s.get('cpu_stats', {})
        precpu   = s.get('precpu_stats', {})
        cpu_d    = cpu_s.get('cpu_usage', {}).get('total_usage', 0) - precpu.get('cpu_usage', {}).get('total_usage', 0)
        sys_d    = cpu_s.get('system_cpu_usage', 0) - precpu.get('system_cpu_usage', 0)
        num_cpus = cpu_s.get('online_cpus') or len(cpu_s.get('cpu_usage', {}).get('percpu_usage', [1]))
        cpu_pct  = (cpu_d / sys_d) * num_cpus * 100 if sys_d > 0 else 0

        mem      = s.get('memory_stats', {})
        usage    = mem.get('usage', 0)
        cache    = mem.get('stats', {}).get('cache', mem.get('stats', {}).get('inactive_file', 0))
        return {
            'name':      name,
            'cpu_pct':   round(cpu_pct, 2),
            'mem_bytes': max(0, usage - cache),
            'mem_limit': mem.get('limit', 1),
        }
    except Exception as e:
        return {'name': name, 'cpu_pct': 0, 'mem_bytes': 0, 'mem_limit': 0, 'error': str(e)}

def stats_local():
    containers = docker_get('/containers/json?filters=%7B%22status%22%3A%5B%22running%22%5D%7D')
    results, lock = [], threading.Lock()

    def fetch(c):
        r = container_stats(c)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=fetch, args=(c,)) for c in containers]
    for t in threads: t.start()
    for t in threads: t.join(timeout=6)

    with open('/proc/meminfo') as f:
        mem_total = int([l for l in f if l.startswith('MemTotal')][0].split()[1]) * 1024

    return {
        'containers': sorted(results, key=lambda x: x['mem_bytes'], reverse=True),
        'system':     {'mem_total': mem_total, 'cpu_cores': os.cpu_count() or 1},
    }


# ── probe ─────────────────────────────────────────────────────────────────────

def probe_url(url, timeout=2.0):
    try:
        u    = urlparse(url)
        host = u.hostname
        port = u.port or (443 if u.scheme == 'https' else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout) as raw:
            if u.scheme == 'https':
                ctx  = ssl._create_unverified_context()
                sock = ctx.wrap_socket(raw, server_hostname=host)
            else:
                sock = raw
            path = u.path or '/'
            sock.sendall(f"HEAD {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
            return sock.recv(64).startswith(b'HTTP/')
    except Exception:
        return False

def probe_local(urls):
    results, lock = {}, threading.Lock()

    def fetch(u):
        ok = probe_url(u)
        with lock:
            results[u] = ok

    threads = [threading.Thread(target=fetch, args=(u,)) for u in urls]
    for t in threads: t.start()
    for t in threads: t.join(timeout=3)
    return results


# ── master aggregation ────────────────────────────────────────────────────────

async def _fetch(client: httpx.AsyncClient, hostname: str, ip: str, endpoint: str):
    try:
        r = await client.get(f'http://{ip}:{NODE_PORT}/{endpoint}', timeout=5.0)
        return hostname, r.json()
    except Exception:
        return hostname, None

async def mapa_master():
    mapa  = load_mapa()
    nodes = [(h, v.get('ip', '')) for h, v in mapa.items()]
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_fetch(client, h, ip, 'mapa') for h, ip in nodes if ip])
    return [data for _, data in results if data]

async def stats_master():
    mapa  = load_mapa()
    nodes = [(h, v.get('ip', '')) for h, v in mapa.items()]
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_fetch(client, h, ip, 'stats') for h, ip in nodes if ip])
    return {'nodes': {h: data for h, data in results if data}}


# ── routes ────────────────────────────────────────────────────────────────────

@app.get('/mapa')
async def route_mapa():
    if MASTER:
        return await mapa_master()
    return mapa_local()

@app.get('/stats')
async def route_stats():
    if MASTER:
        return await stats_master()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, stats_local)

@app.get('/probe')
async def route_probe(url: list[str] = Query(default=[])):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, probe_local, url)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
