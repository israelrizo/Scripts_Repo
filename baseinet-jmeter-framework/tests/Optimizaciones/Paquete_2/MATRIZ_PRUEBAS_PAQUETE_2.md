# Matriz de Casos de Prueba — Modulo: Optimizaciones (Paquete 2)

Esta matriz detalla los scripts de JMeter para el **Paquete 2** del modulo de Optimizaciones, diseñados para pruebas de alta concurrencia sobre microservicios especificos bajo el entorno **QA2**.

## Resumen de Scripts — Paquete 2 (4 Scripts + 1 General)

| Submodulo | Script (Nombre Completo) | Objetivo | Servicio Impactado | Datos | Status Fail/Pass | Fecha |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **Destinatarios** | `G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdAddDestinatario.jmx` | Alta de nuevos destinatarios en QA2 | `CdAddDestinatario` | `usuarios_backend.csv` | | |
| **Autorizaciones / Traspasos** | `G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdDoCapturarTraspasoMasivo_CdDoAutorizarTraspaso_CdGetTraspasos.jmx` | Captura masiva, autorizacion de traspasos y consulta SPEI | `CdDoCapturarTraspasoMasivo`,<br/>`CdDoAutorizarTraspaso`,<br/>`CdGetTraspasos` | `usuarios_backend.csv` | | |
| **Estado de Cuenta** | `G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdGetEstadoCuentaPdf_CdGetEstadoCuentaMt940Commando.jmx` | Descarga de estados de cuenta en PDF y formato MT940 | `CdGetEstadoCuentaPdf`,<br/>`CdGetEstadoCuentaMt940Commando` | `usuarios_backend.csv` | | |
| **Comprobantes** | `G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdGetTraspasosComprobantes.jmx` | Consulta de comprobantes de traspasos en QA2 | `CdGetTraspasosComprobantes` | `usuarios_backend.csv` | | |
| **Flujo General Completo** | `Metodos_General/G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_METODOS_GENERAL.jmx` | Ejecucion combinada de todos los flujos del Paquete 2 | Todos los anteriores | `usuarios_backend.csv` | | |

---

## Configuracion Sugerida (Thread Group)

- Inyecta el perfil de carga correspondiente con `-q tests/Ejecuciones/Tipos_De_Prueba/[Tipo]/perfil_carga.properties`.
- Los datos de usuarios se consumen desde `../../../data/`.
- Ajusta los parametros `${__P(threads, 1)}`, `${__P(rampup, 1)}` y `${__P(duration, 60)}` al escenario requerido.

## Comando de Ejecucion Rapida — Flujo General

```bash
TIMESTAMP=$(date +"%d%m%y_%H%M")
DIR="results/Ejecucion_${TIMESTAMP}_P2_Metodos_General"
mkdir -p "$DIR/html_report"

jmeter -n \
  -t "tests/Optimizaciones/Paquete_2/Metodos_General/G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_METODOS_GENERAL.jmx" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report"
```
