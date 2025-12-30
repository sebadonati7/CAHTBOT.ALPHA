#!/usr/bin/env python3
"""
Test script for backend.py functionality
Tests core functions without requiring Streamlit to be running
"""

import json
import os
import sys
from datetime import datetime

# Test NLP functions
def test_nlp_functions():
    print("Testing NLP Functions...")
    print("=" * 50)
    
    # Import only the NLP functions we need
    sys.path.insert(0, os.path.dirname(__file__))
    
    # Test identify_macro_area
    from backend import identify_macro_area, ASL_MACRO_AREAS
    
    test_cases = [
        ("ho febbre", "riposa", "Area Medica"),
        ("ho il petto che mi fa male", "vai al pronto soccorso", "Area Cardiologica"),
        ("caduta dalle scale", "trauma", "Area Traumatologica"),
        ("sono incinta", "contrazioni", "Area Materno-Infantile"),
    ]
    
    for user_input, bot_response, expected in test_cases:
        result = identify_macro_area(user_input, bot_response)
        status = "✓" if expected in result else "✗"
        print(f"{status} identify_macro_area('{user_input}', '{bot_response}') = {result}")
    
    # Test extract_age
    from backend import extract_age
    
    age_tests = [
        ("ho 45 anni", 45),
        ("età 67", 67),
        ("di 23 anni", 23),
        ("nessuna età", None),
    ]
    
    for text, expected in age_tests:
        result = extract_age(text)
        status = "✓" if result == expected else "✗"
        print(f"{status} extract_age('{text}') = {result}")
    
    # Test detect_hostility_level
    from backend import detect_hostility_level
    
    hostility_tests = [
        ("ciao come stai", 0),
        ("basta con queste domande", 1),
        ("sei stupido", 2),
        ("vaffanculo", 3),
    ]
    
    for text, expected in hostility_tests:
        result = detect_hostility_level(text)
        status = "✓" if result == expected else "✗"
        print(f"{status} detect_hostility_level('{text}') = {result}")
    
    print()

def test_datastore():
    print("Testing TriageDataStore...")
    print("=" * 50)
    
    from backend import TriageDataStore
    
    # Test with actual log file
    if os.path.exists('triage_logs.jsonl'):
        ds = TriageDataStore('triage_logs.jsonl')
        print(f"✓ Loaded {len(ds.records)} records")
        print(f"✓ Found {len(ds.sessions)} unique sessions")
        
        if ds.records:
            # Test filtering
            years = ds.get_unique_values('year')
            if years:
                filtered = ds.filter(year=years[0])
                print(f"✓ Filtered to year {years[0]}: {len(filtered.records)} records")
            
            # Test count_by_field
            outcomes = ds.count_by_field('triage_outcome')
            print(f"✓ count_by_field('triage_outcome'): {len(outcomes)} unique outcomes")
            
            # Test get_unique_values
            districts = ds.get_unique_values('distretto')
            print(f"✓ get_unique_values('distretto'): {len(districts)} unique districts")
    else:
        print("⚠ triage_logs.jsonl not found, skipping datastore tests")
    
    print()

def test_kpis():
    print("Testing KPI Calculations...")
    print("=" * 50)
    
    from backend import TriageDataStore, calculate_kpis
    
    if os.path.exists('triage_logs.jsonl'):
        ds = TriageDataStore('triage_logs.jsonl')
        
        if ds.records:
            kpis = calculate_kpis(ds)
            
            expected_kpis = [
                'sessioni_uniche',
                'tasso_deviazione_ps',
                'completamento_funnel',
                'churn_tecnico',
                'profondita_media',
                'interazioni_totali',
                'eta_media',
                'sentiment_negativo',
                'intensita_ostilita',
                'durata_media_sessione'
            ]
            
            for kpi_name in expected_kpis:
                if kpi_name in kpis:
                    value = kpis[kpi_name]
                    print(f"✓ {kpi_name}: {value:.2f}")
                else:
                    print(f"✗ {kpi_name}: MISSING!")
        else:
            print("⚠ No records to calculate KPIs")
    else:
        print("⚠ triage_logs.jsonl not found, skipping KPI tests")
    
    print()

def test_epi():
    print("Testing EPI Calculations...")
    print("=" * 50)
    
    from backend import TriageDataStore, calculate_epi
    
    if os.path.exists('triage_logs.jsonl'):
        ds = TriageDataStore('triage_logs.jsonl')
        
        if ds.records:
            epi_results = calculate_epi(ds)
            
            for structure in ['CAU', 'Pronto Soccorso', 'Guardia Medica']:
                if structure in epi_results:
                    data = epi_results[structure]
                    print(f"✓ {structure}:")
                    print(f"  - Count: {data['count']}")
                    print(f"  - EPI: {data['epi']:.2f}")
                    print(f"  - Z-score: {data['z_score']:.2f}")
                    print(f"  - Status: {data['status']}")
                else:
                    print(f"✗ {structure}: MISSING!")
        else:
            print("⚠ No records to calculate EPI")
    else:
        print("⚠ triage_logs.jsonl not found, skipping EPI tests")
    
    print()

def test_validation():
    print("Testing Validation Functions...")
    print("=" * 50)
    
    from backend import validate_comune_er, parse_timestamp_robust
    
    # Test comuni validation
    valid_comuni = ['bologna', 'modena', 'cento']
    invalid_comuni = ['milano', 'roma', None]
    
    for comune in valid_comuni:
        result = validate_comune_er(comune)
        status = "✓" if result else "✗"
        print(f"{status} validate_comune_er('{comune}') = {result}")
    
    for comune in invalid_comuni:
        result = validate_comune_er(comune)
        status = "✓" if not result else "✗"
        print(f"{status} validate_comune_er('{comune}') = {result}")
    
    # Test timestamp parsing
    timestamps = [
        "2025-12-30T01:31:14.532615+01:00",
        "2025-12-24T19:49:13.991188",
        "2025-12-30 14:32:39"
    ]
    
    for ts in timestamps:
        result = parse_timestamp_robust(ts)
        status = "✓" if result is not None else "✗"
        print(f"{status} parse_timestamp_robust('{ts[:30]}...') = {result}")
    
    print()

def main():
    print("\n" + "=" * 50)
    print("BACKEND.PY FUNCTIONALITY TEST")
    print("=" * 50 + "\n")
    
    try:
        test_nlp_functions()
        test_datastore()
        test_kpis()
        test_epi()
        test_validation()
        
        print("=" * 50)
        print("ALL TESTS COMPLETED!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
