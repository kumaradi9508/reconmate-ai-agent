"""
ReconMate - AI Agent Layer (Gemini)

This is what makes ReconMate an *agent* rather than just a matching script.
reconcile.py produces a list of exceptions with a static, templated reason string.
This module takes that list and asks an LLM (Gemini) to:
  1. Write a short executive summary of the whole batch, in plain English.
  2. For EACH exception, decide a specific recommended next action, and draft a
     short message a human could actually send to resolve it (e.g. to bank ops,
     to the merchant, to internal finance).

If no API key is set, or the API call fails for any reason (bad key, network,
rate limit), it falls back to a rule-based action generator instead of crashing
-- a demo should never go down because of a flaky API call.

Setup:
  1. Get a free API key from https://aistudio.google.com/apikey
  2. Set it as an environment variable:
       Mac/Linux:   export GOOGLE_API_KEY="your-key-here"
       Windows:     set GOOGLE_API_KEY=your-key-here
  3. pip install -r requirements.txt
  4. python3 ai_agent.py

Reads:  report.json          (produced by reconcile.py)
Writes: report_with_actions.json
        report.html          (adds an "AI Recommended Actions" section)
"""
import json
import os
import sys


def rule_based_action(exc):
    """Fallback used when no API key is available or the API call fails."""
    t = exc["type"]
    if t == "MISSING_SETTLEMENT":
        return {
            "recommended_action": "Escalate to payment gateway support to confirm settlement status.",
            "draft_message": (
                f"Hi team, we can't find a bank settlement for {exc.get('transaction_id')} "
                f"after the normal window. Can you confirm if this payment is still in "
                f"transit or failed?"
            ),
        }
    if t == "AMOUNT_MISMATCH":
        return {
            "recommended_action": "Check for a partial refund or fee change not reflected in the ledger.",
            "draft_message": (
                f"Hi team, transaction {exc.get('transaction_id')} settled for "
                f"{exc.get('closest_bank_amount', exc.get('bank_amount'))} instead of the expected "
                f"{exc.get('ledger_amount')}. Was there a refund or extra fee applied?"
            ),
        }
    if t == "DUPLICATE_SETTLEMENT":
        return {
            "recommended_action": "Flag for finance review — possible double payout, may need a reversal.",
            "draft_message": (
                f"Hi team, bank reference {exc.get('bank_ref')} looks like a duplicate "
                f"settlement. Please confirm and reverse if it's incorrect."
            ),
        }
    return {
        "recommended_action": "Manual review needed — no ledger record matches this bank credit.",
        "draft_message": (
            f"Hi team, we received a bank credit ({exc.get('bank_ref')}, amount "
            f"{exc.get('bank_amount')}) with no matching ledger entry. Can you help "
            f"identify where it came from?"
        ),
    }


def build_fallback_result(exceptions, summary):
    return {
        "executive_summary": (
            f"{summary['matched_count']}/{summary['total_ledger_records']} transactions reconciled "
            f"({summary['match_rate_pct']}% match rate, {summary['amount_reconciled_pct']}% of value). "
            f"{summary['exception_count']} exceptions need manual review — see recommended actions below."
        ),
        "exception_actions": [
            {"reference": e.get("transaction_id") or e.get("bank_ref"), **rule_based_action(e)}
            for e in exceptions
        ],
    }


def load_env():
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GOOGLE_API_KEY="):
                    val = line.strip().split("=", 1)[1].strip('"').strip("'")
                    if val:
                        os.environ["GOOGLE_API_KEY"] = val
                        return val
    return os.environ.get("GOOGLE_API_KEY", "")


def call_gemini(exceptions, summary):
    # pyrefly: ignore [missing-import]
    from google import genai

    api_key = load_env()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    prompt = f"""You are a finance-ops assistant reviewing a payment reconciliation batch.

Return STRICT JSON only — no markdown fences, no commentary before or after — matching exactly this shape:

{{
  "executive_summary": "2-3 sentence plain-English summary of this batch for a finance manager",
  "exception_actions": [
    {{"reference": "<the transaction_id or bank_ref from the input, copied exactly>", "recommended_action": "<one specific, concrete next step>", "draft_message": "<a short message a human could actually send to resolve this, 1-2 sentences>"}}
  ]
}}

Include one entry in exception_actions for every exception in the input, in the same order.

Reconciliation summary:
{json.dumps(summary)}

Exceptions:
{json.dumps(exceptions)}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    text = response.text.strip()

    # Defensive cleanup in case the model wraps the JSON in a markdown fence anyway
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def inject_ai_section_into_html(html_path, ai_result, source):
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    rows = "".join(
        f"<tr><td><code>{a.get('reference','')}</code></td>"
        f"<td>{a.get('recommended_action','')}</td>"
        f"<td><span style='color:#a5d6ff;'>{a.get('draft_message','')}</span></td>"
        f"<td><button onclick=\"askGeminiAbout('{a.get('reference','')}')\" style='background:#238636;color:white;border:none;padding:4px 8px;border-radius:4px;cursor:pointer;font-size:11px;'>Ask AI</button></td></tr>"
        for a in ai_result.get("exception_actions", [])
    )

    badge = "Gemini 2.5 Flash (Live Connected)" if source == "gemini" else "Rule-based fallback"
    badge_color = "#238636" if source == "gemini" else "#d29922"

    section = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px; border-bottom:1px solid #30363d; padding-bottom:8px;">
  <h2>AI Recommended Actions <span style="font-size:12px; background:{badge_color}; color:#fff; padding:3px 8px; border-radius:12px; margin-left:10px; font-weight:normal;">{badge}</span></h2>
  <button id="rerunBtn" onclick="triggerRerun()" style="background:#1f6feb; color:white; border:none; padding:8px 14px; border-radius:6px; font-weight:600; cursor:pointer;">⚡ Re-run Pipeline Live</button>
</div>

<div style="background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; margin:16px 0;">
  <div style="font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:6px; font-weight:600;">Executive Summary</div>
  <p style="color:#e6edf3; margin:0; line-height:1.5;">{ai_result.get('executive_summary','')}</p>
</div>

<table>
<tr><th>Reference</th><th>Recommended Action</th><th>Draft Message</th><th>Action</th></tr>
{rows}
</table>

<!-- Interactive Gemini Assistant Section -->
<div style="margin-top:36px; background:#161b22; border:1px solid #30363d; border-radius:10px; padding:20px;">
  <h3 style="margin-top:0; color:#58a6ff; display:flex; align-items:center; gap:8px;">
    🤖 Interactive Gemini Assistant
    <span style="font-size:11px; color:#8b949e; font-weight:normal;">(Server Backend Connected)</span>
  </h3>
  <p style="color:#8b949e; font-size:13px; margin-bottom:12px;">Ask any question about reconciling these payments, exceptions, or specific transactions:</p>
  <div style="display:flex; gap:10px; margin-bottom:12px;">
    <input id="aiQueryInput" type="text" placeholder="e.g. Why did pay_100003 mismatch? Or how should I handle unrecorded refunds?" 
           style="flex:1; background:#0d1117; border:1px solid #30363d; border-radius:6px; padding:10px 14px; color:#e6edf3; font-size:13px; outline:none;" 
           onkeydown="if(event.key==='Enter') sendGeminiQuery()" />
    <button id="askBtn" onclick="sendGeminiQuery()" style="background:#238636; color:white; border:none; padding:10px 18px; border-radius:6px; font-weight:600; cursor:pointer;">Ask Gemini</button>
  </div>
  <div id="aiResponseBox" style="display:none; background:#0d1117; border:1px solid #30363d; border-radius:6px; padding:14px; color:#e6edf3; font-size:13px; line-height:1.6;"></div>
</div>

<script>
async function triggerRerun() {{
  const btn = document.getElementById('rerunBtn');
  btn.disabled = true;
  btn.innerText = '⏳ Processing with Gemini...';
  try {{
    const res = await fetch('/api/reconcile', {{ method: 'POST' }});
    const data = await res.json();
    if (data.success) {{
      window.location.reload();
    }} else {{
      alert('Error running pipeline: ' + data.error);
    }}
  }} catch (err) {{
    alert('Server request failed: ' + err.message);
  }} finally {{
    btn.disabled = false;
    btn.innerText = '⚡ Re-run Pipeline Live';
  }}
}}

async function askGeminiAbout(ref) {{
  document.getElementById('aiQueryInput').value = 'Please analyze transaction ' + ref + ' and explain what happened and what specific steps I should take.';
  sendGeminiQuery(ref);
}}

async function sendGeminiQuery(reference) {{
  const input = document.getElementById('aiQueryInput');
  const query = input.value.trim();
  if (!query) return;
  
  const box = document.getElementById('aiResponseBox');
  const btn = document.getElementById('askBtn');
  box.style.display = 'block';
  box.innerHTML = '<span style="color:#8b949e;">Thinking with Gemini 2.5 Flash...</span>';
  btn.disabled = true;

  try {{
    const res = await fetch('/api/ask', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ query: query, reference: reference || '' }})
    }});
    const data = await res.json();
    if (data.success) {{
      box.innerHTML = '<strong>Gemini:</strong> ' + data.answer.replace(/\\n/g, '<br>');
    }} else {{
      box.innerHTML = '<span style="color:#f85149;">Error: ' + data.error + '</span>';
    }}
  }} catch (err) {{
    box.innerHTML = '<span style="color:#f85149;">Network Error: ' + err.message + '</span>';
  }} finally {{
    btn.disabled = false;
  }}
}}
</script>
"""
    html = html.replace("</body>", section + "</body>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    with open("report.json", encoding="utf-8") as f:
        report = json.load(f)

    exceptions = report["exceptions"]
    summary = report["summary"]

    try:
        ai_result = call_gemini(exceptions, summary)
        source = "gemini"
    except Exception as e:
        print(f"[ai_agent] Gemini unavailable ({e}) — using rule-based fallback.", file=sys.stderr)
        ai_result = build_fallback_result(exceptions, summary)
        source = "rule_based_fallback"

    report["ai_actions"] = ai_result
    report["ai_actions_source"] = source

    with open("report_with_actions.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    inject_ai_section_into_html("report.html", ai_result, source)

    print(f"Action source: {source}")
    print(f"Executive summary: {ai_result.get('executive_summary')}")
    print(f"\nWritten: report_with_actions.json, and updated report.html")


if __name__ == "__main__":
    main()
