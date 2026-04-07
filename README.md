# 🏦 Bank Reconciliation App

Aplicación de conciliación bancaria que compara movimientos del **estado de cuenta bancario** contra registros del sistema contable **JDE (JD Edwards)**. Genera reportes Excel con los resultados clasificados por tipo de coincidencia.

---

## Características

- Carga archivos Excel del banco y de JDE
- Normaliza y valida los datos automáticamente
- Motor de conciliación con múltiples estrategias de matching:
  - Coincidencia exacta por monto y fecha
  - Coincidencia agrupada (varios movimientos → un registro)
- Interfaz web interactiva con **Streamlit**
- Uso por línea de comandos (CLI)
- Reporte Excel con hojas separadas por resultado

---

## Estructura del proyecto

```
bank-reconciliation-app/
├── app.py                  # Interfaz Streamlit
├── main.py                 # Orquestador CLI del pipeline
├── requirements.txt
├── config/
│   └── settings.py         # Configuración global
├── src/
│   ├── parsers/            # Lectura de archivos Excel
│   ├── normalizers/        # Estandarización de columnas
│   ├── validacion/         # Validación de esquemas
│   ├── matching/           # Motor de conciliación
│   ├── reporting/          # Generación de reportes Excel
│   └── utils/              # Logger, utilidades de fechas/montos
└── data/
    ├── raw/
    │   ├── bank/           # Archivos de entrada del banco
    │   └── jde/            # Archivos de entrada de JDE
    └── output/
        └── reconciliations/ # Reportes generados
```

---

## Instalación

```bash
# Clonar el repositorio
git clone https://github.com/DiegoEscobedo/bank-reconciliation-app.git
cd bank-reconciliation-app

# Crear entorno virtual (recomendado)
python -m venv .venv
.venv\Scripts\activate  # Windows

# Instalar dependencias
pip install -r requirements.txt
```

---

## Uso

### Interfaz web (Streamlit)

```bash
streamlit run app.py
```

Abre `http://localhost:8501` en el navegador, carga los archivos del banco y JDE, y descarga el reporte al finalizar.

### Línea de comandos

```bash
python main.py --bank  data/raw/bank/estado_cuenta.xlsx \
               --jde   data/raw/jde/movimientos_jde.xlsx \
               --output data/output/reconciliations/
```

### Despliegue en servidor propio

Se agregó una guía y plantillas en la carpeta `deploy` para montar la app en Linux con `systemd + Nginx + SSL`:

- `deploy/README_SERVER.md`
- `deploy/systemd/bank-reconciliation.service`
- `deploy/nginx/bank-reconciliation.conf`
- `deploy/scripts/deploy.sh`

Esto **no cambia** tu flujo local. Puedes seguir ejecutando en tu equipo con:

```bash
streamlit run app.py
```

---

## Formato de archivos de entrada

Los archivos deben ser `.xlsx`. Después de parsear y normalizar, el sistema espera las columnas:

| Columna | Tipo | Descripción |
|---|---|---|
| `account_id` | string | Identificador de cuenta |
| `movement_date` | datetime | Fecha del movimiento |
| `description` | string | Descripción o concepto |
| `amount_signed` | float | Monto con signo (+/-) |
| `abs_amount` | float | Monto absoluto |
| `movement_type` | string | Tipo de movimiento |
| `source` | string | Origen (`BANK` o `JDE`) |

---

## Dependencias principales

| Paquete | Uso |
|---|---|
| `pandas` | Procesamiento de datos |
| `streamlit` | Interfaz web |
| `openpyxl` / `xlsxwriter` | Lectura y escritura de Excel |
| `rapidfuzz` | Matching aproximado de texto |
| `python-dateutil` | Parseo de fechas |

---

## Autor

**Diego Escobedo** — diegoemilianoescobedoramirez@gmail.com
