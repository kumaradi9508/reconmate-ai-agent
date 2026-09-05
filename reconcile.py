"""
ReconMate - Reconciliation Engine
Matches a payment ledger against a bank settlement statement in two passes:

  PASS 1 (exact):  match on transaction_id found inside the bank narration text.
  PASS 2 (fuzzy):   for anything still unmatched, match on
                     amount within expected fee range (0-4%) AND date within 3 days.

Anything left over after both passes is reported as an EXCEPTION, tagged with a
plain-English reason (missing settlement / duplicate settlement / amount mismatch /
unexplained bank credit), because a reconciliation agent that hides its failures
is worse than useless.

Run: python3 reconcile.py
Outputs: report.json, report.html
"""
import csv
import json
from datetime import datetime

FEE_MIN, FEE_MAX = 0.0, 0.04     # accept 0-4% deducted as a normal gateway fee
DATE_TOLERANCE_DAYS = 3


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")


def reconcile(ledger, bank):
    ledger = [dict(r, amount=float(r["amount"]), _date=parse_date(r["date"])) for r in ledger]
    bank = [dict(r, amount=float(r["amount"]), _date=parse_date(r["date"])) for r in bank]

    unmatched_bank = bank.copy()
    matched = []
    unmatched_ledger = []

    # PASS 1: exact match via transaction_id inside narration.
    # NOTE: matching the reference is necessary but not sufficient — if the reference
    # matches but the amount is way off (beyond a plausible fee), that's a real
    # discrepancy (e.g. an unrecorded partial refund) and must NOT be silently
    # accepted as a clean match. It gets kicked to the exception list instead, with
    # the amount flagged specifically (not just "missing").
    EXACT_MATCH_MAX_GAP = 0.06  # allow slightly more slack than the fuzzy pass, since
                                 # reference match already gives us high confidence
                                 # this is the right transaction
    flagged_reference_mismatches = []

    for txn in ledger:
        hit = None
        for b in unmatched_bank:
            if txn["transaction_id"] in b["narration"]:
                hit = b
                break
        if hit:
            fee_pct = 1 - (hit["amount"] / txn["amount"]) if txn["amount"] else 0
            if 0 <= fee_pct <= EXACT_MATCH_MAX_GAP:
                unmatched_bank.remove(hit)
                matched.append({
                    "transaction_id": txn["transaction_id"],
                    "ledger_amount": txn["amount"],
                    "bank_amount": hit["amount"],
                    "bank_ref": hit["bank_ref"],
                    "match_type": "exact_reference",
                    "fee_pct": round(fee_pct * 100, 2),
                })
            else:
                # Reference matched, but the amount gap is too large to be a normal fee.
                # Don't consume the bank row — flag it as a mismatch exception instead.
                unmatched_bank.remove(hit)
                flagged_reference_mismatches.append({
                    "type": "AMOUNT_MISMATCH",
                    "transaction_id": txn["transaction_id"],
                    "ledger_amount": txn["amount"],
                    "closest_bank_amount": hit["amount"],
                    "bank_ref": hit["bank_ref"],
                    "reason": (
                        f"Reference matched ({hit['bank_ref']}), but ledger shows "
                        f"{txn['amount']:.2f} vs bank {hit['amount']:.2f} — a "
                        f"{fee_pct*100:.1f}% gap is too large to be a normal gateway "
                        f"fee. Likely a partial refund or credit not reflected in the "
                        f"ledger."
                    ),
                })
        else:
            unmatched_ledger.append(txn)

    # PASS 2: fuzzy match on amount range + date proximity, for what's left
    still_unmatched_ledger = []
    for txn in unmatched_ledger:
        candidate = None
        for b in unmatched_bank:
            days_apart = abs((b["_date"] - txn["_date"]).days)
            if days_apart > DATE_TOLERANCE_DAYS:
                continue
            if txn["amount"] == 0:
                continue
            fee_pct = 1 - (b["amount"] / txn["amount"])
            if FEE_MIN <= fee_pct <= FEE_MAX:
                candidate = b
                break
        if candidate:
            unmatched_bank.remove(candidate)
            fee_pct = 1 - (candidate["amount"] / txn["amount"])
            matched.append({
                "transaction_id": txn["transaction_id"],
                "ledger_amount": txn["amount"],
                "bank_amount": candidate["amount"],
                "bank_ref": candidate["bank_ref"],
                "match_type": "fuzzy_amount_date",
                "fee_pct": round(fee_pct * 100, 2),
            })
        else:
            still_unmatched_ledger.append(txn)

    # Classify what's left as exceptions with an honest reason
    exceptions = []

    for txn in still_unmatched_ledger:
        # Was there a bank row with the same-ish amount but out of tolerance? -> mismatch, else missing
        near = [b for b in unmatched_bank if abs((b["_date"] - txn["_date"]).days) <= DATE_TOLERANCE_DAYS + 2]
        if near:
            best = min(near, key=lambda b: abs(b["amount"] - txn["amount"]))
            exceptions.append({
                "type": "AMOUNT_MISMATCH",
                "transaction_id": txn["transaction_id"],
                "ledger_amount": txn["amount"],
                "closest_bank_amount": best["amount"],
                "bank_ref": best["bank_ref"],
                "reason": (
                    f"Ledger shows {txn['amount']:.2f} but nearest bank credit is "
                    f"{best['amount']:.2f} — gap is larger than a normal gateway fee "
                    f"(possible partial refund not reflected in ledger)."
                ),
            })
            unmatched_bank.remove(best)
        else:
            exceptions.append({
                "type": "MISSING_SETTLEMENT",
                "transaction_id": txn["transaction_id"],
                "ledger_amount": txn["amount"],
                "reason": "No matching bank credit found within tolerance — payment may still be in transit or lost.",
            })

    exceptions.extend(flagged_reference_mismatches)

    # Whatever bank rows are STILL unmatched: duplicates or orphan credits
    seen_narrations = {}
    for b in unmatched_bank:
        seen_narrations.setdefault(b["narration"], []).append(b)

    for narration, rows in seen_narrations.items():
        if "MANUAL ADJUSTMENT" in narration:
            for b in rows:
                exceptions.append({
                    "type": "UNEXPLAINED_BANK_CREDIT",
                    "bank_ref": b["bank_ref"],
                    "bank_amount": b["amount"],
                    "reason": "Bank credit with no corresponding ledger entry — needs manual review.",
                })
        elif len(rows) > 1:
            for b in rows:
                exceptions.append({
                    "type": "DUPLICATE_SETTLEMENT",
                    "bank_ref": b["bank_ref"],
                    "bank_amount": b["amount"],
                    "reason": f"{len(rows)} bank credits share narration '{narration}' — likely a duplicate settlement.",
                })
        else:
            for b in rows:
                exceptions.append({
                    "type": "UNEXPLAINED_BANK_CREDIT",
                    "bank_ref": b["bank_ref"],
                    "bank_amount": b["amount"],
                    "reason": "Bank credit could not be tied to any ledger transaction within tolerance.",
                })

    total_ledger_amount = sum(t["amount"] for t in ledger)
    matched_amount = sum(m["ledger_amount"] for m in matched)

    summary = {
        "total_ledger_records": len(ledger),
        "total_bank_records": len(bank),
        "matched_count": len(matched),
        "exception_count": len(exceptions),
        "match_rate_pct": round(len(matched) / len(ledger) * 100, 1) if ledger else 0,
        "total_ledger_amount": round(total_ledger_amount, 2),
        "matched_amount": round(matched_amount, 2),
        "amount_reconciled_pct": round(matched_amount / total_ledger_amount * 100, 1) if total_ledger_amount else 0,
    }

    return {"summary": summary, "matched": matched, "exceptions": exceptions}


def render_html(result):
    s = result["summary"]
    rows_matched = "".join(
        f"<tr><td>{m['transaction_id']}</td><td>{m['ledger_amount']:.2f}</td>"
        f"<td>{m['bank_amount']:.2f}</td><td>{m['match_type']}</td><td>{m['fee_pct']}%</td></tr>"
        for m in result["matched"]
    )
    rows_exceptions = "".join(
        f"<tr><td>{e['type']}</td><td>{e.get('transaction_id', e.get('bank_ref',''))}</td>"
        f"<td>{e['reason']}</td></tr>"
        for e in result["exceptions"]
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ReconMate Report</title>
<style>
body {{ font-family: -apple-system, Arial, sans-serif; background:#0b0f14; color:#e6edf3; padding:32px; }}
h1 {{ color:#7ee787; }}
.stats {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
.card {{ background:#161b22; border:1px solid #30363d; border-radius:10px; padding:16px 20px; min-width:160px; }}
.card .num {{ font-size:28px; font-weight:700; color:#7ee787; }}
.card .label {{ font-size:12px; color:#8b949e; text-transform:uppercase; }}
table {{ width:100%; border-collapse: collapse; margin-bottom:32px; font-size:13px; }}
th, td {{ border-bottom:1px solid #30363d; padding:8px 10px; text-align:left; }}
th {{ color:#8b949e; text-transform:uppercase; font-size:11px; }}
tr:hover {{ background:#161b22; }}
.exception-row {{ color:#ffa657; }}
h2 {{ border-bottom:1px solid #30363d; padding-bottom:8px; }}
</style></head><body>
<h1>ReconMate — Reconciliation Report</h1>
<div class="stats">
  <div class="card"><div class="num">{s['match_rate_pct']}%</div><div class="label">Match Rate</div></div>
  <div class="card"><div class="num">{s['matched_count']}/{s['total_ledger_records']}</div><div class="label">Records Matched</div></div>
  <div class="card"><div class="num">{s['amount_reconciled_pct']}%</div><div class="label">Amount Reconciled</div></div>
  <div class="card"><div class="num">{s['exception_count']}</div><div class="label">Exceptions</div></div>
  <div class="card"><div class="num">₹{s['matched_amount']:,.0f}</div><div class="label">Amount Matched</div></div>
</div>

<h2>Matched Transactions ({s['matched_count']})</h2>
<table>
<tr><th>Transaction ID</th><th>Ledger Amount</th><th>Bank Amount</th><th>Match Type</th><th>Fee %</th></tr>
{rows_matched}
</table>

<h2>Exceptions ({s['exception_count']}) — needs a human</h2>
<table>
<tr><th>Type</th><th>Reference</th><th>Reason</th></tr>
{rows_exceptions}
</table>
</body></html>"""
    return html


if __name__ == "__main__":
    ledger = load_csv("ledger.csv")
    bank = load_csv("bank_statement.csv")
    result = reconcile(ledger, bank)

    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    with open("report.html", "w", encoding="utf-8") as f:
        f.write(render_html(result))

    print(json.dumps(result["summary"], indent=2))
    print("\nWritten: report.json, report.html")
