"""CLI client for the same localhost API used by the React dashboard."""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID, uuid4


def request(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(base.rstrip("/") + path, data=data,
                  headers={"Content-Type": "application/json", "X-Graph-Stock": "local-research"})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def main(argv=None, send=request):
    parser = argparse.ArgumentParser(description="graph_stock fixture research (synthetic data only)")
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    sub = parser.add_subparsers(dest="action", required=True)
    research = sub.add_parser("research")
    research.add_argument("query")
    research.add_argument("--request-key", type=UUID, default=None)
    research.add_argument("--no-wait", action="store_true")
    search = sub.add_parser("search")
    search.add_argument("query")
    sub.add_parser("watchlist")
    show = sub.add_parser("show")
    show.add_argument("run_id", type=UUID)
    args = parser.parse_args(argv)
    server = urlparse(args.server)
    if server.scheme != "http" or server.hostname not in ("localhost", "127.0.0.1", "::1") or server.username:
        parser.error("Use a local HTTP server URL")
    try:
        if args.action == "research":
            key = str(args.request_key or uuid4())
            print(f"Request key: {key} (reuse this key if a request is interrupted)", file=sys.stderr)
            data = send(args.server, "/api/research", {"query": args.query, "request_key": key})
            deadline = time.monotonic() + 30
            while not args.no_wait and data["status"] == "publishing" and time.monotonic() < deadline:
                time.sleep(.1)
                data = send(args.server, f'/api/research/{data["id"]}')
        elif args.action == "search":
            data = send(args.server, "/api/securities?" + urlencode({"query": args.query}))
        elif args.action == "watchlist":
            data = send(args.server, "/api/watchlist")
        else:
            data = send(args.server, f"/api/research/{args.run_id}")
        print(json.dumps(data, indent=2))
        if args.action == "research" and args.no_wait:
            return 0
        return 0 if not isinstance(data, dict) or data.get("status") not in ("publication-failed", "note-conflict", "publishing") else 1
    except HTTPError as error:
        print(error.read().decode(), file=sys.stderr)
        return 2
    except (URLError, TimeoutError, OSError):
        print("Local server unavailable. Start graph_stock, then retry with the same request key.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
