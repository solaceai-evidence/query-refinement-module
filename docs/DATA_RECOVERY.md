# Data Recovery from Hetzner VM — Post-Evaluation Export Guide

This guide covers recovering all evaluation data from the PostgreSQL database running in
Docker on the remote Hetzner VM. It produces both a full binary backup (safe archive) and
per-table CSV/JSON exports suitable for research paper analysis.

---

## 1. Database Overview

| Table                      | Research relevance                                                                                                    |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `users`                    | Participant accounts; anonymise before publication                                                                    |
| `query_sessions`           | Per-session metadata (framework used, timestamps, status)                                                             |
| `queries`                  | Original queries + full LLM-refined output (synthesized statement, dimensions, search variants, filters, terminology) |
| `refinement_steps`         | Per-dimension outcomes: final value, is_complete, was_skipped, user_ended_early                                       |
| `followup_history`         | Q&A exchanges (question → answer) per refinement step                                                                 |
| `refinement_step_metadata` | LLM usage: model, tokens, cost, duration per step                                                                     |
| `feedback`                 | User ratings and free-text comments                                                                                   |
| `audit_logs`               | Full event log for behavioural analysis (commands, timings)                                                           |

---

## 2. Prerequisites

- SSH access to the Hetzner VM (key-based recommended)
- The VM has Docker and Docker Compose running
- Default container name: `query-refinement-db`
- Default DB name / user: `query_refinement` / `qruser` (check your `.env` on the VM)

---

## 3. Step 1 — SSH into the VM

```bash
ssh <your-user>@<hetzner-vm-ip>
```

Confirm the database container is running:

```bash
docker ps --filter name=query-refinement-db
```

---

## 4. Step 2 — Verify DB credentials

```bash
# Read from the project .env (adjust path if needed)
cd ~/query-refinement-module   # or wherever the project lives on the VM
grep -E 'POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB' .env
```

Substitute the real values for `PGUSER`, `PGPASSWORD`, and `PGDB` in every command below.
The defaults are:

```
PGUSER=qruser
PGPASSWORD=changeme
PGDB=query_refinement
```

---

## 5. Step 3 — Full binary dump (recommended first step)

This produces a portable, complete backup you can restore locally at any time.

```bash
# On the VM — creates a compressed binary dump
docker exec query-refinement-db \
  pg_dump -U qruser -d query_refinement -Fc -Z 9 \
  > ~/query_refinement_full_backup_$(date +%Y%m%d_%H%M%S).dump
```

> **Note:** Replace `qruser` / `query_refinement` with your actual values if they differ.
> The `-Fc` flag produces a custom-format dump; `-Z 9` applies maximum compression.

---

## 6. Step 4 — Export each table as CSV

Run the block below on the VM. It writes one `.csv` file per table into `~/qr_export/`.

```bash
mkdir -p ~/qr_export

# Helper — export a table to CSV (headers included)
export_table() {
  local TABLE=$1
  docker exec query-refinement-db \
    psql -U qruser -d query_refinement -c \
    "\COPY $TABLE TO STDOUT WITH (FORMAT CSV, HEADER true)" \
    > ~/qr_export/${TABLE}.csv
  echo "Exported: $TABLE"
}

export_table users
export_table query_sessions
export_table queries
export_table refinement_steps
export_table followup_history
export_table refinement_step_metadata
export_table feedback
export_table audit_logs

echo "All tables exported to ~/qr_export/"
ls -lh ~/qr_export/
```

---

## 7. Step 5 — Denormalised research export (single flat file)

This query joins the key tables into one wide CSV that is convenient for spreadsheet /
statistical analysis without needing to join tables manually.

```bash
docker exec query-refinement-db \
  psql -U qruser -d query_refinement -c "
\COPY (
  SELECT
    -- Participant (anonymised id only — do not export username/email)
    u.id                          AS participant_id,
    u.has_completed_workflow,

    -- Session
    qs.id                         AS session_id,
    qs.started_at                 AS session_started_at,
    qs.ended_at                   AS session_ended_at,
    qs.status                     AS session_status,
    qs.framework_name,

    -- Query
    q.id                          AS query_id,
    q.original_query,
    q.synthesized_statement,
    q.search_optimized,
    q.search_filters,
    q.terminology,
    q.refined_dimensions,
    q.processing_log,
    q.response_metadata,
    q.created_at                  AS query_created_at,
    q.completed_at                AS query_completed_at,
    q.consent_given,

    -- Refinement step
    rs.id                         AS step_id,
    rs.aspect_name,
    rs.final_value,
    rs.is_complete,
    rs.was_skipped,
    rs.user_ended_early,
    rs.created_at                 AS step_created_at,

    -- LLM metadata
    rsm.llm_provider,
    rsm.llm_model,
    rsm.prompt_tokens,
    rsm.completion_tokens,
    rsm.total_tokens,
    rsm.estimated_cost_usd,
    rsm.llm_duration_seconds,
    rsm.processing_duration_seconds,
    rsm.status                    AS step_status

  FROM users u
  JOIN query_sessions qs ON qs.user_id = u.id
  JOIN queries q         ON q.session_id = qs.id
  JOIN refinement_steps rs ON rs.query_id = q.id
  LEFT JOIN refinement_step_metadata rsm ON rsm.refinement_step_id = rs.id
  ORDER BY u.id, qs.id, q.id, rs.id
) TO STDOUT WITH (FORMAT CSV, HEADER true)
" > ~/qr_export/research_flat_export.csv

echo "Flat export done: $(wc -l ~/qr_export/research_flat_export.csv) rows"
```

---

## 8. Step 6 — Export follow-up Q&A history (conversation logs)

```bash
docker exec query-refinement-db \
  psql -U qruser -d query_refinement -c "
\COPY (
  SELECT
    u.id        AS participant_id,
    qs.id       AS session_id,
    qs.framework_name,
    q.id        AS query_id,
    q.original_query,
    rs.aspect_name,
    fh.question,
    fh.answer,
    fh.created_at
  FROM followup_history fh
  JOIN refinement_steps rs ON rs.id = fh.refinement_step_id
  JOIN queries q            ON q.id  = rs.query_id
  JOIN query_sessions qs    ON qs.id = q.session_id
  JOIN users u              ON u.id  = qs.user_id
  ORDER BY u.id, qs.id, q.id, rs.id, fh.created_at
) TO STDOUT WITH (FORMAT CSV, HEADER true)
" > ~/qr_export/followup_conversations.csv
```

---

## 9. Step 7 — Export feedback

```bash
docker exec query-refinement-db \
  psql -U qruser -d query_refinement -c "
\COPY (
  SELECT
    f.id,
    f.user_id   AS participant_id,
    f.query_id,
    f.rating,
    f.comments,
    f.additional_metadata,
    f.created_at
  FROM feedback f
  ORDER BY f.created_at
) TO STDOUT WITH (FORMAT CSV, HEADER true)
" > ~/qr_export/feedback.csv
```

---

## 10. Step 8 — Row-count sanity check

Before downloading, verify you have data in every table:

```bash
docker exec query-refinement-db \
  psql -U qruser -d query_refinement -c "
SELECT 'users'                   AS tbl, COUNT(*) FROM users
UNION ALL
SELECT 'query_sessions',                  COUNT(*) FROM query_sessions
UNION ALL
SELECT 'queries',                         COUNT(*) FROM queries
UNION ALL
SELECT 'refinement_steps',                COUNT(*) FROM refinement_steps
UNION ALL
SELECT 'followup_history',                COUNT(*) FROM followup_history
UNION ALL
SELECT 'refinement_step_metadata',        COUNT(*) FROM refinement_step_metadata
UNION ALL
SELECT 'feedback',                        COUNT(*) FROM feedback
UNION ALL
SELECT 'audit_logs',                      COUNT(*) FROM audit_logs
ORDER BY tbl;
"
```

---

## 11. Step 9 — Package everything and transfer locally

On the VM, compress the export directory and the binary dump:

```bash
# Compress
tar -czf ~/qr_data_export.tar.gz ~/qr_export/ ~/query_refinement_full_backup_*.dump

echo "Archive ready: $(du -sh ~/qr_data_export.tar.gz)"
```

On your **local machine**, download the archive:

```bash
# Replace <your-user> and <hetzner-vm-ip> with real values
scp <your-user>@<hetzner-vm-ip>:~/qr_data_export.tar.gz ./qr_data_export.tar.gz

# Extract
tar -xzf qr_data_export.tar.gz
```

---

## 12. Step 10 (Optional) — Restore locally for SQL querying

If you want to run ad-hoc SQL queries against a local copy:

```bash
# Start a temporary local Postgres container
docker run --rm -d \
  --name qr-local-db \
  -e POSTGRES_USER=qruser \
  -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=query_refinement \
  -p 5432:5432 \
  postgres:16-alpine

# Wait for it to be ready
sleep 5

# Restore from the binary dump
docker exec -i qr-local-db \
  pg_restore -U qruser -d query_refinement --no-owner --role=qruser \
  < ./query_refinement_full_backup_*.dump

# Connect
docker exec -it qr-local-db psql -U qruser -d query_refinement
```

---

## 13. Anonymisation notes before publication

Before including any data in a paper, remove or pseudonymise:

- `users.username`, `users.email`, `users.name` — replace with `P001`, `P002`, …
- `users.password_hash` — exclude entirely
- Free-text fields (`original_query`, `followup_history.answer`, `feedback.comments`) —
  review for accidental PII (names, institutions, etc.)
- `audit_logs.ip_address` (if present) — exclude

The `participant_id` integer from the exports is safe to use as a pseudonymous identifier.

---

## 14. Quick reference — key files produced

| File                                     | Contents                                 |
| ---------------------------------------- | ---------------------------------------- |
| `query_refinement_full_backup_<ts>.dump` | Full restorable binary backup            |
| `qr_export/users.csv`                    | Participant accounts                     |
| `qr_export/query_sessions.csv`           | Session metadata                         |
| `qr_export/queries.csv`                  | Queries + full LLM output (JSON columns) |
| `qr_export/refinement_steps.csv`         | Per-dimension outcomes                   |
| `qr_export/followup_history.csv`         | Individual Q&A exchanges                 |
| `qr_export/refinement_step_metadata.csv` | LLM token/cost/duration metrics          |
| `qr_export/feedback.csv`                 | Ratings and free-text feedback           |
| `qr_export/audit_logs.csv`               | Full event log                           |
| `qr_export/research_flat_export.csv`     | Denormalised join of all key tables      |
| `qr_export/followup_conversations.csv`   | Conversation logs with session context   |
