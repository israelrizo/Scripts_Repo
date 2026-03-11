# Matriz de Casos de Prueba - Módulo de Optimizaciones (MCD)

Esta matriz detalla los scripts de JMeter para el módulo de **Optimizaciones (MCD)**, diseñados para alta concurrencia y microservicios específicos. Se enfoca exclusivamente en los scripts del **Paquete 1**.

## 📊 Resumen de Scripts - Optimizaciones (10 Casos)

| Submódulo | Script (Nombre Completo) | Objetivo | Servicio Impactado | Datos | Status Fail/Pass | &nbsp;&nbsp;&nbsp;&nbsp; Fecha &nbsp;&nbsp;&nbsp;&nbsp; |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **Inicio** | `G2_PAQUETE_1_SCRIPT01_BASEINET_QA_CLOUD`<br/>`_OPTIMIZACIONES_MCD_ScValidateCuenta`<br/>`_CdGetCustomerNotices_ScDoIniciarSesion`<br/>`_ScDoFinalizarSesion_INICIO_LOGIN-LOGOUT.jmx` | Estrés de<br/>Sesión | `ScValidateCuenta`,<br/>`CdGetCustomerNotices`,<br/>`ScDoIniciarSesion`,<br/>`ScDoFinalizarSesion` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |
| **Cuentas<br/>Digitales** | `G2_PAQUETE_1_SCRIPT05_BASEINET_QA_CLOUD`<br/>`_OPTIMIZACIONES_MCD_CdGetDestinatarios`<br/>`AutorizadosPageInDB.jmx` | Consulta de<br/>Destinatarios DB | `CdGetDestinatarios`<br/>`AutorizadosPageInDB` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |
| **Cuentas<br/>Digitales** | `G2_PAQUETE_1_SCRIPT06_BASEINET_QA_CLOUD`<br/>`_OPTIMIZACIONES_MCD_CdGetTraspasos`<br/>`Comprobantes.jmx` | Consulta de<br/>Comprobantes | `CdGetTraspasos`<br/>`Comprobantes` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |
| **Cuentas<br/>Digitales** | `G2_PAQUETE_1_SCRIPT09_BASEINET_QA_CLOUD`<br/>`_OPTIMIZACIONES_MCD_CdGetCuentas`<br/>`Traspasos.jmx` | Consulta Cuentas<br/>p/Traspasos | `CdGetCuentas`<br/>`Traspasos` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |
| **Cuentas<br/>Digitales** | `G2_PAQUETE_1_SCRIPT15_BASEINET_QA_CLOUD`<br/>`_OPTIMIZACIONES_MCD_CdLoadArchivo`<br/>`LoteBase64_DISPERSION.jmx` | Carga Lotes<br/>Base64 | `CdLoadArchivo`<br/>`LoteBase64` | `usuarios_backend_`<br/>`baseinet_Dispersion.csv` | | |
| **Cuentas<br/>Digitales** | `G2_PAQUETE_2_SCRIPT05_BASEINET_QA_CLOUD`<br/>`_OPTIMIZACIONES_MCD_CdAddDestinatario`<br/>`_DESTINATARIOS_ALTA_MASIVA.jmx` | Alta Masiva de<br/>Destinatarios | `CdAddDestinatario` | `usuarios_backend_`<br/>`baseinet_Dispersion.csv` | | |
| **Autorizaciones** | `G2_PAQUETE_1_BASEINET_CLOUD_MDC__CdDo`<br/>`AutorizarTraspaso_CdGetTraspasos_SPEI_`<br/>`TRANSFER_AUTORIZACIONES.jmx` | Autorización<br/>SPEI | `CdDoAutorizarTraspaso`,<br/>`CdGetTraspasos` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |
| **Consultas** | `G2_PAQUETE_1_BASEINET_BASEINET_SCRIPT06_`<br/>`QA_CLOUD_MCD_CdGetMovimientos_DESTIND`<br/>`IVIDUAL_CONSULTA_MOVIMIENTOS.jmx` | Movimientos<br/>MCD | `CdGetMovimientos` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |
| **Consultas** | `G2_PAQUETE_1_BASEINET_CLOUD_DRP_MDC_`<br/>`CdGetEstadoCuentaPdf_CdGetEstadoCuenta`<br/>`Mt940Commando_CdGetMovimientos_`<br/>`DESCARGAR_EDO-CUENTA.jmx` | EDO-Cuenta /<br/>Movimientos | `CdGetEstadoCuentaPdf`,<br/>`CdGetEstadoCuentaMt940`,<br/>`CdGetMovimientos` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |
| **PF Web** | `G2_PAQUETE_1_SCRIPT06_BASEINET_QA_CLOUD`<br/>`_OPTIMIZACIONES_MCD_CdGetCuentas.jmx` | Consulta de<br/>Cuentas PF | `CdGetCuentas` | `usuarios_backend_`<br/>`baseinet_1800.csv` | | |

---

## ⚙️ Configuración Sugerida (Thread Group)

Se recomienda utilizar el **Stepping Thread Group**:
- **Ramp-up**: 1 usuario cada 5-10 segundos.
- **Duration**: 30 a 60 minutos de carga constante.

---
*Nota: Esta matriz contempla los 10 scripts de los Paquetes 1 y 2 dentro del módulo de Optimizaciones.*
