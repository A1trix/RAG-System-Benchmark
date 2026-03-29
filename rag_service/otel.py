import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class _TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        span = trace.get_current_span()
        context = span.get_span_context() if span else None
        if context and context.trace_id:
            record.trace_id = format(context.trace_id, "032x")
            record.span_id = format(context.span_id, "016x")
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return True


def configure_logging() -> None:
    base_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = base_factory(*args, **kwargs)
        if not hasattr(record, "trace_id"):
            record.trace_id = "0" * 32
        if not hasattr(record, "span_id"):
            record.span_id = "0" * 16
        return record

    logging.setLogRecordFactory(record_factory)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "info").upper(),
        format="%(asctime)s %(levelname)s %(name)s trace_id=%(trace_id)s span_id=%(span_id)s %(message)s",
    )
    trace_filter = _TraceContextFilter()
    logging.getLogger().addFilter(trace_filter)
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(logger_name).addFilter(trace_filter)
    LoggingInstrumentor().instrument(set_logging_format=False)


def setup_tracing(app) -> None:
    exporter_setting = os.getenv("OTEL_TRACES_EXPORTER", "").lower()
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if exporter_setting in ("", "none") and not otlp_endpoint:
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "rag-pipeline")
    service_version = os.getenv("OTEL_SERVICE_VERSION", "0.1.0")
    service_namespace = os.getenv("OTEL_SERVICE_NAMESPACE", "rag")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "service.namespace": service_namespace,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint
        or "http://otel-collector:4318/v1/traces",
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()
