# Comandos de Ejecución JMeter — BDT Framework

La arquitectura de ejecución se basa en el wrapper **`run_by_tag.sh`**.
Este script orquesta automáticamente la ejecución de scripts preconfigurados por medio de **tags**, creando carpetas de resultados con timestamp, pasando parámetros, ejecutando JMeter y comprimiendo el reporte para facilitar la integración CI/CD.

> NOTA: Todos los comandos deben ejecutarse desde la raíz del repositorio (`bdt-jmeter-framework/`).

---

## Estructura del directorio `tests/`

```
tests/
├── Escenarios/
│   └── Estadistica_Transaccional/
│       └── SCRIPT01_BBASE_BDT_ESTADISTICA_TRANSACCIONAL.jmx
├── Modulos/
└── Optimizaciones/
```

---

## Ejecución Base (Generador / Local)

El script `run_by_tag.sh` acepta el tag de la prueba a ejecutar.
Los parámetros de conexión están preconfigurados en el diccionario de tags (sobreescribibles via `-JP_<PARAM>=<VALOR>`).

### Escenarios — Estadística Transaccional

**1. SCRIPT01 — BDT Estadística Transaccional (QA):**
```bash
./run_by_tag.sh bdt_estadistica_transaccional
```

**Con parámetros personalizados (override de ambiente):**
```bash
./run_by_tag.sh bdt_estadistica_transaccional -JP_DNS=apibdt.prod.gslb -JP_PORT=61080
```

> Los parámetros por defecto del script son:
> - `P_DNS`: `apibdt.q.gslb`
> - `P_PORT`: `61080`
> - `P_PathPrefix`: `api/v1/bdt`
> - `P_tt`: `4000` (think time en ms)

---

## Integración con CI/CD (Generador Remoto)

Si estás ejecutando las pruebas desde Jenkins o GitHub Actions, NO necesitas correr estos comandos manualmente.
El pipeline de CI/CD (ver `Jenkinsfile` o `.github/workflows/performance-tests.yml`) te presentará una lista desplegable con los tags disponibles y delegará la ejecución al **Nodo Generador**.

El generador ejecutará automáticamente `./run_by_tag.sh <tag>` y devolverá el archivo comprimido (`.tar.gz`) con el `html_report` y `.jtl` al pipeline para su auditoría y preservación histórica.

---

## Automatización Post-Ejecución

Al finalizar cada prueba local/generador, el sistema realiza automáticamente:
1. **Generación de URL Interno**: Crea un link tipo `http://IP:8080/...` para visualizar el reporte interactivo.
   - *Nota*: Requiere que el servidor Python esté activo en la raíz del proyecto (`python3 -m http.server 8080`).
2. **Apertura Local**: En Mac, abre el reporte automáticamente en el navegador.
3. **Respaldo en Drive**: Sube los resultados a la carpeta corporativa en Google Drive organizada por aplicativo.

## Comandos Adicionales

### Carga Manual a Google Drive
Si deseas subir todos los resultados de este aplicativo de forma masiva (históricos):
```bash
./upload_reports.sh
```

### Uso de Datos Compartidos (shared-data)
Para usar archivos de la carpeta raíz `/shared-data` en tus JMX, utiliza la propiedad:
`${__P(shared_data)}/archivo.csv`
