# Transcriptionist v3 Developer Guide

## Architecture Overview

Transcriptionist v3 follows a clean architecture pattern with clear separation of concerns:

```
transcriptionist_v3/
├── core/                    # Core utilities (config, i18n)
├── domain/                  # Domain models and business logic
│   ├── models/              # Data models (AudioFile, Project, etc.)
│   └── exceptions/          # Custom exceptions
├── application/             # Application services
│   ├── library_manager/     # Library scanning and management
│   ├── playback_manager/    # Audio playback
│   ├── search_engine/       # Search functionality
│   ├── ai_engine/           # AI services
│   ├── naming_manager/      # File naming and UCS
│   ├── project_manager/     # Project management
│   ├── batch_processor/     # Batch operations
│   └── online_resources/    # Freesound integration
├── infrastructure/          # External interfaces
│   ├── database/            # SQLAlchemy models and connection
│   ├── cache/               # Caching infrastructure
│   ├── performance/         # Performance monitoring
│   └── file_system/         # File operations
├── ui/                      # GTK4 user interface
│   ├── app.py               # Main application
│   ├── views/               # View components
│   ├── widgets/             # Reusable widgets
│   └── dialogs/             # Dialog windows
├── lib/                     # Third-party adapters
│   └── quodlibet_adapter/   # Quod Libet integration
├── runtime/                 # Runtime configuration
├── locales/                 # Translation files
├── packaging/               # Distribution packaging
└── docs/                    # Documentation
```

## Getting Started

### Prerequisites

- Python 3.12+
- GTK4 and Libadwaita
- GStreamer with plugins
- MSYS2 (Windows) or system packages (Linux)

### Development Setup

```bash
# Clone repository
git clone https://github.com/transcriptionist/transcriptionist.git
cd transcriptionist/transcriptionist_v3

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Install dependencies
pip install -e ".[dev]"

# Run application
python -m transcriptionist_v3
```

### Windows Setup (MSYS2)

```bash
# Install MSYS2 from https://www.msys2.org/

# In MSYS2 terminal:
pacman -S mingw-w64-x86_64-gtk4
pacman -S mingw-w64-x86_64-libadwaita
pacman -S mingw-w64-x86_64-gstreamer
pacman -S mingw-w64-x86_64-python-gobject
```

## Core Concepts

### Domain Models

All domain models are defined in `domain/models/`:

```python
from transcriptionist_v3.domain.models import AudioFile, Project, AudioMetadata

# AudioFile represents a sound file in the library
audio_file = AudioFile(
    id=1,
    file_path="/path/to/sound.wav",
    filename="sound.wav",
    duration=5.5,
    sample_rate=48000,
    # ...
)

# Project organizes files
project = Project(
    name="My Project",
    description="Sound effects for game",
    template_name="sfx"
)
```

### Application Services

Services in `application/` handle business logic:

```python
from transcriptionist_v3.application.library_manager import LibraryManager
from transcriptionist_v3.application.search_engine import SearchEngine

# Library management
library = LibraryManager()
await library.scan_directory("/path/to/sounds")

# Search
search = SearchEngine()
results = search.search("explosion AND duration:>2")
```

### Database Layer

SQLAlchemy models in `infrastructure/database/`:

```python
from transcriptionist_v3.infrastructure.database import session_scope
from transcriptionist_v3.infrastructure.database.models import AudioFile

with session_scope() as session:
    files = session.query(AudioFile).filter(
        AudioFile.format == 'wav'
    ).all()
```

## UI Development

### GTK4 + Libadwaita

The UI uses GTK4 with Libadwaita for modern GNOME styling:

```python
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

class MyWidget(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        
        # Add Libadwaita components
        header = Adw.HeaderBar()
        self.append(header)
```

### Creating Views

Views are in `ui/views/`:

```python
from gi.repository import Gtk, Adw

class MyView(Gtk.Box):
    """A custom view component."""
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._setup_ui()
    
    def _setup_ui(self):
        # Create header
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title="My View",
            subtitle="Description"
        ))
        self.append(header)
        
        # Create content
        content = Gtk.Box()
        self.append(content)
```

### Creating Dialogs

Dialogs are in `ui/dialogs/`:

```python
from gi.repository import Gtk, Adw

class MyDialog(Adw.Window):
    """A custom dialog."""
    
    def __init__(self, parent):
        super().__init__(
            transient_for=parent,
            modal=True,
            title="My Dialog"
        )
        self._setup_ui()
    
    def _setup_ui(self):
        # Dialog content
        pass
```

## Adding Features

### 1. Define Domain Model

```python
# domain/models/my_model.py
from dataclasses import dataclass

@dataclass
class MyModel:
    id: int
    name: str
    # ...
```

### 2. Create Database Model

```python
# infrastructure/database/models.py
class MyDBModel(Base):
    __tablename__ = 'my_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False)
```

### 3. Implement Service

```python
# application/my_service/__init__.py
class MyService:
    def __init__(self):
        pass
    
    def do_something(self):
        pass
```

### 4. Create UI

```python
# ui/views/my_view.py
class MyView(Gtk.Box):
    def __init__(self, service: MyService):
        super().__init__()
        self._service = service
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=transcriptionist_v3

# Run specific test file
pytest tests/unit/test_search.py
```

### Writing Tests

```python
# tests/unit/test_my_feature.py
import pytest
from transcriptionist_v3.application.my_service import MyService

class TestMyService:
    def test_do_something(self):
        service = MyService()
        result = service.do_something()
        assert result is not None
```

## Internationalization

### Adding Translatable Strings

```python
from transcriptionist_v3.core.i18n import _, ngettext

# Simple translation
label = _("Hello")

# Plural forms
message = ngettext(
    "%d file",
    "%d files",
    count
) % count
```

### Updating Translations

```bash
# Extract strings
python locales/extract_strings.py

# Update .po files
# Edit locales/<lang>/LC_MESSAGES/transcriptionist.po

# Compile translations
python locales/compile_translations.py
```

## Performance

### Caching

```python
from transcriptionist_v3.infrastructure.cache import (
    get_query_cache,
    get_metadata_cache
)

# Query caching
cache = get_query_cache()
result = cache.get_or_compute(
    query="SELECT * FROM files",
    params=(),
    compute_fn=lambda: db.execute(query)
)

# Metadata caching
meta_cache = get_metadata_cache()
metadata = meta_cache.get_or_extract(
    file_path,
    extract_fn=lambda: extractor.extract(file_path)
)
```

### Profiling

```python
from transcriptionist_v3.infrastructure.performance import (
    track_memory,
    profile_memory
)

# Track memory usage
with track_memory("loading files"):
    load_files()

# Decorator
@profile_memory
def my_function():
    pass
```

## Building Packages

### Windows

```bash
cd packaging/windows
python build_installer.py --version 3.0.0
```

### Linux AppImage

```bash
cd packaging/linux
./build_appimage.sh 3.0.0
```

### Flatpak

```bash
cd packaging/linux
flatpak-builder --user --install build-dir com.transcriptionist.app.yml
```

## Code Style

### Python Style

- Follow PEP 8
- Use type hints
- Maximum line length: 100 characters
- Use docstrings for public APIs

```python
def my_function(param: str) -> int:
    """
    Brief description.
    
    Args:
        param: Description of parameter
        
    Returns:
        Description of return value
    """
    pass
```

### GTK Style

- Use Libadwaita components when available
- Follow GNOME HIG (Human Interface Guidelines)
- Use CSS for styling, not inline properties

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

### Commit Messages

```
type(scope): description

- feat: New feature
- fix: Bug fix
- docs: Documentation
- style: Formatting
- refactor: Code restructuring
- test: Adding tests
- chore: Maintenance
```

## Resources

- [GTK4 Documentation](https://docs.gtk.org/gtk4/)
- [Libadwaita Documentation](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/)
- [PyGObject Documentation](https://pygobject.readthedocs.io/)
- [GStreamer Documentation](https://gstreamer.freedesktop.org/documentation/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Quod Libet Source](https://github.com/quodlibet/quodlibet) (reference)
