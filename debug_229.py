#!/usr/bin/env python3
"""
Script para diagnosticar por qué el registro 229,00 no aparece en el output.
Rastrea el registro a través de todo el pipeline.
"""

import pandas as pd
from pathlib import Path
from src.parsers.bank_parser import BankParser
from src.normalizers.bank_normalizer import BankNormalizer
from src.parsers.jde_parser import JDEParser
from src.normalizers.jde_normalizer import JDENormalizer
from src.utils.logger import get_logger

logger = get_logger(__name__)

def debug_229():
    """Rastrear registro 229,00 a través del pipeline."""
    
    # Archivo del usuario
    bank_file = Path("data/raw/bank/6614-B 1.xlsx")
    
    if not bank_file.exists():
        print(f"❌ Archivo no encontrado: {bank_file}")
        return
    
    # Step 1: PARSING
    print("\n" + "="*70)
    print("STEP 1: PARSING")
    print("="*70)
    parser = BankParser()
    bank_raw = parser.parse(str(bank_file))
    
    print(f"✓ Total filas parseadas: {len(bank_raw)}")
    print(f"✓ Columnas: {bank_raw.columns.tolist()}")
    
    # Buscar registro de 229,00
    records_229 = bank_raw[bank_raw["raw_deposit"].astype(str).str.contains("229", na=False)]
    print(f"\n🔍 Registros con monto ~229: {len(records_229)}")
    if not records_229.empty:
        print(records_229.to_string())
    else:
        print("  ❌ No hay registros con monto ~229 en raw parsed data")
        # Mostrar primeros registros para contexto
        print("\n  Primeros 5 registros del parser:")
        print(bank_raw.head()[["raw_date", "raw_deposit", "description", "tienda"]].to_string())
    
    # Step 2: NORMALIZE
    print("\n" + "="*70)
    print("STEP 2: NORMALIZE")
    print("="*70)
    normalizer = BankNormalizer()
    bank_normalized = normalizer.normalize(bank_raw)
    
    print(f"✓ Total filas normalizadas: {len(bank_normalized)}")
    
    # Buscar registro 229,00
    records_229_norm = bank_normalized[
        (bank_normalized["abs_amount"].astype(float) > 228) & 
        (bank_normalized["abs_amount"].astype(float) < 230)
    ]
    print(f"\n🔍 Registros con monto 228-230: {len(records_229_norm)}")
    if not records_229_norm.empty:
        print(records_229_norm[["movement_date", "abs_amount", "description", "tienda"]].to_string())
    else:
        print("  ❌ No hay registros con monto 228-230 tras normalización")
        # Debug: mostrar resumen de montos
        print("\n  Resumen de montos normalizados:")
        print(f"    Min: {bank_normalized['abs_amount'].min()}, Max: {bank_normalized['abs_amount'].max()}")
        print(f"    Media: {bank_normalized['abs_amount'].mean():.2f}")
    
    # Step 3: Analizar tienda "NO ENCONTRADO"
    print("\n" + "="*70)
    print("STEP 3: ANÁLISIS DE TIENDAS")
    print("="*70)
    
    if "tienda" in bank_normalized.columns:
        tienda_counts = bank_normalized["tienda"].value_counts()
        print("Distribución de tiendas:")
        for tienda, count in tienda_counts.items():
            print(f"  {tienda}: {count}")
        
        no_encontrados = bank_normalized[bank_normalized["tienda"] == "NO ENCONTRADO"]
        if not no_encontrados.empty:
            print(f"\n✓ Registros con tienda='NO ENCONTRADO': {len(no_encontrados)}")
            # Mostrar primeros con monto cercano a 229
            print("\n  Primeros registros con tienda=NO ENCONTRADO:")
            print(no_encontrados[["movement_date", "abs_amount", "description"]].head().to_string())

if __name__ == "__main__":
    debug_229()
