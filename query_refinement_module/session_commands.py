"""
Command handlers for QueryRefinementSession.

Extracted from core.py to reduce class complexity.
"""
from typing import Dict, Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from query_refinement_module.core import RefinementSession, UserCommand


def get_help_text() -> str:
    """Get help text for commands - imported from core at runtime to avoid circular import."""
    from query_refinement_module.core import get_help_text as core_get_help_text
    return core_get_help_text()


class SessionCommands:
    """Handles user command execution for a QueryRefinementSession."""
    
    def __init__(self, session: 'RefinementSession'):
        """
        Initialize command handlers.
        
        Args:
            session: The session to operate on
        """
        from query_refinement_module.core import UserCommand
        
        self.session = session
        
        # Command dispatch table
        self.handlers: Dict['UserCommand', Callable[[], Dict[str, Any]]] = {
            UserCommand.BACK: self.go_back,
            UserCommand.PREVIOUS: self.go_back,
            UserCommand.RESTART: self.restart,
            UserCommand.SKIP: self.skip_current,
            UserCommand.DONE: self.finish_current,
            UserCommand.CLEAR: self.clear_current,
            UserCommand.STATUS: self.get_status,
            UserCommand.STEPS: self.list_steps,
            UserCommand.SUBMIT: self.request_synthesis,
            UserCommand.HELP: lambda: {"success": True, "message": get_help_text()},
        }
    
    def execute(self, command: 'UserCommand') -> Dict[str, Any]:
        """
        Execute a command.
        
        Args:
            command: The command to execute
            
        Returns:
            Dict with 'success', 'message', and optional command-specific data
        """
        handler = self.handlers.get(command)
        if handler:
            return handler()
        return {"success": False, "message": f"Command {command.name} not implemented"}

    def _get_active_or_last_completed(self):
        """Return active step, or last completed step when session is fully complete/reviewing."""
        active = self.session.get_active_step()
        if active:
            return active

        if self.session.steps and (self.session.synthesis_requested or all(step.is_complete for step in self.session.steps)):
            return self.session.steps[-1]

        return None
    
    def go_back(self) -> Dict[str, Any]:
        """Navigate to previous refinement dimension, recreating truncated dimensions as placeholders."""
        active = self._get_active_or_last_completed()
        if not active:
            return {"success": False, "message": "No active step to go back from"}
        
        active_idx = self.session.steps.index(active)
        if active_idx == 0:
            return {"success": False, "message": "Already at first refinement dimension. Use /restart to start over."}
        
        # Exiting synthesis-ready review state because user is modifying session
        self.session.synthesis_requested = False

        # Get previous step
        prev_step = self.session.steps[active_idx - 1]
        
        # Track what will be cleared (everything from current onward)
        cleared_aspects = [
            step.refinement_aspect.name 
            for step in self.session.steps[active_idx:]
        ]
        
        # Truncate session.steps - remove current and all subsequent dimensions
        self.session.steps = self.session.steps[:active_idx]
        
        # Reopen the previous step - clear its state completely for fresh re-refinement
        prev_step.is_complete = False
        prev_step.needs_review = False
        prev_step.follow_up_question = None
        prev_step.conversation_history = []
        prev_step.normalized_value = None
        prev_step.reasoning = None
        prev_step.was_skipped = False
        
        # Recreate truncated dimensions as fresh placeholders from the complete framework
        # This ensures they reappear in /status and can be refined as user progresses forward
        if self.session._complete_framework:
            # Build a map of existing step aspect IDs for quick lookup
            existing_aspect_ids = {step.refinement_aspect.id for step in self.session.steps}
            
            # Recreate missing dimensions from the complete framework in original order
            for aspect in self.session._complete_framework:
                if aspect.id not in existing_aspect_ids:
                    # Create a fresh placeholder step for this dimension
                    from query_refinement_module.session_models import AspectRefinementState
                    new_step = AspectRefinementState(
                        refinement_aspect=aspect,
                        conversation_history=[],
                        is_complete=False,
                        needs_review=False,
                        was_skipped=False,
                        reasoning=None,
                        follow_up_question=None,
                        normalized_value=None
                    )
                    self.session.steps.append(new_step)
        
        message = f"Moved back to: {prev_step.refinement_aspect.name}"
        if cleared_aspects:
            message += f"\n⚠️  Cleared {len(cleared_aspects)} refinement dimension(s): {', '.join(cleared_aspects)}"
            message += "\nThey will be regenerated based on your updated answers."
        
        return {
            "success": True,
            "message": message,
            "step_index": active_idx - 1,
            "step": prev_step,
            "cleared_aspects": cleared_aspects,
        }
    
    def restart(self) -> Dict[str, Any]:
        """Restart the entire refinement session, recreating all dimensions as fresh placeholders."""
        # Track all refinement dimensions being cleared for DB cascade delete
        cleared_aspects = [
            step.refinement_aspect.name
            for step in self.session.steps
        ]
        cleared_count = len(self.session.steps)
        
        # Clear all steps
        self.session.steps = []
        self.session.synthesis_requested = False
        
        # Recreate all dimensions as fresh placeholders from the complete framework
        if self.session._complete_framework:
            from query_refinement_module.session_models import AspectRefinementState
            for aspect in self.session._complete_framework:
                new_step = AspectRefinementState(
                    refinement_aspect=aspect,
                    conversation_history=[],
                    is_complete=False,
                    needs_review=False,
                    was_skipped=False,
                    reasoning=None,
                    follow_up_question=None,
                    normalized_value=None
                )
                self.session.steps.append(new_step)
        
        return {
            "success": True,
            "message": f"Session restarted. All {cleared_count} refinement dimension(s) cleared.",
            "cleared_aspects": cleared_aspects,
        }
    
    def skip_current(self) -> Dict[str, Any]:
        """Skip the current refinement dimension, clearing all data."""
        active = self.session.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to skip"}
        
        # Clear all data when skipping
        active.conversation_history = []
        active.normalized_value = None
        active.is_complete = True
        active.was_skipped = True
        active.needs_review = False
        
        return {
            "success": True,
            "message": f"Skipped: {active.refinement_aspect.name}.\nNo specifications from this dimension will be provided to dependent refinement dimensions.",
            "step": active,
        }
    
    def clear_current(self) -> Dict[str, Any]:
        """Clear current refinement dimension's answers and restart it."""
        active = self._get_active_or_last_completed()
        if not active:
            return {"success": False, "message": "No active step to clear"}

        # Exiting synthesis-ready review state because user is modifying session
        self.session.synthesis_requested = False
        
        # Clear all data for current refinement dimension
        active.conversation_history = []
        active.normalized_value = None
        active.is_complete = False
        active.was_skipped = False
        active.needs_review = False
        active.follow_up_question = None
        
        return {
            "success": True,
            "message": f"Cleared: {active.refinement_aspect.name}. Question will be regenerated.",
            "step": active,
            "regenerate_question": True,
        }
    
    def finish_current(self) -> Dict[str, Any]:
        """Finish the current step, preserving captured responses."""
        active = self.session.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to finish"}
        
        message = f"Completed refinement dimension: {active.refinement_aspect.name}"
        if active.normalized_value_as_str:
            message += f" (using current value: {active.normalized_value_as_str})."
        else:
            message += " (no additional details provided)."
        
        # Mark complete without marking as skipped
        active.is_complete = True
        active.needs_review = False
        active.was_skipped = False
        
        return {
            "success": True,
            "message": message,
            "step": active,
        }
    
    def request_synthesis(self) -> Dict[str, Any]:
        """Request immediate synthesis using currently captured clarifications."""
        self.session.synthesis_requested = True
        return {
            "success": True,
            "message": "Generating refined query with current clarifications.",
            "submit": True,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current session status with detailed dimension information."""
        active = self.session.get_active_step()
        summary = self.session.get_step_summary()
        
        # Calculate remaining refinement dimensions
        total_aspects = len(self.session.refinement_framework)
        processed_count = len(self.session.steps)
        remaining_count = total_aspects - processed_count
        
        # Build basic status message
        status_lines = [
            "Session Status:",
            f"  Processed: {summary['completed']}/{processed_count} complete",
            f"  Follow-ups asked: {summary['total_follow_ups']}",
        ]
        
        if active:
            active_idx = self.session.steps.index(active) + 1
            status_tag = " (needs review)" if active.needs_review else ""
            status_lines.append(f"  Current: Step {active_idx} - {active.refinement_aspect.name}{status_tag}")
        else:
            if processed_count == total_aspects:
                status_lines.append("  Current: All refinement dimensions processed")
            else:
                status_lines.append(f"  Current: Ready for next refinement dimension ({remaining_count} remaining)")
        
        # Build detailed dimension status
        dimension_details = []
        for step in self.session.steps:
            # Determine status
            if step.was_skipped:
                status = "skipped"
                status_icon = "⊘"
            elif step.is_complete and not step.needs_review:
                status = "complete"
                status_icon = "✓"
            elif step.needs_review:
                status = "needs_review"
                status_icon = "⚠"
            elif step == active:
                status = "active"
                status_icon = "▶"
            else:
                status = "in_progress"
                status_icon = "◌"
            
            # Get assembled value
            assembled_value = None
            if step.normalized_value_as_str and not step.was_skipped:
                assembled_value = step.normalized_value_as_str
            
            # Get dependency information
            depends_on = step.refinement_aspect.depends_on or []
            dependency_names = []
            for dep_id in depends_on:
                dep_step = next((s for s in self.session.steps if s.refinement_aspect.id == dep_id), None)
                if dep_step:
                    dependency_names.append(dep_step.refinement_aspect.name)
            
            # Add dimension detail
            dimension_details.append({
                "name": step.refinement_aspect.name,
                "description": step.refinement_aspect.description or "",
                "status": status,
                "status_icon": status_icon,
                "is_active": step == active,
                "follow_up_count": step.follow_up_count,
                "assembled_value": assembled_value,
                "was_skipped": step.was_skipped,
                "conversation_history": step.conversation_history,
                "depends_on": dependency_names,
            })
        
        # Enhanced summary with additional metrics
        enhanced_summary = {
            **summary,
            "completed_steps": summary['completed'],
            "pending_steps": remaining_count,
            "dimensions": dimension_details,
        }
        
        return {
            "success": True,
            "message": "\n".join(status_lines),
            "summary": enhanced_summary,
            "active_step": active,
        }
    
    def list_steps(self) -> Dict[str, Any]:
        """List processed steps with their status."""
        active = self.session.get_active_step()
        
        total_aspects = len(self.session.refinement_framework)
        processed_count = len(self.session.steps)
        
        lines = [f"Processed Steps ({processed_count}/{total_aspects} total refinement dimensions):"]
        for i, step in enumerate(self.session.steps, 1):
            if step.was_skipped:
                status = "skipped"
            elif step.is_complete:
                status = "completed"
            elif step == active:
                status = "active"
            else:
                status = "in progress"
            
            followups = f" ({step.follow_up_count} follow-ups)" if step.follow_up_count > 0 else ""
            lines.append(f"  {i}. [{status}] {step.refinement_aspect.name}{followups}")
        
        if processed_count < total_aspects:
            lines.append(f"\n  ... {total_aspects - processed_count} more refinement dimension(s) will be generated on-demand")
        
        return {
            "success": True,
            "message": "\n".join(lines),
            "steps": self.session.steps,
        }
