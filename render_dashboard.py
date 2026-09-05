"""
ReconMate - Modern Dashboard Renderer
Generates a responsive, enterprise-grade dark UI dashboard for financial reconciliation.
Includes interactive tabs, live search, 1-click draft copying, and Gemini Copilot chat.
"""
import json
import urllib.parse

def render_dashboard(report_data, source="gemini"):
    summary = report_data.get("summary", {})
    matched = report_data.get("matched", [])
    exceptions = report_data.get("exceptions", [])
    ai_actions = report_data.get("ai_actions", {})
    
    exec_summary = ai_actions.get(
        "executive_summary",
        f"{summary.get('matched_count', 0)}/{summary.get('total_ledger_records', 0)} transactions reconciled "
        f"({summary.get('match_rate_pct', 0)}% match rate). {summary.get('exception_count', 0)} exceptions flagged for human review."
    )
    
    action_items = ai_actions.get("exception_actions", [])
    if not action_items and exceptions:
        # Build default rule-based action items if not present
        action_items = []
        for e in exceptions:
            ref = e.get("transaction_id") or e.get("bank_ref", "N/A")
            etype = e.get("type", "UNKNOWN")
            if etype == "MISSING_SETTLEMENT":
                act = "Escalate to payment gateway support to confirm settlement status."
                msg = f"Hi team, we can't find a bank settlement for {ref} after the normal window. Please confirm if in transit or failed."
            elif etype == "AMOUNT_MISMATCH":
                act = "Check for partial refund or fee discrepancy not in ledger."
                msg = f"Hi team, transaction {ref} settled for a mismatched amount. Please verify if a refund or penalty fee was applied."
            elif etype == "DUPLICATE_SETTLEMENT":
                act = "Flag for finance review — possible double payout requiring reversal."
                msg = f"Hi team, bank reference {ref} appears to be a duplicate settlement. Please confirm and reverse if necessary."
            else:
                act = "Investigate source of unexplained incoming credit."
                msg = f"Hi team, we received bank credit {ref} with no matching merchant ledger entry. Please identify the sender."
            action_items.append({"reference": ref, "recommended_action": act, "draft_message": msg})

    match_rate = summary.get("match_rate_pct", 0)
    matched_count = summary.get("matched_count", 0)
    total_ledger = summary.get("total_ledger_records", 0)
    total_bank = summary.get("total_bank_records", 0)
    reconciled_pct = summary.get("amount_reconciled_pct", 0)
    matched_amt = summary.get("matched_amount", 0)
    total_amt = summary.get("total_ledger_amount", 0)
    exc_count = summary.get("exception_count", 0)

    is_gemini = source == "gemini" or report_data.get("ai_actions_source") == "gemini"
    ai_badge_text = "Gemini 2.5 Flash (Live)" if is_gemini else "Rule-based Fallback"
    ai_badge_class = "badge-gemini" if is_gemini else "badge-fallback"

    # Action Items Table Rows
    action_rows = []
    for item in action_items:
        ref = item.get("reference", "")
        rec = item.get("recommended_action", "")
        draft = item.get("draft_message", "")
        # Find corresponding exception for type badge
        exc_match = next((e for e in exceptions if (e.get("transaction_id") == ref or e.get("bank_ref") == ref)), None)
        exc_type = exc_match.get("type", "ANOMALY") if exc_match else "ACTION"
        
        type_class = {
            "AMOUNT_MISMATCH": "badge-amber",
            "MISSING_SETTLEMENT": "badge-rose",
            "DUPLICATE_SETTLEMENT": "badge-purple",
            "UNEXPLAINED_BANK_CREDIT": "badge-blue"
        }.get(exc_type, "badge-slate")

        escaped_draft = draft.replace('"', '&quot;').replace("'", "&#39;")
        action_rows.append(f"""
        <tr class="action-row" data-ref="{ref}" data-type="{exc_type}">
            <td>
                <span class="font-mono text-bold text-blue">{ref}</span>
                <span class="badge {type_class} ml-2">{exc_type.replace('_', ' ')}</span>
            </td>
            <td class="text-slate-200">{rec}</td>
            <td>
                <div class="draft-container">
                    <span class="draft-text font-mono text-sm text-cyan">{draft}</span>
                    <button class="btn-copy" onclick="copyText('{escaped_draft}', this)" title="Copy message to clipboard">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        <span>Copy</span>
                    </button>
                </div>
            </td>
            <td class="text-right">
                <button class="btn-ask" onclick="askGeminiAbout('{ref}')">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                    <span>Ask AI</span>
                </button>
            </td>
        </tr>
        """)

    # Exceptions Table Rows
    exc_rows = []
    for e in exceptions:
        etype = e.get("type", "UNKNOWN")
        ref = e.get("transaction_id") or e.get("bank_ref", "N/A")
        reason = e.get("reason", "")
        ledger_a = f"₹{e.get('ledger_amount', 0):,.2f}" if "ledger_amount" in e else "—"
        bank_a = f"₹{e.get('closest_bank_amount', e.get('bank_amount', 0)):,.2f}" if ("closest_bank_amount" in e or "bank_amount" in e) else "—"

        type_class = {
            "AMOUNT_MISMATCH": "badge-amber",
            "MISSING_SETTLEMENT": "badge-rose",
            "DUPLICATE_SETTLEMENT": "badge-purple",
            "UNEXPLAINED_BANK_CREDIT": "badge-blue"
        }.get(etype, "badge-slate")

        exc_rows.append(f"""
        <tr class="exc-row" data-type="{etype}" data-search="{ref} {etype} {reason}">
            <td><span class="badge {type_class}">{etype.replace('_', ' ')}</span></td>
            <td><span class="font-mono text-bold text-slate-100">{ref}</span></td>
            <td class="font-mono text-slate-300">{ledger_a}</td>
            <td class="font-mono text-slate-300">{bank_a}</td>
            <td class="text-sm text-slate-300">{reason}</td>
            <td class="text-right">
                <button class="btn-ask-sm" onclick="askGeminiAbout('{ref}')">Ask AI</button>
            </td>
        </tr>
        """)

    # Matched Transactions Rows
    matched_rows = []
    for m in matched:
        tid = m.get("transaction_id", "")
        bref = m.get("bank_ref", "")
        lamt = m.get("ledger_amount", 0)
        bamt = m.get("bank_amount", 0)
        mtype = m.get("match_type", "")
        fee = m.get("fee_pct", 0)
        
        mtype_badge = '<span class="badge badge-emerald">Exact Reference</span>' if mtype == "exact_reference" else '<span class="badge badge-sky">Fuzzy Match (Date/Amt)</span>'

        matched_rows.append(f"""
        <tr class="matched-row" data-mtype="{mtype}" data-search="{tid} {bref} {mtype}">
            <td><span class="font-mono text-bold text-slate-100">{tid}</span></td>
            <td><span class="font-mono text-slate-400">{bref}</span></td>
            <td class="font-mono text-slate-200">₹{lamt:,.2f}</td>
            <td class="font-mono text-emerald">₹{bamt:,.2f}</td>
            <td>{mtype_badge}</td>
            <td class="font-mono text-sm text-slate-400">{fee}%</td>
        </tr>
        """)

    report_json_str = json.dumps(report_data, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ReconMate — AI Financial Reconciliation Agent</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #0a0e17;
            --bg-card: #111827;
            --bg-card-hover: #162032;
            --bg-subtle: #1e293b;
            --border: #1f293d;
            --border-highlight: #2e3d5b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-dim: #64748b;
            --emerald: #10b981;
            --emerald-bg: rgba(16, 185, 129, 0.12);
            --blue: #3b82f6;
            --blue-bg: rgba(59, 130, 246, 0.12);
            --amber: #f59e0b;
            --amber-bg: rgba(245, 158, 11, 0.12);
            --rose: #ef4444;
            --rose-bg: rgba(239, 68, 68, 0.12);
            --purple: #a855f7;
            --purple-bg: rgba(168, 85, 247, 0.12);
            --cyan: #38bdf8;
            --accent-glow: 0 0 25px rgba(59, 130, 246, 0.15);
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--bg-base);
            color: var(--text-main);
            line-height: 1.5;
            padding: 24px;
            min-height: 100vh;
        }}

        .container {{ max-width: 1360px; margin: 0 auto; }}
        
        /* Header */
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 28px;
        }}
        .brand {{ display: flex; align-items: center; gap: 14px; }}
        .brand-logo {{
            width: 44px; height: 44px;
            background: linear-gradient(135deg, #2563eb, #38bdf8);
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 22px;
            box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35);
        }}
        .brand-title {{ font-size: 22px; font-weight: 800; letter-spacing: -0.02em; color: #fff; }}
        .brand-subtitle {{ font-size: 13px; color: var(--text-muted); font-weight: 400; }}
        
        .header-actions {{ display: flex; align-items: center; gap: 12px; }}
        
        /* Buttons */
        .btn {{
            display: inline-flex; align-items: center; gap: 8px;
            padding: 9px 16px; border-radius: 8px;
            font-size: 13px; font-weight: 600;
            cursor: pointer; transition: all 0.15s ease;
            border: 1px solid transparent; text-decoration: none;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #fff;
            box-shadow: 0 2px 10px rgba(37, 99, 235, 0.25);
        }}
        .btn-primary:hover {{ background: linear-gradient(135deg, #1d4ed8, #1e40af); transform: translateY(-1px); }}
        .btn-outline {{
            background: var(--bg-card); color: var(--text-main);
            border-color: var(--border-highlight);
        }}
        .btn-outline:hover {{ background: var(--bg-subtle); border-color: var(--blue); }}
        
        .btn-copy {{
            display: inline-flex; align-items: center; gap: 5px;
            background: rgba(255, 255, 255, 0.06);
            color: var(--cyan); border: 1px solid rgba(56, 189, 248, 0.25);
            padding: 4px 9px; border-radius: 6px;
            font-size: 11px; font-weight: 600; cursor: pointer;
            transition: all 0.15s ease; white-space: nowrap;
        }}
        .btn-copy:hover {{ background: rgba(56, 189, 248, 0.15); border-color: var(--cyan); }}
        .btn-copy.copied {{ background: var(--emerald-bg); color: var(--emerald); border-color: var(--emerald); }}
        
        .btn-ask {{
            display: inline-flex; align-items: center; gap: 5px;
            background: var(--emerald-bg); color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 5px 10px; border-radius: 6px;
            font-size: 12px; font-weight: 600; cursor: pointer;
            transition: all 0.15s ease;
        }}
        .btn-ask:hover {{ background: var(--emerald); color: #fff; transform: translateY(-1px); }}

        .btn-ask-sm {{
            background: var(--blue-bg); color: var(--cyan);
            border: 1px solid rgba(56, 189, 248, 0.3);
            padding: 3px 8px; border-radius: 4px;
            font-size: 11px; font-weight: 600; cursor: pointer;
        }}
        .btn-ask-sm:hover {{ background: var(--blue); color: #fff; }}

        /* Badges */
        .badge {{
            display: inline-flex; align-items: center;
            padding: 3px 8px; border-radius: 6px;
            font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;
        }}
        .badge-gemini {{ background: var(--emerald-bg); color: var(--emerald); border: 1px solid rgba(16, 185, 129, 0.3); }}
        .badge-fallback {{ background: var(--amber-bg); color: var(--amber); border: 1px solid rgba(245, 158, 11, 0.3); }}
        .badge-emerald {{ background: var(--emerald-bg); color: var(--emerald); }}
        .badge-amber {{ background: var(--amber-bg); color: var(--amber); }}
        .badge-rose {{ background: var(--rose-bg); color: var(--rose); }}
        .badge-purple {{ background: var(--purple-bg); color: var(--purple); }}
        .badge-blue {{ background: var(--blue-bg); color: var(--cyan); }}
        .badge-sky {{ background: rgba(14, 165, 233, 0.12); color: #38bdf8; }}
        .badge-slate {{ background: var(--bg-subtle); color: var(--text-muted); }}

        /* KPI Grid */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            position: relative;
            overflow: hidden;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        .kpi-card:hover {{
            border-color: var(--border-highlight);
            box-shadow: 0 6px 20px rgba(0,0,0,0.3);
        }}
        .kpi-card::before {{
            content: '';
            position: absolute; top: 0; left: 0; right: 0; height: 3px;
        }}
        .kpi-card.kpi-green::before {{ background: linear-gradient(90deg, #10b981, #059669); }}
        .kpi-card.kpi-blue::before {{ background: linear-gradient(90deg, #3b82f6, #2563eb); }}
        .kpi-card.kpi-amber::before {{ background: linear-gradient(90deg, #f59e0b, #d97706); }}
        .kpi-card.kpi-purple::before {{ background: linear-gradient(90deg, #a855f7, #7c3aed); }}

        .kpi-title {{ font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.05em; }}
        .kpi-value {{ font-size: 30px; font-weight: 800; color: #fff; margin: 6px 0 2px; font-family: 'Inter', sans-serif; letter-spacing: -0.02em; }}
        .kpi-subtext {{ font-size: 12px; color: var(--text-dim); display: flex; align-items: center; gap: 6px; }}
        .kpi-progress {{ height: 5px; background: var(--bg-subtle); border-radius: 3px; margin-top: 10px; overflow: hidden; }}
        .kpi-progress-bar {{ height: 100%; border-radius: 3px; }}

        /* Executive Banner */
        .exec-banner {{
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(17, 24, 39, 0.9));
            border: 1px solid var(--border-highlight);
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 28px;
            display: flex; gap: 18px; align-items: flex-start;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.2);
        }}
        .exec-icon {{
            width: 40px; height: 40px; border-radius: 10px;
            background: var(--blue-bg); color: var(--blue);
            display: flex; align-items: center; justify-content: center;
            font-size: 20px; flex-shrink: 0;
        }}
        .exec-title {{ font-size: 13px; font-weight: 700; text-transform: uppercase; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 4px; }}
        .exec-text {{ color: #e2e8f0; font-size: 14.5px; line-height: 1.6; }}

        /* Search & Tab Controls */
        .control-bar {{
            display: flex; justify-content: space-between; align-items: center;
            flex-wrap: wrap; gap: 16px; margin-bottom: 20px;
        }}
        .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .tab-btn {{
            background: var(--bg-card); color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 9px 16px; border-radius: 8px;
            font-size: 13px; font-weight: 600; cursor: pointer;
            transition: all 0.15s ease; display: inline-flex; align-items: center; gap: 8px;
        }}
        .tab-btn:hover {{ background: var(--bg-subtle); color: var(--text-main); }}
        .tab-btn.active {{
            background: var(--blue-bg); color: var(--cyan);
            border-color: rgba(56, 189, 248, 0.4);
            box-shadow: 0 0 15px rgba(56, 189, 248, 0.12);
        }}
        .tab-count {{
            background: rgba(255, 255, 255, 0.08); padding: 1px 6px;
            border-radius: 10px; font-size: 11px;
        }}

        .search-box {{
            position: relative; min-width: 280px;
        }}
        .search-input {{
            width: 100%; background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px; padding: 9px 14px 9px 34px;
            color: #fff; font-size: 13px; outline: none;
            transition: border-color 0.15s;
        }}
        .search-input:focus {{ border-color: var(--blue); box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2); }}
        .search-icon {{
            position: absolute; left: 11px; top: 50%; transform: translateY(-50%);
            color: var(--text-dim); pointer-events: none;
        }}

        /* Table Card */
        .table-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.25);
            margin-bottom: 28px;
        }}
        .table-header {{
            padding: 16px 20px;
            display: flex; justify-content: space-between; align-items: center;
            border-bottom: 1px solid var(--border);
            background: rgba(17, 24, 39, 0.6);
        }}
        .table-title {{ font-size: 15px; font-weight: 700; color: #fff; }}
        .table-subtitle {{ font-size: 12px; color: var(--text-muted); }}

        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13.5px; }}
        th {{
            background: rgba(15, 23, 42, 0.8);
            color: var(--text-muted);
            font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
            padding: 12px 18px; border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 14px 18px; border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }}
        tr:hover {{ background-color: var(--bg-card-hover); }}
        tr:last-child td {{ border-bottom: none; }}

        .draft-container {{ display: flex; align-items: center; gap: 10px; justify-content: space-between; }}
        .draft-text {{ max-width: 480px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}

        /* Sub-filter chips */
        .filter-chips {{ display: flex; gap: 8px; padding: 12px 20px; border-bottom: 1px solid var(--border); background: rgba(15, 23, 42, 0.4); flex-wrap: wrap; }}
        .chip {{
            padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 500;
            background: var(--bg-subtle); color: var(--text-muted); cursor: pointer; border: 1px solid transparent;
            transition: all 0.15s;
        }}
        .chip:hover {{ color: var(--text-main); background: #283548; }}
        .chip.active {{ background: var(--blue-bg); color: var(--cyan); border-color: rgba(56, 189, 248, 0.4); font-weight: 600; }}

        /* Chat Copilot Card */
        .chat-card {{
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 12px; padding: 24px; margin-bottom: 28px;
        }}
        .chat-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }}
        .chat-avatar {{
            width: 36px; height: 36px; border-radius: 10px;
            background: linear-gradient(135deg, #10b981, #06b6d4);
            display: flex; align-items: center; justify-content: center; font-size: 18px;
        }}
        .chat-prompt-chips {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }}
        .prompt-chip {{
            font-size: 12px; background: var(--bg-subtle); color: var(--cyan);
            border: 1px solid rgba(56, 189, 248, 0.2); padding: 5px 12px; border-radius: 16px;
            cursor: pointer; transition: all 0.15s;
        }}
        .prompt-chip:hover {{ background: rgba(56, 189, 248, 0.15); border-color: var(--cyan); }}

        .chat-input-row {{ display: flex; gap: 10px; }}
        .chat-input {{
            flex: 1; background: var(--bg-base); border: 1px solid var(--border-highlight);
            border-radius: 8px; padding: 12px 16px; color: #fff; font-size: 13.5px; outline: none;
        }}
        .chat-input:focus {{ border-color: var(--blue); box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2); }}

        .chat-response-box {{
            margin-top: 16px; background: var(--bg-base); border: 1px solid var(--border);
            border-radius: 10px; padding: 18px; font-size: 14px; line-height: 1.6;
            color: #e2e8f0; display: none;
        }}

        /* Code & JSON View */
        .json-box {{
            background: #090d14; border: 1px solid var(--border);
            border-radius: 10px; padding: 20px; font-family: 'JetBrains Mono', monospace;
            font-size: 12.5px; color: #a5d6ff; max-height: 500px; overflow-y: auto; white-space: pre;
        }}

        /* Toast notifications */
        .toast {{
            position: fixed; bottom: 24px; right: 24px;
            background: #1e293b; color: #fff; border: 1px solid var(--emerald);
            padding: 12px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5); display: flex; align-items: center; gap: 8px;
            transform: translateY(100px); opacity: 0; transition: all 0.3s ease; z-index: 1000;
        }}
        .toast.show {{ transform: translateY(0); opacity: 1; }}

        /* Utilities */
        .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
        .text-bold {{ font-weight: 600; }}
        .text-sm {{ font-size: 12px; }}
        .text-blue {{ color: var(--cyan); }}
        .text-emerald {{ color: var(--emerald); }}
        .text-right {{ text-align: right; }}
        .text-slate-100 {{ color: #f1f5f9; }}
        .text-slate-200 {{ color: #e2e8f0; }}
        .text-slate-300 {{ color: #cbd5e1; }}
        .text-slate-400 {{ color: #94a3b8; }}
        .ml-2 {{ margin-left: 8px; }}

        @media (max-width: 768px) {{
            body {{ padding: 14px; }}
            .kpi-grid {{ grid-template-columns: 1fr; }}
            .header {{ flex-direction: column; align-items: flex-start; }}
            .control-bar {{ flex-direction: column; align-items: stretch; }}
            .search-box {{ width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header class="header">
            <div class="brand">
                <div class="brand-logo">⚡</div>
                <div>
                    <h1 class="brand-title">ReconMate</h1>
                    <p class="brand-subtitle">Autonomous Financial Reconciliation & Settlement Agent</p>
                </div>
            </div>
            <div class="header-actions">
                <span class="badge {ai_badge_class}">
                    <span style="display:inline-block; width:6px; height:6px; background:currentColor; border-radius:50%; margin-right:6px;"></span>
                    {ai_badge_text}
                </span>
                <button id="rerunBtn" class="btn btn-primary" onclick="triggerRerun()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                    <span>Re-run Pipeline</span>
                </button>
            </div>
        </header>

        <!-- KPI Metrics Grid -->
        <div class="kpi-grid">
            <div class="kpi-card kpi-green">
                <div class="kpi-title">Match Rate (Count)</div>
                <div class="kpi-value">{match_rate}%</div>
                <div class="kpi-subtext"><span>{matched_count}</span> of <span>{total_ledger}</span> ledger records matched</div>
                <div class="kpi-progress"><div class="kpi-progress-bar" style="width: {match_rate}%; background: var(--emerald);"></div></div>
            </div>

            <div class="kpi-card kpi-blue">
                <div class="kpi-title">Amount Reconciled</div>
                <div class="kpi-value">₹{matched_amt:,.0f}</div>
                <div class="kpi-subtext"><span>{reconciled_pct}%</span> of total volume (₹{total_amt:,.0f})</div>
                <div class="kpi-progress"><div class="kpi-progress-bar" style="width: {reconciled_pct}%; background: var(--blue);"></div></div>
            </div>

            <div class="kpi-card kpi-amber">
                <div class="kpi-title">Exceptions Flagged</div>
                <div class="kpi-value">{exc_count}</div>
                <div class="kpi-subtext">Requires review & human resolution</div>
                <div class="kpi-progress"><div class="kpi-progress-bar" style="width: {min(100, exc_count*4)}%; background: var(--amber);"></div></div>
            </div>

            <div class="kpi-card kpi-purple">
                <div class="kpi-title">Bank Statements</div>
                <div class="kpi-value">{total_bank}</div>
                <div class="kpi-subtext">Processed across 0–4% fee range & 3d window</div>
                <div class="kpi-progress"><div class="kpi-progress-bar" style="width: 100%; background: var(--purple);"></div></div>
            </div>
        </div>

        <!-- Executive Summary Banner -->
        <div class="exec-banner">
            <div class="exec-icon">💡</div>
            <div>
                <div class="exec-title">Executive Summary — Gemini AI Synthesis</div>
                <p class="exec-text">{exec_summary}</p>
            </div>
        </div>

        <!-- Navigation Tabs & Search Controls -->
        <div class="control-bar">
            <div class="tabs">
                <button class="tab-btn active" onclick="switchTab('ai-actions', this)">
                    <span>🤖 AI Action Center</span>
                    <span class="tab-count">{len(action_items)}</span>
                </button>
                <button class="tab-btn" onclick="switchTab('exceptions', this)">
                    <span>🚨 Exceptions</span>
                    <span class="tab-count">{exc_count}</span>
                </button>
                <button class="tab-btn" onclick="switchTab('matched', this)">
                    <span>✅ Matched</span>
                    <span class="tab-count">{matched_count}</span>
                </button>
                <button class="tab-btn" onclick="switchTab('copilot', this)">
                    <span>💬 Gemini Copilot</span>
                </button>
                <button class="tab-btn" onclick="switchTab('audit', this)">
                    <span>📄 Audit JSON</span>
                </button>
            </div>

            <div class="search-box">
                <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                <input id="globalSearch" class="search-input" type="text" placeholder="Search reference, type, amount..." oninput="filterGlobalSearch(this.value)">
            </div>
        </div>

        <!-- TAB 1: AI Action Center -->
        <div id="tab-ai-actions" class="tab-content">
            <div class="table-card">
                <div class="table-header">
                    <div>
                        <div class="table-title">Prescribed Actions & Communication Drafts</div>
                        <div class="table-subtitle">AI-generated resolution steps and ready-to-dispatch communications</div>
                    </div>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 220px;">Reference / Type</th>
                            <th style="width: 280px;">Recommended Action</th>
                            <th>Draft Message (Ready to Send)</th>
                            <th style="width: 110px; text-align: right;">AI Assist</th>
                        </tr>
                    </thead>
                    <tbody id="actionTableBody">
                        {''.join(action_rows)}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- TAB 2: Exceptions Table -->
        <div id="tab-exceptions" class="tab-content" style="display:none;">
            <div class="table-card">
                <div class="table-header">
                    <div>
                        <div class="table-title">Exceptions Audit Log ({exc_count} Items)</div>
                        <div class="table-subtitle">Transactions requiring investigation beyond deterministic fee/time tolerances</div>
                    </div>
                </div>
                <div class="filter-chips">
                    <button class="chip active" onclick="filterExceptions('ALL', this)">All ({exc_count})</button>
                    <button class="chip" onclick="filterExceptions('AMOUNT_MISMATCH', this)">Amount Mismatch</button>
                    <button class="chip" onclick="filterExceptions('MISSING_SETTLEMENT', this)">Missing Settlement</button>
                    <button class="chip" onclick="filterExceptions('DUPLICATE_SETTLEMENT', this)">Duplicate Settlement</button>
                    <button class="chip" onclick="filterExceptions('UNEXPLAINED_BANK_CREDIT', this)">Unexplained Credit</button>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 170px;">Anomaly Type</th>
                            <th style="width: 140px;">Reference</th>
                            <th style="width: 120px;">Ledger Amt</th>
                            <th style="width: 120px;">Bank Amt</th>
                            <th>Detailed Reason</th>
                            <th style="width: 90px; text-align: right;">Action</th>
                        </tr>
                    </thead>
                    <tbody id="excTableBody">
                        {''.join(exc_rows)}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- TAB 3: Matched Transactions Table -->
        <div id="tab-matched" class="tab-content" style="display:none;">
            <div class="table-card">
                <div class="table-header">
                    <div>
                        <div class="table-title">Matched Settlements ({matched_count} Transactions)</div>
                        <div class="table-subtitle">Deterministic reconciliation via exact narration reference and fuzzy date/fee proximity</div>
                    </div>
                </div>
                <div class="filter-chips">
                    <button class="chip active" onclick="filterMatched('ALL', this)">All Matched ({matched_count})</button>
                    <button class="chip" onclick="filterMatched('exact_reference', this)">Exact Reference</button>
                    <button class="chip" onclick="filterMatched('fuzzy_amount_date', this)">Fuzzy Match</button>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 160px;">Transaction ID</th>
                            <th style="width: 160px;">Bank Ref</th>
                            <th style="width: 140px;">Ledger Amount</th>
                            <th style="width: 140px;">Bank Settled</th>
                            <th style="width: 200px;">Match Methodology</th>
                            <th style="width: 100px;">Fee %</th>
                        </tr>
                    </thead>
                    <tbody id="matchedTableBody">
                        {''.join(matched_rows)}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- TAB 4: Gemini Copilot -->
        <div id="tab-copilot" class="tab-content" style="display:none;">
            <div class="chat-card">
                <div class="chat-header">
                    <div class="chat-avatar">🤖</div>
                    <div>
                        <div style="font-size:16px; font-weight:700; color:#fff;">Interactive Gemini Reconciliation Assistant</div>
                        <div style="font-size:13px; color:var(--text-muted);">Query payment anomalies, ask for root cause analysis, or generate reports in natural language.</div>
                    </div>
                </div>

                <div class="chat-prompt-chips">
                    <button class="prompt-chip" onclick="setQueryPrompt('Why did pay_100003 mismatch?')">🔎 Why did pay_100003 mismatch?</button>
                    <button class="prompt-chip" onclick="setQueryPrompt('Summarize all amount mismatch exceptions and their potential refund causes.')">📊 Summarize refund mismatches</button>
                    <button class="prompt-chip" onclick="setQueryPrompt('Draft a polite formal escalation letter to Bank Ops regarding unexplained credits.')">✉️ Draft Bank Ops escalation letter</button>
                    <button class="prompt-chip" onclick="setQueryPrompt('What is our overall reconciliation health and top risk factor?')">🛡️ Top financial risk assessment</button>
                </div>

                <div class="chat-input-row">
                    <input id="aiQueryInput" class="chat-input" type="text" placeholder="Ask anything regarding these transactions, exceptions, or bank statements..." onkeydown="if(event.key==='Enter') sendGeminiQuery()">
                    <button id="askBtn" class="btn btn-primary" onclick="sendGeminiQuery()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                        <span>Ask Gemini</span>
                    </button>
                </div>

                <div id="aiResponseBox" class="chat-response-box"></div>
            </div>
        </div>

        <!-- TAB 5: Audit JSON -->
        <div id="tab-audit" class="tab-content" style="display:none;">
            <div class="table-card" style="padding: 20px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                    <div>
                        <div class="table-title">Raw Reconciliation & Agent JSON</div>
                        <div class="table-subtitle">Structured payload for API consumers, webhooks, and audit logs</div>
                    </div>
                    <div style="display:flex; gap:10px;">
                        <button class="btn btn-outline" onclick="copyJson()">Copy JSON</button>
                        <a class="btn btn-primary" href="data:text/json;charset=utf-8,{urllib.parse.quote(report_json_str)}" download="reconciliation_report.json">Download JSON</a>
                    </div>
                </div>
                <div id="jsonViewer" class="json-box">{report_json_str}</div>
            </div>
        </div>
    </div>

    <!-- Toast Notification -->
    <div id="toast" class="toast">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
        <span id="toastMsg">Message copied to clipboard</span>
    </div>

    <script>
    // Tab Switching
    function switchTab(tabId, btn) {{
        document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        
        const target = document.getElementById('tab-' + tabId);
        if (target) target.style.display = 'block';
        if (btn) btn.classList.add('active');
    }}

    // Global Search Filter
    function filterGlobalSearch(term) {{
        const q = term.toLowerCase().trim();
        
        // Filter Action Rows
        document.querySelectorAll('#actionTableBody tr').forEach(row => {{
            const text = row.innerText.toLowerCase();
            row.style.display = text.includes(q) ? '' : 'none';
        }});

        // Filter Exception Rows
        document.querySelectorAll('#excTableBody tr').forEach(row => {{
            const searchData = (row.getAttribute('data-search') || row.innerText).toLowerCase();
            row.style.display = searchData.includes(q) ? '' : 'none';
        }});

        // Filter Matched Rows
        document.querySelectorAll('#matchedTableBody tr').forEach(row => {{
            const searchData = (row.getAttribute('data-search') || row.innerText).toLowerCase();
            row.style.display = searchData.includes(q) ? '' : 'none';
        }});
    }}

    // Exception Sub-filters
    function filterExceptions(category, btn) {{
        document.querySelectorAll('#tab-exceptions .chip').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        
        document.querySelectorAll('#excTableBody tr').forEach(row => {{
            const type = row.getAttribute('data-type');
            if (category === 'ALL' || type === category) {{
                row.style.display = '';
            }} else {{
                row.style.display = 'none';
            }}
        }});
    }}

    // Matched Sub-filters
    function filterMatched(mtype, btn) {{
        document.querySelectorAll('#tab-matched .chip').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('#matchedTableBody tr').forEach(row => {{
            const type = row.getAttribute('data-mtype');
            if (mtype === 'ALL' || type === mtype) {{
                row.style.display = '';
            }} else {{
                row.style.display = 'none';
            }}
        }});
    }}

    // Copy draft message
    function copyText(text, btn) {{
        navigator.clipboard.writeText(text).then(() => {{
            showToast('Draft message copied to clipboard');
            if (btn) {{
                const orig = btn.innerHTML;
                btn.classList.add('copied');
                btn.innerHTML = '<span>✓ Copied</span>';
                setTimeout(() => {{
                    btn.classList.remove('copied');
                    btn.innerHTML = orig;
                }}, 2000);
            }}
        }}).catch(() => {{
            // Fallback
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            showToast('Draft message copied to clipboard');
        }});
    }}

    function copyJson() {{
        const jsonText = document.getElementById('jsonViewer').innerText;
        navigator.clipboard.writeText(jsonText).then(() => {{
            showToast('JSON copied to clipboard');
        }});
    }}

    function showToast(msg) {{
        const t = document.getElementById('toast');
        document.getElementById('toastMsg').innerText = msg;
        t.classList.add('show');
        setTimeout(() => t.classList.remove('show'), 2500);
    }}

    // Ask Gemini shortcut from row
    function askGeminiAbout(ref) {{
        switchTab('copilot', document.querySelectorAll('.tab-btn')[3]);
        document.getElementById('aiQueryInput').value = 'Please analyze transaction ' + ref + ' and explain what happened and what specific steps I should take.';
        sendGeminiQuery(ref);
    }}

    function setQueryPrompt(prompt) {{
        document.getElementById('aiQueryInput').value = prompt;
        sendGeminiQuery();
    }}

    // Query Gemini API
    async function sendGeminiQuery(reference) {{
        const input = document.getElementById('aiQueryInput');
        const query = input.value.trim();
        if (!query) return;

        const box = document.getElementById('aiResponseBox');
        const btn = document.getElementById('askBtn');
        box.style.display = 'block';
        box.innerHTML = '<div style="display:flex; align-items:center; gap:10px; color:var(--cyan);"><span style="animation:spin 1s linear infinite;">⏳</span> Thinking with Gemini 2.5 Flash...</div>';
        btn.disabled = true;

        try {{
            const res = await fetch('/api/ask', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ query: query, reference: reference || '' }})
            }});
            const data = await res.json();
            if (data.success) {{
                box.innerHTML = '<div style="color:var(--emerald); font-weight:700; margin-bottom:6px; display:flex; align-items:center; gap:6px;"><span>⚡ Gemini AI Analysis:</span></div><div style="line-height:1.6; color:#f1f5f9;">' + data.answer.replace(/\\n/g, '<br>') + '</div>';
            }} else {{
                box.innerHTML = '<div style="color:var(--rose); font-weight:600;">Error: ' + data.error + '</div>';
            }}
        }} catch (err) {{
            box.innerHTML = '<div style="color:var(--amber);"><strong>Static Mode / Offline:</strong> To interact with live Gemini queries in real-time, please start the ReconMate server (<code>python server.py</code>).<br><small style="color:var(--text-dim);">' + err.message + '</small></div>';
        }} finally {{
            btn.disabled = false;
        }}
    }}

    // Trigger Pipeline Rerun
    async function triggerRerun() {{
        const btn = document.getElementById('rerunBtn');
        btn.disabled = true;
        const origContent = btn.innerHTML;
        btn.innerHTML = '<span>⏳ Running Gemini Pipeline...</span>';

        try {{
            const res = await fetch('/api/reconcile', {{ method: 'POST' }});
            const data = await res.json();
            if (data.success) {{
                showToast('Pipeline completed! Reloading...');
                setTimeout(() => window.location.reload(), 800);
            }} else {{
                alert('Pipeline error: ' + data.error);
            }}
        }} catch (err) {{
            alert('Re-run live requires the ReconMate server. Run: python server.py\\n\\nError: ' + err.message);
        }} finally {{
            btn.disabled = false;
            btn.innerHTML = origContent;
        }}
    }}
    </script>
</body>
</html>"""
    return html
