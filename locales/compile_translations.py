#!/usr/bin/env python3
"""
Translation Compilation Script

Compiles .po files to .mo files for use by gettext.

Usage:
    python compile_translations.py
"""

import os
import subprocess
from pathlib import Path


def compile_po_file(po_path: Path) -> bool:
    """
    Compile a .po file to .mo format.
    
    Args:
        po_path: Path to the .po file
        
    Returns:
        bool: True if compilation succeeded
    """
    mo_path = po_path.with_suffix('.mo')
    
    try:
        # Try using msgfmt (from gettext-tools)
        result = subprocess.run(
            ['msgfmt', '-o', str(mo_path), str(po_path)],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"Compiled: {po_path.name} -> {mo_path.name}")
            return True
        else:
            print(f"Error compiling {po_path}: {result.stderr}")
            return False
            
    except FileNotFoundError:
        # msgfmt not available, use Python fallback
        return compile_po_python(po_path, mo_path)


def compile_po_python(po_path: Path, mo_path: Path) -> bool:
    """
    Compile .po to .mo using pure Python.
    
    This is a simplified implementation that handles basic cases.
    """
    try:
        import struct
        
        # Parse PO file
        messages = parse_po_file(po_path)
        
        if not messages:
            print(f"No messages found in {po_path}")
            return False
        
        # Write MO file
        write_mo_file(mo_path, messages)
        print(f"Compiled (Python): {po_path.name} -> {mo_path.name}")
        return True
        
    except Exception as e:
        print(f"Error compiling {po_path}: {e}")
        return False


def parse_po_file(po_path: Path) -> dict[str, str]:
    """Parse a PO file and return msgid -> msgstr mapping."""
    messages = {}
    
    with open(po_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Simple parser for msgid/msgstr pairs
    import re
    
    # Match msgid "..." msgstr "..."
    pattern = r'msgid\s+"(.*)"\s*\nmsgstr\s+"(.*)"'
    
    for match in re.finditer(pattern, content):
        msgid = unescape_string(match.group(1))
        msgstr = unescape_string(match.group(2))
        
        if msgid and msgstr:  # Skip empty translations
            messages[msgid] = msgstr
    
    return messages


def unescape_string(s: str) -> str:
    """Unescape PO file string."""
    return s.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')


def write_mo_file(mo_path: Path, messages: dict[str, str]) -> None:
    """Write messages to MO file format."""
    import struct
    import array
    
    # Sort messages by msgid
    keys = sorted(messages.keys())
    
    # MO file format constants
    MAGIC = 0x950412de
    VERSION = 0
    
    # Calculate offsets
    n_strings = len(keys)
    
    # Header size: 7 * 4 bytes
    header_size = 28
    
    # String table starts after header
    # Original strings table
    orig_table_offset = header_size
    # Translation strings table
    trans_table_offset = orig_table_offset + n_strings * 8
    
    # String data starts after both tables
    string_data_offset = trans_table_offset + n_strings * 8
    
    # Build string data and tables
    orig_table = []
    trans_table = []
    string_data = b''
    
    for key in keys:
        value = messages[key]
        
        # Original string
        orig_bytes = key.encode('utf-8')
        orig_table.append((len(orig_bytes), string_data_offset + len(string_data)))
        string_data += orig_bytes + b'\x00'
        
        # Translation string
        trans_bytes = value.encode('utf-8')
        trans_table.append((len(trans_bytes), string_data_offset + len(string_data)))
        string_data += trans_bytes + b'\x00'
    
    # Write MO file
    with open(mo_path, 'wb') as f:
        # Header
        f.write(struct.pack(
            '<Iiiiiii',
            MAGIC,
            VERSION,
            n_strings,
            orig_table_offset,
            trans_table_offset,
            0,  # hash table size
            0   # hash table offset
        ))
        
        # Original strings table
        for length, offset in orig_table:
            f.write(struct.pack('<ii', length, offset))
        
        # Translation strings table
        for length, offset in trans_table:
            f.write(struct.pack('<ii', length, offset))
        
        # String data
        f.write(string_data)


def main():
    """Compile all .po files in the locales directory."""
    script_dir = Path(__file__).parent
    
    print("Compiling translations...")
    print("-" * 40)
    
    compiled = 0
    failed = 0
    
    # Find all .po files
    for po_file in script_dir.rglob("*.po"):
        if compile_po_file(po_file):
            compiled += 1
        else:
            failed += 1
    
    print("-" * 40)
    print(f"Compiled: {compiled}, Failed: {failed}")
    
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
