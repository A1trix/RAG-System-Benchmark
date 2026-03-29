import logging
import os
from pathlib import Path
from threading import Thread

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from rag_service.workers.tasks import ingest_job, delete_job


log = logging.getLogger(__name__)


class IngestEventHandler(FileSystemEventHandler):
    def __init__(self, queue, settings):
        self.queue = queue
        self.settings = settings
        self.allowed_exts = {ext.strip().lower() for ext in settings.watch_extensions.split(",") if ext.strip()}

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self.allowed_exts and path.suffix.lower() not in self.allowed_exts:
            return
        file_id = path.name
        payload = {
            "file_id": file_id,
            "title": file_id,
            "path": str(path),
        }
        try:
            job = self.queue.enqueue(ingest_job, payload)
            log.info("Enqueued ingest for %s (job=%s)", path, job.id)
        except Exception as exc:  # pragma: no cover
            log.exception("Failed to enqueue ingest for %s: %s", path, exc)

    def on_deleted(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self.allowed_exts and path.suffix.lower() not in self.allowed_exts:
            return
        file_id = path.name
        payload = {"file_id": file_id}
        try:
            job = self.queue.enqueue(delete_job, payload)
            log.info("Enqueued delete for %s (job=%s)", path, job.id)
        except Exception as exc:  # pragma: no cover
            log.exception("Failed to enqueue delete for %s: %s", path, exc)

    def on_moved(self, event):
        # Treat move-out as delete of old path, move-in as create of new path
        if not event.is_directory:
            src = Path(event.src_path)
            dest = Path(event.dest_path)
            # delete old if allowed
            if (not self.allowed_exts) or src.suffix.lower() in self.allowed_exts:
                self.on_deleted(event)
            # create new if allowed
            if (not self.allowed_exts) or dest.suffix.lower() in self.allowed_exts:
                # Build a lightweight fake event-like object for on_created
                class _Evt:
                    def __init__(self, p):
                        self.src_path = str(p)
                        self.is_directory = False

                self.on_created(_Evt(dest))


class Watcher:
    def __init__(self, settings, queue):
        self.settings = settings
        self.queue = queue
        self.observer: Observer | None = None
        self.thread: Thread | None = None

    def start(self):
        if not self.settings.watch_enabled:
            log.info("File watcher disabled via WATCH_ENABLED")
            return
        watch_path = Path(self.settings.watch_path)
        watch_path.mkdir(parents=True, exist_ok=True)
        handler = IngestEventHandler(self.queue, self.settings)
        observer = PollingObserver() if self.settings.watch_polling else Observer()
        observer.schedule(handler, str(watch_path), recursive=False)
        observer.start()
        self.observer = observer
        mode = "polling" if self.settings.watch_polling else "inotify"
        log.info("Started file watcher (%s) on %s for extensions %s", mode, watch_path, self.settings.watch_extensions)

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)
            log.info("Stopped file watcher")
            self.observer = None
