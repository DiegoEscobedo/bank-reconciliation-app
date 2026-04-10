# Bank Reconciliation App

Aplicacion empresarial para conciliacion bancaria entre estados de cuenta y registros JDE.

## Descripcion general

Se soporta la conciliacion de movimientos mediante estrategias exactas y agrupadas, con validacion operativa en interfaz web y generacion de evidencia en Excel.

## Funcionalidades principales

- Conciliacion exacta (1 a 1).
- Conciliacion agrupada (1 banco a N JDE).
- Conciliacion agrupada inversa (N banco a 1 JDE).
- Validacion de agrupaciones en interfaz Streamlit.
- Generacion de reporte final de conciliacion.
- Write-back a Papel de Trabajo para cuentas habilitadas.
- Modulo independiente de marcado por batch.
- Analisis historico de pendientes.

## Ejecucion

### Interfaz web

```bash
streamlit run app.py
```

Acceso local: http://localhost:8501

### Linea de comandos

```bash
python main.py --bank data/raw/bank/archivo_banco.xlsx --jde data/raw/jde/archivo_jde.xlsx --output data/output/reconciliations
```

## Instalacion local

```bash
git clone https://github.com/DiegoEscobedo/bank-reconciliation-app.git
cd bank-reconciliation-app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Estructura principal

```text
bank-reconciliation-app/
├── app.py
├── main.py
├── README.md
├── ARCHITECTURE.md
├── requirements.txt
├── config/
│   └── settings.py
├── docs/
│   ├── SRS.md
│   ├── SDS.md
│   └── MANUAL_USUARIO.md
├── deploy/
│   └── README_SERVER.md
└── src/
    ├── parsers/
    ├── normalizers/
    ├── validacion/
    ├── matching/
    ├── reporting/
    └── batch/
```

## Reglas operativas relevantes

- Se aplican tolerancias de monto y fecha definidas en config/settings.py.
- Se aplican controles por cuenta, tienda y tipo para reducir falsos positivos.
- Para NetPay y Mercado Pago, se asigna tipo TPV cuando el origen no lo informa.
- En cuentas de Papel de Trabajo, el marcado se ejecuta por Aux_Fact y cuenta.

## Documentacion

- Requisitos: docs/SRS.md
- Diseno tecnico: docs/SDS.md
- Manual de operacion: docs/MANUAL_USUARIO.md
- Arquitectura: ARCHITECTURE.md
- Despliegue en servidor: deploy/README_SERVER.md

## Autor

Diego Escobedo
