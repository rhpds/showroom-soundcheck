from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            body = json.dumps({"status": "ok"}).encode()
            self._json_response(200, body)
        elif self.path == "/unhealthz":
            body = json.dumps({
                "status": "error",
                "error": "unable to fetch gitea endpoint",
                "detail": "connection to https://gitea.example.com/api/v1/health timed out after 30s",
            }).encode()
            self._json_response(503, body)
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return  # silence request logs


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8082"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"healthcheck listening on :{port}")
    server.serve_forever()
