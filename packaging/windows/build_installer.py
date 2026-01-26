#!/usr/bin/env python3
"""
Windows Installer Builder

Creates a Windows installer with embedded Python runtime.

Usage:
    python build_installer.py [--version VERSION]
"""

import os
import sys
import shutil
import subprocess
import argparse
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional


# Configuration
APP_NAME = "Transcriptionist"
APP_VERSION = "3.0.0"
PYTHON_VERSION = "3.12.0"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"


class WindowsInstallerBuilder:
    """Builds Windows installer with embedded Python."""
    
    def __init__(
        self,
        source_dir: Path,
        output_dir: Path,
        version: str = APP_VERSION
    ):
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.version = version
        self.build_dir = output_dir / "build"
        self.dist_dir = output_dir / "dist"
    
    def build(self) -> Path:
        """Build the installer."""
        print(f"Building {APP_NAME} v{self.version} installer...")
        
        # Clean previous build
        self._clean()
        
        # Create build directory structure
        self._create_structure()
        
        # Download and extract embedded Python
        self._setup_python()
        
        # Copy application files
        self._copy_application()
        
        # Install dependencies
        self._install_dependencies()
        
        # Create launcher
        self._create_launcher()
        
        # Create NSIS installer script
        installer_path = self._create_installer()
        
        print(f"Installer created: {installer_path}")
        return installer_path
    
    def _clean(self) -> None:
        """Clean previous build artifacts."""
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)
    
    def _create_structure(self) -> None:
        """Create build directory structure."""
        (self.build_dir / "python").mkdir()
        (self.build_dir / "app").mkdir()
        (self.build_dir / "data").mkdir()
    
    def _setup_python(self) -> None:
        """Download and setup embedded Python."""
        print("Setting up embedded Python...")
        
        python_dir = self.build_dir / "python"
        zip_path = self.build_dir / "python-embed.zip"
        
        # Download embedded Python
        print(f"Downloading Python {PYTHON_VERSION}...")
        urllib.request.urlretrieve(PYTHON_EMBED_URL, zip_path)
        
        # Extract
        print("Extracting Python...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(python_dir)
        
        # Remove zip
        zip_path.unlink()
        
        # Modify python*._pth to enable site-packages
        for pth_file in python_dir.glob("python*._pth"):
            content = pth_file.read_text()
            # Uncomment import site
            content = content.replace("#import site", "import site")
            # Add app directory
            content += "\n../app\n"
            pth_file.write_text(content)
        
        # Download get-pip.py
        print("Installing pip...")
        pip_url = "https://bootstrap.pypa.io/get-pip.py"
        pip_script = python_dir / "get-pip.py"
        urllib.request.urlretrieve(pip_url, pip_script)
        
        # Install pip
        python_exe = python_dir / "python.exe"
        subprocess.run([str(python_exe), str(pip_script)], check=True)
        pip_script.unlink()
    
    def _copy_application(self) -> None:
        """Copy application files."""
        print("Copying application files...")
        
        app_dir = self.build_dir / "app" / "transcriptionist_v3"
        
        # Copy source files
        shutil.copytree(
            self.source_dir,
            app_dir,
            ignore=shutil.ignore_patterns(
                '__pycache__',
                '*.pyc',
                '.git',
                '.gitignore',
                'tests',
                '*.egg-info',
                'build',
                'dist',
                'packaging'
            )
        )
    
    def _install_dependencies(self) -> None:
        """Install Python dependencies."""
        print("Installing dependencies...")
        
        python_exe = self.build_dir / "python" / "python.exe"
        requirements = self.source_dir / "requirements.txt"
        
        if requirements.exists():
            subprocess.run([
                str(python_exe), "-m", "pip", "install",
                "-r", str(requirements),
                "--target", str(self.build_dir / "app")
            ], check=True)
        else:
            # Install from pyproject.toml
            subprocess.run([
                str(python_exe), "-m", "pip", "install",
                str(self.source_dir),
                "--target", str(self.build_dir / "app")
            ], check=True)
    
    def _create_launcher(self) -> None:
        """Create application launcher."""
        print("Creating launcher...")
        
        launcher_content = f'''@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%python"
set "APP_DIR=%SCRIPT_DIR%app"

set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\\Scripts;%PATH%"
set "PYTHONPATH=%APP_DIR%"

"%PYTHON_DIR%\\python.exe" -m transcriptionist_v3 %*
'''
        
        launcher_path = self.build_dir / f"{APP_NAME}.bat"
        launcher_path.write_text(launcher_content)
        
        # Create VBS wrapper to hide console window
        vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "{APP_NAME}.bat" & chr(34), 0
Set WshShell = Nothing
'''
        
        vbs_path = self.build_dir / f"{APP_NAME}.vbs"
        vbs_path.write_text(vbs_content)
    
    def _create_installer(self) -> Path:
        """Create NSIS installer script and build installer."""
        print("Creating installer...")
        
        nsis_script = self._generate_nsis_script()
        script_path = self.build_dir / "installer.nsi"
        script_path.write_text(nsis_script)
        
        # Try to build with NSIS
        installer_name = f"{APP_NAME}-{self.version}-Setup.exe"
        installer_path = self.dist_dir / installer_name
        
        try:
            # Try makensis
            subprocess.run([
                "makensis",
                f"/DVERSION={self.version}",
                f"/DOUTFILE={installer_path}",
                str(script_path)
            ], check=True)
        except FileNotFoundError:
            print("NSIS not found. Creating portable ZIP instead...")
            return self._create_portable_zip()
        
        return installer_path
    
    def _generate_nsis_script(self) -> str:
        """Generate NSIS installer script."""
        return f'''
; Transcriptionist Installer Script
; Generated by build_installer.py

!define PRODUCT_NAME "{APP_NAME}"
!define PRODUCT_VERSION "{self.version}"
!define PRODUCT_PUBLISHER "Transcriptionist Team"

Name "${{PRODUCT_NAME}} ${{PRODUCT_VERSION}}"
OutFile "${{OUTFILE}}"
InstallDir "$PROGRAMFILES64\\${{PRODUCT_NAME}}"
RequestExecutionLevel admin

; Pages
Page directory
Page instfiles

; Sections
Section "Install"
    SetOutPath "$INSTDIR"
    
    ; Copy all files
    File /r "{self.build_dir}\\*.*"
    
    ; Create shortcuts
    CreateDirectory "$SMPROGRAMS\\${{PRODUCT_NAME}}"
    CreateShortcut "$SMPROGRAMS\\${{PRODUCT_NAME}}\\${{PRODUCT_NAME}}.lnk" "$INSTDIR\\${{PRODUCT_NAME}}.vbs"
    CreateShortcut "$DESKTOP\\${{PRODUCT_NAME}}.lnk" "$INSTDIR\\${{PRODUCT_NAME}}.vbs"
    
    ; Create uninstaller
    WriteUninstaller "$INSTDIR\\Uninstall.exe"
    
    ; Registry entries
    WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${{PRODUCT_NAME}}" "DisplayName" "${{PRODUCT_NAME}}"
    WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${{PRODUCT_NAME}}" "UninstallString" "$INSTDIR\\Uninstall.exe"
    WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${{PRODUCT_NAME}}" "DisplayVersion" "${{PRODUCT_VERSION}}"
    WriteRegStr HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${{PRODUCT_NAME}}" "Publisher" "${{PRODUCT_PUBLISHER}}"
SectionEnd

Section "Uninstall"
    ; Remove files
    RMDir /r "$INSTDIR"
    
    ; Remove shortcuts
    Delete "$SMPROGRAMS\\${{PRODUCT_NAME}}\\${{PRODUCT_NAME}}.lnk"
    RMDir "$SMPROGRAMS\\${{PRODUCT_NAME}}"
    Delete "$DESKTOP\\${{PRODUCT_NAME}}.lnk"
    
    ; Remove registry entries
    DeleteRegKey HKLM "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${{PRODUCT_NAME}}"
SectionEnd
'''
    
    def _create_portable_zip(self) -> Path:
        """Create portable ZIP package."""
        zip_name = f"{APP_NAME}-{self.version}-Portable.zip"
        zip_path = self.dist_dir / zip_name
        
        shutil.make_archive(
            str(zip_path.with_suffix('')),
            'zip',
            self.build_dir
        )
        
        return zip_path


def main():
    parser = argparse.ArgumentParser(description="Build Windows installer")
    parser.add_argument("--version", default=APP_VERSION, help="Version number")
    parser.add_argument("--source", type=Path, help="Source directory")
    parser.add_argument("--output", type=Path, help="Output directory")
    args = parser.parse_args()
    
    # Determine paths
    script_dir = Path(__file__).parent
    source_dir = args.source or script_dir.parent.parent
    output_dir = args.output or script_dir / "output"
    
    # Build installer
    builder = WindowsInstallerBuilder(
        source_dir=source_dir,
        output_dir=output_dir,
        version=args.version
    )
    
    installer_path = builder.build()
    print(f"\nBuild complete: {installer_path}")


if __name__ == "__main__":
    main()
