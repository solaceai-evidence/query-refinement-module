#!/usr/bin/env zsh
# =============================================================================
# recover_evaluation_data.sh
#
# Run this script ON YOUR LOCAL MAC.
# It will:
#   1. SSH into the Hetzner VM and create all data exports
#   2. Download everything to LOCAL_DEST on your Mac
#
# Usage:
#   chmod +x scripts/recover_evaluation_data.sh
#   ./scripts/recover_evaluation_data.sh
#
# SECURITY NOTE: This script contains DB credentials in plaintext.
# Delete or secure it after use, and rotate the DB password when done.
# =============================================================================

set -euo pipefail   # exit on any error

# ---------------------------------------------------------------------------
# Configuration — edit these if anything changes
# ---------------------------------------------------------------------------
SSH_KEY="$HOME/.ssh/id_ed25519"
REMOTE_USER="root"
REMOTE_HOST="89.167.74.9"
REMOTE_PROJECT="$HOME/suso/query-refinement-module"   # ~ expands on the VM

CONTAINER="query-refinement-db"
PGUSER="qruser"
PGPASSWORD='20254851qQ!!?!!'
PGDB="query_refinement"

REMOTE_EXPORT_DIR="/root/qr_export"
LOCAL_DEST="$HOME/research/evaluation_data"          # on your Mac
# ---------------------------------------------------------------------------

SSH=(ssh -i "$SSH_KEY" "${REMOTE_USER}@${REMOTE_HOST}")
SCP=(scp -i "$SSH_KEY")
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "============================================================"
echo "  Query Refinement — Evaluation Data Recovery"
echo "  Remote:  ${REMOTE_USER}@${REMOTE_HOST}"
echo "  Local:   ${LOCAL_DEST}"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# PHASE 1: Run all export commands on the remote VM
# ---------------------------------------------------------------------------
echo "[1/3] Creating exports on the VM …"

"${SSH[@]}" bash -s <<REMOTE_SCRIPT
set -euo pipefail

CONTAINER="${CONTAINER}"
PGUSER="${PGUSER}"
PGPASSWORD="${PGPASSWORD}"
PGDB="${PGDB}"
EXPORT_DIR="${REMOTE_EXPORT_DIR}"
TIMESTAMP="${TIMESTAMP}"

PSQL_CMD="docker exec -e PGPASSWORD=\${PGPASSWORD} \${CONTAINER} psql -U \${PGUSER} -d \${PGDB}"

echo "  -> Verifying container is running …"
docker ps --filter "name=\${CONTAINER}" --format "{{.Status}}"

# Create export directory
mkdir -p "\${EXPORT_DIR}"

# ---- Row count sanity check ------------------------------------------------
echo ""
echo "  -> Row counts:"
docker exec -e PGPASSWORD="\${PGPASSWORD}" "\${CONTAINER}" \
  psql -U "\${PGUSER}" -d "\${PGDB}" -c "
SELECT 'users'                    AS table_name, COUNT(*) AS rows FROM users
UNION ALL SELECT 'query_sessions',               COUNT(*) FROM query_sessions
UNION ALL SELECT 'queries',                      COUNT(*) FROM queries
UNION ALL SELECT 'refinement_steps',             COUNT(*) FROM refinement_steps
UNION ALL SELECT 'followup_history',             COUNT(*) FROM followup_history
UNION ALL SELECT 'refinement_step_metadata',     COUNT(*) FROM refinement_step_metadata
UNION ALL SELECT 'feedback',                     COUNT(*) FROM feedback
UNION ALL SELECT 'audit_logs',                   COUNT(*) FROM audit_logs
ORDER BY table_name;
"

# ---- Full binary dump ------------------------------------------------------
echo ""
echo "  -> Creating full binary backup …"
docker exec -e PGPASSWORD="\${PGPASSWORD}" "\${CONTAINER}" \
  pg_dump -U "\${PGUSER}" -d "\${PGDB}" -Fc -Z 9 \
  > "\${EXPORT_DIR}/query_refinement_backup_\${TIMESTAMP}.dump"
echo "     Done: \$(du -sh \${EXPORT_DIR}/query_refinement_backup_\${TIMESTAMP}.dump | cut -f1)"

# ---- Per-table CSV exports -------------------------------------------------
echo ""
echo "  -> Exporting individual tables as CSV …"

export_table() {
  local TABLE=\$1
  docker exec -e PGPASSWORD="\${PGPASSWORD}" "\${CONTAINER}" \
    psql -U "\${PGUSER}" -d "\${PGDB}" -c "\COPY \${TABLE} TO STDOUT WITH (FORMAT CSV, HEADER true)" \
    > "\${EXPORT_DIR}/\${TABLE}.csv"
  local ROWS=\$(( \$(wc -l < "\${EXPORT_DIR}/\${TABLE}.csv") - 1 ))
  echo "     \${TABLE}: \${ROWS} rows"
}

export_table users
export_table query_sessions
export_table queries
export_table refinement_steps
export_table followup_history
export_table refinement_step_metadata
export_table feedback
export_table audit_logs

# ---- Denormalised research export ------------------------------------------
echo ""
echo "  -> Creating denormalised flat export (all key tables joined) …"
docker exec -e PGPASSWORD="\${PGPASSWORD}" "\${CONTAINER}" \
  psql -U "\${PGUSER}" -d "\${PGDB}" -c "
COPY (
  SELECT
    u.id                            AS participant_id,
    u.has_completed_workflow,
    qs.id                           AS session_id,
    qs.started_at                   AS session_started_at,
    qs.ended_at                     AS session_ended_at,
    qs.status                       AS session_status,
    qs.framework_name,
    q.id                            AS query_id,
    q.original_query,
    q.synthesized_statement,
    q.search_optimized,
    q.search_filters,
    q.terminology,
    q.refined_dimensions,
    q.processing_log,
    q.response_metadata,
    q.created_at                    AS query_created_at,
    q.completed_at                  AS query_completed_at,
    q.consent_given,
    rs.id                           AS step_id,
    rs.aspect_name,
    rs.final_value,
    rs.is_complete,
    rs.was_skipped,
    rs.user_ended_early,
    rs.created_at                   AS step_created_at,
    rsm.llm_provider,
    rsm.llm_model,
    rsm.prompt_tokens,
    rsm.completion_tokens,
    rsm.total_tokens,
    rsm.estimated_cost_usd,
    rsm.llm_duration_seconds,
    rsm.processing_duration_seconds,
    rsm.status                      AS step_status
  FROM users u
  JOIN query_sessions qs   ON qs.user_id = u.id
  JOIN queries q           ON q.session_id = qs.id
  JOIN refinement_steps rs ON rs.query_id = q.id
  LEFT JOIN refinement_step_metadata rsm ON rsm.refinement_step_id = rs.id
  ORDER BY u.id, qs.id, q.id, rs.id
) TO STDOUT WITH (FORMAT CSV, HEADER true)
" > "\${EXPORT_DIR}/research_flat_export.csv"
echo "     \$(( \$(wc -l < "\${EXPORT_DIR}/research_flat_export.csv") - 1 )) rows"

# ---- Conversation / Q&A export ---------------------------------------------
echo ""
echo "  -> Exporting follow-up conversation logs …"
docker exec -e PGPASSWORD="\${PGPASSWORD}" "\${CONTAINER}" \
  psql -U "\${PGUSER}" -d "\${PGDB}" -c "
COPY (
  SELECT
    u.id          AS participant_id,
    qs.id         AS session_id,
    qs.framework_name,
    q.id          AS query_id,
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
" > "\${EXPORT_DIR}/followup_conversations.csv"
echo "     \$(( \$(wc -l < "\${EXPORT_DIR}/followup_conversations.csv") - 1 )) rows"

# ---- Feedback export -------------------------------------------------------
echo ""
echo "  -> Exporting feedback with context …"
docker exec -e PGPASSWORD="\${PGPASSWORD}" "\${CONTAINER}" \
  psql -U "\${PGUSER}" -d "\${PGDB}" -c "
COPY (
  SELECT
    f.id,
    f.user_id   AS participant_id,
    f.query_id,
    q.original_query,
    qs.framework_name,
    f.rating,
    f.comments,
    f.additional_metadata,
    f.created_at
  FROM feedback f
  LEFT JOIN queries q       ON q.id  = f.query_id
  LEFT JOIN query_sessions qs ON qs.id = q.session_id
  ORDER BY f.created_at
) TO STDOUT WITH (FORMAT CSV, HEADER true)
" > "\${EXPORT_DIR}/feedback_with_context.csv"
echo "     \$(( \$(wc -l < "\${EXPORT_DIR}/feedback_with_context.csv") - 1 )) rows"

# ---- Package everything ----------------------------------------------------
echo ""
echo "  -> Packaging archive …"
tar -czf "\${EXPORT_DIR}/../qr_data_export_\${TIMESTAMP}.tar.gz" -C "\$(dirname \${EXPORT_DIR})" "\$(basename \${EXPORT_DIR})"
echo "     Archive: \$(du -sh \${EXPORT_DIR}/../qr_data_export_\${TIMESTAMP}.tar.gz | cut -f1)"
echo ""
echo "  All exports complete on VM."
REMOTE_SCRIPT

# ---------------------------------------------------------------------------
# PHASE 2: Download the archive to your Mac
# ---------------------------------------------------------------------------
echo ""
echo "[2/3] Downloading archive to ${LOCAL_DEST} …"
mkdir -p "${LOCAL_DEST}"

# Find the archive on the remote (it's in /root/)
ARCHIVE_NAME="qr_data_export_${TIMESTAMP}.tar.gz"

"${SCP[@]}" "${REMOTE_USER}@${REMOTE_HOST}:~/${ARCHIVE_NAME}" "${LOCAL_DEST}/"

echo "     Downloaded: ${LOCAL_DEST}/${ARCHIVE_NAME}"

# ---------------------------------------------------------------------------
# PHASE 3: Extract locally
# ---------------------------------------------------------------------------
echo ""
echo "[3/3] Extracting …"
tar -xzf "${LOCAL_DEST}/${ARCHIVE_NAME}" -C "${LOCAL_DEST}"

echo ""
echo "============================================================"
echo "  DONE — files saved to:"
ls -lh "${LOCAL_DEST}/qr_export/"
echo ""
echo "  REMINDER: Before including any data in your paper,"
echo "  anonymise: users.username, users.email, users.name"
echo "  and review free-text fields for accidental PII."
echo "============================================================"
