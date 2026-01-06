#!/bin/bash
# Build macOS releases for Query Refinement Module
# This script creates distributable packages for macOS (ARM64 and x86_64)

set -e  # Exit on error

echo "=========================================="
echo "Query Refinement Module - macOS Release Builder"
echo "=========================================="
echo ""

# Get current architecture
ARCH=$(uname -m)
echo "Current architecture: $ARCH"
echo ""

# Create timestamp for release
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RELEASE_DIR="release/macos/${TIMESTAMP}"

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist
rm -rf packaging/macos/build packaging/macos/dist
echo "✓ Cleaned"
echo ""

# Build for current architecture (ARM64)
if [ "$ARCH" = "arm64" ]; then
    echo "Building for ARM64 (Apple Silicon)..."
    echo "----------------------------------------"
    
    # Build using the main spec file
    poetry run pyinstaller packaging/macos/QueryRefine.spec --distpath dist/QueryRefine-arm64 --workpath build/QueryRefine-arm64 --clean --noconfirm
    
    echo "✓ ARM64 build complete"
    echo ""
    
    # Create release directory
    mkdir -p "${RELEASE_DIR}/arm64"
    
    # Copy launcher scripts
    cp packaging/macos/*.command "${RELEASE_DIR}/arm64/" 2>/dev/null || true
    cp packaging/macos/sample.env "${RELEASE_DIR}/arm64/sample.env"
    cp packaging/macos/sample_framework.yaml "${RELEASE_DIR}/arm64/"
    
    # Copy the built application
    cp -r dist/QueryRefine-arm64/QueryRefine.app "${RELEASE_DIR}/arm64/"
    
    # Create README
    cat > "${RELEASE_DIR}/arm64/README.txt" << 'EOF'
Query Refinement Module - macOS ARM64 (Apple Silicon)
=====================================================

Installation:
1. Copy the QueryRefine folder to your desired location
2. Copy .env.sample to .env and configure your API keys
3. Optionally, copy sample_framework.yaml to customize frameworks
4. Run "Configure Environment.command" to set up your environment
5. Run "Run Query Refine.command" to launch the application

Requirements:
- macOS 11.0 or later
- Apple Silicon (M1, M2, M3, etc.)

Configuration:
- Edit the .env file to add your LiteLLM API keys and settings
- Use --list-frameworks to see available refinement frameworks
- Use --help for command-line options

For more information, visit the project repository.
EOF
    
    # Create compressed archive
    cd "${RELEASE_DIR}"
    tar -czf "QueryRefine-macOS-arm64.tar.gz" arm64/
    cd - > /dev/null
    
    echo "✓ ARM64 release package created: ${RELEASE_DIR}/QueryRefine-macOS-arm64.tar.gz"
    echo ""
else
    echo "Note: Current architecture is $ARCH (not ARM64)"
    echo "Building for x86_64..."
    echo "----------------------------------------"
    
    # Build for x86_64 (Intel)
    poetry run pyinstaller QueryRefine.spec --distpath dist/QueryRefine-x86_64 --workpath build/QueryRefine-x86_64 --clean --noconfirm
    
    echo "✓ x86_64 build complete"
    echo ""
    
    # Create release directory
    mkdir -p "${RELEASE_DIR}/x86_64"
    
    # Copy launcher scripts
    cp packaging/macos/*.command "${RELEASE_DIR}/x86_64/" 2>/dev/null || true
    cp packaging/macos/sample.env "${RELEASE_DIR}/x86_64/sample.env"
    cp packaging/macos/sample_framework.yaml "${RELEASE_DIR}/x86_64/"
    
    # Copy the built application
    cp -r dist/QueryRefine-x86_64/QueryRefine.app "${RELEASE_DIR}/x86_64/"
    
    # Create README
    cat > "${RELEASE_DIR}/x86_64/README.txt" << 'EOF'
Query Refinement Module - macOS x86_64 (Intel)
===============================================

Installation:
1. Copy the QueryRefine folder to your desired location
2. Copy .env.sample to .env and configure your API keys
3. Optionally, copy sample_framework.yaml to customize frameworks
4. Run "Configure Environment.command" to set up your environment
5. Run "Run Query Refine.command" to launch the application

Requirements:
- macOS 10.15 or later
- Intel processor

Configuration:
- Edit the .env file to add your LiteLLM API keys and settings
- Use --list-frameworks to see available refinement frameworks
- Use --help for command-line options

For more information, visit the project repository.
EOF
    
    # Create compressed archive
    cd "${RELEASE_DIR}"
    tar -czf "QueryRefine-macOS-x86_64.tar.gz" x86_64/
    cd - > /dev/null
    
    echo "✓ x86_64 release package created: ${RELEASE_DIR}/QueryRefine-macOS-x86_64.tar.gz"
    echo ""
fi

echo "=========================================="
echo "Build Summary"
echo "=========================================="
echo "Release location: ${RELEASE_DIR}"
echo ""
ls -lh "${RELEASE_DIR}"/*.tar.gz 2>/dev/null || true
echo ""
echo "✓ Build complete!"
echo ""
echo "To distribute:"
echo "  - Share the .tar.gz file with your colleagues"
echo "  - Recipients should extract and follow the README.txt"
echo ""
 