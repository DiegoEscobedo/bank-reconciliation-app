import pandas as pd

path = r'Z:\40. PERSONAL SERVICIO SOCIAL\CONCILIACION\02.-03-2026\Copia de Ventas_MercadoPago_2026-03-02_11-06hs.xlsx'
df = pd.read_excel(path, header=None, dtype=str)
print(f"Total filas: {len(df)} | Total columnas: {len(df.columns)}")
print()
print("--- Fila 3 (cabeceras) ---")
for i, h in enumerate(df.iloc[3].tolist()):
    print(f"  col{i:02d}: {repr(h)}")
print()
print("--- Fila 4 (primer dato) ---")
for i, v in enumerate(df.iloc[4].tolist()):
    print(f"  col{i:02d}: {repr(v)}")
