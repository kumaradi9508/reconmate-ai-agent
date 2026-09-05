"""
ReconMate - Synthetic Data Generator
Generates two datasets that simulate a real reconciliation problem:
  1. ledger.csv          -> Razorpay-side payment ledger (what the merchant's system recorded)
  2. bank_statement.csv  -> Bank/settlement-side statement (what actually landed in the bank)

Real-world reconciliation is messy on purpose. We inject:
  - Payment gateway fees (bank amount = ledger amount - fee)         -> "fuzzy match" case
  - Settlement delay (bank date = ledger date + 1-3 days)            -> "fuzzy match" case
  - Missing bank entries (payment never settled / still in transit)  -> "exception" case
  - Missing ledger entries (bank has an entry ledger doesn't know)   -> "exception" case
  - Duplicate bank entries (double settlement)                      -> "exception" case
  - Amount mismatches beyond normal fee range (needs human review)   -> "exception" case

Run: python3 generate_data.py
"""
import csv
import random
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

NUM_RECORDS = 65  # >50 as required by the track brief

FEE_RATE = 0.02  # typical payment gateway fee ~2%

ledger_rows = []
bank_rows = []

start_date = datetime(2026, 8, 1)

for i in range(1, NUM_RECORDS + 1):
    txn_id = f"pay_{100000 + i}"
    amount = round(random.uniform(200, 25000), 2)
    ledger_date = start_date + timedelta(days=random.randint(0, 25))
    merchant = fake.company()

    ledger_rows.append({
        "transaction_id": txn_id,
        "date": ledger_date.strftime("%Y-%m-%d"),
        "amount": amount,
        "merchant": merchant,
        "status": "captured",
    })

    # Decide what kind of bank-side event this becomes
    roll = random.random()

    if roll < 0.55:
        # Normal case: settles with fee deducted, 1-3 day delay
        fee = round(amount * FEE_RATE, 2)
        settled_amount = round(amount - fee, 2)
        settle_date = ledger_date + timedelta(days=random.randint(1, 3))
        bank_rows.append({
            "bank_ref": f"stl_{200000 + i}",
            "date": settle_date.strftime("%Y-%m-%d"),
            "amount": settled_amount,
            "narration": f"SETTLEMENT {txn_id}",
        })

    elif roll < 0.70:
        # Not yet settled / lost in transit -> ledger has it, bank doesn't (exception)
        pass

    elif roll < 0.80:
        # Duplicate settlement (bank double-counted) -> two bank rows for one ledger row
        fee = round(amount * FEE_RATE, 2)
        settled_amount = round(amount - fee, 2)
        settle_date = ledger_date + timedelta(days=random.randint(1, 3))
        for dup in range(2):
            bank_rows.append({
                "bank_ref": f"stl_{200000 + i}{'b' if dup else ''}",
                "date": settle_date.strftime("%Y-%m-%d"),
                "amount": settled_amount,
                "narration": f"SETTLEMENT {txn_id}",
            })

    elif roll < 0.90:
        # Amount mismatch beyond normal fee range (e.g. partial refund not reflected in ledger)
        settle_date = ledger_date + timedelta(days=random.randint(1, 3))
        bad_amount = round(amount * random.uniform(0.5, 0.85), 2)
        bank_rows.append({
            "bank_ref": f"stl_{200000 + i}",
            "date": settle_date.strftime("%Y-%m-%d"),
            "amount": bad_amount,
            "narration": f"SETTLEMENT {txn_id}",
        })

    else:
        # Settled but reference number got mangled (no clean txn_id in narration) -> needs fuzzy match
        fee = round(amount * FEE_RATE, 2)
        settled_amount = round(amount - fee, 2)
        settle_date = ledger_date + timedelta(days=random.randint(1, 3))
        bank_rows.append({
            "bank_ref": f"stl_{200000 + i}",
            "date": settle_date.strftime("%Y-%m-%d"),
            "amount": settled_amount,
            "narration": "SETTLEMENT MISC BATCH",  # no txn_id -> can't exact-match on reference
        })

# Add a few pure bank-side orphans (bank has money ledger never recorded - e.g. manual adjustment)
for j in range(4):
    settle_date = start_date + timedelta(days=random.randint(0, 28))
    bank_rows.append({
        "bank_ref": f"stl_{300000 + j}",
        "date": settle_date.strftime("%Y-%m-%d"),
        "amount": round(random.uniform(500, 5000), 2),
        "narration": "MANUAL ADJUSTMENT",
    })

random.shuffle(bank_rows)

with open("ledger.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["transaction_id", "date", "amount", "merchant", "status"])
    writer.writeheader()
    writer.writerows(ledger_rows)

with open("bank_statement.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["bank_ref", "date", "amount", "narration"])
    writer.writeheader()
    writer.writerows(bank_rows)

print(f"Generated {len(ledger_rows)} ledger rows -> ledger.csv")
print(f"Generated {len(bank_rows)} bank rows -> bank_statement.csv")
