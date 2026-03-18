#!/usr/bin/env python3
"""
Debug para ver exactamente qué hay en el archivo BBVA en data/raw/bank/
"""

import pandas as pd
from pathlib import Path
import glob

def debug_raw_bank():
    """Ver la estructura del archivo BBVA en data/raw/bank/"""
    
    bank_dir = Path("data/raw/bank")
    if not bank_dir.exists():
        print(f"❌ Directorio no encontrado: {bank_dir}")
        return
    
    # Buscar archivos Excel
    xlsx_files = list(bank_dir.glob("*.xlsx"))
    if not xlsx_files:
        print(f"❌ No hay archivos .xlsx en {bank_dir}")
        return
    
    print(f"Archivos encontrados: {[f.name for f in xlsx_files]}\n")
    
    for xlsx_file in xlsx_files:
        print("="*80)
        print(f"ANALIZANDO: {xlsx_file.name}")
        print("="*80)
        
        # Leer todo sin transformaciones
        raw = pd.read_excel(xlsx_file, sheet_name=0, header=None, dtype=str).fillna("")
        
        print(f"Total filas: {len(raw)}")
        print(f"\nHEADER (Fila 0): {raw.iloc[0].tolist()}\n")
        
        # Buscar 229
        found_229 = False
        for idx in range(1, len(raw)):
            row = raw.iloc[idx]
            row_str = " | ".join(str(v) for v in row.values)
            if "229" in row_str:
                if not found_229:
                    print("="*80)
                    print("FILAS CON '229':")
                    print("="*80)
                    found_229 = True
                
                print(f"\nFila {idx}: {row_str[:120]}...")
                
                # Mostrar detalle
                header = raw.iloc[0].tolist()
                print("\n  Detalle columnas:")
                for col_idx, (col_name, val) in enumerate(zip(header, row.values)):
                    if val.strip():
                        print(f"    [{col_idx:2d}] {col_name:30s} = {val!r}")
        
        if not found_229:
            print("❌ NO se encontró '229' en este archivo\n")
        
        print()

if __name__ == "__main__":
    debug_raw_bank()
