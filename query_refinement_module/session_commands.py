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
    
    def go_back(self) -> Dict[str, Any]:
        """Navigate to previous aspect, truncating all subsequent aspects."""
        active = self.session.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to go back from"}
        
        active_idx = self.session.steps.index(active)
        if active_idx == 0:
            return {"success": False, "message": "Already at first aspect. Use /restart to start over."}
        
        # Get previous step
        prev_step = self.session.steps[active_idx - 1]
        
        # Track what will be cleared (everything from current onward)
        cleared_aspects = [
            step.refinement_aspect.aspect_name 
            for step in self.session.steps[active_idx:]
        ]
        
        # Truncate session.steps - remove current and all subsequent aspects
        self.session.steps = self.session.steps[:active_idx]
        
        # Reopen the previous step
        prev_step.is_complete = False
        prev_step.needs_review = False
        
        message = f"Moved back to: {prev_step.refinement_aspect.aspect_name}"
        if cleared_aspects:
            message += f"\n⚠️  Cleared {len(cleared_aspects)} aspect(s): {', '.join(cleared_aspects)}"
            message += "\nThey will be regenerated based on your updated answers."
        
        return {
            "success": True,
            "message": message,
            "step_index": active_idx - 1,
            "step": prev_step,
            "cleared_aspects": cleared_aspects,
        }
    
    def restart(self) -> Dict[str, Any]:
        """Restart the entire refinement session, clearing all aspects."""
        # Track all aspects being cleared for DB cascade delete
        cleared_aspects = [
            step.refinement_aspect.aspect_name
            for step in self.session.steps
        ]
        cleared_count = len(self.session.steps)
        
        self.session.steps = []
        self.session.synthesis_requested = False
        
        return {
            "success": True,
            "message": f"Session restarted. All {cleared_count} aspect(s) cleared.",
            "cleared_aspects": cleared_aspects,
        }
    
    def skip_current(self) -> Dict[str, Any]:
        """Skip the current refinement aspect, clearing all data."""
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
            "message": f"Skipped: {active.refinement_aspect.aspect_name}.\nNo specifications from this dimension will be provided to dependent refinement dimensions.",
            "step": active,
        }
    
    def clear_current(self) -> Dict[str, Any]:
        """Clear current aspect's answers and restart it."""
        active = self.session.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to clear"}
        
        # Clear all data for current aspect
        active.conversation_history = []
        active.normalized_value = None
        active.is_complete = False
        active.was_skipped = False
        active.needs_review = False
        active.follow_up_question = None
        
        return {
            "success": True,
            "message": f"Cleared: {active.refinement_aspect.aspect_name}. Question will be regenerated.",
            "step": active,
            "regenerate_question": True,
        }
    
    def finish_current(self) -> Dict[str, Any]:
        """Finish the current step, preserving captured responses."""
        active = self.session.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to finish"}
        
        message = f"Completed refinement aspect: {active.refinement_aspect.aspect_name}"
        if not active.normalized_value:
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
        """Get current session status."""
        active = self.session.get_active_step()
        summary = self.session.get_step_summary()
        
        # Calculate remaining aspects
        total_aspects = len(self.session.refinement_framework)
        processed_count = len(self.session.steps)
        remaining_count = total_aspects - processed_count
        
        status_lines = [
            "Session Status:",
            f"  Processed: {summary['completed']}/{processed_count} complete",
            f"  Follow-ups asked: {summary['total_follow_ups']}",
        ]
        
        if active:
            active_idx = self.session.steps.index(active) + 1
            status_tag = " (needs review)" if active.needs_review else ""
            status_lines.append(f"  Current: Step {active_idx} - {active.refinement_aspect.aspect_name}{status_tag}")
        else:
            if processed_count == total_aspects:
                status_lines.append("  Current: All aspects processed")
            else:
                status_lines.append(f"  Current: Ready for next aspect ({remaining_count} remaining)")
        
        return {
            "success": True,
            "message": "\n".join(status_lines),
            "summary": summary,
            "active_step": active,
        }
    
    def list_steps(self) -> Dict[str, Any]:
        """List processed steps with their status."""
        active = self.session.get_active_step()
        
        total_aspects = len(self.session.refinement_framework)
        processed_count = len(self.session.steps)
        
        lines = [f"Processed Steps ({processed_count}/{total_aspects} total aspects):"]
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
            lines.append(f"  {i}. [{status}] {step.refinement_aspect.aspect_name}{followups}")
        
        if processed_count < total_aspects:
            lines.append(f"\n  ... {total_aspects - processed_count} more aspect(s) will be generated on-demand")
        
        return {
            "success": True,
            "message": "\n".join(lines),
            "steps": self.session.steps,
        }
