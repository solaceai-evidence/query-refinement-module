"""
Admin endpoints for advanced analytics and usage statistics.

Provides aggregated metrics on refinement completion rates, dimension usage,
command patterns, and LLM performance.
"""
from typing import List, Dict, Any, Optional, Iterable
from fastapi import APIRouter, Depends, Query as QueryParam
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_, or_
from datetime import datetime, timedelta
import re

from query_refinement_module.api.auth import get_current_user
from query_refinement_module.api.routes.admin import require_superuser
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.query import Query as QueryModel
from query_refinement_module.db.models.refinement_step import RefinementStep
from query_refinement_module.db.models.followup_history import FollowUpHistory
from query_refinement_module.db.models.audit_log import AuditLog, AuditSeverity
from query_refinement_module.db.session import get_db
from query_refinement_module.tracing import get_request_id

router = APIRouter(prefix="/api/admin/analytics", tags=["admin", "analytics"])


def _percentile(values: Iterable[int], percentile: float) -> Optional[float]:
    items = sorted(v for v in values if v is not None)
    if not items:
        return None
    if percentile <= 0:
        return float(items[0])
    if percentile >= 100:
        return float(items[-1])
    k = (len(items) - 1) * (percentile / 100.0)
    f = int(k)
    c = min(f + 1, len(items) - 1)
    if f == c:
        return float(items[f])
    d0 = items[f] * (c - k)
    d1 = items[c] * (k - f)
    return float(d0 + d1)


def _normalize_endpoint(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    path = url.split("?", 1)[0]
    path = re.sub(r"/queries/\d+", "/queries/:id", path)
    path = re.sub(r"/sessions/\d+", "/sessions/:id", path)
    return path


@router.get("/completion-rates", response_model=Dict[str, Any])
async def get_completion_rates(
    days: int = QueryParam(30, ge=1, le=365, description="Number of days to analyze"),
    framework: Optional[str] = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Get refinement completion statistics.
    
    **Admin Only**
    
    Args:
        days: Number of days to analyze (1-365, default: 30)
        framework: Optional framework filter
    
    Returns:
        - total_sessions: Total sessions created
        - completed_sessions: Sessions with synthesized queries
        - completion_rate: Percentage of sessions completed
        - avg_time_to_completion: Average time from start to synthesis
        - completed_with_all_aspects: Sessions that answered all refinement aspects
        - by_framework: Completion rates broken down by framework
        - by_time_bucket: Completion rates over time (daily/weekly)
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    request_id = get_request_id()
    
    # Base query filter
    base_filter = [QuerySession.created_at >= cutoff_date]
    if framework:
        base_filter.append(QuerySession.framework_name == framework)
    
    # Total sessions
    total_sessions = db.query(func.count(QuerySession.id))\
        .filter(*base_filter)\
        .scalar() or 0
    
    # Completed sessions (have at least one synthesized query)
    completed_sessions = db.query(func.count(func.distinct(QuerySession.id)))\
        .join(QueryModel, QueryModel.query_session_id == QuerySession.id)\
        .filter(*base_filter)\
        .filter(QueryModel.refined_query.isnot(None))\
        .scalar() or 0
    
    completion_rate = (completed_sessions / total_sessions * 100) if total_sessions > 0 else 0
    
    # Average time to completion (in seconds)
    time_stats = db.query(
        func.avg(
            func.julianday(QueryModel.updated_at) - func.julianday(QuerySession.created_at)
        ).label('avg_days')
    ).join(QueryModel, QueryModel.query_session_id == QuerySession.id)\
     .filter(*base_filter)\
     .filter(QueryModel.refined_query.isnot(None))\
     .first()
    
    avg_time_seconds = (time_stats.avg_days * 86400) if (time_stats and time_stats.avg_days) else 0
    
    # Sessions with all aspects completed
    # This is complex - we need to check if all aspects for a session have followups
    sessions_with_all_aspects = db.query(func.count(func.distinct(QuerySession.id)))\
        .join(QueryModel, QueryModel.query_session_id == QuerySession.id)\
        .join(RefinementStep, RefinementStep.query_id == QueryModel.id)\
        .join(FollowUpHistory, FollowUpHistory.refinement_step_id == RefinementStep.id)\
        .filter(*base_filter)\
        .filter(FollowUpHistory.answer.isnot(None))\
        .filter(QueryModel.refined_query.isnot(None))\
        .scalar() or 0
    
    # Completion by framework
    by_framework = []
    if not framework:  # Only show breakdown if not filtering by framework
        framework_stats = db.query(
            QuerySession.framework_name,
            func.count(QuerySession.id).label('total'),
            func.sum(
                case(
                    (QueryModel.refined_query.isnot(None), 1),
                    else_=0
                )
            ).label('completed')
        ).outerjoin(QueryModel, QueryModel.query_session_id == QuerySession.id)\
         .filter(QuerySession.created_at >= cutoff_date)\
         .group_by(QuerySession.framework_name)\
         .all()
        
        for fw_name, total, completed in framework_stats:
            by_framework.append({
                "framework": fw_name or "default",
                "total_sessions": total or 0,
                "completed_sessions": completed or 0,
                "completion_rate": ((completed or 0) / total * 100) if total > 0 else 0
            })
    
    # Time buckets (daily for last 7 days, then weekly)
    by_time_bucket = []
    if days <= 7:
        # Daily buckets
        for i in range(days):
            bucket_start = datetime.utcnow() - timedelta(days=i+1)
            bucket_end = datetime.utcnow() - timedelta(days=i)
            
            total = db.query(func.count(QuerySession.id))\
                .filter(QuerySession.created_at >= bucket_start)\
                .filter(QuerySession.created_at < bucket_end)\
                .scalar() or 0
            
            completed = db.query(func.count(func.distinct(QuerySession.id)))\
                .join(QueryModel, QueryModel.query_session_id == QuerySession.id)\
                .filter(QuerySession.created_at >= bucket_start)\
                .filter(QuerySession.created_at < bucket_end)\
                .filter(QueryModel.refined_query.isnot(None))\
                .scalar() or 0
            
            by_time_bucket.append({
                "date": bucket_start.date().isoformat(),
                "total_sessions": total,
                "completed_sessions": completed,
                "completion_rate": (completed / total * 100) if total > 0 else 0
            })
    
    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "completion_rate": round(completion_rate, 2),
        "avg_time_to_completion_seconds": round(avg_time_seconds, 2),
        "sessions_with_all_aspects_answered": sessions_with_all_aspects,
        "by_framework": by_framework,
        "by_time_bucket": list(reversed(by_time_bucket)),
        "period_days": days,
        "framework_filter": framework,
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/dimension-skip-rates", response_model=Dict[str, Any])
async def get_dimension_skip_rates(
    days: int = QueryParam(30, ge=1, le=365, description="Number of days to analyze"),
    framework: Optional[str] = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Analyze which refinement dimensions users skip most frequently.
    
    **Admin Only**
    
    Args:
        days: Number of days to analyze (1-365, default: 30)
        framework: Optional framework filter
    
    Returns:
        - total_refinement_steps: Total steps presented to users
        - steps_with_answers: Steps that received user answers
        - overall_skip_rate: Percentage of steps skipped (no answer)
        - by_aspect: Skip rates for each refinement aspect/dimension
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    request_id = get_request_id()
    
    # Base filter
    base_filter = [QuerySession.created_at >= cutoff_date]
    if framework:
        base_filter.append(QuerySession.framework_name == framework)
    
    # Total refinement steps
    total_steps = db.query(func.count(RefinementStep.id))\
        .join(QueryModel, QueryModel.id == RefinementStep.query_id)\
        .join(QuerySession, QuerySession.id == QueryModel.query_session_id)\
        .filter(*base_filter)\
        .scalar() or 0
    
    # Steps with answers (have at least one followup with an answer)
    steps_with_answers = db.query(func.count(func.distinct(RefinementStep.id)))\
        .join(QueryModel, QueryModel.id == RefinementStep.query_id)\
        .join(QuerySession, QuerySession.id == QueryModel.query_session_id)\
        .join(FollowUpHistory, FollowUpHistory.refinement_step_id == RefinementStep.id)\
        .filter(*base_filter)\
        .filter(FollowUpHistory.answer.isnot(None))\
        .scalar() or 0
    
    steps_skipped = total_steps - steps_with_answers
    overall_skip_rate = (steps_skipped / total_steps * 100) if total_steps > 0 else 0
    
    # Skip rates by aspect
    aspect_stats = db.query(
        RefinementStep.aspect_name,
        func.count(RefinementStep.id).label('total_presentations'),
        func.sum(
            case(
                (FollowUpHistory.answer.isnot(None), 1),
                else_=0
            )
        ).label('answered')
    ).join(QueryModel, QueryModel.id == RefinementStep.query_id)\
     .join(QuerySession, QuerySession.id == QueryModel.query_session_id)\
     .outerjoin(FollowUpHistory, FollowUpHistory.refinement_step_id == RefinementStep.id)\
     .filter(*base_filter)\
     .group_by(RefinementStep.aspect_name)\
     .all()
    
    by_aspect = []
    for aspect_name, total, answered in aspect_stats:
        answered_count = answered or 0
        skipped = total - answered_count
        skip_rate = (skipped / total * 100) if total > 0 else 0
        
        by_aspect.append({
            "aspect_name": aspect_name or "Unknown",
            "total_presentations": total,
            "answered": answered_count,
            "skipped": skipped,
            "skip_rate": round(skip_rate, 2)
        })
    
    # Sort by skip rate descending (most skipped first)
    by_aspect.sort(key=lambda x: x['skip_rate'], reverse=True)
    
    return {
        "total_refinement_steps": total_steps,
        "steps_with_answers": steps_with_answers,
        "steps_skipped": steps_skipped,
        "overall_skip_rate": round(overall_skip_rate, 2),
        "by_aspect": by_aspect,
        "period_days": days,
        "framework_filter": framework,
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/command-usage", response_model=Dict[str, Any])
async def get_command_usage(
    days: int = QueryParam(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Analyze user command usage patterns (/back, /clear, /skip, etc.).
    
    **Admin Only**
    
    Args:
        days: Number of days to analyze (1-365, default: 30)
    
    Returns:
        - total_commands: Total command executions
        - unique_users: Number of users who used commands
        - by_command: Usage breakdown for each command type
        - command_sequences: Common command patterns
        - avg_commands_per_session: Average commands per session
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    request_id = get_request_id()
    
    # Query audit logs for command events
    command_events = [
        'command.back',
        'command.clear',
        'command.skip',
        'command.restart',
        'command.help',
        'command.status'
    ]
    
    # Total commands
    total_commands = db.query(func.count(AuditLog.id))\
        .filter(AuditLog.created_at >= cutoff_date)\
        .filter(AuditLog.event_type.in_(command_events))\
        .scalar() or 0
    
    # Unique users who used commands
    unique_users = db.query(func.count(func.distinct(AuditLog.user_id)))\
        .filter(AuditLog.created_at >= cutoff_date)\
        .filter(AuditLog.event_type.in_(command_events))\
        .scalar() or 0
    
    # Commands by type
    command_stats = db.query(
        AuditLog.event_type,
        func.count(AuditLog.id).label('count'),
        func.count(func.distinct(AuditLog.user_id)).label('unique_users')
    ).filter(AuditLog.created_at >= cutoff_date)\
     .filter(AuditLog.event_type.in_(command_events))\
     .group_by(AuditLog.event_type)\
     .all()
    
    by_command = []
    for event_type, count, users in command_stats:
        command_name = event_type.replace('command.', '')
        by_command.append({
            "command": command_name,
            "total_uses": count,
            "unique_users": users,
            "avg_uses_per_user": round(count / users, 2) if users > 0 else 0
        })
    
    # Sort by usage
    by_command.sort(key=lambda x: x['total_uses'], reverse=True)
    
    # Average commands per session (sessions that used commands)
    sessions_with_commands = db.query(func.count(func.distinct(AuditLog.context_data['query_id'].astext)))\
        .filter(AuditLog.created_at >= cutoff_date)\
        .filter(AuditLog.event_type.in_(command_events))\
        .filter(AuditLog.context_data['query_id'].isnot(None))\
        .scalar() or 0
    
    avg_commands_per_session = (total_commands / sessions_with_commands) if sessions_with_commands > 0 else 0
    
    return {
        "total_commands": total_commands,
        "unique_users": unique_users,
        "sessions_with_commands": sessions_with_commands,
        "avg_commands_per_session": round(avg_commands_per_session, 2),
        "by_command": by_command,
        "period_days": days,
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/llm-performance", response_model=Dict[str, Any])
async def get_llm_performance(
    days: int = QueryParam(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Analyze LLM performance metrics (response times, token usage).
    
    **Admin Only**
    
    Args:
        days: Number of days to analyze (1-365, default: 30)
    
    Returns:
        - total_llm_calls: Total LLM API calls
        - avg_response_time: Average response time in seconds
        - total_tokens: Total tokens consumed
        - by_model: Performance breakdown by LLM model
        - by_operation: Performance by operation type (refinement, synthesis)
        - error_rate: Percentage of failed LLM calls
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    request_id = get_request_id()
    
    # Query audit logs for LLM events
    llm_events = [
        'llm.refinement_query',
        'llm.synthesis',
        'llm.followup',
        'llm.error'
    ]
    
    # Total LLM calls
    total_calls = db.query(func.count(AuditLog.id))\
        .filter(AuditLog.created_at >= cutoff_date)\
        .filter(AuditLog.event_type.in_(llm_events))\
        .filter(AuditLog.event_type != 'llm.error')\
        .scalar() or 0
    
    # Error calls
    error_calls = db.query(func.count(AuditLog.id))\
        .filter(AuditLog.created_at >= cutoff_date)\
        .filter(AuditLog.event_type == 'llm.error')\
        .scalar() or 0
    
    error_rate = (error_calls / (total_calls + error_calls) * 100) if (total_calls + error_calls) > 0 else 0
    
    # Performance stats (from LLM tracking events that have duration info)
    # Note: This assumes audit logs track duration in context_data
    response_time_stats = db.query(
        func.avg(
            func.cast(AuditLog.context_data['duration_ms'].astext, db.bind.dialect.NUMERIC)
        ).label('avg_duration')
    ).filter(AuditLog.created_at >= cutoff_date)\
     .filter(AuditLog.event_type.in_(llm_events))\
     .filter(AuditLog.context_data['duration_ms'].isnot(None))\
     .first()
    
    avg_response_time = response_time_stats.avg_duration if (response_time_stats and response_time_stats.avg_duration) else 0
    
    # Token usage (if available in context_data)
    token_stats = db.query(
        func.sum(
            func.cast(AuditLog.context_data['tokens'].astext, db.bind.dialect.INTEGER)
        ).label('total_tokens')
    ).filter(AuditLog.created_at >= cutoff_date)\
     .filter(AuditLog.event_type.in_(llm_events))\
     .filter(AuditLog.context_data['tokens'].isnot(None))\
     .first()
    
    total_tokens = token_stats.total_tokens if (token_stats and token_stats.total_tokens) else 0
    
    # By operation type
    operation_stats = db.query(
        AuditLog.event_type,
        func.count(AuditLog.id).label('count'),
        func.avg(
            func.cast(AuditLog.context_data['duration_ms'].astext, db.bind.dialect.NUMERIC)
        ).label('avg_duration')
    ).filter(AuditLog.created_at >= cutoff_date)\
     .filter(AuditLog.event_type.in_(llm_events))\
     .filter(AuditLog.event_type != 'llm.error')\
     .group_by(AuditLog.event_type)\
     .all()
    
    by_operation = []
    for event_type, count, avg_dur in operation_stats:
        operation_name = event_type.replace('llm.', '')
        by_operation.append({
            "operation": operation_name,
            "total_calls": count,
            "avg_response_time_ms": round(avg_dur, 2) if avg_dur else 0
        })
    
    # By model (if tracked in context_data)
    model_stats = db.query(
        AuditLog.context_data['model'].astext.label('model'),
        func.count(AuditLog.id).label('count')
    ).filter(AuditLog.created_at >= cutoff_date)\
     .filter(AuditLog.event_type.in_(llm_events))\
     .filter(AuditLog.context_data['model'].isnot(None))\
     .group_by(AuditLog.context_data['model'].astext)\
     .all()
    
    by_model = []
    for model, count in model_stats:
        if model:  # Skip None values
            by_model.append({
                "model": model,
                "total_calls": count
            })
    
    return {
        "total_llm_calls": total_calls,
        "error_calls": error_calls,
        "error_rate": round(error_rate, 2),
        "avg_response_time_ms": round(avg_response_time, 2),
        "total_tokens": total_tokens,
        "by_operation": by_operation,
        "by_model": by_model,
        "period_days": days,
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/dashboard", response_model=Dict[str, Any])
async def get_evaluation_dashboard(
    days: int = QueryParam(7, ge=1, le=365, description="Number of days to analyze"),
    error_limit: int = QueryParam(50, ge=1, le=500, description="Max errors to return"),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Summary dashboard for production evaluation.

    **Admin Only**
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    request_id = get_request_id()

    total_sessions = db.query(func.count(QuerySession.id))\
        .filter(QuerySession.created_at >= cutoff_date)\
        .scalar() or 0

    completed_sessions = db.query(func.count(func.distinct(QuerySession.id)))\
        .join(QueryModel, QueryModel.query_session_id == QuerySession.id)\
        .filter(QuerySession.created_at >= cutoff_date)\
        .filter(QueryModel.refined_query.isnot(None))\
        .scalar() or 0

    active_sessions = max(total_sessions - completed_sessions, 0)

    audit_errors = db.query(AuditLog)\
        .filter(AuditLog.timestamp >= cutoff_date)\
        .filter(AuditLog.severity.in_([AuditSeverity.ERROR, AuditSeverity.CRITICAL]))\
        .order_by(AuditLog.timestamp.desc())\
        .limit(error_limit)\
        .all()

    return {
        "workflow_counts": {
            "total_sessions": total_sessions,
            "completed_sessions": completed_sessions,
            "active_sessions": active_sessions,
            "completion_rate": round((completed_sessions / total_sessions * 100), 2) if total_sessions else 0.0,
        },
        "recent_errors": {
            "audit": [entry.to_dict() for entry in audit_errors],
        },
        "latency": {
            "source": "not_collected_in_chainlit_mode",
            "endpoints": [],
        },
        "period_days": days,
        "request_id": request_id,
        "timestamp": datetime.utcnow().isoformat(),
    }
