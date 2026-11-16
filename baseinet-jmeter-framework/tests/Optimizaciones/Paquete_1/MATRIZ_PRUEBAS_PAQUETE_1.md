# Matriz de Casos de Prueba — Modulo: Optimizaciones (Paquete 1)

Esta matriz detalla los scripts de JMeter para el **Paquete 1** del modulo de Optimizaciones, diseñados para pruebas de alta concurrencia sobre microservicios especificos bajo los entornos **QA y DRP**.

## Resumen de Scripts — Paquete 1 (9 Scripts + 1 General)

| Submodulo | Script (Nombre Completo) | Objetivo | Servicio Impactado | Datos | Status Fail/Pass | Fecha |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **Login / Sesion** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_ScValidateCuenta_CdGetCustomerNotices_ScDoIniciarSesion_ScDoFinalizarSesion.jmx` | Flujo completo de inicio y cierre de sesion con validacion de cuenta | `ScValidateCuenta`,<br/>`CdGetCustomerNotices`,<br/>`ScDoIniciarSesion`,<br/>`ScDoFinalizarSesion` | `usuarios_backend.csv` | | |
| **Cuentas** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetCuentas.jmx` | Consulta de cuentas disponibles del usuario | `CdGetCuentas` | `usuarios_backend.csv` | | |
| **Traspasos** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetCuentasTraspasos.jmx` | Consulta de cuentas habilitadas para traspasos | `CdGetCuentasTraspasos` | `usuarios_backend.csv` | | |
| **Destinatarios** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetDestinatariosAutorizadosPageInDB.jmx` | Consulta paginada de destinatarios autorizados en BD | `CdGetDestinatariosAutorizadosPageInDB` | `usuarios_backend.csv` | | |
| **Movimientos** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetMovimientos.jmx` | Consulta de movimientos de cuenta | `CdGetMovimientos` | `usuarios_backend.csv` | | |
| **Comprobantes** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetTraspasosComprobantes.jmx` | Consulta de comprobantes de traspasos | `CdGetTraspasosComprobantes` | `usuarios_backend.csv` | | |
| **Autorizaciones / SPEI** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdDoAutorizarTraspaso_CdGetTraspasos.jmx` | Autorizacion de traspasos y consulta de SPEI | `CdDoAutorizarTraspaso`,<br/>`CdGetTraspasos` | `usuarios_backend.csv` | | |
| **Estado de Cuenta** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetEstadoCuentaPdf_CdGetEstadoCuentaMt940Commando_CdGetMovimientos.jmx` | Descarga de estado de cuenta (PDF y MT940) y movimientos | `CdGetEstadoCuentaPdf`,<br/>`CdGetEstadoCuentaMt940Commando`,<br/>`CdGetMovimientos` | `usuarios_backend.csv` | | |
| **Dispersion / Lote** | `G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdLoadArchivoLoteBase64.jmx` | Carga de archivo de dispersion masiva en Base64 | `CdLoadArchivoLoteBase64` | `usuarios_backend.csv`,<br/>`archivo_lote.b64` | | |
| **Flujo General Completo** | `Metodos_General/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_METODOS_GENERAL.jmx` | Ejecucion combinada de todos los flujos del Paquete 1 | Todos los anteriores | `usuarios_backend.csv` | | |

---

## Configuracion Sugerida (Thread Group)

- Inyecta el perfil de carga correspondiente con `-q tests/Ejecuciones/Tipos_De_Prueba/[Tipo]/perfil_carga.properties`.
- Los datos de usuarios se consumen desde `../../../data/`.
- Ajusta los parametros `${__P(threads, 1)}`, `${__P(rampup, 1)}` y `${__P(duration, 60)}` al escenario requerido.

## Comando de Ejecucion Rapida — Flujo General

```bash
TIMESTAMP=$(date +"%d%m%y_%H%M")
DIR="results/Ejecucion_${TIMESTAMP}_P1_Metodos_General"
mkdir -p "$DIR/html_report"

jmeter -n \
  -t "tests/Optimizaciones/Paquete_1/Metodos_General/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_METODOS_GENERAL.jmx" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report"
```
