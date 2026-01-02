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
# PARTE 1: Import per State Machine
from typing import List, Dict, Any, Optional, Union, Generator, Tuple
from enum import Enum
# PARTE 2: Import per calcoli geospaziali
import math
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

LOG_FILE = "triage_logs.jsonl"

PHASES = [
    {"id": "IDENTIFICATION", "name": "Identificazione", "icon": "👤"},
    {"id": "ANAMNESIS", "name": "Analisi Sintomi", "icon": "🔍"},
    {"id": "SAFETY_CHECK", "name": "Protocolli Sicurezza", "icon": "🛡️"},
    {"id": "LOGISTICS", "name": "Supporto Territoriale", "icon": "📍"},
    {"id": "DISPOSITION", "name": "Conclusione Triage", "icon": "🏥"}
]

# PARTE 1: Definizione Stati del Triage
class TriageStep(Enum):
    """
    Stati obbligatori del flusso di triage. 
    L'utente deve completare ogni step prima di procedere.
    """
    LOCATION = 1           # Comune Emilia-Romagna (obbligatorio)
    CHIEF_COMPLAINT = 2    # Sintomo principale (obbligatorio)
    PAIN_SCALE = 3         # Scala 1-10 o descrittore (obbligatorio)
    RED_FLAGS = 4          # Checklist sintomi gravi (obbligatorio)
    ANAMNESIS = 5          # Età, farmaci, allergie (obbligatorio)
    DISPOSITION = 6        # Verdetto finale (generato dal sistema)

# PARTE 1: Sistema Emergenze a Livelli
class EmergencyLevel(Enum):
    """
    Livelli di emergenza con azioni specifiche (non arbitrarie).
    """
    GREEN = 1     # Non urgente (gestione normale)
    YELLOW = 2    # Differibile (monitorare)
    ORANGE = 3    # Urgente (PS entro 2h)
    RED = 4       # Emergenza immediata (118)
    BLACK = 5     # Crisi psichiatrica (hotline specializzata)

EMERGENCY_RULES = {
    EmergencyLevel.RED: {
        "symptoms": [
            "dolore toracico intenso", "dolore petto insopportabile", "oppressione torace",
            "difficoltà respiratoria grave", "non riesco respirare", "soffoco",
            "perdita di coscienza", "svenuto", "svenimento improvviso",
            "convulsioni", "crisi convulsiva", "attacco epilettico",
            "emorragia massiva", "sangue abbondante", "emorragia incontrollabile",
            "paralisi improvvisa", "metà corpo bloccata", "braccio gamba non si muovono"
        ],
        "action": "IMMEDIATE_118",
        "message": "🚨 EMERGENZA MEDICA: È necessario chiamare immediatamente il 118",
        "ui_behavior": "overlay_fullscreen_blocking"
    },
    EmergencyLevel.ORANGE: {
        "symptoms": [
            "dolore addominale acuto", "dolore pancia molto forte", "addome rigido",
            "trauma cranico", "battuto forte testa", "caduta testa",
            "febbre alta bambino", "febbre 39 neonato", "febbre bambino piccolo",
            "vomito persistente", "vomito continuo", "vomito sangue",
            "dolore molto forte", "dolore insopportabile", "dolore lancinante"
        ],
        "action": "ER_URGENT",
        "message": "⚠️ SITUAZIONE URGENTE: Recati in Pronto Soccorso entro 2 ore",
        "ui_behavior": "banner_warning_persistent"
    },
    EmergencyLevel.BLACK: {
        "symptoms": [
            "suicidio", "uccidermi", "togliermi la vita", "farla finita",
            "ammazzarmi", "voglio morire", "non voglio più vivere",
            "autolesionismo", "tagliarmi", "farmi male da solo",
            "pensieri suicidari", "ideazione suicidaria"
        ],
        "action": "PSYCH_HOTLINE",
        "message": "🆘 SUPPORTO PSICOLOGICO IMMEDIATO: Non sei solo, aiuto disponibile 24/7",
        "ui_behavior": "panel_support_numbers"
    }
}


def assess_emergency_level(user_input: str, metadata: Dict) -> Optional[EmergencyLevel]:
    """
    Valuta il livello di emergenza basandosi su:
    1. Keyword matching nel testo utente (non case-sensitive)
    2. Metadata di urgenza forniti dall'AI
    3. Red flags clinici
    
    Args:
        user_input: Testo grezzo dell'utente
        metadata: Dict con chiavi 'urgenza' (1-5), 'red_flags' (List[str])
    
    Returns:
        EmergencyLevel se rilevata emergenza, None altrimenti
    
    Priorità:
        BLACK (psichiatrico) > RED (medico critico) > ORANGE (urgente) > metadata AI
    """
    text_lower = user_input.lower().strip()
    
    # PRIORITÀ 1: Check BLACK (psichiatrico) - ha precedenza assoluta
    for symptom in EMERGENCY_RULES[EmergencyLevel.BLACK]["symptoms"]:
        if symptom.lower() in text_lower:
            logger.warning(f"BLACK emergency detected: keyword='{symptom}'")
            return EmergencyLevel.BLACK
    
    # PRIORITÀ 2: Check RED (emergenza medica)
    for symptom in EMERGENCY_RULES[EmergencyLevel.RED]["symptoms"]:
        if symptom.lower() in text_lower:
            logger.error(f"RED emergency detected: keyword='{symptom}'")
            return EmergencyLevel.RED
    
    # PRIORITÀ 3: Check metadata AI (se disponibili)
    if metadata:
        urgenza = metadata.get("urgenza", 0)
        red_flags = metadata.get("red_flags", [])
        confidence = metadata.get("confidence", 0.0)
        
        # Urgenza AI massima + alta confidence → RED
        if urgenza >= 5 and confidence >= 0.7:
            logger.error(f"RED emergency from AI: urgenza={urgenza}, confidence={confidence}")
            return EmergencyLevel.RED
        
        # Urgenza 5 con bassa confidence o presenza di 2+ red flags → RED
        if urgenza >= 5 or len(red_flags) >= 2:
            logger.warning(f"RED emergency: urgenza={urgenza}, red_flags={len(red_flags)}")
            return EmergencyLevel.RED
        
        # Urgenza 4 o 1 red flag → ORANGE
        if urgenza == 4 or len(red_flags) == 1:
            logger.info(f"ORANGE urgency: urgenza={urgenza}, red_flags={red_flags}")
            return EmergencyLevel.ORANGE
    
    # PRIORITÀ 4: Check ORANGE (sintomi urgenti)
    for symptom in EMERGENCY_RULES[EmergencyLevel.ORANGE]["symptoms"]:
        if symptom.lower() in text_lower:
            logger.info(f"ORANGE emergency detected: keyword='{symptom}'")
            return EmergencyLevel.ORANGE
    
    # Nessuna emergenza rilevata
    return None


def render_emergency_overlay(level: EmergencyLevel):
    """
    Mostra UI specifica per livello emergenza (azione NON arbitraria).
    
    Args:
        level: Livello di emergenza rilevato
    
    Side Effects:
        - RED: Blocca completamente l'applicazione con overlay, chiama st.stop()
        - BLACK: Mostra panel supporto psicologico persistente
        - ORANGE: Mostra banner warning con raccomandazione PS
    """
    rule = EMERGENCY_RULES[level]
    
    if level == EmergencyLevel.RED:
        # COMPORTAMENTO RED: Overlay fullscreen BLOCCANTE
        st.markdown(f"""
        <div style='position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
                    background: rgba(220, 38, 38, 0.97); z-index: 9999;
                    display: flex; align-items: center; justify-content: center;
                    backdrop-filter: blur(10px);'>
            <div style='background: white; padding: 50px; border-radius: 20px; 
                        text-align: center; max-width: 600px; box-shadow: 0 25px 50px rgba(0,0,0,0.5);'>
                <h1 style='color: #dc2626; font-size: 3em; margin: 0 0 20px 0;'>🚨</h1>
                <h2 style='color: #dc2626; margin: 0 0 15px 0;'>EMERGENZA MEDICA</h2>
                <p style='font-size: 1.3em; margin: 20px 0; color: #374151; line-height: 1.6;'>
                    {rule['message']}
                </p>
                <p style='font-size: 1.1em; margin: 20px 0; color: #6b7280;'>
                    Questa applicazione <strong>non può sostituire</strong> l'intervento medico immediato.
                </p>
                <a href='tel:118' 
                   style='display: inline-block; background: #dc2626; color: white; 
                          padding: 25px 50px; text-decoration: none; border-radius: 15px; 
                          font-size: 2em; font-weight: bold; margin-top: 20px;
                          box-shadow: 0 10px 25px rgba(220, 38, 38, 0.5);
                          transition: transform 0.2s;'
                   onmouseover='this.style.transform="scale(1.05)"'
                   onmouseout='this.style.transform="scale(1)"'>
                    📞 CHIAMA 118 ORA
                </a>
                <p style='margin-top: 30px; font-size: 0.9em; color: #9ca3af;'>
                    Servizio attivo 24/7 - Chiamata gratuita
                </p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # BLOCCA esecuzione applicazione
        logger.critical(f"Application stopped: RED emergency overlay displayed")
        st.stop()
    
    elif level == EmergencyLevel.BLACK:
        # COMPORTAMENTO BLACK: Panel supporto psicologico (NON bloccante)
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%); 
                    color: white; padding: 35px; border-radius: 20px; margin: 25px 0;
                    box-shadow: 0 15px 35px rgba(124, 58, 237, 0.4);'>
            <h2 style='margin: 0 0 20px 0; font-size: 2em;'>🆘 Non sei solo/a</h2>
            <p style='font-size: 1.2em; margin-bottom: 25px; line-height: 1.6;'>
                {rule['message']}
            </p>
            <div style='background: rgba(255, 255, 255, 0.95); color: #1f2937; 
                        padding: 25px; border-radius: 15px; margin-top: 20px;'>
                <h3 style='margin: 0 0 15px 0; color: #7c3aed;'>📞 Contatti Supporto Immediato</h3>
                <div style='font-size: 1.1em; line-height: 2;'>
                    <strong>Telefono Amico Italia:</strong> 
                    <a href='tel:02-2327-2327' style='color: #7c3aed; font-weight: bold;'>02 2327 2327</a>
                    <span style='color: #6b7280;'> (tutti i giorni 10-24)</span>
                    <br>
                    <strong>Numero Antiviolenza:</strong> 
                    <a href='tel:1522' style='color: #7c3aed; font-weight: bold;'>1522</a>
                    <span style='color: #6b7280;'> (24/7, anche WhatsApp)</span>
                    <br>
                    <strong>Samaritans Onlus:</strong> 
                    <a href='tel:800-86-00-22' style='color: #7c3aed; font-weight: bold;'>800 86 00 22</a>
                    <span style='color: #6b7280;'> (24/7)</span>
                    <br>
                    <strong>Chat Online:</strong> 
                    <a href='https://www.telefonoamico.it' target='_blank' 
                       style='color: #7c3aed; font-weight: bold;'>www.telefonoamico.it</a>
                </div>
            </div>
            <p style='margin-top: 25px; font-size: 0.95em; font-style: italic; opacity: 0.9;'>
                💬 Puoi continuare la conversazione qui sotto, ma ti consigliamo di contattare 
                uno dei servizi sopra per supporto specializzato.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        logger.warning(f"BLACK emergency panel displayed (non-blocking)")
    
    elif level == EmergencyLevel.ORANGE:
        # COMPORTAMENTO ORANGE: Banner warning persistente
        st.warning(f"""
        **{rule['message']}**
        
        Utilizza la sezione "📍 Strutture Sanitarie Vicine" nella sidebar per trovare 
        il Pronto Soccorso più vicino con indicazioni stradali.
        """)
        logger.info(f"ORANGE warning banner displayed")

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

# PARTE 1: Lista comuni Emilia-Romagna per validazione
COMUNI_ER_VALIDI = {
    "bologna", "modena", "reggio emilia", "parma", "ferrara", "ravenna",
    "rimini", "forli", "cesena", "piacenza", "imola", "carpi", "cento",
    "faenza", "casalecchio", "san lazzaro", "medicina", "budrio", "lugo",
    "cervia", "riccione", "cattolica", "bellaria", "comacchio", "argenta"
}

# PARTE 1: Validatori Input per ogni Step
class InputValidator:
    """
    Validatori stateless per input utente in ogni step del triage.
    
    REGOLA ANTI-ALLUCINAZIONE:
    - Ogni validatore ritorna Tuple[bool, Optional[Any]]
    - bool = True se validazione OK, False altrimenti
    - Any = valore estratto/normalizzato se True, None se False
    - NO eccezioni sollevate: gestione errori interna
    """
    
    # Dizionario numeri scritti in italiano (0-100)
    WORD_TO_NUM = {
        "zero": 0, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
        "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
        "undici": 11, "dodici": 12, "tredici": 13, "quattordici": 14, "quindici": 15,
        "sedici": 16, "diciassette": 17, "diciotto": 18, "diciannove": 19,
        "venti": 20, "ventuno": 21, "ventidue": 22, "ventitre": 23, "ventiquattro": 24,
        "venticinque": 25, "ventisei": 26, "ventisette": 27, "ventotto": 28, "ventinove": 29,
        "trenta": 30, "trentuno": 31, "trentadue": 32, "trentatre": 33, "trentaquattro": 34,
        "trentacinque": 35, "quaranta": 40, "quarantacinque": 45, "cinquanta": 50,
        "cinquantacinque": 55, "sessanta": 60, "sessantacinque": 65, "settanta": 70,
        "settantacinque": 75, "ottanta": 80, "ottantacinque": 85, "novanta": 90,
        "novantacinque": 95, "cento": 100
    }
    
    @staticmethod
    def validate_location(user_input: str) -> Tuple[bool, Optional[str]]:
        """
        Valida che l'input sia un comune dell'Emilia-Romagna.
        
        Args:
            user_input: Testo grezzo dell'utente
        
        Returns:
            (True, "Comune Normalizzato") se valido
            (False, None) se non riconosciuto
        """
        if not user_input or not isinstance(user_input, str):
            return False, None
        
        input_clean = user_input.lower().strip()
        
        # Rimuovi articoli comuni
        input_clean = re.sub(r'\b(il|lo|la|i|gli|le|un|uno|una|di|a)\b', '', input_clean).strip()
        
        # Match esatto
        if input_clean in COMUNI_ER_VALIDI:
            return True, input_clean.title()
        
        # Match parziale (almeno 4 caratteri in comune)
        if len(input_clean) >= 4:
            for comune in COMUNI_ER_VALIDI:
                if input_clean in comune:
                    return True, comune.title()
                if comune in input_clean:
                    return True, comune.title()
                if len(input_clean) >= 5 and abs(len(input_clean) - len(comune)) <= 2:
                    diff = sum(1 for a, b in zip(input_clean, comune) if a != b)
                    if diff <= 2:
                        return True, comune.title()
        
        return False, None
    
    @staticmethod
    def validate_age(user_input: str) -> Tuple[bool, Optional[int]]:
        """
        Estrae età da testo libero (0-120 anni).
        
        Args:
            user_input: Testo grezzo (es. "ho 25 anni", "venticinque", "67")
        
        Returns:
            (True, età_int) se estratta ed entro range
            (False, None) se non trovata o fuori range
        """
        if not user_input or not isinstance(user_input, str):
            return False, None
        
        text_lower = user_input.lower().strip()
        
        # PRIORITÀ 1: Estrazione numeri diretti
        numbers = re.findall(r'\b(\d{1,3})\b', text_lower)
        for num_str in numbers:
            try:
                age = int(num_str)
                if 0 <= age <= 120:
                    if age < 10 and len(numbers) > 1:
                        continue
                    return True, age
            except ValueError:
                continue
        
        # PRIORITÀ 2: Numeri scritti in lettere
        for word, num in InputValidator.WORD_TO_NUM.items():
            if word in text_lower:
                if 0 <= num <= 120:
                    return True, num
        
        # PRIORITÀ 3: Keyword speciali
        if any(kw in text_lower for kw in ["neonato", "appena nato", "nato da poco"]):
            return True, 0
        
        if "bambino" in text_lower or "bambina" in text_lower:
            return True, 5
        
        if "adolescente" in text_lower or "teenager" in text_lower:
            return True, 15
        
        if any(kw in text_lower for kw in ["anziano", "anziana", "vecchio", "vecchia"]):
            return True, 75
        
        return False, None
    
    @staticmethod
    def validate_pain_scale(user_input: str) -> Tuple[bool, Optional[int]]:
        """
        Valida scala dolore 1-10 o converte descrittori qualitativi.
        
        Args:
            user_input: Testo grezzo (es. "8", "molto forte", "insopportabile")
        
        Returns:
            (True, valore_1_10) se riconosciuto
            (False, None) se non riconosciuto
        """
        if not user_input or not isinstance(user_input, str):
            return False, None
        
        text_lower = user_input.lower().strip()
        
        # PRIORITÀ 1: Numeri diretti 1-10
        numbers = re.findall(r'\b(\d{1,2})\b', text_lower)
        for num_str in numbers:
            try:
                pain = int(num_str)
                if 1 <= pain <= 10:
                    return True, pain
            except ValueError:
                continue
        
        # PRIORITÀ 2: Mappatura qualitativa
        pain_map = {
            "nessun": 0,
            "poco": 2,
            "leggero": 2,
            "lieve": 3,
            "sopportabile": 3,
            "moderato": 5,
            "medio": 5,
            "normale": 5,
            "forte": 7,
            "acuto": 7,
            "molto": 8,
            "intenso": 8,
            "grave": 8,
            "severo": 9,
            "insopportabile": 10,
            "estremo": 10,
            "lancinante": 10,
            "atroce": 10
        }
        
        for keyword, value in pain_map.items():
            if keyword in text_lower:
                if value == 0:
                    return True, 1
                return True, value
        
        # PRIORITÀ 3: Numeri scritti in lettere
        for word, num in InputValidator.WORD_TO_NUM.items():
            if word in text_lower and 1 <= num <= 10:
                return True, num
        
        return False, None
    
    @staticmethod
    def validate_red_flags(user_input: str) -> Tuple[bool, List[str]]:
        """
        Identifica presenza di red flags clinici nel testo.
        
        Args:
            user_input: Testo grezzo dell'utente
        
        Returns:
            (True, lista_red_flags) - sempre True, lista può essere vuota
        """
        if not user_input or not isinstance(user_input, str):
            return True, []
        
        red_flags = []
        text_lower = user_input.lower()
        
        flag_patterns = {
            "dolore_toracico": [
                r"dolore.{0,10}petto", r"dolore.{0,10}torace",
                r"oppressione.{0,10}petto", r"stretta.{0,10}petto",
                r"peso.{0,10}petto"
            ],
            "dispnea": [
                r"difficolt[aà].{0,15}respir", r"affanno", r"fiato corto",
                r"non.{0,10}riesco.{0,10}respir", r"soffoco", r"fame d'aria"
            ],
            "alterazione_coscienza": [
                r"confus[oa]", r"stordito", r"svenimento", r"perso.{0,10}sensi",
                r"coscienza alterata", r"non.{0,10}lucido"
            ],
            "emorragia": [
                r"sangue.{0,10}abbondante", r"emorragia", r"sanguino.{0,10}molto",
                r"perdit[ao].{0,10}sangue.{0,10}importante"
            ],
            "trauma_cranico": [
                r"battuto.{0,10}testa", r"trauma.{0,10}crani", r"caduta.{0,10}testa",
                r"colpo.{0,10}testa", r"botta.{0,10}testa.{0,10}forte"
            ],
            "dolore_addominale_acuto": [
                r"dolore.{0,10}addom.{0,10}acuto", r"pancia.{0,10}dolore.{0,10}forte",
                r"addome.{0,10}rigido", r"dolore.{0,10}pancia.{0,10}insopportabile"
            ],
            "paralisi": [
                r"non.{0,10}muovo", r"paralizzat[oa]", r"braccio.{0,10}bloccato",
                r"gamba.{0,10}non.{0,10}si muove", r"met[aà].{0,10}corpo.{0,10}bloccat"
            ],
            "convulsioni": [
                r"convulsion", r"crisi.{0,10}epilett", r"attacco.{0,10}epilett",
                r"spasmi", r"tremori.{0,10}incontrollabili"
            ]
        }
        
        for flag_name, patterns in flag_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    red_flags.append(flag_name)
                    break
        
        return True, red_flags

# PARTE 2: Modulo Geolocalizzazione
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcola distanza Great Circle tra due coordinate (formula Haversine).
    """
    if not (-90 <= lat1 <= 90) or not (-90 <= lat2 <= 90):
        raise ValueError(f"Latitude out of range: lat1={lat1}, lat2={lat2}")
    if not (-180 <= lon1 <= 180) or not (-180 <= lon2 <= 180):
        raise ValueError(f"Longitude out of range: lon1={lon1}, lon2={lon2}")
    
    R = 6371.0  # Raggio medio Terra (km)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def find_nearest_facilities(
    user_lat: float, user_lon: float,
    facility_type: str = "pronto_soccorso",
    max_results: int = 3, max_distance_km: float = 50.0
) -> List[Dict]:
    """
    Trova strutture sanitarie più vicine da master_kb.json.
    """
    try:
        with open("master_kb.json", 'r', encoding='utf-8') as f:
            kb = json.load(f)
    except FileNotFoundError:
        logger.error("master_kb.json not found in root directory")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"master_kb.json invalid JSON: {e}")
        return []
    
    facilities = kb.get(facility_type, [])
    if not facilities:
        logger.warning(f"No facilities found for type '{facility_type}'")
        return []
    
    enriched = []
    for facility in facilities:
        try:
            f_lat = float(facility.get('latitudine') or facility.get('lat', 0))
            f_lon = float(facility.get('longitudine') or facility.get('lon', 0))
            if f_lat == 0.0 and f_lon == 0.0:
                continue
            distance = haversine_distance(user_lat, user_lon, f_lat, f_lon)
            if distance <= max_distance_km:
                facility_copy = facility.copy()
                facility_copy['distance_km'] = round(distance, 2)
                enriched.append(facility_copy)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Skipping facility: {e}")
            continue
    
    enriched.sort(key=lambda x: x['distance_km'])
    logger.info(f"Found {len(enriched)} facilities within {max_distance_km}km")
    return enriched[:max_results]


def estimate_eta(distance_km: float, area_type: str = "urban") -> Dict[str, float]:
    """
    Stima tempo di arrivo (ETA) basato su velocità medie.
    """
    TORTUOSITY_FACTOR = 1.3
    SPEED_MAP = {"urban": 30.0, "suburban": 50.0, "rural": 70.0}
    
    real_distance = distance_km * TORTUOSITY_FACTOR
    avg_speed = SPEED_MAP.get(area_type, 50.0)
    duration_minutes = (real_distance / avg_speed) * 60
    
    return {
        "duration_minutes": round(duration_minutes, 1),
        "real_distance_km": round(real_distance, 2)
    }


def get_comune_coordinates(comune: str) -> Optional[Dict[str, float]]:
    """
    Ottiene coordinate geografiche di un comune ER.
    """
    COMUNI_COORDS = {
        "bologna": {"lat": 44.4949, "lon": 11.3426},
        "modena": {"lat": 44.6471, "lon": 10.9252},
        "parma": {"lat": 44.8015, "lon": 10.3279},
        "reggio emilia": {"lat": 44.6989, "lon": 10.6297},
        "ferrara": {"lat": 44.8381, "lon": 11.6197},
        "ravenna": {"lat": 44.4184, "lon": 12.2035},
        "rimini": {"lat": 44.0678, "lon": 12.5695},
        "forli": {"lat": 44.2225, "lon": 12.0408},
        "forlì": {"lat": 44.2225, "lon": 12.0408},
        "cesena": {"lat": 44.1396, "lon": 12.2431},
        "piacenza": {"lat": 45.0526, "lon": 9.6924},
        "imola": {"lat": 44.3534, "lon": 11.7142},
        "carpi": {"lat": 44.7842, "lon": 10.8867},
        "faenza": {"lat": 44.2858, "lon": 11.8814},
        "lugo": {"lat": 44.4203, "lon": 11.9098},
        "cervia": {"lat": 44.2619, "lon": 12.3476},
        "riccione": {"lat": 43.9990, "lon": 12.6556},
        "cattolica": {"lat": 43.9636, "lon": 12.7392},
        "cento": {"lat": 44.7289, "lon": 11.2892},
        "sassuolo": {"lat": 44.5433, "lon": 10.7844},
        "casalecchio di reno": {"lat": 44.4816, "lon": 11.2783},
        "san lazzaro di savena": {"lat": 44.4651, "lon": 11.4087},
        "fidenza": {"lat": 44.8654, "lon": 10.0604},
        "correggio": {"lat": 44.7713, "lon": 10.7803},
        "formigine": {"lat": 44.5764, "lon": 10.8506}
    }
    
    comune_normalized = comune.lower().strip()
    coords = COMUNI_COORDS.get(comune_normalized)
    
    if coords:
        logger.info(f"Coordinates found for '{comune}': {coords}")
    else:
        logger.warning(f"No coordinates for comune '{comune}'")
    
    return coords


def get_area_type_from_comune(comune: str) -> str:
    """
    Determina tipo area (urban/suburban/rural) basato su comune.
    """
    urban_cities = [
        "bologna", "modena", "parma", "reggio emilia", "ferrara",
        "ravenna", "rimini", "forli", "forlì", "cesena", "piacenza"
    ]
    suburban_cities = [
        "imola", "carpi", "sassuolo", "faenza", "lugo", "cervia",
        "cesenatico", "riccione", "cattolica", "fidenza", "correggio"
    ]
    
    comune_lower = comune.lower().strip()
    if comune_lower in urban_cities:
        return "urban"
    elif comune_lower in suburban_cities:
        return "suburban"
    return "rural"

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

    # PARTE 2: System Prompt con Schema JSON Vincolante
    def _get_system_prompt(self, phase: str, is_sensitive: bool) -> str:
        """
        Genera system prompt con schema JSON OBBLIGATORIO per ridurre allucinazioni.
        """
        prompt = (
            "🚨 **REGOLA ASSOLUTA**: Rispondi SOLO con oggetto JSON valido.\n"
            "❌ VIETATO: Testo prima/dopo JSON, spiegazioni, note.\n\n"
            
            "📋 **SCHEMA JSON OBBLIGATORIO**:\n"
            "```json\n"
            "{\n"
            '  "testo": "Domanda in italiano (max 200 char)",\n'
            '  "tipo_domanda": "survey" | "scale" | "text",\n'
            '  "opzioni": ["Opzione1", "Opzione2", "Opzione3"] | null,\n'
            '  "metadata": {\n'
            '    "urgenza": 1 | 2 | 3 | 4 | 5,\n'
            '    "area": "Trauma" | "Medica" | "Cardiologica" | "Neurologica" | "Pediatrica" | "Psichiatrica",\n'
            '    "red_flags": ["flag1", "flag2"] | [],\n'
            '    "confidence": 0.0-1.0\n'
            '  }\n'
            "}\n"
            "```\n\n"
            
            "📌 **REGOLE TIPO_DOMANDA**:\n"
            '- "survey" → opzioni DEVE essere array [min 2, max 5 elementi]\n'
            '- "scale" → chiedi numero (es. "1-10"), opzioni = null\n'
            '- "text" → input libero, opzioni = null\n\n'
            
            "📊 **SCALA URGENZA** (obbligatorio, no 0):\n"
            "1 = Non urgente (follow-up giorni)\n"
            "2 = Bassa (valutazione 24-48h)\n"
            "3 = Moderata (valutazione stessa giornata)\n"
            "4 = Alta (Pronto Soccorso entro 2h)\n"
            "5 = Critica (118 immediato)\n"
            "⚠️ Se incerto → usa urgenza=3, confidence=0.5\n\n"
            
            "❌ **DIVIETI ASSOLUTI**:\n"
            "- NON diagnosticare ('Hai la polmonite' → VIETATO)\n"
            "- NON prescrivere farmaci\n"
            "- NON dare certezze ('È sicuramente...' → VIETATO)\n"
            "- Ruolo: SOLO raccolta info + valutazione urgenza\n\n"
            
            "✅ **ESEMPIO VALIDO**:\n"
            '{"testo": "Il dolore si irradia al braccio sinistro?", '
            '"tipo_domanda": "survey", '
            '"opzioni": ["Sì", "No", "Non so"], '
            '"metadata": {"urgenza": 4, "area": "Cardiologica", "red_flags": ["dolore_toracico"], "confidence": 0.85}}\n\n'
        )
        
        if is_sensitive:
            prompt += (
                "⚠️ **MODALITÀ EMERGENZA**:\n"
                "- Rilevato contenuto sensibile\n"
                "- MAX 2 domande essenziali\n"
                "- Se confermato rischio → urgenza=5\n"
                "- Tono empatico ma conciso\n\n"
            )
        
        phase_map = {
            "LOCATION": "Chiedi SOLO comune. Se fuori ER → chiedi comune ER più vicino.",
            "CHIEF_COMPLAINT": "Un sintomo principale. Max 5 opzioni + 'Altro'.",
            "PAIN_SCALE": "Intensità 1-10. Tipo 'scale', opzioni=null.",
            "RED_FLAGS": "Domande Sì/No: dispnea, dolore torace, confusione, emorragia.",
            "ANAMNESIS": "Una domanda: età O farmaci O allergie O patologie.",
            "DISPOSITION": "NON chiedere. Riassumi e raccomanda (CAU/PS/Medico Base)."
        }
        
        if phase in phase_map:
            prompt += f"🎯 **FASE {phase}**: {phase_map[phase]}\n"
        
        return prompt

    def call_ai(self, messages: List[Dict], phase: str) -> Generator[Union[str, Dict], None, None]:
        last_input = messages[-1]["content"]
        # PARTE 1: Check emergenze (sostituisce SENSITIVE_KEYWORDS)
        emergency_level = assess_emergency_level(last_input, {})
        is_sensitive = emergency_level in [EmergencyLevel.BLACK, EmergencyLevel.RED]
        
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

        # PARTE 2: Retry Loop con Schema Validation
        if not success:
            fail_msg = {"testo": "Servizio AI momentaneamente non disponibile. Chiamare il 118 in caso di urgenza.", "metadata": {"error": True}}
            yield fail_msg
            return

        final_data = None
        max_retries = 2
        
        for attempt in range(max_retries):
            final_data = JSONExtractor.extract(full_response)
            
            # Validazione schema JSON
            if final_data and isinstance(final_data, dict):
                # Clamp urgenza 1-5
                metadata = final_data.get("metadata", {})
                if "urgenza" in metadata:
                    urgenza = metadata["urgenza"]
                    if isinstance(urgenza, (int, float)):
                        metadata["urgenza"] = max(1, min(5, int(urgenza)))
                    else:
                        metadata["urgenza"] = 3
                else:
                    metadata["urgenza"] = 3
                
                # Clamp confidence 0-1
                if "confidence" in metadata:
                    confidence = metadata["confidence"]
                    if isinstance(confidence, (int, float)):
                        metadata["confidence"] = max(0.0, min(1.0, float(confidence)))
                    else:
                        metadata["confidence"] = 0.5
                else:
                    metadata["confidence"] = 0.5
                
                final_data["metadata"] = metadata
                
                # Valida opzioni per tipo_domanda
                tipo = final_data.get("tipo_domanda", "text")
                opzioni = final_data.get("opzioni")
                
                if tipo == "survey" and (not opzioni or not isinstance(opzioni, list) or len(opzioni) < 2):
                    logger.warning(f"Invalid survey options on attempt {attempt + 1}, retrying...")
                    if attempt < max_retries - 1:
                        continue
                    # Fallback su ultimo tentativo
                    logger.error("AI retry exhausted, using fallback options")
                    try:
                        current_step = st.session_state.current_step
                        final_data["opzioni"] = get_fallback_options(current_step)
                        final_data["metadata"]["fallback_used"] = True
                    except:
                        final_data["opzioni"] = ["Sì", "No", "Non so"]
                
                # Schema valido, esci dal loop
                break
            else:
                logger.warning(f"JSON extraction failed on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
                # Fallback finale
                final_data = {"testo": full_response, "tipo_domanda": "text", "opzioni": None, "metadata": {"urgenza": 3, "confidence": 0.5}}
                break
        
        if not final_data:
            final_data = {"testo": full_response, "tipo_domanda": "text", "opzioni": None, "metadata": {"urgenza": 3, "confidence": 0.5}}
        
        yield final_data


# PARTE 2: Opzioni Fallback Predefinite (non arbitrarie)
def get_fallback_options(step: TriageStep) -> List[str]:
    """
    Restituisce opzioni predefinite per step se AI fallisce.
    """
    FALLBACK_MAP = {
        TriageStep.LOCATION: [
            "Bologna", "Modena", "Parma", "Reggio Emilia",
            "Ferrara", "Ravenna", "Rimini", "Altro comune ER"
        ],
        TriageStep.CHIEF_COMPLAINT: [
            "Dolore", "Febbre", "Trauma/Caduta",
            "Difficoltà respiratorie", "Problemi gastrointestinali", "Altro sintomo"
        ],
        TriageStep.PAIN_SCALE: [
            "1-3 (Lieve/Sopportabile)", "4-6 (Moderato)",
            "7-8 (Forte)", "9-10 (Insopportabile)", "Nessun dolore"
        ],
        TriageStep.RED_FLAGS: [
            "Sì, ho sintomi gravi", "No, nessun sintomo preoccupante", "Non sono sicuro/a"
        ],
        TriageStep.ANAMNESIS: [
            "Fornisco informazioni", "Preferisco non rispondere", "Non applicabile"
        ],
        TriageStep.DISPOSITION: ["Mostra raccomandazione finale"]
    }
    
    options = FALLBACK_MAP.get(step, ["Continua", "Annulla"])
    logger.info(f"Fallback options for {step.name}: {len(options)} choices")
    return options

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
        
        # PARTE 2: Expander Strutture Sanitarie Vicine con Geolocalizzazione
        with st.expander("📍 Strutture Sanitarie Vicine"):
            comune_input = st.text_input("Inserisci Comune:", key="geo_comune", placeholder="es. Bologna")
            
            facility_type_map = {
                "Pronto Soccorso": "pronto_soccorso",
                "CAU (Continuità Assistenziale)": "cau",
                "Guardia Medica": "guardia_medica",
                "Farmacie": "farmacie"
            }
            facility_label = st.selectbox("Tipo struttura:", list(facility_type_map.keys()), key="facility_type_select")
            facility_type = facility_type_map[facility_label]
            
            col1, col2 = st.columns(2)
            max_distance = col1.slider("Raggio massimo (km)", 5, 100, 50, key="max_dist_slider")
            max_results = col2.slider("Max risultati", 1, 10, 3, key="max_results_slider")
            
            if st.button("🔍 Cerca Strutture", use_container_width=True):
                if comune_input:
                    coords = get_comune_coordinates(comune_input)
                    if coords:
                        user_lat = coords["lat"]
                        user_lon = coords["lon"]
                        
                        facilities = find_nearest_facilities(
                            user_lat, user_lon,
                            facility_type=facility_type,
                            max_results=max_results,
                            max_distance_km=max_distance
                        )
                        
                        if facilities:
                            st.success(f"✅ Trovate {len(facilities)} strutture")
                            
                            area_type = get_area_type_from_comune(comune_input)
                            
                            # Mostra card risultati
                            for idx, facility in enumerate(facilities, 1):
                                distance = facility.get('distance_km', 0)
                                eta = estimate_eta(distance, area_type)
                                
                                with st.container():
                                    st.markdown(f"**{idx}. {facility.get('nome', 'N/D')}**")
                                    st.markdown(f"📍 {facility.get('indirizzo', 'N/D')} - {facility.get('comune', 'N/D')}")
                                    st.markdown(f"📞 {facility.get('telefono', 'N/D')}")
                                    if facility.get('orari'):
                                        st.markdown(f"🕒 {facility['orari']}")
                                    if facility.get('H24'):
                                        st.markdown("🟢 **Aperto H24**")
                                    st.markdown(f"🚗 Distanza: **{distance} km** - ETA: **~{eta['duration_minutes']} min**")
                                    st.divider()
                            
                            # Mappa Folium
                            m = folium.Map(location=[user_lat, user_lon], zoom_start=11)
                            
                            # Marker utente (blu)
                            folium.Marker(
                                [user_lat, user_lon],
                                popup=f"📍 La tua posizione<br>{comune_input}",
                                icon=folium.Icon(color="blue", icon="home", prefix="fa")
                            ).add_to(m)
                            
                            # Marker strutture (rosso)
                            for facility in facilities:
                                f_lat = facility.get('latitudine') or facility.get('lat')
                                f_lon = facility.get('longitudine') or facility.get('lon')
                                if f_lat and f_lon:
                                    popup_text = (
                                        f"<b>{facility.get('nome', 'N/D')}</b><br>"
                                        f"{facility.get('indirizzo', 'N/D')}<br>"
                                        f"📞 {facility.get('telefono', 'N/D')}<br>"
                                        f"🚗 {facility.get('distance_km', 0)} km"
                                    )
                                    folium.Marker(
                                        [f_lat, f_lon],
                                        popup=folium.Popup(popup_text, max_width=300),
                                        icon=folium.Icon(color="red", icon="plus", prefix="fa")
                                    ).add_to(m)
                            
                            st_folium(m, height=400, width=700)
                        else:
                            st.warning(f"⚠️ Nessuna struttura trovata entro {max_distance}km da {comune_input}")
                    else:
                        st.error(f"❌ Comune '{comune_input}' non riconosciuto. Usa comuni dell'Emilia-Romagna.")
                else:
                    st.warning("⚠️ Inserisci un comune per iniziare la ricerca")

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
# PARTE 1: Session State con State Machine
def init_session():
    """
    Inizializza stato sessione con supporto State Machine.
    
    CAMPI NUOVI (PARTE 1):
    - current_step: TriageStep enum (step corrente)
    - collected_data: Dict con dati validati per ogni step
    - step_completed: Dict[TriageStep, bool] (tracking completamenti)
    - step_timestamps: Dict con timing per analytics
    - session_start: Timestamp inizio sessione
    - ai_retry_count: Dict per tracking retry AI per fase
    """
    if "session_id" not in st.session_state:
        # ID sessione univoco
        st.session_state.session_id = str(uuid.uuid4())
        
        # Cronologia messaggi (invariato)
        st.session_state.messages = []
        
        # NUOVO: State Machine
        st.session_state.current_step = TriageStep.LOCATION
        st.session_state.collected_data = {}  # {step_name: validated_value}
        st.session_state.step_completed = {step: False for step in TriageStep}
        
        # NUOVO: Tracking temporale
        st.session_state.step_timestamps = {}  # {step_name: {'start': dt, 'end': dt}}
        st.session_state.session_start = datetime.now()
        
        # Campi esistenti (mantieni)
        st.session_state.current_phase_idx = 0
        st.session_state.pending_survey = None
        st.session_state.critical_alert = False
        st.session_state.gdpr_consent = False
        st.session_state.specialization = "Generale"
        st.session_state.metadata_history = []
        st.session_state.backend = BackendClient()
        
        # NUOVO: Retry tracking per AI
        st.session_state.ai_retry_count = {}
        
        # NUOVO: Livello emergenza corrente
        st.session_state.emergency_level = None
        
        logger.info(f"New session initialized: {st.session_state.session_id}")

# PARTE 1: Funzioni Gestione State Machine
def can_proceed_to_next_step() -> bool:
    """
    Verifica se lo step corrente è completato e validato.
    
    Returns:
        True se collected_data contiene valore validato per current_step
        False altrimenti
    """
    current_step = st.session_state.current_step
    step_name = current_step.name
    
    # Check se esiste dato validato per questo step
    has_data = step_name in st.session_state.collected_data
    
    # Step DISPOSITION è speciale: si completa automaticamente
    if current_step == TriageStep.DISPOSITION:
        return True
    
    logger.debug(f"can_proceed_to_next_step: step={step_name}, has_data={has_data}")
    return has_data


def advance_step() -> bool:
    """
    Avanza allo step successivo del triage con validazione.
    
    Returns:
        True se avanzamento riuscito
        False se step corrente non completato
    """
    if not can_proceed_to_next_step():
        st.warning("⚠️ Completa le informazioni richieste prima di procedere")
        logger.warning(f"advance_step blocked: step {st.session_state.current_step.name} not completed")
        return False
    
    current_step = st.session_state.current_step
    current_value = current_step.value
    
    # Salva timestamp completamento
    st.session_state.step_timestamps[current_step.name] = {
        'start': st.session_state.get(f'{current_step.name}_start_time', datetime.now()),
        'end': datetime.now()
    }
    
    # Marca come completato
    st.session_state.step_completed[current_step] = True
    
    # Avanza solo se non è l'ultimo step
    if current_value < len(TriageStep):
        next_step = TriageStep(current_value + 1)
        st.session_state.current_step = next_step
        
        # Inizia timer nuovo step
        st.session_state[f'{next_step.name}_start_time'] = datetime.now()
        
        # Feedback visivo
        st.toast(f"✅ Completato: {current_step.name}", icon="✅")
        
        logger.info(f"Advanced from {current_step.name} to {next_step.name}")
    else:
        logger.info(f"Triage completed: all steps done")
    
    return True


# PARTE 2: Logging Strutturato per Backend Analytics
def save_structured_log():
    """
    Salva log sessione in formato strutturato JSON per analytics.
    Schema version "2.0" per distinguere dal vecchio formato.
    """
    if not st.session_state.get("gdpr_consent", False):
        logger.info("Skipping log save: GDPR consent not given")
        return
    
    try:
        session_end = datetime.now()
        session_start = st.session_state.session_start
        total_duration = (session_end - session_start).total_seconds()
        
        steps_data = []
        for step in TriageStep:
            step_name = step.name
            if step_name in st.session_state.step_timestamps:
                ts_data = st.session_state.step_timestamps[step_name]
                duration = (ts_data['end'] - ts_data['start']).total_seconds()
                steps_data.append({
                    "step_name": step_name,
                    "duration_seconds": round(duration, 2),
                    "data_collected": st.session_state.collected_data.get(step_name),
                    "timestamp_start": ts_data['start'].isoformat(),
                    "timestamp_end": ts_data['end'].isoformat()
                })
        
        clinical_summary = {
            "chief_complaint": st.session_state.collected_data.get('CHIEF_COMPLAINT'),
            "pain_severity": st.session_state.collected_data.get('PAIN_SCALE'),
            "red_flags": st.session_state.collected_data.get('RED_FLAGS', []),
            "age": st.session_state.collected_data.get('age'),
            "location": st.session_state.collected_data.get('LOCATION')
        }
        
        disposition_data = st.session_state.collected_data.get('DISPOSITION', {})
        outcome = {
            "disposition": disposition_data.get('type', 'Non Completato'),
            "urgency_level": disposition_data.get('urgency', 0),
            "facility_recommended": disposition_data.get('facility_name'),
            "distance_km": disposition_data.get('distance'),
            "eta_minutes": disposition_data.get('eta')
        }
        
        metadata = {
            "specialization": st.session_state.specialization,
            "emergency_triggered": st.session_state.emergency_level is not None,
            "emergency_level": st.session_state.emergency_level.name if st.session_state.emergency_level else None,
            "ai_fallback_used": any("fallback" in str(m) for m in st.session_state.metadata_history),
            "total_messages": len(st.session_state.messages)
        }
        
        log_entry = {
            "session_id": st.session_state.session_id,
            "timestamp_start": session_start.isoformat(),
            "timestamp_end": session_end.isoformat(),
            "total_duration_seconds": round(total_duration, 2),
            "steps": steps_data,
            "clinical_summary": clinical_summary,
            "outcome": outcome,
            "metadata": metadata,
            "version": "2.0"
        }
        
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        logger.info(f"Structured log saved: session={st.session_state.session_id}")
    
    except Exception as e:
        logger.error(f"Failed to save structured log: {e}", exc_info=True)


def get_step_display_name(step: TriageStep) -> str:
    """
    Ottiene nome human-readable per step.
    
    Args:
        step: TriageStep enum
    
    Returns:
        Stringa descrittiva in italiano
    """
    names = {
        TriageStep.LOCATION: "Localizzazione Geografica",
        TriageStep.CHIEF_COMPLAINT: "Sintomo Principale",
        TriageStep.PAIN_SCALE: "Valutazione Intensità",
        TriageStep.RED_FLAGS: "Screening Emergenze",
        TriageStep.ANAMNESIS: "Anamnesi Clinica",
        TriageStep.DISPOSITION: "Verdetto e Raccomandazioni"
    }
    return names.get(step, step.name)

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
    
    # PARTE 2: Salvataggio log strutturato se DISPOSITION completato
    if st.session_state.current_step == TriageStep.DISPOSITION and \
       st.session_state.step_completed.get(TriageStep.DISPOSITION, False):
        save_structured_log()
        st.success("✅ Triage completato. Dati salvati per analisi sanitaria.")

    if not st.session_state.pending_survey:
        if raw_input := st.chat_input("Descrivi i sintomi..."):
            user_input = DataSecurity.sanitize_input(raw_input)
            
            # PARTE 1: Check emergenze (sostituisce SENSITIVE_KEYWORDS)
            emergency_level = assess_emergency_level(user_input, {})
            if emergency_level:
                st.session_state.emergency_level = emergency_level
                if emergency_level == EmergencyLevel.BLACK:
                    st.session_state.critical_alert = True
                render_emergency_overlay(emergency_level)
            
            st.session_state.messages.append({"role": "user", "content": user_input})

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
                    
                    # PARTE 1: Check emergenze con metadata AI
                    metadata = final_obj.get("metadata", {})
                    emergency_level = assess_emergency_level(user_input, metadata)
                    if emergency_level:
                        st.session_state.emergency_level = emergency_level
                        render_emergency_overlay(emergency_level)
                    
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
