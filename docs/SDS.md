# SDS - Especificacion de Diseno de Software

Version: 2.2  
Fecha: 10/04/2026  
Autor: Diego Escobedo

## 1. Objetivo

Se documenta el diseno tecnico del sistema, su estructura por componentes y el flujo de procesamiento.

## 2. Arquitectura logica

Se adopta arquitectura por capas:
- Presentacion: app.py (Streamlit).
- Orquestacion: main.py.
- Dominio: src/matching.
- Infraestructura: src/parsers, src/normalizers, src/validacion, src/reporting, src/utils.

## 3. Componentes

- config/settings.py
  - Parametros globales y mapeos de negocio.

- src/parsers
  - Parseo y deteccion de formatos bancarios, JDE e historicos.

- src/normalizers
  - Transformacion al esquema estandar interno.

- src/validacion
  - Verificacion de columnas y tipos requeridos.

- src/matching
  - Matching exacto, agrupado y agrupado inverso.
  - Cruce historico de pendientes.

- src/reporting
  - Generacion de Excel de salida y write-back.

- src/batch
  - Proceso independiente para marcado por batch.

## 4. Flujo tecnico

### Stage 1
1. Parseo de archivos de entrada.
2. Normalizacion de datos.
3. Validacion de esquema.
4. Matching exacto.
5. Generacion de propuestas agrupadas.

### Stage 2
1. Recepcion de aprobaciones de usuario.
2. Aplicacion de grupos aprobados.
3. Construccion de pendientes finales.
4. Preparacion de resumen y salida.

## 5. Decisiones de diseno

- Se prioriza precision sobre cobertura de conciliacion.
- Se aplican filtros por cuenta, tienda y tipo.
- Se evita reutilizacion de movimientos conciliados.
- Se asigna tipo TPV por defecto a NetPay y Mercado Pago cuando no se informa en origen.
- Se utiliza Aux_Fact como identificador de write-back.

## 6. Contrato de datos

Columnas base internas:
- account_id
- movement_date
- description
- amount_signed
- abs_amount
- movement_type
- source

Campos complementarios:
- tienda
- tipo_banco
- tipo_jde
- _aux_fact

## 7. Extensibilidad

Para soportar nuevos formatos:
1. Incorporar parser correspondiente.
2. Ajustar normalizacion de columnas.
3. Validar esquema requerido.
4. Verificar compatibilidad con motor de matching.
5. Incorporar pruebas de regresion.
