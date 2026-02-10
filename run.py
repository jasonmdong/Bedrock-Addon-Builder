#!/usr/bin/env python3
"""
Entry point for running the Bedrock Add-on Builder server.
"""
import sys
import os

# Add backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=True)
