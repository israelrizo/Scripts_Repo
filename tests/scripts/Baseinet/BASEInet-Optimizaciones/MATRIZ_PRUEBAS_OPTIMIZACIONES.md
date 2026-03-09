# Matriz de Casos de Prueba - Módulo de Optimizaciones (MCD)

Esta matriz detalla los scripts de JMeter para el módulo de **Optimizaciones (MCD)**, diseñados para alta concurrencia y microservicios específicos.

## 📊 Resumen de Scripts

| Submódulo | Script | Objetivo de Negocio | Datos Req. (CSV) |
| :--- | :--- | :--- | :--- |
| **Inicio** | `G2_PAQUETE_1_SCRIPT01_..._INICIO_LOGIN-LOGOUT.jmx` | Pruebas de estrés de sesión (Validación, Inicio y Cierre). | `usuarios_backend_baseinet_1800.csv` |
| **Cuentas Digitales** | `G2_PAQUETE_1_SCRIPT06_..._CdGetTraspasosComprobantes.jmx` | Consulta de comprobantes de traspasos realizados. | `usuarios_backend_baseinet_1800.csv` |
| **Cuentas Digitales** | `G2_PAQUETE_1_SCRIPT15_..._CdLoadArchivoLoteBase64_DISPERSION.jmx` | Carga masiva de archivos para dispersiones en Base64. | `usuarios_backend_baseinet_Dispersion.csv` |
| **Cuentas Digitales** | `G2_PAQUETE_2_SCRIPT05_..._CdAddDestinatario_DESTINATARIOS_ALTA_MASIVA.jmx` | Alta masiva de nuevos destinatarios en el sistema. | `usuarios_backend_baseinet_agosto25.csv` |
| **Modulo Autorizaciones** | `G2_PAQUETE_1_..._CdDoAutorizarTraspaso_SPEI_TRANSFER_AUTORIZACIONES.jmx` | Autorización de transferencias SPEI pendientes. | `usuarios_backend_baseinet_1800.csv` |
| **Modulo Consultas** | `G2_PAQUETE_1_..._CdGetMovimientos_CONSULTA_MOVIMIENTOS.jmx` | Consulta optimizada de movimientos de cuenta. | `usuarios_backend_baseinet_1800.csv` |
| **Modulo Consultas** | `G2_PAQUETE_1_..._CdGetEstadoCuentaPdf_DESCARGAR_EDO-CUENTA.jmx` | Consulta y descarga de estados de cuenta (PDF/MT940). | `usuarios_backend_baseinet_1800.csv` |
| **PF Web** | `G2_PAQUETE_1_..._CdGetCuentas.jmx` | Consulta de cuentas vinculadas para personas físicas. | `usuarios_backend_baseinet_1800.csv` |

---

## ⚙️ Configuración Sugerida (Thread Group)

Para estos scripts de optimización, se recomienda utilizar el **Stepping Thread Group** o el **Ultimate Thread Group** con los siguientes parámetros base:

- **Target Level**: Según el objetivo de la prueba (Load/Stress).
- **Ramp-up**: 1 usuario cada 5 segundos (gradual).
- **Duration**: 30-60 minutos de estado estable.

## 📁 Ubicación de Archivos
- **Scripts**: `tests/scripts/Baseinet/BASEInet-Optimizaciones/`
- **Datos**: `data/`

---
*Nota: Esta matriz fue generada automáticamente basada en el análisis del repositorio `Scripts_Repo`.*
