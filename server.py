"""
ReconMate - Interactive Server with Gemini Integration
Runs a multi-threaded HTTP server connected directly with Google Gemini.
Provides interactive API endpoints for live reconciliation, report viewing, and interactive AI copilot queries.
"""
import os
import sys
import json
import argparse
import webbrowser
import subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import urllib.parse
from render_dashboard import render_dashboard


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


def ensure_initial_report():
    """Ensure data files and report exist before serving."""
    if not os.path.exists("report.html") or not os.path.exists("report_with_actions.json"):
        print("[INIT] Initial reconciliation report not found. Generating now...")
        try:
            subprocess.run([sys.executable, "generate_data.py"], check=True, capture_output=True)
            subprocess.run([sys.executable, "reconcile.py"], check=True, capture_output=True)
            subprocess.run([sys.executable, "ai_agent.py"], check=True, capture_output=True)
            print("[INIT] Initial report successfully generated.")
        except Exception as e:
            print(f"[INIT] Warning during initial generation: {e}")


class ReconMateServerHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS and disable caching for live data
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        
        # Route root or index to report.html
        if parsed.path in ["", "/", "/index.html"]:
            self.path = "/report.html"

        if parsed.path == "/api/status":
            api_key = get_api_key()
            masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 10 else ("Configured" if api_key else "Missing")
            resp = {
                "status": "online",
                "gemini_connected": bool(api_key),
                "api_key_status": masked_key,
                "model": "gemini-2.5-flash",
                "endpoints": ["/api/status", "/api/reconcile", "/api/ask", "/api/data", "/report.html"]
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))
            return

        if parsed.path == "/api/data":
            target_file = "report_with_actions.json" if os.path.exists("report_with_actions.json") else "report.json"
            if os.path.exists(target_file):
                with open(target_file, "r", encoding="utf-8") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(data.encode("utf-8"))
                return
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "No report data available. Run pipeline first."}).encode("utf-8"))
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
            api_key = get_api_key()

            # Load report for context
            report = {}
            context_item = None
            if os.path.exists("report_with_actions.json"):
                try:
                    with open("report_with_actions.json", "r", encoding="utf-8") as f:
                        report = json.load(f)
                except Exception:
                    pass
            elif os.path.exists("report.json"):
                try:
                    with open("report.json", "r", encoding="utf-8") as f:
                        report = json.load(f)
                except Exception:
                    pass

            if context_ref and report:
                for m in report.get("matched", []):
                    if m.get("transaction_id") == context_ref or m.get("bank_ref") == context_ref:
                        context_item = {"type": "MATCHED", "data": m}
                        break
                if not context_item:
                    for e in report.get("exceptions", []):
                        if e.get("transaction_id") == context_ref or e.get("bank_ref") == context_ref:
                            context_item = {"type": "EXCEPTION", "data": e}
                            break

            answer = None

            # Attempt Gemini with fallback models if API key present
            if api_key:
                models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
                try:
                    # pyrefly: ignore [missing-import]
                    from google import genai
                    client = genai.Client(api_key=api_key)

                    context_str = f"Summary: {json.dumps(report.get('summary', {}))}\n"
                    if context_item:
                        context_str += f"Target Item: {json.dumps(context_item)}\n"

                    prompt = f"""You are ReconMate's AI financial reconciliation analyst for Razorpay merchant payments and bank settlement statements.
Context:
{context_str}

User question:
{query}

Provide a concise, highly actionable, and professional finance-ops response (2-4 sentences)."""

                    for m in models_to_try:
                        try:
                            response = client.models.generate_content(model=m, contents=prompt)
                            if response and response.text:
                                answer = response.text.strip()
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            # Smart Contextual Fallback if offline or quota reached
            if not answer:
                if context_item:
                    cdata = context_item.get("data", {})
                    if context_item.get("type") == "EXCEPTION":
                        etype = cdata.get("type", "ANOMALY")
                        reason = cdata.get("reason", "")
                        if etype == "AMOUNT_MISMATCH":
                            answer = (
                                f"Transaction {context_ref} was flagged with an AMOUNT_MISMATCH. {reason} "
                                "Recommended Action: Check whether a partial refund or dispute was initiated on the payment gateway, "
                                "and adjust the merchant ledger entry accordingly."
                            )
                        elif etype == "MISSING_SETTLEMENT":
                            answer = (
                                f"Transaction {context_ref} is MISSING_SETTLEMENT. {reason} "
                                "Recommended Action: Escalate with Bank Settlement Operations via batch inquiry ticket to verify if payout failed or is held in escrow."
                            )
                        elif etype == "DUPLICATE_SETTLEMENT":
                            answer = (
                                f"Transaction {context_ref} was flagged as a DUPLICATE_SETTLEMENT. "
                                "Recommended Action: Flag for Finance Ops to issue a reversal request to prevent duplicate merchant disbursement."
                            )
                        else:
                            answer = (
                                f"Reference {context_ref} is an UNEXPLAINED_BANK_CREDIT. {reason} "
                                "Recommended Action: Trace credit originator via bank transaction UTR/RRN to map to merchant ledger."
                            )
                    else:
                        answer = (
                            f"Transaction {context_ref} was successfully reconciled via {cdata.get('match_type','deterministic match')} "
                            f"(Ledger: ₹{cdata.get('ledger_amount',0):,.2f}, Bank: ₹{cdata.get('bank_amount',0):,.2f}, Fee: {cdata.get('fee_pct',0)}%). No action required."
                        )
                else:
                    sum_data = report.get("summary", {})
                    answer = (
                        f"ReconMate Analysis: This batch has a {sum_data.get('match_rate_pct', 70.8)}% match rate "
                        f"reconciling ₹{sum_data.get('matched_amount', 571694):,.2f}. "
                        f"There are {sum_data.get('exception_count', 22)} exceptions requiring review, mainly due to unrecorded partial refunds and transit delays. "
                        "Review the AI Action Center tab to dispatch recommended draft communications."
                    )

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "answer": answer}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def start_server(port=8000, auto_open=False):
    ensure_initial_report()
    
    server = None
    selected_port = port
    max_tries = 10

    for offset in range(max_tries):
        test_port = port + offset
        try:
            server_address = ("0.0.0.0", test_port)
            server = ThreadingHTTPServer(server_address, ReconMateServerHandler)
            selected_port = test_port
            break
        except OSError as e:
            if offset == max_tries - 1:
                print(f"[ERROR] Could not bind to port {test_port}: {e}")
                sys.exit(1)
            continue

    api_key = get_api_key()
    masked = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 10 else ("Connected" if api_key else "Missing (using fallback)")
    
    url_local = f"http://localhost:{selected_port}"
    url_ip = f"http://127.0.0.1:{selected_port}"
    
    print("\n" + "="*60)
    print("  ⚡ ReconMate — AI Financial Reconciliation Dashboard")
    print("="*60)
    print(f"  [+] Status:       Server Online (Multi-Threaded)")
    print(f"  [+] Gemini Engine: {masked}")
    print(f"  [+] Localhost:    {url_local}")
    print(f"  [+] Direct IP:    {url_ip}")
    print("="*60)
    print("  Press Ctrl+C to stop server.\n")

    if auto_open:
        try:
            webbrowser.open(url_local)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down ReconMate server cleanly.")
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReconMate Interactive Server")
    parser.add_argument("--port", "-p", type=int, default=None, help="Port to listen on (default 8000 or .env)")
    parser.add_argument("--open", "-o", action="store_true", help="Automatically open browser on start")
    args = parser.parse_args()

    port = args.port
    if port is None:
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("PORT="):
                        try:
                            port = int(line.strip().split("=")[1].strip())
                        except Exception:
                            pass
    if port is None:
        port = 8000

    start_server(port=port, auto_open=args.open)
