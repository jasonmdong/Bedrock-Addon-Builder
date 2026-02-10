#!/usr/bin/env python3
"""
Entry point for running the Bedrock Add-on Builder server.
"""
import sys
import os

# Add root directory to Python path so backend modules can be imported
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("backend.core.app:app", host="127.0.0.1", port=port, reload=True)
