import pandas as pd, sys

path = r"Z:\40. PERSONAL SERVICIO SOCIAL\CONCILIACION\26-02-2026\REPORTE CAJA.xlsx"
out  = open("_reporte_structure.txt", "w", encoding="utf-8")

xl = pd.ExcelFile(path)
out.write(f"Hojas: {xl.sheet_names}\n")

for sh in xl.sheet_names:
    df = pd.read_excel(xl, sheet_name=sh, header=None, dtype=str).fillna("")
    out.write(f"\n--- Hoja: '{sh}' | {df.shape[0]} filas x {df.shape[1]} cols ---\n")
    out.write(df.head(12).to_string())
    out.write("\n")

out.close()
print("OK - ver _reporte_structure.txt")
