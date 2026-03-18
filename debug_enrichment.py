#!/usr/bin/env python3
"""
Debug específico para el merge de enriquecimiento del 229,00
"""

import pandas as pd
from pathlib import Path
from src.parsers.bank_parser import BankParser
from src.normalizers.bank_normalizer import BankNormalizer
from src.utils.logger import get_logger

logger = get_logger(__name__)

def debug_enrich_229():
    """Debug del merge de enriquecimiento para 229,00."""
    
    import os
    import glob
    from src.utils.date_utils import parse_date_series
    
    # Buscar archivos
    temp_base = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Temp"
    
    # Encontrar archivos más recientes
    bbva_file = None
    reporte_file = None
    
    for temp_dir in glob.glob(str(temp_base / "tmp*")):
        temp_path = Path(temp_dir)
        bbva_candidates = list(temp_path.glob("*6614*.xlsx"))
        reporte_candidates = list(temp_path.glob("*MARZO*.xlsx")) + list(temp_path.glob("*03M*.xlsx"))
        
        if bbva_candidates:
            bbva_file = str(bbva_candidates[0])
        if reporte_candidates:
            reporte_file = str(reporte_candidates[0])
        
        if bbva_file and reporte_file:
            break
    
    if not bbva_file or not reporte_file:
        print(f"❌ Archivos no encontrados")
        print(f"   BBVA: {bbva_file}")
        print(f"   REPORTE: {reporte_file}")
        return
    
    print(f"BBVA: {Path(bbva_file).name}")
    print(f"REPORTE: {Path(reporte_file).name}")
    print()
    
    # Parse ambos
    print("="*70)
    print("PARSING Y NORMALIZACIÓN")
    print("="*70)
    
    bbva_raw = BankParser().parse(bbva_file)
    reporte_raw = BankParser().parse(reporte_file)
    
    print(f"BBVA parseado: {len(bbva_raw)} filas")
    print(f"REPORTE parseado: {len(reporte_raw)} filas")
    
    # Normalizar
    bbva_norm = BankNormalizer().normalize(bbva_raw)
    reporte_norm = BankNormalizer().normalize(reporte_raw)
    
    print(f"BBVA normalizado: {len(bbva_norm)} filas")
    print(f"REPORTE normalizado: {len(reporte_norm)} filas")
    
    # Filtrar REPORTE por 6614
    reporte_6614 = reporte_norm[reporte_norm["account_id"] == "6614"].copy()
    print(f"REPORTE 6614: {len(reporte_6614)} filas")
    
    # Buscar 229 en ambos
    print("\n" + "="*70)
    print("BÚSQUEDA DE 229,00")
    print("="*70)
    
    bbva_229 = bbva_norm[(bbva_norm["abs_amount"] > 228.5) & (bbva_norm["abs_amount"] < 229.5)]
    rep_229 = reporte_6614[(reporte_6614["abs_amount"] > 228.5) & (reporte_6614["abs_amount"] < 229.5)]
    
    print(f"BBVA tiene 229: {len(bbva_229)}")
    if not bbva_229.empty:
        print("  Datos BBVA 229:")
        print(f"    Fecha: {bbva_229['movement_date'].iloc[0]}")
        print(f"    Monto: {bbva_229['abs_amount'].iloc[0]:.2f}")
        print(f"    Desc: {bbva_229['description'].iloc[0][:60]}")
    
    print(f"\nREPORTE tiene 229: {len(rep_229)}")
    if not rep_229.empty:
        print("  Datos REPORTE 229:")
        print(f"    Fecha: {rep_229['movement_date'].iloc[0]}")
        print(f"    Monto: {rep_229['abs_amount'].iloc[0]:.2f}")
        print(f"    Desc: {rep_229['description'].iloc[0][:60]}")
        print(f"    Tienda: {rep_229['tienda'].iloc[0]}")
        print(f"    Tipo: {rep_229['tipo_banco'].iloc[0]}")
    
    # Simular el merge
    print("\n" + "="*70)
    print("SIMULACIÓN DE MERGE")
    print("="*70)
    
    bank = bbva_norm.copy()
    bank["_amt_key"] = bank["abs_amount"].round(2)
    bank["_date_key"] = bank["movement_date"].dt.date
    
    rep = reporte_6614.copy()
    rep["_amt_key"] = rep["abs_amount"].round(2)
    rep["_date_key"] = rep["movement_date"].dt.date
    
    # Eliminar duplicados en reporte
    rep = rep.drop_duplicates(subset=["_date_key", "_amt_key"])
    
    print(f"Keys para merge BBVA: {len(bank)} (fecha + monto)")
    print(f"Keys para merge REPORTE: {len(rep)} (fecha + monto)")
    
    # Debug: mostrar el 229 antes del merge
    if not bbva_229.empty:
        bbva_229_key_data = bbva_229.copy()
        bbva_229_key_data["_amt_key"] = bbva_229_key_data["abs_amount"].round(2)
        bbva_229_key_data["_date_key"] = bbva_229_key_data["movement_date"].dt.date
        print(f"\nBBVA 229 keys: date={bbva_229_key_data['_date_key'].iloc[0]}, amt={bbva_229_key_data['_amt_key'].iloc[0]}")
    
    if not rep_229.empty:
        rep_229_key_data = rep_229.copy()
        rep_229_key_data["_amt_key"] = rep_229_key_data["abs_amount"].round(2)
        rep_229_key_data["_date_key"] = rep_229_key_data["movement_date"].dt.date
        print(f"REPORTE 229 keys: date={rep_229_key_data['_date_key'].iloc[0]}, amt={rep_229_key_data['_amt_key'].iloc[0]}")
    
    # Hacer el merge
    merged = bank.merge(
        rep[["_date_key", "_amt_key", "tienda", "tipo_banco"]],
        on=["_date_key", "_amt_key"],
        how="left",
        suffixes=("", "_rep"),
    )
    
    print(f"\nMerge resultado: {len(merged)} filas")
    
    # Buscar 229 en merged
    merged_229 = merged[(merged["abs_amount"] > 228.5) & (merged["abs_amount"] < 229.5)]
    
    if not merged_229.empty:
        print(f"\n✓ 229 en merged: {len(merged_229)}")
        print(f"  Tienda en merged: {merged_229['tienda'].iloc[0]}")
        print(f"  Tipo_banco en merged: {merged_229['tipo_banco'].iloc[0]}")
    else:
        print(f"\n❌ 229 NO en merged después del join")

if __name__ == "__main__":
    debug_enrich_229()
