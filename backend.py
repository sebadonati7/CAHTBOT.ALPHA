import streamlit as st
import json
import os
import re
import io
import pandas as pd
from datetime import datetime
from collections import Counter
import plotly.graph_objects as go
import plotly.express as px

# --- GESTIONE DIPENDENZE CRITICHE ---
NUMPY_AVAILABLE = True
try:
    import numpy as np
except ImportError as e:
    NUMPY_AVAILABLE = False
    NUMPY_ERROR = str(e)

XLSX_AVAILABLE = True
try:
    import xlsxwriter
except ImportError:
    XLSX_AVAILABLE = False

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(
    page_title="Health Navigator | Strategic Analytics",
    page_icon="🧬",
    layout="wide"
)

LOG_FILE = "triage_logs.jsonl"

# --- MAPPATURA CLINICA E LOGICA NLP ---
ASL_MACRO_AREAS = {
    "Area Medica": ["febbre", "stomaco", "respiro", "tosse", "testa", "pancia", "nausea", "vertigini", "diarrea", "pressione"],
    "Area Chirurgica": ["emorragia", "ferita profonda", "appendice", "addome acuto", "ascesso", "sangue"],
    "Area Traumatologica": ["caduta", "botta", "frattura", "distorsione", "incidente", "trauma", "gonfiore"],
    "Area Materno-Infantile": ["bambino", "neonato", "gravidanza", "pediatrico", "contrazioni", "allattamento"]
}

def identify_macro_area(u, b):
    combined = (str(u) + " " + str(b)).lower()
    for area, keywords in ASL_MACRO_AREAS.items():
        if any(kw in combined for kw in keywords): return area
    return "Area Non Definita"

def extract_age(text):
    match = re.search(r'(?:ho|età|anni|di)\s*(\d{1,2})\s*(?:anni)?', str(text).lower())
    return int(match.group(1)) if match else None

def detect_hostility(text):
    hostile_keywords = ["stupido", "inutile", "vaffanculo", "bastardo", "non capisci"]
    return 1 if any(kw in str(text).lower() for kw in hostile_keywords) else 0

# --- CARICAMENTO DATI CON CACHING ---
@st.cache_data(ttl=60)
def load_and_enrich_data(file_path):
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return pd.DataFrame()

    enriched_data = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                # Arricchimento dati
                entry["macro_area"] = identify_macro_area(entry.get("user_input", ""), entry.get("bot_response", ""))
                entry["age"] = extract_age(str(entry.get("user_input", "")) + " " + str(entry.get("bot_response", "")))
                entry["is_hostile"] = detect_hostility(entry.get("user_input", ""))
                
                dt = datetime.fromisoformat(entry["timestamp"])
                entry["date"] = dt.date()
                entry["hour"] = dt.hour
                entry["week"] = dt.isocalendar()[1]
                entry["year"] = dt.year
                entry["distretto"] = entry.get("city_detected") or "Non Specificato"
                
                enriched_data.append(entry)
            except: continue
    
    return pd.DataFrame(enriched_data)

# --- UI SIDEBAR ---
st.sidebar.header("📂 Filtri e Reportistica")
df_raw = load_and_enrich_data(LOG_FILE)

if not df_raw.empty:
    years = sorted(df_raw['year'].unique(), reverse=True)
    sel_year = st.sidebar.selectbox("Anno", years)
    
    weeks = sorted(df_raw[df_raw['year'] == sel_year]['week'].unique())
    sel_week = st.sidebar.selectbox("Settimana", weeks)
    
    districts = sorted(df_raw['distretto'].unique().tolist())
    sel_dist = st.sidebar.selectbox("Distretto", ["Tutti"] + districts)

    # Filtraggio
    mask = (df_raw['year'] == sel_year) & (df_raw['week'] == sel_week)
    if sel_dist != "Tutti":
        mask &= (df_raw['distretto'] == sel_dist)
    
    df = df_raw.loc[mask]
else:
    df = pd.DataFrame()

# --- EXPORT EXCEL ---
if not df.empty and XLSX_AVAILABLE:
    st.sidebar.divider()
    st.sidebar.subheader("📥 Centro Download")
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for district in df['distretto'].unique():
            dist_data = df[df['distretto'] == district]
            dist_data.to_excel(writer, sheet_name=str(district)[:31], index=False)
    
    st.sidebar.download_button(
        label="📊 Scarica Report Excel",
        data=output.getvalue(),
        file_name=f"Report_Sanitario_W{sel_week}_{sel_year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --- MAIN DASHBOARD ---
st.title("🧬 AI Health Navigator | Advanced Analytics")

# Avviso critico Python 3.14
if not NUMPY_AVAILABLE:
    st.error(f"""
    **⚠️ Errore DLL (Ambiente Python Sperimentale):** Il sistema sta funzionando in **Modalità Sicura** (Numpy non caricato). 
    I grafici avanzati sono limitati. Si consiglia Python 3.12.
    """)

if df.empty:
    st.warning("Nessun dato disponibile. Inizia una chat per popolare i log.")
else:
    # --- KPI PROFESSIONALI ---
    total_triage = len(df)
    diversion_count = len(df[df['triage_outcome'].isin(['CAU', 'Guardia Medica', 'Medico di Base'])])
    diversion_rate = (diversion_count / total_triage) * 100 if total_triage > 0 else 0
    avg_age = df['age'].mean() if not df['age'].isna().all() else 0
    hostility = (df['is_hostile'].sum() / total_triage) * 100

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Accessi Totali", total_triage)
    k2.metric("Tasso Deviazione PS", f"{diversion_rate:.1f}%", help="Utenti filtrati lontano dai PS")
    k3.metric("Età Media", f"{avg_age:.1f}" if avg_age > 0 else "N/D")
    k4.metric("Sentiment Negativo", f"{hostility:.1f}%")

    st.divider()

    # --- ANALISI DOMANDA ---
    st.subheader("📊 Analisi Strategica della Domanda")
    
    col_l, col_r = st.columns([6, 4])
    
    with col_l:
        # Distribuzione oraria per Area
        pivot_time = df.groupby(['hour', 'macro_area']).size().reset_index(name='counts')
        fig_time = px.bar(pivot_time, x='hour', y='counts', color='macro_area', 
                         title="Afflusso Orario per Area Clinica",
                         color_discrete_sequence=px.colors.qualitative.Safe)
        fig_time.update_layout(xaxis=dict(tickmode='linear', dtick=1), barmode='stack')
        st.plotly_chart(fig_time, width="stretch")

    with col_r:
        # Pie chart esiti
        outcome_counts = df['triage_outcome'].value_counts()
        fig_pie = go.Figure(data=[go.Pie(labels=outcome_counts.index, values=outcome_counts.values, hole=0.5)])
        fig_pie.update_layout(title="Distribuzione Esiti Triage")
        st.plotly_chart(fig_pie, width="stretch")

    st.divider()
    
    # --- DETTAGLIO TECNICO ---
    c_inf, c_tab = st.columns([4, 6])
    
    with c_inf:
        st.subheader("📍 Focus Territoriale")
        city_stats = df['distretto'].value_counts()
        st.bar_chart(city_stats)
        
    with c_tab:
        st.subheader("📝 Anteprima Dati Arricchiti")
        st.dataframe(
            df[['timestamp', 'macro_area', 'age', 'triage_outcome', 'is_hostile']].tail(15),
            column_config={
                "is_hostile": st.column_config.CheckboxColumn("Ostilità")
            },
            width="stretch"
        )

    if not NUMPY_AVAILABLE:
        st.info("💡 Nota: L'analisi statistica avanzata (Heatmap di correlazione) è stata disattivata per garantire la stabilità in Python 3.14.")