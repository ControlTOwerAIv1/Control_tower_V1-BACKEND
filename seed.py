from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
db.execute(text("INSERT INTO lead_time_setting (days, created_at, updated_at) VALUES ('14', NOW(), NOW())"))
db.commit()
print("Done - lead time set to 14 days")
db.close()