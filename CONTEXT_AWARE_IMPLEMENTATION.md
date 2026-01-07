# Context-Aware Triage System - Implementation Guide

## Overview

This document describes the context-aware triage system implementation that eliminates redundant questions and maintains conversation state throughout the clinical triage process.

## Problem Addressed

### Before Implementation
- **Amnesia**: AI repeatedly asked for information already provided by users
- **Poor UX**: Users had to answer "Valuta il dolore 1-10" multiple times
- **No Context**: Each AI response was independent, ignoring conversation history
- **Manual Flow**: Required explicit button clicks to advance through steps

### After Implementation
- **Zero Redundancy**: AI never re-asks for provided information
- **Context Awareness**: AI knows what's already been collected
- **Smart Slot Filling**: Guides conversation through triage protocol
- **Auto-Advancement**: Automatically progresses when data is complete

## Architecture Changes

### Data Flow

```
User Input
    ↓
Frontend (maintains collected_data)
    ↓
Bridge (forwards collected_data)
    ↓
Orchestrator (builds contextual prompt)
    ↓
AI Model (context-aware generation)
    ↓
Response (with dati_estratti)
    ↓
Frontend (updates collected_data)
```

## Key Components

### 1. Enhanced Data Models (`models.py`)

```python
class TriageResponse(BaseModel):
    testo: str
    tipo_domanda: QuestionType
    opzioni: Optional[List[str]]
    metadata: TriageMetadata
    sbar: Optional[SBARReport]
    
    # NEW FIELDS
    fase_corrente: Optional[str]        # Current triage phase
    dati_estratti: Dict[str, Any]       # Multi-slot extraction
```

**Purpose**: Support context awareness and multi-slot extraction

### 2. Bridge Layer (`bridge.py`)

```python
def stream_ai_response(orchestrator, messages, path, phase, 
                      collected_data=None):
    # Validates and forwards collected_data to orchestrator
```

**Purpose**: Thread context through the application layers

### 3. Context-Aware Orchestrator (`model_orchestrator_v2.py`)

#### _build_context_section()
Formats collected data into readable context:
```
DATI GIÀ RACCOLTI (NON CHIEDERE NUOVAMENTE):
  - Comune: Bologna
  - Dolore: 7/10
  - Età: 35 anni
```

#### _determine_next_slot()
Follows triage protocol order:
1. LOCATION (Comune)
2. CHIEF_COMPLAINT (Sintomo principale)
3. PAIN_SCALE (Intensità dolore)
4. RED_FLAGS (Sintomi gravi)
5. ANAMNESIS (Età, farmaci)
6. DISPOSITION (Raccomandazione finale)

#### _check_emergency_triggers()
Real-time emergency detection:
- **RED**: Dolore toracico, difficoltà respiratoria → 118
- **ORANGE**: Trauma cranico, febbre alta → PS entro 2h
- **BLACK**: Ideazione suicidaria → Hotline psichiatrica
- **GREEN**: Normal triage flow

#### _get_system_prompt()
Generates dynamic prompts with:
- Already collected data (to prevent re-asking)
- Next required information
- Updated JSON schema with new fields

### 4. Frontend (`frontend.py`)

#### Updated AI Call
```python
res_gen = stream_ai_response(
    orchestrator,
    st.session_state.messages,
    path,
    phase_id,
    collected_data=st.session_state.collected_data  # NEW
)
```

#### Data Extraction
```python
dati_estratti = final_obj.get("dati_estratti", {})
for key, value in dati_estratti.items():
    st.session_state.collected_data[key] = value
```

#### Auto-Advancement
```python
def auto_advance_if_ready():
    """Advance when all required fields for current step are collected"""
    requirements = {
        TriageStep.LOCATION: ['LOCATION'],
        TriageStep.CHIEF_COMPLAINT: ['CHIEF_COMPLAINT'],
        TriageStep.PAIN_SCALE: ['PAIN_SCALE'],
        # ...
    }
    if all fields present:
        advance_step()
```

### 5. Emergency Detection (`smart_router.py`)

```python
def detect_emergency_keywords(user_message: str) -> str:
    """
    Returns: "RED" | "ORANGE" | "BLACK" | "GREEN"
    """
    # Checks message against predefined keyword lists
```

## Usage Examples

### Example 1: Multi-Slot Extraction

**User Input**: "Ho 35 anni e mi fa male la pancia da ieri, dolore 7/10"

**AI Processing**:
1. Extracts: `age=35`, `CHIEF_COMPLAINT="mal di pancia"`, `PAIN_SCALE=7`
2. Updates `collected_data` with all three values
3. Checks next slot: `LOCATION` is missing
4. Asks: "In che comune ti trovi?"

**Result**: One rich user input fills multiple slots

### Example 2: Context Awareness

**Conversation Flow**:
```
User: "Dolore 6/10"
AI: [Saves PAIN_SCALE=6]

Later in conversation...
AI: "Quando è iniziato il dolore?"  ✅ NEW QUESTION
NOT: "Valuta il dolore 1-10"  ❌ NEVER REPEATS
```

**How**: System prompt includes:
```
DATI GIÀ RACCOLTI:
  - Dolore: 6/10
```

### Example 3: Emergency Override

**User Input**: "non riesco a respirare, dolore toracico"

**AI Processing**:
1. `_check_emergency_triggers()` detects "dolore toracico"
2. Returns immediate emergency response
3. Bypasses normal triage flow
4. Response: "🚨 Rilevata possibile emergenza. Chiama immediatamente il 118."

**Result**: Critical situations handled immediately

## Testing

### Test Suite (`test_context_aware.py`)

15 tests covering:

1. **Context Awareness** (5 tests)
   - Empty context handling
   - Context with data
   - Slot determination logic
   - Progression through protocol
   - Disposition phase

2. **Emergency Detection** (5 tests)
   - RED level (medical emergency)
   - ORANGE level (urgent)
   - BLACK level (psychiatric)
   - GREEN level (normal)
   - Orchestrator integration

3. **Model Validation** (2 tests)
   - New fields handling
   - Optional fields

4. **Prompt Generation** (3 tests)
   - Includes collected data
   - Includes next slot
   - Includes new JSON fields

### Running Tests

```bash
python3 test_context_aware.py
```

Expected output:
```
✅ ALL TESTS PASSED (15/15)
```

## Configuration

No additional configuration required. The system uses existing:
- `st.session_state.collected_data` (already present)
- `st.session_state.current_step` (already present)
- Existing triage step enums

## Backward Compatibility

- All new fields are optional (defaults provided)
- Existing code continues to work
- No breaking changes to API signatures (only additions)
- Fallback behavior if `collected_data` not provided

## Performance Impact

- **Minimal**: Context building is O(n) where n = number of collected fields (typically < 10)
- **Logging**: Additional debug logs for tracing context flow
- **Memory**: Negligible (collected_data already in session state)

## Security Considerations

- No new user input accepted (uses existing validated data)
- Emergency keywords carefully chosen (clinical guidelines)
- No sensitive data logged (only keys, not values)
- CodeQL analysis: 0 vulnerabilities found

## Maintenance

### Adding New Slots

1. Add to `_determine_next_slot()` priority order
2. Add to `auto_advance_if_ready()` requirements map
3. Add to `_build_context_section()` for formatting
4. Update tests

### Adding Emergency Keywords

1. Add to appropriate level in `detect_emergency_keywords()`
2. Add to `_check_emergency_triggers()` in orchestrator
3. Add test case

### Debugging

Enable verbose logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Look for:
- `collected_data_keys=` in bridge logs
- `DATI GIÀ RACCOLTI` in prompt generation
- `Dato estratto automaticamente:` in frontend logs

## Future Enhancements

Potential improvements:
1. **Machine Learning**: Train model to extract slots more reliably
2. **Fuzzy Matching**: Handle typos in user input better
3. **Confidence Scores**: Rate quality of extracted data
4. **Analytics**: Track which slots require most clarification
5. **Multilingual**: Extend to other languages

## Conclusion

This implementation transforms the chatbot from a generic Q&A system into a professional clinical triage engine that:
- ✅ Eliminates redundant questions
- ✅ Maintains conversation context
- ✅ Follows clinical protocols
- ✅ Handles emergencies intelligently
- ✅ Provides seamless user experience

**Zero Amnesia. Zero Redundancy. Professional Clinical Triage.**
