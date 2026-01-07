import streamlit as st
import json
import time
import uuid
import os
import logging
import random
import re
import requests
import math
import difflib  # Aggiunta per il matching dei comuni
from datetime import datetime

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
    """Inizializza lo stato della sessione allineato con il sistema di Privacy."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.current_step = TriageStep.LOCATION
        st.session_state.current_phase_idx = 0
        st.session_state.collected_data = {}
        st.session_state.step_completed = {step: False for step in TriageStep}
        st.session_state.metadata_history = []
        st.session_state.pending_survey = None
        
        # Allineato con la funzione render_disclaimer
        st.session_state.privacy_accepted = False 
        
        st.session_state.specialization = "Generale"
        st.session_state.backend = BackendClient()
        st.session_state.emergency_level = None
        st.session_state.user_comune = None
        logger.info(f"Nuova sessione inizializzata: {st.session_state.session_id}")


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
    
    # Ottieni il valore massimo dell'enum
    max_value = max(step.value for step in TriageStep)
    
    # Avanza solo se non è l'ultimo step
    if current_value < max_value:
        # Crea il prossimo step usando il value + 1
        next_step = TriageStep(current_value + 1)
        st.session_state.current_step = next_step
        
        # Inizia timer nuovo step
        st.session_state[f'{next_step.name}_start_time'] = datetime.now()
        
        # Feedback visivo
        st.toast(f"✅ Completato:  {current_step.name}", icon="✅")
        
        logger.info(f"Advanced from {current_step.name} (value={current_value}) to {next_step.name} (value={next_step.value})")
        return True
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


# PARTE 3: Componenti UI - Progress Bar
def render_progress_bar():
    """
    Renderizza barra progresso con indicatori visivi per ogni step.
    """
    current_step = st.session_state.current_step
    
    step_ui_data = {
        TriageStep.LOCATION: {"emoji": "📍", "label": "Posizione", "description": "Comune di riferimento"},
        TriageStep.CHIEF_COMPLAINT: {"emoji": "🩺", "label": "Sintomi", "description": "Disturbo principale"},
        TriageStep.PAIN_SCALE: {"emoji": "📊", "label": "Intensità", "description": "Scala dolore"},
        TriageStep.RED_FLAGS: {"emoji": "🚨", "label": "Urgenza", "description": "Sintomi gravi"},
        TriageStep.ANAMNESIS: {"emoji": "📋", "label": "Anamnesi", "description": "Dati clinici"},
        TriageStep.DISPOSITION: {"emoji": "🏥", "label": "Verdetto", "description": "Raccomandazione"}
    }
    
    total_steps = len(TriageStep)
    completed_count = sum(1 for status in st.session_state.step_completed.values() if status)
    progress_percentage = completed_count / total_steps
    
    st.progress(progress_percentage, text=f"Progresso Triage: {completed_count}/{total_steps} step completati")
    
    cols = st.columns(total_steps)
    
    for i, step in enumerate(TriageStep):
        ui_data = step_ui_data[step]
        is_current = (step == current_step)
        is_completed = st.session_state.step_completed.get(step, False)
        
        if is_completed:
            status_emoji = "✅"
            status_color = "#10b981"
            status_text = "Completato"
        elif is_current:
            status_emoji = "▶️"
            status_color = "#3b82f6"
            status_text = "In corso"
        else:
            status_emoji = "⏸️"
            status_color = "#9ca3af"
            status_text = "Da fare"
        
        with cols[i]:
            st.markdown(f"""
            <div style='text-align: center; padding: 10px; border-radius: 8px;
                        background: {"#f0fdf4" if is_completed else "#f9fafb"};
                        border: 2px solid {status_color if is_current else "transparent"};'>
                <div style='font-size: 2em; margin-bottom: 5px;' role='img' aria-label='{ui_data["description"]}'>
                    {ui_data['emoji']}
                </div>
                <div style='font-size: 1.2em; margin-bottom: 3px;'>{status_emoji}</div>
                <div style='font-size: 0.75em; font-weight: 600; color: {status_color};'>{ui_data['label']}</div>
                <div style='font-size: 0.65em; color: #6b7280; margin-top: 3px;'>{status_text}</div>
            </div>
            """, unsafe_allow_html=True)
    
    st.divider()
    logger.debug(f"Progress bar rendered: {completed_count}/{total_steps} steps")


# PARTE 3: Badge Urgenza Real-Time
def render_urgency_badge():
    """
    Renderizza badge urgenza che si aggiorna in base ai metadata AI raccolti.
    """
    urgency_values = [
        m.get('urgenza', 3)
        for m in st.session_state.metadata_history
        if isinstance(m, dict) and 'urgenza' in m
    ]
    
    if not urgency_values:
        avg_urgency = 3.0
        has_data = False
    else:
        recent_values = urgency_values[-3:]
        avg_urgency = sum(recent_values) / len(recent_values)
        has_data = True
    
    trend_emoji = ""
    if len(urgency_values) >= 2:
        last_value = urgency_values[-1]
        previous_value = urgency_values[-2]
        if last_value > previous_value:
            trend_emoji = "↗️"
        elif last_value < previous_value:
            trend_emoji = "↘️"
        else:
            trend_emoji = "➡️"
    
    if avg_urgency <= 2.0:
        bg_color, text_color, border_color = "#10b981", "#ffffff", "#059669"
        label, emoji, advice = "BASSA", "😊", "Situazione gestibile"
    elif avg_urgency <= 3.0:
        bg_color, text_color, border_color = "#f59e0b", "#ffffff", "#d97706"
        label, emoji, advice = "MODERATA", "😐", "Monitorare sintomi"
    elif avg_urgency <= 4.0:
        bg_color, text_color, border_color = "#f97316", "#ffffff", "#ea580c"
        label, emoji, advice = "ALTA", "😟", "Valutazione medica raccomandata"
    else:
        bg_color, text_color, border_color = "#dc2626", "#ffffff", "#b91c1c"
        label, emoji, advice = "CRITICA", "😰", "Intervento urgente necessario"
    
    st.markdown(f"""
    <div style='background: linear-gradient(135deg, {bg_color} 0%, {border_color} 100%);
                color: {text_color}; padding: 15px 25px; border-radius: 12px;
                text-align: center; margin: 15px 0; box-shadow: 0 4px 12px rgba(0,0,0,0.15);'
         role='status' aria-live='polite' aria-label='Livello urgenza: {label}'>
        <div style='font-size: 2em; margin-bottom: 5px;'>{emoji} {trend_emoji}</div>
        <div style='font-size: 1.3em; font-weight: 700;'>URGENZA: {label}</div>
        <div style='font-size: 0.95em; margin-top: 8px;'>Livello {avg_urgency:.1f}/5.0</div>
        <div style='font-size: 0.85em; margin-top: 5px; font-style: italic;'>{advice}</div>
        {f"<div style='font-size: 0.75em; margin-top: 8px; opacity: 0.8;'>Basato su {len(urgency_values)} valutazioni</div>" if has_data else ""}
    </div>
    """, unsafe_allow_html=True)
    
    logger.debug(f"Urgency badge rendered: avg={avg_urgency:.2f}, label={label}")


# PARTE 3: Text-to-Speech con Fallback
def text_to_speech_button(text: str, key: str, auto_play: bool = False):
    """
    Renderizza bottone Text-to-Speech con Web Speech API.
    """
    clean_text = text.replace('`', '').replace("'", "\\'").replace('"', '\\"')
    if len(clean_text) > 500:
        clean_text = clean_text[:497] + "..."
        logger.warning(f"TTS text truncated for key={key}")
    
    tts_html = f"""
    <div style='display: inline-block; margin: 5px 0;'>
        <button id='tts-btn-{key}' onclick='speakText_{key}()'
                style='background: #3b82f6; color: white; border: none; padding: 8px 16px;
                       border-radius: 8px; cursor: pointer; font-size: 0.9em;'
                aria-label='Leggi testo ad alta voce'>
            🔊 Ascolta
        </button>
        <span id='tts-status-{key}' style='font-size: 0.8em; color: #6b7280; margin-left: 8px;'></span>
    </div>
    
    <script>
        function speakText_{key}() {{
            const text = `{clean_text}`;
            const statusEl = document.getElementById('tts-status-{key}');
            const btnEl = document.getElementById('tts-btn-{key}');
            
            if (!('speechSynthesis' in window)) {{
                statusEl.textContent = '❌ Browser non supporta TTS';
                btnEl.disabled = true;
                return;
            }}
            
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'it-IT';
            utterance.rate = 0.9;
            
            utterance.onstart = function() {{
                statusEl.textContent = '🔊 In riproduzione...';
                btnEl.textContent = '⏹️ Stop';
                btnEl.onclick = function() {{ window.speechSynthesis.cancel(); }};
            }};
            
            utterance.onend = function() {{
                statusEl.textContent = '✅ Completato';
                btnEl.textContent = '🔊 Ascolta';
                btnEl.onclick = function() {{ speakText_{key}(); }};
                setTimeout(() => {{ statusEl.textContent = ''; }}, 3000);
            }};
            
            window.speechSynthesis.speak(utterance);
        }}
        {'speakText_' + key + '();' if auto_play else ''}
    </script>
    """
    st.markdown(tts_html, unsafe_allow_html=True)
    logger.debug(f"TTS button rendered: key={key}, auto_play={auto_play}")


# PARTE 3: Schermata Recap e Raccomandazione Finale
def render_disposition_summary():
    """
    Renderizza schermata finale con recap dati e raccomandazione.
    """
    st.markdown("---")
    st.markdown("## 📋 Riepilogo Triage e Raccomandazione")
    
    collected = st.session_state.collected_data
    
    urgency_values = [m.get('urgenza', 3) for m in st.session_state.metadata_history if 'urgenza' in m]
    avg_urgency = sum(urgency_values) / len(urgency_values) if urgency_values else 3.0
    
    st.markdown("### 📊 Dati Raccolti")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""
        **📍 Localizzazione:** {collected.get('LOCATION', 'Non specificata')}  
        **🩺 Sintomo Principale:** {collected.get('CHIEF_COMPLAINT', 'Non specificato')}  
        **📊 Intensità Dolore:** {collected.get('PAIN_SCALE', 'N/D')}/10
        """)
    
    with col2:
        st.markdown(f"""
        **👤 Età:** {collected.get('age', 'Non specificata')} anni  
        **🚨 Red Flags:** {', '.join(collected.get('RED_FLAGS', [])) or 'Nessuno'}  
        **⚡ Livello Urgenza:** {avg_urgency:.1f}/5.0
        """)
    
    st.divider()
    st.markdown("### 🏥 Raccomandazione")
    
    if avg_urgency >= 4.5:
        rec_type, rec_urgency, rec_color = 'Pronto Soccorso', 'IMMEDIATA', '#dc2626'
        rec_msg, facility_type = 'Recati **immediatamente** al PS o chiama 118.', 'pronto_soccorso'
    elif avg_urgency >= 3.5:
        rec_type, rec_urgency, rec_color = 'Pronto Soccorso', 'URGENTE', '#f97316'
        rec_msg, facility_type = 'Si consiglia PS **entro 2 ore**.', 'pronto_soccorso'
    elif avg_urgency >= 2.5:
        rec_type, rec_urgency, rec_color = 'CAU', 'MODERATA', '#f59e0b'
        rec_msg, facility_type = 'Valutazione presso **CAU** o Guardia Medica.', 'cau'
    else:
        rec_type, rec_urgency, rec_color = 'Medico di Base', 'BASSA', '#10b981'
        rec_msg, facility_type = 'Contatta il **Medico di Base** nei prossimi giorni.', None
    
    st.markdown(f"""
    <div style='background: {rec_color}; color: white; padding: 25px; border-radius: 15px;
                margin: 20px 0; text-align: center; box-shadow: 0 8px 20px rgba(0,0,0,0.15);'>
        <h3 style='margin: 10px 0;'>{rec_type}</h3>
        <p style='font-size: 1.1em;'>Urgenza: <strong>{rec_urgency}</strong></p>
        <p style='font-size: 1em;'>{rec_msg}</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.session_state.collected_data['DISPOSITION'] = {
        'type': rec_type, 'urgency': avg_urgency, 'facility_name': None, 'distance': None, 'eta': None
    }
    
    if facility_type:
        st.markdown("### 📍 Struttura Più Vicina")
        comune = collected.get('LOCATION')
        if comune:
            coords = get_comune_coordinates(comune)
            if coords:
                with st.spinner("🔍 Ricerca struttura..."):
                    nearest = find_nearest_facilities(coords['lat'], coords['lon'], facility_type, 1)
                
                if nearest:
                    facility = nearest[0]
                    area_type = get_area_type_from_comune(comune)
                    eta = estimate_eta(facility['distance_km'], area_type)
                    
                    st.session_state.collected_data['DISPOSITION'].update({
                        'facility_name': facility.get('nome'),
                        'distance': facility['distance_km'],
                        'eta': eta['duration_minutes']
                    })
                    
                    st.success(f"✅ Trovata: **{facility.get('nome')}**")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Distanza", f"{facility['distance_km']} km")
                    c2.metric("Tempo Stimato", f"~{eta['duration_minutes']} min")
                    c3.metric("Tipo Area", area_type.title())
                    
                    st.markdown(f"**📫 Indirizzo:** {facility.get('indirizzo', 'N/D')}")
                    st.markdown(f"**📞 Telefono:** {facility.get('telefono', 'N/D')}")
                    
                    f_lat = facility.get('latitudine') or facility.get('lat')
                    f_lon = facility.get('longitudine') or facility.get('lon')
                    if f_lat and f_lon:
                        maps_url = f"https://www.google.com/maps/dir/?api=1&destination={f_lat},{f_lon}"
                        st.link_button("🗺️ Indicazioni Stradali", maps_url, use_container_width=True)
    
    st.divider()
    st.markdown("### 🎯 Prossimi Passi")
    c1, c2 = st.columns(2)
    
    with c1:
        if st.button("🔄 Nuovo Triage", type="primary", use_container_width=True, key="disposition_new_triage_btn"):
            for key in list(st.session_state.keys()):
                if key not in ['gdpr_consent', 'high_contrast', 'font_size', 'auto_speech']:
                    del st.session_state[key]
            logger.info("New triage started from disposition")
            st.rerun()
    
    with c2:
        if st.button("💾 Salva e Esci", use_container_width=True, key="disposition_save_exit_btn"):
            save_structured_log()
            st.success("✅ Dati salvati. Puoi chiudere la finestra.")
    
    st.info("ℹ️ **Nota:** Questa valutazione non sostituisce il parere medico. In caso di dubbi, contatta il 118.")
    logger.info(f"Disposition summary rendered: type={rec_type}, urgency={avg_urgency:.2f}")


def update_backend_metadata(metadata):
    """Aggiorna lo stato della specializzazione basandosi sui dati del triage."""
    st.session_state.metadata_history.append(metadata)
    areas = [m.get("area") for m in st.session_state.metadata_history if m.get("area")]
    
    if areas.count("Trauma") >= 2:
        st.session_state.specialization = "Ortopedia"
    elif areas.count("Psichiatria") >= 2:
        st.session_state.specialization = "Psichiatria"

# --- MAIN ---
# ============================================
# SESSION STATE E GESTIONE STEP
# ============================================

def init_session():
    """
    Inizializza stato sessione con supporto State Machine. 
    
    CAMPI NUOVI (PARTE 1):
    - current_step: TriageStep enum (step corrente)
    - collected_data: Dict con dati validati per ogni step
    - step_completed: Dict[TriageStep, bool] (tracking completamenti)
    - step_timestamps: Dict con timing per analytics
    - session_start:  Timestamp inizio sessione
    - ai_retry_count: Dict per tracking retry AI per fase
    - emergency_level:  Livello emergenza corrente (EmergencyLevel o None)
    - user_comune: Comune dell'utente per smart routing
    """
    if "session_id" not in st.session_state:
        # ID sessione univoco
        st.session_state.session_id = str(uuid.uuid4())
        
        # Cronologia messaggi (invariato)
        st.session_state.messages = []
        
        # NUOVO:  State Machine
        st.session_state.current_step = TriageStep. LOCATION
        st.session_state.collected_data = {}  # {step_name: validated_value}
        st.session_state.step_completed = {step: False for step in TriageStep}
        
        # NUOVO: Tracking temporale
        st.session_state. step_timestamps = {}  # {step_name: {'start': dt, 'end': dt}}
        st.session_state.session_start = datetime.now()
        
        # Campi esistenti (mantieni)
        st.session_state. current_phase_idx = 0
        st.session_state.pending_survey = None
        st. session_state.critical_alert = False
        st. session_state.gdpr_consent = False
        st.session_state.specialization = "Generale"
        st.session_state.metadata_history = []
        st. session_state.backend = BackendClient()
        
        # NUOVO: Retry tracking per AI
        st.session_state. ai_retry_count = {}
        
        # NUOVO:  Livello emergenza corrente
        st.session_state.emergency_level = None
        
        # NUOVO: Comune utente per smart routing
        st.session_state.user_comune = None
        
        logger.info(f"New session initialized: {st.session_state. session_id}")


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
    
    # Step DISPOSITION è speciale:  si completa automaticamente
    if current_step == TriageStep. DISPOSITION:
        return True
    
    logger.debug(f"can_proceed_to_next_step: step={step_name}, has_data={has_data}")
    return has_data


def get_step_display_name(step: TriageStep) -> str:
    """
    Ottiene nome human-readable per step.
    
    Args:
        step: TriageStep enum
    
    Returns:
        Stringa descrittiva in italiano
    """
    names = {
        TriageStep.LOCATION: "📍 Localizzazione",
        TriageStep.CHIEF_COMPLAINT:  "🩺 Sintomo Principale",
        TriageStep.PAIN_SCALE: "📊 Intensità Dolore",
        TriageStep.RED_FLAGS:  "🚨 Segnali di Allarme",
        TriageStep.ANAMNESIS: "📋 Anamnesi",
        TriageStep.DISPOSITION: "🏥 Raccomandazione"
    }
    return names.get(step, step.name)

def render_main_application():
    """Entry point principale applicazione."""
    init_session()
    orchestrator = ModelOrchestrator()
    pharmacy_db = PharmacyService()

    # STEP 1: Consenso GDPR obbligatorio
    if not st.session_state.gdpr_consent:
        st.markdown("### 📋 Benvenuto in Health Navigator")
        render_disclaimer()
        if st.button("✅ Accetto e Inizio Triage", type="primary", use_container_width=True, key="accept_gdpr_btn"):
            st.session_state.gdpr_consent = True
            st.rerun()
        return

    # STEP 2: Rendering UI principale
    render_sidebar(pharmacy_db)
    render_header(PHASES[st.session_state.current_phase_idx])

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
    if st.session_state.current_step == TriageStep.DISPOSITION and \
       st.session_state.step_completed.get(TriageStep.DISPOSITION, False):
        render_disposition_summary()
        save_structured_log()
        st.stop()

    # STEP 6: Input utente e generazione domanda AI
    if not st.session_state.pending_survey:
        if raw_input := st.chat_input("💬 Descrivi i sintomi... "):
            user_input = DataSecurity.sanitize_input(raw_input)
            
            # Check immediato emergenze basato su testo
            emergency_level = assess_emergency_level(user_input, {})
            if emergency_level:
                st.session_state.emergency_level = emergency_level
                render_emergency_overlay(emergency_level)
            
            # Aggiunta immediata del messaggio utente
            st.session_state.messages. append({"role": "user", "content": user_input})
            
            with st.chat_message("assistant", avatar="🩺"):
                placeholder = st. empty()
                typing = st. empty()
                typing.markdown('<div class="typing-indicator">Analisi triage...  </div>', unsafe_allow_html=True)
                
                phase_id = PHASES[st. session_state. current_phase_idx]["id"]
                path = "C"  # Percorso standard
                full_text_vis = ""
                final_obj = None
                
                try:
                    # ✅ CORREZIONE:  4 parametri esatti come da firma bridge. py
                    res_gen = stream_ai_response(
                        orchestrator,           # 1. orchestrator
                        st.session_state.messages,  # 2. messages
                        path,                   # 3. path
                        phase_id                # 4. phase
                    )
                    
                    typing.empty()
                    
                    # Consumo del generatore in tempo reale
                    for chunk in res_gen: 
                        if isinstance(chunk, str):
                            full_text_vis += chunk
                            placeholder.markdown(full_text_vis)
                        # ✅ FIX PYDANTIC V2
                        elif hasattr(chunk, 'model_dump'):  
                            final_obj = chunk. model_dump()
                        elif isinstance(chunk, dict):
                            final_obj = chunk
                    
                except Exception as e:
                    logger.error(f"Error during AI generation: {e}", exc_info=True)
                    full_text_vis = "Mi dispiace, si è verificato un errore di connessione con l'AI.  Riprova tra un istante."
                    placeholder.error(full_text_vis)
                
                # SALVATAGGIO STATO: Essenziale per non perdere la risposta al rerun
                if full_text_vis:
                    st.session_state.messages. append({
                        "role": "assistant",
                        "content": full_text_vis
                    })
                    logger.info(f"✅ Assistant message added:  {len(full_text_vis)} chars")
                
                # Gestione Metadata e Survey
                if final_obj: 
                    metadata = final_obj.get("metadata", {})
                    
                    # Check emergenze dai metadata AI
                    if metadata:
                        update_backend_metadata(metadata)
                        emergency_level = assess_emergency_level(user_input, metadata)
                        if emergency_level: 
                            st.session_state. emergency_level = emergency_level
                            if emergency_level == EmergencyLevel.BLACK: 
                                st.session_state.critical_alert = True
                            render_emergency_overlay(emergency_level)
                        
                        # Check tempi d'attesa PS
                        urgency = metadata.get("urgenza", 3)
                        comune_utente = st.session_state.get("user_comune")
                        
                        if comune_utente and should_show_ps_wait_times(comune_utente, urgency):
                            render_ps_wait_times_alert(
                                comune_utente, 
                                urgency, 
                                has_cau_alternative=(3.0 <= urgency < 4.5)
                            )
                    
                    # Gestione Opzioni (Survey)
                    if final_obj.get("opzioni"):
                        st.session_state.pending_survey = final_obj
                        logger.info(f"📋 Survey options set: {final_obj. get('opzioni')}")
                    
                    # ✅ BACKEND SYNC SILENZIOSO
                    if metadata:
                        try:
                            if hasattr(st.session_state, 'backend') and st.session_state.backend:
                                st.session_state.backend. sync(metadata)
                        except Exception as sync_err:
                            logger.warning(f"Backend sync failed (non-blocking): {sync_err}")
                            pass  # Silenzio totale, non blocca il chatbot
                
                # Rerender per mostrare i bottoni della survey o il messaggio finale
                st.rerun()

    # STEP 7: Rendering opzioni survey (se presenti)
        if st.session_state.pending_survey:
            st.markdown("---")
            opts = st.session_state.pending_survey.get("opzioni", [])
    
        if not opts or len(opts) == 0:
            st.caption("⚠️ *L'assistente sta usando opzioni predefinite per garantire la continuità del servizio.*")
        else:
            opts = get_fallback_options(st.session_state.current_step)
            logger.info(f"🔍 Rendering survey options: {opts}")
            cols = st.columns(len(opts))
            for i, opt in enumerate(opts):
                    logger.info(f"🔍 Option [{i}]: value='{opt}', type={type(opt)}")
                    
                    # La chiave ora include il nome dello step (es. btn_LOCATION_0)
                    unique_key = f"btn_{st.session_state.current_step.name}_{i}"
                    if cols[i].button(opt, key=unique_key, use_container_width=True):
                            current_step = st.session_state.current_step
                            step_name = current_step.name
                        
                        # SECONDA: Validazione E salvataggio PRIMA di advance_step()
                        validation_success = False
                        
                        if current_step == TriageStep.LOCATION:
                            is_valid, normalized = InputValidator.validate_location(opt)
                            if is_valid:
                                st.session_state.collected_data[step_name] = normalized
                                st.session_state.user_comune = normalized
                                validation_success = True
                                logger.info(f"✅ Location validated: {normalized}")
                            else:
                                st.warning(f"⚠️ Comune '{opt}' non valido. Riprova.")
                                st.session_state.pending_survey = None
                                st.rerun()
                                
                        elif current_step == TriageStep.CHIEF_COMPLAINT:
                            st.session_state.collected_data[step_name] = opt
                            validation_success = True
                            
                        elif current_step == TriageStep.PAIN_SCALE:
                            is_valid, pain_value = InputValidator.validate_pain_scale(opt)
                            if is_valid: 
                                st.session_state.collected_data[step_name] = pain_value
                                validation_success = True
                            else:
                                st.session_state.collected_data[step_name] = opt
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
                    
                    # TERZA: Clear pending survey PRIMA di advance
                    st.session_state.pending_survey = None
                    
                    # QUARTA:  Avanza SOLO se validazione OK
                    if validation_success: 
                        advance_result = advance_step()
                        logger.info(f"✅ Step completed: {step_name}, advanced:  {advance_result}")
                        
                        # Mantieni compatibilità con current_phase_idx
                        if st.session_state.current_phase_idx < len(PHASES) - 1:
                            st.session_state.current_phase_idx += 1
                    else:
                        logger.warning(f"⚠️ Validation failed for step {step_name}")
                    
                    st.rerun()
        
        if st.session_state.get("show_altro"):
            st.markdown("<div class='fade-in'>", unsafe_allow_html=True)
            
            # Layout con colonna per testo e colonna per tasto chiudi
            c1, c2 = st.columns([4, 1])
            
            # Chiave univoca per l'input di testo basata sullo step corrente
            val = c1.text_input(
                "Dettaglia qui:", 
                placeholder="Scrivi...", 
                key=f"altro_input_{st.session_state.current_step.name}"
            )
            
            # Pulsante ANNULLA (✖)
            if c2.button("✖", key=f"cancel_altro_{st.session_state.current_step.name}"):
                st.session_state.show_altro = False
                st.rerun()

            # Pulsante INVIA (Esegue la validazione e il salvataggio)
            if val and st.button("Invia", key=f"send_custom_{st.session_state.current_step.name}", use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": val})
                
                current_step = st.session_state.current_step
                step_name = current_step.name
                validation_success = False
                
                # --- LOGICA DI VALIDAZIONE DIFFERENZIATA ---
                if current_step == TriageStep.LOCATION:
                    is_valid, normalized = InputValidator.validate_location(val)
                    if is_valid:
                        st.session_state.collected_data[step_name] = normalized
                        st.session_state.user_comune = normalized
                        validation_success = True
                    else:
                        st.warning("⚠️ Comune non riconosciuto. Inserisci un comune dell'Emilia-Romagna.")
                        time.sleep(2)
                        st.rerun()
                        
                elif current_step == TriageStep.CHIEF_COMPLAINT: 
                    st.session_state.collected_data[step_name] = val
                    validation_success = True
                    
                elif current_step == TriageStep.PAIN_SCALE:
                    is_valid, pain_value = InputValidator.validate_pain_scale(val)
                    if is_valid: 
                        st.session_state.collected_data[step_name] = pain_value
                    else:
                        st.session_state.collected_data[step_name] = val
                    validation_success = True
                    
                elif current_step == TriageStep.RED_FLAGS: 
                    # Salviamo i dati come lista per coerenza
                    st.session_state.collected_data[step_name] = [val]
                    validation_success = True
                    
                elif current_step == TriageStep.ANAMNESIS:
                    is_valid, age = InputValidator.validate_age(val)
                    if is_valid:
                        st.session_state.collected_data['age'] = age
                    st.session_state.collected_data[step_name] = val
                    validation_success = True
                    
                elif current_step == TriageStep.DISPOSITION:
                    st.session_state.collected_data[step_name] = val
                    validation_success = True
                
                # --- CONCLUSIONE E AVANZAMENTO ---
                if validation_success:
                    st.session_state.pending_survey = None
                    st.session_state.show_altro = False
                    advance_step()
                    # Se necessario, aggiorna l'indice della fase visuale
                    if st.session_state.current_phase_idx < len(PHASES) - 1:
                        st.session_state.current_phase_idx += 1
                    st.rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)

def main():
    """Entry point principale che chiama render_main_application."""
    render_main_application()


if __name__ == "__main__":
    main()
