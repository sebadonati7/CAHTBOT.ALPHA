#!/usr/bin/env python3
"""
Test suite for context-aware triage system.

Tests the key functionality:
1. Context injection into prompts
2. Slot determination logic  
3. Emergency detection
4. Data extraction from responses
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock streamlit before importing other modules
sys.modules['streamlit'] = MagicMock()

# Import modules to test
from models import TriageResponse, TriageMetadata, QuestionType
from model_orchestrator_v2 import ModelOrchestrator
from smart_router import detect_emergency_keywords


class TestContextAwareness(unittest.TestCase):
    """Test that collected_data prevents redundant questions"""
    
    def setUp(self):
        self.orchestrator = ModelOrchestrator(groq_key="", gemini_key="")
    
    def test_build_context_section_empty(self):
        """Test context building with no collected data"""
        context = self.orchestrator._build_context_section({})
        self.assertIn("Nessuno", context)
    
    def test_build_context_section_with_data(self):
        """Test context building with collected data"""
        collected = {
            'LOCATION': 'Bologna',
            'PAIN_SCALE': 7,
            'age': 35
        }
        context = self.orchestrator._build_context_section(collected)
        
        self.assertIn("Bologna", context)
        self.assertIn("7/10", context)
        self.assertIn("35 anni", context)
        self.assertNotIn("Nessuno", context)
    
    def test_determine_next_slot_location_first(self):
        """Test that location is requested first"""
        next_slot = self.orchestrator._determine_next_slot({}, "INITIAL")
        self.assertIn("Comune", next_slot)
    
    def test_determine_next_slot_progression(self):
        """Test slot progression follows protocol"""
        # After location, should ask for chief complaint
        collected = {'LOCATION': 'Bologna'}
        next_slot = self.orchestrator._determine_next_slot(collected, "CHIEF_COMPLAINT")
        self.assertIn("Sintomo", next_slot)
        
        # After complaint, should ask for pain scale
        collected['CHIEF_COMPLAINT'] = 'mal di testa'
        next_slot = self.orchestrator._determine_next_slot(collected, "PAIN_SCALE")
        self.assertIn("dolore", next_slot.lower())
        
        # After pain, should ask for red flags
        collected['PAIN_SCALE'] = 6
        next_slot = self.orchestrator._determine_next_slot(collected, "RED_FLAGS")
        self.assertIn("sintomi gravi", next_slot.lower())
    
    def test_determine_next_slot_disposition(self):
        """Test disposition phase triggers final recommendation"""
        collected = {
            'LOCATION': 'Bologna',
            'CHIEF_COMPLAINT': 'mal di testa',
            'PAIN_SCALE': 6,
            'RED_FLAGS': 'no',
            'age': 35
        }
        next_slot = self.orchestrator._determine_next_slot(collected, "DISPOSITION")
        self.assertIn("FINALE", next_slot.upper())


class TestEmergencyDetection(unittest.TestCase):
    """Test emergency keyword detection"""
    
    def test_detect_red_emergency(self):
        """Test RED level emergency detection"""
        messages = [
            "ho un dolore toracico intenso",
            "non riesco a respirare",
            "ho avuto una perdita di coscienza"
        ]
        
        for msg in messages:
            level = detect_emergency_keywords(msg)
            self.assertEqual(level, "RED", f"Failed for: {msg}")
    
    def test_detect_black_emergency(self):
        """Test BLACK level (psychiatric) emergency detection"""
        messages = [
            "voglio farla finita",
            "non voglio più vivere",
            "pensieri di suicidio"
        ]
        
        for msg in messages:
            level = detect_emergency_keywords(msg)
            self.assertEqual(level, "BLACK", f"Failed for: {msg}")
    
    def test_detect_orange_emergency(self):
        """Test ORANGE level (urgent) detection"""
        messages = [
            "dolore addominale acuto",
            "trauma cranico forte",
            "febbre 40 gradi"
        ]
        
        for msg in messages:
            level = detect_emergency_keywords(msg)
            self.assertEqual(level, "ORANGE", f"Failed for: {msg}")
    
    def test_detect_green_no_emergency(self):
        """Test GREEN level (no emergency)"""
        messages = [
            "ho un leggero mal di testa",
            "mi sento un po' stanco",
            "ho il raffreddore"
        ]
        
        for msg in messages:
            level = detect_emergency_keywords(msg)
            self.assertEqual(level, "GREEN", f"Failed for: {msg}")
    
    def test_orchestrator_emergency_override(self):
        """Test that orchestrator detects emergencies"""
        orchestrator = ModelOrchestrator(groq_key="", gemini_key="")
        
        emergency = orchestrator._check_emergency_triggers(
            "ho un dolore toracico forte", 
            {}
        )
        
        self.assertIsNotNone(emergency)
        self.assertIn("118", emergency['testo'])
        self.assertEqual(emergency['metadata']['urgenza'], 5)


class TestTriageResponseModel(unittest.TestCase):
    """Test enhanced TriageResponse model"""
    
    def test_triage_response_with_new_fields(self):
        """Test that new fields are properly handled"""
        response = TriageResponse(
            testo="In che comune ti trovi?",
            tipo_domanda=QuestionType.TEXT,
            metadata=TriageMetadata(
                urgenza=3,
                area="Generale",
                confidence=0.8
            ),
            fase_corrente="LOCATION",
            dati_estratti={"age": 35, "PAIN_SCALE": 7}
        )
        
        self.assertEqual(response.fase_corrente, "LOCATION")
        self.assertEqual(response.dati_estratti['age'], 35)
        self.assertEqual(response.dati_estratti['PAIN_SCALE'], 7)
    
    def test_triage_response_optional_new_fields(self):
        """Test that new fields are optional"""
        response = TriageResponse(
            testo="Come posso aiutarti?",
            tipo_domanda=QuestionType.TEXT,
            metadata=TriageMetadata(
                urgenza=3,
                area="Generale",
                confidence=0.8
            )
        )
        
        self.assertIsNone(response.fase_corrente)
        self.assertEqual(response.dati_estratti, {})


class TestSystemPromptGeneration(unittest.TestCase):
    """Test dynamic system prompt generation"""
    
    def setUp(self):
        self.orchestrator = ModelOrchestrator(groq_key="", gemini_key="")
    
    def test_prompt_includes_collected_data(self):
        """Test that prompt includes already collected data"""
        collected = {
            'LOCATION': 'Bologna',
            'PAIN_SCALE': 7
        }
        
        prompt = self.orchestrator._get_system_prompt('C', 'CHIEF_COMPLAINT', collected)
        
        self.assertIn("Bologna", prompt)
        self.assertIn("7/10", prompt)
        self.assertIn("NON CHIEDERE NUOVAMENTE", prompt)
    
    def test_prompt_includes_next_slot(self):
        """Test that prompt indicates next information to collect"""
        collected = {'LOCATION': 'Bologna'}
        
        prompt = self.orchestrator._get_system_prompt('C', 'CHIEF_COMPLAINT', collected)
        
        self.assertIn("PROSSIMA INFORMAZIONE", prompt)
        self.assertIn("Sintomo", prompt)
    
    def test_prompt_includes_fase_corrente(self):
        """Test that prompt includes fase_corrente in JSON schema"""
        prompt = self.orchestrator._get_system_prompt('C', 'PAIN_SCALE', {})
        
        self.assertIn('"fase_corrente"', prompt)
        self.assertIn('"dati_estratti"', prompt)


def run_tests():
    """Run all tests"""
    print("=" * 60)
    print("🧪 Testing Context-Aware Triage System")
    print("=" * 60)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestContextAwareness))
    suite.addTests(loader.loadTestsFromTestCase(TestEmergencyDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestTriageResponseModel))
    suite.addTests(loader.loadTestsFromTestCase(TestSystemPromptGeneration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
