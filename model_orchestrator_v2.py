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
        self.groq_key = st.secrets. get("GROQ_API_KEY", "")
        self.gemini_key = st.secrets. get("GEMINI_API_KEY", "")
        
        # Client Async Groq
        try:
            from groq import AsyncGroq
            self.groq_client = AsyncGroq(api_key=self.groq_key) if self.groq_key else None
        except ImportError: 
            logging.error("AsyncGroq non disponibile, installa:  pip install groq")
            self.groq_client = None
        
        # Client Gemini
        if self.gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.gemini_key)
                self.gemini_model = genai.GenerativeModel("gemini-1.5-flash")
            except: 
                self.gemini_model = None
        else:
            self.gemini_model = None

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
        """Metodo principale con streaming"""
        system_msg = self._get_system_prompt(path, phase)
        api_messages = [{"role": "system", "content": system_msg}] + messages[-5:]
        full_response = ""
        success = False

        try:
            if self.groq_client:
                stream = await self.groq_client.chat.completions.create(
                    model="llama-3.1-70b-versatile",
                    messages=api_messages,
                    temperature=0.1,
                    stream=True,
                    response_format={"type": "json_object"}
                )
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    full_response += token
                    yield token
                success = True
        except Exception as e:
            logging.warning(f"Groq error: {e}")

        if not success:
            full_response = await self._handle_gemini_fallback(api_messages)
            yield full_response

        # Validazione finale
        response_obj = self._validate_and_parse(full_response)
        
        # Smart Routing per fase finale
        if phase == "DISPOSITION":
            loc = st.session_state.get("collected_data", {}).get("location", "Bologna")
            structure = self.router.route(loc, response_obj.metadata.urgenza, response_obj.metadata.area)
            response_obj.testo += f"\n\n📍 **{structure['nome']}**\n{structure. get('note', '')}"

        yield response_obj

    async def _handle_gemini_fallback(self, messages: List[Dict]) -> str:
        """Fallback asincrono su Gemini"""
        if not self.gemini_model:
            return json.dumps({"testo": "Servizio non disponibile", "metadata": {"urgenza": 3, "confidence": 0}})
        
        def _call():
            prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            res = self.gemini_model. generate_content(prompt)
            return res.text
        
        try:
            return await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(self._executor, _call),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            return json.dumps({"testo": "Timeout servizio", "metadata": {"urgenza": 3, "confidence": 0}})

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
        """Controlla disponibilità servizi"""
        return self.groq_client is not None or self.gemini_model is not None