#!/usr/bin/env python3
"""Clean up LLM log files from data/llm_logs/"""
import shutil
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "data" / "llm_logs"

def clean_logs():
    if not LOG_DIR.exists():
        print("No llm_logs directory found.")
        return
    
    log_files = list(LOG_DIR.glob("*.json"))
    if not log_files:
        print("No log files to clean.")
        return
    
    print(f"Found {len(log_files)} log file(s) in {LOG_DIR}")
    confirm = input("Delete all? (y/n): ").strip().lower()
    
    if confirm == "y":
        for f in log_files:
            f.unlink()
        print(f"Deleted {len(log_files)} log file(s).")
    else:
        print("Cancelled.")

if __name__ == "__main__":
    clean_logs()
