import streamlit as st
import json
import os
import re
import io
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import plotly.graph_objects as go
import plotly.express as px

# --- GESTIONE DIPENDENZE OPZIONALI ---
NUMPY_AVAILABLE = True
try:
    import numpy as np
except ImportError:
    NUMPY_AVAILABLE = False

SCIPY_AVAILABLE = True
try:
    from scipy import stats
except ImportError:
    SCIPY_AVAILABLE = False

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

# --- MAPPATURE CLINICHE ---
ASL_MACRO_AREAS = {
    "Area Medica": ["febbre", "stomaco", "respiro", "tosse", "testa", "pancia", "nausea", "vertigini", "diarrea", "pressione", "stanchezza", "debolezza"],
    "Area Chirurgica": ["emorragia", "ferita profonda", "appendice", "addome acuto", "ascesso", "sangue", "ernia", "calcoli"],
    "Area Traumatologica": ["caduta", "botta", "frattura", "distorsione", "incidente", "trauma", "gonfiore", "contusione"],
    "Area Materno-Infantile": ["bambino", "neonato", "gravidanza", "pediatrico", "contrazioni", "allattamento", "parto"],
    "Area Cardiologica": ["petto", "cuore", "palpitazioni", "tachicardia", "aritmia", "infarto"],
    "Area Neurologica": ["svenimento", "convulsioni", "paralisi", "formicolio", "confusione", "ictus"]
}

FUNNEL_STEP_KEYWORDS = {
    1: ["cosa ti porta", "sintomo", "problema", "disturbo"],
    2: ["citta", "comune", "dove", "localita", "zona"],
    3: ["intensita", "scala", "1-10", "quanto forte", "dolore"],
    4: ["natura", "come descrivi", "tipo di", "caratteristica"],
    5: ["altri sintomi", "associati", "correlati", "accompagna"],
    6: ["eta", "anni", "farmaci", "patologie", "allergie"],
    7: ["consiglio", "raccomando", "indirizzo", "struttura", "cau", "pronto soccorso", "guardia medica"]
}

COMUNI_ER_VALIDI = {
    "bologna", "modena", "reggio emilia", "parma", "ferrara", "ravenna",
    "rimini", "forli", "cesena", "piacenza", "imola", "carpi", "cento",
    "faenza", "casalecchio", "san lazzaro", "medicina", "budrio", "lugo",
    "cervia", "riccione", "cattolica", "bellaria", "comacchio", "argenta"
}

# --- NLP FUNCTIONS ---
def identify_macro_area(user_input, bot_response):
    """Identifica l'area clinica basata su keyword"""
    combined = (str(user_input) + " " + str(bot_response)).lower()
    for area, keywords in ASL_MACRO_AREAS.items():
        if any(kw in combined for kw in keywords):
            return area
    return "Area Non Definita"

def extract_age(text):
    """Estrae l'età dal testo"""
    match = re.search(r'(?:ho|età|anni|di)\s*(\d{1,2})\s*(?:anni)?', str(text).lower())
    if match:
        age = int(match.group(1))
        return age if 0 <= age <= 120 else None
    return None

def detect_hostility_level(text):
    """Rileva il livello di ostilità (0=nessuna, 1=leggero, 2=medio, 3=grave)"""
    text_lower = str(text).lower()
    
    # Livello grave
    grave_keywords = ["vaffanculo", "bastardo", "cazzo", "merda", "stronzo"]
    if any(kw in text_lower for kw in grave_keywords):
        return 3
    
    # Livello medio
    medio_keywords = ["stupido", "inutile", "idiota", "rotto", "incompetente"]
    if any(kw in text_lower for kw in medio_keywords):
        return 2
    
    # Livello leggero
    leggero_keywords = ["fastidio", "basta", "insistere", "ripetere"]
    if any(kw in text_lower for kw in leggero_keywords):
        return 1
    
    return 0

def detect_funnel_step(text):
    """Identifica lo step del funnel di triage"""
    text_lower = str(text).lower()
    for step, keywords in FUNNEL_STEP_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return step
    return None

def validate_comune_er(city_name):
    """Valida se il comune appartiene all'Emilia-Romagna"""
    if not city_name:
        return False
    return city_name.lower() in COMUNI_ER_VALIDI


# --- DISTRICT MAPPING FUNCTIONS (NEW FOR V2) ---
def load_district_mapping():
    """
    Load health district mappings from distretti_sanitari_er.json
    
    Returns:
        dict: District mapping data
    """
    districts_file = "distretti_sanitari_er.json"
    if not os.path.exists(districts_file):
        st.warning(f"⚠️ File {districts_file} non trovato. Mapping distretti non disponibile.")
        return {"health_districts": [], "comune_to_district_mapping": {}}
    
    try:
        with open(districts_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"❌ Errore caricamento mapping distretti: {e}")
        return {"health_districts": [], "comune_to_district_mapping": {}}


def get_district_from_comune(comune: str, district_data: dict) -> str:
    """
    Get district code from comune name
    
    Args:
        comune: Municipality name
        district_data: District mapping data
        
    Returns:
        District code (e.g., "BOL-CIT") or "UNKNOWN"
    """
    if not comune or not district_data:
        return "UNKNOWN"
    
    comune_lower = comune.lower().strip()
    mapping = district_data.get("comune_to_district_mapping", {})
    
    return mapping.get(comune_lower, "UNKNOWN")


def get_district_name(district_code: str, district_data: dict) -> str:
    """
    Get full district name from code
    
    Args:
        district_code: District code (e.g., "BOL-CIT")
        district_data: District mapping data
        
    Returns:
        Full district name or code if not found
    """
    if not district_code or not district_data:
        return district_code
    
    for ausl_data in district_data.get("health_districts", []):
        for district in ausl_data.get("districts", []):
            if district.get("code") == district_code:
                return f"{district['name']} ({ausl_data['ausl']})"
    
    return district_code


def filter_records_by_district(records: list, district_code: str, district_data: dict) -> list:
    """
    Filter triage records by district code
    
    Args:
        records: List of triage records
        district_code: District code to filter by
        district_data: District mapping data
        
    Returns:
        Filtered list of records
    """
    if district_code == "ALL":
        return records
    
    filtered = []
    for record in records:
        # Check if record has district field
        rec_district = record.get("distretto")
        
        # If not, try to infer from comune
        if not rec_district:
            comune = record.get("comune") or record.get("location")
            if comune:
                rec_district = get_district_from_comune(comune, district_data)
        
        if rec_district == district_code:
            filtered.append(record)
    
    return filtered


def parse_timestamp_robust(timestamp_str):
    """Parsing robusto di timestamp con timezone"""
    if not timestamp_str:
        return None
    
    try:
        # Prova con formato ISO standard
        if '+' in timestamp_str or timestamp_str.endswith('Z'):
            # Rimuovi 'Z' finale se presente
            ts = timestamp_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(ts)
        else:
            dt = datetime.fromisoformat(timestamp_str)
        return dt
    except:
        try:
            # Fallback: prova altri formati comuni
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']:
                try:
                    return datetime.strptime(timestamp_str, fmt)
                except:
                    continue
        except:
            pass
    return None

# --- CLASSE TRIAGEDATASTORE ---
class TriageDataStore:
    """Gestione dati triage con supporto NumPy opzionale"""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.records = []
        self.sessions = {}
        self._load_data()
        self._enrich_data()
        
        # Crea array NumPy se disponibile
        if NUMPY_AVAILABLE and self.records:
            self._create_numpy_arrays()
    
    def _load_data(self):
        """Carica dati da file JSONL"""
        if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
            return
        
        with open(self.filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    self.records.append(record)
                except json.JSONDecodeError:
                    continue
    
    def _enrich_data(self):
        """Arricchisce i dati con analisi NLP"""
        for record in self.records:
            # Timestamp parsing
            dt = parse_timestamp_robust(record.get('timestamp'))
            if dt:
                record['datetime'] = dt
                record['date'] = dt.date()
                record['hour'] = dt.hour
                record['week'] = dt.isocalendar()[1]
                record['year'] = dt.year
                record['day_of_week'] = dt.weekday()
            
            # NLP
            user_input = record.get('user_input', '')
            bot_response = record.get('bot_response', '')
            combined_text = user_input + " " + bot_response
            
            record['macro_area'] = identify_macro_area(user_input, bot_response)
            record['age'] = extract_age(combined_text)
            record['hostility_level'] = detect_hostility_level(user_input)
            record['funnel_step'] = detect_funnel_step(bot_response)
            
            # Distretto
            city = record.get('city_detected', 'N.D.')
            record['distretto'] = city if validate_comune_er(city) else "Non Specificato"
            
            # Organizza per sessione
            session_id = record.get('session_id')
            if session_id:
                if session_id not in self.sessions:
                    self.sessions[session_id] = []
                self.sessions[session_id].append(record)
    
    def _create_numpy_arrays(self):
        """Crea array NumPy per calcoli veloci"""
        try:
            self.np_ages = np.array([r.get('age') for r in self.records if r.get('age') is not None])
            self.np_hostility = np.array([r.get('hostility_level', 0) for r in self.records])
            self.np_hours = np.array([r.get('hour') for r in self.records if r.get('hour') is not None])
        except:
            pass
    
    def filter(self, year=None, week=None, distretto=None):
        """Filtra i record"""
        filtered = self.records
        
        if year is not None:
            filtered = [r for r in filtered if r.get('year') == year]
        
        if week is not None:
            filtered = [r for r in filtered if r.get('week') == week]
        
        if distretto and distretto != "Tutti":
            filtered = [r for r in filtered if r.get('distretto') == distretto]
        
        # Crea una nuova istanza con i dati filtrati
        filtered_store = TriageDataStore.__new__(TriageDataStore)
        filtered_store.filepath = self.filepath
        filtered_store.records = filtered
        
        # Ricostruisci sessioni
        filtered_store.sessions = {}
        for record in filtered:
            session_id = record.get('session_id')
            if session_id:
                if session_id not in filtered_store.sessions:
                    filtered_store.sessions[session_id] = []
                filtered_store.sessions[session_id].append(record)
        
        return filtered_store
    
    def count_by_field(self, field):
        """Conta occorrenze per campo"""
        counter = Counter()
        for record in self.records:
            value = record.get(field)
            if value is not None:
                counter[value] += 1
        return dict(counter)
    
    def group_by_fields(self, *fields):
        """Raggruppa per multipli campi"""
        groups = defaultdict(list)
        for record in self.records:
            key = tuple(record.get(f) for f in fields)
            groups[key].append(record)
        return dict(groups)
    
    def get_unique_values(self, field):
        """Ottiene valori unici per un campo"""
        values = set()
        for record in self.records:
            value = record.get(field)
            if value is not None:
                values.add(value)
        return sorted(list(values))

# --- CALCOLO KPI ---
def calculate_kpis(datastore):
    """Calcola tutti i 10 KPI strategici"""
    kpis = {}
    
    # 1. Sessioni Uniche
    kpis['sessioni_uniche'] = len(datastore.sessions)
    
    # 2. Tasso Deviazione PS
    total = len(datastore.records)
    if total > 0:
        deviazioni = sum(1 for r in datastore.records 
                        if r.get('triage_outcome') in ['CAU', 'Guardia Medica', 'Medico di Base'])
        kpis['tasso_deviazione_ps'] = (deviazioni / total) * 100
    else:
        kpis['tasso_deviazione_ps'] = 0.0
    
    # 3. Completamento Funnel
    if datastore.sessions:
        completed = sum(1 for sess_records in datastore.sessions.values()
                       if any(r.get('funnel_step') == 7 for r in sess_records))
        kpis['completamento_funnel'] = (completed / len(datastore.sessions)) * 100
    else:
        kpis['completamento_funnel'] = 0.0
    
    # 4. Churn Tecnico (sessioni con < 3 interazioni)
    if datastore.sessions:
        churned = sum(1 for sess_records in datastore.sessions.values() if len(sess_records) < 3)
        kpis['churn_tecnico'] = (churned / len(datastore.sessions)) * 100
    else:
        kpis['churn_tecnico'] = 0.0
    
    # 5. Profondità Media (interazioni per sessione)
    if datastore.sessions:
        kpis['profondita_media'] = sum(len(sess) for sess in datastore.sessions.values()) / len(datastore.sessions)
    else:
        kpis['profondita_media'] = 0.0
    
    # 6. Interazioni Totali
    kpis['interazioni_totali'] = total
    
    # 7. Età Media
    ages = [r.get('age') for r in datastore.records if r.get('age') is not None]
    if NUMPY_AVAILABLE and hasattr(datastore, 'np_ages') and len(datastore.np_ages) > 0:
        kpis['eta_media'] = float(np.mean(datastore.np_ages))
    elif ages:
        kpis['eta_media'] = sum(ages) / len(ages)
    else:
        kpis['eta_media'] = 0.0
    
    # 8. Sentiment Negativo (% con ostilità > 0)
    if total > 0:
        hostile_count = sum(1 for r in datastore.records if r.get('hostility_level', 0) > 0)
        kpis['sentiment_negativo'] = (hostile_count / total) * 100
    else:
        kpis['sentiment_negativo'] = 0.0
    
    # 9. Intensità Ostilità (media livelli)
    hostility_levels = [r.get('hostility_level', 0) for r in datastore.records]
    if NUMPY_AVAILABLE and hasattr(datastore, 'np_hostility'):
        kpis['intensita_ostilita'] = float(np.mean(datastore.np_hostility))
    elif hostility_levels:
        kpis['intensita_ostilita'] = sum(hostility_levels) / len(hostility_levels)
    else:
        kpis['intensita_ostilita'] = 0.0
    
    # 10. Durata Media Sessione
    durations = []
    for sess_records in datastore.sessions.values():
        if len(sess_records) >= 2:
            timestamps = [r.get('datetime') for r in sess_records if r.get('datetime')]
            if len(timestamps) >= 2:
                timestamps.sort()
                duration = (timestamps[-1] - timestamps[0]).total_seconds() / 60  # minuti
                durations.append(duration)
    
    if durations:
        kpis['durata_media_sessione'] = sum(durations) / len(durations)
    else:
        kpis['durata_media_sessione'] = 0.0
    
    return kpis

# --- CALCOLO EPI (Estimated Pressure Index) ---
def calculate_epi(datastore):
    """Calcola l'indice di pressione stimata per strutture sanitarie"""
    epi_results = {}
    
    # Conta per tipo di struttura
    outcome_counts = datastore.count_by_field('triage_outcome')
    
    cau_count = outcome_counts.get('CAU', 0)
    ps_count = outcome_counts.get('Pronto Soccorso', 0)
    gm_count = outcome_counts.get('Guardia Medica', 0)
    
    total = len(datastore.records)
    
    # Calcola EPI normalizzato (per 100 interazioni)
    if total > 0:
        epi_cau = (cau_count / total) * 100
        epi_ps = (ps_count / total) * 100
        epi_gm = (gm_count / total) * 100
    else:
        epi_cau = epi_ps = epi_gm = 0.0
    
    # Helper function for z-score calculation
    def calculate_z_scores(values):
        """Calculate z-scores for a list of values"""
        if not any(v > 0 for v in values):
            return [0.0] * len(values)
        
        try:
            mean_val = sum(values) / len(values)
            variance = sum((x - mean_val) ** 2 for x in values) / len(values)
            std_val = variance ** 0.5
            
            if std_val > 0:
                return [(v - mean_val) / std_val for v in values]
            else:
                return [0.0] * len(values)
        except (ZeroDivisionError, ValueError, ArithmeticError):
            return [0.0] * len(values)
    
    # Calcola z-score
    values = [epi_cau, epi_ps, epi_gm]
    z_scores = calculate_z_scores(values)
    z_cau, z_ps, z_gm = z_scores
    
    # Determina status
    def get_status(z_score):
        if z_score > 1.5:
            return "Critico"
        elif z_score > 0.5:
            return "Elevato"
        elif z_score > -0.5:
            return "Moderato"
        else:
            return "Normale"
    
    epi_results['CAU'] = {
        'count': cau_count,
        'epi': epi_cau,
        'z_score': z_cau,
        'status': get_status(z_cau)
    }
    
    epi_results['Pronto Soccorso'] = {
        'count': ps_count,
        'epi': epi_ps,
        'z_score': z_ps,
        'status': get_status(z_ps)
    }
    
    epi_results['Guardia Medica'] = {
        'count': gm_count,
        'epi': epi_gm,
        'z_score': z_gm,
        'status': get_status(z_gm)
    }
    
    return epi_results

# --- GRAFICI ---
def create_afflusso_orario_chart(datastore):
    """Grafico a barre stacked: Afflusso Orario per Area Clinica"""
    # Raggruppa per ora e macro_area
    hour_area_counts = defaultdict(lambda: defaultdict(int))
    
    for record in datastore.records:
        hour = record.get('hour')
        area = record.get('macro_area')
        if hour is not None and area:
            hour_area_counts[hour][area] += 1
    
    # Prepara dati per Plotly
    areas = set()
    for counts in hour_area_counts.values():
        areas.update(counts.keys())
    areas = sorted(areas)
    
    hours = sorted(hour_area_counts.keys())
    
    fig = go.Figure()
    
    for area in areas:
        counts = [hour_area_counts[h].get(area, 0) for h in hours]
        fig.add_trace(go.Bar(
            name=area,
            x=hours,
            y=counts
        ))
    
    fig.update_layout(
        title="Afflusso Orario per Area Clinica",
        xaxis_title="Ora del giorno",
        yaxis_title="Numero accessi",
        barmode='stack',
        xaxis=dict(tickmode='linear', dtick=1)
    )
    
    return fig

def create_esiti_pie_chart(datastore):
    """Grafico a torta: Distribuzione Esiti Triage"""
    outcome_counts = datastore.count_by_field('triage_outcome')
    
    if not outcome_counts:
        # Grafico vuoto
        fig = go.Figure(data=[go.Pie(labels=[], values=[])])
        fig.update_layout(title="Distribuzione Esiti Triage - Nessun dato")
        return fig
    
    labels = list(outcome_counts.keys())
    values = list(outcome_counts.values())
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.4
    )])
    
    fig.update_layout(title="Distribuzione Esiti Triage")
    
    return fig

def create_sankey_funnel(datastore):
    """Diagramma Sankey: Flusso Utenti nel Funnel di Triage"""
    # Traccia il flusso attraverso gli step del funnel
    step_transitions = defaultdict(int)
    
    for sess_records in datastore.sessions.values():
        steps = [r.get('funnel_step') for r in sess_records if r.get('funnel_step')]
        steps = sorted(set(steps))  # Rimuovi duplicati e ordina
        
        for i in range(len(steps) - 1):
            transition = (f"Step {steps[i]}", f"Step {steps[i+1]}")
            step_transitions[transition] += 1
    
    if not step_transitions:
        # Grafico vuoto
        fig = go.Figure(data=[go.Sankey()])
        fig.update_layout(title="Flusso Utenti nel Funnel - Nessun dato")
        return fig
    
    # Crea nodi unici
    nodes = set()
    for source, target in step_transitions.keys():
        nodes.add(source)
        nodes.add(target)
    nodes = sorted(nodes)
    node_indices = {node: i for i, node in enumerate(nodes)}
    
    # Prepara dati Sankey
    sources = [node_indices[source] for source, _ in step_transitions.keys()]
    targets = [node_indices[target] for _, target in step_transitions.keys()]
    values = list(step_transitions.values())
    
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=nodes
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values
        )
    )])
    
    fig.update_layout(title="Flusso Utenti nel Funnel di Triage")
    
    return fig

def create_focus_territoriale_chart(datastore):
    """Grafico a barre: Focus Territoriale (distribuzione per distretto)"""
    district_counts = datastore.count_by_field('distretto')
    
    if not district_counts:
        # Grafico vuoto
        fig = go.Figure()
        fig.update_layout(title="Focus Territoriale - Nessun dato")
        return fig
    
    districts = list(district_counts.keys())
    counts = list(district_counts.values())
    
    fig = go.Figure(data=[go.Bar(
        x=districts,
        y=counts,
        marker_color='indianred'
    )])
    
    fig.update_layout(
        title="Focus Territoriale - Distribuzione per Distretto",
        xaxis_title="Distretto",
        yaxis_title="Numero accessi"
    )
    
    return fig

# --- EXPORT EXCEL ---
def export_to_excel(datastore, kpis):
    """Crea file Excel con dati completi e KPI summary"""
    if not XLSX_AVAILABLE:
        return None
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    
    # Foglio 1: Dati Completi
    worksheet1 = workbook.add_worksheet('Dati_Completi')
    
    # Header
    headers = ['session_id', 'timestamp', 'user_input', 'bot_response', 'city_detected',
               'triage_outcome', 'macro_area', 'age', 'hostility_level', 'funnel_step',
               'distretto', 'year', 'week', 'hour']
    
    for col, header in enumerate(headers):
        worksheet1.write(0, col, header)
    
    # Dati
    for row, record in enumerate(datastore.records, start=1):
        for col, header in enumerate(headers):
            value = record.get(header, '')
            # Converti datetime in stringa
            if header == 'timestamp' and isinstance(value, datetime):
                value = value.isoformat()
            worksheet1.write(row, col, value)
    
    # Foglio 2: KPI Summary
    worksheet2 = workbook.add_worksheet('KPI_Summary')
    
    # Formato
    bold = workbook.add_format({'bold': True})
    
    worksheet2.write('A1', 'KPI', bold)
    worksheet2.write('B1', 'Valore', bold)
    
    kpi_names = {
        'sessioni_uniche': 'Sessioni Uniche',
        'tasso_deviazione_ps': 'Tasso Deviazione PS (%)',
        'completamento_funnel': 'Completamento Funnel (%)',
        'churn_tecnico': 'Churn Tecnico (%)',
        'profondita_media': 'Profondità Media',
        'interazioni_totali': 'Interazioni Totali',
        'eta_media': 'Età Media',
        'sentiment_negativo': 'Sentiment Negativo (%)',
        'intensita_ostilita': 'Intensità Ostilità',
        'durata_media_sessione': 'Durata Media Sessione (min)'
    }
    
    row = 1
    for key, name in kpi_names.items():
        worksheet2.write(row, 0, name)
        worksheet2.write(row, 1, round(kpis.get(key, 0), 2))
        row += 1
    
    workbook.close()
    output.seek(0)
    
    return output.getvalue()

# --- MAIN APPLICATION ---
def main():
    # Load district mapping data (NEW FOR V2)
    district_data = load_district_mapping()
    
    # Load data
    datastore = TriageDataStore(LOG_FILE)
    
    if not datastore.records:
        st.warning("⚠️ Nessun dato disponibile. Inizia una chat per popolare i log.")
        return
    
    # --- SIDEBAR FILTERS ---
    st.sidebar.header("📂 Filtri e Reportistica")
    
    years = datastore.get_unique_values('year')
    if years:
        sel_year = st.sidebar.selectbox("Anno", sorted(years, reverse=True))
    else:
        sel_year = None
    
    weeks = []
    if sel_year:
        filtered_by_year = datastore.filter(year=sel_year)
        weeks = filtered_by_year.get_unique_values('week')
    
    if weeks:
        sel_week = st.sidebar.selectbox("Settimana", sorted(weeks))
    else:
        sel_week = None
    
    # Enhanced district selection with full names (NEW FOR V2)
    districts = datastore.get_unique_values('distretto')
    if districts:
        district_options = ["Tutti"]
        for dist_code in sorted(districts):
            if dist_code and dist_code != "UNKNOWN":
                dist_name = get_district_name(dist_code, district_data)
                district_options.append(f"{dist_code} - {dist_name}")
        
        sel_dist_display = st.sidebar.selectbox("Distretto Sanitario", district_options)
        # Extract code from display
        if sel_dist_display == "Tutti":
            sel_dist = "Tutti"
        else:
            sel_dist = sel_dist_display.split(" - ")[0]
    else:
        sel_dist = "Tutti"
    
    # Apply filters
    filtered_datastore = datastore.filter(year=sel_year, week=sel_week, distretto=sel_dist)
    
    # --- EXCEL EXPORT ---
    if XLSX_AVAILABLE and filtered_datastore.records:
        st.sidebar.divider()
        st.sidebar.subheader("📥 Centro Download")
        
        kpis = calculate_kpis(filtered_datastore)
        excel_data = export_to_excel(filtered_datastore, kpis)
        
        if excel_data:
            filename = f"Report_Sanitario_W{sel_week}_{sel_year}.xlsx"
            st.sidebar.download_button(
                label="📊 Scarica Report Excel",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    # --- MAIN DASHBOARD ---
    st.title("🧬 AI Health Navigator | Advanced Analytics")
    
    # Warning se NumPy non disponibile
    if not NUMPY_AVAILABLE:
        st.warning("""
        ⚠️ **Modalità Ridotta**: NumPy non disponibile. Alcune ottimizzazioni sono disattivate.
        """)
    
    if not filtered_datastore.records:
        st.info("Nessun dato disponibile per i filtri selezionati.")
        return
    
    # --- KPI DASHBOARD ---
    st.subheader("📊 KPI Strategici")
    kpis = calculate_kpis(filtered_datastore)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Sessioni Uniche", f"{kpis['sessioni_uniche']}")
        st.metric("Tasso Deviazione PS", f"{kpis['tasso_deviazione_ps']:.1f}%")
    
    with col2:
        st.metric("Completamento Funnel", f"{kpis['completamento_funnel']:.1f}%")
        st.metric("Churn Tecnico", f"{kpis['churn_tecnico']:.1f}%")
    
    with col3:
        st.metric("Profondità Media", f"{kpis['profondita_media']:.1f}")
        st.metric("Interazioni Totali", f"{kpis['interazioni_totali']}")
    
    with col4:
        st.metric("Età Media", f"{kpis['eta_media']:.1f}" if kpis['eta_media'] > 0 else "N/D")
        st.metric("Sentiment Negativo", f"{kpis['sentiment_negativo']:.1f}%")
    
    with col5:
        st.metric("Intensità Ostilità", f"{kpis['intensita_ostilita']:.2f}")
        st.metric("Durata Media Sessione", f"{kpis['durata_media_sessione']:.1f} min")
    
    st.divider()
    
    # --- EPI DASHBOARD ---
    st.subheader("📈 Indice di Pressione Stimata (EPI)")
    epi_results = calculate_epi(filtered_datastore)
    
    epi_col1, epi_col2, epi_col3 = st.columns(3)
    
    with epi_col1:
        cau_data = epi_results['CAU']
        st.metric("EPI CAU", f"{cau_data['epi']:.1f}", 
                 help=f"Z-score: {cau_data['z_score']:.2f}")
        st.caption(f"Status: **{cau_data['status']}** ({cau_data['count']} accessi)")
    
    with epi_col2:
        ps_data = epi_results['Pronto Soccorso']
        st.metric("EPI Pronto Soccorso", f"{ps_data['epi']:.1f}",
                 help=f"Z-score: {ps_data['z_score']:.2f}")
        st.caption(f"Status: **{ps_data['status']}** ({ps_data['count']} accessi)")
    
    with epi_col3:
        gm_data = epi_results['Guardia Medica']
        st.metric("EPI Guardia Medica", f"{gm_data['epi']:.1f}",
                 help=f"Z-score: {gm_data['z_score']:.2f}")
        st.caption(f"Status: **{gm_data['status']}** ({gm_data['count']} accessi)")
    
    st.divider()
    
    # --- GRAFICI ---
    st.subheader("📊 Analisi Strategica della Domanda")
    
    col_l, col_r = st.columns([6, 4])
    
    with col_l:
        fig_afflusso = create_afflusso_orario_chart(filtered_datastore)
        st.plotly_chart(fig_afflusso, use_container_width=True)
    
    with col_r:
        fig_esiti = create_esiti_pie_chart(filtered_datastore)
        st.plotly_chart(fig_esiti, use_container_width=True)
    
    st.divider()
    
    # --- SANKEY E FOCUS TERRITORIALE ---
    col_sankey, col_territorio = st.columns([6, 4])
    
    with col_sankey:
        fig_sankey = create_sankey_funnel(filtered_datastore)
        st.plotly_chart(fig_sankey, use_container_width=True)
    
    with col_territorio:
        fig_territorio = create_focus_territoriale_chart(filtered_datastore)
        st.plotly_chart(fig_territorio, use_container_width=True)
    
    st.divider()
    
    # --- TABELLA DATI ---
    st.subheader("📝 Anteprima Dati Arricchiti")
    
    # Prepara dati per visualizzazione
    display_data = []
    for record in filtered_datastore.records[-20:]:  # Ultimi 20 record
        display_data.append({
            'Timestamp': record.get('timestamp', ''),
            'Macro Area': record.get('macro_area', ''),
            'Età': record.get('age', 'N/D'),
            'Esito': record.get('triage_outcome', ''),
            'Distretto': record.get('distretto', ''),
            'Ostilità': record.get('hostility_level', 0),
            'Step Funnel': record.get('funnel_step', 'N/D')
        })
    
    st.dataframe(display_data, use_container_width=True)

if __name__ == "__main__":
    main()