
import os
from dotenv import load_dotenv
load_dotenv()
from backend.database.supabase_client import get_service_client

print(f"Checking Supabase connection to: {os.getenv('SUPABASE_URL')}")
try:
    # A simple query to check if the DB is reachable
    res = get_service_client().table('profiles').select('id').limit(1).execute()
    print("✅ Supabase is ONLINE and responding.")
except Exception as e:
    print(f"❌ Supabase connection FAILED.")
    print(f"Error detail: {e}")
    if "503" in str(e) or "paused" in str(e).lower():
        print("Suggestion: Your Supabase project might be PAUSED due to inactivity. Please log in to the Supabase dashboard to resume it.")
