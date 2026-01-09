# CAHTBOT.ALPHA v2 - AI Health Navigator

## Architettura v2 (2026+)

Sistema di triage sanitario intelligente per l'Emilia-Romagna con architettura monolitica frontend e backend di reporting.

### Caratteristiche Principali

- **Fat Frontend**: Tutta la logica operativa centralizzata in `frontend.py`
- **Backend Sync**: Reporting e sorveglianza sanitaria con sincronizzazione automatica
- **Dynamic Time Management**: Gestione dinamica degli anni per compatibilità futura
- **District-Based Reporting**: Report per distretto sanitario ER
- **Secure API**: Autenticazione tramite API key per tutte le comunicazioni

## Struttura Architetturale

### Frontend (frontend.py)
- Orchestratore principale con FSM (Finite State Machine)
- Gestione completa del triage con 3 percorsi:
  - **Percorso A**: Emergenza (Red/Orange) - Max 3 domande
  - **Percorso B**: Salute Mentale (Black) - Con consenso formale
  - **Percorso C**: Standard (Green/Yellow) - Triage approfondito
- Integrazione con LLM (Gemini/Groq) via `model_orchestrator_v2.py`
- Smart routing verso strutture sanitarie ER
- Sync automatico al backend su completamento sessione

### Backend API (backend_api.py)
- REST API per sincronizzazione sessioni
- Endpoint `/triage/complete` per ricezione dati completati
- Autenticazione tramite `BACKEND_API_KEY`
- Storage JSONL per analisi e reporting

### Backend Analytics (backend.py)
- Dashboard analitica con Streamlit
- Report per distretto sanitario
- Export Excel con filtri temporali
- Analisi KPI e metriche cliniche

### Model Orchestrator (model_orchestrator_v2.py)
- Gestione LLM con fallback Groq → Gemini
- Normalizzazione sintomi integrata
- Sanitization automatica diagnosi
- Configurazione API key da `secrets.toml`

## Configurazione

### 1. Secrets Configuration

Crea il file `.streamlit/secrets.toml`:

```toml
# Google Gemini API
GEMINI_API_KEY = "your-gemini-api-key"

# Groq API (Fallback)
GROQ_API_KEY = "your-groq-api-key"

# Backend API
BACKEND_URL = "http://localhost:5000"
BACKEND_API_KEY = "your-secure-api-key"
```

### 2. Dipendenze

```bash
pip install -r requirements.txt
```

### 3. Avvio Sistema

**Backend API** (porta 5000):
```bash
python backend_api.py
```

**Frontend** (porta 8501):
```bash
streamlit run frontend.py
```

**Analytics Dashboard** (porta 8502):
```bash
streamlit run backend.py --server.port 8502
```

## Distretti Sanitari Emilia-Romagna

Il sistema supporta tutti i distretti sanitari dell'ER:

- **AUSL ROMAGNA**: Ravenna, Faenza, Lugo, Forlì, Cesena, Rubicone, Rimini, Riccione
- **AUSL BOLOGNA**: Bologna Città, Pianura Est, Pianura Ovest, Reno-Lavino-Samoggia, San Lazzaro, Appennino
- **AUSL IMOLA**: Imola
- **AUSL FERRARA**: Centro-Nord, Sud-Est, Ovest
- **AUSL MODENA**: Modena, Carpi, Mirandola, Sassuolo, Pavullo, Vignola, Castelfranco
- **AUSL REGGIO EMILIA**: Reggio Emilia, Guastalla, Correggio, Montecchio, Scandiano, Castelnovo ne' Monti
- **AUSL PARMA**: Parma, Fidenza, Sud-Est, Valli Taro e Ceno
- **AUSL PIACENZA**: Città di Piacenza, Levante, Ponente

## Flusso Operativo v2

1. **Triage Frontend**:
   - Utente interagisce con chatbot AI
   - Sistema classifica urgenza e percorso (A/B/C)
   - Raccolta dati con slot filling persistente
   - Generazione SBAR e raccomandazione

2. **Backend Sync**:
   - A fine sessione: POST a `/triage/complete`
   - Payload include: Log, SBAR, Distretto, Urgenza
   - Autenticazione via Bearer token
   - Storage su `triage_logs.jsonl`

3. **Analytics**:
   - Dashboard filtra per distretto e periodo
   - Generazione report Excel
   - KPI: tempo medio, conversioni, distribuzione urgenze

## API Endpoints

### POST /triage/complete
Riceve dati di sessione completata.

**Headers**:
```
Authorization: Bearer <BACKEND_API_KEY>
Content-Type: application/json
```

**Body**:
```json
{
  "session_id": "0001_090126",
  "timestamp": "2026-01-09T19:30:00Z",
  "comune": "Bologna",
  "distretto": "BOL-CIT",
  "path": "PERCORSO_C",
  "urgency": 3,
  "disposition": "CAU",
  "sbar": {
    "situation": "Cefalea intensa",
    "background": "Età: 45, Bologna",
    "assessment": "Nessun red flag",
    "recommendation": "CAU per valutazione"
  },
  "log": { ... }
}
```

**Response**:
```json
{
  "success": true,
  "session_id": "0001_090126",
  "message": "Triage data received and logged"
}
```

## Protocolli Triage

### Percorso A - Emergenza
- **Trigger**: Red flags critici (dolore toracico, dispnea grave, emorragia)
- **Fasi**: Location → Chief Complaint → Red Flags → Disposition
- **Output**: 118 immediato o PS + link affollamento
- **Tempo target**: < 2 minuti

### Percorso B - Salute Mentale
- **Trigger**: Keywords ansia, depressione, panico, autolesionismo
- **Fasi**: Consenso → Anamnesi dettagliata → Valutazione rischio
- **Output**: 118 (rischio alto) | CSM/NPIA/Consultorio (per età/distretto)
- **Privacy**: Dati non mostrati in chat, solo invio backend

### Percorso C - Standard
- **Trigger**: Tutti gli altri casi
- **Fasi**: Location → Chief Complaint → Pain Scale → Red Flags → Anamnesi → Disposition
- **Output**: Smart Routing (Specialistica → CAU → MMG)
- **Tempo target**: 3-5 minuti

## Single Question Policy

Il sistema segue rigorosamente la **Single Question Policy**:
- Una sola domanda alla volta
- Slot filling: dati raccolti non vengono richiesti nuovamente
- Opzioni A/B/C per scelte guidate
- Input ibrido: bottoni o testo libero

## Sicurezza

- ✅ API Key authentication su tutti gli endpoint sensibili
- ✅ Nessuna diagnosi medica (solo triage e routing)
- ✅ Sanitization automatica di risposte non conformi
- ✅ Privacy: dati sensibili non esposti in chat (Path B)
- ✅ Timeout e fallback per chiamate esterne

## Sviluppo e Testing

### Test Sintassi
```bash
python3 -m py_compile frontend.py backend_api.py backend.py model_orchestrator_v2.py
```

### Test Endpoint
```bash
curl -X POST http://localhost:5000/triage/complete \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test","comune":"Bologna","path":"PERCORSO_C"}'
```

## Versioning

- **v2.0**: Architettura monolitica + backend sync + district reporting
- **Dynamic Year**: Usa `datetime.now().year` - nessun hardcoding
- **Compatibilità**: 2026+

## Licenza

Proprietario - Emilia-Romagna Health System

## Supporto

Per issue e richieste: GitHub Issues