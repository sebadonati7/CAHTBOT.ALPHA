# utils/symptom_normalizer.py - Fuzzy Symptom Matching and Normalization
"""
Normalizes user-reported symptoms to canonical medical terms.

Features:
- Multi-level matching: exact → fuzzy → context-aware
- Stop-words removal
- Fuzzy matching with configurable threshold
- Context-based disambiguation
- Unknown terms tracking for AI refinement

Example:
    >>> normalizer = SymptomNormalizer()
    >>> normalizer.normalize("mal di testa forte")
    'Cefalea'
    >>> normalizer.normalize("ho dolore alla pancia")
    'Dolore addominale'
"""

import re
import difflib
import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ============================================================================
# CANONICAL KNOWLEDGE BASE
# ============================================================================

# Canonical symptom names (target medical terms)
CANONICAL_KB: Dict[str, str] = {
    # Cefalea
    "mal di testa": "Cefalea",
    "mal testa": "Cefalea",
    "testa che fa male": "Cefalea",
    "dolore testa": "Cefalea",
    "dolore alla testa": "Cefalea",
    "emicrania": "Cefalea",
    "cefalea": "Cefalea",
    
    # Dolore addominale
    "mal di pancia": "Dolore addominale",
    "mal pancia": "Dolore addominale",
    "dolore pancia": "Dolore addominale",
    "dolore addome": "Dolore addominale",
    "dolore stomaco": "Dolore addominale",
    "mal di stomaco": "Dolore addominale",
    
    # Dolore toracico (RED FLAG)
    "dolore petto": "Dolore toracico",
    "dolore torace": "Dolore toracico",
    "dolore al petto": "Dolore toracico",
    "dolore cuore": "Dolore toracico",
    "oppressione petto": "Dolore toracico",
    "peso sul petto": "Dolore toracico",
    
    # Dispnea
    "difficoltà respirare": "Dispnea",
    "difficolta respiro": "Dispnea",
    "non riesco respirare": "Dispnea grave",
    "non riesco a respirare": "Dispnea grave",
    "soffoco": "Dispnea grave",
    "affanno": "Dispnea",
    "fiato corto": "Dispnea",
    
    # Febbre
    "febbre": "Febbre",
    "temperatura alta": "Febbre",
    "febbrile": "Febbre",
    "ho la febbre": "Febbre",
    
    # Tosse
    "tosse": "Tosse",
    "tossisco": "Tosse",
    "colpi tosse": "Tosse",
    
    # Trauma
    "caduta": "Trauma",
    "sono caduto": "Trauma",
    "sono caduta": "Trauma",
    "botta": "Trauma",
    "incidente": "Trauma",
    "trauma": "Trauma",
    
    # Vertigini
    "vertigini": "Vertigini",
    "capogiro": "Vertigini",
    "giramento testa": "Vertigini",
    "testa che gira": "Vertigini",
    
    # Nausea
    "nausea": "Nausea",
    "voglia vomitare": "Nausea",
    "sto male": "Nausea",
    
    # Vomito
    "vomito": "Vomito",
    "ho vomitato": "Vomito",
    "rimetto": "Vomito",
    
    # Diarrea
    "diarrea": "Diarrea",
    "scariche": "Diarrea",
    "feci liquide": "Diarrea",
    
    # Dolore articolare
    "dolore articolazioni": "Dolore articolare",
    "male alle ossa": "Dolore articolare",
    "dolore ginocchio": "Dolore articolare",
    "dolore schiena": "Lombalgia",
    
    # Mental health
    "ansia": "Ansia",
    "ansioso": "Ansia",
    "ansiosa": "Ansia",
    "attacco panico": "Attacco di panico",
    "panico": "Attacco di panico",
    "depressione": "Depressione",
    "depresso": "Depressione",
    "triste": "Umore depresso",
    "stress": "Stress",
}

# Stop words da rimuovere nel preprocessing
STOP_WORDS: Set[str] = {
    "ho", "hai", "ha", "un", "una", "il", "la", "lo", "di", "da", "in",
    "per", "con", "su", "a", "che", "mi", "ti", "si", "al", "alla",
    "del", "della", "delle", "dei", "degli", "molto", "tanto", "poco"
}


# ============================================================================
# SYMPTOM NORMALIZER CLASS
# ============================================================================

class SymptomNormalizer:
    """
    Normalizes symptom descriptions to canonical medical terms.
    
    Attributes:
        canonical_kb: Dictionary mapping symptom variants to canonical names
        fuzzy_threshold: Minimum similarity for fuzzy matching (0.0-1.0)
        unknown_terms: Set of terms that failed normalization
    """
    
    def __init__(
        self,
        canonical_kb: Optional[Dict[str, str]] = None,
        fuzzy_threshold: float = 0.85
    ):
        """
        Initialize symptom normalizer.
        
        Args:
            canonical_kb: Custom knowledge base (default: built-in)
            fuzzy_threshold: Fuzzy matching threshold (default: 0.85)
        """
        self.canonical_kb = canonical_kb or CANONICAL_KB
        self.fuzzy_threshold = fuzzy_threshold
        self.unknown_terms: Set[str] = set()
        
        logger.info(f"SymptomNormalizer initialized with {len(self.canonical_kb)} entries")
    
    def _preprocess(self, text: str) -> str:
        """
        Preprocess text for normalization.
        
        Steps:
        1. Lowercase
        2. Remove punctuation
        3. Remove stop words
        4. Collapse whitespace
        
        Args:
            text: Raw symptom text
        
        Returns:
            Cleaned text
        """
        if not text:
            return ""
        
        # Lowercase
        text = text.lower().strip()
        
        # Remove punctuation (keep only alphanumeric and spaces)
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Remove stop words
        words = text.split()
        words = [w for w in words if w not in STOP_WORDS]
        text = ' '.join(words)
        
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def normalize(
        self,
        symptom: str,
        context: Optional[str] = None
    ) -> str:
        """
        Normalize symptom to canonical medical term.
        
        Algorithm:
        1. Preprocessing (lowercase, remove stop words)
        2. Exact match in canonical_kb
        3. Fuzzy matching with similarity threshold
        4. Context-based disambiguation (if provided)
        5. Fallback to original (marked as Unknown)
        
        Args:
            symptom: User-reported symptom description
            context: Optional context for disambiguation (e.g., "Trauma", "Cardiology")
        
        Returns:
            Canonical symptom name or original text if no match
        
        Example:
            >>> normalizer.normalize("ho un forte mal di testa")
            'Cefalea'
            >>> normalizer.normalize("pancia che fa male", context="Gastroenterology")
            'Dolore addominale'
        """
        if not symptom or not isinstance(symptom, str):
            return ""
        
        original = symptom
        
        # Level 0: Preprocessing
        cleaned = self._preprocess(symptom)
        
        if not cleaned:
            return original
        
        # Level 1: Exact match
        if cleaned in self.canonical_kb:
            canonical = self.canonical_kb[cleaned]
            logger.debug(f"Exact match: '{original}' → '{canonical}'")
            return canonical
        
        # Level 2: Fuzzy matching
        canonical_keys = list(self.canonical_kb.keys())
        matches = difflib.get_close_matches(
            cleaned,
            canonical_keys,
            n=1,
            cutoff=self.fuzzy_threshold
        )
        
        if matches:
            matched_key = matches[0]
            canonical = self.canonical_kb[matched_key]
            
            # Compute similarity for logging
            similarity = difflib.SequenceMatcher(None, cleaned, matched_key).ratio()
            
            logger.debug(
                f"Fuzzy match: '{original}' → '{canonical}' "
                f"(similarity: {similarity:.2f}, key: '{matched_key}')"
            )
            
            # Context boost: if context provided, prefer context-related terms
            if context:
                # Find all matches above threshold
                all_matches = difflib.get_close_matches(
                    cleaned,
                    canonical_keys,
                    n=3,
                    cutoff=self.fuzzy_threshold * 0.9  # Slightly lower threshold
                )
                
                # Check if any match is context-relevant
                for match_key in all_matches:
                    match_canonical = self.canonical_kb[match_key]
                    if self._is_context_relevant(match_canonical, context):
                        logger.debug(
                            f"Context boost: '{original}' → '{match_canonical}' "
                            f"(context: {context})"
                        )
                        return match_canonical
            
            return canonical
        
        # Level 3: Fallback - no match found
        logger.warning(f"No match found for: '{original}' (cleaned: '{cleaned}')")
        self.unknown_terms.add(original)
        
        return original
    
    def _is_context_relevant(self, canonical: str, context: str) -> bool:
        """
        Check if canonical term is relevant to given context.
        
        Args:
            canonical: Canonical symptom name
            context: Clinical context
        
        Returns:
            True if term is contextually relevant
        """
        context_lower = context.lower()
        canonical_lower = canonical.lower()
        
        # Context mappings
        CONTEXT_KEYWORDS = {
            "trauma": ["trauma", "caduta", "botta", "frattura"],
            "cardiology": ["toracico", "cuore", "petto", "dispnea"],
            "gastroenterology": ["addominale", "stomaco", "nausea", "vomito", "diarrea"],
            "neurology": ["cefalea", "vertigini", "testa"],
            "mental_health": ["ansia", "panico", "depressione", "stress"]
        }
        
        for ctx_key, keywords in CONTEXT_KEYWORDS.items():
            if ctx_key in context_lower:
                return any(kw in canonical_lower for kw in keywords)
        
        return False
    
    def get_unknown_terms(self) -> List[str]:
        """
        Get list of terms that failed normalization.
        
        Useful for:
        - Identifying gaps in knowledge base
        - AI-assisted refinement
        - Manual review
        
        Returns:
            Sorted list of unknown terms
        """
        return sorted(list(self.unknown_terms))
    
    def add_to_kb(self, symptom_variant: str, canonical: str) -> None:
        """
        Add new symptom variant to knowledge base.
        
        Args:
            symptom_variant: User-reported variant (will be preprocessed)
            canonical: Canonical medical term
        """
        cleaned = self._preprocess(symptom_variant)
        if cleaned:
            self.canonical_kb[cleaned] = canonical
            logger.info(f"Added to KB: '{symptom_variant}' → '{canonical}'")
    
    def normalize_batch(
        self,
        symptoms: List[str],
        context: Optional[str] = None
    ) -> List[str]:
        """
        Normalize a batch of symptoms.
        
        Args:
            symptoms: List of symptom descriptions
            context: Optional context for all symptoms
        
        Returns:
            List of normalized symptom names
        """
        return [self.normalize(s, context) for s in symptoms]


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.DEBUG)
    
    normalizer = SymptomNormalizer()
    
    test_cases = [
        "ho un forte mal di testa",
        "mi fa male la pancia da stamattina",
        "dolore al petto che non passa",
        "non riesco a respirare bene",
        "sono caduto e mi fa male il ginocchio",
        "vertigini e nausea",
        "attacco di ansia",
        "sintomo sconosciuto XYZ"
    ]
    
    print("Testing symptom normalization:\n")
    for symptom in test_cases:
        normalized = normalizer.normalize(symptom)
        print(f"  '{symptom}' → '{normalized}'")
    
    print(f"\nUnknown terms: {normalizer.get_unknown_terms()}")
