import json
import random
import socket
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from url_provider import URLProvider, ResponseValidator


def iso_utc_now() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def calculate_backoff(attempt: int, initial_ms: float, multiplier: float, max_ms: float) -> float:
    base_delay = initial_ms * (multiplier ** attempt)
    jitter = random.uniform(0.0, 0.1 * base_delay)
    return min(base_delay + jitter, max_ms)


# Response Handler
class ResponseHandler:
    def __init__(self, log_path: str, validator: ResponseValidator | None = None):
        self.log_path = log_path
        self.validator = validator

    def _write(self, obj: dict) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")

    def _record(self, url: str, callback_name: str) -> None:
        if self.validator is not None:
            self.validator.add_callback(url, callback_name)

    def _emit(self, callback_name: str, url: str, **fields) -> None:
        self._record(url, callback_name)
        event_name = callback_name[3:] if callback_name.startswith("on_") else callback_name
        self._write({"timestamp": iso_utc_now(), "event": event_name, "url": url, **fields})

    def on_success(self, url: str, status: int, body: bytes, latency_ms: float) -> None:
        self._emit("on_success", url, status=status, latency_ms=latency_ms)

    def on_client_error(self, url: str, status: int, body: bytes) -> None:
        self._emit("on_client_error", url, status=status)

    def on_server_error(self, url: str, status: int, attempt: int) -> None:
        self._emit("on_server_error", url, status=status, attempt=attempt)

    def on_timeout(self, url: str, attempt: int, timeout_sec: float) -> None:
        self._emit("on_timeout", url, attempt=attempt, timeout_sec=timeout_sec)

    def on_connection_error(self, url: str, attempt: int, error: str) -> None:
        self._emit("on_connection_error", url, attempt=attempt, error=error)

    def on_slow_response(self, url: str, latency_ms: float) -> None:
        self._emit("on_slow_response", url, latency_ms=latency_ms)

    def on_retry(self, url: str, attempt: int, wait_ms: float, reason: str) -> None:
        self._emit("on_retry", url, attempt=attempt, wait_ms=wait_ms, reason=reason)

    def on_body_match(self, url: str, keyword: str) -> None:
        self._emit("on_body_match", url, keyword=keyword)

    def on_max_retries(self, url: str, attempts: int, last_error: str) -> None:
        self._emit("on_max_retries", url, attempts=attempts, last_error=last_error)


# Summary Tracking

class SummaryTracker:
    def __init__(self):
        self.total_urls = 0
        self.successful = 0
        self.failed = 0
        self.total_requests = 0
        self.retries = 0
        self.latencies_ms = []
        self.slow_responses = 0
        self.by_status = {}
        self.by_error = {}

    def record_url(self, ok: bool) -> None:
        self.total_urls += 1
        if ok:
            self.successful += 1
        else:
            self.failed += 1

    def record_request(self) -> None:
        self.total_requests += 1

    def record_retry(self) -> None:
        self.retries += 1

    def record_latency(self, latency_ms: float, slow_threshold_ms: float) -> None:
        self.latencies_ms.append(latency_ms)
        if latency_ms > slow_threshold_ms:
            self.slow_responses += 1

    def record_status(self, status: int) -> None:
        k = str(status)
        self.by_status[k] = self.by_status.get(k, 0) + 1

    def record_error(self, kind: str) -> None:
        self.by_error[kind] = self.by_error.get(kind, 0) + 1

    def to_dict(self) -> dict:
        avg = (sum(self.latencies_ms) / len(self.latencies_ms)) if self.latencies_ms else 0.0
        return {
            "total_urls": self.total_urls,
            "successful": self.successful,
            "failed": self.failed,
            "total_requests": self.total_requests,
            "retries": self.retries,
            "avg_latency_ms": round(avg, 1),
            "slow_responses": self.slow_responses,
            "by_status": self.by_status,
            "by_error": self.by_error,
        }

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=4)
            f.write("\n")


class RobustHTTPClient:
    SLOW_THRESHOLD_MS = 500.0
    MAX_RETRIES = 3
    BASE_TIMEOUT_SEC = 5.0
    INITIAL_BACKOFF_MS = 100.0
    MAX_BACKOFF_MS = 5000.0
    BACKOFF_MULTIPLIER = 2.0

    MONITORED_KEYWORDS = ["Herman"]


    def __init__(self, handler: ResponseHandler, summary_path: str = "summary.json"):
        self.handler = handler
        self.summary_path = summary_path
        self.stats = SummaryTracker()

    def fetch(self, url: str) -> bool:
        total_attempts = 1 + self.MAX_RETRIES
        last_reason = "unknown"

        for attempt in range(1, total_attempts + 1):
            self.stats.record_request()
            start = time.perf_counter()

            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=self.BASE_TIMEOUT_SEC) as resp:
                    status = getattr(resp, "status", 200)
                    body = resp.read() or b""

                latency_ms = (time.perf_counter() - start) * 1000.0
                self.stats.record_latency(latency_ms, self.SLOW_THRESHOLD_MS)
                self.stats.record_status(int(status))

                if latency_ms > self.SLOW_THRESHOLD_MS:
                    self.handler.on_slow_response(url, latency_ms)

                if 200 <= status < 300:
                    self.handler.on_success(url, status, body, latency_ms)
                    self._check_keywords(url, body)
                    return True

                if 400 <= status < 500:
                    self.handler.on_client_error(url, status, body)
                    return False

                self.handler.on_server_error(url, status, attempt)
                last_reason = "server_error"

            except urllib.error.HTTPError as e:
                status = int(getattr(e, "code", 0) or 0)
                try:
                    body = e.read() or b""
                except Exception:
                    body = b""

                latency_ms = (time.perf_counter() - start) * 1000.0
                self.stats.record_latency(latency_ms, self.SLOW_THRESHOLD_MS)
                if status:
                    self.stats.record_status(status)

                if latency_ms > self.SLOW_THRESHOLD_MS:
                    self.handler.on_slow_response(url, latency_ms)

                if 400 <= status < 500:
                    self.handler.on_client_error(url, status, body)
                    return False

                if 500 <= status < 600:
                    self.handler.on_server_error(url, status, attempt)
                    last_reason = "server_error"
                else:
                    self.handler.on_max_retries(url, attempt, f"http_error:{status}")
                    return False

            except (socket.timeout, TimeoutError):
                last_reason = "timeout"
                self.stats.record_error("timeout")
                self.handler.on_timeout(url, attempt, self.BASE_TIMEOUT_SEC)

            except urllib.error.URLError as e:
                if isinstance(getattr(e, "reason", None), socket.timeout):
                    last_reason = "timeout"
                    self.stats.record_error("timeout")
                    self.handler.on_timeout(url, attempt, self.BASE_TIMEOUT_SEC)
                else:
                    last_reason = "connection"
                    self.stats.record_error("connection")
                    self.handler.on_connection_error(url, attempt, str(e))

            except Exception as e:
                last_reason = "connection"
                self.stats.record_error("connection")
                self.handler.on_connection_error(url, attempt, str(e))

            if attempt < total_attempts:
                wait_ms = calculate_backoff(
                    attempt - 1,
                    self.INITIAL_BACKOFF_MS,
                    self.BACKOFF_MULTIPLIER,
                    self.MAX_BACKOFF_MS,
                )
                self.stats.record_retry()
                self.handler.on_retry(url, attempt + 1, wait_ms, last_reason)
                time.sleep(wait_ms / 1000.0)
            else:
                self.handler.on_max_retries(url, attempt, last_reason)
                return False

        return False

    def fetch_all(self, provider: URLProvider) -> dict:
        while True:
            url = provider.next_url()
            if url is None:
                break
            ok = self.fetch(url)
            self.stats.record_url(ok)

        results = self.stats.to_dict()
        self.stats.write(self.summary_path)
        return results

    def _check_keywords(self, url: str, body: bytes) -> None:
        if not body:
            return
        text = body.decode("utf-8", errors="ignore")
        for kw in self.MONITORED_KEYWORDS:
            if kw in text:
                self.handler.on_body_match(url, kw)
