# test_api_v2.py
import os

def test_groq():
    """Test Groq API"""
    try:
        from groq import Groq
        
        secrets_path = ".streamlit/secrets.toml"
        groq_key = None
        
        if os.path.exists(secrets_path):
            with open(secrets_path, 'r', encoding='utf-8') as f:
                content = f.read()
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith("GROQ_API_KEY"):
                        # Parsing più robusto
                        if '=' in line:
                            groq_key = line.split('=', 1)[1].strip().strip('"').strip("'").strip()
                        break
        
        if not groq_key:
            print("❌ GROQ_API_KEY non trovata")
            print(f"   File esiste: {os.path.exists(secrets_path)}")
            if os.path.exists(secrets_path):
                with open(secrets_path, 'r') as f:
                    print("   Contenuto file:")
                    for i, line in enumerate(f, 1):
                        print(f"      {i}: {repr(line)}")
            return False
        
        print(f"🔑 Groq Key:  {groq_key[: 10]}...{groq_key[-5:]}")
        
        # Test API
        client = Groq(api_key=groq_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Rispondi solo 'OK'"}],
            max_tokens=10,
            temperature=0
        )
        
        result = response.choices[0].message. content
        print(f"✅ Groq FUNZIONANTE | Risposta: '{result}'")
        return True
        
    except Exception as e:
        print(f"❌ Groq ERROR: {type(e).__name__}")
        print(f"   Dettagli:  {str(e)}")
        return False


def test_gemini():
    """Test Gemini API con modello corretto"""
    try:
        import google.generativeai as genai
        
        secrets_path = ".streamlit/secrets.toml"
        gemini_key = None
        
        if os. path.exists(secrets_path):
            with open(secrets_path, 'r', encoding='utf-8') as f:
                content = f.read()
                for line in content.split('\n'):
                    line = line. strip()
                    if line. startswith("GEMINI_API_KEY"):
                        if '=' in line:
                            gemini_key = line.split('=', 1)[1].strip().strip('"').strip("'").strip()
                        break
        
        if not gemini_key:
            print("❌ GEMINI_API_KEY non trovata")
            return False
        
        print(f"🔑 Gemini Key: {gemini_key[: 10]}...{gemini_key[-5:]}")
        
        # Configura API
        genai.configure(api_key=gemini_key)
        
        # ✅ PROVA MODELLI ALTERNATIVI
        models_to_try = [
            "gemini-2.5-flash"
        ]
        
        for model_name in models_to_try: 
            try:
                print(f"   Provo modello: {model_name}...")
                model = genai.GenerativeModel(model_name)
                response = model.generate_content("Rispondi solo 'OK'")
                result = response.text. strip()
                print(f"✅ Gemini FUNZIONANTE | Modello: {model_name} | Risposta: '{result}'")
                return True
            except Exception as e:
                print(f"   ⚠️ {model_name} fallito: {type(e).__name__}")
                continue
        
        print("❌ Tutti i modelli Gemini falliti")
        return False
        
    except Exception as e:
        print(f"❌ Gemini ERROR: {type(e).__name__}")
        print(f"   Dettagli:  {str(e)}")
        return False


if __name__ == "__main__": 
    print("=" * 60)
    print("🧪 TEST CHIAVI API V2 - DEBUG AVANZATO")
    print("=" * 60)
    print()
    
    if not os.path.exists(".streamlit/secrets.toml"):
        print("❌ File . streamlit/secrets.toml NON TROVATO")
        exit(1)
    
    print("📁 File secrets.toml trovato")
    print()
    
    # Mostra contenuto grezzo
    print("📄 CONTENUTO FILE (RAW):")
    print("-" * 60)
    with open(".streamlit/secrets.toml", 'rb') as f:
        raw = f.read()
        print(f"Bytes: {raw}")
        print(f"Decodificato:\n{raw.decode('utf-8')}")
    print("-" * 60)
    print()
    
    # Test API
    print("-" * 60)
    print("TEST 1: GROQ API")
    print("-" * 60)
    groq_ok = test_groq()
    print()
    
    print("-" * 60)
    print("TEST 2: GEMINI API")
    print("-" * 60)
    gemini_ok = test_gemini()
    print()
    
    # Risultato
    print("=" * 60)
    print("RISULTATO FINALE")
    print("=" * 60)
    
    if groq_ok and gemini_ok:
        print("✅ ENTRAMBE LE API FUNZIONANTI")
    elif groq_ok:
        print("✅ Groq OK | ⚠️ Gemini fallisce")
    elif gemini_ok:
        print("⚠️ Groq fallisce | ✅ Gemini OK")
    else:
        print("❌ ENTRAMBE LE API FALLISCONO")