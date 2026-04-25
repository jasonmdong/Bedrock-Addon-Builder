"""Test database connection to Neon PostgreSQL."""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Set the environment variable
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require"

try:
    from backend.database import get_connection
    
    print("🔄 Testing database connection...")
    conn = get_connection()
    cur = conn.cursor()
    
    # Test query
    cur.execute("SELECT version();")
    version = cur.fetchone()
    print(f"✅ Connection successful!")
    print(f"📦 PostgreSQL version: {version[0]}")
    
    # List tables
    cur.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    tables = cur.fetchall()
    print(f"📊 Tables in database: {[t[0] for t in tables]}")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Connection failed: {e}")
    sys.exit(1)
