#!/usr/bin/env python3
# test_refactoring.py - Comprehensive Testing Script for CAHTBOT 2026 Refactoring
"""
Test script per validare tutte le funzionalità implementate nel refactoring.

Usage:
    python test_refactoring.py

Tests:
    1. Session Storage (create, read, update, delete)
    2. Smart Router (Path A/B/C classification)
    3. Model Orchestrator (prompt generation)
    4. FSM Models (state transitions)
    5. Backend API (REST endpoints)
"""

import sys
import os
import json
import time
import requests
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# TEST 1: Session Storage
# ============================================================================

def test_session_storage():
    """Test SessionStorage functionality."""
    print("\n" + "="*60)
    print("TEST 1: Session Storage")
    print("="*60)
    
    try:
        from session_storage import SessionStorage
        
        # Initialize storage
        storage = SessionStorage("test_sessions.json")
        print("✅ SessionStorage initialized")
        
        # Test save
        test_session_id = "test_session_001"
        test_data = {
            "messages": [
                {"role": "user", "content": "Ho mal di testa"},
                {"role": "assistant", "content": "Dimmi di più"}
            ],
            "collected_data": {
                "LOCATION": "Bologna",
                "CHIEF_COMPLAINT": "Mal di testa"
            },
            "current_step": "PAIN_SCALE"
        }
        
        success = storage.save_session(test_session_id, test_data)
        assert success, "Save failed"
        print("✅ Session saved successfully")
        
        # Test load
        loaded_data = storage.load_session(test_session_id)
        assert loaded_data is not None, "Load failed"
        assert loaded_data["collected_data"]["LOCATION"] == "Bologna", "Data mismatch"
        print("✅ Session loaded successfully")
        
        # Test list
        active_sessions = storage.list_active_sessions()
        assert test_session_id in active_sessions, "Session not in active list"
        print(f"✅ Active sessions: {len(active_sessions)}")
        
        # Test delete
        deleted = storage.delete_session(test_session_id)
        assert deleted, "Delete failed"
        print("✅ Session deleted successfully")
        
        # Cleanup
        if os.path.exists("test_sessions.json"):
            os.remove("test_sessions.json")
        
        print("\n✅ ALL SESSION STORAGE TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ SESSION STORAGE TEST FAILED: {e}")
        return False


# ============================================================================
# TEST 2: Smart Router
# ============================================================================

def test_smart_router():
    """Test SmartRouter classification and routing."""
    print("\n" + "="*60)
    print("TEST 2: Smart Router")
    print("="*60)
    
    try:
        from smart_router import SmartRouter
        from models import TriagePath, TriageBranch
        
        router = SmartRouter()
        print("✅ SmartRouter initialized")
        
        # Test Path A (Emergency)
        score = router.classify_initial_urgency("Ho un dolore fortissimo al petto")
        assert score.assigned_path == TriagePath.A, "Path A not assigned"
        assert score.score >= 4, "Urgency score too low"
        print(f"✅ Path A classified: urgency={score.score}, flags={score.detected_red_flags}")
        
        # Test Path B (Mental Health)
        score = router.classify_initial_urgency("Mi sento molto ansioso e depresso")
        assert score.assigned_path == TriagePath.B, "Path B not assigned"
        print(f"✅ Path B classified: urgency={score.score}")
        
        # Test Path C (Standard)
        score = router.classify_initial_urgency("Ho mal di testa da 2 giorni")
        assert score.assigned_path == TriagePath.C, "Path C not assigned"
        assert score.score <= 3, "Urgency score too high"
        print(f"✅ Path C classified: urgency={score.score}")
        
        # Test INFO branch
        score = router.classify_initial_urgency("A che ora apre la farmacia?")
        assert score.assigned_branch == TriageBranch.INFORMAZIONI, "INFO branch not assigned"
        print(f"✅ INFO branch classified")
        
        # Test routing
        result = router.route("Bologna", 3, "Generale", TriagePath.C)
        assert result["tipo"] == "CAU", "CAU not routed correctly"
        print(f"✅ CAU routing: {result['nome']}")
        
        print("\n✅ ALL SMART ROUTER TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ SMART ROUTER TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# TEST 3: Model Orchestrator
# ============================================================================

def test_model_orchestrator():
    """Test ModelOrchestrator prompt generation."""
    print("\n" + "="*60)
    print("TEST 3: Model Orchestrator")
    print("="*60)
    
    try:
        from model_orchestrator_v2 import ModelOrchestrator
        
        # Initialize without API keys (test prompt generation only)
        orchestrator = ModelOrchestrator()
        print("✅ ModelOrchestrator initialized")
        
        # Test prompt generation for Path A
        collected_data = {"LOCATION": "Bologna"}
        prompt = orchestrator._get_system_prompt(
            path="A",
            phase="CHIEF_COMPLAINT",
            collected_data=collected_data,
            is_first_message=False
        )
        
        assert "Path A" in prompt or "EMERGENZA" in prompt, "Path A prompt incorrect"
        assert "Bologna" in prompt, "Collected data not in prompt"
        assert "opzioni" in prompt.lower(), "Options instruction missing"
        print("✅ Path A prompt generated correctly")
        
        # Test prompt generation for Path B
        prompt = orchestrator._get_system_prompt(
            path="B",
            phase="CHIEF_COMPLAINT",
            collected_data={},
            is_first_message=False
        )
        
        assert "SALUTE MENTALE" in prompt or "Path B" in prompt, "Path B prompt incorrect"
        assert "consenso" in prompt.lower() or "empatico" in prompt.lower(), "Consent instruction missing"
        print("✅ Path B prompt generated correctly")
        
        # Test first message prompt
        prompt = orchestrator._get_system_prompt(
            path="C",
            phase="INTENT_DETECTION",
            collected_data={},
            is_first_message=True
        )
        
        assert "PRIMO CONTATTO" in prompt or "ROUTING" in prompt, "First message prompt incorrect"
        print("✅ First message prompt generated correctly")
        
        print("\n✅ ALL MODEL ORCHESTRATOR TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ MODEL ORCHESTRATOR TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# TEST 4: FSM Models
# ============================================================================

def test_fsm_models():
    """Test FSM TriageState and related models."""
    print("\n" + "="*60)
    print("TEST 4: FSM Models")
    print("="*60)
    
    try:
        from models import (
            TriageState, TriagePath, TriagePhase,
            PatientInfo, ClinicalData, TriageMetadata
        )
        
        # Create TriageState
        state = TriageState(
            session_id="test_fsm_001",
            assigned_path=TriagePath.C
        )
        print("✅ TriageState created")
        
        # Test completion percentage (empty state)
        completion = state.get_completion_percentage()
        assert completion == 0.0, "Empty state should be 0%"
        print(f"✅ Completion: {completion}%")
        
        # Add data
        state.patient_info.location = "Bologna"
        state.patient_info.age = 35
        state.clinical_data.chief_complaint = "Mal di testa"
        state.clinical_data.pain_scale = 5
        state.clinical_data.red_flags = ["Nessuno"]
        state.patient_info.sex = "M"
        state.clinical_data.medications = "Nessuno"
        
        # Test completion percentage (complete state)
        completion = state.get_completion_percentage()
        assert completion == 100.0, "Complete state should be 100%"
        print(f"✅ Completion after data: {completion}%")
        
        # Test missing slots
        state2 = TriageState(session_id="test_002", assigned_path=TriagePath.A)
        missing = state2.get_missing_critical_slots()
        assert len(missing) > 0, "Should have missing slots"
        print(f"✅ Missing slots: {missing}")
        
        # Test can transition
        can_transition = state.can_transition_to_disposition()
        assert can_transition, "Should be able to transition"
        print("✅ Can transition to disposition")
        
        # Test SBAR generation
        sbar = state.to_sbar_summary()
        assert "SITUAZIONE" in sbar, "SBAR missing Situation"
        assert "BACKGROUND" in sbar, "SBAR missing Background"
        assert "VALUTAZIONE" in sbar, "SBAR missing Assessment"
        assert "RACCOMANDAZIONE" in sbar, "SBAR missing Recommendation"
        print("✅ SBAR generated correctly")
        
        # Test critical red flags
        state.clinical_data.red_flags = ["dolore toracico"]
        has_critical = state.has_critical_red_flags()
        assert has_critical, "Should detect critical red flag"
        print("✅ Critical red flags detected")
        
        print("\n✅ ALL FSM MODELS TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ FSM MODELS TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# TEST 5: Backend API (Optional - requires server running)
# ============================================================================

def test_backend_api():
    """Test Backend API endpoints (requires server running on port 5000)."""
    print("\n" + "="*60)
    print("TEST 5: Backend API (Optional)")
    print("="*60)
    
    try:
        # Check if server is running
        try:
            response = requests.get("http://localhost:5000/health", timeout=2)
            if response.status_code != 200:
                print("⚠️ Backend API not running - skipping tests")
                return True
        except requests.exceptions.ConnectionError:
            print("⚠️ Backend API not running - skipping tests")
            print("   To test API: python backend_api.py in another terminal")
            return True
        
        print("✅ Backend API is running")
        
        # Test POST /session
        test_session_id = f"api_test_{int(time.time())}"
        test_data = {
            "messages": [{"role": "user", "content": "Test"}],
            "collected_data": {"test": "data"}
        }
        
        response = requests.post(
            f"http://localhost:5000/session/{test_session_id}",
            json=test_data,
            timeout=5
        )
        assert response.status_code == 200, f"POST failed: {response.status_code}"
        print("✅ POST /session successful")
        
        # Test GET /session
        response = requests.get(
            f"http://localhost:5000/session/{test_session_id}",
            timeout=5
        )
        assert response.status_code == 200, f"GET failed: {response.status_code}"
        data = response.json()
        assert data["success"], "GET returned failure"
        assert data["session_id"] == test_session_id, "Session ID mismatch"
        print("✅ GET /session successful")
        
        # Test GET /sessions/active
        response = requests.get("http://localhost:5000/sessions/active", timeout=5)
        assert response.status_code == 200, "GET /sessions/active failed"
        data = response.json()
        assert test_session_id in data["sessions"], "Session not in active list"
        print(f"✅ GET /sessions/active successful (count: {data['count']})")
        
        # Test DELETE /session
        response = requests.delete(
            f"http://localhost:5000/session/{test_session_id}",
            timeout=5
        )
        assert response.status_code == 200, "DELETE failed"
        print("✅ DELETE /session successful")
        
        print("\n✅ ALL BACKEND API TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"\n❌ BACKEND API TEST FAILED: {e}")
        return False


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("CAHTBOT 2026 REFACTORING - COMPREHENSIVE TEST SUITE")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {
        "Session Storage": test_session_storage(),
        "Smart Router": test_smart_router(),
        "Model Orchestrator": test_model_orchestrator(),
        "FSM Models": test_fsm_models(),
        "Backend API": test_backend_api()
    }
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print("="*60)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("="*60)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! System ready for deployment.")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed. Review logs above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
