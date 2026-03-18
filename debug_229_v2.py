#!/usr/bin/env python3
"""
Debug profundo para rastrear el registro 229,00
"""

import pandas as pd
from pathlib import Path
from src.parsers.bank_parser import BankParser
from src.normalizers.bank_normalizer import BankNormalizer
from src.utils.logger import get_logger

logger = get_logger(__name__)

def find_229_in_files():
    """Buscar registro 229,00 en todos los archivos."""
    
    # Buscar archivos en Streamlit temp dir
    import os
    import glob
    
    temp_dirs = [
        Path(os.path.expanduser("~")) / "AppData" / "Local" / "Temp",
    ]
    
    found_files = []
    for temp_dir in temp_dirs:
        if temp_dir.exists():
            for pattern in ["*6614*", "*REPORTE*", "*MARZO*"]:
                files = glob.glob(str(temp_dir / f"tmp*/{pattern}*.xlsx"))
                found_files.extend(files)
    
    print(f"🔍 Archivos encontrados: {len(found_files)}")
    for f in found_files[:5]:
        print(f"  - {f}")
    
    if not found_files:
        print("❌ No hay archivos temporales. Intenta cargar desde Streamlit y vuelve a ejecutar.")
        return
    
    # Analizar el primero que parece ser 6614
    for file_path in found_files:
        if "6614" in file_path.upper():
            print(f"\n{'='*70}")
            print(f"ANALIZANDO: {Path(file_path).name}")
            print('='*70)
            
            # Leer raw
            try:
                raw = pd.read_excel(file_path, header=None, dtype=str)
                print(f"Total filas en Excel: {len(raw)}")
                
                # Buscar 229
                mask_229 = raw.astype(str).apply(lambda x: x.str.contains("229", case=False, na=False).any(), axis=1)
                matching_rows = raw[mask_229]
                
                if not matching_rows.empty:
                    print(f"\n✓ Encontradas {len(matching_rows)} filas con '229':")
                    print(matching_rows.to_string())
                else:
                    print("\n❌ No hay filas con '229' en el archivo raw")
            except Exception as e:
                print(f"❌ Error leyendo archivo: {e}")
                continue
            
            # Parsear
            try:
                print(f"\n--- STEP 1: PARSING ---")
                parser = BankParser()
                parsed = parser.parse(file_path)
                print(f"Total filas parseadas: {len(parsed)}")
                
                # Buscar 229 en parsed
                mask_229_parsed = (
                    (parsed["raw_deposit"].astype(str).str.contains("229", na=False)) |
                    (parsed["raw_withdrawal"].astype(str).str.contains("229", na=False))
                )
                
                if mask_229_parsed.any():
                    print(f"✓ Encontrado en parsed:")
                    df_229 = parsed[mask_229_parsed]
                    print(df_229[["raw_date", "raw_deposit", "raw_withdrawal", "description", "tienda", "tipo_banco"]].to_string())
                    
                    # Normalizar
                    print(f"\n--- STEP 2: NORMALIZE ---")
                    normalizer = BankNormalizer()
                    normalized = normalizer.normalize(parsed)
                    print(f"Total filas normalizadas: {len(normalized)}")
                    
                    # Buscar en normalized
                    mask_229_norm = (
                        (normalized["abs_amount"] > 228.5) & 
                        (normalized["abs_amount"] < 229.5)
                    )
                    
                    if mask_229_norm.any():
                        print(f"✓ Encontrado en normalized:")
                        df_229_norm = normalized[mask_229_norm]
                        print(df_229_norm[["movement_date", "abs_amount", "description", "tienda", "tipo_banco"]].to_string())
                    else:
                        print(f"❌ NO encontrado en normalized (monto 228-230)")
                        print(f"  Rango de montos: {normalized['abs_amount'].min():.2f} - {normalized['abs_amount'].max():.2f}")
                else:
                    print(f"❌ No encontrado en parsed")
                    print(f"  Primeras 5 filas parseadas:")
                    print(parsed[["raw_date", "raw_deposit", "description", "tienda"]].head().to_string())
                    
            except Exception as e:
                print(f"❌ Error en parsing/normalize: {e}")
                import traceback
                traceback.print_exc()
            
            break

if __name__ == "__main__":
    find_229_in_files()
