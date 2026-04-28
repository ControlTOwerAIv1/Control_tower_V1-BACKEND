from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).resolve().parent / ".env")
key = os.getenv("ANTHROPIC_API_KEY", "")
print("Key found:", bool(key))
print("Key prefix:", key[:10] if key else "MISSING - check your .env file")
