"""LLM Request/Response Logging for analysis and debugging.

Logs all LLM calls with:
- Timestamp
- Provider used
- Input prompt and spec
- Output spec
- Validation results
- Scoring results (if available)

Logs are stored as JSON files in data/llm_logs/
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from backend.core.core import BASE_DIR


# Log directory
LOG_DIR = BASE_DIR / "data" / "llm_logs"


def _ensure_log_dir():
    """Ensure the log directory exists."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_llm_call(
    provider: str,
    prompt: str,
    input_spec: dict,
    output_spec: Optional[dict] = None,
    error: Optional[str] = None,
    validation_passed: bool = True,
    semantic_score: Optional[float] = None,
    duration_ms: Optional[int] = None,
    metadata: Optional[dict] = None
) -> str:
    """Log an LLM call to disk.
    
    Returns the log ID (filename without extension).
    """
    _ensure_log_dir()
    
    log_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    
    log_entry = {
        "id": log_id,
        "timestamp": datetime.now().isoformat(),
        "provider": provider,
        "prompt": prompt,
        "input_spec": input_spec,
        "output_spec": output_spec,
        "error": error,
        "validation_passed": validation_passed,
        "semantic_score": semantic_score,
        "duration_ms": duration_ms,
        "metadata": metadata or {}
    }
    
    log_path = LOG_DIR / f"{log_id}.json"
    log_path.write_text(json.dumps(log_entry, indent=2), encoding="utf-8")
    
    return log_id


def get_log(log_id: str) -> Optional[dict]:
    """Retrieve a log entry by ID."""
    _ensure_log_dir()
    log_path = LOG_DIR / f"{log_id}.json"
    if log_path.exists():
        return json.loads(log_path.read_text(encoding="utf-8"))
    return None


def list_logs(
    limit: int = 100,
    provider: Optional[str] = None,
    errors_only: bool = False,
    since: Optional[datetime] = None
) -> list[dict]:
    """List recent log entries with optional filtering.
    
    Args:
        limit: Maximum number of logs to return
        provider: Filter by provider name
        errors_only: Only return logs with errors
        since: Only return logs after this datetime
    
    Returns:
        List of log entries (most recent first)
    """
    _ensure_log_dir()
    
    logs = []
    for log_path in sorted(LOG_DIR.glob("*.json"), reverse=True):
        if len(logs) >= limit:
            break
            
        try:
            entry = json.loads(log_path.read_text(encoding="utf-8"))
            
            # Apply filters
            if provider and entry.get("provider") != provider:
                continue
            if errors_only and not entry.get("error"):
                continue
            if since:
                log_time = datetime.fromisoformat(entry["timestamp"])
                if log_time < since:
                    continue
            
            logs.append(entry)
        except Exception:
            continue
    
    return logs


def get_provider_stats(since: Optional[datetime] = None) -> dict:
    """Get aggregate statistics per provider.
    
    Returns dict with per-provider stats:
    - total_calls
    - error_count
    - avg_semantic_score
    - validation_fail_count
    """
    logs = list_logs(limit=10000, since=since)
    
    stats = {}
    for log in logs:
        provider = log.get("provider", "unknown")
        if provider not in stats:
            stats[provider] = {
                "total_calls": 0,
                "error_count": 0,
                "validation_fail_count": 0,
                "semantic_scores": [],
                "durations": []
            }
        
        s = stats[provider]
        s["total_calls"] += 1
        
        if log.get("error"):
            s["error_count"] += 1
        if not log.get("validation_passed", True):
            s["validation_fail_count"] += 1
        if log.get("semantic_score") is not None:
            s["semantic_scores"].append(log["semantic_score"])
        if log.get("duration_ms") is not None:
            s["durations"].append(log["duration_ms"])
    
    # Calculate averages
    for provider, s in stats.items():
        scores = s.pop("semantic_scores")
        durations = s.pop("durations")
        
        s["avg_semantic_score"] = sum(scores) / len(scores) if scores else None
        s["avg_duration_ms"] = sum(durations) / len(durations) if durations else None
        s["error_rate"] = s["error_count"] / s["total_calls"] if s["total_calls"] > 0 else 0
    
    return stats


def export_logs_for_analysis(output_path: Path, limit: int = 1000) -> int:
    """Export logs to a single JSON file for analysis.
    
    Returns number of logs exported.
    """
    logs = list_logs(limit=limit)
    output_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
    return len(logs)
