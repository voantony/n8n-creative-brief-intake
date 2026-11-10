"""Local stand-ins for Google Sheets and Slack, so the workflow runs with no accounts.

POST /sheets/append   -> appends the JSON body as a row to output/briefs.csv
POST /slack/webhook   -> appends the JSON body to output/slack.jsonl
GET  /health          -> ok

Set FAIL_FIRST=N to make the first N calls to each endpoint return 503,
which shows the n8n retry settings doing their job.
"""
import csv, json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)
FAIL_FIRST = int(os.environ.get("FAIL_FIRST", "0"))
calls = {}
COLUMNS = ["received_at", "brief_id", "brand", "contact_email", "status", "completeness",
           "lead_score", "priority", "formats", "missing_fields", "prompt_count", "reply_subject", "model", "tokens_used", "llm_seconds"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"ok": True})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        calls[self.path] = calls.get(self.path, 0) + 1
        if calls[self.path] <= FAIL_FIRST:
            print(f"[mock] {self.path} call {calls[self.path]}: returning 503 (FAIL_FIRST)", flush=True)
            return self._send(503, {"error": "simulated outage"})
        if self.path == "/sheets/append":
            path = OUT / "briefs.csv"
            new = not path.exists()
            with path.open("a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in body.items()})
            print(f"[mock] sheets row: {body.get('brief_id')} {body.get('status')}", flush=True)
            return self._send(200, {"ok": True, "updatedRows": 1})
        if self.path == "/slack/webhook":
            with (OUT / "slack.jsonl").open("a") as f:
                f.write(json.dumps(body) + "\n")
            print(f"[mock] slack: {body.get('text', '')[:80]}", flush=True)
            return self._send(200, {"ok": True})
        self._send(404, {"error": "unknown path"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"[mock] listening on :{port} FAIL_FIRST={FAIL_FIRST}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
