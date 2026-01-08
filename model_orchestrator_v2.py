# model_orchestrator_v2.py
import streamlit as st
import asyncio
import json
import logging
import re
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, AsyncGenerator, Union, Optional
from pydantic import ValidationError

from models import TriageResponse, TriageMetadata, QuestionType
from smart_router import SmartRouter

logger = logging.getLogger(__name__)


class DiagnosisSanitizer: 
    """Blocca diagnosi non autorizzate e prescrizioni farmacologiche."""
    FORBIDDEN_PATTERNS = [
        r"\bdiagnosi\b", r"\bprescrivo\b", r"\bterapia\b",
        r"\bhai\s+(la|il|un[\'a]? )\s+\w+",
        r"\bè\s+(sicuramente|probabilmente)\b",
        r"\bprendi\s+\w+\s+mg\b",
        r"\b(hai|sembra che tu abbia|potresti avere)\s+.*\b(infiammazione|infezione|patologia|malattia)\b"
    ]
    
    @staticmethod
    def sanitize(response: TriageResponse) -> TriageResponse:
        text_lower = response.testo.lower()
        for pattern in DiagnosisSanitizer.FORBIDDEN_PATTERNS:
            if re.search(pattern, text_lower):
                logging.critical(f"DIAGNOSI BLOCCATA: {response.testo}")
                response.testo = "In base ai dati raccolti, la situazione merita un approfondimento clinico.  Potresti descrivermi meglio da quanto tempo avverti questi sintomi?"
                response.metadata.confidence = 0.1
                break
        return response


class ModelOrchestrator:
    """
    Orchestratore AI con Fallback Groq -> Gemini. 
    Versione aggiornata per modelli 2025.
    """
    def __init__(self, groq_key: str = "", gemini_key: str = ""):
        self.groq_client = None
        self.gemini_model = None
        self._executor = ThreadPoolExecutor(max_workers=5)
        self.router = SmartRouter()
        self.prompts = self._load_prompts()
        
        g_key = groq_key or st.secrets.get("GROQ_API_KEY", "")
        gem_key = gemini_key or st.secrets.get("GEMINI_API_KEY", "")
        
        self.set_keys(groq=g_key, gemini=gem_key)
        atexit.register(self._cleanup)

    def set_keys(self, groq:  str = "", gemini: str = ""):
        """Configura o aggiorna le chiavi API in runtime."""
        try:
            if groq:
                from groq import AsyncGroq
                self.groq_client = AsyncGroq(api_key=groq)
                logging.info("Groq client initialized")
            
            if gemini: 
                import google.generativeai as genai
                genai.configure(api_key=gemini)
                self.gemini_model = genai.GenerativeModel("gemini-2.0-flash-exp")
                logging.info("Gemini model initialized (gemini-2.0-flash-exp)")
        except Exception as e:
            logging.error(f"Errore configurazione chiavi: {e}")

    def _cleanup(self):
        if hasattr(self, '_executor'):
            self._executor. shutdown(wait=False)

    def _load_prompts(self) -> Dict[str, str]:
        return {
            "base_rules":  (
                "Sei l'AI Health Navigator. NON SEI UN MEDICO.\n"
                "- SINGLE QUESTION POLICY:  Una sola domanda alla volta.\n"
                "- NO DIAGNOSI:  Non nominare malattie o cure.\n"
                "- SLOT FILLING: Non chiedere dati già forniti."
            ),
            "percorso_a": "EMERGENZA:  Max 3 domande rapide e mirate alla sicurezza territoriale.",
            "percorso_b": "SALUTE MENTALE: Tono empatico.  Includere riferimenti se necessario (1522, Telefono Amico).",
            "percorso_c": "STANDARD: Valuta scala dolore (1-10) e anamnesi recente.",
            "disposition_prompt": "FASE FINALE: Genera una sintesi chiara e una raccomandazione sulla struttura."
        }
    
    def _build_context_section(self, collected_data: Dict) -> str:
        """
        Costruisce la sezione del prompt con i dati già raccolti.
        FIX BUG #2: Iniezione esplicita con formato JSON per chiarezza AI
        """
        if not collected_data:
            return "DATI GIÀ RACCOLTI:  Nessuno\n\nINIZIA LA RACCOLTA DATI."
        
        known_slots = []
        
        # Mappatura completa con priorità per Red Flags
        if collected_data.get('LOCATION'):
            known_slots. append(f"Comune: {collected_data['LOCATION']}")
        
        if collected_data.get('CHIEF_COMPLAINT'):
            known_slots.append(f"Sintomo principale: {collected_data['CHIEF_COMPLAINT']}")
        
        if collected_data.get('PAIN_SCALE'):
            known_slots.append(f"Dolore: {collected_data['PAIN_SCALE']}/10")
        
        # FIX CRITICO:  Gestione robusta RED_FLAGS
        if collected_data.get('RED_FLAGS'):
            rf = collected_data['RED_FLAGS']
            if isinstance(rf, str):
                rf_display = rf
            elif isinstance(rf, list):
                rf_display = ', '.join(rf) if rf else 'Nessuno rilevato'
            else:
                rf_display = str(rf)
            known_slots.append(f"Red Flags: {rf_display}")
        
        if collected_data.get('age'):
            known_slots.append(f"Età: {collected_data['age']} anni")
        
        if collected_data.get('sex'):
            known_slots.append(f"Sesso: {collected_data['sex']}")
        
        if collected_data. get('pregnant'):
            known_slots.append(f"Gravidanza:  {collected_data['pregnant']}")
        
        if collected_data.get('medications'):
            known_slots.append(f"Farmaci: {collected_data['medications']}")
        
        # NUOVA SEZIONE: Esportazione JSON per debug AI
        json_export = json.dumps(collected_data, ensure_ascii=False, indent=2)
        
        context = f"""
DATI GIA RACCOLTI (NON RIPETERE QUESTE DOMANDE):

{chr(10).join(known_slots)}

Formato Strutturato (per validazione):
{json_export}

ISTRUZIONE CRITICA:
- Se un dato è presente sopra, NON chiedere nuovamente
- Passa direttamente al prossimo slot mancante
- Se tutti i dati sono completi, genera la raccomandazione finale
"""
        
        return context
    
    def _determine_next_slot(self, collected_data: Dict, current_phase: str) -> str:
        """
        Determina il prossimo slot da riempire seguendo il protocollo triage.
        FIX BUG #2: Gestione intelligente RED_FLAGS
        """
        if not collected_data. get('LOCATION') and current_phase != "DISPOSITION":
            return "Comune di residenza (Emilia-Romagna)"
        
        if not collected_data.get('CHIEF_COMPLAINT') and current_phase != "DISPOSITION":
            return "Sintomo principale (descrizione breve)"
        
        if not collected_data.get('PAIN_SCALE') and current_phase != "DISPOSITION": 
            return "Intensità dolore (scala 1-10, o 'nessun dolore')"
        
        # FIX CRITICO RED_FLAGS:  Verifica se è stringa vuota, lista vuota, o None
        red_flags_data = collected_data.get('RED_FLAGS')
        has_red_flags = False
        
        if red_flags_data:
            if isinstance(red_flags_data, str) and red_flags_data.strip():
                has_red_flags = True
            elif isinstance(red_flags_data, list) and len(red_flags_data) > 0:
                has_red_flags = True
        
        if not has_red_flags and current_phase != "DISPOSITION": 
            return """RED FLAGS (DOMANDA SINGOLA):
            
Fai UNA SOLA domanda tra queste opzioni (scegli la più rilevante):
1. "Hai difficoltà a respirare o dolore al petto?"
2. "Hai avuto febbre alta (>38.5°C) nelle ultime 24 ore?"
3. "Hai notato perdite di sangue insolite?"

NON fare più di una domanda per messaggio. 
Se l'utente risponde NO, considera RED_FLAGS completato e passa all'anamnesi.
"""
        
        if not collected_data.get('age') and current_phase != "DISPOSITION":
            return "Età del paziente"
        
        if current_phase == "DISPOSITION": 
            return "GENERAZIONE_RACCOMANDAZIONE_FINALE"
        
        return "Anamnesi aggiuntiva (farmaci, allergie, condizioni croniche)"
    
    def _check_emergency_triggers(self, user_message: str, collected_data: Dict) -> Optional[Dict]:
        """
        Rileva trigger di emergenza in tempo reale.
        Integrazione con sistema di emergenza.
        """
        if not user_message: 
            return None
        
        text_lower = user_message.lower().strip()
        
        red_keywords = [
            "dolore toracico", "dolore petto", "oppressione torace",
            "non riesco respirare", "non riesco a respirare", "soffoco", "difficoltà respiratoria grave",
            "perdita di coscienza", "svenuto", "svenimento",
            "convulsioni", "crisi convulsiva",
            "emorragia massiva", "sangue abbondante",
            "paralisi", "metà corpo bloccata"
        ]
        
        for keyword in red_keywords:
            if keyword in text_lower: 
                logger.error(f"RED EMERGENCY detected: '{keyword}'")
                return {
                    "testo": "Rilevata possibile emergenza.  Chiama immediatamente il 118.",
                    "tipo_domanda": "text",
                    "fase_corrente": "EMERGENCY_OVERRIDE",
                    "opzioni": None,
                    "dati_estratti": {},
                    "metadata": {
                        "urgenza": 5,
                        "area": "Emergenza",
                        "red_flags": [keyword],
                        "confidence": 1.0,
                        "fallback_used": False
                    }
                }
        
        return None

    def _get_system_prompt(self, path:  str, phase: str, collected_data: Dict = None, is_first_message: bool = False) -> str:
        """
        Genera system prompt dinamico con contesto dei dati già raccolti.
        
        Args:
            path: Percorso triage (A/B/C)
            phase: Fase corrente
            collected_data: Dati già raccolti
            is_first_message: True se primo contatto
        """
        if collected_data is None:
            collected_data = {}
        
        if is_first_message:
            return f"""
{self.prompts['base_rules']}

PRIMO CONTATTO - ROUTING INTELLIGENTE: 
Analizza il messaggio dell'utente e determina l'intento: 

1. **TRIAGE PATH** (Percorso A/B/C):
   - Sintomi attivi (dolore, febbre, trauma)
   - Richieste urgenti ("mi fa male", "ho bisogno di cure")
   → Inizia raccolta dati:  Location → Sintomo → Urgenza

2. **INFO PATH** (Servizi ASL):
   - Domande generiche ("dove trovo.. .", "orari farmacie")
   - Chiarimenti ("cosa fai? ", "come funziona?")
   → Rispondi direttamente senza raccogliere dati clinici

RISPONDI IN JSON:
{{
    "testo": "messaggio per l'utente",
    "tipo_domanda": "text|info_request",
    "fase_corrente": "INTENT_DETECTION|LOCATION|INFO_SERVICES",
    "dati_estratti": {{}},
    "metadata": {{ "urgenza": 1, "area": "Generale", "confidence": 0.8, "fallback_used": false }}
}}
"""
        
        context_section = self._build_context_section(collected_data)
        next_slot_info = self._determine_next_slot(collected_data, phase)
        path_instruction = self. prompts. get(f"percorso_{path. lower()}", self.prompts["percorso_c"])
        
        if phase == "DISPOSITION":
            path_instruction = self.prompts["disposition_prompt"]
        
        return f"""
{self.prompts['base_rules']}

CONTESTO MEMORIA (NON CHIEDERE NUOVAMENTE):
{context_section}

OBIETTIVO ATTUALE:  {next_slot_info}
DIRETTIVE: {path_instruction}
FASE:  {phase} | PERCORSO: {path}

ESTRAZIONE AUTOMATICA: 
Se l'utente fornisce spontaneamente dati (es. "Sono a Bologna e mi fa male la testa"):
- Popola "dati_estratti" con TUTTI i dati rilevati
- Conferma brevemente e passa alla prossima domanda

FORMATO RISPOSTA JSON:
{{
    "testo": "singola domanda mirata",
    "tipo_domanda": "survey|scale|text|confirmation",
    "opzioni": ["A", "B"] o null,
    "fase_corrente": "{phase}",
    "dati_estratti": {{
        "LOCATION": "nome_comune" (se presente),
        "CHIEF_COMPLAINT": "sintomo" (se presente),
        "PAIN_SCALE": 1-10 (se presente),
        "age": numero (se presente)
    }},
    "metadata": {{ "urgenza": 1-5, "area": ".. .", "confidence": 0.0-1.0, "fallback_used": false }}
}}
"""

    async def call_ai_streaming(self, messages: List[Dict], path: str, phase: str,
                                 collected_data: Dict = None, is_first_message: bool = False) -> AsyncGenerator[Union[str, TriageResponse], None]:
        """
        Metodo principale con logging dettagliato e modelli aggiornati.
        
        Args:
            messages: Lista messaggi della conversazione
            path: Percorso triage (A/B/C)
            phase: Fase corrente
            collected_data: Dati già raccolti
            is_first_message: True se primo contatto
        
        Yields:
            str: Token di testo per streaming
            TriageResponse:  Oggetto finale con metadati
        """
        if collected_data is None:
            collected_data = {}
        
        if messages: 
            last_user_msg = next((m['content'] for m in reversed(messages) if m.get('role') == 'user'), "")
            emergency_response = self._check_emergency_triggers(last_user_msg, collected_data)
            if emergency_response:
                logger.warning("Emergency override attivato")
                yield emergency_response['testo']
                yield TriageResponse(**emergency_response)
                return
        
        system_msg = self._get_system_prompt(path, phase, collected_data, is_first_message)
        api_messages = [{"role": "system", "content":  system_msg}] + messages[-5:]
        full_response_str = ""
        success = False

        logger.info(f"call_ai_streaming START | phase={phase}, path={path}, collected_keys={list(collected_data.keys())}")
        logger.info(f"Groq disponibile: {self.groq_client is not None}")
        logger.info(f"Gemini disponibile: {self.gemini_model is not None}")

        if self.groq_client:
            try:
                logger.info("Tentativo Groq con llama-3.3-70b-versatile...")
                stream = await asyncio.wait_for(
                    self.groq_client.chat. completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=api_messages,
                        temperature=0.1,
                        stream=True,
                        response_format={"type": "json_object"}
                    ), timeout=60.0
                )
                
                logger.info("Groq stream ricevuto, lettura in corso...")
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    full_response_str += token
                
                logger.info(f"Groq completato | Lunghezza: {len(full_response_str)} char")
                success = True
                
            except asyncio.TimeoutError:
                logger.error("Groq TIMEOUT (60 secondi)")
            except Exception as e:
                logger.error(f"Groq ERROR: {type(e).__name__} - {str(e)}")

        if not success and self.gemini_model:
            try:
                logger.info("Tentativo fallback Gemini...")
                def _gem_call():
                    prompt = "\n".join([f"{m['role']}: {m['content']}" for m in api_messages])
                    res = self.gemini_model. generate_content(prompt)
                    return res.text
                
                full_response_str = await asyncio.get_event_loop().run_in_executor(self._executor, _gem_call)
                logger.info(f"Gemini completato | Lunghezza:  {len(full_response_str)} char")
                success = True
                
            except Exception as e:
                logger.error(f"Gemini ERROR:  {type(e).__name__} - {str(e)}")

        if success and full_response_str:
            try:
                logger.info("Inizio parsing JSON...")
                clean_json = re.sub(r"```json\n? |```", "", full_response_str).strip()
                logger.debug(f"JSON pulito (primi 200 char): {clean_json[:200]}")
                
                data = json.loads(clean_json)
                response_obj = TriageResponse(**data)
                response_obj = DiagnosisSanitizer. sanitize(response_obj)

                if phase == "DISPOSITION":
                    loc = st.session_state.get("collected_data", {}).get("LOCATION", "Bologna")
                    urgenza = response_obj.metadata.urgenza
                    area = response_obj.metadata.area
                    
                    structure = self. router.route(loc, urgenza, area)
                    
                    st.session_state.collected_data['DISPOSITION'] = {
                        'type': structure['tipo'],
                        'urgency': urgenza,
                        'facility_name': structure['nome'],
                        'note': structure.get('note', ''),
                        'distance': structure.get('distance_km')
                    }
                    
                    response_obj.testo += f"\n\nStruttura consigliata: {structure['nome']}\n{structure. get('note', '')}"

                logger.info(f"Parsing completato | Testo: {len(response_obj.testo)} char")
                yield response_obj.testo
                yield response_obj
                return
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON DECODE ERROR: {e}")
                logger.error(f"JSON problematico: {full_response_str[: 500]}")
            except ValidationError as e:
                logger. error(f"PYDANTIC VALIDATION ERROR: {e}")
            except Exception as e:
                logger.error(f"PARSING ERROR: {type(e).__name__} - {str(e)}")

        logger.warning("Restituzione fallback generico")
        fallback = self._get_safe_fallback_response()
        yield fallback. testo
        yield fallback

    def _get_safe_fallback_response(self) -> TriageResponse:
        return TriageResponse(
            testo="Sto analizzando i dati raccolti. Potresti descrivere con più precisione come ti senti in questo momento?",
            tipo_domanda=QuestionType.TEXT,
            fase_corrente="ANAMNESIS",
            dati_estratti={},
            metadata=TriageMetadata(urgenza=3, area="Generale", confidence=0.0, fallback_used=True)
        )

    def is_available(self) -> bool:
        """Controlla se almeno uno dei servizi è configurato."""
        return bool(self.groq_client or self.gemini_model)