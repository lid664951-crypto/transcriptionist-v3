#!/bin/bash
# Build AppImage for Transcriptionist v3
#
# Usage:
#   ./build_appimage.sh [VERSION]
#
# Requirements:
#   - appimagetool
#   - Python 3.12+
#   - GTK4 and Libadwaita

set -e

APP_NAME="Transcriptionist"
VERSION="${1:-3.0.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
BUILD_DIR="$SCRIPT_DIR/build"
APPDIR="$BUILD_DIR/$APP_NAME.AppDir"

echo "Building $APP_NAME v$VERSION AppImage..."

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Create AppDir structure
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib/python3/dist-packages"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APPDIR/usr/share/metainfo"

# Copy application files
echo "Copying application files..."
cp -r "$SOURCE_DIR/transcriptionist_v3" "$APPDIR/usr/lib/python3/dist-packages/"

# Create desktop entry
cat > "$APPDIR/usr/share/applications/$APP_NAME.desktop" << EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Professional Sound Effects Management
Exec=transcriptionist
Icon=transcriptionist
Categories=AudioVideo;Audio;
Terminal=false
StartupNotify=true
EOF

# Copy desktop entry to AppDir root
cp "$APPDIR/usr/share/applications/$APP_NAME.desktop" "$APPDIR/"

# Create icon (placeholder - replace with actual icon)
cat > "$APPDIR/usr/share/icons/hicolor/256x256/apps/transcriptionist.svg" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<svg width="256" height="256" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg">
  <rect width="256" height="256" rx="32" fill="#3584e4"/>
  <text x="128" y="160" font-size="120" text-anchor="middle" fill="white" font-family="sans-serif">T</text>
</svg>
EOF

# Create symlink for icon
ln -sf usr/share/icons/hicolor/256x256/apps/transcriptionist.svg "$APPDIR/transcriptionist.svg"

# Create AppRun script
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}

export PATH="${HERE}/usr/bin:${PATH}"
export PYTHONPATH="${HERE}/usr/lib/python3/dist-packages:${PYTHONPATH}"
export GI_TYPELIB_PATH="${HERE}/usr/lib/girepository-1.0:${GI_TYPELIB_PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${LD_LIBRARY_PATH}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS}"
export GSETTINGS_SCHEMA_DIR="${HERE}/usr/share/glib-2.0/schemas:${GSETTINGS_SCHEMA_DIR}"

exec python3 -m transcriptionist_v3 "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Create launcher script
cat > "$APPDIR/usr/bin/transcriptionist" << 'EOF'
#!/bin/bash
exec python3 -m transcriptionist_v3 "$@"
EOF
chmod +x "$APPDIR/usr/bin/transcriptionist"

# Create AppStream metadata
cat > "$APPDIR/usr/share/metainfo/$APP_NAME.appdata.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>com.transcriptionist.app</id>
  <name>$APP_NAME</name>
  <summary>Professional Sound Effects Management</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <description>
    <p>
      Transcriptionist is a professional sound effects management application
      designed for audio professionals, game developers, and content creators.
    </p>
    <p>Features include:</p>
    <ul>
      <li>Comprehensive audio library management</li>
      <li>Advanced search with boolean operators</li>
      <li>AI-powered translation and tagging</li>
      <li>Batch processing and format conversion</li>
      <li>Project organization and export</li>
      <li>Freesound integration</li>
    </ul>
  </description>
  <launchable type="desktop-id">$APP_NAME.desktop</launchable>
  <url type="homepage">https://github.com/transcriptionist/transcriptionist</url>
  <provides>
    <binary>transcriptionist</binary>
  </provides>
  <releases>
    <release version="$VERSION" date="$(date +%Y-%m-%d)"/>
  </releases>
</component>
EOF

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install --target="$APPDIR/usr/lib/python3/dist-packages" \
    PyGObject \
    mutagen \
    aiohttp \
    sqlalchemy \
    || echo "Warning: Some dependencies may need to be installed system-wide"

# Download appimagetool if not available
APPIMAGETOOL="$BUILD_DIR/appimagetool"
if ! command -v appimagetool &> /dev/null && [ ! -f "$APPIMAGETOOL" ]; then
    echo "Downloading appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
        -O "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
fi

# Build AppImage
echo "Building AppImage..."
ARCH=x86_64 "${APPIMAGETOOL:-appimagetool}" "$APPDIR" "$BUILD_DIR/${APP_NAME}-${VERSION}-x86_64.AppImage"

echo ""
echo "Build complete: $BUILD_DIR/${APP_NAME}-${VERSION}-x86_64.AppImage"
