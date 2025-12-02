# Database Migrations Guide

This project uses Alembic for database schema management.

## Quick Start

```bash
# Apply all migrations (creates tables)
poetry run alembic upgrade head

# Check current migration version
poetry run alembic current

# View migration history
poetry run alembic history
```

## Creating New Migrations

When you add or modify database models:

```bash
# Generate migration from model changes
poetry run alembic revision --autogenerate -m "Description of changes"

# Review the generated migration file in:
# query_refinement_module/db/migrations/versions/

# Apply the migration
poetry run alembic upgrade head
```

## Migration Commands

### Upgrade

```bash
# Upgrade to latest version
poetry run alembic upgrade head

# Upgrade by one version
poetry run alembic upgrade +1

# Upgrade to specific revision
poetry run alembic upgrade <revision_id>
```

### Downgrade

```bash
# Downgrade by one version
poetry run alembic downgrade -1

# Downgrade to specific revision
poetry run alembic downgrade <revision_id>

# Downgrade to base (remove all tables)
poetry run alembic downgrade base
```

### Information

```bash
# Show current version
poetry run alembic current

# Show migration history
poetry run alembic history --verbose

# Show SQL that would be executed (don't apply)
poetry run alembic upgrade head --sql
```

## Current Schema

The database includes the following tables:

- **users** - User authentication and profiles
- **query_sessions** - Query refinement sessions
- **queries** - Original and refined queries
- **refinement_steps** - Individual aspect refinements
- **followup_history** - Multi-turn Q&A for each step
- **feedback** - User feedback on queries

## Migration Files

Location: `query_refinement_module/db/migrations/versions/`

Current migrations:
- `f02d0f7a5296_initial_db_schema.py` - Initial schema with all tables

## Development Workflow

### Adding a New Field

1. Modify the SQLAlchemy model in `query_refinement_module/db/models/`

```python
# Example: Add a field to User model
class User(Base):
    __tablename__ = "users"
    # ... existing fields ...
    phone = Column(String(20), nullable=True)  # New field
```

2. Generate migration:

```bash
poetry run alembic revision --autogenerate -m "Add phone field to users table"
```

3. Review the generated migration file

4. Apply the migration:

```bash
poetry run alembic upgrade head
```

### Testing Migrations

```bash
# Start with clean database
rm -f query_refinement.db

# Apply migrations
poetry run alembic upgrade head

# Verify schema
sqlite3 query_refinement.db ".schema"

# Run application tests
poetry run pytest tests/integration/
```

## Production Deployment

### Initial Setup

```bash
# Set DATABASE_URL environment variable
export DATABASE_URL="postgresql://user:pass@localhost/dbname"

# Run migrations
poetry run alembic upgrade head
```

### Updating Production

```bash
# Pull latest code with new migrations
git pull

# Apply new migrations
poetry run alembic upgrade head

# Restart application
```

## Troubleshooting

### "Target database is not up to date"

This means the database has tables but Alembic doesn't know which version it's at.

```bash
# Option 1: Stamp database with current schema
poetry run alembic stamp head

# Option 2: Start fresh (WARNING: deletes all data)
rm -f query_refinement.db
poetry run alembic upgrade head
```

### "Can't locate revision"

Delete the problematic migration file and regenerate:

```bash
# Remove bad migration
rm query_refinement_module/db/migrations/versions/<revision_id>_*.py

# Generate new one
poetry run alembic revision --autogenerate -m "Your description"
```

### Schema Out of Sync

If models don't match database:

```bash
# Generate migration to sync
poetry run alembic revision --autogenerate -m "Sync schema"

# Review and apply
poetry run alembic upgrade head
```

## Configuration

Alembic configuration is in:
- `alembic.ini` - Main configuration
- `query_refinement_module/db/migrations/env.py` - Migration environment

Database URL is read from:
1. `DATABASE_URL` environment variable
2. `.env` file
3. Defaults to `sqlite:///query_refinement.db`

## Best Practices

1. **Always review auto-generated migrations** before applying
2. **Test migrations on development database** before production
3. **Keep migrations small and focused** - one logical change per migration
4. **Never edit applied migrations** - create a new migration to fix issues
5. **Commit migrations to version control** with the code changes
6. **Document complex migrations** with comments in the migration file
7. **Back up production database** before running migrations

## API Server Integration

The FastAPI server **does not** automatically run migrations. You must run them separately:

```bash
# Before starting the server
poetry run alembic upgrade head

# Then start server
poetry run uvicorn query_refinement_module.api.main:app
```

The test runner (`tests/api/run_api_tests.sh`) automatically runs migrations before starting the test server.
