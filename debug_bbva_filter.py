#!/usr/bin/env python3
"""
Debug para ver exactamente qué está descartando el parser BBVA
"""

import pandas as pd
from pathlib import Path
from src.utils.date_utils import looks_like_date
from src.utils.logger import get_logger

logger = get_logger(__name__)

def debug_bbva_rows():
    """Ver qué filas se descartan en BBVA."""
    
    import os
    import glob
    
    temp_base = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Temp"
    bbva_file = None
    
    for temp_dir in glob.glob(str(temp_base / "tmp*")):
        temp_path = Path(temp_dir)
        bbva_candidates = list(temp_path.glob("*6614*.xlsx"))
        if bbva_candidates:
            bbva_file = str(bbva_candidates[0])
            break
    
    if not bbva_file:
        print("❌ Archivo BBVA no encontrado")
        return
    
    print(f"ANALIZANDO: {Path(bbva_file).name}\n")
    
    # Leer raw (como lo hace el parser)
    raw = pd.read_excel(bbva_file, sheet_name=0, header=None, dtype=str).fillna("")
    print(f"Total filas en Excel: {len(raw)}")
    print(f"Primeras 3 filas:\n{raw.head(3)}\n")
    
    # Simular header detection
    header = [str(c).strip() for c in raw.iloc[0]]
    df = raw.iloc[1:].copy()
    df.columns = header
    df = df.reset_index(drop=True)
    
    print(f"Columnas detectadas: {df.columns.tolist()}\n")
    
    # Buscar el 229
    print("=" * 70)
    print("BÚSQUEDA DE 229 EN RAW")
    print("=" * 70)
    
    mask_229_raw = raw.astype(str).apply(lambda x: x.str.contains("229", case=False, na=False).any(), axis=1)
    if mask_229_raw.any():
        print(f"✓ Encontradas {mask_229_raw.sum()} filas con '229' en raw:")
        for idx in raw[mask_229_raw].index:
            print(f"\n  Fila {idx}: {raw.iloc[idx].tolist()}")
    else:
        print("❌ No hay filas con '229' en raw")
    
    # Aplicar el filtro de fecha
    print("\n" + "=" * 70)
    print("FILTRO DE FECHA")
    print("=" * 70)
    
    if "FECHA DE OPERACIÓN" in df.columns:
        fecha_col = "FECHA DE OPERACIÓN"
    elif "FECHA" in df.columns:
        fecha_col = "FECHA"
    else:
        fecha_col = df.columns[0]
    
    print(f"Columna de fecha: {fecha_col}\n")
    
    # Mostrar qué fechas hay
    print(f"Primeras 10 fechas:")
    for i, fecha in enumerate(df[fecha_col].head(10)):
        valid = looks_like_date(fecha)
        print(f"  [{i}] {fecha!r} → {valid}")
    
    # Contar descartadas
    valid_mask = df[fecha_col].apply(looks_like_date)
    print(f"\nTotal filas: {len(df)}")
    print(f"Filas con fecha válida: {valid_mask.sum()}")
    print(f"Filas descartadas por fecha: {(~valid_mask).sum()}")
    
    # Ver qué se descarta
    if (~valid_mask).any():
        print(f"\nEjemplos de filas descartadas:")
        discarded = df[~valid_mask]
        for idx, row in discarded.head(10).iterrows():
            fecha = row[fecha_col]
            print(f"  [{idx}] Fecha={fecha!r} → Desc={row.get('DESCRIPCIÓN', '')[:40]}")
    
    # Buscar 229 en lo descartado
    print(f"\n" + "=" * 70)
    print("¿ESTÁ 229 EN LO DESCARTADO?")
    print("=" * 70)
    
    discarded_filtered = df[~valid_mask]
    mask_229_disc = (discarded_filtered.astype(str).apply(lambda x: x.str.contains("229", case=False, na=False).any(), axis=1))
    
    if mask_229_disc.any():
        print(f"⚠️  SÍ - El 229 ESTÁ EN LAS FILAS DESCARTADAS:")
        for idx in discarded_filtered[mask_229_disc].index:
            row = df.iloc[idx]
            print(f"\n  Fila {idx}:")
            print(f"    Fecha: {row[fecha_col]!r}")
            print(f"    Desc: {row.get('DESCRIPCIÓN', 'N/A')}")
            print(f"    Depósitos: {row.get('DEPÓSITOS', 'N/A')}")
    else:
        print(f"✓ No - El 229 NO está en filas descartadas")
        print(f"Posiblemente el 229 no exista en el BBVA raw")

if __name__ == "__main__":
    debug_bbva_rows()
