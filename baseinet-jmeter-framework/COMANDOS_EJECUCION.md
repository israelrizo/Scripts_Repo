# Comandos de Ejecución JMeter — BASEInet Framework

La arquitectura de ejecución ahora se basa en el wrapper **`run_by_tag.sh`**.
Este script orquesta automáticamente la ejecución de scripts preconfigurados por medio de **tags**, creando carpetas de resultados, pasando parámetros, ejecutando JMeter y comprimiendo el reporte para facilitar la integración CI/CD.

> NOTA: Todos los comandos deben ejecutarse desde la raiz del repositorio (`baseinet-jmeter-framework/`).

---

## Ejecución Base (Generador / Local)

El script `run_by_tag.sh` acepta el tag de la prueba a ejecutar:
- `TAG`: Identificador del script (ej. `login_qa`, `drp_flujo_critico`).

### Ejemplos Prácticos

**1. Ejecutar Modulo de Login en QA:**
```bash
./run_by_tag.sh login_qa
```

**2. Ejecutar Dispersiones QA Cloud:**
```bash
./run_by_tag.sh dispersiones_qa
```

**3. Ejecutar Paquete 1 de Optimizaciones con valores por defecto:**
```bash
./run_by_tag.sh opt1_metodos_general
```

**4. Ejecutar Flujo Crítico DRP:**
```bash
./run_by_tag.sh drp_flujo_critico
```

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
