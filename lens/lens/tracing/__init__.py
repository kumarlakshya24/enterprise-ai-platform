"""OpenTelemetry-shaped span construction and OTLP JSON export."""

from lens.tracing.otlp import export_otlp
from lens.tracing.tracer import hex_id, new_span

__all__ = ["export_otlp", "hex_id", "new_span"]
