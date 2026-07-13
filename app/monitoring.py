import time
import logging
import json
from contextvars import ContextVar
from fastapi import Request
from prometheus_client import Counter, Histogram, Gauge, generate_latest as generate_latest, CONTENT_TYPE_LATEST as CONTENT_TYPE_LATEST, REGISTRY as REGISTRY
from sqlalchemy import event
from app.database import engine

logger = logging.getLogger(__name__)

# ── Prometheus Metrics ────────────────────────────────────────────────────────

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests by method, path, and status",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request latency by method and path",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress", "Current in-flight requests by method and path",
    ["method", "path"],
)

sql_queries_per_request = Histogram(
    "sql_queries_per_request", "SQL queries per request by method and path",
    ["method", "path"],
    buckets=(0.5, 1, 2, 5, 10, 25, 50, 100, 200, 500),
)

sql_queries_total = Counter(
    "sql_queries_total", "Total SQL queries by endpoint",
    ["method", "path"],
)

sql_count_var: ContextVar[int] = ContextVar("sql_count", default=0)

# ── SQL Query Counting ──────────────────────────────────────────────────────

@event.listens_for(engine, "before_cursor_execute")
def _count_sql(conn, cursor, statement, parameters, context, executemany):
    sql_count_var.set(sql_count_var.get() + 1)

# ── Structured JSON Logging ────────────────────────────────────────────────

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for attr in ("method", "path", "status", "duration_ms", "sql_count"):
            val = getattr(record, attr, None)
            if val is not None:
                entry[attr] = val
        exc = record.exc_info
        if exc and exc[0]:
            entry["exception"] = self.formatException(exc)
        return json.dumps(entry, ensure_ascii=False)


def setup_structured_logging(level=logging.INFO):
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)

# ── FastAPI Middleware ──────────────────────────────────────────────────────

async def monitoring_middleware(request: Request, call_next):
    if request.url.path.startswith("/static") or request.url.path == "/metrics":
        return await call_next(request)

    method = request.method
    path = request.url.path

    sql_count_var.set(0)
    http_requests_in_progress.labels(method=method, path=path).inc()
    start = time.time()

    try:
        response = await call_next(request)
    except Exception:
        dur = time.time() - start
        sc = "error"
        http_requests_total.labels(method=method, path=path, status=sc).inc()
        http_request_duration_seconds.labels(method=method, path=path).observe(dur)
        http_requests_in_progress.labels(method=method, path=path).dec()
        sql_count = sql_count_var.get()
        sql_queries_per_request.labels(method=method, path=path).observe(sql_count)
        sql_queries_total.labels(method=method, path=path).inc(sql_count)
        logger.error(
            "Request failed",
            extra={"method": method, "path": path, "status": sc,
                   "duration_ms": round(dur * 1000, 1), "sql_count": sql_count},
        )
        raise

    dur = time.time() - start
    sc = str(response.status_code)
    http_requests_total.labels(method=method, path=path, status=sc).inc()
    http_request_duration_seconds.labels(method=method, path=path).observe(dur)
    http_requests_in_progress.labels(method=method, path=path).dec()
    sql_count = sql_count_var.get()
    sql_queries_per_request.labels(method=method, path=path).observe(sql_count)
    sql_queries_total.labels(method=method, path=path).inc(sql_count)

    logger.info(
        "Request completed",
        extra={"method": method, "path": path, "status": response.status_code,
               "duration_ms": round(dur * 1000, 1), "sql_count": sql_count},
    )

    return response
