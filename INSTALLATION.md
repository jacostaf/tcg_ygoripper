# Installation Troubleshooting Guide

## Common Issues and Solutions

### 1. Python 3.13 Compatibility
If you're using Python 3.13 (especially on macOS), some packages may not have pre-compiled wheels yet.

**Solution:**
```bash
# Option 1: Use flexible requirements (recommended)
pip install -r requirements.txt --upgrade

# Option 2: Use locked requirements for older Python versions
pip install -r requirements-lock.txt

# Option 3: Install from source if needed
pip install -r requirements.txt --no-binary=:all:
```

### 2. Apple Silicon (M1/M2) macOS Issues
Some packages may need special handling on Apple Silicon.

**Solution:**
```bash
# Install with native architecture
pip install -r requirements.txt --upgrade --force-reinstall

# If that fails, try installing problematic packages individually
pip install playwright --upgrade
pip install psutil --upgrade
pip install pymongo --upgrade
```

### 3. Network Timeouts
If you experience network timeouts during installation:

**Solution:**
```bash
# Increase timeout
pip install -r requirements.txt --timeout 300

# Use different index
pip install -r requirements.txt -i https://pypi.org/simple/

# Install packages individually
pip install flask requests python-dotenv pymongo[srv] playwright pydantic psutil certifi urllib3 pyOpenSSL
```

### 4. Permission Issues
If you get permission errors:

**Solution:**
```bash
# Always use virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Or install to user directory
pip install -r requirements.txt --user
```

### 5. Playwright Browser Installation
After installing requirements, you need to install browsers:

**Solution:**
```bash
playwright install
# Or install specific browser
playwright install chromium
```

### 6. Version Conflicts
If you get version conflicts:

**Solution:**
```bash
# Clean install
pip uninstall -y -r requirements.txt
pip install -r requirements.txt

# Or use pip-tools
pip install pip-tools
pip-compile requirements.txt
pip-sync requirements.txt
```

## Testing Installation

Run this to verify your installation:
```bash
python -c "
import flask, requests, pymongo, playwright, pydantic, psutil
print('✓ All core dependencies imported successfully')
print('✓ Installation complete')
"
```

## Environment Setup

1. Create `.env` file with your configuration:
```
MONGO_URI=your_mongodb_connection_string
MEM_LIMIT=512
PORT=8081
```

2. Run the application:
```bash
python main_modular.py
```