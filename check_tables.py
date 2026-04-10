# Save as check_sales.py and run: python check_sales.py
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

tables = ['invoice', 'invoice_details', 'sales_bill', 'sales_bill_details']
for t in tables:
    count = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
    print(f"{t}: {count} rows")

# Also check invoice columns
print("\n--- invoice columns ---")
cols = db.execute(text("DESCRIBE invoice")).fetchall()
for c in cols:
    print(c[0], c[1])

print("\n--- invoice_details columns ---")
cols = db.execute(text("DESCRIBE invoice_details")).fetchall()
for c in cols:
    print(c[0], c[1])

db.close()