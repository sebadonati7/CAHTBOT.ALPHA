import asyncio
import logging
from typing import Union, Iterator
import streamlit as st

logger = logging.getLogger(__name__)

def stream_ai_response(orchestrator, messages, path, phase, collected_data=None, is_first_message=False) -> Iterator[Union[str, any]]:
    """
    Converte il generatore asincrono in uno sincrono per Streamlit.
    Wrapper con gestione errori robusta e logging dettagliato.  
    
    Args: 
        orchestrator:  Istanza di ModelOrchestrator
        messages: Lista di messaggi della chat
        path: Percorso triage (A/B/C)
        phase: Fase corrente (es. "ANAMNESIS", "DISPOSITION")
        collected_data: Dati già raccolti durante la conversazione
        is_first_message: True se primo contatto per intent detection
    
    Yields:
        str:  Token di testo per streaming incrementale
        TriageResponse:  Oggetto finale con metadati
    """
    # Validazione input
    if collected_data is None:
        collected_data = {}
    if not isinstance(collected_data, dict):
        logger.error(f"collected_data deve essere un dizionario, ricevuto {type(collected_data)}")
        collected_data = {}
    
    async def _collect():
        items = []
        try:
            logger.info(f"Bridge: Avvio collezione asincrona | phase={phase}, path={path}, messages={len(messages)}, collected_data_keys={list(collected_data.keys())}, is_first={is_first_message}")
            
            # Chiama il metodo streaming dell'orchestratore con collected_data
            async for chunk in orchestrator.call_ai_streaming(messages, path, phase, collected_data, is_first_message):
                items.append(chunk)
                
                # Log del tipo di chunk ricevuto
                chunk_type = type(chunk).__name__
                if isinstance(chunk, str):
                    logger.debug(f"Chunk testo ricevuto: {len(chunk)} caratteri")
                else:
                    logger. debug(f"Chunk oggetto ricevuto: {chunk_type}")
            
            logger.info(f"Bridge: Collezione completata | {len(items)} chunk totali")
        
        except asyncio.TimeoutError:
            logger.error(f"Bridge: Timeout durante la generazione (phase={phase})")
            items.append("La richiesta ha impiegato troppo tempo.  Riprova con una domanda più breve.")
        
        except Exception as e:
            logger.error(f"Bridge: Errore durante collezione asincrona:  {e}", exc_info=True)
            items.append(f"Si è verificato un errore durante la comunicazione con l'AI. Riprova.")
        
        return items
    
    # Crea un nuovo loop di eventi per la richiesta corrente
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        results = loop.run_until_complete(_collect())
        logger.info(f"Bridge: Inizio yield di {len(results)} items")
        
        for item in results:
            yield item
    
    except Exception as e:
        logger.error(f"Bridge: Errore critico nel loop di eventi: {e}", exc_info=True)
        yield f"Errore critico:  {str(e)}"
    
    finally:
        loop. close()
        logger.debug("Bridge: Loop di eventi chiuso")