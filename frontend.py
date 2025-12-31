import streamlit as st
import json
import time
import uuid
import os
import logging
import random
import re
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Generator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import groq
import google.generativeai as genai
import folium
from streamlit_folium import st_folium

# --- CONFIGURAZIONE LOGGING E PAGINA ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="AI Health Navigator - Professional Triage",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- STILI CSS AVANZATI ---
st.markdown("""
<style>
    .main { background-color: #f0f2f6; }
    .stButton>button { width: 100%; border-radius: 12px; height: 3.5em; font-weight: 600; transition: all 0.3s; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .emergency-banner { 
        padding: 25px; background: linear-gradient(135deg, #ff4b4b 0%, #b91c1c 100%); 
        color: white; border-radius: 15px; margin-bottom: 25px; box-shadow: 0 10px 20px rgba(185, 28, 28, 0.3);
    }
    .disclaimer-box {
        padding: 20px; border: 2px solid #d1d5db; background-color: #ffffff;
        border-radius: 12px; font-size: 0.95em; color: #1f2937; margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .typing-indicator { color: #6b7280; font-size: 0.9em; font-style: italic; margin-bottom: 10px; }
    .fade-in { animation: fadeIn 0.5s; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
</style>
""", unsafe_allow_html=True)

# --- COSTANTI DI SISTEMA ---
MODEL_CONFIG = {
    "triage": "llama-3.1-8b-instant",
    "complex": "llama-3.3-70b-versatile",
    "fallback": "gemini-2.0-flash"
}

PHASES = [
    {"id": "IDENTIFICATION", "name": "Identificazione", "icon": "👤"},
    {"id": "ANAMNESIS", "name": "Analisi Sintomi", "icon": "🔍"},
    {"id": "SAFETY_CHECK", "name": "Protocolli Sicurezza", "icon": "🛡️"},
    {"id": "LOGISTICS", "name": "Supporto Territoriale", "icon": "📍"},
    {"id": "DISPOSITION", "name": "Conclusione Triage", "icon": "🏥"}
]

SENSITIVE_KEYWORDS = ["suicidio", "uccidere", "morte", "autolesionismo", "violenza", "stupro", "abuso", "botte", "coltellata", "arma"]

# --- UTILITIES DI SICUREZZA E PARSING ---
class DataSecurity:
    @staticmethod
    def sanitize_input(text: str) -> str:
        """Sanifica l'input per prevenire injection e limitare la lunghezza."""
        if not text: return ""
        clean = re.sub(r'<script.*?>.*?</script>|<.*?>', '', text, flags=re.DOTALL)
        return clean[:2000].strip()

class JSONExtractor:
    @staticmethod
    def extract(text: str) -> Optional[Dict]:
        """Estrae l'oggetto JSON dal testo dell'AI con fallback regex."""
        try:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
            match = re.search(r'\{(?:[^{}]|(?R))*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.error(f"Errore critico parsing JSON: {e}")
        return None

# --- BACKEND SYNC (GDPR COMPLIANT) ---
class BackendClient:
    def __init__(self):
        # I secrets vengono letti da .streamlit/secrets.toml
        self.url = st.secrets.get("BACKEND_URL", "https://api.health-navigator.it/triage")
        self.api_key = st.secrets.get("BACKEND_API_KEY", "")
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def sync(self, data: Dict):
        """Invia dati strutturati per il backend (Triage Data Passing)."""
        if not st.session_state.get("gdpr_consent", False):
            return 
            
        try:
            # Arricchimento dati per il backend
            enriched_data = {
                "session_id": st.session_state.session_id,
                "phase": PHASES[st.session_state.current_phase_idx]["id"],
                "triage_data": data,
                "current_specialization": st.session_state.specialization,
                "timestamp": datetime.now().isoformat()
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            # Simulazione invio (decommentare in produzione)
            # self.session.post(self.url, json=enriched_data, headers=headers, timeout=5)
            logger.info(f"BACKEND_SYNC | Data: {json.dumps(enriched_data)}")
        except Exception as e:
            logger.error(f"Sync Backend Fallito: {e}")

# --- CLASSE LOGISTICA ---
class PharmacyService:
    def __init__(self, directory: str = "knowledge_base/logistics/farmacie"):
        self.directory = directory

    @st.cache_data
    def get_pharmacies(_self, comune: str) -> List[Dict]:
        path = os.path.join(_self.directory, f"{comune.lower().replace(' ', '_')}.json")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception: return []
        # Fallback Mock per demo
        if comune.lower() == "roma":
            return [
                {"nome": "Farmacia Centrale", "lat": 41.9028, "lon": 12.4964, "indirizzo": "Via del Corso, 1", "H24": True},
                {"nome": "Farmacia S. Anna", "lat": 41.9035, "lon": 12.4544, "indirizzo": "Via di Porta Angelica, 1", "H24": False}
            ]
        return []

# --- ORCHESTRATORE AI (CON LOGICA NO-DIAGNOSI) ---
class ModelOrchestrator:
    def __init__(self):
        # Accesso ai secrets da .streamlit/secrets.toml
        self.groq_key = st.secrets.get("GROQ_API_KEY", "")
        self.gemini_key = st.secrets.get("GEMINI_API_KEY", "")
        self.groq_client = groq.Groq(api_key=self.groq_key) if self.groq_key else None
        
        if self.gemini_key:
            genai.configure(api_key=self.gemini_key)
            self.gemini_model = genai.GenerativeModel(MODEL_CONFIG["fallback"])
        else:
            self.gemini_model = None

    def is_available(self) -> bool:
        return self.groq_client is not None or self.gemini_model is not None

    def _get_system_prompt(self, phase: str, is_sensitive: bool) -> str:
        prompt = (
            "Sei un assistente AI di Triage Sanitario Professionale. "
            "REGOLA FONDAMENTALE: Non fornire MAI diagnosi mediche (es. 'Hai la polmonite'). "
            "Il tuo compito è ESCLUSIVAMENTE raccogliere sintomi, valutare l'urgenza e orientare l'utente. "
            "Poni UNA SOLA domanda alla volta. Rispondi SEMPRE in JSON. "
            "Esempio: {\"testo\": \"...\", \"tipo_domanda\": \"survey\", \"opzioni\": [\"Sì\", \"No\"], \"metadata\": {\"area\": \"Trauma\", \"urgenza\": 2, \"sintomi_rilevati\": [\"dolore\"]}}\n"
        )
        if is_sensitive:
            prompt += " EMERGENZA: Dinamica sensibile rilevata. Sii estremamente protettivo e sintetico."
        return prompt

    def call_ai(self, messages: List[Dict], phase: str) -> Generator[Union[str, Dict], None, None]:
        last_input = messages[-1]["content"]
        is_sensitive = any(kw in last_input.lower() for kw in SENSITIVE_KEYWORDS)
        
        model_id = MODEL_CONFIG["complex"] if is_sensitive or phase == "DISPOSITION" else MODEL_CONFIG["triage"]
        temp = 0.1 if is_sensitive else 0.4
        system_msg = self._get_system_prompt(phase, is_sensitive)
        
        api_messages = [{"role": "system", "content": system_msg}] + messages[-10:]

        full_response = ""
        success = False

        if self.groq_client:
            try:
                stream = self.groq_client.chat.completions.create(
                    model=model_id, messages=api_messages, temperature=temp, stream=True
                )
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        full_response += token
                        yield token
                success = True
            except Exception as e:
                logger.warning(f"Groq API Error: {e}")

        if not success and self.gemini_model:
            try:
                gemini_prompt = f"{system_msg}\n\nCronologia:\n" + "\n".join([f"{m['role']}: {m['content']}" for m in api_messages])
                response = self.gemini_model.generate_content(
                    gemini_prompt, 
                    generation_config=genai.types.GenerationConfig(temperature=temp)
                )
                full_response = response.text
                yield full_response
                success = True
            except Exception as e:
                logger.error(f"Gemini Fallback Error: {e}")

        if not success:
            fail_msg = {"testo": "Servizio AI momentaneamente non disponibile. Chiamare il 118 in caso di urgenza.", "metadata": {"error": True}}
            yield fail_msg
            return

        final_data = JSONExtractor.extract(full_response)
        if not final_data:
            final_data = {"testo": full_response, "tipo_domanda": "text", "opzioni": None, "metadata": {}}
        
        yield final_data

# --- UI COMPONENTS ---
def render_header(current_phase):
    st.markdown(f"### 🩺 Triage AI - Fase {st.session_state.current_phase_idx + 1}/5: {current_phase['name']}")
    if st.session_state.critical_alert:
        st.markdown("""
            <div class='emergency-banner fade-in'>
                <b>⚠️ PROTOCOLLO DI SICUREZZA ATTIVO</b><br>
                Rilevato contenuto sensibile. Non sei solo. Per supporto immediato: 
                <a href='https://findahelpline.com/countries/it/topics/suicidal-thoughts' style='color:white;text-decoration:underline;'>Find A Helpline</a> 
                o chiama il <b>1522</b>.
            </div>
        """, unsafe_allow_html=True)

def render_sidebar(pharmacy_db):
    with st.sidebar:
        st.title("🛡️ Navigator Pro")
        
        if st.button("🔄 Nuova Sessione", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
            
        if st.button("🆘 SOS - INVIA POSIZIONE", type="primary", use_container_width=True):
            st.warning("Geolocalizzazione in corso...")
            st.session_state.backend.sync({"event": "SOS_GPS_REQUEST"})
            st.info("In caso di pericolo reale, chiama subito il 118.")
        
        st.divider()
        current_phase = PHASES[st.session_state.current_phase_idx]
        st.markdown(f"**Specializzazione Backend:** `{st.session_state.specialization}`")
        st.progress((st.session_state.current_phase_idx + 1) / len(PHASES))
        
        with st.expander("📍 Farmacie & Logistica"):
            comune = st.text_input("Inserisci Comune:", key="pharm_search", placeholder="es. Roma")
            h24 = st.checkbox("Solo H24")
            if comune:
                farms = pharmacy_db.get_pharmacies(comune)
                if h24: farms = [f for f in farms if f.get("H24")]
                
                if farms:
                    center_lat = farms[0].get("lat", 41.90)
                    center_lon = farms[0].get("lon", 12.49)
                    m = folium.Map(location=[center_lat, center_lon], zoom_start=13)
                    for f in farms:
                        folium.Marker(
                            [f.get("lat"), f.get("lon")],
                            popup=f"{f['nome']}\n{f.get('indirizzo', '')}",
                            icon=folium.Icon(color="red" if f.get("H24") else "blue", icon="plus", prefix="fa")
                        ).add_to(m)
                    st_folium(m, height=250, width=250)
                else:
                    st.write("Nessun dato logistico trovato.")

def render_disclaimer():
    st.markdown("""
        <div class='disclaimer-box'>
            <b>CONSENSO INFORMATO:</b><br>
            1. Questo sistema effettua solo <b>Triage</b> e non fornisce diagnosi mediche.<br>
            2. Le informazioni sono elaborate da un'AI e possono contenere inesattezze.<br>
            3. Per emergenze chiamare il <b>118</b>.<br>
            4. I dati sono trasmessi in forma protetta al backend per la gestione clinica.
        </div>
    """, unsafe_allow_html=True)

# --- STATO SESSIONE ---
def init_session():
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.current_phase_idx = 0
        st.session_state.pending_survey = None
        st.session_state.critical_alert = False
        st.session_state.gdpr_consent = False
        st.session_state.specialization = "Generale"
        st.session_state.metadata_history = []
        st.session_state.backend = BackendClient()

def update_backend_metadata(metadata):
    """Aggiorna lo stato della specializzazione basandosi sui dati del triage."""
    st.session_state.metadata_history.append(metadata)
    areas = [m.get("area") for m in st.session_state.metadata_history if m.get("area")]
    
    if areas.count("Trauma") >= 2:
        st.session_state.specialization = "Ortopedia"
    elif areas.count("Psichiatria") >= 2:
        st.session_state.specialization = "Psichiatria"

# --- MAIN ---
def main():
    init_session()
    orchestrator = ModelOrchestrator()
    pharmacy_db = PharmacyService()

    if not st.session_state.gdpr_consent:
        st.markdown("### 📋 Benvenuto in Health Navigator")
        render_disclaimer()
        if st.button("Accetto e Inizio Triage"):
            st.session_state.gdpr_consent = True
            st.rerun()
        return

    render_sidebar(pharmacy_db)
    current_phase = PHASES[st.session_state.current_phase_idx]
    render_header(current_phase)

    if not orchestrator.is_available():
        st.error("Servizio AI offline (Chiavi API non rilevate in secrets.toml).")
        return

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if not st.session_state.pending_survey:
        if raw_input := st.chat_input("Descrivi i sintomi..."):
            user_input = DataSecurity.sanitize_input(raw_input)
            st.session_state.messages.append({"role": "user", "content": user_input})
            
            if any(kw in user_input.lower() for kw in SENSITIVE_KEYWORDS):
                st.session_state.critical_alert = True

            with st.chat_message("assistant", avatar="🩺"):
                placeholder = st.empty()
                typing = st.empty()
                typing.markdown('<div class="typing-indicator">Analisi triage...</div>', unsafe_allow_html=True)
                
                full_text_vis = ""
                res_gen = orchestrator.call_ai(st.session_state.messages, current_phase["id"])
                
                final_obj = None
                for chunk in res_gen:
                    if isinstance(chunk, str):
                        full_text_vis += chunk
                        placeholder.markdown(full_text_vis)
                    else:
                        final_obj = chunk
                
                typing.empty()
                if final_obj:
                    actual_text = final_obj.get("testo", full_text_vis)
                    placeholder.markdown(actual_text)
                    st.session_state.messages.append({"role": "assistant", "content": actual_text})
                    st.session_state.pending_survey = final_obj
                    update_backend_metadata(final_obj.get("metadata", {}))
                    st.session_state.backend.sync(final_obj.get("metadata", {}))
                    st.rerun()

    if st.session_state.pending_survey and st.session_state.pending_survey.get("opzioni"):
        st.markdown("---")
        opts = st.session_state.pending_survey["opzioni"]
        cols = st.columns(len(opts))
        for i, opt in enumerate(opts):
            if cols[i].button(opt, key=f"btn_{i}"):
                if opt == "Altro":
                    st.session_state.show_altro = True
                    st.rerun()
                else:
                    st.session_state.messages.append({"role": "user", "content": opt})
                    st.session_state.pending_survey = None
                    if st.session_state.current_phase_idx < len(PHASES) - 1:
                        st.session_state.current_phase_idx += 1
                        st.toast(f"Step completato: {PHASES[st.session_state.current_phase_idx]['name']}")
                    st.rerun()
        
        if st.session_state.get("show_altro"):
            st.markdown("<div class='fade-in'>", unsafe_allow_html=True)
            c1, c2 = st.columns([4, 1])
            val = c1.text_input("Dettaglia qui:", placeholder="Scrivi...")
            if c2.button("X", key="cancel_altro"):
                st.session_state.show_altro = False
                st.rerun()
            if val and st.button("Invia"):
                st.session_state.messages.append({"role": "user", "content": val})
                st.session_state.pending_survey = None
                st.session_state.show_altro = False
                st.rerun()

if __name__ == "__main__":
    main()
