#!/usr/bin/env python3
"""
String Extraction Script

Extracts translatable strings from Python source files.
Creates POT (Portable Object Template) file for translation.

Usage:
    python extract_strings.py
"""

import os
import re
import ast
from pathlib import Path
from datetime import datetime


# Patterns to match translatable strings
PATTERNS = [
    r'_\(["\'](.+?)["\']\)',           # _("string") or _('string')
    r'ngettext\(["\'](.+?)["\']',      # ngettext("singular", ...
    r'translate\(["\'](.+?)["\']\)',   # translate("string")
]


def extract_strings_from_file(file_path: Path) -> list[tuple[str, int]]:
    """Extract translatable strings from a Python file."""
    strings = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for pattern in PATTERNS:
            for match in re.finditer(pattern, content):
                # Find line number
                line_num = content[:match.start()].count('\n') + 1
                strings.append((match.group(1), line_num))
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
    
    return strings


def extract_all_strings(source_dir: Path) -> dict[str, list[tuple[Path, int]]]:
    """Extract all translatable strings from source directory."""
    all_strings: dict[str, list[tuple[Path, int]]] = {}
    
    for py_file in source_dir.rglob("*.py"):
        # Skip test files and this script
        if "test" in str(py_file).lower() or py_file.name == "extract_strings.py":
            continue
        
        strings = extract_strings_from_file(py_file)
        
        for string, line_num in strings:
            if string not in all_strings:
                all_strings[string] = []
            all_strings[string].append((py_file.relative_to(source_dir), line_num))
    
    return all_strings


def generate_pot_file(strings: dict[str, list[tuple[Path, int]]], output_path: Path) -> None:
    """Generate POT file from extracted strings."""
    
    header = f'''# Transcriptionist v3 Translation Template
# Copyright (C) {datetime.now().year}
# This file is distributed under the same license as the Transcriptionist package.
#
#, fuzzy
msgid ""
msgstr ""
"Project-Id-Version: Transcriptionist 3.0\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}+0000\\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"
"Language-Team: LANGUAGE <LL@li.org>\\n"
"Language: \\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"

'''
    
    entries = []
    for string, locations in sorted(strings.items()):
        # Add location comments
        location_comments = []
        for path, line in locations[:5]:  # Limit to 5 locations
            location_comments.append(f"#: {path}:{line}")
        
        entry = "\n".join(location_comments)
        entry += f'\nmsgid "{escape_string(string)}"'
        entry += '\nmsgstr ""'
        entries.append(entry)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write("\n\n".join(entries))
    
    print(f"Generated {output_path} with {len(strings)} strings")


def escape_string(s: str) -> str:
    """Escape special characters for PO file."""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def main():
    # Get source directory
    script_dir = Path(__file__).parent
    source_dir = script_dir.parent
    
    print(f"Extracting strings from: {source_dir}")
    
    # Extract strings
    strings = extract_all_strings(source_dir)
    
    print(f"Found {len(strings)} unique translatable strings")
    
    # Generate POT file
    pot_path = script_dir / "transcriptionist.pot"
    generate_pot_file(strings, pot_path)


if __name__ == "__main__":
    main()
