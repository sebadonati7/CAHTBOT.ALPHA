import json
import logging
from typing import Dict, Optional

class SmartRouter:
    """Integrazione deterministica con master_kb. json"""
    
    def __init__(self, kb_path: str = "master_kb.json"):
        self.kb = self._load_kb(kb_path)

    def _load_kb(self, path: str) -> Dict:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            logging.warning(f"KB {path} non trovato")
            return {"facilities": []}

    def route(self, location: str, urgenza: int, area: str) -> Dict:
        """Determina la struttura corretta"""
        facilities = self.kb. get("facilities", [])
        loc = location.lower().strip()
        
        # Urgenza critica -> PS
        if urgenza >= 4:
            return {"nome": "Pronto Soccorso", "tipo": "PS", "note": "Recati immediatamente in ospedale o chiama 118"}
        
        # Salute mentale -> CSM
        if "Psichiatrica" in area:
            return {"nome": "Centro Salute Mentale", "tipo": "CSM", "note": "Contatta il servizio territoriale"}
        
        # Moderata -> CAU
        if urgenza == 3:
            return {"nome": "CAU", "tipo": "CAU", "note": "Centro Assistenza Urgenza"}
        
        # Fallback -> MMG
        return {"nome": "Medico di Medicina Generale", "tipo":  "MMG", "note": "Contatta il tuo medico"}