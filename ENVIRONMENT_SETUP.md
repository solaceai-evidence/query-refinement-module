# Environment Setup Guide

## Recommended Setup: Conda + Poetry

This project uses **conda for Python version management** and **poetry for dependency management**.

### Why This Approach?

- **Conda**: Manages Python version, system dependencies, and provides better support for AI/ML packages
- **Poetry**: Modern Python dependency management with lock files and virtual environment handling
- **No manual venv needed**: Poetry automatically manages virtual environments within conda

---

## Fresh Setup (New Users)

### 1. Create Conda Environment

```bash
# Create the environment
conda env create -f environment.yml

# Activate it
conda activate query-refinement
```

### 2. Install Python Dependencies

```bash
# Install all project dependencies
poetry install
```

### 3. Setup Environment Variables

```bash
# Create .env file
cp .env.example .env  # or create manually

# Edit .env and add your API key:
# QUERY_REFINEMENT_LLM_API_KEY=your-api-key-here
```

### 4. Start the Application

```bash
# Make sure conda environment is active
conda activate query-refinement

# Run the startup script
./start_webapp_dev.sh
```

---

## Migration from venv (Existing Users)

If you currently have `.venv` directory:

### 1. Save Current State

```bash
# Deactivate any active environment
deactivate 2>/dev/null || true

# Check what you have installed
pip freeze > old_requirements.txt
```

### 2. Remove .venv

```bash
# Remove the venv directory
rm -rf .venv
```

### 3. Update Conda Environment

```bash
# Update your conda environment
conda env update -f environment.yml

# Activate it
conda activate query-refinement
```

### 4. Install Dependencies with Poetry

```bash
# Install all dependencies
poetry install

# Verify installation
poetry show
```

### 5. Test Everything Works

```bash
# Start the application
./start_webapp_dev.sh
```

---

## Daily Workflow

### Starting Work

```bash
# 1. Activate conda environment
conda activate query-refinement

# 2. Start the application
./start_webapp_dev.sh
```

### Adding New Dependencies

```bash
# Add a package
poetry add package-name

# Add a dev dependency
poetry add --group dev package-name

# Update dependencies
poetry update
```

### Checking Environment

```bash
# Check active environment
conda info --envs

# Should show: query-refinement (active)

# Check Python version
python --version  # Should be 3.12+

# Check installed packages
poetry show
```

---

## Troubleshooting

### "Poetry not found"

```bash
# Reinstall conda environment
conda env remove -n query-refinement
conda env create -f environment.yml
```

### "Wrong Python version"

```bash
# Check active environment
echo $CONDA_DEFAULT_ENV

# Should show: query-refinement
# If not, activate it:
conda activate query-refinement
```

### "Import errors when running"

```bash
# Reinstall dependencies
poetry install

# Or if that fails, clear cache
poetry cache clear . --all
poetry install
```

### "Script says environment not active"

```bash
# Always activate before running the script
conda activate query-refinement
./start_webapp_dev.sh
```

---

## Key Files

- **environment.yml**: Conda environment specification (Python, Poetry, system tools)
- **pyproject.toml**: Poetry dependency specification (all Python packages)
- **poetry.lock**: Locked dependency versions (committed to git)
- **requirements.txt**: Legacy file (can be removed or kept for CI/CD)

---

## Benefits of This Setup

✅ **Consistent Python version** across team (3.12+)
✅ **Reproducible dependencies** via poetry.lock
✅ **Better AI/ML support** via conda
✅ **No manual venv management** - poetry handles it
✅ **Easy dependency updates** with poetry
✅ **Works on all platforms** (macOS, Linux, Windows)
