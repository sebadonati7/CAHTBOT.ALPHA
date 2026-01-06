import asyncio
import logging
from typing import Union, Iterator
import streamlit as st

logger = logging.getLogger(__name__)

def stream_ai_response(orchestrator, messages, path, phase) -> Iterator[Union[str, any]]:
    """
    Converte il generatore asincrono in uno sincrono per Streamlit.
    Wrapper with improved error handling.
    """
    async def _collect():
        items = []
        try:
            logger.info(f"Bridge: Starting async collection for phase={phase}")
            # Chiama il metodo del nuovo orchestratore nel Canvas
            async for chunk in orchestrator.call_ai_streaming(messages, path, phase):
                items.append(chunk)
            logger.info(f"Bridge: Collected {len(items)} chunks successfully")
        except Exception as e:
            logger.error(f"Bridge: Error during async collection: {e}", exc_info=True)
            # Return error message as fallback
            items.append(f"Si è verificato un errore durante la comunicazione con l'AI. Riprova.")
        return items
    
    # Crea un nuovo loop di eventi per la richiesta corrente
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(_collect())
        logger.info(f"Bridge: Yielding {len(results)} items")
        for item in results:
            yield item
    except Exception as e:
        logger.error(f"Bridge: Critical error in event loop: {e}", exc_info=True)
        yield f"Errore critico: {str(e)}"
    finally:
        loop.close()