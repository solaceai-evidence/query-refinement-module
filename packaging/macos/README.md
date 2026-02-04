# QueryRefine macOS Distribution

This directory contains files for building standalone macOS executables of QueryRefine CLI.

## Building the Application

### Prerequisites
```bash
poetry install
poetry run pip install pyinstaller
```

### Build Commands

**For current architecture (arm64 or x86_64):**
```bash
cd packaging/macos
poetry run pyinstaller QueryRefine.spec --clean
```

**For specific architecture:**
```bash
# For Apple Silicon (arm64)
poetry run pyinstaller QueryRefine.spec --target-arch arm64 --clean

# For Intel (x86_64)
poetry run pyinstaller QueryRefine.spec --target-arch x86_64 --clean
```

Build output will be in `dist/QueryRefine.app/`

## Distribution Package

Create a distributable folder with:
```bash
mkdir QueryRefine-Distribution
cp -R dist/QueryRefine.app QueryRefine-Distribution/
cp sample.env QueryRefine-Distribution/
cp sample_framework.yaml QueryRefine-Distribution/
cp "Run Query Refine.command" QueryRefine-Distribution/
cp "Configure Environment.command" QueryRefine-Distribution/
chmod +x QueryRefine-Distribution/*.command

# Create zip for distribution
ditto -c -k --keepParent QueryRefine-Distribution QueryRefine-macOS.zip
```

## User Instructions

1. Unzip the distribution package
2. Run "Configure Environment.command" to set up API key
3. Run "Run Query Refine.command" to start the CLI

Or manually:
```bash
cd QueryRefine-Distribution
cp sample.env .env
# Edit .env with your API key
./QueryRefine.app/Contents/MacOS/QueryRefine --framework pico_advanced --query "your query"
```

## Files

- `QueryRefine.spec` - PyInstaller configuration
- `cli_entrypoint.py` - Main entry point for bundled app
- `sample.env` - Template environment configuration
- `sample_framework.yaml` - Example PICO framework
- `Run Query Refine.command` - User launcher script
- `Configure Environment.command` - Setup helper script

## Troubleshooting

**"Cannot be opened because it is from an unidentified developer"**
```bash
xattr -cr QueryRefine.app
```

**Missing dependencies:**
Ensure all hidden imports are listed in QueryRefine.spec

**API key issues:**
Check that .env file exists and QUERY_REFINEMENT_LLM_API_KEY is set
