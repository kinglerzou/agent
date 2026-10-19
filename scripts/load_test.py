"""Small dependency-free HTTP load probe. Start the API first."""
import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.request
import urllib.error


def request(base):
    start = time.perf_counter()
    body = json.dumps({'messages': [{'role': 'user', 'content': '计算 128 * 16'}]}).encode()
    req = urllib.request.Request(base + '/api/chat', data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=95) as response:
            data = response.read().decode()
            ok = '"type": "done"' in data and '2048' in data
            status = response.status
    except urllib.error.HTTPError as exc:
        ok, status = False, exc.code
    except (urllib.error.URLError, TimeoutError):
        ok, status = False, 0
    return (time.perf_counter() - start) * 1000, ok, status


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:3001')
    parser.add_argument('--requests', type=int, default=30)
    parser.add_argument('--concurrency', type=int, default=4)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error('requests and concurrency must be positive')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: request(args.url), range(args.requests)))
    latencies = sorted(r[0] for r in results)
    print(json.dumps({'requests': len(results), 'success': sum(r[1] for r in results),
                      'p50_ms': round(statistics.median(latencies), 2),
                      'p95_ms': round(latencies[min(len(latencies)-1, int(len(latencies)*.95))], 2),
                      'status_counts': {str(s): sum(r[2] == s for r in results) for s in set(r[2] for r in results)}}, indent=2))
