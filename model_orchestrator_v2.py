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
                logging.critical(f"🚨 DIAGNOSI BLOCCATA: {response.testo}")
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
        
        g_key = groq_key or st.secrets. get("GROQ_API_KEY", "")
        gem_key = gemini_key or st.secrets.get("GEMINI_API_KEY", "")
        
        self.set_keys(groq=g_key, gemini=gem_key)
        atexit.register(self._cleanup)

    def set_keys(self, groq:  str = "", gemini: str = ""):
        """Configura o aggiorna le chiavi API in runtime."""
        try:
            if groq:
                from groq import AsyncGroq
                self.groq_client = AsyncGroq(api_key=groq)
                logging.info("✅ Groq client initialized")
            
            if gemini:
                import google.generativeai as genai
                genai.configure(api_key=gemini)
                # ✅ FIX:   Usa modello aggiornato 2025
                self.gemini_model = genai.GenerativeModel("gemini-2.0-flash-exp")
                logging.info("✅ Gemini model initialized (gemini-2.0-flash-exp)")
        except Exception as e:
            logging.error(f"❌ Errore configurazione chiavi: {e}")

    def _cleanup(self):
        if hasattr(self, '_executor'):
            self._executor. shutdown(wait=False)

    def _load_prompts(self) -> Dict[str, str]:
        return {
            "base_rules": (
                "Sei l'AI Health Navigator. NON SEI UN MEDICO.\n"
                "- SINGLE QUESTION POLICY:  Una sola domanda alla volta.\n"
                "- NO DIAGNOSI:  Non nominare malattie o cure.\n"
                "- SLOT FILLING: Non chiedere dati già forniti."
            ),
            "percorso_a":  "🚨 EMERGENZA:  Max 3 domande rapide e mirate alla sicurezza territoriale.",
            "percorso_b": "🆘 SALUTE MENTALE: Tono empatico.  Includere riferimenti se necessario (1522, Telefono Amico).",
            "percorso_c": "📗 STANDARD: Valuta scala dolore (1-10) e anamnesi recente.",
            "disposition_prompt": "🎯 FASE FINALE: Genera una sintesi chiara e una raccomandazione sulla struttura."
        }

    def _get_system_prompt(self, path: str, phase: str) -> str:
        path_instruction = self.prompts. get(f"percorso_{path. lower()}", self.prompts["percorso_c"])
        if phase == "DISPOSITION":
            path_instruction = self.prompts["disposition_prompt"]
            
        return f"""
        {self.prompts['base_rules']}
        DIRETTIVE ATTUALI:  {path_instruction}
        FASE:  {phase} | PERCORSO: {path}
        
        RISPONDI ESCLUSIVAMENTE IN FORMATO JSON:  
        {{
            "testo": "stringa con la domanda o sintesi",
            "tipo_domanda": "survey|scale|text",
            "opzioni": ["Opzione A", "Opzione B"] o null,
            "metadata": {{ 
                "urgenza": 1-5, 
                "area": "nome_area", 
                "red_flags":  [], 
                "confidence": 0.0-1.0,
                "kb_reference": "PROTOCOLLO_ID" (opzionale)
            }}
        }}
        """

    async def call_ai_streaming(self, messages: List[Dict], path: str, phase: str) -> AsyncGenerator[Union[str, TriageResponse], None]:
        """
        Metodo principale con logging dettagliato e modelli aggiornati.
        """
        system_msg = self._get_system_prompt(path, phase)
        api_messages = [{"role": "system", "content": system_msg}] + messages[-5:]
        full_response_str = ""
        success = False

        logger.info(f"🎯 call_ai_streaming START | phase={phase}, path={path}")
        logger.info(f"📊 Groq disponibile: {self.groq_client is not None}")
        logger.info(f"📊 Gemini disponibile: {self.gemini_model is not None}")

        # --- 1. TENTA GROQ ---
        if self.groq_client:
            try:
                logger.info("🔵 Tentativo Groq con llama-3.3-70b-versatile...")
                stream = await asyncio.wait_for(
                    self. groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",  # ✅ MODELLO AGGIORNATO
                        messages=api_messages,
                        temperature=0.1,
                        stream=True,
                        response_format={"type": "json_object"}
                    ), timeout=60.0  # ✅ TIMEOUT AUMENTATO
                )
                
                logger.info("✅ Groq stream ricevuto, lettura in corso...")
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    full_response_str += token
                
                logger.info(f"✅ Groq completato | Lunghezza: {len(full_response_str)} char")
                success = True
                
            except asyncio.TimeoutError:
                logger.error("⏱️ Groq TIMEOUT (60 secondi)")
            except Exception as e:
                logger.error(f"❌ Groq ERROR: {type(e).__name__} - {str(e)}")

        # --- 2. FALLBACK GEMINI ---
        if not success and self.gemini_model:
            try:
                logger.info("🟡 Tentativo fallback Gemini...")
                def _gem_call():
                    prompt = "\n".join([f"{m['role']}: {m['content']}" for m in api_messages])
                    res = self.gemini_model. generate_content(prompt)
                    return res.text
                
                full_response_str = await asyncio.get_event_loop().run_in_executor(self._executor, _gem_call)
                logger.info(f"✅ Gemini completato | Lunghezza: {len(full_response_str)} char")
                success = True
                
            except Exception as e:
                logger.error(f"❌ Gemini ERROR: {type(e).__name__} - {str(e)}")

        # --- 3. PARSING E VALIDAZIONE ---
        if success and full_response_str:
            try:
                logger.info("🔍 Inizio parsing JSON...")
                clean_json = re.sub(r"```json\n? |```", "", full_response_str).strip()
                logger.debug(f"JSON pulito (primi 200 char): {clean_json[:200]}")
                
                data = json.loads(clean_json)
                response_obj = TriageResponse(**data)
                response_obj = DiagnosisSanitizer. sanitize(response_obj)

                # ✅ ROUTING DISPOSITION CON SALVATAGGIO
                if phase == "DISPOSITION":
                    loc = st.session_state.get("collected_data", {}).get("LOCATION", "Bologna")
                    urgenza = response_obj.metadata.urgenza
                    area = response_obj. metadata.area
                    
                    structure = self.router.route(loc, urgenza, area)
                    
                    st.session_state.collected_data['DISPOSITION'] = {
                        'type': structure['tipo'],
                        'urgency': urgenza,
                        'facility_name': structure['nome'],
                        'note': structure.get('note', ''),
                        'distance':  structure.get('distance_km')
                    }
                    
                    response_obj.testo += f"\n\n📍 **Struttura consigliata:** {structure['nome']}\n{structure. get('note', '')}"

                logger.info(f"✅ Parsing completato | Testo: {len(response_obj.testo)} char")
                yield response_obj.testo
                yield response_obj
                return
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON DECODE ERROR: {e}")
                logger.error(f"JSON problematico: {full_response_str[: 500]}")
            except ValidationError as e:
                logger. error(f"❌ PYDANTIC VALIDATION ERROR: {e}")
            except Exception as e:
                logger.error(f"❌ PARSING ERROR: {type(e).__name__} - {str(e)}")

        # --- 4. FALLBACK DI SICUREZZA ---
        logger.warning("⚠️ Restituzione fallback generico")
        fallback = self._get_safe_fallback_response()
        yield fallback. testo
        yield fallback

    def _get_safe_fallback_response(self) -> TriageResponse:
        return TriageResponse(
            testo="Sto analizzando i dati raccolti. Potresti descrivere con più precisione come ti senti in questo momento?",
            tipo_domanda=QuestionType.TEXT,
            metadata=TriageMetadata(urgenza=3, area="Generale", confidence=0.0, fallback_used=True)
        )

    def is_available(self) -> bool:
        """Controlla se almeno uno dei servizi è configurato."""
        return bool(self.groq_client or self.gemini_model)