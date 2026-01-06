import asyncio
from typing import Union, Iterator
import streamlit as st

def stream_ai_response(orchestrator, messages, path, phase) -> Iterator[Union[str, any]]:
    """
    Converte il generatore asincrono in uno sincrono per Streamlit.
    """
    async def _collect():
        items = []
        # Chiama il metodo del nuovo orchestratore nel Canvas
        async for chunk in orchestrator.call_ai_streaming(messages, path, phase):
            items.append(chunk)
        return items
    
    # Crea un nuovo loop di eventi per la richiesta corrente
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(_collect())
        for item in results:
            yield item
    finally:
        loop.close()