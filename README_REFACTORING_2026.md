# CAHTBOT.ALPHA - Refactoring 2026

## Panoramica del Sistema

Sistema di triage dinamico basato su FSM (Finite State Machine) con percorsi differenziati A/B/C, persistenza cross-istanza e routing territoriale Emilia-Romagna 2026.

## Architettura

### Frontend (Streamlit)
- **File**: `frontend.py`
- **Funzionalità**:
  - Interfaccia chat con opzioni A/B/C dinamiche
  - Session storage persistence
  - Auto-sync ogni 10 secondi
  - Support query params: `?session_id=xxx`
  - TTS (Text-to-Speech) integrato
  - Emergency overlays (RED/ORANGE/BLACK)

### Backend API (Flask)
- **File**: `backend_api.py`
- **Porta**: 5000
- **Endpoints**:
  - `GET /session/<id>` - Recupera sessione
  - `POST /session/<id>` - Aggiorna sessione
  - `DELETE /session/<id>` - Elimina sessione
  - `GET /sessions/active` - Lista sessioni attive
  - `POST /sessions/cleanup` - Pulizia automatica

### Session Storage
- **File**: `session_storage.py`
- **Storage**: `sessions.json` (file-based)
- **Features**:
  - Thread-safe operations
  - Atomic writes
  - Auto-cleanup >24h
  - Cross-instance sync

### AI Orchestrator
- **File**: `model_orchestrator_v2.py`
- **Modelli**:
  - Primary: Groq (llama-3.3-70b-versatile)
  - Fallback: Gemini 2.0 Flash
- **Features**:
  - Formato A/B/C obbligatorio
  - Path-specific prompts (A/B/C)
  - Emergency detection
  - Slot filling automatico

### Smart Router
- **File**: `smart_router.py`
- **Features**:
  - Classificazione urgenza iniziale (1-5)
  - Path assignment (A/B/C)
  - Routing gerarchico 2026:
    - Urgenza 5: 118 immediato
    - Urgenza 4: Pronto Soccorso
    - Urgenza 3: CAU h24 potenziato
    - Urgenza 2: Servizi specialistici > CAU
    - Urgenza 1: Telemedicina > MMG

### FSM Models
- **File**: `models.py`
- **Enums**:
  - `TriagePath`: A (Emergenza), B (Salute Mentale), C (Standard)
  - `TriagePhase`: INTENT_DETECTION, LOCATION, CHIEF_COMPLAINT, etc.
  - `TriageBranch`: TRIAGE, INFORMAZIONI
- **Models**:
  - `TriageState`: Stato principale FSM
  - `PatientInfo`: Dati anagrafici
  - `ClinicalData`: Dati clinici
  - `DispositionRecommendation`: Output finale

### Bridge
- **File**: `bridge.py`
- **Features**:
  - Entity extraction (regex-based)
  - State synchronization
  - Data validation
  - Legacy compatibility

## Percorsi di Triage

### Percorso A: EMERGENZA (Max 3 domande)
1. LOCATION: Comune (testo libero)
2. CHIEF_COMPLAINT: Sintomo con opzioni A/B/C
3. RED_FLAGS: Una domanda critica
4. DISPOSITION: Raccomandazione immediata

**Skip**: Anamnesi completa

### Percorso B: SALUTE MENTALE (Con consenso)
1. Consenso per domande personali
2. LOCATION: Comune
3. DEMOGRAPHICS: Età (per CSM/NPIA)
4. CHIEF_COMPLAINT: Natura del disagio
5. Risk assessment (autolesionismo)
6. DISPOSITION: CSM/Consultorio/MMG

**Hotline**: 1522, Telefono Amico 02 2327 2327

### Percorso C: STANDARD (Protocollo completo)
1. LOCATION: Comune
2. CHIEF_COMPLAINT: Sintomo con opzioni A/B/C
3. PAIN_SCALE: 1-10 con descrittori
4. RED_FLAGS: Opzioni A/B/C
5. ANAMNESIS: Età, sesso, gravidanza, farmaci
6. DISPOSITION: Raccomandazione + SBAR

## Routing Territoriale 2026

### Novità CAU (Continuità Assistenziale Urgenze)
- **H24**: Apertura continua
- **Diagnostici**: ECG, radiologia base
- **Telemedicina**: Consultazioni remote
- **Numero Unico**: 116117
- **App**: ER Salute

### Gerarchia Routing
```
Urgenza 5 → 118 Immediato
Urgenza 4 → Pronto Soccorso
Urgenza 3 → CAU h24
Urgenza 2 → Servizi Specialistici > CAU
            - Poliambulatori (medicazioni, prelievi)
            - Consultori (salute donna, giovani)
            - SerD (dipendenze)
            - CSM (salute mentale)
Urgenza 1 → Telemedicina > MMG
```

## Output SBAR

### Formato Strutturato
```
S (Situation): Sintomo principale + intensità
B (Background): Età, sesso, localizzazione, anamnesi
A (Assessment): Red flags, urgenza
R (Recommendation): Struttura consigliata + motivazione
```

### Pulsanti d'Azione (In Sviluppo)
- 📧 Invia al mio Medico
- 📞 Chiama Struttura
- 🗺️ Mappa per il PS

## Installazione

```bash
# Clone repository
git clone https://github.com/sebadonati7/CAHTBOT.ALPHA.git
cd CAHTBOT.ALPHA

# Install dependencies
pip install -r requirements.txt

# Configure secrets
# Create .streamlit/secrets.toml with:
# GROQ_API_KEY = "your-key"
# GEMINI_API_KEY = "your-key"
```

## Utilizzo

### Opzione 1: Solo Frontend (File-based storage)
```bash
streamlit run frontend.py
```

### Opzione 2: Frontend + Backend API (Recommended)
```bash
# Terminal 1: Start backend API
python backend_api.py

# Terminal 2: Start frontend
streamlit run frontend.py
```

### Opzione 3: Windows Batch (avvia_tutto.bat)
```batch
start python backend_api.py
timeout /t 3
start streamlit run frontend.py
```

## Testing

### Test Path A (Emergenza)
```
Utente: "Ho un dolore fortissimo al petto"
→ Path A assegnato
→ Max 3 domande
→ Raccomandazione: PS o 118
```

### Test Path B (Salute Mentale)
```
Utente: "Mi sento molto ansioso"
→ Path B assegnato
→ Richiesta consenso
→ Età → Tipologia disagio
→ Raccomandazione: CSM/Consultorio
```

### Test Path C (Standard)
```
Utente: "Ho mal di testa da 2 giorni"
→ Path C assegnato
→ 7 fasi complete
→ SBAR report finale
```

## Persistenza Cross-Istanza

### Scenario: Utente cambia dispositivo

1. **Dispositivo 1** (Desktop):
   - Inizia triage
   - Session ID: `abc-123-def`
   - URL: `http://localhost:8501?session_id=abc-123-def`

2. **Copia URL** e apri su **Dispositivo 2** (Mobile)

3. **Dispositivo 2** (Mobile):
   - Carica automaticamente da SessionStorage
   - Continua triage dallo stesso punto
   - Messaggi sincronizzati

### Auto-Sync
- Ogni 10 secondi (throttling)
- Dopo ogni messaggio AI
- Durante save_structured_log

## Configurazione

### Secrets (`.streamlit/secrets.toml`)
```toml
GROQ_API_KEY = "gsk_..."
GEMINI_API_KEY = "AI..."
BACKEND_URL = "http://localhost:5000"
BACKEND_API_KEY = "optional-key"
```

### Storage (`sessions.json`)
```json
{
  "session-id-123": {
    "timestamp_last_update": "2026-01-09T13:00:00",
    "messages": [...],
    "collected_data": {...},
    "current_step": "CHIEF_COMPLAINT",
    "triage_state": {...}
  }
}
```

## Sicurezza

### Privacy
- GDPR consent obbligatorio
- No dati sensibili in log pubblici
- Encryption in transito (HTTPS)

### Sanitization
- Input sanitization (XSS prevention)
- JSON validation
- SQL injection prevention (N/A - file-based)

### Diagnosis Prevention
- NO diagnosi mediche
- NO prescrizioni
- Tone assistenziale: "potrebbe essere opportuno..."

## Performance

### Throttling
- Session sync: max 1/10s
- AI requests: timeout 60s
- Storage cleanup: automatico (>24h)

### Caching
- Knowledge base: caricato una volta
- Orchestrator: singleton pattern
- Storage: in-memory + file persistence

## Monitoring

### Logs
- `triage_logs.jsonl`: Analytics strutturati
- `sessions.json`: State persistence
- Console: INFO level

### Analytics Dashboard
```bash
streamlit run backend.py
```

Features:
- KPI strategici (10 metriche)
- Afflusso orario per area clinica
- EPI (Estimated Pressure Index)
- Funnel analysis
- Export Excel

## Roadmap

### Q1 2026
- [x] Session persistence
- [x] A/B/C dynamic options
- [x] CAU 2026 routing
- [x] SBAR output
- [ ] Cross-instance testing
- [ ] Firestore integration (optional)

### Q2 2026
- [ ] Handover clinico attivo
- [ ] Integrazione MMG
- [ ] App ER Salute sync
- [ ] Telemedicina diretta

### Q3 2026
- [ ] ML predictions urgenza
- [ ] NLP avanzato
- [ ] Voice input
- [ ] Multi-lingua

## Troubleshooting

### Session non caricata
```bash
# Verifica sessions.json
cat sessions.json | python -m json.tool

# Reset storage
rm sessions.json
```

### AI non risponde
```bash
# Verifica chiavi API
python -c "import streamlit as st; print(st.secrets.get('GROQ_API_KEY'))"

# Test Groq
curl -H "Authorization: Bearer gsk_..." https://api.groq.com/openai/v1/models
```

### Backend API non risponde
```bash
# Verifica porta 5000
lsof -i :5000
netstat -an | grep 5000

# Test health
curl http://localhost:5000/health
```

## Contributi

### Code Style
- PEP 8 per Python
- Type hints obbligatori
- Docstrings Google style

### Testing
```bash
pytest tests/
python -m unittest discover
```

### Pull Requests
1. Fork repository
2. Create feature branch
3. Implement + test
4. Update documentation
5. Submit PR

## Licenza

Proprietario - Regione Emilia-Romagna 2026

## Contatti

- **Developer**: sebadonati7
- **Issue Tracker**: GitHub Issues
- **Documentation**: README.md + inline docs

## Versioning

- **Current**: 2026.1.0
- **Schema**: ANNO.MAJOR.MINOR
- **Release**: Gennaio 2026

---

**NOTA IMPORTANTE**: Questo sistema è un assistente digitale e NON sostituisce il parere medico. In caso di emergenza reale, chiamare sempre il 118.
