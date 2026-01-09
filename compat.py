# compat.py - Compatibility Layer for Gradual Migration
"""
Provides compatibility functions to bridge between legacy code and new FSM system.

This allows existing frontend.py and model_orchestrator_v2.py to work with
the new models.py while we gradually migrate functionality.
"""

from typing import Dict, Any, Optional
from models import (
    TriageState, TriageResponse, TriageMetadata, QuestionType,
    TriagePath, TriagePhase, TriageBranch
)
from bridge import TriageSessionBridge
from smart_router import SmartRouter
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

_bridge = TriageSessionBridge()
_router = SmartRouter()


# ============================================================================
# CONVERSION HELPERS
# ============================================================================

def dict_to_triage_state(session_data: Dict[str, Any], session_id: str = "default") -> TriageState:
    """
    Convert legacy session dict to TriageState.
    
    Args:
        session_data: Legacy collected_data dict
        session_id: Session ID
    
    Returns:
        TriageState object
    """
    return _bridge.convert_legacy_session_data({
        "session_id": session_id,
        **session_data
    })


def triage_state_to_dict(state: TriageState) -> Dict[str, Any]:
    """
    Convert TriageState back to legacy dict format.
    
    Args:
        state: TriageState object
    
    Returns:
        Dict compatible with legacy code
    """
    result = {
        "session_id": state.session_id,
        "current_phase": state.current_phase.value if state.current_phase else None,
        "assigned_path": state.assigned_path.value if state.assigned_path else None,
        "assigned_branch": state.assigned_branch.value if state.assigned_branch else None,
        "question_count": state.question_count,
        "consent_given": state.consent_given,
    }
    
    # Patient info
    if state.patient_info.location:
        result["LOCATION"] = state.patient_info.location
    if state.patient_info.age is not None:
        result["age"] = state.patient_info.age
    if state.patient_info.sex:
        result["sex"] = state.patient_info.sex
    if state.patient_info.pregnant is not None:
        result["pregnant"] = state.patient_info.pregnant
    
    # Clinical data
    if state.clinical_data.chief_complaint:
        result["CHIEF_COMPLAINT"] = state.clinical_data.chief_complaint
    if state.clinical_data.pain_scale is not None:
        result["PAIN_SCALE"] = state.clinical_data.pain_scale
    if state.clinical_data.red_flags:
        result["RED_FLAGS"] = state.clinical_data.red_flags
    if state.clinical_data.duration:
        result["duration"] = state.clinical_data.duration
    if state.clinical_data.medications:
        result["medications"] = state.clinical_data.medications
    if state.clinical_data.allergies:
        result["allergies"] = state.clinical_data.allergies
    if state.clinical_data.chronic_conditions:
        result["chronic_conditions"] = state.clinical_data.chronic_conditions
    
    # Metadata
    result["urgenza"] = state.metadata.urgenza
    result["area"] = state.metadata.area
    result["confidence"] = state.metadata.confidence
    
    # Disposition
    if state.disposition:
        result["DISPOSITION"] = {
            "type": state.disposition.type.value if hasattr(state.disposition.type, 'value') else state.disposition.type,
            "urgency": state.disposition.urgency,
            "facility_name": state.disposition.facility_name,
            "note": state.disposition.note,
            "distance_km": state.disposition.distance_km
        }
    
    return result


# ============================================================================
# HELPER FUNCTIONS FOR LEGACY CODE
# ============================================================================

def update_session_with_user_input(
    session_data: Dict[str, Any],
    user_input: str,
    session_id: str = "default"
) -> Dict[str, Any]:
    """
    Update session data with entities extracted from user input.
    
    This is the bridge function that legacy code can call.
    
    Args:
        session_data: Current session dict
        user_input: User's message
        session_id: Session ID
    
    Returns:
        Updated session dict
    """
    # Convert to TriageState
    state = dict_to_triage_state(session_data, session_id)
    
    # Extract entities from user input
    extracted = _bridge.extract_entities_from_text(user_input)
    
    # Sync with current state
    state = _bridge.sync_session_context(state, extracted)
    
    # Convert back to dict
    return triage_state_to_dict(state)


def get_next_question_for_path(
    session_data: Dict[str, Any],
    path: str = "C"
) -> Dict[str, Any]:
    """
    Determine what question to ask next based on path and current data.
    
    Args:
        session_data: Current session dict
        path: Path string ("A", "B", or "C")
    
    Returns:
        Dict with next_slot and prompt_message
    """
    # Convert path string to enum
    try:
        if path == "A":
            triage_path = TriagePath.A
        elif path == "B":
            triage_path = TriagePath.B
        else:
            triage_path = TriagePath.C
    except:
        triage_path = TriagePath.C
    
    # Create TriageState
    state = dict_to_triage_state(session_data, session_data.get("session_id", "default"))
    state.assigned_path = triage_path
    
    # Get next phase from router
    next_phase, prompt = _router.route_to_phase(state)
    
    return {
        "next_phase": next_phase.value,
        "prompt_message": prompt,
        "can_proceed_disposition": state.can_transition_to_disposition(),
        "completion_percentage": state.get_completion_percentage(),
        "missing_slots": state.get_missing_critical_slots()
    }


def validate_session_completeness(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate if session has enough data for disposition.
    
    Args:
        session_data: Current session dict
    
    Returns:
        Validation results dict
    """
    state = dict_to_triage_state(session_data, session_data.get("session_id", "default"))
    return _bridge.validate_triage_completeness(state)


def classify_user_intent(first_message: str) -> Dict[str, Any]:
    """
    Classify user intent from first message.
    
    Args:
        first_message: User's first message
    
    Returns:
        Classification results as dict
    """
    urgency_score = _router.classify_initial_urgency(first_message)
    
    return {
        "urgency": urgency_score.score,
        "assigned_path": urgency_score.assigned_path.value,
        "assigned_branch": urgency_score.assigned_branch.value,
        "rationale": urgency_score.rationale,
        "detected_red_flags": urgency_score.detected_red_flags,
        "requires_immediate_118": urgency_score.requires_immediate_118
    }


# ============================================================================
# EXPORT ALL
# ============================================================================

__all__ = [
    "dict_to_triage_state",
    "triage_state_to_dict",
    "update_session_with_user_input",
    "get_next_question_for_path",
    "validate_session_completeness",
    "classify_user_intent"
]
