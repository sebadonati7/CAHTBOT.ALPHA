import os
import sys
import platform

print("="*50)
print("🔍 DIAGNOSTICA PANDAS - TEST COMPATIBILITÀ")
print("="*50)

try:
    # 1. Info Sistema
    print(f"[1] Python: {sys.version}")
    print(f"[1b] OS: {platform.system()} {platform.release()} ({platform.architecture()[0]})")
    
    # 2. Test Import NumPy (Cuore di Pandas)
    print("[2] Tentativo di importazione NumPy...", end=" ")
    import numpy as np
    print(f"✅ OK (v{np.__version__})")
    
    # 3. Test Import Pandas
    print("[3] Tentativo di importazione Pandas...", end=" ")
    import pandas as pd
    print(f"✅ OK (v{pd.__version__})")
    
    # 4. Test Creazione DataFrame
    print("[4] Test creazione DataFrame...", end=" ")
    df = pd.DataFrame({
        'A': [1, 2, 3, 4],
        'B': ['alpha', 'beta', 'gamma', 'delta'],
        'C': [10.5, 20.1, 30.7, 40.2]
    })
    print("✅ OK")

    # 5. Test Operazioni Matematiche (Vettorializzazione)
    print("[5] Test calcoli matematici...", end=" ")
    df['D'] = df['A'] * 2 + df['C']
    print("✅ OK")

    # 6. Test Filtraggio e Stringhe
    print("[6] Test filtraggio stringhe...", end=" ")
    result = df[df['B'].str.contains('a')]
    print("✅ OK")

    print("\n" + "="*50)
    print("🎉 RISULTATO: Pandas è COMPATIBILE con il tuo PC!")
    print("="*50)
    
    print("\nDettagli ambiente:")
    pd.show_versions()

except ImportError as e:
    print(f"\n❌ ERRORE: Libreria mancante: {e}")
    print("Prova a eseguire: py -3.12 -m pip install pandas numpy")
except Exception as e:
    print(f"\n❌ CRASH RILEVATO: {e}")
    print("\nSe il programma si è chiuso senza questo messaggio,")
    print("il problema risiede nelle istruzioni della CPU caricate da NumPy.")