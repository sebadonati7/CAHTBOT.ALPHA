import asyncio
import logging
from typing import Union, Iterator
import streamlit as st

logger = logging.getLogger(__name__)

def stream_ai_response(orchestrator, messages, path, phase) -> Iterator[Union[str, any]]:
    """
    Converte il generatore asincrono in uno sincrono per Streamlit.
    Wrapper con gestione errori robusta e logging dettagliato.
    
    Args:
        orchestrator:  Istanza di ModelOrchestrator
        messages: Lista di messaggi della chat
        path: Percorso triage (A/B/C)
        phase: Fase corrente (es. "ANAMNESIS", "DISPOSITION")
    
    Yields:
        str: Token di testo per streaming incrementale
        TriageResponse: Oggetto finale con metadati
    """
    async def _collect():
        items = []
        try:
            logger.info(f"🔄 Bridge: Avvio collezione asincrona | phase={phase}, path={path}, messages={len(messages)}")
            
            # Chiama il metodo streaming dell'orchestratore
            async for chunk in orchestrator.call_ai_streaming(messages, path, phase):
                items.append(chunk)
                
                # ✅ NUOVO:  Log del tipo di chunk ricevuto
                chunk_type = type(chunk).__name__
                if isinstance(chunk, str):
                    logger.debug(f"📦 Chunk testo ricevuto: {len(chunk)} caratteri")
                else:
                    logger.debug(f"📦 Chunk oggetto ricevuto: {chunk_type}")
            
            logger.info(f"✅ Bridge: Collezione completata | {len(items)} chunk totali")
        
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Bridge: Timeout durante la generazione (phase={phase})")
            items. append("La richiesta ha impiegato troppo tempo.  Riprova con una domanda più breve.")
        
        except Exception as e:
            logger.error(f"❌ Bridge: Errore durante collezione asincrona:  {e}", exc_info=True)
            items.append(f"Si è verificato un errore durante la comunicazione con l'AI. Riprova.")
        
        return items
    
    # Crea un nuovo loop di eventi per la richiesta corrente
    loop = asyncio. new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        results = loop.run_until_complete(_collect())
        logger.info(f"🚀 Bridge: Inizio yield di {len(results)} items")
        
        for item in results:
            yield item
    
    except Exception as e:
        logger. error(f"❌ Bridge: Errore critico nel loop di eventi: {e}", exc_info=True)
        yield f"Errore critico:  {str(e)}"
    
    finally:
        loop. close()
        logger.debug("🔒 Bridge: Loop di eventi chiuso")