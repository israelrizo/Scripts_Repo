# Comandos de Ejecución por Tags (Generador de Carga)

Si necesitas ejecutar las pruebas de manera manual directamente en el **Generador de Carga**, debes utilizar el script `run_by_tag.sh`. Este script ya incluye los parámetros óptimos (DNS, puerto, path prefix, think time) y gestiona la creación de las carpetas de resultados automáticamente.

> **NOTA:** Todos los comandos deben ser ejecutados estando posicionado en la raíz del repositorio (`bdt-jmeter-framework/`).

---

## Escenarios — Estadística Transaccional

### 1. SCRIPT01 — BDT Estadística Transaccional

Prueba de escalabilidad del microservicio BDT (`apibdt`). Cubre los siguientes endpoints:

| # | Transacción | Endpoint | Método |
|---|-------------|----------|--------|
| T01 | Signature | `POST /api/v1/bdt/signature` | POST |
| T02 | Client Stats | `POST /api/v1/bdt/clients/stats` | POST |
| T03 | Client Stats Save | `POST /api/v1/bdt/clients/stats/save` | POST |
| T04 | Client Decode | `POST /api/v1/bdt/clients/decode` | POST |
| T05 | Health | `GET /api/v1/bdt/health` | GET |
| T06 | Batch Process Deltas | `POST /api/v1/bdt/batch/process-deltas` | POST |
| T07 | Estado Job Delta | `GET /api/v1/bdt/batch/{jobId}` | GET |
| T08 | Batch Process All | `POST /api/v1/bdt/batch/process-all` | POST |
| T09 | Estado Job All | `GET /api/v1/bdt/batch/{jobId}` | GET |
| T10 | Certificate Health | `GET /api/v1/bdt/certificate/health` | GET |

**Configuración del Thread Group (Stepping):**
- Hilos totales: `400`
- Inicio escalonado: `100` usuarios cada `300s`
- Flight time: `2420s`
- Think time: `1000ms + [0–4000ms] random`

**Ejecución con parámetros por defecto (QA):**
```bash
./run_by_tag.sh bdt_estadistica_transaccional
```

**Ejecución con override de ambiente (ejemplo SIL/PROD):**
```bash
./run_by_tag.sh bdt_estadistica_transaccional -JP_DNS=apibdt.sil.gslb -JP_PORT=61080
```

**Parámetros configurables:**

| Parámetro JMeter | Descripción | Valor por defecto |
|-----------------|-------------|-------------------|
| `P_DNS` | Host del servicio BDT | `apibdt.q.gslb` |
| `P_PORT` | Puerto del servicio | `61080` |
| `P_PathPrefix` | Prefijo del path API | `api/v1/bdt` |
| `P_tt` | Think time máximo (ms) | `4000` |

---

## Notas de Operación

- Los resultados se guardan automáticamente en `results/Ejecucion_<TIMESTAMP>_<SCRIPT_NAME>/`
- El HTML report se genera en `results/.../html_report/`
- El archivo `.jtl` queda disponible para análisis posterior en `results/.../resultado_<TIMESTAMP>.jtl`
- El Backend Listener está configurado para enviar métricas a InfluxDB (`BDT_QA`) en tiempo real
