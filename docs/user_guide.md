# Transcriptionist v3 User Guide

## Introduction

Transcriptionist is a professional sound effects management application designed for audio professionals, game developers, and content creators. This guide covers all features and workflows.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Library Management](#library-management)
3. [Search and Filter](#search-and-filter)
4. [Audio Playback](#audio-playback)
5. [Projects](#projects)
6. [Batch Processing](#batch-processing)
7. [AI Tools](#ai-tools)
8. [Freesound Integration](#freesound-integration)
9. [Naming and Organization](#naming-and-organization)
10. [Settings](#settings)
11. [Keyboard Shortcuts](#keyboard-shortcuts)

---

## Getting Started

### First Launch

When you first launch Transcriptionist, you'll see the main window with:
- **Sidebar**: Navigation between Library, Projects, AI Tools, and Settings
- **Main Area**: Content view for the selected section
- **Player Bar**: Audio playback controls at the bottom

### Adding Your First Library

1. Click **Library** in the sidebar
2. Click **Add Folder** button
3. Select a folder containing your audio files
4. Transcriptionist will scan and index all supported audio files

### Supported Formats

- WAV (Waveform Audio)
- FLAC (Free Lossless Audio Codec)
- MP3 (MPEG Audio Layer III)
- OGG (Ogg Vorbis)
- AIFF (Audio Interchange File Format)
- M4A (MPEG-4 Audio)

---

## Library Management

### Adding Folders

You can add multiple folders to your library:
1. Click **Add Folder** in the Library view
2. Select the folder to add
3. Choose whether to scan recursively (include subfolders)

### Removing Folders

1. Right-click on a folder in the folder browser
2. Select **Remove from Library**
3. Files are removed from the index but not deleted from disk

### Rescanning

To update the library after adding new files:
1. Click **Refresh** button
2. Or right-click a folder and select **Rescan**

### File Details

Click on any file to see its details:
- Duration, sample rate, bit depth, channels
- File size and format
- Metadata (title, artist, tags)
- Waveform preview

---

## Search and Filter

### Basic Search

Type in the search bar to find files by:
- Filename
- Tags
- Description
- Metadata fields

### Advanced Search

Use operators for precise searches:

| Operator | Example | Description |
|----------|---------|-------------|
| AND | `dog AND bark` | Both terms must match |
| OR | `cat OR kitten` | Either term matches |
| NOT | `animal NOT bird` | Exclude term |
| "" | `"door slam"` | Exact phrase |
| field: | `format:wav` | Search specific field |

### Field Searches

| Field | Example | Description |
|-------|---------|-------------|
| `duration:` | `duration:>5` | Duration in seconds |
| `samplerate:` | `samplerate:48000` | Sample rate in Hz |
| `format:` | `format:flac` | File format |
| `channels:` | `channels:2` | Number of channels |
| `tag:` | `tag:explosion` | Specific tag |

### Saving Searches

1. Perform a search
2. Click **Save Search** button
3. Enter a name for the search
4. Access saved searches from the dropdown

---

## Audio Playback

### Basic Controls

- **Play/Pause**: Space bar or click play button
- **Stop**: Click stop button
- **Seek**: Click on waveform or progress bar
- **Volume**: Drag volume slider

### Playback Queue

1. Double-click a file to play immediately
2. Right-click and select **Add to Queue** to queue files
3. View queue in the player panel

### Loop and Shuffle

- **Loop**: Click loop button to repeat current file
- **Shuffle**: Click shuffle to randomize queue order

---

## Projects

### Creating a Project

1. Go to **Projects** in sidebar
2. Click **New Project**
3. Enter project name and description
4. Select a template (optional)

### Project Templates

Available templates:
- **SFX Library**: For sound effects collections
- **Music Production**: For music projects
- **Foley Session**: For foley recording sessions
- **Ambience Collection**: For ambient sounds
- **Delivery Package**: For client deliveries

### Adding Files to Projects

1. Open a project
2. Drag files from library to project
3. Or right-click files and select **Add to Project**

### Exporting Projects

1. Open the project
2. Click **Export**
3. Choose export options:
   - Output folder
   - File organization (flat or preserve structure)
   - Include metadata sidecars
   - Convert format (optional)
4. Click **Export**

---

## Batch Processing

### Format Conversion

1. Select files in library
2. Click **Batch Processing** > **Convert Format**
3. Choose target format and settings:
   - Format (WAV, FLAC, MP3, etc.)
   - Sample rate
   - Bit depth
   - Channels
4. Click **Convert**

### Loudness Normalization

1. Select files
2. Click **Batch Processing** > **Normalize**
3. Choose standard:
   - **EBU R128**: Broadcast standard (-23 LUFS)
   - **ATSC A/85**: US broadcast (-24 LKFS)
   - **Streaming**: Music streaming (-14 LUFS)
   - **Custom**: Set your own target
4. Click **Normalize**

### Metadata Editing

1. Select files
2. Click **Batch Processing** > **Edit Metadata**
3. Choose operation:
   - Set field value
   - Clear field
   - Find and replace
   - Add/remove tags
4. Preview changes
5. Click **Apply**

---

## AI Tools

### Translation

Translate filenames and metadata between languages:
1. Go to **AI Tools** > **Translation**
2. Select source and target languages
3. Select files to translate
4. Click **Translate**

### Tag Generation

Automatically generate tags from audio content:
1. Select files
2. Click **Generate Tags**
3. Review suggested tags
4. Accept or modify tags

### Audio Analysis

Analyze audio characteristics:
1. Select a file
2. Click **Analyze**
3. View analysis results:
   - Loudness measurements
   - Frequency spectrum
   - Dynamic range
   - Suggested categories

### Similar Sounds

Find similar sounds in your library:
1. Select a reference file
2. Click **Find Similar**
3. Browse results sorted by similarity

---

## Freesound Integration

### Setup

1. Go to **Settings** > **Freesound**
2. Click **Connect Account**
3. Log in to Freesound
4. Authorize Transcriptionist

### Searching

1. Go to **Freesound** in sidebar
2. Enter search terms
3. Filter by:
   - License type
   - Duration
   - Sample rate
   - Tags

### Downloading

1. Click on a sound to preview
2. Click **Download** to add to library
3. Attribution is automatically tracked

---

## Naming and Organization

### UCS Naming

Transcriptionist supports Universal Category System (UCS) naming:

Format: `CATId_Category-SubCategory_Description_CreatorID`

Example: `AMBExt_Forest-Birds_Morning Chorus_ABC`

### Batch Rename

1. Select files
2. Click **Rename** > **Batch Rename**
3. Choose template or create custom pattern
4. Preview changes
5. Click **Rename**

### Rename Templates

Available variables:
- `{filename}` - Original filename
- `{category}` - UCS category
- `{subcategory}` - UCS subcategory
- `{description}` - Description
- `{date}` - Date (YYYYMMDD)
- `{counter}` - Sequential number

---

## Settings

### General

- **Language**: Choose interface language
- **Startup**: Configure startup behavior
- **Updates**: Check for updates

### Appearance

- **Theme**: Light, Dark, or System
- **Waveform Colors**: Customize waveform display
- **Font Size**: Adjust text size

### Audio

- **Output Device**: Select audio output
- **Buffer Size**: Adjust for latency
- **Preview Duration**: Set preview length

### AI Services

- **Provider**: Select AI service provider
- **API Key**: Enter your API key
- **Model**: Choose AI model

### Library

- **Scan Options**: Configure scanning behavior
- **File Monitoring**: Enable/disable auto-refresh
- **Cache**: Manage cache settings

---

## Keyboard Shortcuts

### Playback

| Shortcut | Action |
|----------|--------|
| Space | Play/Pause |
| Ctrl+Right | Next track |
| Ctrl+Left | Previous track |
| Ctrl+Up | Volume up |
| Ctrl+Down | Volume down |
| M | Mute |

### Navigation

| Shortcut | Action |
|----------|--------|
| Ctrl+1 | Library view |
| Ctrl+2 | Projects view |
| Ctrl+3 | AI Tools view |
| Ctrl+, | Settings |
| Ctrl+F | Focus search |
| Escape | Clear search |

### File Operations

| Shortcut | Action |
|----------|--------|
| Ctrl+A | Select all |
| Ctrl+C | Copy |
| Ctrl+V | Paste |
| Delete | Remove from library |
| F2 | Rename |
| Ctrl+E | Export |

### General

| Shortcut | Action |
|----------|--------|
| Ctrl+Z | Undo |
| Ctrl+Y | Redo |
| Ctrl+S | Save |
| Ctrl+Q | Quit |
| F1 | Help |
| F11 | Fullscreen |

---

## Troubleshooting

### Common Issues

**Files not appearing after scan**
- Check that the file format is supported
- Verify file permissions
- Try rescanning the folder

**Audio not playing**
- Check audio output device in Settings
- Verify file is not corrupted
- Check system audio settings

**Slow performance with large libraries**
- Enable caching in Settings
- Reduce waveform quality
- Close unused projects

### Getting Help

- Check the [FAQ](faq.md)
- Visit [GitHub Issues](https://github.com/transcriptionist/transcriptionist/issues)
- Join our [Discord community](https://discord.gg/transcriptionist)

---

## Credits

Transcriptionist v3 is built with:
- GTK4 and Libadwaita
- GStreamer for audio playback
- SQLAlchemy for database
- Mutagen for metadata

Special thanks to the Quod Libet project for inspiration and patterns.
