import streamlit as st
import asyncio
import json
import logging
import re
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, AsyncGenerator, Union
from pydantic import ValidationError

# Import dei modelli
from models import TriageResponse, TriageMetadata, QuestionType

# Import router
from smart_router import SmartRouter


class DiagnosisSanitizer:
    """Blocca diagnosi non autorizzate"""
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
                response.testo = "In base ai dati raccolti, la situazione merita un approfondimento.  Potresti descrivermi l'insorgenza?"
                response.metadata.confidence = 0.1
                break
        return response


class ModelOrchestrator:
    def __init__(self):
        self.groq_key = st.secrets.get("GROQ_API_KEY", "")
        self.gemini_key = st.secrets.get("GEMINI_API_KEY", "")
        
        # ✅ Early validation of API keys
        if not self.groq_key and not self.gemini_key:
            logging.error("❌ NO API KEYS CONFIGURED! Check .streamlit/secrets.toml")
            st.error("⚠️ Configuration error: No API keys found. The chatbot may not work properly.")
        
        # Client Async Groq
        try:
            from groq import AsyncGroq
            if self.groq_key:
                self.groq_client = AsyncGroq(api_key=self.groq_key)
                logging.info("✅ Groq client initialized")
            else:
                self.groq_client = None
                logging.warning("⚠️ Groq API key missing")
        except ImportError: 
            logging.error("❌ AsyncGroq not available, install: pip install groq")
            self.groq_client = None
        
        # Client Gemini
        if self.gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.gemini_key)
                self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
                logging.info("✅ Gemini model initialized")
            except Exception as e: 
                logging.error(f"❌ Gemini initialization failed: {e}")
                self.gemini_model = None
        else:
            self.gemini_model = None
            logging.warning("⚠️ Gemini API key missing")

        # ThreadPool per fallback
        self._executor = ThreadPoolExecutor(max_workers=5)
        atexit.register(self._cleanup)
        
        # Router territoriale
        self.router = SmartRouter()
        self.prompts = self._load_prompts()

    def _cleanup(self):
        """Previene memory leak"""
        if hasattr(self, '_executor'):
            self._executor. shutdown(wait=False)

    def _load_prompts(self) -> Dict[str, str]:
        return {
            "base_rules": (
                "Sei l'AI Health Navigator. NON SEI UN MEDICO.\n"
                "- SINGLE QUESTION POLICY:  Una sola domanda alla volta.\n"
                "- NO DIAGNOSI:  Non nominare malattie.\n"
                "- SLOT FILLING: Non chiedere dati già forniti."
            ),
            "percorso_a": "🚨 EMERGENZA:  Max 3 domande rapide.",
            "percorso_b": "🆘 SALUTE MENTALE:  Tono empatico.  Hotline:  1522, Telefono Amico.",
            "percorso_c": "📗 STANDARD: Scala dolore 1-10, anamnesi.",
            "disposition_prompt": "🎯 FASE FINALE: Genera raccomandazione finale."
        }

    def _get_system_prompt(self, path: str, phase: str) -> str:
        path_instruction = self.prompts. get(f"percorso_{path. lower()}", self.prompts["percorso_c"])
        if phase == "DISPOSITION":
            path_instruction = self.prompts["disposition_prompt"]
            
        return f"""
        {self.prompts['base_rules']}
        DIRETTIVE:  {path_instruction}
        FASE: {phase} | PERCORSO: {path}
        
        RISPONDI SOLO IN JSON: 
        {{
            "testo": "domanda o sintesi",
            "tipo_domanda":  "survey|scale|text",
            "opzioni": ["A", "B"]|null,
            "metadata": {{ "urgenza": 1-5, "area": "string", "red_flags": [], "confidence": 0.0-1.0 }}
        }}
        """

    async def call_ai_streaming(self, messages: List[Dict], path: str, phase: str) -> AsyncGenerator[Union[str, TriageResponse], None]:
        """Metodo principale con streaming e error handling robusto"""
        system_msg = self._get_system_prompt(path, phase)
        api_messages = [{"role": "system", "content": system_msg}] + messages[-5:]
        full_response = ""
        success = False

        # ATTEMPT 1: Groq with timeout
        if self.groq_client:
            try:
                logging.info("Orchestrator: Attempting Groq API call...")
                stream = await asyncio.wait_for(
                    self.groq_client.chat.completions.create(
                        model="llama-3.1-70b-versatile",
                        messages=api_messages,
                        temperature=0.1,
                        stream=True,
                        response_format={"type": "json_object"}
                    ),
                    timeout=30.0
                )
                
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        full_response += token
                        yield token
                
                success = True
                logging.info(f"Orchestrator: Groq completed successfully ({len(full_response)} chars)")
                
            except asyncio.TimeoutError:
                logging.error("Orchestrator: Groq timeout after 30s")
            except Exception as e:
                logging.error(f"Orchestrator: Groq error - {type(e).__name__}: {str(e)}")

        # ATTEMPT 2: Gemini fallback
        if not success:
            logging.info("Orchestrator: Attempting Gemini fallback...")
            try:
                full_response = await self._handle_gemini_fallback(api_messages)
                if full_response:
                    yield full_response
                    success = True
                    logging.info("Orchestrator: Gemini fallback succeeded")
            except Exception as e:
                logging.error(f"Orchestrator: Gemini fallback error: {e}")

        # ATTEMPT 3: Static fallback if all services fail
        if not success or not full_response:
            logging.error("Orchestrator: All AI services failed, using static fallback")
            fallback = self._get_safe_fallback_response()
            yield fallback.testo
            yield fallback
            return

        # Validate and parse response
        try:
            response_obj = self._validate_and_parse(full_response)
            
            # Smart Routing per fase finale
            if phase == "DISPOSITION":
                loc = st.session_state.get("collected_data", {}).get("location", "Bologna")
                structure = self.router.route(loc, response_obj.metadata.urgenza, response_obj.metadata.area)
                response_obj.testo += f"\n\n📍 **{structure['nome']}**\n{structure.get('note', '')}"

            yield response_obj
            logging.info("Orchestrator: Response validated and yielded successfully")
            
        except Exception as e:
            logging.error(f"Orchestrator: Validation error: {e}")
            yield self._get_safe_fallback_response()

    async def _handle_gemini_fallback(self, messages: List[Dict]) -> str:
        """Fallback asincrono su Gemini con error handling"""
        if not self.gemini_model:
            logging.warning("Gemini fallback called but model not available")
            return json.dumps({
                "testo": "Servizio AI temporaneamente non disponibile. Riprova tra qualche istante.",
                "tipo_domanda": "text",
                "metadata": {"urgenza": 3, "area": "Generale", "confidence": 0.0, "fallback_used": True}
            })
        
        def _call():
            prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            res = self.gemini_model.generate_content(prompt)
            return res.text
        
        try:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(self._executor, _call),
                timeout=10.0
            )
            return result
        except asyncio.TimeoutError:
            logging.error("Gemini timeout after 10s")
            return json.dumps({
                "testo": "La richiesta sta impiegando troppo tempo. Riprova.",
                "tipo_domanda": "text",
                "metadata": {"urgenza": 3, "area": "Generale", "confidence": 0.0, "fallback_used": True}
            })
        except Exception as e:
            logging.error(f"Gemini error: {e}")
            return json.dumps({
                "testo": "Si è verificato un errore. Riprova.",
                "tipo_domanda": "text",
                "metadata": {"urgenza": 3, "area": "Generale", "confidence": 0.0, "fallback_used": True}
            })

    def _validate_and_parse(self, raw_json: str) -> TriageResponse:
        """Validazione con Pydantic"""
        try:
            clean_json = raw_json.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            response = TriageResponse(**data)
            return DiagnosisSanitizer. sanitize(response)
        except (json.JSONDecodeError, ValidationError) as e:
            logging.error(f"Validazione fallita: {e}")
            return self._get_safe_fallback_response()

    def _get_safe_fallback_response(self) -> TriageResponse:
        """Risposta di sicurezza"""
        return TriageResponse(
            testo="Sto analizzando i tuoi sintomi. Descrivimi meglio come ti senti.",
            tipo_domanda=QuestionType.TEXT,
            metadata=TriageMetadata(urgenza=3, area="Generale", confidence=0.5, fallback_used=True)
        )

    def is_available(self) -> bool:
        """Controlla disponibilità servizi con test rapido"""
        if not self.groq_client and not self.gemini_model:
            logging.error("❌ No AI service available")
            return False
        
        # Quick test for Groq if available
        if self.groq_client:
            try:
                async def _test():
                    response = await asyncio.wait_for(
                        self.groq_client.chat.completions.create(
                            model="llama-3.1-8b-instant",
                            messages=[{"role": "user", "content": "test"}],
                            max_tokens=5
                        ),
                        timeout=5.0
                    )
                    return bool(response.choices[0].message.content)
                
                # Use asyncio.run() for cleaner async execution
                try:
                    result = asyncio.run(_test())
                    if result:
                        logging.info("✅ Groq connectivity test passed")
                        return True
                except RuntimeError:
                    # If there's already an event loop, fall back to manual loop creation
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(_test())
                        if result:
                            logging.info("✅ Groq connectivity test passed")
                            return True
                    finally:
                        loop.close()
                    
            except Exception as e:
                logging.warning(f"⚠️ Groq test failed: {e}")
        
        # If Groq fails, check if Gemini is available as fallback
        if self.gemini_model:
            logging.info("✅ Gemini available as fallback")
            return True
        
        return False