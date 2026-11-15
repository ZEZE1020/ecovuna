"""Compatibility entry point for creating the synthetic registry."""
from .ingest import ingest

if __name__ == "__main__":
    ingest(offline_fallback=True)
