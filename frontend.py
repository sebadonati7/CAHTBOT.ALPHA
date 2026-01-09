import streamlit as st
import json
import time
import uuid
import os
import random
import re
import requests
import math
import difflib  # Aggiunta per il matching dei comuni
import logging

# Configurazione base del logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from datetime import datetime

# ============================================
# IMPORT SESSION STORAGE
# ============================================
try:
    from session_storage import get_storage, sync_session_to_storage, load_session_from_storage
    SESSION_STORAGE_ENABLED = True
    logger.info("✅ Session Storage caricato con successo")
except ImportError as e:
    SESSION_STORAGE_ENABLED = False
    logger.warning(f"⚠️ Session Storage non disponibile: {e}")

# ============================================
# IMPORT FSM DA PR #7
# ============================================
try:
    from models import (
        TriageState, 
        TriagePath, 
        TriagePhase, 
        TriageBranch,
        PatientInfo,
        ClinicalData,
        TriageMetadata,
        DispositionRecommendation
    )
    from bridge import TriageSessionBridge
    from smart_router import SmartRouter, UrgencyScore
    from utils.id_manager import IDManager
    from utils. symptom_normalizer import SymptomNormalizer
    
    FSM_ENABLED = True
    logger.info("✅ Moduli FSM caricati con successo (PR #7)")
except ImportError as e:
    FSM_ENABLED = False
    logger.warning(f"⚠️ FSM non disponibile - usando logica legacy: {e}")
    logger.info("💡 Verifica che i file models.py, bridge.py, smart_router.py esistano")

# --- TIPIZZAZIONE E STRUTTURE DATI ---
from typing import List, Dict, Any, Optional, Union, Generator, Tuple, Callable
from enum import Enum

# --- GESTIONE RETE E API ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import groq
# --- LOGICA DI RICERCA SANITARIA TERRITORIALE ---

def get_all_available_services():
    """Analizza tutti i JSON e crea un catalogo unico di servizi e tipologie."""
    catalog = set()
    files = ["master_kb.json", "FARMACIE_EMILIA.json", "FARMACIE_ROMAGNA.json"]
    
    for f_name in files:
        if os.path.exists(f_name):
            try:
                with open(f_name, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Gestione strutture (master_kb ha chiave 'facilities') o farmacie (lista)
                    items = data.get('facilities', []) if isinstance(data, dict) else data
                    for item in items:
                        if item.get('tipologia'): catalog.add(item['tipologia'])
                        for s in item.get('servizi_disponibili', []):
                            catalog.add(s)
            except: continue
    return sorted([s for s in catalog if s])

def find_facilities_smart(query_service, query_comune):
    """
    Ricerca gerarchica e 'Filtro Intelligente': 
    3=Stesso Comune, 2=Stesso Distretto, 1=Stessa Provincia.
    Implementa substring matching per trovare 'visita' in 'visita ginecologica'.
    """
    results = []
    files = ["master_kb.json", "FARMACIE_EMILIA.json", "FARMACIE_ROMAGNA.json"]
    
    all_items = []
    for f_name in files:
        if os.path.exists(f_name):
            with open(f_name, 'r', encoding='utf-8') as f:
                d = json.load(f)
                all_items.extend(d.get('facilities', []) if isinstance(d, dict) else d)

    qs = query_service.lower()
    qc = query_comune.lower()

    for item in all_items:
        # Match servizio/tipologia (Logica 'Fuzzy' e Substring)
        servizi = [s.lower() for s in item.get('servizi_disponibili', [])]
        tipo = item.get('tipologia', '').lower()
        
        # Verifica se la query è contenuta nel tipo o in uno dei servizi (es: 'visita' in 'visita medica')
        match_servizio = qs in tipo or any(qs in s for s in servizi)
        
        if match_servizio:
            score = 0
            # Punteggio vicinanza basato su testo
            item_comune = item.get('comune', '').lower()
            item_dist = item.get('distretto', '').lower()
            item_prov = item.get('provincia', '').lower()

            if qc == item_comune: score = 3
            elif qc in item_dist or item_dist in qc: score = 2
            elif qc in item_prov or item_prov in qc: score = 1
            
            if score > 0:
                results.append({"data": item, "score": score})

    # Ordina per score di prossimità e limita a 5
    results.sort(key=lambda x: x['score'], reverse=True)
    return [r['data'] for r in results[:5]]

def make_gmaps_link(item):
    """Crea URL Google Maps pulito senza bisogno di coordinate."""
    q = f"{item.get('nome','')} {item.get('indirizzo','')} {item.get('comune','')}"
    # Formattazione URL corretta per la ricerca
    query_encoded = q.replace(' ', '+').replace(',', '+')
    return f"[https://www.google.com/maps/search/?api=1&query=](https://www.google.com/maps/search/?api=1&query=){query_encoded}"

def make_gmaps_link(item):
    """Crea URL Google Maps pulito senza bisogno di coordinate."""
    q = f"{item.get('nome','')} {item.get('indirizzo','')} {item.get('comune','')}"
    # Formattazione URL corretta
    query_encoded = q.replace(' ', '+').replace(',', '+')
    return f"[https://www.google.com/maps/search/?api=1&query=](https://www.google.com/maps/search/?api=1&query=){query_encoded}"

# --- CONFIGURAZIONE LOGGING E AMBIENTE ---
# (Qui puoi procedere con la configurazione del logging o della pagina Streamlit)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="AI Health Navigator - Professional Triage",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded"
)
# Inizializzazione Catalogo Servizi nello Session State
if 'service_catalog' not in st.session_state:
    try:
        st.session_state.service_catalog = get_all_available_services()
        logger.info(f"Catalogo servizi pronto: {len(st.session_state.service_catalog)} voci.")
    except Exception as e:
        # Fallback se i file mancano
        st.session_state.service_catalog = ["Pronto Soccorso", "CAU", "Guardia Medica", "Farmacia"]

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
    "triage": "llama-3.3-70b-versatile",
    "complex": "llama-3.1-8b-instant",  
    "fallback": "gemini-2.5-flash" 
}

LOG_FILE = "triage_logs.jsonl"

PHASES = [
    {"id": "IDENTIFICATION", "name": "Identificazione", "icon": "👤"},
    {"id": "ANAMNESIS", "name": "Analisi Sintomi", "icon": "🔍"},
    {"id": "SAFETY_CHECK", "name": "Protocolli Sicurezza", "icon": "🛡️"},
    {"id": "LOGISTICS", "name": "Supporto Territoriale", "icon": "📍"},
    {"id": "DISPOSITION", "name": "Conclusione Triage", "icon": "🏥"}
]
# --- CARICAMENTO DATASET COMUNI EMILIA-ROMAGNA ---
def load_comuni_er(filepath="mappa_er.json"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            geoms = data.get("objects", {}).get("comuni", {}).get("geometries", [])
            return {g["properties"]["name"].lower().strip() for g in geoms if "name" in g["properties"]}
    except Exception as e:
        logger.error(f"Errore caricamento mappa: {e}")
        return {"bologna", "modena", "parma", "reggio emilia", "ferrara", "ravenna", "rimini", "forlì", "piacenza", "cesena"}

COMUNI_ER_VALIDI = load_comuni_er()

def is_valid_comune_er(comune: str) -> bool:
    if not comune or not isinstance(comune, str):
        return False
    
    nome = comune.lower().strip()
    
    if nome in COMUNI_ER_VALIDI:
        return True
    
    # Controllo intelligente per accenti e piccoli refusi
    matches = difflib.get_close_matches(nome, list(COMUNI_ER_VALIDI), n=1, cutoff=0.8)
    return len(matches) > 0



# ============================================
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

# --- PARTE 2: Opzioni Fallback Predefinite ---
TRIAGE_FALLBACK_OPTIONS = {
    "LOCATION": ["Bologna", "Modena", "Parma", "Reggio Emilia", "Ferrara", "Ravenna", "Rimini", "Altro comune ER"],
    "CHIEF_COMPLAINT": ["Dolore", "Febbre", "Trauma/Caduta", "Difficoltà respiratorie", "Problemi gastrointestinali", "Altro sintomo"],
    "PAIN_SCALE": ["1-3 (Lieve)", "4-6 (Moderato)", "7-8 (Forte)", "9-10 (Insopportabile)", "Nessun dolore"],
    "RED_FLAGS": ["Sì, ho sintomi gravi", "No, nessun sintomo preoccupante", "Non sono sicuro/a"],
    "ANAMNESIS": ["Fornisco informazioni", "Preferisco non rispondere", "Non applicabile"],
    "DISPOSITION": ["Mostra raccomandazione finale"]
}

def get_fallback_options(step: TriageStep) -> List[str]:
    """Recupera le opzioni di emergenza se l'AI non risponde correttamente."""
    options = TRIAGE_FALLBACK_OPTIONS.get(step.name, ["Continua", "Annulla"])
    logger.info(f"Fallback attivato per {step.name}")
    return options
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
    Mostra un'interfaccia di avviso non bloccante per emergenze RED, ORANGE o BLACK.
    Unifica la gestione delle urgenze mediche e del supporto psicologico.
    """
    rule = EMERGENCY_RULES.get(level, {"message": "Si consiglia cautela."})
    
    # --- CASO 1: URGENZA MEDICA (RED o ORANGE) ---
    if level in [EmergencyLevel.RED, EmergencyLevel.ORANGE]:
        is_red = (level == EmergencyLevel.RED)
        
        # Configurazione UI dinamica
        config = {
            EmergencyLevel.RED: {
                "color": "#dc2626", "icon": "🚨", 
                "title": "Suggerimento di Urgenza Critica",
                "advice": f"In base ai sintomi ({rule['message']}), ti suggeriamo di **contattare il 118** immediatamente.",
                "btn_label": "📞 CHIAMA 118 ORA", "btn_link": "tel:118"
            },
            EmergencyLevel.ORANGE: {
                "color": "#f97316", "icon": "⚠️", 
                "title": "Suggerimento di Urgenza",
                "advice": f"La tua situazione ({rule['message']}) suggerisce l'opportunità di una valutazione in **Pronto Soccorso**.",
                "btn_label": "🏥 TROVA PRONTO SOCCORSO",
                "btn_link": f"https://www.google.com/maps/search/pronto+soccorso+{st.session_state.get('collected_data', {}).get('location', '')}".strip()
            }
        }
        
        cfg = config[level]

        # Rendering del Box di Avviso
        st.markdown(f"""
            <div style='border-left: 10px solid {cfg['color']}; background: white; padding: 25px; 
                        border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); margin: 20px 0;'>
                <div style='display: flex; align-items: center; margin-bottom: 15px;'>
                    <span style='font-size: 2.5em; margin-right: 20px;'>{cfg['icon']}</span>
                    <h3 style='color: {cfg['color']}; margin: 0;'>{cfg['title']}</h3>
                </div>
                <p style='font-size: 1.15em; color: #1f2937; line-height: 1.6;'>{cfg['advice']}</p>
                <hr style='margin: 15px 0; border: 0; border-top: 1px solid #eee;'>
                <p style='font-size: 0.85em; color: #6b7280; font-style: italic;'>
                    Questo è un assistente digitale. Non sostituisce un parere medico professionale. 
                    Puoi proseguire la conversazione per fornire ulteriori dettagli.
                </p>
            </div>
        """, unsafe_allow_html=True)

        # Pulsanti d'azione
        col_btn, col_info = st.columns([1, 1])
        with col_btn:
            st.link_button(cfg['btn_label'], cfg['btn_link'], type="primary", use_container_width=True)
        with col_info:
            st.info("La conversazione rimane attiva se desideri scrivermi altro.")

        logger.info(f"Visualizzato alert {level.name}")

    # --- CASO 2: SUPPORTO PSICOLOGICO (BLACK) ---
    elif level == EmergencyLevel.BLACK:
        st.markdown(f"""
            <div style='background: linear-gradient(135deg, #7c3aed 0%, #5b21b6 100%); 
                        color: white; padding: 35px; border-radius: 20px; margin: 25px 0;'>
                <h2 style='margin: 0 0 20px 0;'>🆘 Non sei solo/a</h2>
                <p style='font-size: 1.2em; margin-bottom: 25px;'>{rule['message']}</p>
                <div style='background: white; color: #1f2937; padding: 25px; border-radius: 15px;'>
                    <h4 style='color: #7c3aed; margin-top: 0;'>Contatti di supporto immediato:</h4>
                    <ul style='list-style: none; padding: 0; line-height: 2;'>
                        <li><strong>Telefono Amico:</strong> <a href='tel:0223272327'>02 2327 2327</a></li>
                        <li><strong>Numero Antiviolenza:</strong> <a href='tel:1522'>1522</a></li>
                        <li><strong>Samaritans:</strong> <a href='tel:800860022'>800 86 00 22</a></li>
                    </ul>
                </div>
            </div>
        """, unsafe_allow_html=True)
        logger.warning("Visualizzato pannello di supporto psicologico (BLACK)")
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



class InputValidator:
    """
    Validatori stateless per la normalizzazione dell'input utente.
    Gestisce la pulizia dei dati locali prima dell'eventuale fallback su LLM.
    """
    
    # Mappatura minima per numeri comuni scritti a parole
    WORD_TO_NUM = {
        "zero": 0, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
        "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
        "venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50, 
        "sessanta": 60, "settanta": 70, "ottanta": 80, "novanta": 90, "cento": 100
    }

    @staticmethod
    def validate_location(user_input: str) -> Tuple[bool, Optional[str]]:
        """Valida il comune ER usando fuzzy matching per correggere piccoli refusi."""
        if not user_input: return False, None
        
        # Pulizia base e rimozione articoli iniziali
        target = user_input.lower().strip()
        target = re.sub(r'^(il|lo|la|i|gli|le|a|di)\s+', '', target)
        
        # Controllo esatto (Veloce)
        if target in COMUNI_ER_VALIDI:
            return True, target.title()
        
        # Fuzzy matching (Intelligente) - Gestisce accenti e piccoli errori
        matches = difflib.get_close_matches(target, list(COMUNI_ER_VALIDI.keys()), n=1, cutoff=0.8)
        return (True, matches[0].title()) if matches else (False, None)

    @staticmethod
    def validate_age(user_input: str) -> Tuple[bool, Optional[int]]:
        """Estrae l'età (0-120) da numeri arabi, parole o categorie."""
        if not user_input: return False, None
        text = user_input.lower()
        
        # 1. Ricerca numeri (es. "ho 45 anni")
        nums = re.findall(r'\b(\d{1,3})\b', text)
        if nums:
            age = int(nums[0])
            if 0 <= age <= 120: return True, age
            
        # 2. Ricerca numeri a parole (es. "trenta")
        for word, val in InputValidator.WORD_TO_NUM.items():
            if word in text: return True, val
            
        # 3. Categorie generazionali (Fallback rapido)
        if "bambin" in text: return True, 7
        if "anzian" in text or "vecchio" in text: return True, 80
        if "neonato" in text: return True, 0
        
        return False, None

    @staticmethod
    def validate_pain_scale(user_input: str) -> Tuple[bool, Optional[int]]:
        """Converte descrittori di dolore o numeri in scala 1-10."""
        if not user_input: return False, None
        text = user_input.lower()
        
        # Numeri diretti
        nums = re.findall(r'\b(\d{1,2})\b', text)
        if nums and 1 <= int(nums[0]) <= 10:
            return True, int(nums[0])
            
        # Mapping qualitativo essenziale
        pain_map = {
            "lieve": 2, "poco": 2, "moderato": 5, "medio": 5,
            "forte": 8, "molto": 8, "intenso": 8, "acuto": 8,
            "insopportabile": 10, "atroce": 10, "estremo": 10
        }
        for kw, val in pain_map.items():
            if kw in text: return True, val
            
        return False, None

    @staticmethod
    def validate_red_flags(user_input: str) -> Tuple[bool, List[str]]:
        """Rileva segnali di allarme clinico critici per attivazione Fast-Triage."""
        if not user_input: return True, []
        text = user_input.lower()
        
        flags_detected = []
        patterns = {
            "dolore_toracico": r"dolore.*petto|oppressione.*torace|infarto",
            "dispnea": r"non.*respir|affanno|soffoc|fame.*aria",
            "coscienza": r"svenut|perso.*sensi|confus|stordit",
            "emorragia": r"sangue.*molto|emorragia|sanguinamento.*forte"
        }
        
        for name, pat in patterns.items():
            if re.search(pat, text):
                flags_detected.append(name)
        
        return True, flags_detected

# =============================================================
# CARICAMENTO KNOWLEDGE BASE (Eseguito solo all'avvio)
# =============================================================

def load_master_kb(filepath="master_kb.json") -> Dict:
    """
    Carica la Knowledge Base delle strutture sanitarie in memoria.
    Questo evita di riaprire il file a ogni ricerca dell'utente.
    """
    try:
        if not os.path.exists(filepath):
            logger.error(f"File {filepath} non trovato. La ricerca strutture non funzionerà.")
            return {}
            
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Logghiamo il numero di strutture caricate per tipo
            stats = {k: len(v) for k, v in data.items() if isinstance(v, list)}
            logger.info(f"Knowledge Base caricata con successo: {stats}")
            return data
            
    except json.JSONDecodeError as e:
        logger.error(f"Errore nel formato JSON di {filepath}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Errore imprevisto nel caricamento KB: {e}")
        return {}

# Costante globale che funge da database in memoria (O(1) access)
FACILITIES_KB = load_master_kb()

# =============================================================
# LOGICA DI CALCOLO E RICERCA
# =============================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcola la distanza in km tra due coordinate geografiche."""
    # Validazione range
    if not (-90 <= lat1 <= 90) or not (-90 <= lat2 <= 90) or \
       not (-180 <= lon1 <= 180) or not (-180 <= lon2 <= 180):
        return 9999.0 # Valore di errore per distanze out of range

    R = 6371.0  # Raggio Terra (km)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    
    a = (math.sin(d_phi / 2)**2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# =============================================================
# CARICAMENTO DATASET (Eseguito una sola volta all'avvio)
# =============================================================

def load_geodata_er(filepath="mappa_er.json") -> Dict[str, Dict[str, Any]]:
    """
    Carica TUTTI i comuni e le loro proprietà dal Canvas mappa_er.json.
    Restituisce un dizionario ottimizzato per lookup rapidi.
    """
    try:
        if not os.path.exists(filepath):
            logger.error(f"File {filepath} non trovato.")
            return {}

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            geoms = data.get("objects", {}).get("comuni", {}).get("geometries", [])
            
            # Creiamo una mappa: "nome_comune" -> {lat, lon, prov_acr}
            # Questo sostituisce i vecchi dizionari manuali
            return {
                g["properties"]["name"].lower().strip(): {
                    "lat": float(g["properties"]["lat"]),
                    "lon": float(g["properties"]["lon"]),
                    "prov": g["properties"].get("prov_acr", "ER")
                }
                for g in geoms if "name" in g["properties"]
            }
    except Exception as e:
        logger.error(f"Errore caricamento geodata: {e}")
        return {}

# Inizializzazione dati globali
ALL_COMUNI = load_geodata_er()
# Supponiamo che FACILITIES_KB sia caricato altrove come visto in precedenza
# FACILITIES_KB = load_master_kb() 

# =============================================================
# LOGICA DI CALCOLO E RICERCA
# =============================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Formula di Haversine compatta per distanza in km."""
    R = 6371.0
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_nearest_facilities(user_lat: float, user_lon: float, facility_type: str = "pronto_soccorso", 
                             max_results: int = 3, max_distance_km: float = 50.0) -> List[Dict]:
    """Trova strutture vicine filtrando e ordinando in memoria."""
    # Nota: FACILITIES_KB deve essere accessibile globalmente
    facilities = globals().get('FACILITIES_KB', {}).get(facility_type, [])
    enriched = []

    for f in facilities:
        f_lat = float(f.get('latitudine') or f.get('lat', 0))
        f_lon = float(f.get('longitudine') or f.get('lon', 0))
        if f_lat == 0: continue
        
        dist = haversine_distance(user_lat, user_lon, f_lat, f_lon)
        if dist <= max_distance_km:
            enriched.append({**f, 'distance_km': round(dist, 2)})

    return sorted(enriched, key=lambda x: x['distance_km'])[:max_results]

# =============================================================
# FUNZIONI DI INTERFACCIA (Rifattorizzate e Dinamiche)
# =============================================================

def get_comune_coordinates(comune: str) -> Optional[Dict[str, float]]:
    """
    Ottiene coordinate di QUALSIASI comune caricato dal Canvas.
    Utilizza fuzzy matching per correggere refusi.
    """
    name = comune.lower().strip()
    # Match esatto
    if name in ALL_COMUNI:
        return {"lat": ALL_COMUNI[name]["lat"], "lon": ALL_COMUNI[name]["lon"]}
    
    # Fuzzy match su tutti i comuni della regione
    matches = difflib.get_close_matches(name, list(ALL_COMUNI.keys()), n=1, cutoff=0.8)
    if matches:
        match_name = matches[0]
        return {"lat": ALL_COMUNI[match_name]["lat"], "lon": ALL_COMUNI[match_name]["lon"]}
    
    return None

def get_area_type_from_comune(comune: str) -> str:
    """Determina il tipo di area basato sulla centralità urbana."""
    urban_hubs = {"bologna", "modena", "parma", "reggio emilia", "ferrara", "ravenna", "rimini", "forlì", "cesena", "piacenza"}
    suburban_hubs = {"imola", "carpi", "sassuolo", "faenza", "lugo", "cervia", "riccione", "cattolica", "fidenza"}
    
    name = comune.lower().strip()
    if name in urban_hubs: return "urban"
    if name in suburban_hubs: return "suburban"
    return "rural"

def estimate_eta(distance_km: float, area_type: str = "urban") -> Dict[str, float]:
    """Stima ETA considerando traffico e tortuosità stradale."""
    speeds = {"urban": 30.0, "suburban": 50.0, "rural": 70.0}
    real_dist = distance_km * 1.3 # Fattore di tortuosità medio
    duration = (real_dist / speeds.get(area_type, 50.0)) * 60
    return {"duration_minutes": round(duration, 1), "real_distance_km": round(real_dist, 2)}

class BackendClient:
    def __init__(self):
        """
        Inizializza il client per la sincronizzazione dati.
        Mantiene la sicurezza delle credenziali tramite st.secrets.
        """
        # Puntiamo al server locale (localhost) per il test con il file .bat
        # Se non presente nei secrets, usa il fallback localhost per lo sviluppo
        self.url = st.secrets.get("BACKEND_URL", "http://127.0.0.1:5000/triage")
        self.api_key = st.secrets.get("BACKEND_API_KEY", "test-key-locale")
        self.session = requests.Session()
        
        # 1. GESTIONE DELLA RESILIENZA (Retry Logic)
        # Configurato per 5 tentativi con backoff progressivo per gestire sovraccarichi
        retries = Retry(
            total=5, 
            backoff_factor=1, 
            status_forcelist=[500, 502, 503, 504]
        )
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def sync(self, data: Dict):
        """
        Invia dati strutturati al backend rispettando il GDPR e arricchendo il contesto.
        """
        # 2. PROTEZIONE DELLA PRIVACY (GDPR Compliance)
        if not st.session_state.get("gdpr_consent", False):
            logger.warning("BACKEND_SYNC | Invio negato: Consenso GDPR mancante.")
            return 
            
        try:
            # 3. ARRICCHIMENTO DEI DATI (Contextual Data)
            # Aggiungiamo metadati vitali per l'analisi clinica e cronologica
            enriched_data = {
                "session_id": st.session_state.get("session_id", "anon_session"),
                "phase": st.session_state.get("step", "unknown_phase"),
                "triage_data": data,
                "current_specialization": st.session_state.get("specialization", "Generale"),
                "timestamp": datetime.now().isoformat()
            }
            
            # 4. SICUREZZA DELLE CREDENZIALI
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # INVIO REALE (Attivo per il test con il file .bat)
            response = self.session.post(
                self.url, 
                json=enriched_data, 
                headers=headers, 
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"✅ BACKEND_SYNC | Dati sincronizzati con successo per sessione: {enriched_data['session_id']}")
            else:
                logger.error(f"❌ BACKEND_SYNC | Errore server ({response.status_code}): {response.text}")

        except Exception as e:
            logger.error(f"❌ BACKEND_SYNC | Connessione fallita: {e}")

class PharmacyService:
    """
    Servizio logistico avanzato per la ricerca di farmacie in Emilia-Romagna.
    Integrazione intelligente con il database geografico regionale per ricerche di prossimità.
    """
    def __init__(self, emilia_path: str = "FARMACIE_EMILIA.json", romagna_path: str = "FARMACIE_ROMAGNA.json"):
        self.data = self._load_all_data(emilia_path, romagna_path)
        # Lista di tutti i comuni presenti nel database farmacie
        self.cities_in_db = sorted(list(set(f['comune'].lower() for f in self.data)))

    def _load_all_data(self, p1: str, p2: str) -> List[Dict]:
        """Carica e unisce i database regionali."""
        combined = []
        for path in [p1, p2]:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        combined.extend(json.load(f))
                except Exception:
                    continue
        return combined

    def _is_pharmacy_open(self, orari: Dict, dt: datetime = None) -> bool:
        """
        Verifica l'apertura in tempo reale.
        Gestisce 'H24', 'Chiuso' e formati complessi come '08:30-13:00, 15:00-19:30'.
        """
        if not dt: dt = datetime.now()
        
        days_map = {0: "lunedi", 1: "martedi", 2: "mercoledi", 3: "giovedi", 4: "venerdi", 5: "sabato", 6: "domenica"}
        today_name = days_map[dt.weekday()]
        orario_oggi = orari.get(today_name, "").upper()

        if "H24" in orario_oggi: return True
        if "CHIUSO" in orario_oggi or not orario_oggi: return False

        try:
            current_time = dt.strftime("%H:%M")
            # Pulizia per gestire note extra tra parentesi
            clean_orario = orario_oggi.split("(")[0].strip() 
            slots = clean_orario.split(",")
            for slot in slots:
                if "-" in slot:
                    start, end = slot.strip().split("-")
                    if start.strip() <= current_time <= end.strip():
                        return True
        except Exception:
            return False
        return False

    def get_pharmacies(self, comune_input: str, open_only: bool = False, 
                       user_lat: float = None, user_lon: float = None, 
                       radius_km: float = 15.0) -> List[Dict]:
        """
        Ricerca farmacie con fallback geografico automatico.
        """
        target_city = comune_input.lower().strip()
        
        # 1. Fuzzy matching per normalizzare il comune inserito
        matches = difflib.get_close_matches(target_city, self.cities_in_db, n=1, cutoff=0.8)
        if matches: target_city = matches[0]

        results = []
        
        # Importiamo le funzioni dal modulo geolocalizzazione aggiornato
        from geolocalizzazione_er import haversine_distance, get_comune_coordinates

        for f in self.data:
            dist = None
            # Recupero coordinate farmacia (se presenti) o del suo comune (fallback)
            f_lat = f.get('lat') or f.get('latitudine')
            f_lon = f.get('lon') or f.get('longitudine')
            
            if not f_lat or not f_lon:
                # Fallback: usiamo il centroide del comune della farmacia da mappa_er.json
                city_coords = get_comune_coordinates(f['comune'])
                if city_coords:
                    f_lat, f_lon = city_coords['lat'], city_coords['lon']

            # Calcolo distanza rispetto all'utente
            if user_lat and user_lon and f_lat and f_lon:
                dist = haversine_distance(user_lat, user_lon, float(f_lat), float(f_lon))

            # Filtro: Stesso comune OPPURE entro raggio km (demo comuni vicini)
            is_in_city = f['comune'].lower() == target_city
            is_nearby = dist is not None and dist <= radius_km
            
            if is_in_city or is_nearby:
                f_copy = f.copy()
                f_copy['is_open'] = self._is_pharmacy_open(f['orari'])
                f_copy['distance_km'] = round(dist, 2) if dist is not None else None
                
                if open_only and not f_copy['is_open']:
                    continue
                    
                results.append(f_copy)

        # Ordinamento strategico: 1. Aperte, 2. Più vicine
        results.sort(key=lambda x: (not x['is_open'], x.get('distance_km', 999)))
        
        return results

# --- ESEMPIO DI RENDERING PER CHATBOT ---
def format_pharmacy_results(pharmacies: List[Dict]):
    if not pharmacies: return "Nessuna farmacia trovata con i criteri selezionati."
    
    output = "Ecco le farmacie disponibili:\n"
    for p in pharmacies[:5]: # Mostriamo le prime 5
        status = "🟢 APERTA" if p['is_open'] else "🔴 CHIUSA"
        dist_info = f" a {p['distance_km']} km" if p['distance_km'] else ""
        output += f"- **{p['nome']}** ({status}{dist_info})\n"
        output += f"  📍 {p['indirizzo']} | 📞 {p['contatti'].get('telefono', 'N.D.')}\n"
    return output

# Import nuovo orchestratore
from model_orchestrator_v2 import ModelOrchestrator
from models import TriageResponse
from bridge import stream_ai_response


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
def get_fallback_options(step: TriageStep) -> List[str]:
    """
    Restituisce opzioni predefinite per lo step corrente se l'AI fallisce.
    Utilizza la costante globale TRIAGE_FALLBACK_OPTIONS.
    """
    # Recuperiamo le opzioni usando il nome della chiave nell'enum
    options = TRIAGE_FALLBACK_OPTIONS.get(step.name, ["Continua", "Annulla"])
    
    logger.info(f"Fallback attivato per lo step {step.name}: generate {len(options)} opzioni.")
    return options

def render_header(current_phase=None):
    """
    Renderizza l'header dell'applicazione in modalità 'Silent Triage'.
    Versione Ottimizzata:
    - Rimosso ogni banner di allerta (anche per codici rossi) per velocità.
    - Focus su navigazione e consapevolezza del progresso.
    - Efficienza: Utilizza stili inline per evitare dipendenze CSS esterne pesanti.
    """
    # 1. Feedback Visivo (Progress Bar)
    # Assicurati che render_progress_bar() sia definita nel tuo frontend.py
    try:
        render_progress_bar()
    except Exception as e:
        logger.warning(f"Impossibile renderizzare progress bar: {e}")
    
    # 2. Badge Urgenza Discreto
    # Mostra il colore dell'urgenza rilevata dai metadati senza messaggi bloccanti
    if st.session_state.get('metadata_history'):
        try:
            render_urgency_badge()
        except Exception as e:
            logger.debug(f"Badge urgenza non disponibile: {e}")
    
    # 3. Struttura Titolo e Contatore Step
    current_step = st.session_state.current_step
    
    # Helper per il nome visualizzato (se non esiste la funzione, usa il nome dell'Enum)
    if 'get_step_display_name' in globals():
        step_display_name = get_step_display_name(current_step)
    else:
        step_display_name = current_step.name.replace("_", " ").title()
    
    # Calcolo lunghezza totale
    total_steps = len(TriageStep)
    
    # Render HTML centrato e pulito
    st.markdown(f"""
    <div style='text-align: center; margin: 10px 0 25px 0; font-family: sans-serif;'>
        <h2 style='color: #1f2937; margin: 0; font-size: 1.8em;'>🩺 AI Health Navigator</h2>
        <div style='margin-top: 10px;'>
            <span style='background-color: #f3f4f6; color: #4b5563; padding: 6px 16px; 
                         border-radius: 25px; font-size: 0.95em; font-weight: 600;
                         border: 1px solid #e5e7eb;'>
                {step_display_name} <span style='color: #9ca3af; font-weight: 400; margin-left: 5px;'>|</span> 
                <span style='color: #3b82f6; margin-left: 5px;'>Passaggio {current_step.value} di {total_steps}</span>
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Logging per monitoraggio efficacia
    logger.info(f"Header renderizzato con successo per lo step {current_step.name} (Valore: {current_step.value})")

def render_sidebar(pharmacy_db):
    with st.sidebar:
        st.title("🛡️ Navigator Pro")
        
        if st.button("🔄 Nuova Sessione", use_container_width=True, key="sidebar_new_session"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
            
        if st.button("🆘 SOS - INVIA POSIZIONE", type="primary", use_container_width=True, key="sidebar_sos_gps"):
            st.warning("Geolocalizzazione in corso...")
            st.session_state.backend.sync({"event": "SOS_GPS_REQUEST"})
            st.info("In caso di pericolo reale, chiama subito il 118.")
        
        st.divider()
        current_phase = PHASES[st.session_state.current_phase_idx]
        st.markdown(f"**Specializzazione Backend:** `{st.session_state.specialization}`")
        st.progress((st.session_state.current_phase_idx + 1) / len(PHASES))
        
        # PARTE 2: RICERCA SERVIZI (VERSIONE OTTIMIZZATA) ---
        with st.expander("📍 Ricerca Servizi e Strutture"):
            st.markdown("<small>Scrivi il servizio o la specialità (es. *Ginecologia* o *Visita*).</small>", unsafe_allow_html=True)
            
            # A. Input Comune (Prende il valore dal triage se l'utente lo ha già inserito)
            if not st.session_state.get('user_comune'):
                c_input = st.text_input(
                "In quale comune?", 
                key="sidebar_geo_comune", 
                value=st.session_state.get('user_comune', ''),
                placeholder="es. Cento"
            )
            
            # B. Selezione Servizio (Tendina con ricerca dinamica integrata)
            s_input = st.selectbox(
                "Di cosa hai bisogno?",
                options=st.session_state.get('service_catalog', ["Caricamento..."]),
                key="sidebar_service_select",
                index=None,
                placeholder="Cerca servizio o prestazione..."
            )
            
            # C. Pulsante di Esecuzione
            if st.button("🔍 Cerca e Invia in Chat", use_container_width=True, key="exec_search_btn"):
                if not c_input or not s_input:
                    st.warning("⚠️ Per favore, inserisci sia il comune che il servizio.")
                else:
                    with st.spinner("Consultando i database territoriali..."):
                        found = find_facilities_smart(s_input, c_input)
                    
                    if found:
                        # 1. Messaggio professionale per la chat
                        msg = f"### 📍 Risultati per: {s_input}\n"
                        msg += f"Analisi territoriale effettuata per il comune di: **{c_input}**\n\n---\n"
                        
                        for i, r in enumerate(found, 1):
                            link = make_gmaps_link(r)
                            contatti = r.get('contatti', {})
                            tel = contatti.get('telefono') or contatti.get('telephone') or "N/D"
                            
                            msg += f"**{i}. {r['nome']}**\n"
                            msg += f"🏢 *{r.get('tipologia', 'Servizio Sanitario')}*\n"
                            msg += f"📍 {r['indirizzo']} ({r['comune']})\n"
                            msg += f"📞 {tel} | [🚗 Apri Navigatore Maps]({link})\n\n"
                        
                        # 2. Aggiunta alla cronologia chat
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.success("✅ Strutture inviate nella chat!")
                        st.rerun()
                    else:
                        st.error("❌ Nessuna struttura trovata in questa zona.")

        # PARTE 3: Expander Accessibilità
        st.divider()
        
        with st.expander("♿ Impostazioni Accessibilità"):
            st.markdown("**Personalizza l'interfaccia**")
            
            high_contrast = st.checkbox(
                "Contrasto Elevato",
                value=st.session_state.get('high_contrast', False),
                key='high_contrast',
                help="Tema scuro con contrasto aumentato"
            )
            
            if high_contrast:
                st.markdown("""
                <style>
                    .stApp { background-color: #000000 !important; color: #ffffff !important; }
                    .stButton>button { background-color: #ffffff !important; color: #000000 !important; }
                </style>
                """, unsafe_allow_html=True)
                logger.info("High contrast mode activated")
            
            font_size = st.select_slider(
                "Dimensione Testo",
                options=["Piccolo", "Normale", "Grande", "Molto Grande"],
                value=st.session_state.get('font_size', "Normale"),
                key='font_size'
                        )
            
            font_size_map = {"Piccolo": "0.9em", "Normale": "1.0em", "Grande": "1.2em", "Molto Grande":  "1.5em"}
            st.markdown(f"""
            <style>
                .stMarkdown, .stText, .stChatMessage {{ font-size: {font_size_map[font_size]} !important; }}
            </style>
            """, unsafe_allow_html=True)
            
            auto_speech = st.checkbox(
                "Lettura Automatica Risposte",
                value=st.session_state.get('auto_speech', False),
                key='auto_speech',
                help="Legge automaticamente ogni risposta del bot"
            )
            
            if auto_speech:
                st.info("🔊 Lettura automatica attiva")
            
            reduce_motion = st.checkbox(
                "Riduci Animazioni",
                value=st. session_state.get('reduce_motion', False),
                key='reduce_motion'
            )
            
            if reduce_motion:
                st. markdown("""
                <style>
                    *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
                </style>
                """, unsafe_allow_html=True)
            
            if st.button("🔄 Ripristina Default", use_container_width=True, key="reset_accessibility_btn"):
                for key in ['high_contrast', 'font_size', 'auto_speech', 'reduce_motion']:
                    if key in st.session_state: 
                        del st.session_state[key]
                st. rerun()


# --- SESSION STATE, LOGICA DI AVANZAMENTO E GESTIONE DATI ---

def init_session():
    """
    Inizializza lo stato della sessione con supporto FSM opzionale.
    Integra PR #7 mantenendo retrocompatibilità.
    """
    if "session_id" not in st.session_state:
        # === 1. IDENTITÀ E TRACKING (Legacy) ===
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        
        # === 2. STATE MACHINE (Legacy + FSM) ===
        st.session_state.current_step = TriageStep.LOCATION
        st.session_state. collected_data = {}
        st. session_state.step_completed = {step:  False for step in TriageStep}
        st.session_state.current_phase_idx = 0
        
        # === 3. ANALYTICS E TEMPI ===
        st.session_state.step_timestamps = {}
        st.session_state.session_start = datetime.now()
        st.session_state[f"{TriageStep.LOCATION. name}_start_time"] = datetime.now()
        
        # === 4. SICUREZZA E CONSENSO ===
        st.session_state.privacy_accepted = False
        st.session_state.critical_alert = False
        st.session_state.pending_survey = None
        
        # === 5. ROUTING CLINICO (Legacy) ===
        st.session_state.specialization = "Generale"
        st.session_state.triage_path = "C"
        st.session_state.kb_reference = None
        st.session_state.metadata_history = []
        st.session_state.emergency_level = None
        
        # === 6. LOGISTICA TERRITORIALE ===
        st.session_state.user_comune = None
        st.session_state.backend = BackendClient()
        
        # === 7. QUALITÀ AI ===
        st.session_state.ai_retry_count = {}
        
        # ============================================
        # 🆕 INTEGRAZIONE FSM (PR #7)
        # ============================================
        if FSM_ENABLED: 
            try:
                # A. ID Manager per sessioni atomiche
                id_manager = IDManager()
                fsm_session_id = id_manager.generate_new_id()
                
                # B. Inizializza TriageState con Path di default
                st.session_state.triage_state = TriageState(
                    session_id=fsm_session_id,
                    assigned_path=TriagePath.C,  # Default: Standard
                    assigned_branch=TriageBranch. TRIAGE,
                    current_phase=TriagePhase. INTENT_DETECTION
                )
                
                # C. Bridge per sincronizzazione dati
                st.session_state.fsm_bridge = TriageSessionBridge()
                
                # D. Router per classificazione urgenza
                st.session_state.router = SmartRouter()
                
                # E. Normalizzatore sintomi
                st. session_state.symptom_normalizer = SymptomNormalizer()
                
                logger.info(f"✅ FSM inizializzato | Session:  {fsm_session_id} | Path: {TriagePath.C. name}")
                
            except Exception as e: 
                logger.error(f"❌ Errore inizializzazione FSM: {e}", exc_info=True)
                FSM_ENABLED = False
        
        logger.info(f"Sessione inizializzata:  {st.session_state.session_id} | FSM: {FSM_ENABLED}")

# ============================================
# FSM:  CLASSIFICAZIONE INIZIALE URGENZA
# ============================================
def classify_initial_urgency_fsm(user_input:  str) -> Optional[UrgencyScore]:
    """
    Usa SmartRouter per classificare l'urgenza del primo messaggio.
    Ritorna UrgencyScore con path assegnato (A/B/C).
    """
    if not FSM_ENABLED or not st.session_state.get('router'):
        return None
    
    try:
        router = st.session_state.router
        urgency_score = router.classify_initial_urgency(user_input)
        
        # Aggiorna triage_state con il path assegnato
        if hasattr(st.session_state, 'triage_state'):
            st.session_state. triage_state.assigned_path = urgency_score.assigned_path
            st.session_state.triage_state.assigned_branch = urgency_score.assigned_branch
            
            logger.info(f"🎯 Classificazione FSM | Path: {urgency_score.assigned_path.name} | "
                       f"Score: {urgency_score.score}/5 | Branch: {urgency_score.assigned_branch.name}")
        
        return urgency_score
        
    except Exception as e: 
        logger.error(f"❌ Errore classificazione FSM: {e}", exc_info=True)
        return None

def advance_step() -> bool:
    """Avanza allo step successivo del triage utilizzando i valori dell'Enum."""
    current = st.session_state.current_step
    current_value = current.value
    max_value = max(step.value for step in TriageStep)
    
    if current_value < max_value:
        next_step = TriageStep(current_value + 1)
        st.session_state.current_step = next_step
        logger.info(f"Avanzamento: {current.name} -> {next_step.name}")
        return True
    
    return False


def can_proceed_to_next_step() -> bool:
    """Verifica se i dati necessari per lo step corrente sono stati raccolti."""
    current_step = st.session_state.current_step
    has_data = current_step.name in st.session_state.collected_data
    
    if current_step == TriageStep.DISPOSITION: 
        return True
    
    return has_data


def update_backend_metadata(metadata):
    """
    Aggiorna lo stato della specializzazione e monitora l'urgenza critica.
    Viene chiamata ad ogni risposta dell'AI per affinare il percorso.
    """
    st.session_state.metadata_history.append(metadata)
    
    # Check automatico urgenza alta (Codice Giallo/Rosso)
    urgenza = metadata.get("urgenza", 0)
    if urgenza >= 4 and not st.session_state.get("emergency_level"):
        # assess_emergency_level deve essere definita globalmente o importata
        emergency_level = assess_emergency_level("", metadata)
        if emergency_level:
            st.session_state.emergency_level = emergency_level
    
    # Logica di specializzazione basata sulla frequenza delle aree rilevate
    areas = [m.get("area") for m in st.session_state.metadata_history if m.get("area")]
    if areas.count("Trauma") >= 2:
        st.session_state.specialization = "Ortopedia"
    elif areas.count("Psichiatria") >= 2:
        st.session_state.specialization = "Psichiatria"
    elif areas.count("Cardiologia") >= 1 and urgenza >= 4:
        st.session_state.specialization = "Cardiologia"


def save_structured_log():
    """Salva il log strutturato della sessione su file JSONL per il backend."""
    try:
        log_entry = {
            "session_id": st.session_state.session_id,
            "timestamp": datetime.now().isoformat(),
            "collected_data": st.session_state.collected_data,
            "metadata_history": st.session_state.metadata_history,
            "emergency_level": st.session_state.get("emergency_level"),
            "specialization": st.session_state.specialization
        }
        
        # LOG_FILE deve essere definita in alto (es. "triage_logs.jsonl")
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + "\n")
        
        logger.info(f"Structured log saved: session_id={st.session_state.session_id}")
    except Exception as e:
        logger.error(f"Failed to save structured log: {e}")


def text_to_speech_button(text: str, key: str, auto_play: bool = False):
    """Placeholder per funzionalità TTS (Text-to-Speech) con Web Speech API."""
    # Implementazione futura con componenti custom o st.audio
    pass


def render_disclaimer():
    """
    Renderizza il consenso informato completo con blocco di sicurezza. 
    Copre le finalità del backend e la sicurezza clinica.
    """
    st.markdown("""
        <div style='background-color: #fff3cd; padding: 20px; border-radius: 10px; border-left: 5px solid #ffc107; margin-bottom: 20px;'>
            <h4 style='margin-top:0; color: #856404;'>📄 CONSENSO INFORMATO E PRIVACY</h4>
            <p style='font-size: 0.9em; color: #856404;'>
                Benvenuto in <b>AI Health Navigator</b>. Per procedere, è necessario accettare i seguenti termini:
            </p>
            <ul style='font-size: 0.85em; color: #856404;'>
                <li><b>Finalità:</b> Il sistema effettua un <b>Triage digitale</b> per orientarti verso la struttura corretta. <b>Non fornisce diagnosi né terapie.</b></li>
                <li><b>Trattamento Dati:</b> Le tue risposte (sintomi, comune, età) sono trasmesse in modo sicuro al <b>Backend di Analytics</b> per generare il report SBAR e ottimizzare i flussi sanitari territoriali*.</li>
                <li><b>Emergenze:</b> In caso di pericolo immediato, interrompi il triage e chiama subito il <b>118</b>.</li>
                <li><b>Responsabilità:</b> L'AI è un supporto decisionale; la responsabilità finale della consultazione medica resta in capo all'utente.</li>
            </ul>
            <p style='font-size: 0.75em; color: #856404; font-style: italic; border-top: 1px solid #ffeeba; padding-top: 10px;'>
                * I dati saranno utilizzati ai sensi del Regolamento UE 2016/679 (GDPR), Art. 89, per finalità di ricerca e statistica. Previa anonimizzazione irreversibile (Recital 26 GDPR), tali dati potranno essere condivisi con partner terzi per finalità di analisi e sviluppo commerciale.
            </p>
        </div>
    """, unsafe_allow_html=True)
    
    if not st.session_state.get('privacy_accepted', False):
        if st.checkbox("Ho letto e accetto i termini del servizio e il trattamento dei dati per fini di triage.", key="privacy_check"):
            st.session_state.privacy_accepted = True
            st.success("Consenso registrato. Avvio sistema...")
            time.sleep(1)
            st.rerun()
        else:
            st.info("⚠️ È necessario accettare il consenso per utilizzare l'assistente.")
            st.stop()


def render_disposition_summary():
    """Mostra il verdetto finale e resetta la sessione se richiesto."""
    st.success("### ✅ Triage Completato")
    
    if st.session_state.collected_data:
        st.json(st.session_state.collected_data)
        # Salvataggio log automatico a fine triage
        save_structured_log()
    
    comune = st.session_state.get("user_comune")
    if comune and 'should_show_ps_wait_times' in globals():
        last_urgency = st.session_state.metadata_history[-1].get("urgenza", 3) if st.session_state.metadata_history else 3
        if should_show_ps_wait_times(comune, last_urgency):
            render_ps_wait_times_alert(comune, last_urgency)
    
    if st.button("🔄 Inizia Nuova Sessione", type="primary", key="main_reset_btn"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- STATO SESSIONE ---
# PARTE 1: Session State con State Machine
def init_session():
    """
    Inizializza lo stato della sessione.
    Sostituisce la vecchia init_session.
    """
    if "session_id" not in st.session_state:
        # 1. Identità e Cronologia
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        
        # 2. State Machine (Navigazione)
        st.session_state.current_step = TriageStep.LOCATION
        st.session_state.collected_data = {}
        st.session_state.step_completed = {step: False for step in TriageStep}
        
        # 3. Tracking Temporale (Analytics)
        st.session_state.step_timestamps = {}
        st.session_state.session_start = datetime.now()
        # FIX: Inizializzazione timer per lo step LOCATION
        st.session_state[f"{TriageStep.LOCATION.name}_start_time"] = datetime.now()
        
        # 4. Stato UI e Privacy
        st.session_state.current_phase_idx = 0
        st.session_state.pending_survey = None
        st.session_state.critical_alert = False
        # FIX: Allineamento nome variabile privacy
        st.session_state.privacy_accepted = False 
        
        # 5. Parametri Clinici e Backend
        st.session_state.specialization = "Generale"
        st.session_state.metadata_history = []
        st.session_state.backend = BackendClient()
        st.session_state.ai_retry_count = {}
        st.session_state.emergency_level = None
        
        logger.info(f"Sessione {st.session_state.session_id} inizializzata con successo.")

def can_proceed_to_next_step() -> bool:
    """
    Verifica se lo step corrente ha dati validati.
    Riferimento: Completa e approvata.
    """
    current_step = st.session_state.current_step
    step_name = current_step.name
    
    # Check dati validati
    has_data = step_name in st.session_state.collected_data
    
    # Lo step finale procede sempre
    if current_step == TriageStep.DISPOSITION:
        return True
    
    return has_data

def advance_step() -> bool:
    """
    Gestisce l'avanzamento logico e visivo.
    Sostituisce la vecchia advance_step.
    """
    if not can_proceed_to_next_step():
        st.warning("⚠️ Completa le informazioni richieste prima di procedere")
        return False
    
    current_step = st.session_state.current_step
    current_value = current_step.value
    
    # A. Registrazione Tempi Analytics
    start_time = st.session_state.get(f"{current_step.name}_start_time", datetime.now())
    st.session_state.step_timestamps[current_step.name] = {
        'start': start_time,
        'end': datetime.now()
    }
    
    st.session_state.step_completed[current_step] = True
    max_value = max(step.value for step in TriageStep)
    
    if current_value < max_value:
        # B. Avanzamento logico
        next_step = TriageStep(current_value + 1)
        st.session_state.current_step = next_step
        
        # C. Sincronizzazione Progress Bar (UI)
        if st.session_state.current_phase_idx < len(PHASES) - 1:
            st.session_state.current_phase_idx += 1
        
        # D. Start timer nuovo step
        st.session_state[f"{next_step.name}_start_time"] = datetime.now()
        
        st.toast(f"✅ Completato: {current_step.name.replace('_', ' ')}")
        return True
    
    return True


def auto_advance_if_ready() -> bool:
    """
    Avanza automaticamente quando tutti i dati dello step sono raccolti.
    ✅ FIX BUG #2: Logica speciale per RED_FLAGS
    """
    current_step = st.session_state.current_step
    collected = st.session_state.collected_data
    
    # Mappa:  Step → Campi richiesti
    requirements = {
        TriageStep.LOCATION: ['LOCATION'],
        TriageStep. CHIEF_COMPLAINT: ['CHIEF_COMPLAINT'],
        TriageStep.PAIN_SCALE: ['PAIN_SCALE'],
        TriageStep. RED_FLAGS: ['RED_FLAGS'],  # Gestito sotto
        TriageStep. ANAMNESIS: ['age']
    }
    
    # ✅ CASO SPECIALE: RED_FLAGS
    if current_step == TriageStep.RED_FLAGS: 
        red_flags_data = collected.get('RED_FLAGS')
        
        # Considera RED_FLAGS completato se:
        # 1. Qualsiasi risposta testuale è stata data (anche "no" o "nessuno")
        # 2. Una lista vuota esplicita è stata salvata (significa "nessun flag")
        if red_flags_data is not None: 
            # Se è una stringa con contenuto
            if isinstance(red_flags_data, str) and len(red_flags_data. strip()) > 0:
                logger.info(f"✅ Auto-advance: RED_FLAGS completato con risposta '{red_flags_data}'")
                return advance_step()
            # Se è una lista (anche vuota)
            elif isinstance(red_flags_data, list):
                logger.info(f"✅ Auto-advance: RED_FLAGS completato con lista {red_flags_data}")
                return advance_step()
        
        # Non avanzare se RED_FLAGS è ancora None
        return False
    
    # LOGICA STANDARD per altri step
    required_fields = requirements. get(current_step, [])
    
    if all(field in collected and collected. get(field) for field in required_fields):
        logger.info(f"✅ Auto-advance: {current_step.name} → completato, avanzamento automatico")
        return advance_step()
    
    return False


# PARTE 2: Logging Strutturato per Backend Analytics
def save_structured_log():
    """
    Salva log sessione in formato strutturato JSON per analytics.
    Schema version "2.0" ottimizzato per l'analisi clinica.
    """
    # Verifica consenso (allineato con privacy_accepted dello session_state)
    if not st.session_state.get("privacy_accepted", False):
        logger.info("Skipping log save: Privacy consent not given")
        return
    
    try:
        session_end = datetime.now()
        session_start = st.session_state.session_start
        total_duration = (session_end - session_start).total_seconds()
        
        # 1. Ricostruzione cronologia degli step con durate
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
        
        # 2. Riassunto Clinico estratto
        clinical_summary = {
            "chief_complaint": st.session_state.collected_data.get('CHIEF_COMPLAINT'),
            "pain_severity": st.session_state.collected_data.get('PAIN_SCALE'),
            "red_flags": st.session_state.collected_data.get('RED_FLAGS', []),
            "age": st.session_state.collected_data.get('age'),
            "location": st.session_state.collected_data.get('LOCATION')
        }
        
        # 3. Esito (Disposition)
        disposition_data = st.session_state.collected_data.get('DISPOSITION', {})
        outcome = {
            "disposition": disposition_data.get('type', 'Non Completato'),
            "urgency_level": disposition_data.get('urgency', 0),
            "facility_recommended": disposition_data.get('facility_name'),
            "distance_km": disposition_data.get('distance'),
            "eta_minutes": disposition_data.get('eta')
        }
        
        # 4. Metadati tecnici
        metadata = {
            "specialization": st.session_state.specialization,
            "emergency_triggered": st.session_state.emergency_level is not None,
            "emergency_level": st.session_state.emergency_level.name if st.session_state.emergency_level else None,
            "ai_fallback_used": any("fallback" in str(m) for m in st.session_state.metadata_history),
            "total_messages": len(st.session_state.messages)
        }
        
        # 5. Assemblaggio Log Entry finale
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
        
        # Scrittura su file JSONL
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        logger.info(f"Structured log 2.0 salvato: session={st.session_state.session_id}")
        
        # 🆕 SYNC TO SESSION STORAGE
        if SESSION_STORAGE_ENABLED:
            try:
                sync_session_to_storage(st.session_state.session_id, st.session_state)
                logger.info(f"✅ Session synced to storage: {st.session_state.session_id}")
            except Exception as sync_error:
                logger.error(f"❌ Failed to sync to storage: {sync_error}")
    
    except Exception as e:
        logger.error(f"Failed to save structured log: {e}", exc_info=True)


def auto_sync_session_storage():
    """
    Sincronizza automaticamente lo stato della sessione nello storage.
    Chiamata periodicamente durante la conversazione per garantire persistenza.
    
    NUOVO (2026): Supporto per sincronizzazione cross-istanza.
    """
    if not SESSION_STORAGE_ENABLED:
        return
    
    # Throttle: sync max ogni 10 secondi
    last_sync = st.session_state.get('_last_storage_sync', 0)
    current_time = time.time()
    
    if current_time - last_sync < 10:
        logger.debug(f"Throttling storage sync (last: {current_time - last_sync:.1f}s ago)")
        return
    
    try:
        success = sync_session_to_storage(st.session_state.session_id, st.session_state)
        if success:
            st.session_state._last_storage_sync = current_time
            logger.debug(f"✅ Auto-sync session storage: {st.session_state.session_id}")
        else:
            logger.warning(f"⚠️ Auto-sync failed for session: {st.session_state.session_id}")
    except Exception as e:
        logger.error(f"❌ Auto-sync error: {e}")

def get_step_display_name(step) -> str:
    """
    Ottiene nome human-readable per lo step corrente.
    Utilizzato per l'interfaccia utente (Header/Progress).
    """
    names = {
        TriageStep.LOCATION: "Localizzazione Geografica",
        TriageStep.CHIEF_COMPLAINT: "Sintomo Principale",
        TriageStep.PAIN_SCALE: "Valutazione Intensità",
        TriageStep.RED_FLAGS: "Screening Emergenze",
        TriageStep.ANAMNESIS: "Anamnesi Clinica",
        TriageStep.DISPOSITION: "Verdetto e Raccomandazioni"
    }
    return names.get(step, step.name if hasattr(step, 'name') else str(step))
# PARTE 3: Componenti UI - Progress Bar
def render_progress_bar():
    """
    Renderizza una barra di progresso focalizzata sullo step attuale.
    Ottimizzata per mobile: mostra una card singola invece di colonne multiple.
    """
    if "current_step" not in st.session_state:
        return

    current_step = st.session_state.current_step
    
    # Mapping dati UI
    step_ui_data = {
        TriageStep.LOCATION: {"emoji": "📍", "label": "Posizione", "description": "Comune di riferimento"},
        TriageStep.CHIEF_COMPLAINT: {"emoji": "🩺", "label": "Sintomi", "description": "Descrizione del disturbo"},
        TriageStep.PAIN_SCALE: {"emoji": "📊", "label": "Intensità", "description": "Valutazione del dolore"},
        TriageStep.RED_FLAGS: {"emoji": "🚨", "label": "Urgenza", "description": "Verifica segnali d'allarme"},
        TriageStep.ANAMNESIS: {"emoji": "📋", "label": "Anamnesi", "description": "Storia clinica e dati"},
        TriageStep.DISPOSITION: {"emoji": "🏥", "label": "Verdetto", "description": "Raccomandazione finale"}
    }
    
    # Calcolo progresso
    total_steps = len(TriageStep)
    # Troviamo l'indice numerico dello step attuale (basato sull'ordine dell'Enum)
    current_index = list(TriageStep).index(current_step) + 1
    progress_percentage = current_index / total_steps
    
    # 1. Barra di progresso standard (Top)
    st.progress(progress_percentage, text=f"Fase {current_index} di {total_steps}")
    
    # 2. Card Singola Focus (Mobile-First)
    ui = step_ui_data[current_step]
    
    st.markdown(f"""
    <div style='
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin-bottom: 20px;
    '>
        <div style='font-size: 2.5em; margin-bottom: 10px;'>{ui['emoji']}</div>
        <div style='font-size: 1.1em; font-weight: 700; color: #1e293b; text-transform: uppercase; letter-spacing: 0.5px;'>
            {ui['label']}
        </div>
        <div style='font-size: 0.9em; color: #64748b; margin-top: 5px;'>
            {ui['description']}
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_dynamic_step_tracker():
    """
    ✅ NUOVO: Stepper a tendine che mostra dati raccolti
    Sostituisce il box singolo con una riga di step interattivi
    """
    st.markdown("---")
    st.markdown("### 📋 Avanzamento Triage")
    
    # Definizione step e mapping dati
    steps_config = [
        {
            "id": "LOCATION",
            "emoji": "📍",
            "label": "Localizzazione",
            "key_data": "LOCATION",
            "format_fn": lambda x: f"Comune: **{x}**"
        },
        {
            "id": "CHIEF_COMPLAINT",
            "emoji": "🩺",
            "label": "Sintomi",
            "key_data":  "CHIEF_COMPLAINT",
            "format_fn": lambda x: f"Disturbo: **{x}**"
        },
        {
            "id": "PAIN_SCALE",
            "emoji": "📊",
            "label":  "Dolore",
            "key_data": "PAIN_SCALE",
            "format_fn": lambda x: f"Intensità: **{x}/10**"
        },
        {
            "id": "RED_FLAGS",
            "emoji":  "🚨",
            "label": "Urgenza",
            "key_data": "RED_FLAGS",
            "format_fn": lambda x:  f"Segnali: **{', '.join(x) if isinstance(x, list) else x}**" if x else "Nessuno"
        },
        {
            "id": "ANAMNESIS",
            "emoji":  "📋",
            "label": "Anamnesi",
            "key_data": "age",
            "format_fn":  lambda x: f"Età:  **{x} anni**"
        },
        {
            "id":  "DISPOSITION",
            "emoji": "🏥",
            "label": "Esito",
            "key_data": "DISPOSITION",
            "format_fn": lambda x: f"Raccomandazione: **{x. get('type', 'In corso.. .')}**" if isinstance(x, dict) else str(x)
        }
    ]
    
    collected = st.session_state.get('collected_data', {})
    current_step = st.session_state.get('current_step', TriageStep.LOCATION)
    
    # Rendering colonne dinamiche
    cols = st.columns(len(steps_config))
    
    for i, step in enumerate(steps_config):
        with cols[i]:
            data_value = collected.get(step['key_data'])
            
            # ✅ CASO 1: Dato presente → Tendina verde
            if data_value: 
                with st.expander(f"✅ {step['emoji']} {step['label']}", expanded=False):
                    st.markdown(step['format_fn'](data_value))
                    
                    # Bottone reset (solo se non siamo in DISPOSITION finale)
                    if step['id'] != 'DISPOSITION':
                        if st.button(
                            "🔄 Modifica",
                            key=f"reset_{step['id']}",
                            use_container_width=True
                        ):
                            del st.session_state. collected_data[step['key_data']]
                            st. rerun()
            
            # ✅ CASO 2: Step corrente → Box blu animato
            elif current_step. name == step['id']:
                st.markdown(f"""
                <div style='
                    background:  linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
                    color: white;
                    padding:  15px;
                    border-radius: 10px;
                    text-align: center;
                    animation: pulse 2s infinite;
                '>
                    <div style='font-size: 2em;'>{step['emoji']}</div>
                    <div style='font-weight: 600; margin-top: 5px;'>{step['label']}</div>
                    <div style='font-size: 0.8em; margin-top: 5px;'>In corso...</div>
                </div>
                <style>
                    @keyframes pulse {{
                        0%, 100% {{ box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7); }}
                        50% {{ box-shadow: 0 0 0 10px rgba(59, 130, 246, 0); }}
                    }}
                </style>
                """, unsafe_allow_html=True)
            
            # ✅ CASO 3: Step futuro → Box grigio
            else:
                st.markdown(f"""
                <div style='
                    background-color: #f3f4f6;
                    border: 1px dashed #d1d5db;
                    color: #6b7280;
                    padding: 15px;
                    border-radius: 10px;
                    text-align: center;
                '>
                    <div style='font-size: 2em; opacity: 0.5;'>{step['emoji']}</div>
                    <div style='font-weight: 500; margin-top: 5px;'>{step['label']}</div>
                    <div style='font-size: 0.75em; margin-top: 5px;'>In attesa</div>
                </div>
                """, unsafe_allow_html=True)
    
    st.markdown("---")
def render_urgency_badge():
    """
    Renderizza un badge di urgenza minimalista basato sui metadati AI.
    Nasconde il badge se non ci sono valutazioni reali.
    """
    # Recupero valori urgenza dai metadati
    urgency_values = [
        m.get('urgenza') 
        for m in st.session_state.get('metadata_history', []) 
        if isinstance(m, dict) and m.get('urgenza') is not None
    ]
    
    # LOGICA DI VISIBILITÀ: Se non ci sono dati, non renderizzare nulla
    if not urgency_values:
        return None
    
    # Calcolo media (Logica originale mantenuta)
    recent_values = urgency_values[-3:]
    avg_urgency = sum(recent_values) / len(recent_values)
    
    # Calcolo Trend
    trend_emoji = ""
    if len(urgency_values) >= 2:
        last = urgency_values[-1]
        prev = urgency_values[-2]
        if last > prev: trend_emoji = "<span style='font-size: 0.8em;'>↗️</span>"
        elif last < prev: trend_emoji = "<span style='font-size: 0.8em;'>↘️</span>"
    
    # Configurazione Colori Professionali (Sfondo leggero, bordo scuro)
    if avg_urgency <= 2.0:
        bg, border, text = "#ecfdf5", "#10b981", "#065f46" # Emerald
        label = "Bassa"
    elif avg_urgency <= 3.0:
        bg, border, text = "#fffbeb", "#f59e0b", "#92400e" # Amber
        label = "Moderata"
    elif avg_urgency <= 4.0:
        bg, border, text = "#fff7ed", "#f97316", "#9a3412" # Orange
        label = "Alta"
    else:
        bg, border, text = "#fef2f2", "#991b1b", "#7f1d1d" # Ruby
        label = "Critica"

    # Rendering Minimalista
    st.markdown(f"""
    <div style='
        background-color: {bg};
        border: 1px solid {border};
        color: {text};
        padding: 8px 16px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin: 10px 0;
    '>
        <div style='font-weight: 700; font-size: 0.85em; text-transform: uppercase;'>
            Urgenza: {label} {trend_emoji}
        </div>
        <div style='font-size: 0.85em; font-weight: 500;'>
            Livello {avg_urgency:.1f}
        </div>
    </div>
    """, unsafe_allow_html=True)

# PARTE 3: Text-to-Speech con Fallback
def text_to_speech_button(text: str, key: str, auto_play: bool = False):
    """
    Renderizza un bottone Text-to-Speech che utilizza la Web Speech API del browser.
    Consente di ascoltare il testo in italiano (it-IT).
    """
    # Pulizia testo per prevenire errori JavaScript
    clean_text = text.replace('`', '').replace("'", "\\'").replace('"', '\\"')
    
    # Limite prudenziale per evitare blocchi del browser
    if len(clean_text) > 500:
        clean_text = clean_text[:497] + "..."
        logger.warning(f"Testo TTS troncato per la chiave={key}")
    
    tts_html = f"""
    <div style='display: inline-block; margin: 5px 0;'>
        <button id='tts-btn-{key}' onclick='speakText_{key}()'
                style='background: #3b82f6; color: white; border: none; padding: 8px 16px;
                       border-radius: 8px; cursor: pointer; font-size: 0.9em; 
                       display: flex; align-items: center; gap: 8px;'
                aria-label='Leggi testo ad alta voce'>
            <span id='tts-icon-{key}'>🔊</span> <span id='tts-label-{key}'>Ascolta</span>
        </button>
        <span id='tts-status-{key}' style='font-size: 0.8em; color: #6b7280; margin-left: 8px;'></span>
    </div>
    
    <script>
        function speakText_{key}() {{
            const text = `{clean_text}`;
            const statusEl = document.getElementById('tts-status-{key}');
            const btnEl = document.getElementById('tts-btn-{key}');
            const labelEl = document.getElementById('tts-label-{key}');
            const iconEl = document.getElementById('tts-icon-{key}');
            
            if (!('speechSynthesis' in window)) {{
                statusEl.textContent = '❌ Browser non supportato';
                btnEl.disabled = true;
                return;
            }}
            
            // Se sta già parlando, ferma tutto (funge da Toggle Stop)
            if (window.speechSynthesis.speaking) {{
                window.speechSynthesis.cancel();
                return;
            }}

            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'it-IT';
            utterance.rate = 0.95; // Velocità naturale
            
            utterance.onstart = function() {{
                statusEl.textContent = 'In riproduzione...';
                labelEl.textContent = 'Stop';
                iconEl.textContent = '⏹️';
            }};
            
            utterance.onend = function() {{
                statusEl.textContent = '';
                labelEl.textContent = 'Ascolta';
                iconEl.textContent = '🔊';
            }};

            utterance.onerror = function() {{
                statusEl.textContent = '❌ Errore audio';
                labelEl.textContent = 'Ascolta';
                iconEl.textContent = '🔊';
            }};
            
            window.speechSynthesis.speak(utterance);
        }}
        
        // Gestione auto-play al caricamento del componente
        {f'setTimeout(() => speakText_{key}(), 500);' if auto_play else ''}
    </script>
    """
    st.markdown(tts_html, unsafe_allow_html=True)
    logger.debug(f"TTS caricato per key={key} (auto_play={auto_play})")

# PARTE 3: Schermata Recap e Raccomandazione Finale
def render_disposition_summary():
    """
    Renderizza schermata finale con recap dati, raccomandazione evoluta e navigatore territoriale.
    
    NOVITÀ V2:
    - Logica di raccomandazione basata su specializzazione (no limiti temporali rigidi)
    - Caching dei risultati di ricerca per performance
    - Input dinamico per cercare in comuni diversi
    - Gestione robusta di red_flags (str/list)
    - Fix privacy_accepted nel reset
    """
    st.markdown("---")
    st.markdown("## 📋 Riepilogo Triage e Raccomandazione")
    
    collected = st.session_state.collected_data
    
    # Calcolo urgenza media
    urgency_values = [m.get('urgenza', 3) for m in st.session_state.metadata_history if 'urgenza' in m]
    avg_urgency = sum(urgency_values) / len(urgency_values) if urgency_values else 3.0
    
    # === SEZIONE 1: DATI RACCOLTI ===
    st.markdown("### 📊 Dati Raccolti")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""
        **📍 Localizzazione:** {collected.get('LOCATION', 'Non specificata')}  
        **🩺 Sintomo Principale:** {collected. get('CHIEF_COMPLAINT', 'Non specificato')}  
        **📊 Intensità Dolore:** {collected. get('PAIN_SCALE', 'N/D')}/10
        """)
    
    with col2:
        # FIX: Gestione robusta di RED_FLAGS (può essere str o list)
        red_flags_raw = collected.get('RED_FLAGS', [])
        if isinstance(red_flags_raw, str):
            red_flags_display = red_flags_raw if red_flags_raw else 'Nessuno'
        elif isinstance(red_flags_raw, list):
            red_flags_display = ', '.join(red_flags_raw) if red_flags_raw else 'Nessuno'
        else:
            red_flags_display = 'Nessuno'
        
        st.markdown(f"""
        **👤 Età:** {collected.get('age', 'Non specificata')} anni  
        **🚨 Red Flags:** {red_flags_display}  
        **⚡ Livello Urgenza:** {avg_urgency:. 1f}/5.0
        """)
    
    st.divider()
    
    # === SEZIONE 2: LOGICA DI RACCOMANDAZIONE EVOLUTA ===
    st.markdown("### 🏥 Raccomandazione")
    
    specialization = st.session_state.get('specialization', 'Generale')
    
    # MAPPING SPECIALIZZAZIONI -> FACILITY TYPES
    specialty_map = {
        'Psichiatria': 'centro_salute_mentale',
        'Ginecologia': 'consultorio',
        'Ostetricia': 'consultorio',
        'Dipendenze': 'serd',
        'Ortopedia': 'cau',  # CAU per traumi non gravi
        'Cardiologia': 'pronto_soccorso',  # Sempre PS per cardio
        'Neurologia': 'pronto_soccorso'
    }
    
    # DECISIONE BASATA SU URGENZA + SPECIALIZZAZIONE
    if avg_urgency >= 4.0:
        # ALTA URGENZA:  Sempre Pronto Soccorso
        rec_type = 'Pronto Soccorso'
        rec_urgency = 'URGENTE' if avg_urgency < 4.5 else 'IMMEDIATA'
        rec_color = '#dc2626' if avg_urgency >= 4.5 else '#f97316'
        rec_msg = 'Recati **immediatamente** al Pronto Soccorso o chiama il 118.' if avg_urgency >= 4.5 else 'Si consiglia valutazione in **Pronto Soccorso**.'
        facility_type = 'pronto_soccorso'
        
    elif avg_urgency >= 2.5:
        # MEDIA URGENZA:  Usa la specializzazione
        facility_type = specialty_map.get(specialization, 'cau')
        
        if facility_type == 'centro_salute_mentale': 
            rec_type = 'Centro di Salute Mentale'
            rec_urgency = 'MODERATA'
            rec_color = '#8b5cf6'
            rec_msg = 'Contatta il **Centro di Salute Mentale** per una valutazione specialistica.'
        elif facility_type == 'consultorio':
            rec_type = 'Consultorio Familiare'
            rec_urgency = 'MODERATA'
            rec_color = '#ec4899'
            rec_msg = 'Rivolgiti al **Consultorio** per assistenza specialistica.'
        elif facility_type == 'serd': 
            rec_type = 'SerD (Dipendenze)'
            rec_urgency = 'MODERATA'
            rec_color = '#06b6d4'
            rec_msg = 'Contatta il **SerD** per supporto e consulenza.'
        elif facility_type == 'cau':
            rec_type = 'CAU (Continuità Assistenziale)'
            rec_urgency = 'MODERATA'
            rec_color = '#f59e0b'
            rec_msg = 'Valutazione presso **CAU** o Guardia Medica.'
        else:
            # Fallback generico
            rec_type = 'CAU / Medico di Base'
            rec_urgency = 'MODERATA'
            rec_color = '#f59e0b'
            rec_msg = 'Valutazione presso **CAU** o contatta il tuo Medico di Base.'
            facility_type = 'cau'
    
    else:
        # BASSA URGENZA: Medico di Base
        rec_type = 'Medico di Base'
        rec_urgency = 'BASSA'
        rec_color = '#10b981'
        rec_msg = 'Contatta il **Medico di Base** nei prossimi giorni.'
        facility_type = None  # Nessuna ricerca strutture
    
    # RENDERING CARD RACCOMANDAZIONE
    st.markdown(f"""
    <div style='background: {rec_color}; color: white; padding: 25px; border-radius: 15px;
                margin: 20px 0; text-align: center; box-shadow: 0 8px 20px rgba(0,0,0,0.15);'>
        <h3 style='margin: 10px 0;'>{rec_type}</h3>
        <p style='font-size: 1.1em;'>Urgenza: <strong>{rec_urgency}</strong></p>
        <p style='font-size: 1em;'>{rec_msg}</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Salva disposition base
    st.session_state. collected_data['DISPOSITION'] = {
        'type': rec_type,
        'urgency': avg_urgency,
        'facility_name': None,
        'distance': None,
        'eta':  None
    }
    
    # === SEZIONE 3: RICERCA STRUTTURA CON CACHING ===
    if facility_type:
        st. markdown("### 📍 Struttura Più Vicina")
        
        # INPUT DINAMICO:  Comune di ricerca
        comune_default = collected.get('LOCATION', '')
        
        col_search, col_btn = st.columns([3, 1])
        with col_search:
            comune_ricerca = st.text_input(
                "Cerca in un altro comune (se non sei a casa):",
                value=comune_default,
                key="disposition_search_comune",
                placeholder="es. Bologna"
            )
        
        with col_btn:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)  # Allineamento verticale
            force_refresh = st.button("🔄 Aggiorna", key="disposition_refresh_search")
        
        # CACHE KEY basata su comune + facility_type
        cache_key = f"{comune_ricerca}_{facility_type}"
        
        # CONTROLLO CACHE
        if 'nearest_facility_cache' not in st.session_state:
            st.session_state.nearest_facility_cache = {}
        
        # INVALIDA CACHE se utente cambia comune o clicca refresh
        if force_refresh or cache_key not in st.session_state.nearest_facility_cache:
            coords = get_comune_coordinates(comune_ricerca)
            
            if coords:
                with st.spinner("🔍 Ricerca struttura in corso..."):
                    nearest = find_nearest_facilities(
                        coords['lat'],
                        coords['lon'],
                        facility_type,
                        max_results=1
                    )
                    
                    # SALVA IN CACHE
                    st.session_state.nearest_facility_cache[cache_key] = {
                        'results': nearest,
                        'coords': coords,
                        'comune': comune_ricerca
                    }
            else:
                st.warning(f"⚠️ Comune '{comune_ricerca}' non trovato.  Verifica l'ortografia.")
                st.session_state.nearest_facility_cache[cache_key] = {
                    'results': [],
                    'coords': None,
                    'comune': comune_ricerca
                }
        
        # RECUPERA DALLA CACHE
        cached_data = st.session_state.nearest_facility_cache.get(cache_key, {})
        nearest = cached_data.get('results', [])
        coords = cached_data.get('coords')
        
        # === RENDERING RISULTATI ===
        if nearest and len(nearest) > 0:
            facility = nearest[0]
            area_type = get_area_type_from_comune(comune_ricerca)
            eta = estimate_eta(facility['distance_km'], area_type)
            
            # Aggiorna disposition con dati struttura
            st.session_state.collected_data['DISPOSITION']. update({
                'facility_name': facility.get('nome'),
                'distance': facility['distance_km'],
                'eta': eta['duration_minutes']
            })
            
            st.success(f"✅ Trovata: **{facility. get('nome')}**")
            
            # METRICHE
            c1, c2, c3 = st.columns(3)
            c1.metric("Distanza", f"{facility['distance_km']} km")
            c2.metric("Tempo Stimato", f"~{eta['duration_minutes']} min")
            c3.metric("Tipo Area", area_type.title())
            
            # DETTAGLI CONTATTO
            st.markdown(f"**📫 Indirizzo:** {facility.get('indirizzo', 'N/D')}")
            
            telefono = facility.get('telefono') or facility.get('contatti', {}).get('telefono', 'N/D')
            st.markdown(f"**📞 Telefono:** {telefono}")
            
            # LINK GOOGLE MAPS
            f_lat = facility.get('latitudine') or facility.get('lat')
            f_lon = facility.get('longitudine') or facility.get('lon')
            if f_lat and f_lon: 
                maps_url = f"https://www.google.com/maps/dir/?api=1&destination={f_lat},{f_lon}"
                st.link_button("🗺️ Indicazioni Stradali", maps_url, use_container_width=True)
        
        elif coords: 
            # NESSUN RISULTATO TROVATO
            st. warning(f"⚠️ Nessuna struttura di tipo **{rec_type}** trovata nelle vicinanze di {comune_ricerca}.")
            st.info("""
            **Suggerimenti:**
            - Prova a cercare in un comune limitrofo più grande
            - Contatta il **numero unico sanitario** della tua AUSL
            - Consulta la [mappa dei servizi regionali](https://salute.regione.emilia-romagna. it/)
            """)
        
        else:
            # COORDINATE NON TROVATE
            st.error(f"❌ Impossibile localizzare il comune '{comune_ricerca}'. Verifica il nome.")
    
    # === SEZIONE 4: PROSSIMI PASSI ===
    st.divider()
    st.markdown("### 🎯 Prossimi Passi")
    c1, c2 = st.columns(2)
    
    with c1:
        if st.button("🔄 Nuovo Triage", type="primary", use_container_width=True, key="disposition_new_triage_btn"):
            # FIX: Usa privacy_accepted invece di gdpr_consent
            keys_to_preserve = ['privacy_accepted', 'high_contrast', 'font_size', 'auto_speech', 'reduce_motion']
            
            for key in list(st.session_state.keys()):
                if key not in keys_to_preserve:
                    del st.session_state[key]
            
            logger.info("New triage started from disposition")
            st.rerun()
    
    with c2:
        if st.button("💾 Salva e Esci", use_container_width=True, key="disposition_save_exit_btn"):
            save_structured_log()
            st.success("✅ Dati salvati. Puoi chiudere la finestra.")
    
    # DISCLAIMER FINALE
    st.info("ℹ️ **Nota:** Questa valutazione non sostituisce il parere medico. In caso di dubbi, contatta il 118.")
    
    logger.info(f"Disposition summary rendered: type={rec_type}, urgency={avg_urgency:. 2f}, specialization={specialization}")

def update_backend_metadata(metadata):
    """
    Aggiorna la specializzazione medica e il protocollo clinico basandosi su metadati AI
    e documenti della Knowledge Base (DA5, ASQ, Linee Guida Regionali).
    
    Implementa: 
    - Fast Track (urgenze critiche)
    - Protocol Matching (Violenza, Suicidio, Pediatria)
    - Sistema di Voto (stabilità per casi standard)
    - Instradamento Percorsi (A, B, C)
    """
    # 1. Inizializzazione e Manutenzione Storia
    if "metadata_history" not in st.session_state:
        st.session_state.metadata_history = []
    
    st.session_state.metadata_history.append(metadata)
    
    # Estrazione dati correnti dai metadati AI
    current_area = metadata.get("area", "Generale")
    current_urgency = metadata.get("urgenza", 0)
    protocol_ref = metadata.get("kb_reference") # Riferimento al documento (es. 'DA5', 'ASQ')
    
    # 2. Mapping di Normalizzazione Esteso (basato su Knowledge Base)
    # Include aree dai protocolli: Violenza (Allegato B), Suicidio (ASQ), Pediatria (Lazio/Piemonte)
    mapping = {
        "Violenza": "Violenza di Genere",
        "Maltrattamento": "Violenza di Genere",
        "Rischio Suicidio": "Psichiatria",
        "Psichiatria": "Psichiatria",
        "Salute Mentale": "Psichiatria",
        "Trauma": "Ortopedia",
        "Pediatria": "Pediatria",
        "Ginecologia": "Ginecologia",
        "Ostetricia": "Ginecologia",
        "Dipendenze": "Dipendenze",
        "Cardiologia": "Cardiologia",
        "Neurologia": "Neurologia"
    }

    # 3. LOGICA DI INSTRADAMENTO PERCORSI (A, B, C)
    # Percorso A: Emergenza | Percorso B: Pediatrico | Percorso C: Standard
    if current_urgency >= 5 or current_area == "Emergenza":
        st.session_state.triage_path = "A"
    elif metadata.get("age", 99) < 14 or current_area == "Pediatria":
        st.session_state.triage_path = "B"
        st.session_state.specialization = "Pediatria" # Override immediato per pediatria
    else:
        st.session_state.triage_path = "C"

    # 4. LOGICA FAST TRACK & PROTOCOLLI CRITICI
    # Se l'AI rileva un protocollo specifico dai documenti KB (es. ASQ o DA5), 
    # attiviamo subito la specializzazione corretta indipendentemente dai voti.
    
    is_protocol_match = protocol_ref in ["DA5", "ASQ", "WAST"]
    
    if (current_urgency >= 4 or is_protocol_match) and current_area in mapping:
        new_spec = mapping[current_area]
        st.session_state.specialization = new_spec
        logger.info(f"FAST TRACK PROTOCOLLO: {new_spec} attivato via {protocol_ref or 'Urgenza'}")
        return

    # 5. SISTEMA DI VOTO (Per stabilità nei casi non critici)
    normalized_votes = []
    urgency_per_spec = {}

    for m in st.session_state.metadata_history:
        area = m.get("area")
        urg = m.get("urgenza", 0)
        
        if area in mapping:
            spec = mapping[area]
            normalized_votes.append(spec)
            if spec not in urgency_per_spec or urg > urgency_per_spec[spec]:
                urgency_per_spec[spec] = urg

    if not normalized_votes:
        if st.session_state.get("specialization") is None:
            st.session_state.specialization = "Generale"
        return

    # Conteggio e soglia di attivazione (minimo 2 occorrenze per cambio area non urgente)
    counts = Counter(normalized_votes)
    candidates = [spec for spec, count in counts.items() if count >= 2]

    # 6. RISOLUZIONE CONFLITTI
    if not candidates:
        # Mantieni la specializzazione attuale o imposta Generale se nuova sessione
        if "specialization" not in st.session_state:
            st.session_state.specialization = "Generale"
    elif len(candidates) == 1:
        st.session_state.specialization = candidates[0]
    else:
        # In caso di sintomi misti, vince l'area con il rischio clinico (urgenza) più alto
        winner = max(candidates, key=lambda x: urgency_per_spec.get(x, 0))
        st.session_state.specialization = winner
        logger.debug(f"CONFLITTO RISOLTO: Priorità clinica a {winner}")

    # Log finale per audit backend
    logger.info(f"Update completato: Path={st.session_state.get('triage_path')}, Spec={st.session_state.specialization}")

# --- MAIN ---
# ============================================
# SESSION STATE E GESTIONE STEP
# ============================================

def init_session():
    """
    Inizializza lo stato della sessione ottimizzato per Triage AI.
    Integra i campi necessari per i protocolli KB (DA5, ASQ, Percorsi A/B/C).
    
    NUOVO: Supporta caricamento da SessionStorage per persistenza cross-istanza.
    """
    if "session_id" not in st.session_state:
        # --- 1. IDENTITÀ E TRACKING ---
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        
        # --- 2. STATE MACHINE & NAVIGAZIONE ---
        st.session_state.current_step = TriageStep.LOCATION
        st.session_state.collected_data = {}  # Contenitore validato per step
        st.session_state.step_completed = {step: False for step in TriageStep}
        st.session_state.current_phase_idx = 0
        
        # --- 3. ANALYTICS E TEMPI (Richiesti per log 2.0) ---
        st.session_state.step_timestamps = {}
        st.session_state.session_start = datetime.now()
        # Timer specifico per il primo step (📍 Localizzazione)
        st.session_state[f"{TriageStep.LOCATION.name}_start_time"] = datetime.now()
        
        # --- 4. SICUREZZA E CONSENSO ---
        st.session_state.privacy_accepted = False # Allineato con render_disclaimer
        st.session_state.critical_alert = False
        st.session_state.pending_survey = None
        
        # --- 5. ROUTING CLINICO AVANZATO (Basato su KB) ---
        st.session_state.specialization = "Generale"
        st.session_state.triage_path = "C"  # Default: Percorso Standard
        st.session_state.kb_reference = None # Traccia se attivato DA5, ASQ, WAST, ecc.
        st.session_state.metadata_history = []
        st.session_state.emergency_level = None # EmergencyLevel (Red, Yellow, etc.)
        
        # --- 6. LOGISTICA TERRITORIALE ---
        st.session_state.user_comune = None # Comune rilevato o inserito
        st.session_state.backend = BackendClient() # Connessione persistente
        
        # --- 7. QUALITÀ AI ---
        st.session_state.ai_retry_count = {} # Monitora fallimenti estrazione dati
        
        # --- 8. SESSION STORAGE INTEGRATION (NUOVO) ---
        st.session_state._storage_sync_enabled = SESSION_STORAGE_ENABLED
        st.session_state._last_storage_sync = None
        
        logger.info(f"Sessione Advanced inizializzata: {st.session_state.session_id}")
    
    # --- 9. TENTATIVO DI CARICAMENTO DA STORAGE (NUOVO) ---
    # Se è attivato il session storage e la sessione è nuova, cerca di recuperare
    if SESSION_STORAGE_ENABLED and st.session_state.get('_last_storage_sync') is None:
        # Controlla se c'è un session_id nei query params per cross-instance sync
        query_params = st.experimental_get_query_params()
        stored_session_id = query_params.get('session_id', [None])[0]
        
        if stored_session_id:
            logger.info(f"🔍 Tentativo di caricamento sessione da storage: {stored_session_id}")
            stored_data = load_session_from_storage(stored_session_id)
            
            if stored_data:
                # Carica dati dalla storage
                st.session_state.session_id = stored_session_id
                st.session_state.messages = stored_data.get('messages', [])
                st.session_state.collected_data = stored_data.get('collected_data', {})
                st.session_state.specialization = stored_data.get('specialization', 'Generale')
                st.session_state.triage_path = stored_data.get('triage_path', 'C')
                st.session_state.metadata_history = stored_data.get('metadata_history', [])
                st.session_state.user_comune = stored_data.get('user_comune')
                st.session_state.current_phase_idx = stored_data.get('current_phase_idx', 0)
                
                # Ricostruisci current_step da string se necessario
                if 'current_step' in stored_data:
                    step_name = stored_data['current_step']
                    if isinstance(step_name, str):
                        try:
                            st.session_state.current_step = TriageStep[step_name]
                        except KeyError:
                            st.session_state.current_step = TriageStep.LOCATION
                
                st.session_state._last_storage_sync = time.time()
                logger.info(f"✅ Sessione caricata da storage: {stored_session_id}")
                st.info(f"🔄 Sessione ripristinata: {len(st.session_state.messages)} messaggi caricati")
            else:
                logger.warning(f"⚠️ Sessione non trovata in storage: {stored_session_id}")

def can_proceed_to_next_step() -> bool:
    """
    Verifica se lo step corrente è completato e validato.
    Garantisce che il paziente non salti fasi critiche del triage.
    """
    current_step = st.session_state.current_step
    step_name = current_step.name
    
    # Verifica se i dati per lo step attuale sono stati salvati correttamente
    has_data = step_name in st.session_state.collected_data
    
    # Lo step DISPOSITION è l'output finale: non richiede validazione per 'procedere'
    if current_step == TriageStep.DISPOSITION:
        return True
    
    logger.debug(f"Validazione step {step_name}: {has_data}")
    return has_data

def get_step_display_name(step: TriageStep) -> str:
    """
    Restituisce il nome human-readable dello step per i componenti UI.
    Aggiunge icone standardizzate per migliorare l'accessibilità.
    """
    names = {
        TriageStep.LOCATION: "📍 Localizzazione",
        TriageStep.CHIEF_COMPLAINT: "🩺 Sintomo Principale",
        TriageStep.PAIN_SCALE: "📊 Intensità Dolore",
        TriageStep.RED_FLAGS: "🚨 Segnali di Allarme",
        TriageStep.ANAMNESIS: "📋 Anamnesi Clinica",
        TriageStep.DISPOSITION: "🏥 Raccomandazione Finale"
    }
    # Fallback in caso di step non mappato (es. SBAR o debug)
    return names.get(step, step.name.replace("_", " ").title())

def render_main_application():
    """Entry point principale applicazione."""
    init_session()
    
    # Inizializza orchestrator PRIMA di tutto
    if 'orchestrator' not in st. session_state:
        from model_orchestrator_v2 import ModelOrchestrator
        st. session_state. orchestrator = ModelOrchestrator()
        logger.info("🤖 Orchestrator inizializzato")
    
    # Usa l'orchestrator dalla session_state
    orchestrator = st.session_state. orchestrator
    
    # Inizializza il servizio farmacie
    pharmacy_db = PharmacyService()

    # STEP 1: Consenso GDPR obbligatorio
    if not st.session_state.get('privacy_accepted', False):
        st.markdown("### 📋 Benvenuto in Health Navigator")
        render_disclaimer()
        if st.button("✅ Accetto e Inizio Triage", type="primary", use_container_width=True, key="accept_gdpr_btn"):
            st.session_state.privacy_accepted = True
            st.rerun()
        return

    # STEP 2: Rendering UI principale
    render_sidebar(pharmacy_db)
    render_dynamic_step_tracker()

    # STEP 3: Check disponibilità AI
    if not orchestrator.is_available():
        st.error("❌ Servizio AI offline. Riprova più tardi.")
        return

    # STEP 4: Rendering cronologia messaggi con TTS opzionale
    for i, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            
            if m["role"] == "assistant":
                auto_speech = st.session_state.get('auto_speech', False)
                is_last_message = (i == len(st.session_state.messages) - 1)
                auto_play = auto_speech and is_last_message
                
                text_to_speech_button(
                    text=m["content"],
                    key=f"tts_msg_{i}",
                    auto_play=auto_play
                )

    # STEP 5: Check se step finale
    if st.session_state. current_step == TriageStep.DISPOSITION and \
       st.session_state. step_completed. get(TriageStep. DISPOSITION, False):
        render_disposition_summary()
        save_structured_log()
        st.stop()

    # --- STEP 6: INPUT CHAT E GENERAZIONE AI ---
    if not st.session_state.get("pending_survey"):
        # Inizializza le chiavi API
        groq_key = st.secrets. get("GROQ_API_KEY", "")
        gemini_key = st.secrets.get("GEMINI_API_KEY", "")
        
        # Validazione configurazione
        if not groq_key and not gemini_key:
            st.warning("⚠️ Configurazione API mancante.  Controlla il file secrets.toml.")
            st.info("💡 Aggiungi almeno una delle seguenti chiavi:\n- `GROQ_API_KEY`\n- `GEMINI_API_KEY`")
            st.stop()
        
        # Configura orchestrator con le chiavi (una volta sola per sessione)
        if not st.session_state.get('orchestrator_configured', False):
            orchestrator.set_keys(groq=groq_key, gemini=gemini_key)
            st.session_state.orchestrator_configured = True
            logger.info("✅ Orchestrator configurato con chiavi API")
        
        # Input utente
        if raw_input := st.chat_input("💬 Descrivi la situazione... "):
            # 1. Sanificazione Input
            user_input = DataSecurity.sanitize_input(raw_input)
            
            # ============================================
            # 🆕 FSM: CLASSIFICAZIONE PRIMO MESSAGGIO
            # ============================================
            is_first_message = len(st.session_state.messages) == 0
            
            if FSM_ENABLED and is_first_message:
                urgency_score = classify_initial_urgency_fsm(user_input)
                
                if urgency_score: 
                    # A. Se richiede 118 immediato
                    if urgency_score. requires_immediate_118:
                        st.session_state.emergency_level = EmergencyLevel.RED
                        render_emergency_overlay(EmergencyLevel.RED)
                        logger.critical(f"🚨 118 IMMEDIATO rilevato da FSM | Rationale: {urgency_score.rationale}")
                    
                    # B. Se path Mental Health (B) con branch INFO
                    elif urgency_score.assigned_path == TriagePath.B and urgency_score.assigned_branch == TriageBranch. INFORMAZIONI:
                        st.info(f"ℹ️ Rilevata richiesta informativa su salute mentale")
                        logger.info(f"📘 Branch INFORMAZIONI attivato | Rationale: {urgency_score.rationale}")
                    
                    # C. Path Emergency (A) - Max 3 domande
                    elif urgency_score.assigned_path == TriagePath.A: 
                        st.session_state.triage_path = "A"
                        st.warning(f"⚠️ Percorso Emergenza attivato | Urgenza: {urgency_score. score}/5")
                        logger.warning(f"🚨 Path A (Emergency) | Score: {urgency_score.score} | Flags: {urgency_score.detected_red_flags}")
                    
                    # D. Estrazione entità con FSM
                    if st.session_state.get('fsm_bridge'):
                        extracted_data = st.session_state. fsm_bridge.extract_entities_from_text(user_input)
                        if extracted_data:
                            # Sincronizza con TriageState
                            st.session_state.triage_state = st.session_state.fsm_bridge.sync_session_context(
                                st.session_state.triage_state,
                                extracted_data
                            )
                            logger.info(f"✅ Dati estratti da FSM: {list(extracted_data.keys())}")
            
            # 2. Check Emergenza Immediata (Text-based Legacy)
            emergency_level = assess_emergency_level(user_input, {})
            if emergency_level:
                st. session_state.emergency_level = emergency_level
                render_emergency_overlay(emergency_level)
            
            # 3. Aggiungi messaggio utente alla cronologia
            st.session_state.messages.append({"role": "user", "content": user_input})
            
            # ✅ NUOVO: Rilevamento primo messaggio per intent detection
            is_first = len(st.session_state. messages) == 1
            
            # 4. Generazione Risposta AI
            with st.chat_message("assistant", avatar="🩺"):
                placeholder = st.empty()
                typing = st.empty()
                typing.markdown('<div class="typing-indicator">🔄 Analisi in corso...</div>', unsafe_allow_html=True)
                
                # Parametri dinamici dallo stato
                current_phase = PHASES[st.session_state. current_phase_idx]
                phase_id = current_phase["id"]
                path = st.session_state.get('triage_path', 'C')
                
                full_text_vis = ""
                final_obj = None
                
                try:
                    # Chiamata streaming con collected_data per context awareness
                    res_gen = stream_ai_response(
                        orchestrator,
                        st.session_state.messages,
                        path,
                        phase_id,
                        collected_data=st.session_state.collected_data,
                        is_first_message=is_first
                    )
                    
                    # Rimuovi subito l'indicatore di caricamento
                    typing.empty()
                    
                    # Consumo generatore con logica pulita
                    for chunk in res_gen:
                        # CASO A: Dizionario già parsato
                        if isinstance(chunk, dict):
                            final_obj = chunk
                            text_chunk = chunk.get("testo", "")
                            if text_chunk and not full_text_vis:
                                full_text_vis = text_chunk
                                placeholder.markdown(full_text_vis)
                        
                        # CASO B:  Stringa (streaming incrementale)
                        elif isinstance(chunk, str):
                            full_text_vis += chunk
                            placeholder.markdown(full_text_vis)
                        
                        # CASO C: Oggetti Pydantic V2
                        elif hasattr(chunk, 'model_dump'):
                            final_obj = chunk.model_dump()
                            text_chunk = final_obj.get("testo", "")
                            if text_chunk: 
                                full_text_vis = text_chunk
                                placeholder. markdown(full_text_vis)
                    
                    # 5. Salvataggio Risposta AI
                    if full_text_vis:
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": full_text_vis
                        })
                        logger.info(f"✅ Messaggio AI salvato ({len(full_text_vis)} caratteri)")
                    else:
                        fallback_msg = "Mi dispiace, non ho ricevuto una risposta valida.  Riprova."
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": fallback_msg
                        })
                        placeholder.warning(fallback_msg)
                        logger.warning("⚠️ Nessun testo ricevuto dal generatore")
                    
                    # 6. Elaborazione Metadati
                    if final_obj:
                        metadata = final_obj.get("metadata", {})
                        
                        if metadata: 
                            # Sincronizzazione stato backend
                            update_backend_metadata(metadata)
                            
                            # ============================================
                            # 🆕 FSM: SINCRONIZZAZIONE DATI
                            # ============================================
                            if FSM_ENABLED and st.session_state.get('fsm_bridge') and st.session_state.get('triage_state'):
                                try:
                                    # A. Estrai dati dal testo AI se presenti
                                    if full_text_vis: 
                                        fsm_extracted = st.session_state.fsm_bridge.extract_entities_from_text(full_text_vis)
                                        if fsm_extracted:
                                            # Sincronizza con TriageState
                                            st.session_state.triage_state = st.session_state.fsm_bridge.sync_session_context(
                                                st.session_state.triage_state,
                                                fsm_extracted
                                            )
                                    
                                    # B.  Sincronizza collected_data legacy con FSM
                                    if st.session_state.collected_data:
                                        st. session_state.triage_state = st.session_state.fsm_bridge.sync_session_context(
                                            st. session_state.triage_state,
                                            st.session_state.collected_data
                                        )
                                    
                                    # C. Verifica completezza triage
                                    validation = st.session_state.fsm_bridge.validate_triage_completeness(
                                        st.session_state. triage_state
                                    )
                                    
                                    if validation['can_proceed_disposition'] and not validation['is_complete']:
                                        logger. info(f"⚠️ Triage parziale ma sufficiente per disposition | "
                                                   f"Completezza: {validation['completion_percentage']:.1%}")
                                
                                except Exception as e:
                                    logger.error(f"❌ Errore sincronizzazione FSM: {e}", exc_info=True)
                            
                            # Verifica emergenze dai metadati
                            emergency_level = assess_emergency_level(user_input, metadata)
                            if emergency_level:
                                st.session_state.emergency_level = emergency_level
                                render_emergency_overlay(emergency_level)
                            
                            # Gestione Protocolli Critici
                            kb_ref = metadata.get("kb_reference", "")
                            if kb_ref:
                                st. session_state.kb_reference = kb_ref
                                logger. info(f"📄 Protocollo rilevato:  {kb_ref}")
                                
                                critical_protocols = ["DA5", "ASQ", "WAST", "AUDIT"]
                                if any(protocol in kb_ref for protocol in critical_protocols):
                                    logger.warning(f"🚨 Protocollo critico:  {kb_ref}")
                                    if not st.session_state.get('emergency_level'):
                                        st.session_state.emergency_level = EmergencyLevel. ORANGE
                                    render_emergency_overlay(st.session_state.emergency_level)
                        
                        # 7. Gestione Survey
                        if final_obj.get("opzioni"):
                            st.session_state.pending_survey = final_obj
                            logger.info(f"📋 Survey con {len(final_obj['opzioni'])} opzioni")
                        
                        # 7b. Estrazione automatica dati multipli
                        dati_estratti = final_obj.get("dati_estratti", {})
                        if dati_estratti and isinstance(dati_estratti, dict):
                            for key, value in dati_estratti.items():
                                if value: 
                                    st.session_state.collected_data[key] = value
                                    logger. info(f"✅ Dato estratto automaticamente: {key} = {value}")
                            
                            # Check auto-advancement dopo estrazione dati
                            auto_advance_if_ready()
                        
                        # FIX BUG #2: Salvataggio fallback per RED_FLAGS
                        if st.session_state.current_step == TriageStep. RED_FLAGS:
                            if 'RED_FLAGS' not in st.session_state. collected_data:
                                last_user_msg = next(
                                    (m['content'] for m in reversed(st.session_state.messages) if m.get('role') == 'user'),
                                    None
                                )
                                if last_user_msg:
                                    st.session_state.collected_data['RED_FLAGS'] = last_user_msg
                                    logger.info(f"✅ RED_FLAGS salvato da risposta testuale:  {last_user_msg}")
                                    auto_advance_if_ready()
                    
                    # 8. Rerun
                    st.rerun()
                
                except Exception as e:
                    logger.error(f"❌ Errore critico: {e}", exc_info=True)
                    error_msg = "Si è verificato un errore di comunicazione con l'AI. Riprova."
                    placeholder.error(error_msg)
                    st.session_state. messages.append({
                        "role": "assistant",
                        "content": "⚠️ " + error_msg
                    })
                    st.session_state.pending_survey = None

    # STEP 7: Rendering opzioni survey (se presenti)
    if st.session_state.get("pending_survey"):
        st.markdown("---")
        opts = st.session_state.pending_survey. get("opzioni", [])
        
        if not opts or len(opts) == 0:
            st.caption("⚠️ *L'assistente sta usando opzioni predefinite.*")
            opts = get_fallback_options(st.session_state.current_step)
        
        logger.info(f"🔍 Rendering {len(opts)} opzioni")
        cols = st.columns(len(opts))
        
        for i, opt in enumerate(opts):
            unique_key = f"btn_{st.session_state.current_step. name}_{i}"
            if cols[i].button(opt, key=unique_key, use_container_width=True):
                current_step = st.session_state.current_step
                step_name = current_step.name
                validation_success = False
                
                # FIX BUG #1: Aggiungi messaggio utente alla cronologia PRIMA della validazione
                st.session_state.messages.append({
                    "role": "user",
                    "content": opt
                })
                logger.info(f"✅ Bottone cliccato salvato in cronologia: {opt}")
                
                # Validazione per step
                if current_step == TriageStep.LOCATION:
                    is_valid, normalized = InputValidator.validate_location(opt)
                    if is_valid: 
                        st.session_state.collected_data[step_name] = normalized
                        st.session_state.user_comune = normalized
                        validation_success = True
                    else: 
                        st.warning(f"⚠️ Comune '{opt}' non valido.")
                        st.session_state.pending_survey = None
                        st.rerun()
                
                elif current_step == TriageStep. CHIEF_COMPLAINT:
                    st.session_state.collected_data[step_name] = opt
                    validation_success = True
                
                elif current_step == TriageStep.PAIN_SCALE:
                    is_valid, pain_value = InputValidator.validate_pain_scale(opt)
                    st.session_state.collected_data[step_name] = pain_value if is_valid else opt
                    validation_success = True
                
                elif current_step == TriageStep.RED_FLAGS:
                    is_valid, flags = InputValidator.validate_red_flags(opt)
                    st.session_state.collected_data[step_name] = flags
                    validation_success = True
                
                elif current_step == TriageStep.ANAMNESIS:
                    is_valid, age = InputValidator.validate_age(opt)
                    if is_valid:
                        st.session_state.collected_data['age'] = age
                    st.session_state.collected_data[step_name] = opt
                    validation_success = True
                
                elif current_step == TriageStep.DISPOSITION:
                    st.session_state.collected_data[step_name] = opt
                    validation_success = True
                
                # Clear survey e avanza
                st.session_state. pending_survey = None
                
                if validation_success:
                    advance_step()
                    if st.session_state.current_phase_idx < len(PHASES) - 1:
                        st.session_state.current_phase_idx += 1
                
                st.rerun()
    
    # Gestione input personalizzato "Altro"
    if st.session_state.get("show_altro"):
        st.markdown("<div class='fade-in'>", unsafe_allow_html=True)
        c1, c2 = st. columns([4, 1])
        
        val = c1.text_input(
            "Dettaglia qui:",
            placeholder="Scrivi.. .",
            key=f"altro_input_{st.session_state. current_step.name}"
        )
        
        if c2.button("✖", key=f"cancel_altro_{st.session_state.current_step.name}"):
            st.session_state.show_altro = False
            st.rerun()
        
        if val and st.button("Invia", key=f"send_custom_{st.session_state.current_step.name}", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": val})
            current_step = st.session_state.current_step
            step_name = current_step.name
            validation_success = False
            
            # Validazione per step personalizzato
            if current_step == TriageStep.LOCATION:
                is_valid, normalized = InputValidator.validate_location(val)
                if is_valid:
                    st.session_state.collected_data[step_name] = normalized
                    st.session_state.user_comune = normalized
                    validation_success = True
                else:
                    st.warning("⚠️ Comune non riconosciuto.")
                    time.sleep(2)
                    st.rerun()
            
            elif current_step == TriageStep. CHIEF_COMPLAINT:
                st.session_state.collected_data[step_name] = val
                validation_success = True
            
            elif current_step == TriageStep.PAIN_SCALE:
                is_valid, pain_value = InputValidator. validate_pain_scale(val)
                st.session_state. collected_data[step_name] = pain_value if is_valid else val
                validation_success = True
            
            elif current_step == TriageStep.RED_FLAGS:
                st.session_state.collected_data[step_name] = [val]
                validation_success = True
            
            elif current_step == TriageStep. ANAMNESIS:
                is_valid, age = InputValidator.validate_age(val)
                if is_valid:
                    st.session_state.collected_data['age'] = age
                st.session_state.collected_data[step_name] = val
                validation_success = True
            
            elif current_step == TriageStep.DISPOSITION: 
                st.session_state.collected_data[step_name] = val
                validation_success = True
            
            if validation_success:
                st.session_state.pending_survey = None
                st.session_state.show_altro = False
                advance_step()
                if st. session_state.current_phase_idx < len(PHASES) - 1:
                    st. session_state.current_phase_idx += 1
                st. rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)

def main():
    """Entry point principale che chiama render_main_application."""
    render_main_application()


if __name__ == "__main__":

    main()

