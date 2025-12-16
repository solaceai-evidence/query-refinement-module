#!/usr/bin/env python
"""
Complete the username migration manually by fixing the database state.
"""
import sqlite3
import os

# Get database path
db_path = os.path.join(os.path.dirname(__file__), '..', 'query_refinement.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Checking current database schema...")
schema = cursor.execute('PRAGMA table_info(users)').fetchall()
for col in schema:
    print(f"  {col}")

print("\n1. Creating unique index on username if not exists...")
try:
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)')
    print("  ✓ Index created")
except Exception as e:
    print(f"  ℹ Index may already exist: {e}")

print("\n2. Checking for existing users...")
users = cursor.execute('SELECT id, email, username FROM users').fetchall()
print(f"  Found {len(users)} users")

if users:
    print("\n3. Populating usernames from emails for existing users...")
    for user_id, email, username in users:
        if not username and email:
            # Generate username from email (part before @)
            generated_username = email.split('@')[0]
            print(f"  Setting username '{generated_username}' for user {user_id} ({email})")
            cursor.execute('UPDATE users SET username = ? WHERE id = ?', (generated_username, user_id))
    conn.commit()
    print("  ✓ Usernames populated")

print("\n4. Recreating table with proper constraints...")
# SQLite requires table recreation for constraint changes
cursor.execute('''
    CREATE TABLE users_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(50) NOT NULL UNIQUE,
        email VARCHAR(255) UNIQUE,
        name VARCHAR(128),
        password_hash VARCHAR(255) NOT NULL,
        created_at DATETIME,
        updated_at DATETIME
    )
''')

cursor.execute('''
    INSERT INTO users_new (id, username, email, name, password_hash, created_at, updated_at)
    SELECT id, username, email, name, password_hash, created_at, updated_at
    FROM users
''')

cursor.execute('DROP TABLE users')
cursor.execute('ALTER TABLE users_new RENAME TO users')

# Recreate index
cursor.execute('CREATE UNIQUE INDEX ix_users_username ON users (username)')

conn.commit()

print("\n✓ Migration completed successfully!")

print("\nFinal schema:")
schema = cursor.execute('PRAGMA table_info(users)').fetchall()
for col in schema:
    print(f"  {col}")

conn.close()

print("\nNow updating Alembic version stamp...")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("UPDATE alembic_version SET version_num = '2638f74414d0'")
conn.commit()
conn.close()
print("✓ Alembic version updated to 2638f74414d0")
