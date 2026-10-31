"""Run one Celery Beat per database/queue, including overlapping container rollouts."""

import hashlib
import signal
import subprocess
from threading import Event
from typing import Any

from psycopg import Connection

from investiq.core.config import Settings
from investiq.db.session import postgres_url


class SchedulerLease:
    def __init__(self, settings: Settings) -> None:
        self.url = postgres_url(settings)
        self.key = int.from_bytes(
            hashlib.sha256(("investiq:beat:" + settings.valuation_queue).encode()).digest()[:8],
            signed=True,
        )
        self.connection: Connection[Any] | None = None

    def acquire(self) -> bool:
        self.close()
        conn = Connection.connect(self.url, autocommit=True, connect_timeout=5)
        try:
            conn.execute("SET statement_timeout = '5s'")
            row = conn.execute("SELECT pg_try_advisory_lock(%s)", (self.key,)).fetchone()
            if row and row[0]:
                self.connection = conn
                return True
        except BaseException:
            conn.close()
            raise
        conn.close()
        return False

    def heartbeat(self) -> None:
        if not self.connection:
            raise RuntimeError("Scheduler lease is not held")
        self.connection.execute("SELECT 1")

    def close(self) -> None:
        if self.connection:
            self.connection.close()  # PostgreSQL releases the session advisory lock.
            self.connection = None


def run() -> None:
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    lease = SchedulerLease(Settings())
    child: subprocess.Popen[bytes] | None = None
    try:
        while not stop.is_set():
            if lease.acquire():
                break
            stop.wait(2)
        if stop.is_set():
            return
        child = subprocess.Popen(
            [
                "celery",
                "-q",
                "-A",
                "investiq.jobs.valuation:app",
                "beat",
                "--loglevel=WARNING",
                "--schedule=/tmp/investiq-celerybeat",
            ]
        )
        while not stop.wait(2):
            if child.poll() is not None:
                raise RuntimeError("Scheduler process exited; restart required")
            lease.heartbeat()
    finally:
        # Stop publishing before releasing the lock to the next deployment.
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        lease.close()


def main() -> None:
    try:
        run()
    except Exception:
        raise SystemExit("scheduler_stopped: database lease or process unavailable") from None


if __name__ == "__main__":
    main()
