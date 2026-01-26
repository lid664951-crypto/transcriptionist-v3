# Transcriptionist v3 Localization

This directory contains translation files for Transcriptionist v3.

## Directory Structure

```
locales/
├── transcriptionist.pot    # Template file (source strings)
├── extract_strings.py      # Script to extract strings from source
├── compile_translations.py # Script to compile .po to .mo
├── README.md               # This file
├── zh_CN/                  # Chinese (Simplified)
│   └── LC_MESSAGES/
│       ├── transcriptionist.po   # Translation file
│       └── transcriptionist.mo   # Compiled translation
└── en_US/                  # English (US)
    └── LC_MESSAGES/
        ├── transcriptionist.po
        └── transcriptionist.mo
```

## Translation Workflow

### 1. Extract Strings

When adding new translatable strings to the code, run:

```bash
python extract_strings.py
```

This updates `transcriptionist.pot` with all translatable strings.

### 2. Update Translation Files

For each language, merge the new strings:

```bash
# Using msgmerge (from gettext-tools)
msgmerge -U zh_CN/LC_MESSAGES/transcriptionist.po transcriptionist.pot
```

Or manually copy new entries from the .pot file.

### 3. Translate

Edit the `.po` files to add translations:

```
msgid "Hello"
msgstr "你好"
```

### 4. Compile Translations

Compile `.po` files to `.mo` format:

```bash
python compile_translations.py
```

## Adding a New Language

1. Create the directory structure:
   ```bash
   mkdir -p <lang_code>/LC_MESSAGES
   ```

2. Copy the template:
   ```bash
   cp transcriptionist.pot <lang_code>/LC_MESSAGES/transcriptionist.po
   ```

3. Edit the header in the `.po` file:
   - Set `Language: <lang_code>`
   - Set `Language-Team: <language name>`
   - Set appropriate `Plural-Forms`

4. Translate all strings

5. Compile the translation

6. Add the language to `SUPPORTED_LANGUAGES` in `core/i18n.py`

## Supported Languages

| Code  | Language          | Status    |
|-------|-------------------|-----------|
| zh_CN | Chinese (Simplified) | Complete |
| en_US | English (US)      | Complete  |
| ja_JP | Japanese          | Planned   |
| ko_KR | Korean            | Planned   |
| fr_FR | French            | Planned   |
| de_DE | German            | Planned   |
| es_ES | Spanish           | Planned   |

## Using Translations in Code

```python
from transcriptionist_v3.core.i18n import _, ngettext

# Simple translation
label = _("Hello")

# Plural forms
message = ngettext(
    "%d file selected",
    "%d files selected",
    count
) % count
```

## Notes

- All source strings should be in English
- Use `_()` for all user-visible strings
- Use `ngettext()` for strings with plural forms
- Keep translations concise - UI space is limited
- Test translations in the actual UI
