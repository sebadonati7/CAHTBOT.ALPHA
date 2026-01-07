import os
import re

PROTOCOL_MAP = {
    # Pattern da cercare nel nome file -> Nome normalizzato
    r"DA5|da5":  "DA5_ViolenzaDonne",
    r"ASQ|asq": "ASQ_AbuseSostanze",
    r"WAST|wast": "WAST_ViolenzaDomestica",
    r"AUDIT|audit": "AUDIT_Alcol",
    r"ginecolog": "GINECOLOGIA_Standard",
    r"psichiatr": "PSICHIATRIA_Standard",
    r"trauma|ortoped": "TRAUMA_Ortopedia"
}

def normalize_protocol_names(folder_path:  str):
    """Rinomina i file secondo lo standard TIPO_Descrizione. ext"""
    if not os.path.exists(folder_path):
        print(f"❌ Cartella {folder_path} non trovata")
        return
    
    renamed_count = 0
    for filename in os.listdir(folder_path):
        old_path = os.path.join(folder_path, filename)
        
        # Salta directory
        if os.path.isdir(old_path):
            continue
        
        # Estrai estensione
        name, ext = os.path.splitext(filename)
        name_lower = name.lower()
        
        # Trova match con i pattern
        new_name = None
        for pattern, standard_name in PROTOCOL_MAP. items():
            if re.search(pattern, name_lower, re.IGNORECASE):
                new_name = f"{standard_name}{ext}"
                break
        
        # Rinomina se trovato match
        if new_name and new_name != filename:
            new_path = os.path.join(folder_path, new_name)
            
            # Evita sovrascritture
            if os.path.exists(new_path):
                print(f"⚠️ {new_name} già esiste, skip {filename}")
                continue
            
            os.rename(old_path, new_path)
            print(f"✅ Rinominato:  {filename} → {new_name}")
            renamed_count += 1
        else:
            print(f"⏭️ Nessun match per:  {filename}")
    
    print(f"\n🎉 Operazione completata: {renamed_count} file rinominati")

if __name__ == "__main__": 
    PROTOCOLS_PATH = r"C:\Users\Seba\Desktop\demo\knowledge_base\PROTOCOLLI"
    normalize_protocol_names(PROTOCOLS_PATH)