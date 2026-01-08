print("1. Inizio test...")
import sys
print("2. Python versione:", sys.version)

try:
    print("3. Caricamento Streamlit...")
    import streamlit as st
    print("4. Caricamento Groq...")
    import groq
    print("5. Caricamento Folium...")
    import folium
    print("6. Caricamento Plotly...")
    import plotly
    print("7. Caricamento JSON e Dati...")
    import json
    print("--- TUTTE LE LIBRERIE CARICATE CON SUCCESSO ---")
except Exception as e:
    print(f"ERRORE RILEVATO: {e}")

input("Premi INVIO per chiudere...")
# ============================================
# SESSION MANAGEMENT & NAVIGATION
# ============================================
def init_session():
    """Inizializza variabili di sessione con valori di default."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.current_step = TriageStep.LOCATION
        st.session_state.current_phase_idx = 0
        st.session_state.collected_data = {}
        st.session_state.step_completed = {step:  False for step in TriageStep}
        st.session_state.metadata_history = []
        st. session_state.pending_survey = None
        st.session_state.gdpr_consent = False
        st.session_state. specialization = "General Triage"
        st.session_state.backend = BackendClient()
        st.session_state.emergency_level = None
        st.session_state. show_altro = False
    
    logger.debug(f"Session initialized:  {st.session_state.session_id}")


def advance_step() -> bool:
    """
    Avanza allo step successivo del triage.
    
    Returns:
        True se avanzamento riuscito
        False se già all'ultimo step
    """
    current = st.session_state.current_step
    
    # Usa il VALUE dell'enum (1, 2, 3, .. .) invece dell'istanza
    current_value = current.value
    
    # Ottieni il valore massimo dell'enum
    max_value = max(step.value for step in TriageStep)
    
    # Se non siamo all'ultimo step, avanza
    if current_value < max_value:
        # Crea il prossimo step usando il value + 1
        next_step = TriageStep(current_value + 1)
        st.session_state.current_step = next_step
        logger.info(f"Advanced from {current. name} (value={current_value}) to {next_step.name} (value={next_step.value})")
        return True
    
    logger.info(f"Already at last step: {current. name}")
    return False


def get_step_display_name(step:  TriageStep) -> str:
    """Restituisce nome human-readable per lo step corrente."""
    names = {
        TriageStep.LOCATION: "📍 Localizzazione",
        TriageStep.CHIEF_COMPLAINT:  "🤒 Sintomo Principale",
        TriageStep.PAIN_SCALE: "📊 Intensità Dolore",
        TriageStep.RED_FLAGS:  "🚨 Segnali di Allarme",
        TriageStep.ANAMNESIS: "📝 Storia Clinica",
        TriageStep.DISPOSITION: "🏥 Raccomandazione Finale"
    }
    return names.get(step, "Triage")


def render_progress_bar():
    """Mostra progress bar basata sullo step corrente."""
    current_value = st.session_state.current_step.value
    total_steps = len(TriageStep)
    progress = current_value / total_steps
    st.progress(progress)
    logger.debug(f"Progress bar: {current_value}/{total_steps} ({progress:.1%})")


def render_urgency_badge():
    """Mostra badge con livello di urgenza corrente."""
    if not st.session_state.metadata_history:
        return
    
    latest_metadata = st.session_state.metadata_history[-1]
    urgency = latest_metadata.get("urgenza", 3)
    
    colors = {
        1: "#10b981",  # Verde
        2: "#3b82f6",  # Blu
        3: "#f59e0b",  # Giallo
        4: "#f97316",  # Arancione
        5: "#dc2626"   # Rosso
    }
    
    color = colors.get(urgency, "#6b7280")
    
    st.markdown(f"""
    <div style='background:  {color}; color: white; padding: 5px 15px; 
                border-radius: 20px; text-align: center; width: fit-content; 
                margin: 0 auto 10px auto; font-weight: bold;'>
        Urgenza:  {urgency}/5
    </div>
    """, unsafe_allow_html=True)


def render_disposition_summary():
    """Mostra riepilogo finale del triage."""
    st.success("### ✅ Triage Completato")
    
    if st.session_state. collected_data:
        st. markdown("#### 📋 Dati Raccolti:")
        st.json(st.session_state.collected_data)
    
    if st.session_state.metadata_history:
        latest_metadata = st.session_state.metadata_history[-1]
        urgency = latest_metadata.get("urgenza", 3)
        area = latest_metadata.get("area", "Generale")
        
        st.markdown(f"""
        #### 🎯 Valutazione Finale
        - **Area Clinica**: {area}
        - **Livello Urgenza**: {urgency}/5
        """)
        
        if urgency >= 4:
            st.error("🚨 **Raccomandazione**:  Recarsi in Pronto Soccorso")
        elif urgency == 3:
            st.warning("⚠️ **Raccomandazione**: Consulto medico in giornata")
        else:
            st.info("ℹ️ **Raccomandazione**: Monitorare sintomi e consulto medico se peggioramento")


def update_backend_metadata(metadata: Dict):
    """Aggiorna metadata e sincronizza con backend."""
    st.session_state.metadata_history.append(metadata)
    
    # Aggiorna specializzazione se presente
    if "area" in metadata:
        st. session_state.specialization = metadata["area"]
    
    # Sincronizza con backend
    st.session_state.backend. sync({
        "current_step": st.session_state.current_step. name,
        "metadata": metadata,
        "collected_data":  st.session_state.collected_data
    })
    
    logger.info(f"Metadata updated: urgenza={metadata.get('urgenza')}, area={metadata.get('area')}")


# ============================================
# MAIN APPLICATION FLOW
# ============================================
def main():
    """Entry point principale dell'applicazione."""
    init_session()
    orchestrator = ModelOrchestrator()
    pharmacy_db = PharmacyService()
    
    # GDPR Consent Screen
    if not st.session_state.gdpr_consent:
        st.markdown("### 📋 Consenso Informato")
        st.markdown("""
        <div class='disclaimer-box'>
            <p><strong>AVVISO IMPORTANTE:</strong></p>
            <ul>
                <li>Questo sistema effettua <strong>solo triage</strong>, non diagnosi mediche</li>
                <li>In caso di emergenza chiamare immediatamente il <strong>118</strong></li>
                <li>I dati raccolti sono trattati secondo GDPR (anonimizzati)</li>
                <li>Per informazioni:  privacy@health-navigator.it</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("✅ Accetto e Inizio Triage", use_container_width=True, type="primary"):
            st.session_state.gdpr_consent = True
            st.rerun()
        
        return
    
    # Render UI Components
    render_header(PHASES[st.session_state. current_phase_idx])
    
    # Check if AI service is available
    if not orchestrator.is_available():
        st.error("⚠️ **Servizio AI temporaneamente non disponibile**")
        st.info("Per emergenze chiamare il **118**")
        return
    
    # Render message history
    for message in st.session_state. messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Check if at disposition step
    if st.session_state.current_step == TriageStep.DISPOSITION:
        render_disposition_summary()
        
        if st.button("🔄 Nuova Sessione", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        
        st.stop()
    
    # Chat input (only if no pending survey)
    if not st.session_state.pending_survey:
        if raw_input := st.chat_input("Descrivi i tuoi sintomi... "):
            user_input = DataSecurity.sanitize_input(raw_input)
            
            # Check for emergencies
            emergency_level = assess_emergency_level(user_input, {})
            if emergency_level:
                st. session_state.emergency_level = emergency_level
                render_emergency_overlay(emergency_level)
            
            # Add user message
            st.session_state.messages.append({"role":  "user", "content": user_input})
            
            # Get AI response
            with st.chat_message("assistant"):
                placeholder = st.empty()
                response_generator = orchestrator.call_ai(
                    st.session_state.messages, 
                    PHASES[st.session_state. current_phase_idx]["id"]
                )
                
                full_response = ""
                final_data = None
                
                for chunk in response_generator:
                    if isinstance(chunk, str):
                        full_response += chunk
                        placeholder.markdown(full_response + "▌")
                    elif isinstance(chunk, dict):
                        final_data = chunk
                        break
                
                if final_data:
                    placeholder.markdown(final_data. get("testo", ""))
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": final_data["testo"]
                    })
                    st.session_state.pending_survey = final_data
                    
                    # Update metadata and check for PS wait times
                    metadata = final_data.get("metadata", {})
                    update_backend_metadata(metadata)
                    
                    urgency = metadata.get("urgenza", 3)
                    comune = st.session_state.collected_data.get("LOCATION")
                    
                    if comune and should_show_ps_wait_times(comune, urgency):
                        render_ps_wait_times_alert(
                            comune, 
                            urgency, 
                            has_cau_alternative=(3. 0 <= urgency < 4.5)
                        )
                    
                    st.rerun()
    
    # Render survey options
    if st.session_state.pending_survey and st.session_state.pending_survey.get("opzioni"):
        st.markdown("---")
        opts = st.session_state.pending_survey["opzioni"]
        
        # ✅ DEBUG: Log opzioni ricevute
        logger.info(f"🔍 Survey options:  {opts} (type={type(opts)}, len={len(opts)})")
        
        cols = st.columns(len(opts))
        
        for i, opt in enumerate(opts):
            # ✅ DEBUG: Log ogni singola opzione
            logger.info(f"🔍 Option[{i}]: '{opt}' (type={type(opt)}, len={len(opt) if isinstance(opt, str) else 'N/A'})")
            
            if cols[i].button(opt, key=f"btn_{i}"):
                if opt == "Altro":
                    st.session_state.show_altro = True
                    st.rerun()
                else:
                    # Save response
                    st.session_state.messages.append({"role": "user", "content": opt})
                    
                    current_step = st.session_state.current_step
                    step_name = current_step.name
                    
                    # Validate and save based on step
                    if current_step == TriageStep. LOCATION:
                        is_valid, normalized = InputValidator.validate_location(opt)
                        if is_valid: 
                            st.session_state.collected_data[step_name] = normalized
                    elif current_step == TriageStep.CHIEF_COMPLAINT: 
                        st.session_state.collected_data[step_name] = opt
                    elif current_step == TriageStep.PAIN_SCALE:
                        is_valid, pain_value = InputValidator.validate_pain_scale(opt)
                        if is_valid:
                            st.session_state.collected_data[step_name] = pain_value
                        else:
                            st.session_state.collected_data[step_name] = opt
                    elif current_step == TriageStep.RED_FLAGS:
                        is_valid, flags = InputValidator.validate_red_flags(opt)
                        st.session_state.collected_data[step_name] = flags
                    elif current_step == TriageStep.ANAMNESIS:
                        is_valid, age = InputValidator.validate_age(opt)
                        if is_valid:
                            st. session_state.collected_data['age'] = age
                        st.session_state.collected_data[step_name] = opt
                    elif current_step == TriageStep.DISPOSITION: 
                        st.session_state.collected_data[step_name] = opt
                    
                    st.session_state.pending_survey = None
                    
                    # Advance to next step
                    if advance_step():
                        logger.info(f"✅ Advanced to:  {st.session_state.current_step.name}")
                    
                    st.rerun()
        
        # Handle "Altro" custom input
        if st.session_state.get("show_altro"):
            st.markdown("<div class='fade-in'>", unsafe_allow_html=True)
            col1, col2 = st. columns([4, 1])
            
            custom_input = col1.text_input("Specifica altro:", placeholder="Descrivi qui...")
            
            if col2.button("❌", key="cancel_altro"):
                st.session_state.show_altro = False
                st.rerun()
            
            if custom_input and st.button("✅ Invia", use_container_width=True):
                # Validate and save custom input
                st.session_state.messages.append({"role": "user", "content": custom_input})
                
                current_step = st. session_state.current_step
                step_name = current_step.name
                
                # Validate based on step
                if current_step == TriageStep.LOCATION:
                    is_valid, normalized = InputValidator.validate_location(custom_input)
                    if is_valid:
                        st.session_state.collected_data[step_name] = normalized
                    else:
                        st.warning("⚠️ Comune non riconosciuto.  Inserisci un comune dell'Emilia-Romagna.")
                        st.rerun()
                elif current_step == TriageStep.PAIN_SCALE:
                    is_valid, pain_value = InputValidator.validate_pain_scale(custom_input)
                    if is_valid:
                        st.session_state.collected_data[step_name] = pain_value
                    else:
                        st.session_state.collected_data[step_name] = custom_input
                elif current_step == TriageStep. ANAMNESIS:
                    is_valid, age = InputValidator.validate_age(custom_input)
                    if is_valid: 
                        st.session_state. collected_data['age'] = age
                    st.session_state.collected_data[step_name] = custom_input
                else:
                    st.session_state.collected_data[step_name] = custom_input
                
                st.session_state. pending_survey = None
                st.session_state.show_altro = False
                
                # Advance to next step
                if advance_step():
                    logger.info(f"✅ Advanced to: {st. session_state.current_step. name}")
                
                st. rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__": 
    main()