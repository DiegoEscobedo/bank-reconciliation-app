# ARCHITECTURE

Se presenta la arquitectura funcional y tecnica del sistema de conciliacion bancaria.

## 1. Estructura por capas

1. Presentacion (app.py).
2. Orquestacion (main.py).
3. Logica de negocio (src/matching).
4. Procesamiento y salida (parsers, normalizers, reporting).

## 2. Flujo de procesamiento

1. Carga de archivos desde interfaz.
2. Deteccion y parseo por tipo de fuente.
3. Normalizacion de esquema.
4. Validacion de calidad minima.
5. Ejecucion de matching exacto, agrupado e inverso.
6. Validacion operativa de propuestas.
7. Generacion de salidas y write-back cuando aplica.

## 3. Componentes principales

- src/parsers/bank_parser.py: parseo de BBVA, Banorte, Scotiabank, Mercado Pago, NetPay y Reporte Caja.
- src/parsers/jde_parser.py: parseo de JDE CSV y Papel de Trabajo.
- src/matching/reconciliation_engine.py: orquestacion de estrategias de conciliacion.
- src/reporting/excel_reporter.py: generacion de Excel y write-back por Aux_Fact.
- src/batch/batch_marking.py: flujo de marcado por batch.

## 4. Controles de precision

- Validacion por cuenta compatible.
- Validacion por tienda cuando aplica.
- Compatibilidad por tipo de pago.
- Tolerancias de monto y fecha configurables.

Regla vigente:
- En NetPay y Mercado Pago, se asigna TPV por defecto cuando tipo no es informado en origen.

## 5. Mantenimiento

Para cambios controlados se recomienda:
1. Ajuste puntual en parser o regla.
2. Incorporacion de prueba de regresion.
3. Validacion funcional en interfaz.
4. Verificacion de write-back.
