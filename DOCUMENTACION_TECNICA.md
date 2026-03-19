# DOCUMENTACIÓN TÉCNICA — Framework de Pruebas de Rendimiento
# JMeter · Banca Cloud Baseinet
**Repositorio:** `israelrizo/Scripts_Repo`
**Última actualización:** Marzo 2026
**Autores:** Israel Lopez · Carlos Cervantes

---

# TABLA DE CONTENIDOS

1. Descripción General
2. Arquitectura del Framework
3. Estructura del Repositorio
4. Datos de Entrada (CSV)
5. Módulos de Scripts — Detalle Completo
   - 5.1 BASEInet-Login
   - 5.2 BASEInet-EstadoDeCuenta
   - 5.3 BASEInet-DispersionesCRUD
   - 5.4 BASEInet-Optimizaciones
     - Inicio (Script01)
     - Autorizaciones (Script02)
     - Cuentas Digitales (Scripts 05, 06, 09, 15)
     - Modulo Consultas (Scripts 06B, 08)
     - PF Web (Script06)
     - Suite General DRP (METODOS_GENERAL)
6. Componentes Técnicos del Test Plan
7. Endpoints del Sistema Bajo Prueba
8. Guía de Ejecución — Local
9. Guía de Ejecución — AWS EC2 Ubuntu
10. Convención de Nombres
11. Flujo de Contribución
12. Glosario
13. Matriz de Casos de Prueba — Optimizaciones

---

# 1. DESCRIPCIÓN GENERAL

El repositorio **Scripts_Repo** es el repositorio centralizado de pruebas de rendimiento para la plataforma **Banca Cloud Baseinet**, implementado con **Apache JMeter**. Los scripts simulan flujos reales de usuarios bancarios para evaluar:

- **Estabilidad** de los servicios bajo carga sostenida
- **Capacidad máxima** de usuarios concurrentes que el sistema soporta
- **Tiempos de respuesta** de los microservicios del backend
- **Comportamiento bajo estrés** de funciones críticas como Login, Dispersiones y Autorizaciones SPEI

El framework cubre dos ambientes principales:
- **DRP / Producción**: `web-cloud.baseinet.com`
- **QA / Cloud MCD**: `qa.baseinet.com`

---

# 2. ARQUITECTURA DEL FRAMEWORK

```
┌─────────────────────────────────────────────────────────────┐
│                      GITHUB REPOSITORY                      │
│  israelrizo/Scripts_Repo · main branch                      │
│  ┌────────────────────────┐  ┌──────────────────────────┐  │
│  │ tests/scripts/Baseinet │  │ data/                    │  │
│  │ 21 scripts .jmx        │  │ usuarios_1800.csv        │  │
│  │ 4 módulos principales  │  │ usuarios_Dispersion.csv  │  │
│  └────────────────────────┘  └──────────────────────────┘  │
└───────────────────────┬─────────────────────────────────────┘
                        │ wget raw URL
                        ▼
┌─────────────────────────────────────────────────────────────┐
│            AWS EC2 · Ubuntu 22.04 (Load Generator)         │
│  /mnt/jmeter/JMeter_Scripts/Volume/                         │
│                                                             │
│  Pre-requisitos:                                            │
│  • Java ≥ 11 (OpenJDK)                                      │
│  • Apache JMeter ≥ 5.5                                      │
│  • JMeter Plugins Manager (Stepping Thread Group)           │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               TEST PLAN (.jmx)                       │   │
│  │                                                      │   │
│  │  [Configuración Global]                              │   │
│  │   HTTP Header · DNS Cache · Cookie · Auth Manager   │   │
│  │          ↓                                           │   │
│  │  [Stepping Thread Group]                             │   │
│  │   Ramp-up: 1 user/5-10s · Duration: 30-60min       │   │
│  │          ↓                                           │   │
│  │  [CSV Data Set] ←── usuarios_backend_*.csv          │   │
│  │          ↓                                           │   │
│  │  [JSR223 Groovy PreProcessor]                        │   │
│  │   • Genera P_Request_ID                              │   │
│  │   • JWT Bearer Token (extracción/inyección)          │   │
│  │   • Encoding SHA / Base64                            │   │
│  │          ↓                                           │   │
│  │  [Módulos de Prueba]                                 │   │
│  │   Script01 → Script02 → Script03 → ... → Script09   │   │
│  │          ↓                                           │   │
│  │  [Validaciones: Assertions · Extractors · Timers]   │   │
│  │          ↓                                           │   │
│  │  [Resultados: .jtl · HTML · InfluxDB · ErrorLog]    │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTPS + JWT Bearer Token
            ┌───────────┴────────────┐
            ▼                        ▼
┌───────────────────┐   ┌──────────────────────┐
│ web-cloud.        │   │ qa.baseinet.com       │
│ baseinet.com      │   │ (QA / Cloud MCD)      │
│ (DRP / Cloud)     │   │                       │
└───────────────────┘   └──────────────────────┘
```

---

# 3. ESTRUCTURA DEL REPOSITORIO

```
Scripts_Repo/
│
├── README.md                              ← Documentación principal
├── .gitignore                             ← Exclusiones de Git
│
├── .github/
│   └── pull_request_template.md          ← Template para Pull Requests
│
├── data/                                  ← Archivos de datos de entrada
│   ├── usuarios_backend_baseinet_1800.csv         (258 KB)
│   ├── usuarios_backend_baseinet_Dispersion.csv   (284 B)
│   ├── usuarios_backend_baseinet_Dispersion_Enero2026.csv
│   ├── usuarios_backend_baseinet_Dispersion_feguerra.csv
│   ├── usuarios_backend_baseinet_agosto25.csv     (173 KB)
│   └── sample*.txt                               (archivos de muestra)
│
├── results/                               ← Resultados de ejecuciones
│   └── [resultado_DDMMYY.jtl + Report_DDMMYY/]
│
└── tests/
    └── scripts/
        └── Baseinet/
            ├── BASEInet-Login/            ← 3 scripts · Autenticación
            ├── BASEInet-EstadoDeCuenta/   ← 1 script  · Consultas
            ├── BASEInet-DispersionesCRUD/ ← 6 scripts · Dispersiones
            └── BASEInet-Optimizaciones/   ← 11 scripts · MCD
                ├── G2_PAQUETE_1_BASEINET_DRP_METODOS_GENERAL.jmx  ⭐
                ├── MATRIZ_PRUEBAS_OPTIMIZACIONES.md
                ├── Inicio/
                ├── Cuentas Digitales/
                ├── Modulo Autorizaciones/
                ├── Modulo Consultas/
                └── PF Web/
```

**Total de scripts JMX: 21 archivos**

---

# 4. DATOS DE ENTRADA (CSV)

| Archivo | Tamaño | Uso |
|---|---|---|
| `usuarios_backend_baseinet_1800.csv` | 258 KB | Credenciales y cuentas para flujos de sesión (~1800 usuarios) |
| `usuarios_backend_baseinet_Dispersion.csv` | 284 B | Datos para flujos de dispersión de pagos (lotes) |
| `usuarios_backend_baseinet_Dispersion_Enero2026.csv` | 606 B | Dispersiones - actualización enero 2026 |
| `usuarios_backend_baseinet_Dispersion_feguerra.csv` | 285 B | Dispersiones - usuario específico |
| `usuarios_backend_baseinet_agosto25.csv` | 173 KB | Sesiones - corte agosto 2025 |
| `sample*.txt` | ~1-2 KB | Muestras de referencia por cliente |

> **Nota de seguridad**: Los archivos CSV contienen credenciales de ambientes de prueba. Nunca incluir credenciales de producción real en el repositorio.

Los scripts utilizan **rutas relativas** desde la raíz del repositorio, por lo que es necesario ejecutar JMeter desde ese nivel.

---

# 5. MÓDULOS DE SCRIPTS — DETALLE COMPLETO

---

## 5.1 BASEInet-Login — Autenticación

Módulo de pruebas de carga para el proceso de autenticación en distintos ambientes.

### Inventario de Scripts

| # | Archivo | Ambiente | Tamaño |
|---|---|---|---|
| 1 | `G1_BASEINET_CLOUD_LOGIN_STG_v7.jmx` | STG (Staging) | 1.9 MB |
| 2 | `G1_BASEINET_CLOUD_LOGIN_UTG_v7.jmx` | UTG (User Testing) | 1.9 MB |
| 3 | `G1_SIL_LOGIN_v1.jmx` | SIL | 904 KB |

### Descripción
Estos scripts realizan pruebas de estrés del flujo completo de autenticación, incluyendo:
- Apertura de página de inicio
- Validación de usuario
- Desbloqueo si es necesario
- Autenticación con token OTP/2FA
- Cierre de sesión

---

## 5.2 BASEInet-EstadoDeCuenta — Consultas

| # | Archivo | Tamaño |
|---|---|---|
| 1 | `G1_BASEINET_CLOUD_LOGIN_MOV_EDO-CUENTA_v7.jmx` | 1.2 MB |

### Descripción
Flujo completo que combina autenticación con operaciones de consulta:

| Transacción | Descripción |
|---|---|
| T01 — Login / AbrirPágina | Acceso a la plataforma Baseinet |
| T02 — ValidarUsuario | Validación de credenciales backend |
| T03 — DesbloquearUsuario | Desbloqueo de token si aplica |
| T04 — AutenticarConToken | Autenticación con OTP |
| T05 — ConsultarMovimientos_AbrirPágina | Navegar a sección de movimientos |
| T06 — ConsultarMovimientos_SeleccionarCuenta | Selección de cuenta a consultar |
| T07 — ConsultarEstadosDeCuenta | Consulta de EDO-Cuenta |
| T08 — DescargarEstadoDeCuenta | Descarga del estado de cuenta (PDF/MT940) |
| T09 — CerrarSesión | Logout del sistema |

---

## 5.3 BASEInet-DispersionesCRUD — Dispersiones y Destinatarios

### Inventario de Scripts

| # | Archivo | Descripción | Tamaño |
|---|---|---|---|
| 1 | `G2_BASEINET_QA_CLOUD_DISPERSIONES_V1.jmx` | Dispersiones Cloud QA — versión 1 | 360 KB |
| 2 | `G2_BASEINET_QA_CLOUD_DISPERSIONES_V2.jmx` | Dispersiones Cloud QA — versión 2 | 360 KB |
| 3 | `G2_BASEINET_QA_CLOUD_DISPERSIONES_V3.jmx` | Dispersiones Cloud QA — versión 3 | 360 KB |
| 4 | `G2_BASEINET_QA_CLOUD_DISPERSIONES_TC_V4.jmx` | Dispersiones con Thread Config V4 | 292 KB |
| 5 | `G2_BASEINET_DRP_CLOUD_DISPERSIONES_TC_V1.jmx` | Dispersiones DRP Cloud | 272 KB |
| 6 | `G2_BASEINET_BASEINET_SCRIPT04_QA_CLOUD_DESTINDIVIDUAL_CRUD.jmx` | CRUD Destinatarios individuales | 1.2 MB |

### Descripción
Scripts para operaciones de negocio relacionadas con el envío masivo de pagos (dispersiones) y la administración de cuentas destino (destinatarios). Cubren el ciclo completo: carga, autorización, validación y consulta de lotes.

---

## 5.4 BASEInet-Optimizaciones — Módulo MCD

Módulo de scripts optimizados para alta concurrencia, orientados al testing de microservicios específicos del backend MCD. Todos usan **Stepping Thread Group** para control preciso de concurrencia.

---

### SCRIPT01 — Inicio / Login-Logout
**Archivo:** `G2_PAQUETE_1_SCRIPT01_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_ScValidateCuenta_CdGetCustomerNotices_ScDoIniciarSesion_ScDoFinalizarSesion_INICIO_LOGIN-LOGOUT.jmx`
**Tamaño:** 272 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Prueba de estrés del ciclo completo de sesión de usuario.

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `CdGetCustomerNotices` | Carga inicial de la plataforma y avisos |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación de cuenta de usuario |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Autenticación con credenciales + token |
| T04 — CerrarSesión | `ScDoFinalizarSesion` | Logout y limpieza de sesión |

**Endpoints principales:**
- `POST /api/parameter`
- `POST /api/process/P00S000_VALIDAR_PAGINA`
- `POST /api/process/P01S000_OBTENER_DATOS`
- `POST /api/process/P01S000_VALIDA_VENCIMIENTO_TOKEN`
- `POST /api/process/P01S005_TOKEN_VENCIDO`

---

### SCRIPT02 — Autorizaciones SPEI
**Archivo:** `G2_PAQUETE_1_BASEINET_CLOUD_MDC__CdDoAutorizarTraspaso_CdGetTraspasos_SPEI_TRANSFER_AUTORIZACIONES.jmx`
**Tamaño:** 644 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Prueba del flujo de autorización de transferencias SPEI / traspasos entre cuentas.

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `—` | Acceso inicial a la plataforma |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación de credenciales |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Login con token de autenticación |
| T04 — ClickTransferencia | `—` | Navegar a módulo de transferencias |
| T05 — BúsquedaDestinatario | `CdGetTraspasos` | Búsqueda del destinatario del traspaso |
| T06 — ClickContinuar | `CdDoAutorizarTraspaso` | Primera confirmación del traspaso |
| T07 — ClickConfirmar | `CdDoAutorizarTraspaso` | Confirmación final y envío |
| T08 — ClickTraspasos | `CdGetTraspasos` | Verificación del estado del traspaso |
| T09 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

**Endpoints principales:**
- `POST /api/process/P03S312` — Consultar traspasos
- `POST /api/process/P03S312_AUTORIZAR`
- `POST /api/process/P03S312_CONSULTAR`
- `POST /api/process/P03S312_VALIDAR_CONFIRMAR`

---

### SCRIPT05 — Destinatarios (Cuentas Digitales)
**Archivo:** `G2_PAQUETE_1_SCRIPT05_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_CdGetDestinatariosAutorizadosPageInDB.jmx`
**Tamaño:** 312 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Prueba del flujo CRUD de destinatarios autorizados, incluyendo alta, validación y eliminación.

| Transacción | Servicios | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `—` | Acceso inicial |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación de credenciales |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Login |
| T04 — ClickDestinatariosOtrosBancos | `CdGetDestinatariosAutorizadosPageInDB` | Navegar a catálogo de destinatarios |
| T05 — IngresaDatos | `CdAddDestinatario` | Captura de datos del nuevo destinatario |
| VerificaCuentaNoRegistrada | `—` | Verificación que la cuenta no existe |
| T06 — AutorizarAlta | `—` | Autorización del alta de destinatario |
| T07 — ClickAdministración | `—` | Navegar a sección de administración |
| T09 — ValidarPaginación | `P03S250_NEXT_PAG / PREV_PAG` | Verificación de paginación |
| T10 — EliminarAlta | `P03S250_ELIMINAR` | Eliminación del destinatario creado |
| T11 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

**Endpoints principales:**
- `POST /api/process/P03S250` — Gestión de destinatarios
- `POST /api/process/P03S250_NEXT_PAG / PREV_PAG`
- `POST /api/process/P03S250_ELIMINAR`

---

### SCRIPT06 — Comprobantes (Cuentas Digitales)
**Archivo:** `G2_PAQUETE_1_SCRIPT06_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_CdGetTraspasosComprobantes.jmx`
**Tamaño:** 388 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Prueba del módulo de consulta de comprobantes filtrando por múltiples tipos de operación.

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `—` | Acceso inicial |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Login |
| T04 — ClickComprobantes | `CdGetTraspasosComprobantes` | Navegar a comprobantes |
| T05 — FiltroTransferencias | `—` | Filtro por transferencias SPEI |
| T06 — FiltroPagoDeServicios | `—` | Filtro por pago de servicios |
| T07 — FiltroPagoImpuestos | `—` | Filtro por pago de impuestos |
| T08 — FiltroRecargas | `—` | Filtro por recargas |
| T09 — FiltroDispersionPagos | `—` | Filtro por dispersión de pagos |
| T10 — FiltroSIPARE | `—` | Filtro por SIPARE |
| T11 — FiltroPECE | `—` | Filtro por PECE |
| T12 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

---

### SCRIPT09 — Cuentas para Traspasos (Cuentas Digitales)
**Archivo:** `G2_PAQUETE_1_SCRIPT09_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_CdGetCuentasTraspasos.jmx`
**Tamaño:** 312 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Consulta de cuentas disponibles para realizar traspasos entre bancos.

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `—` | Acceso inicial |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Login |
| T04 — ClickTransferenciasBancoBASE | `CdGetCuentasTraspasos` | Navegar a transferencias BancoBASE |
| T05 — CapturaTransferenciaBancoBASE | `—` | Captura de datos de la transferencia |
| T06 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

---

### SCRIPT15 — Carga de Dispersiones Base64 (Cuentas Digitales)
**Archivo:** `G2_PAQUETE_1_SCRIPT15_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_CdLoadArchivoLoteBase64_DISPERSION.jmx`
**Tamaño:** 444 KB | **Datos:** `usuarios_backend_baseinet_Dispersion.csv`
**Objetivo:** Prueba de carga y autorización de lotes de dispersión en formato Base64.

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `—` | Acceso inicial |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Login |
| T04 — ClickDispersiones | `—` | Navegar al módulo de dispersiones |
| T05 — CargarDispersión | `CdLoadArchivoLoteBase64` | Carga del archivo lote en Base64 |
| T06 — AutorizarDispersión | Autorizar Alta | Autorización del lote cargado |
| T07 — ClickDetalleDispersión | `—` | Consulta del detalle del lote |
| T08 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

**Endpoints principales:**
- `POST /api/process/P03S480` — Dispersiones
- `POST /api/process/P03S480_CARGAR`
- `POST /api/process/P03S480_CONF`
- `POST /api/process/P03S485`

---

### SCRIPT06B — Consulta de Movimientos MCD
**Archivo:** `G2_PAQUETE_1_BASEINET_BASEINET_SCRIPT06_QA_CLOUD_MCD_CdGetMovimientos_DESTINDIVIDUAL_CONSULTA_MOVIMIENTOS.jmx`
**Tamaño:** 644 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Prueba de la consulta de movimientos por cuenta, incluyendo paginación.

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `—` | Acceso inicial |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Login |
| T04 — ClickConsultaMovimientos | `CdGetMovimientos` | Navegar a consulta de movimientos |
| T05 — ValidarPaginación | `P03S150 / NEXT_PAG / PREV_PAG` | Verificación de paginación |
| T06 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

**Endpoints principales:**
- `POST /api/process/P03S150` — Consulta de movimientos
- `POST /api/process/P03S150_CONS_MOVIMIENTOS`

---

### SCRIPT08 — Estado de Cuenta / PDF / MT940 (Modulo Consultas)
**Archivo:** `G2_PAQUETE_1_BASEINET_CLOUD_DRP_MDC_CdGetEstadoCuentaPdf_CdGetEstadoCuentaMt940Commando_CdGetMovimientos_DESCARGAR_EDO-CUENTA.jmx`
**Tamaño:** 680 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Prueba de los 3 formatos de estado de cuenta: consulta de movimientos, descarga en PDF y descarga en MT940.

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — Login / AbrirPágina | `—` | Acceso inicial |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación |
| T03 — IniciarSesión | `ScDoIniciarSesion` | Login con token |
| T02B — ConsultarMovimientos | — | P01 AbrirPáginaMovimientos |
| — | — | P02 SeleccionarCuenta |
| T03B — ConsultarEstadosDeCuenta | `CdGetEstadoCuentaPdf` | Solicitud del EDO-Cuenta en PDF |
| T04B — DescargarEstadoDeCuenta | `CdGetEstadoCuentaMt940` | Descarga en formato MT940 (SWIFT) |
| T09 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

**Endpoints principales:**
- `POST /api/process/P03S150_CONS_MOVIMIENTOS`
- Descarga PDF Estado de Cuenta
- Descarga MT940 Commando

---

### SCRIPT06 PF Web — Consulta de Cuentas (PF Web)
**Archivo:** `G2_PAQUETE_1_SCRIPT06_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_CdGetCuentas.jmx`
**Tamaño:** 312 KB | **Datos:** `usuarios_backend_baseinet_1800.csv`
**Objetivo:** Consulta de cuentas disponibles en el módulo de Personas Físicas (PF Web).

| Transacción | Servicio | Descripción |
|---|---|---|
| T01 — AbrirPáginaDeInicio | `—` | Acceso inicial |
| T02 — ValidarUsuario | `ScValidateCuenta` | Validación |
| T03 — IniciarSesión_Autenticar | `ScDoIniciarSesion` | Login |
| T04 — ConsultarCuentas | `CdGetCuentas` | Consulta del listado de cuentas PF |
| T05 — CerrarSesión | `ScDoFinalizarSesion` | Logout |

---

### ⭐ METODOS_GENERAL — Suite DRP Integrada
**Archivo:** `G2_PAQUETE_1_BASEINET_DRP_METODOS_GENERAL.jmx`
**Tamaño:** 640 KB | **Datos:** `usuarios_backend_baseinet_1800.csv` + `usuarios_backend_baseinet_Dispersion.csv`
**Objetivo:** Plan de prueba integral que agrupa los flujos de los Scripts 01 al 09 en un único archivo para ejecución DRP.

Este es el script principal para pruebas de regresión completa del ambiente DRP. Incluye:
- Script01: Inicio / Login-Logout
- Script02: Autorizaciones SPEI
- Script03: Dispersiones CRUD
- Script05: Destinatarios
- Script06: Comprobantes
- Script06B: Movimientos
- Script08: EDO-Cuenta / PDF
- Script09: Cuentas Traspasos
- Controlador de Throughput para 900+ dispersiones

---

# 6. COMPONENTES TÉCNICOS DEL TEST PLAN

Cada script `.jmx` comparte la siguiente arquitectura interna:

## 6.1 Configuración Global

| Componente | Propósito |
|---|---|
| **HTTP Header Manager** | Define los headers globales: `Content-Type: application/json`, `Authorization: Bearer {token}`, `Referer` |
| **DNS Cache Manager** | Optimiza la resolución DNS bajo alta carga, evita re-resolución por hilo |
| **HTTP Cookie Manager** | Gestión automática de cookies de sesión entre requests |
| **HTTP Cache Manager** | Control de caché HTTP, simula comportamiento real del navegador |
| **HTTP Authorization Manager** | Manejo centralizado de credenciales de autenticación HTTP |

## 6.2 Control de Concurrencia

| Componente | Configuración | Descripción |
|---|---|---|
| **Stepping Thread Group** | 1 user / 5-10 s | Plugin de JMeter para ramp-up escalonado y controlado |
| **Loop Controller** | Loops: -1 (∞) | Ejecución continua hasta timeout o interrupción manual |
| **Synchronizing Timer** | Configurable | Sincroniza hilos para simular ráfagas de usuarios simultáneos |
| **Throughput Controller** | +900 dispersiones | Control de throughput específico para flujos de dispersión |

## 6.3 Gestión de Datos

| Componente | Archivo | Descripción |
|---|---|---|
| **CSV Data Set** | `usuarios_backend_baseinet_1800.csv` | Alimenta usuario, contraseña y cuenta por hilo virtual |
| **CSV Data Set** | `usuarios_backend_baseinet_Dispersion.csv` | Alimenta datos de lote de dispersión |

## 6.4 Pre-procesadores (Groovy / JSR223)

```groovy
// JSR223 PreProcessor — P_Request_ID
// Genera un ID único por request para correlación
import java.security.MessageDigest;
import java.util.Base64;
// Genera hash SHA de la URL del sampler actual
// y lo expone como variable P_Request_ID
```

Funciones implementadas:
- **P_Request_ID**: Identificador único por transacción (SHA + Base64)
- **C_JWT_KEY**: Extracción y reutilización del token JWT entre requests
- **C_SYNCHRONIZATION_KEY**: Clave de sincronización de sesión
- **C_THEME**: Tema visual extraído de la respuesta inicial

## 6.5 Extractores y Correlación

| Extractor | Variable | Fuente |
|---|---|---|
| **RegexExtractor** | `C_JWT_KEY` | Header `Authorization` de la respuesta de login |
| **JSONPostProcessor** | `C_Synchronization_Key` | Body JSON de `/api/parameter` |
| **RegexExtractor** | `C_THEME` | Response body de `/api/view/{ver}/V01` |
| **BoundaryExtractor** | `C_JWT_KEY` (alt) | Alternativa cuando Regex no aplica |

## 6.6 Validaciones

| Componente | Uso |
|---|---|
| **Response Assertion** | Verifica código HTTP 200, ausencia de errores 5xx |
| **Validar respuesta de error - 200 Servicio no disponible** | Detecta respuestas HTTP 200 que contienen mensajes de error en el body |

## 6.7 Timers

| Timer | Propósito |
|---|---|
| **Uniform Random Timer** | Tiempo de espera variable entre transacciones (comportamiento humano realista) |
| **Think Time** | Pausa estándar entre pasos del flujo |
| **Synchronizing Timer** | Barrera de sincronización para simular picos de carga simultánea |

## 6.8 Listeners y Resultados

| Listener | Formato | Descripción |
|---|---|---|
| **Simple Data Writer** | `.jtl` | Escritura de resultados crudos en formato JMeter |
| **ResultCollector (errors)** | `.jtl` | Log dedicado únicamente a errores (`error_logging: true`) |
| **Backend Listener → InfluxDB** | HTTP | Streaming de métricas en tiempo real hacia InfluxDB |
| **View Results Tree** | GUI | Solo para debugging (deshabilitado en producción) |
| **Debug Sampler** | GUI | Solo para debugging (deshabilitado en producción) |

---

# 7. ENDPOINTS DEL SISTEMA BAJO PRUEBA

## 7.1 web-cloud.baseinet.com (DRP / Producción Cloud)

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/parameter` | POST | Parámetros iniciales y clave de sincronización |
| `/api/initialData` | POST | Datos de inicialización de la aplicación |
| `/api/ping` | GET | Health check del backend |
| `/api/view/{version}/V01` | POST | Vista de login |
| `/api/view/{version}/V01/contents1/S005` | POST | Contenido de pantalla de inicio |
| `/api/view/{version}/V03/contents1/S150` | POST | Vista de movimientos |
| `/api/view/{version}/V03/contents1/S160` | POST | Vista de autorización |
| `/api/view/{version}/V03/contents1/S230` | POST | Vista adicional |
| `/api/view/{version}/V03/contents1/S312` | POST | Vista de transferencias SPEI |
| `/api/view/{version}/V03/contents1/S313` | POST | Vista de confirmación |
| `/api/view/{version}/V03/contents1/S314` | POST | Vista de resultado |
| `/api/view/{version}/V03/contents1/S480` | POST | Vista de dispersiones |
| `/api/view/{version}/V03/contents1/S485` | POST | Vista de detalle dispersión |
| `/api/view/{version}/V03/footer:S000;...` | POST | Vista completa con footer |
| `/api/process/P00S000_VALIDAR_PAGINA` | POST | Validación inicial de página |
| `/api/process/P01S000_OBTENER_DATOS` | POST | Obtención de datos del usuario |
| `/api/process/P01S000_VALIDA_VENCIMIENTO_TOKEN` | POST | Validación de vigencia del JWT |
| `/api/process/P01S005_TOKEN_VENCIDO` | POST | Renovación de token vencido |
| `/api/process/P03S005_GUARDAR_BITACORA` | POST | Registro de actividad en bitácora |
| `/api/process/P03S150_CONS_MOVIMIENTOS` | POST | Consulta de movimientos de cuenta |
| `/api/process/P_VALIDA_GEOLOCATION_INDEX` | POST | Validación de geolocalización |
| `/api/process/P_AVISOS_SWIPE` | POST | Avisos tipo swipe |
| `/api/resources/{version}/scriptgeo2` | GET | Recurso de geolocalización |
| `/api/static/dictionary/{version}/es` | GET | Diccionario de textos en español |
| `/api/themes/custom/{version}/{theme}` | GET | Tema visual personalizado |
| `/api/storage/current-storage` | GET | Configuración de almacenamiento de sesión |

## 7.2 qa.baseinet.com (QA / Cloud MCD)

| Endpoint | Método | Descripción |
|---|---|---|
| `/api/process/P03S150` | POST | Consulta de movimientos MCD |
| `/api/process/P03S160` | POST | Autorización de operación |
| `/api/process/P03S250` | POST | Gestión de destinatarios |
| `/api/process/P03S250_NEXT_PAG` | POST | Siguiente página de destinatarios |
| `/api/process/P03S250_PREV_PAG` | POST | Página anterior de destinatarios |
| `/api/process/P03S250_ELIMINAR` | POST | Eliminar destinatario |
| `/api/process/P03S312` | POST | Consulta de traspasos SPEI |
| `/api/process/P03S312_AUTORIZAR` | POST | Autorizar traspaso SPEI |
| `/api/process/P03S312_CONSULTAR` | POST | Consultar traspaso específico |
| `/api/process/P03S312_VALIDAR_CONFIRMAR` | POST | Confirmar traspaso SPEI |
| `/api/process/P03S480` | POST | Operaciones de dispersión |
| `/api/process/P03S480_CARGAR` | POST | Cargar lote de dispersión (Base64) |
| `/api/process/P03S480_CONF` | POST | Confirmar dispersión |
| `/api/process/P03S485` | POST | Detalle de dispersión |
| `/api/view/174/V03/contents1/S483` | POST | Vista de dispersión versión 174 |
| `/api/view/176/V03/contents1/S150` | POST | Vista de movimientos versión 176 |

---

# 8. GUÍA DE EJECUCIÓN — LOCAL

Para ejecutar correctamente los scripts, **JMeter debe iniciarse desde la raíz del repositorio** para que los datos CSV con rutas relativas sean encontrados.

```bash
# Clonar el repositorio
git clone https://github.com/israelrizo/Scripts_Repo.git
cd Scripts_Repo

# Ejecutar en modo No-GUI (recomendado para pruebas de carga)
jmeter -n \
  -t tests/scripts/Baseinet/BASEInet-Login/G1_BASEINET_CLOUD_LOGIN_STG_v7.jmx \
  -l results/resultado_$(date +%d%m%y).jtl \
  -e -o results/Report_$(date +%d%m%y)/
```

### Flags principales de JMeter

| Flag | Descripción |
|---|---|
| `-n` | Modo Non-GUI (headless) |
| `-t <archivo.jmx>` | Ruta al script de prueba |
| `-l <archivo.jtl>` | Ruta donde se guardan los resultados crudos |
| `-e` | Genera reporte HTML al finalizar |
| `-o <directorio>` | Directorio de salida del reporte HTML |

---

# 9. GUÍA DE EJECUCIÓN — AWS EC2 UBUNTU

## 9.1 Pre-requisitos del Servidor

```bash
# Actualizar paquetes del sistema
sudo apt-get update && sudo apt-get upgrade -y

# Instalar Java 11
sudo apt-get install -y openjdk-11-jdk

# Verificar instalación
java -version

# Descargar Apache JMeter (ajustar versión según disponibilidad)
wget https://downloads.apache.org/jmeter/binaries/apache-jmeter-5.6.3.tgz
tar -xzf apache-jmeter-5.6.3.tgz -C /mnt/jmeter/

# Instalar JMeter Plugins Manager
# Descargar jmeter-plugins-manager-1.x.jar en /mnt/jmeter/apache-jmeter-5.x/lib/ext/
```

## 9.2 Configuración de Límites del Sistema (Ubuntu)

```bash
# Aumentar límites de archivos abiertos para soporte de alta concurrencia
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf
ulimit -n 65536

# Confirmar
ulimit -n
```

## 9.3 Ejecución de la Prueba

```bash
# 1. Ingresar como superusuario
sudo su

# 2. Ir al directorio de trabajo
cd /mnt/jmeter/JMeter_Scripts/Volume

# 3. Descargar el script principal desde GitHub
wget -O G2_PAQUETE_1_BASEINET_DRP_METODOS_GENERAL.jmx \
  https://raw.githubusercontent.com/israelrizo/Scripts_Repo/refs/heads/main/tests/scripts/Baseinet/BASEInet-Optimizaciones/G2_PAQUETE_1_BASEINET_DRP_METODOS_GENERAL.jmx

# 4. Descargar datos CSV de sesiones
wget -O usuarios_backend_baseinet_1800.csv \
  https://raw.githubusercontent.com/israelrizo/Scripts_Repo/refs/heads/main/data/usuarios_backend_baseinet_1800.csv

# 5. Descargar datos CSV de dispersiones
wget -O usuarios_backend_baseinet_Dispersion.csv \
  https://raw.githubusercontent.com/israelrizo/Scripts_Repo/refs/heads/main/data/usuarios_backend_baseinet_Dispersion.csv

# 6. Ejecutar la prueba de carga
jmeter -n \
  -t G2_PAQUETE_1_BASEINET_DRP_METODOS_GENERAL.jmx \
  -l results/result_$(date +%d%m%y).jtl \
  -e -o results/Result_$(date +%d%m%y)

# 7. Verificar que los resultados se generaron correctamente
ls -lh results/
```

## 9.4 Configuración Sugerida de Carga

| Parámetro | Valor Sugerido | Descripción |
|---|---|---|
| **Thread Group** | Stepping Thread Group | Plugin para ramp-up escalonado |
| **Ramp-up inicial** | 1 usuario / 5 segundos | Inicio gradual para evitar picos |
| **Ramp-up agresivo** | 1 usuario / 10 segundos | Para pruebas de estrés más controladas |
| **Duración** | 30 a 60 minutos | Carga constante sostenida |
| **Loops** | Infinito (-1) | Hasta timeout manual o programado |
| **Usuarios máximos** | Según capacidad del servidor | Ajustar según objetivo de la prueba |

---

# 10. CONVENCIÓN DE NOMBRES

## Nomenclatura de Scripts

```
G<Grupo>_PAQUETE_<N>_<Sistema>_<Ambiente>_[SCRIPT<NN>_]<Metodos>_<Descripcion>.jmx
```

### Componentes

| Token | Descripción | Ejemplos |
|---|---|---|
| `G<Grupo>` | Grupo del script | `G1` (Login), `G2` (Operaciones) |
| `PAQUETE_<N>` | Número de paquete | `PAQUETE_1` (producción), `PAQUETE_2` (aux) |
| `<Sistema>` | Sistema o plataforma | `BASEINET`, `SIL` |
| `<Ambiente>` | Ambiente de prueba | `QA_CLOUD`, `DRP`, `STG`, `UTG` |
| `SCRIPT<NN>` | Número de script (opcional) | `SCRIPT01`, `SCRIPT05`, `SCRIPT15` |
| `<Metodos>` | Servicios o métodos probados | `CdGetMovimientos`, `ScDoIniciarSesion` |
| `<Descripcion>` | Descripción funcional en mayúsculas | `INICIO_LOGIN-LOGOUT`, `DESCARGAR_EDO-CUENTA` |

### Ejemplos

```
G1_BASEINET_CLOUD_LOGIN_STG_v7.jmx
G2_PAQUETE_1_SCRIPT01_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_ScValidateCuenta_CdGetCustomerNotices_ScDoIniciarSesion_ScDoFinalizarSesion_INICIO_LOGIN-LOGOUT.jmx
G2_PAQUETE_1_BASEINET_DRP_METODOS_GENERAL.jmx
```

---

# 11. FLUJO DE CONTRIBUCIÓN

## Proceso de Pull Request

1. **Crear rama descriptiva:**
   ```bash
   git checkout -b feature/nuevo-script-modulo-consultas
   # o
   git checkout -b fix/script01-timeout-autorizaciones
   ```

2. **Seguir la convención de nombres** (ver Sección 10)

3. **Actualizar documentación:**
   - Si es un script nuevo: agregar entrada a `MATRIZ_PRUEBAS_OPTIMIZACIONES.md`
   - Si modifica la arquitectura: actualizar `README.md`

4. **Abrir Pull Request** usando el template `.github/pull_request_template.md`

## Checklist del Pull Request

El template incluye (entre otros):
- [ ] Nombre del script sigue la convención establecida
- [ ] Script usa rutas relativas para los datos CSV
- [ ] Thread Group configurado con Stepping Thread Group
- [ ] Extractores de JWT/tokens funcionando
- [ ] Assertions activas y validando respuestas correctas
- [ ] Listeners de InfluxDB configurados
- [ ] No hay credenciales de producción en el script

---

# 12. GLOSARIO

| Término | Definición |
|---|---|
| **JMeter** | Herramienta de pruebas de rendimiento de Apache. Permite simular múltiples usuarios enviando peticiones HTTP. |
| **JMX** | Formato XML de los planes de prueba de JMeter (JMeter eXecutable) |
| **Thread Group** | Agrupación de hilos virtuales de JMeter. Cada hilo representa un usuario virtual. |
| **Stepping Thread Group** | Plugin de JMeter que permite un ramp-up escalonado y controlado |
| **Ramp-up** | Período de tiempo en el que se incrementa gradualmente el número de usuarios virtuales |
| **MCD** | Módulo de Cuentas Digitales de Baseinet |
| **DRP** | Disaster Recovery Plan — ambiente de producción en la nube |
| **CSV Data Set** | Componente de JMeter que lee datos de un archivo CSV para parametrizar las pruebas |
| **JSR223 / Groovy** | Lenguaje de scripting utilizado en los pre/post procesadores de JMeter |
| **JWT** | JSON Web Token — mecanismo de autenticación stateless usado por los APIs de Baseinet |
| **InfluxDB** | Base de datos de series temporales usada para almacenar métricas de JMeter en tiempo real |
| **Stepping** | Técnica de incremento escalonado de usuarios (1 cada N segundos) |
| **Think Time** | Tiempo de espera entre transacciones que simula el comportamiento humano real |
| **Sync Timer** | Temporizador que sincroniza N hilos antes de liberar las peticiones simultáneamente |
| **Throughput Controller** | Componente que controla la frecuencia de ejecución de un bloque de prueba |
| **SPEI** | Sistema de Pagos Electrónicos Interbancarios — sistema de transferencias en México |
| **MT940** | Formato SWIFT de estado de cuenta bancario electrónico |
| **SIPARE** | Sistema de Pago Referenciado — sistema del SAT para pago de impuestos |
| **PECE** | Plataforma de Pagos de Cuotas y Emisión electrónica |
| **P03S312** | Código de proceso interno de Baseinet para Autorizaciones SPEI |
| **P03S480** | Código de proceso interno de Baseinet para Dispersiones |
| **ScDoIniciarSesion** | Servicio de autenticación de Baseinet (inicio de sesión) |
| **CdGetMovimientos** | Servicio de consulta de movimientos de Cuentas Digitales |
| **CdLoadArchivoLoteBase64** | Servicio de carga de lotes de dispersión en formato Base64 |

---

# 13. MATRIZ DE CASOS DE PRUEBA — OPTIMIZACIONES

| # | Submódulo | Script | Objetivo | Servicios Impactados | Datos | Paquete |
|---|---|---|---|---|---|---|
| 1 | Inicio | Script01 `_INICIO_LOGIN-LOGOUT.jmx` | Estrés de Sesión | `ScValidateCuenta`, `CdGetCustomerNotices`, `ScDoIniciarSesion`, `ScDoFinalizarSesion` | `_1800.csv` | P1 |
| 2 | Cuentas Digitales | Script05 `_CdGetDestinatariosAutorizadosPageInDB.jmx` | Consulta Destinatarios DB | `CdGetDestinatariosAutorizadosPageInDB` | `_1800.csv` | P1 |
| 3 | Cuentas Digitales | Script06 `_CdGetTraspasosComprobantes.jmx` | Consulta Comprobantes | `CdGetTraspasosComprobantes` | `_1800.csv` | P1 |
| 4 | Cuentas Digitales | Script09 `_CdGetCuentasTraspasos.jmx` | Consulta Cuentas Traspasos | `CdGetCuentasTraspasos` | `_1800.csv` | P1 |
| 5 | Cuentas Digitales | Script15 `_CdLoadArchivoLoteBase64_DISPERSION.jmx` | Carga Lotes Base64 | `CdLoadArchivoLoteBase64` | `_Dispersion.csv` | P1 |
| 6 | Cuentas Digitales | Script05-P2 `_CdAddDestinatario_ALTA_MASIVA.jmx` | Alta Masiva Destinatarios | `CdAddDestinatario` | `_Dispersion.csv` | P2 (auxiliar) |
| 7 | Autorizaciones | `_CdDoAutorizarTraspaso_CdGetTraspasos_SPEI_AUTORIZACIONES.jmx` | Autorización SPEI | `CdDoAutorizarTraspaso`, `CdGetTraspasos` | `_1800.csv` | P1 |
| 8 | Consultas | Script06B `_CdGetMovimientos_CONSULTA_MOVIMIENTOS.jmx` | Movimientos MCD | `CdGetMovimientos` | `_1800.csv` | P1 |
| 9 | Consultas | `_CdGetEstadoCuentaPdf_CdGetEstadoCuentaMt940_DESCARGAR_EDO-CUENTA.jmx` | EDO-Cuenta / PDF / MT940 | `CdGetEstadoCuentaPdf`, `CdGetEstadoCuentaMt940`, `CdGetMovimientos` | `_1800.csv` | P1 |
| 10 | General DRP | `METODOS_GENERAL.jmx` | Suite Scripts 01→09 | Todos los servicios anteriores | `_1800.csv` + `_Dispersion.csv` | P1 |
| 11 | PF Web | Script06PF `_CdGetCuentas.jmx` | Consulta Cuentas PF | `CdGetCuentas` | `_1800.csv` | P1 |

**Configuración de Thread Group sugerida:**
- Ramp-up: 1 usuario cada 5–10 segundos
- Duración: 30 a 60 minutos de carga constante
- Loops: Infinito hasta fin de duración

---

*Documento generado automáticamente — Marzo 2026*
*Repositorio: https://github.com/israelrizo/Scripts_Repo*
