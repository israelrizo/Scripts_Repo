# Scripts_Repo — JMeter Performance Tests (Banca Cloud)

Repositorio centralizado de scripts de pruebas de rendimiento para la plataforma **Banca Cloud (Baseinet)**, implementados con **Apache JMeter**. Los scripts simulan flujos reales de usuarios bancarios para evaluar la estabilidad, capacidad y tiempos de respuesta de los servicios.

---

## 📁 Estructura del Repositorio

```
Scripts_Repo/
├── README.md
└── tests/
    ├── scripts/
    │   ├── G1_Login_EdoCuenta/       # Scripts de Login y Estado de Cuenta
    │   │   ├── G1_BASEINET_CLOUD_LOGIN_MOV_EDO-CUENTA_v7.jmx
    │   │   ├── G1_BASEINET_CLOUD_LOGIN_STG_v7.jmx
    │   │   ├── G1_BASEINET_CLOUD_LOGIN_UTG_v7.jmx
    │   │   └── G1_SIL_LOGIN_v1.jmx
    │   └── G2_Dispersiones_CRUD/     # Scripts de Dispersiones y Operaciones CRUD
    │       ├── G2_BASEINET_BASEINET_SCRIPT04_QA_CLOUD_DESTINDIVIDUAL_CRUD.jmx
    │       ├── G2_BASEINET_BASEINET_SCRIPT05_SCRIPT06_SCRIPT03_DRP_CLOUD_OPTIMIZACIONES_AND_DISPERSION.jmx
    │       ├── G2_BASEINET_DRP_CLOUD_DISPERSIONES_TC_V1.jmx
    │       ├── G2_BASEINET_QA_CLOUD_DISPERSIONES_TC_V4.jmx
    │       ├── G2_BASEINET_QA_CLOUD_DISPERSIONES_V1.jmx
    │       ├── G2_BASEINET_QA_CLOUD_DISPERSIONES_V2.jmx
    │       ├── G2_BASEINET_QA_CLOUD_DISPERSIONES_V3.jmx
    │       ├── G2_SCRIPT05_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_DESTINATARIOS.jmx
    │       ├── G2_SCRIPT06_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_CdGetTraspasosComprobantes.jmx
    │       └── G2_SCRIPT15_BASEINET_QA_CLOUD_OPTIMIZACIONES_MCD_DISPERSION.jmx
    └── data/                         # Datos de usuarios y configuración para los scripts
        ├── usuarios_backend_baseinet_1800.csv
        ├── usuarios_backend_baseinet_agosto25.csv
        ├── usuarios_backend_baseinet_Dispersion.csv
        ├── usuarios_backend_baseinet_Dispersion_Enero2026.csv
        ├── usuarios_backend_baseinet_Dispersion_feguerra.csv
        └── sample*.txt               # Muestras de respuestas para validación
```

---

## 🗂️ Grupos de Scripts

### G1 — Login y Estado de Cuenta
Scripts que prueban el flujo de autenticación de usuarios y la consulta de estados de cuenta y movimientos bancarios.

| Script | Ambiente | Descripción |
|---|---|---|
| `G1_BASEINET_CLOUD_LOGIN_MOV_EDO-CUENTA_v7.jmx` | CLOUD | Login completo + movimientos + estado de cuenta |
| `G1_BASEINET_CLOUD_LOGIN_STG_v7.jmx` | STG | Login en ambiente de staging |
| `G1_BASEINET_CLOUD_LOGIN_UTG_v7.jmx` | UTG | Login en ambiente UTG |
| `G1_SIL_LOGIN_v1.jmx` | SIL | Login para el módulo SIL |

### G2 — Dispersiones y Operaciones CRUD
Scripts que prueban los flujos de dispersión de pagos, creación/consulta de destinatarios individuales y optimizaciones de carga.

| Script | Descripción |
|---|---|
| `G2_..._DESTINDIVIDUAL_CRUD.jmx` | CRUD de destinatarios individuales |
| `G2_..._OPTIMIZACIONES_AND_DISPERSION.jmx` | Flujo combinado de optimizaciones y dispersión (Scripts 03, 05, 06) |
| `G2_..._DISPERSIONES_TC_V*.jmx` | Pruebas de dispersión con tarjeta (TC) |
| `G2_..._DISPERSIONES_V*.jmx` | Pruebas generales de dispersión (versiones 1, 2, 3) |
| `G2_SCRIPT05_..._DESTINATARIOS.jmx` | Optimización MCD — listado de destinatarios |
| `G2_SCRIPT06_..._CdGetTraspasosComprobantes.jmx` | Optimización MCD — comprobantes de traspasos |
| `G2_SCRIPT15_..._DISPERSION.jmx` | Optimización MCD — dispersión masiva |

---

## ⚙️ Pre-requisitos

- **Apache JMeter** `>= 5.5` — [Descargar aquí](https://jmeter.apache.org/download_jmeter.cgi)
- **Java** `>= 11` (requerido por JMeter)
- Acceso a los ambientes de prueba (QA, STG, UTG, DRP según corresponda)
- Archivo de datos de usuarios (`.csv`) disponible en `tests/data/`

---

## 🚀 Cómo Ejecutar los Scripts

### Ejecución en modo GUI (recomendado para depuración)

```bash
jmeter -t tests/scripts/G1_Login_EdoCuenta/G1_BASEINET_CLOUD_LOGIN_MOV_EDO-CUENTA_v7.jmx
```

### Ejecución en modo No-GUI (recomendado para cargas)

```bash
jmeter -n \
  -t tests/scripts/G1_Login_EdoCuenta/G1_BASEINET_CLOUD_LOGIN_MOV_EDO-CUENTA_v7.jmx \
  -l results/resultado_$(date +%Y%m%d_%H%M%S).jtl \
  -e -o results/report/
```

> Asegúrate de crear la carpeta `results/` antes de ejecutar: `mkdir -p results/report`

### Parámetros importantes

| Parámetro | Descripción |
|---|---|
| `-n` | Modo No-GUI (headless) |
| `-t <archivo.jmx>` | Ruta al script a ejecutar |
| `-l <archivo.jtl>` | Archivo de resultados raw |
| `-e -o <directorio>` | Genera reporte HTML en el directorio indicado |

---

## 📊 Datos de Prueba

Los archivos de datos se encuentran en `tests/data/`. Los scripts de dispersión utilizan los CSV de usuarios para simular múltiples cuentas:

| Archivo | Uso |
|---|---|
| `usuarios_backend_baseinet_1800.csv` | Pool de ~1800 usuarios para pruebas de carga general |
| `usuarios_backend_baseinet_agosto25.csv` | Usuarios activos (corte agosto 2025) |
| `usuarios_backend_baseinet_Dispersion*.csv` | Usuarios específicos para flujos de dispersión |

> ⚠️ **Seguridad**: Los archivos CSV contienen credenciales de usuarios de prueba. **No compartir** fuera del equipo ni subir a repositorios públicos.

---

## 📝 Convenciones de Nombres

```
G<grupo>_<sistema>_<ambiente>_<descripcion>_<version>.jmx
```

- **G1**: Flujos de Login y Consulta
- **G2**: Flujos de Dispersión / Operaciones de negocio
- **Ambientes**: `QA`, `STG`, `UTG`, `DRP`, `CLOUD`, `SIL`

---

## 👥 Equipo

Mantenido por el equipo de **QA / Performance Engineering** de Baseinet.
