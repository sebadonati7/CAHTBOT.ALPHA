import json
import os
import glob

def merge_json_files():
    # --- CONFIGURAZIONE PERCORSI ---
    # Ottiene la cartella dove si trova questo script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Cartella di INPUT (dove metti i file dei distretti: bologna.json, ferrara.json, ecc.)
    # Assicurati che questa cartella esista!
    input_folder = os.path.join(base_dir, "KNOWLEDGE_BASE", "LOGISTIC")
    
    # Cartella e File di OUTPUT
    output_folder = os.path.join(base_dir, "KNOWLEDGE_BASE")
    output_file = os.path.join(output_folder, "master_kb.json")
    
    print(f"🚀 Avvio unificazione dati...")
    print(f"📂 Cartella Input: {input_folder}")

    # Creazione cartelle se non esistono
    if not os.path.exists(input_folder):
        try:
            os.makedirs(input_folder)
            print(f"⚠️ Creata cartella {input_folder}. Inserisci qui i file JSON dei distretti e riesegui.")
            return
        except OSError as e:
            print(f"❌ Errore creazione cartella: {e}")
            return

    # Dizionario per unione (chiave univoca -> dati)
    merged_facilities_map = {}
    files_processed = 0
    
    # Cerca tutti i file .json nella cartella LOGISTIC
    json_files = glob.glob(os.path.join(input_folder, "*.json"))
    
    for file_path in json_files:
        filename = os.path.basename(file_path)
        
        # Salta il master se per errore è finito nella cartella di input
        if filename == "master_kb.json":
            continue
            
        print(f"📄 Elaborazione: {filename}...")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Gestione formati (Lista o Dizionario wrapper)
                items_to_add = []
                if isinstance(data, list):
                    items_to_add = data
                elif isinstance(data, dict) and "facilities" in data:
                    items_to_add = data["facilities"]
                else:
                    print(f"⚠️  Formato ignoto in {filename}, salto il file.")
                    continue

                # Inserimento dati nella mappa
                for item in items_to_add:
                    # Tenta di creare un ID univoco se manca
                    unique_id = item.get("id")
                    if not unique_id:
                        # Fallback: crea ID da nome e comune
                        clean_name = item.get('nome', 'unknown').replace(" ", "_").upper()
                        clean_city = item.get('comune', 'unknown').replace(" ", "_").upper()
                        unique_id = f"AUTO_{clean_city}_{clean_name}"
                        item["id"] = unique_id
                    
                    merged_facilities_map[unique_id] = item
                    
                files_processed += 1

        except json.JSONDecodeError:
            print(f"❌ ERRORE JSON: Il file {filename} non è valido o è corrotto.")
        except Exception as e:
            print(f"❌ Errore generico su {filename}: {e}")

    if files_processed == 0:
        print("⚠️  Nessun file JSON valido trovato in LOGISTIC. Il Master KB non è stato aggiornato.")
        return

    # Creazione oggetto finale
    master_kb = {
        "metadata": {
            "source": "AI Healthcare Navigator ETL",
            "total_nodes": len(merged_facilities_map),
            "districts_processed": files_processed
        },
        "facilities": list(merged_facilities_map.values())
    }

    # Scrittura su disco
    try:
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
            
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(master_kb, f, indent=4, ensure_ascii=False)
        
        print(f"\n✅ SUCCESSO! Generato 'master_kb.json' con {len(merged_facilities_map)} strutture.")
        print(f"📍 Percorso: {output_file}")
        
    except Exception as e:
        print(f"❌ Errore nel salvataggio finale: {e}")

if __name__ == "__main__":
    merge_json_files()