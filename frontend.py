import streamlit as st
import google.generativeai as genai
import os
import json
import datetime
import uuid
import pytz  # Libreria per gestire correttamente il fuso orario

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(
    page_title="AI Health Navigator ER",
    page_icon="🏥",
    layout="centered"
)

# --- CSS PERSONALIZZATO (Look & Feel Professionale) ---
st.markdown("""
    <style>
    .chat-message {
        padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex
    }
    .chat-message.user {
        background-color: #e6f3ff;
        border-left: 5px solid #2196F3;
    }
    .chat-message.bot {
        background-color: #f0f2f6;
        border-left: 5px solid #4CAF50;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        font-weight: bold;
    }
    /* Nasconde elementi default di Streamlit per pulizia */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. SETUP E GESTIONE API ---
api_key = st.secrets.get("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))

if not api_key:
    st.error("⚠️ Chiave API mancante. Configura GOOGLE_API_KEY nei Secrets di Streamlit o nelle variabili d'ambiente.")
    st.stop()

genai.configure(api_key=api_key)

# --- 2. GESTIONE STATO DELLA SESSIONE ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- 3. CARICAMENTO KNOWLEDGE BASE (KB) ---
@st.cache_resource
def load_knowledge_base():
    """
    Carica il file master_kb.json se presente.
    """
    kb_path = "master_kb.json"
    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.warning(f"Errore nel caricamento della KB: {e}")
            return {}
    return {}

kb_data = load_knowledge_base()

# --- 4. COSTRUZIONE SYSTEM PROMPT (CORE LOGIC) ---
def get_system_instruction(kb_context):
    """
    Costruisce il prompt di sistema integrando Linee Guida Triage e Struttura Rigida.
    """
    
    # Calcolo data e ora attuale preciso (Rome Timezone)
    try:
        rome_tz = pytz.timezone('Europe/Rome')
        now_ita = datetime.datetime.now(rome_tz)
    except:
        # Fallback se pytz non è disponibile (ma su Streamlit Cloud lo è di solito)
        now_utc = datetime.datetime.utcnow()
        now_ita = now_utc + datetime.timedelta(hours=1) # Approssimazione

    current_time_str = now_ita.strftime("%A %d/%m/%Y, ore %H:%M")

    # Serializzazione Facilities KB
    facilities_str = ""
    if kb_context and "facilities" in kb_context:
        simplified_facilities = []
        for f in kb_context['facilities']:
            simplified_facilities.append({
                "nome": f.get("nome"),
                "citta": f.get("comune"),
                "tipo": f.get("tipologia"),
                "indirizzo": f.get("indirizzo"),
                "contatti": f.get("contatti"),
                "orari": f.get("orari_standard")
            })
        facilities_str = json.dumps(simplified_facilities, ensure_ascii=False, indent=2)

    prompt = f"""
SEI: AI Health Navigator per la Regione Emilia-Romagna.
RUOLO: Operatore di Triage Sanitario virtuale e Sportello Informazioni.
OBIETTIVO: Identificare la destinazione di cura appropriata (CAU, Guardia Medica, PS) usando protocolli clinici standard.

NON SEI UN MEDICO, MA DEVI RAGIONARE COME UN TRIAGISTA ESPERTO.

--- CONTESTO TEMPORALE REALE ---
DATA E ORA ATTUALE: {current_time_str}
(Usa questo dato ESATTO per verificare orari di apertura CAU/Guardia Medica).

--- FONTI CLINICHE DI RIFERIMENTO (TRIAGE) ---
Per formulare le domande, NON improvvisare. Basati sulla logica dei manuali standard italiani:
1. "Manuale Triage Regione Lazio" (Modello a 5 codici).
2. "Sistema Dispatch 118 Toscana" (Intervista telefonica strutturata).
3. "Linee Guida Triage Piemonte".
USA QUESTE FONTI per determinare QUALI sintomi associati indagare e QUALI discriminanti (red flags) cercare per ogni sintomo specifico.

--- KNOWLEDGE BASE LOGISTICA (DOVE ANDARE) ---
{facilities_str}

--- MODALITÀ OPERATIVA ---
1. Rileva l'intento: "INFO" (chiede orari/luoghi) vs "TRIAGE" (ha un sintomo).
2. Se "INFO": Rispondi diretto con dati precisi (Indirizzo, Orari, Telefono).
3. Se "TRIAGE": Attiva il PROTOCOLLO RIGIDO SOTTOSTANTE.

--- PROTOCOLLO TRIAGE RIGIDO (STRUTTURA OBBLIGATORIA) ---
Usa questa scaletta per evitare prolissità, ma riempi il contenuto delle domande usando le Linee Guida cliniche sopra citate.

REGOLA FONDAMENTALE: 1 DOMANDA ALLA VOLTA. PING-PONG.

Step 1: SINTOMO PRINCIPALE
- "Cosa ti porta qui oggi?"

Step 2: LOCALIZZAZIONE (Città/Comune)
- FONDAMENTALE chiederlo subito per contestualizzare la logistica.

Step 3: INTENSITÀ (Scala 1-10)
- "Da 1 a 10, quanto è forte il dolore/fastidio?"

Step 4: NATURA DEL SINTOMO (Scelta Multipla A/B/C basata su LINEE GUIDA)
- Consulta mentalmente i manuali di Triage: per questo sintomo, quali sono le qualità discriminanti?
- Proponi 3 opzioni descrittive.
- Esempio (Dolore Toracico): "Come descrivi il dolore? A) Oppressivo/pesante (come un elefante sul petto), B) Trafittivo (come una pugnalata), C) Bruciore o altro."

Step 5: SINTOMI ASSOCIATI (Scelta Multipla A/B/C basata su LINEE GUIDA)
- Partecipativo: "Indaghiamo ora eventuali sintomi correlati per capire meglio il quadro..."
- Consulta i manuali: Quali sono i sintomi associati critici per il problema dello Step 1?
- Esempio (Dolore Addominale): "Oltre al dolore, hai altri sintomi? A) Nausea/Vomito, B) Febbre o brividi, C) Chiusura dell'alvo o diarrea. (Oppure altro?)"
- NON chiedere sintomi a caso. Chiedi quelli pertinenti al protocollo medico.

Step 6: ANAMNESI TARDIVA
- "Quanti anni hai? Assumi farmaci pertinenti al problema (es. anticoagulanti, immunosoppressori)?"

Step 7: VERDETTO E AZIONE
- Analizza le risposte secondo i criteri di gravità dei Manuali Triage.
- Se SINTOMI LIEVI/DIFFERIBILI (Codici Bianchi/Verdi): Indirizza a CAU o Guardia Medica (se aperta).
- Se URGENZA (Codici Gialli/Rossi): Indirizza a PS o 118.
- OUTPUT OBBLIGATORIO: Nome Struttura + Indirizzo + ORARI + TELEFONO.
- Se non trovi la città esatta nella KB, dai il numero verde regionale 800 033 033.

--- PROTOCOLLO 'UTENTE OSTILE' ---
Se l'utente è aggressivo o impaziente ("Basta domande!", insulti):
- STOP empatia.
- Passa a modalità "CHIRURGICA": Solo fatti.
- Vai subito allo Step successivo essenziale o chiudi il triage dando la struttura più vicina (richiedi città se manca).

--- FORMATO RISPOSTA ---
- Lingua: Italiano.
- Tono: Professionale ma empatico (spiega il "perché" delle domande cliniche).
"""
    return prompt

# --- 5. INTERFACCIA UTENTE ---

# Header
col1, col2 = st.columns([1, 5])
with col1:
    st.write("🏥") 
with col2:
    st.title("Triage Emilia-Romagna")
    st.caption("AI Health Navigator - Progetto Sperimentale")

# Visualizzazione Chat History
for message in st.session_state.messages:
    role_class = "user" if message["role"] == "user" else "bot"
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 6. LOGICA DI RISPOSTA AI ---
prompt_user = st.chat_input("Descrivi il tuo sintomo o fai una domanda...")

if prompt_user:
    # 1. Visualizza messaggio utente
    st.session_state.messages.append({"role": "user", "content": prompt_user})
    with st.chat_message("user"):
        st.markdown(prompt_user)

    # 2. Prepara la chiamata a Gemini
    try:
        # Prepara la storia per il contesto
        gemini_history = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
            for m in st.session_state.messages[:-1]
        ]

        system_instruction = get_system_instruction(kb_data)
        
        # Configurazione Modello
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash-preview-09-2025', 
            system_instruction=system_instruction,
            generation_config={"temperature": 0.2, "max_output_tokens": 600} 
        )
        
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(prompt_user)
        
        bot_reply = response.text
        
        # 3. Visualizza risposta Bot
        with st.chat_message("assistant"):
            st.markdown(bot_reply)
            
        st.session_state.messages.append({"role": "assistant", "content": bot_reply})
        
        # 4. SALVA IL LOG nel file triage_logs.jsonl
        try:
            rome_tz = pytz.timezone('Europe/Rome')
            timestamp_now = datetime.datetime.now(rome_tz).isoformat()
        except:
            timestamp_now = datetime.datetime.utcnow().isoformat()
        
        # Estrai città dalla conversazione (semplice: cerca nelle risposte precedenti)
        city_detected = "N.D."
        for msg in st.session_state.messages:
            if "città" in msg["content"].lower() or "comune" in msg["content"].lower():
                # Semplice extraction - in produzione usi NER più sofisticato
                words = msg["content"].lower().split()
                for i, word in enumerate(words):
                    if ("città" in word or "comune" in word) and i+1 < len(words):
                        city_detected = words[i+1].strip(".,!?")
                        break
        
        # Estrai outcome dal verdetto del bot (cerca keyword)
        triage_outcome = "Consiglio"
        if "pronto soccorso" in bot_reply.lower() or "ps " in bot_reply.lower():
            triage_outcome = "Pronto Soccorso"
        elif "cau" in bot_reply.lower():
            triage_outcome = "CAU"
        elif "guardia medica" in bot_reply.lower():
            triage_outcome = "Guardia Medica"
        elif "118" in bot_reply.lower():
            triage_outcome = "118"
        
        log_entry = {
            "session_id": st.session_state.session_id,
            "timestamp": timestamp_now,
            "user_input": prompt_user,
            "bot_response": bot_reply,
            "city_detected": city_detected,
            "triage_outcome": triage_outcome
        }
        
        # Scrivi in append mode
        with open("triage_logs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    except Exception as e:
        st.error(f"⚠️ Errore di connessione o API: {str(e)}")
        # Fallback sicuro
        fallback_msg = "Sistemi momentaneamente sovraccarichi. In caso di emergenza medica grave, chiama subito il 118."
        st.session_state.messages.append({"role": "assistant", "content": fallback_msg})

# --- SIDEBAR INFO ---
with st.sidebar:
    st.header("ℹ️ Info Progetto")
    st.info(
        """
        **AI Health Navigator**
        
        Orientamento sanitario basato su protocolli di Triage nazionali (Lazio, Toscana, Piemonte) e risorse territoriali Emilia-Romagna.
        
        ⚠️ **NON SOSTITUISCE IL 118 IN CASO DI EMERGENZA.**
        """
    )
    if st.button("🔄 Resetta Triage"):
        st.session_state.messages = []
        st.rerun()