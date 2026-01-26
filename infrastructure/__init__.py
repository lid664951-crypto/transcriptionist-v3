"""
Infrastructure Layer - External Services and Persistence

This layer implements data persistence (SQLite/SQLAlchemy),
manages file system operations, integrates external services
(GStreamer, Freesound API), and provides embedded Python runtime.

Modules:
- database: SQLite database with SQLAlchemy ORM
- file_system: File system operations and monitoring
- external_apis: External API clients (Freesound, translation)
- audio_engine: GStreamer audio engine integration
- ai_models: AI/ML model loading and inference
"""
