from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from enum import Enum

class QuestionType(str, Enum):
    SURVEY = "survey"
    SCALE = "scale"
    TEXT = "text"

class SBARReport(BaseModel):
    """Modello per l'handover strutturato (Fase 5 del protocollo)"""
    situation:  str = Field(..., description="Sintomo principale e intensità")
    background: Dict[str, Any] = Field(default_factory=dict, description="Età, sesso, farmaci, etc.")
    assessment: List[str] = Field(default_factory=list, description="Risposte chiave fornite")
    recommendation: str = Field(..., description="Struttura suggerita e motivo clinico")

class TriageMetadata(BaseModel):
    urgenza: int = Field(..., description="Livello di urgenza da 1 a 5")
    area: str = Field(..., description="Area clinica di riferimento")
    red_flags: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    fallback_used: bool = False

    @field_validator("urgenza")
    @classmethod
    def clamp_urgenza(cls, v: int) -> int:
        return max(1, min(5, v))

class TriageResponse(BaseModel):
    """Schema di validazione definitivo per le risposte dell'AI"""
    testo: str = Field(..., max_length=1000)
    tipo_domanda: QuestionType
    opzioni: Optional[List[str]] = None
    metadata: TriageMetadata
    sbar:  Optional[SBARReport] = None
    
    # ✅ NUOVO: Fase protocollo corrente
    fase_corrente: Optional[str] = Field(
        default=None, 
        description="Fase del protocollo triage (LOCATION, PAIN_SCALE, RED_FLAGS, etc.)"
    )
    
    # ✅ NUOVO: Dati estratti dall'ultima risposta utente
    dati_estratti: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dati multipli estratti automaticamente dalla risposta utente"
    )

    @field_validator("opzioni")
    @classmethod
    def validate_options(cls, v: Any, info: Any) -> Any:
        if info.data. get("tipo_domanda") == QuestionType.SURVEY: 
            if not v or len(v) < 2:
                return ["Sì", "No", "Non so"]
        return v