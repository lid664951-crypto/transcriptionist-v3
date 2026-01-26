"""
Application Layer - Business Logic and Services

This layer implements business logic and use cases, coordinates between
UI and Domain/Infrastructure layers, manages application state and workflows,
and handles asynchronous operations using asyncio.

Modules:
- library_manager: Library scanning, metadata extraction, duplicate detection
- playback_manager: Audio playback control and queue management
- search_engine: Query parsing, execution, and relevance scoring
- ai_manager: AI services for translation, classification, tagging
- naming_manager: UCS naming conventions and batch renaming
- project_manager: Project CRUD and file associations
- batch_processor: Bulk operations on multiple files
- freesound_integration: Freesound.org API integration
"""
