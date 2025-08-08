#!/usr/bin/env python3
"""
Statement Organizer Installer
-----------------------------
Cross-platform installer that detects OS, downloads Python 3.12 if needed,
and creates executable scripts for the main applications.
"""

import os
import sys
import platform
import subprocess
import urllib.request
import shutil
import stat
from pathlib import Path

class StatementOrganizerInstaller:
    """Cross-platform installer for Statement Organizer."""
    
    def __init__(self):
        self.system = platform.system().lower()
        self.machine = platform.machine().lower()
        self.python_version = "3.12.8"  # Latest Python 3.12 version
        self.project_dir = Path(__file__).parent.absolute()
        
    def detect_os(self):
        """Detect the operating system and architecture."""
        print(f"🔍 Detected OS: {platform.system()} {platform.release()}")
        print(f"🔍 Architecture: {platform.machine()}")
        print(f"🔍 Python version: {platform.python_version()}")
        
        if self.system == "windows":
            return "windows"
        elif self.system == "darwin":
            return "macos"
        elif self.system in ["linux", "freebsd", "openbsd", "netbsd"]:
            return "unix"
        else:
            print(f"⚠️ Unsupported operating system: {self.system}")
            return "unknown"
    
    def check_python_version(self):
        """Check if Python 3.12+ is available."""
        try:
            version = sys.version_info
            if version.major == 3 and version.minor >= 12:
                print(f"✅ Python {version.major}.{version.minor}.{version.micro} is available")
                return True
            else:
                print(f"⚠️ Python {version.major}.{version.minor}.{version.micro} found, but 3.12+ is recommended")
                return False
        except Exception as e:
            print(f"❌ Error checking Python version: {e}")
            return False
    
    def get_python_download_url(self, os_type):
        """Get the appropriate Python download URL for the OS."""
        base_url = f"https://www.python.org/ftp/python/{self.python_version}"
        
        if os_type == "windows":
            if "64" in platform.machine() or "x86_64" in platform.machine():
                return f"{base_url}/python-{self.python_version}-amd64.exe"
            else:
                return f"{base_url}/python-{self.python_version}.exe"
        elif os_type == "macos":
            if "arm" in self.machine or "aarch64" in self.machine:
                return f"{base_url}/python-{self.python_version}-macos11.pkg"
            else:
                return f"{base_url}/python-{self.python_version}-macosx10.9.pkg"
        else:
            # For Linux/BSD, we'll provide instructions instead of direct download
            return None
    
    def download_python(self, os_type):
        """Download Python installer for the current OS."""
        url = self.get_python_download_url(os_type)
        
        if not url:
            print("📋 For Linux/BSD systems, please install Python 3.12+ using your package manager:")
            print("   Ubuntu/Debian: sudo apt update && sudo apt install python3.12 python3.12-venv")
            print("   CentOS/RHEL: sudo yum install python312 python312-venv")
            print("   Fedora: sudo dnf install python3.12 python3.12-venv")
            print("   FreeBSD: sudo pkg install python312")
            print("   OpenBSD: sudo pkg_add python-3.12")
            return False
        
        filename = url.split("/")[-1]
        filepath = self.project_dir / filename
        
        print(f"📥 Downloading Python {self.python_version} from {url}")
        
        try:
            urllib.request.urlretrieve(url, filepath)
            print(f"✅ Downloaded to {filepath}")
            
            if os_type == "windows":
                print("🚀 Please run the downloaded installer with administrator privileges")
                print("   Make sure to check 'Add Python to PATH' during installation")
            elif os_type == "macos":
                print("🚀 Please run the downloaded .pkg installer")
                print("   You may need to allow installation from the Security & Privacy settings")
            
            return True
            
        except Exception as e:
            print(f"❌ Error downloading Python: {e}")
            return False
    
    def install_dependencies(self):
        """Install required Python packages."""
        print("📦 Installing required packages...")
        
        requirements = [
            "PyQt6",
            "PyMuPDF",
            "pdfplumber", 
            "pandas",
            "python-dateutil",
            "openpyxl",
            "openai"  # Optional for AI features
        ]
        
        try:
            # Try to use pip3 first, then pip
            pip_cmd = "pip3" if shutil.which("pip3") else "pip"
            
            for package in requirements:
                print(f"   Installing {package}...")
                result = subprocess.run([pip_cmd, "install", package], 
                                      capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"⚠️ Warning: Failed to install {package}")
                    print(f"   Error: {result.stderr}")
                else:
                    print(f"   ✅ {package} installed successfully")
            
            print("✅ Package installation complete")
            return True
            
        except Exception as e:
            print(f"❌ Error installing packages: {e}")
            return False
    
    def create_windows_scripts(self):
        """Create PowerShell scripts for Windows."""
        print("📝 Creating Windows PowerShell scripts...")
        
        scripts = {
            "pdf_field_mapper.ps1": "pdf_field_mapper_pyqt6.py",
            "bank_statement_gui.ps1": "bank_statement_gui.py", 
            "final_schedule_c_filler.ps1": "final_schedule_c_filler.py"
        }
        
        for script_name, python_file in scripts.items():
            script_path = self.project_dir / script_name
            
            script_content = f'''# Statement Organizer - {script_name}
# Auto-generated PowerShell script

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PythonScript = Join-Path $ScriptDir "{python_file}"

if (Test-Path $PythonScript) {{
    Write-Host "🚀 Starting {python_file}..."
    python "$PythonScript" @args
}} else {{
    Write-Host "❌ Error: {python_file} not found in $ScriptDir"
    Write-Host "Please ensure you're running this script from the Statement Organizer directory"
    pause
}}
'''
            
            try:
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(script_content)
                print(f"   ✅ Created {script_name}")
            except Exception as e:
                print(f"   ❌ Error creating {script_name}: {e}")
        
        # Create batch files as well for easier execution
        batch_scripts = {
            "pdf_field_mapper.bat": "pdf_field_mapper_pyqt6.py",
            "bank_statement_gui.bat": "bank_statement_gui.py",
            "final_schedule_c_filler.bat": "final_schedule_c_filler.py"
        }
        
        for batch_name, python_file in batch_scripts.items():
            batch_path = self.project_dir / batch_name
            
            batch_content = f'''@echo off
REM Statement Organizer - {batch_name}
REM Auto-generated batch script

echo 🚀 Starting {python_file}...
python "{python_file}" %*
if errorlevel 1 (
    echo ❌ Error running {python_file}
    pause
)
'''
            
            try:
                with open(batch_path, 'w', encoding='utf-8') as f:
                    f.write(batch_content)
                print(f"   ✅ Created {batch_name}")
            except Exception as e:
                print(f"   ❌ Error creating {batch_name}: {e}")
    
    def create_unix_scripts(self):
        """Create bash scripts for Unix-like systems (Linux, macOS, BSD)."""
        print("📝 Creating Unix bash scripts...")
        
        scripts = {
            "pdf_field_mapper.sh": "pdf_field_mapper_pyqt6.py",
            "bank_statement_gui.sh": "bank_statement_gui.py",
            "final_schedule_c_filler.sh": "final_schedule_c_filler.py"
        }
        
        for script_name, python_file in scripts.items():
            script_path = self.project_dir / script_name
            
            script_content = f'''#!/bin/bash
# Statement Organizer - {script_name}
# Auto-generated bash script

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/{python_file}"

if [ -f "$PYTHON_SCRIPT" ]; then
    echo "🚀 Starting {python_file}..."
    
    # Try python3 first, then python
    if command -v python3 &> /dev/null; then
        python3 "$PYTHON_SCRIPT" "$@"
    elif command -v python &> /dev/null; then
        python "$PYTHON_SCRIPT" "$@"
    else
        echo "❌ Error: Python not found in PATH"
        echo "Please install Python 3.12+ and try again"
        exit 1
    fi
else
    echo "❌ Error: {python_file} not found in $SCRIPT_DIR"
    echo "Please ensure you're running this script from the Statement Organizer directory"
    exit 1
fi
'''
            
            try:
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(script_content)
                
                # Make script executable
                script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
                print(f"   ✅ Created {script_name} (executable)")
                
            except Exception as e:
                print(f"   ❌ Error creating {script_name}: {e}")
    
    def create_config_directory(self):
        """Create config directory and sample files if they don't exist."""
        config_dir = self.project_dir / "config"
        config_dir.mkdir(exist_ok=True)
        print(f"📁 Config directory: {config_dir}")
        
        # Check for required config files
        required_files = [
            "business_categories.json",
            "schedule_c_field_mappings.json"
        ]
        
        missing_files = []
        for file_name in required_files:
            file_path = config_dir / file_name
            if not file_path.exists():
                missing_files.append(file_name)
        
        if missing_files:
            print(f"⚠️ Missing config files: {', '.join(missing_files)}")
            print("   These will be created automatically when you run the applications")
    
    def install(self):
        """Main installation process."""
        print("🚀 Statement Organizer Installer")
        print("=" * 50)
        
        # Detect OS
        os_type = self.detect_os()
        if os_type == "unknown":
            return False
        
        # Check Python version
        python_ok = self.check_python_version()
        
        # Download Python if needed
        if not python_ok:
            response = input("📥 Would you like to download Python 3.12? (y/n): ")
            if response.lower() in ['y', 'yes']:
                if not self.download_python(os_type):
                    print("❌ Python download failed. Please install Python 3.12+ manually")
                    return False
            else:
                print("⚠️ Continuing with current Python version")
        
        # Install dependencies
        if not self.install_dependencies():
            print("⚠️ Some packages failed to install. The applications may not work correctly")
        
        # Create config directory
        self.create_config_directory()
        
        # Create appropriate scripts
        if os_type == "windows":
            self.create_windows_scripts()
        else:
            self.create_unix_scripts()
        
        print("\n✅ Installation complete!")
        print("\n📋 Next steps:")
        print("1. Place your bank statement PDFs in the project directory")
        print("2. Run the applications using the created scripts:")
        
        if os_type == "windows":
            print("   - bank_statement_gui.bat (main application)")
            print("   - pdf_field_mapper.bat (field mapping tool)")
            print("   - final_schedule_c_filler.bat (PDF form filler)")
        else:
            print("   - ./bank_statement_gui.sh (main application)")
            print("   - ./pdf_field_mapper.sh (field mapping tool)")
            print("   - ./final_schedule_c_filler.sh (PDF form filler)")
        
        print("\n📖 For detailed usage instructions, see README.md")
        
        return True


def main():
    """Main function."""
    installer = StatementOrganizerInstaller()
    success = installer.install()
    
    if not success:
        print("\n❌ Installation failed")
        sys.exit(1)
    
    print("\n🎉 Ready to organize your business expenses!")


if __name__ == "__main__":
    main()
