"""
ReconMate - Interactive Server with Gemini Integration
Runs a lightweight HTTP server connected directly with the Gemini API key.
Provides API endpoints for live reconciliation, report viewing, and interactive AI queries.
"""
import os
import sys
import json
import subprocess
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

def get_api_key():
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GOOGLE_API_KEY="):
                    k = line.strip().split("=", 1)[1].strip('"').strip("'")
                    if k:
                        return k
    return os.environ.get("GOOGLE_API_KEY", "")

os.environ["GOOGLE_API_KEY"] = get_api_key()

class ReconMateServerHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS and disable aggressive caching for API/HTML
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ["", "/", "/index.html"]:
            self.path = "/report.html"

        if parsed.path == "/api/status":
            api_key = get_api_key()
            masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 10 else "***"
            resp = {
                "status": "online",
                "gemini_connected": bool(api_key),
                "api_key_masked": masked_key,
                "model": "gemini-2.5-flash",
                "endpoints": ["/api/status", "/api/reconcile", "/api/ask", "/report.html", "/report_with_actions.json"]
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))
            return

        if parsed.path == "/api/data":
            if os.path.exists("report_with_actions.json"):
                with open("report_with_actions.json", "r", encoding="utf-8") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(data.encode("utf-8"))
                return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}

        if parsed.path == "/api/reconcile":
            try:
                # 1. Run generate_data
                subprocess.run([sys.executable, "generate_data.py"], check=True, capture_output=True)
                # 2. Run reconcile
                subprocess.run([sys.executable, "reconcile.py"], check=True, capture_output=True)
                # 3. Run ai_agent with Gemini
                subprocess.run([sys.executable, "ai_agent.py"], check=True, capture_output=True, env=dict(os.environ, GOOGLE_API_KEY=get_api_key()))
                
                with open("report_with_actions.json", "r", encoding="utf-8") as f:
                    result = json.load(f)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "data": result}, indent=2).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        if parsed.path == "/api/ask":
            query = payload.get("query", "")
            context_ref = payload.get("reference", "")
            
            try:
                # pyrefly: ignore [missing-import]
                from google import genai
                client = genai.Client(api_key=get_api_key())
                
                # Load existing report for context
                context = ""
                if os.path.exists("report_with_actions.json"):
                    with open("report_with_actions.json", "r", encoding="utf-8") as f:
                        report = json.load(f)
                        context = f"Summary: {json.dumps(report.get('summary', {}))}\n"
                        if context_ref:
                            matched = [m for m in report.get("matched", []) if m.get("transaction_id") == context_ref or m.get("bank_ref") == context_ref]
                            excs = [e for e in report.get("exceptions", []) if e.get("transaction_id") == context_ref or e.get("bank_ref") == context_ref]
                            context += f"Relevant Item: {json.dumps(matched + excs)}"

                prompt = f"""You are ReconMate's AI financial reconciliation analyst.
Context:
{context}

User question:
{query}

Provide a concise, helpful, and professional finance-ops response (2-4 sentences)."""

                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "answer": response.text.strip()}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def run(port=8000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, ReconMateServerHandler)
    api_key = get_api_key()
    masked = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 10 else "None"
    print(f"[SERVER] ReconMate Server connected to Gemini API ({masked})")
    print(f"[SERVER] Serving on http://localhost:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer shutting down.")

if __name__ == "__main__":
    p = 8000
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("PORT="):
                    p = int(line.strip().split("=")[1])
    run(port=p)
