import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class SmartRouter:
    """Integrazione avanzata con master_kb. json e logica specialistica"""
    
    def __init__(self, kb_path: str = "master_kb. json"):
        self.kb = self._load_kb(kb_path)

    def _load_kb(self, path: str) -> Dict:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"KB {path} non trovato: {e}")
            return {"facilities": []}

    def route(self, location: str, urgenza: int, area: str) -> Dict:
        """
        Determina la struttura corretta con logica evoluta.
        
        Args:
            location: Comune utente
            urgenza: 1-5
            area: Area clinica (es.  "Psichiatria", "Generale")
        
        Returns:
            Dict con nome, tipo, note, distance_km della struttura
        """
        facilities = self.kb.get("facilities", [])
        loc = location.lower().strip()
        
        # ✅ 1. URGENZA CRITICA -> PRONTO SOCCORSO (SEMPRE)
        if urgenza >= 4:
            logger.info(f"🚨 Routing PS per urgenza {urgenza}")
            return {
                "nome": "Pronto Soccorso",
                "tipo": "PS",
                "note": "Recati immediatamente in ospedale o chiama il 118.",
                "distance_km": None
            }
        
        # ✅ 2. SALUTE MENTALE -> CENTRO SALUTE MENTALE
        if "Psichiatria" in area or "Psichiatrica" in area or "Mentale" in area:
            logger.info(f"🧠 Routing CSM per area {area}")
            return {
                "nome": "Centro di Salute Mentale",
                "tipo": "CSM",
                "note": "Contatta il servizio territoriale per una valutazione.",
                "distance_km": None
            }
        
        # ✅ 3. GINECOLOGIA/OSTETRICIA -> CONSULTORIO
        if "Ginecologia" in area or "Ostetricia" in area or "Gravidanza" in area:
            logger.info(f"👶 Routing Consultorio per area {area}")
            return {
                "nome": "Consultorio Familiare",
                "tipo":  "Consultorio",
                "note":  "Prenota una visita presso il consultorio di zona.",
                "distance_km":  None
            }
        
        # ✅ 4. DIPENDENZE -> SerD
        if "Dipendenze" in area or "Tossicodipendenza" in area or "Alcol" in area:
            logger. info(f"💊 Routing SerD per area {area}")
            return {
                "nome": "SerD (Servizio Dipendenze)",
                "tipo": "SerD",
                "note": "Accesso diretto o tramite MMG per supporto specialistico.",
                "distance_km": None
            }
        
        # ✅ 5. URGENZA MODERATA (3) -> CAU
        if urgenza == 3:
            logger.info(f"⚡ Routing CAU per urgenza {urgenza}")
            return {
                "nome": "CAU (Continuità Assistenziale Urgenze)",
                "tipo": "CAU",
                "note": "Centro di Assistenza Urgenza per valutazioni senza appuntamento.",
                "distance_km": None
            }
        
        # ✅ 6. FALLBACK -> MEDICO DI BASE
        logger.info(f"🩺 Routing MMG (fallback) per urgenza {urgenza}, area {area}")
        return {
            "nome": "Medico di Medicina Generale",
            "tipo":  "MMG",
            "note": "Contatta il tuo medico di base per una valutazione nei prossimi giorni.",
            "distance_km": None
        }


def detect_emergency_keywords(user_message: str) -> str:
    """
    Rileva keyword di emergenza nel messaggio utente.
    
    ✅ NUOVO: Supporto per emergency detection in tempo reale
    
    Args:
        user_message: Messaggio dell'utente
    
    Returns:
        "RED": Emergenza medica critica
        "ORANGE": Situazione urgente
        "BLACK": Emergenza psichiatrica
        "GREEN": Nessuna emergenza rilevata
    """
    if not user_message:
        return "GREEN"
    
    text_lower = user_message.lower().strip()
    
    # BLACK triggers (emergenza psichiatrica)
    black_keywords = [
        "suicidio", "uccidermi", "togliermi la vita", "farla finita",
        "ammazzarmi", "voglio morire", "non voglio più vivere",
        "autolesionismo", "tagliarmi", "farmi male"
    ]
    
    for keyword in black_keywords:
        if keyword in text_lower:
            logger.error(f"🚨 BLACK EMERGENCY: '{keyword}'")
            return "BLACK"
    
    # RED triggers (emergenza medica critica)
    red_keywords = [
        "dolore toracico", "dolore petto", "oppressione torace",
        "non riesco respirare", "soffoco", "difficoltà respiratoria grave",
        "perdita di coscienza", "svenuto", "svenimento",
        "convulsioni", "crisi convulsiva",
        "emorragia massiva", "sangue abbondante",
        "paralisi", "metà corpo bloccata"
    ]
    
    for keyword in red_keywords:
        if keyword in text_lower:
            logger.error(f"🚨 RED EMERGENCY: '{keyword}'")
            return "RED"
    
    # ORANGE triggers (urgente)
    orange_keywords = [
        "dolore addominale acuto", "dolore pancia molto forte",
        "trauma cranico", "battuto forte testa",
        "febbre alta", "febbre 39", "febbre 40",
        "vomito continuo", "vomito sangue",
        "dolore insopportabile", "dolore lancinante"
    ]
    
    for keyword in orange_keywords:
        if keyword in text_lower:
            logger.warning(f"⚠️ ORANGE EMERGENCY: '{keyword}'")
            return "ORANGE"
    
    return "GREEN"