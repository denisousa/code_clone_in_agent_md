import time
import inspect
from datetime import datetime
from functools import wraps
from typing import Optional

def timed(label: Optional[str] = None, *, tz=None, fmt: str = "%Y-%m-%d %H:%M:%S"):
    def decorator(fn):
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def wrapper(*args, **kwargs):
                start_dt = datetime.now(tz)
                start = time.perf_counter()
                result = await fn(*args, **kwargs)
                end_dt = datetime.now(tz)
                elapsed = time.perf_counter() - start
                name = label or fn.__name__
                print(f"[{start_dt.strftime(fmt)} → {end_dt.strftime(fmt)}] {name} took {elapsed:.3f}s")
                return result
            return wrapper
        else:
            @wraps(fn)
            def wrapper(*args, **kwargs):
                start_dt = datetime.now(tz)
                start = time.perf_counter()
                result = fn(*args, **kwargs)
                end_dt = datetime.now(tz)
                elapsed = time.perf_counter() - start
                name = label or fn.__name__
                print(f"[{start_dt.strftime(fmt)} → {end_dt.strftime(fmt)}] {name} took {elapsed:.3f}s")
                return result
            return wrapper
    return decorator

def timeToString(seconds):
    result = ""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = (seconds % 3600) % 60
    if hours:
        result += str(hours) + " hours, "
    if minutes:
        result += str(minutes) + " minutes, "
    result += str(seconds) + " seconds"
    return result

