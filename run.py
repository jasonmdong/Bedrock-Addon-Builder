#!/usr/bin/env python3
"""
Entry point for running the Bedrock Add-on Builder server.
"""
import sys
import os
from pathlib import Path

# Add root directory to Python path so backend modules can be imported
root_dir = os.path.dirname(__file__)
sys.path.insert(0, root_dir)

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(root_dir) / ".env"
    if env_path.exists():
        print(f"📦 Loading environment from {env_path}")
        load_dotenv(env_path)
except ImportError:
    print("⚠️ python-dotenv not installed, skipping .env loading")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    
    # Verify psycopg2 is available
    try:
        import psycopg2
        print(f"✓ psycopg2 {psycopg2.__version__} available")
    except ImportError:
        print("⚠️ psycopg2 not found - database features will fail")
    
    # Verify DATABASE_URL is set
    if os.environ.get("DATABASE_URL"):
        print("✓ DATABASE_URL is set")
    else:
        print("⚠️ DATABASE_URL not set - database features will fail")
    
    uvicorn.run("backend.core.app:app", host="127.0.0.1", port=port, reload=True)
