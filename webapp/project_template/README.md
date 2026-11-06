# Framework de Pruebas de Rendimiento — {{APP_NAME}}

Este directorio (`{{PROJECT_FOLDER}}`) contiene el framework de pruebas automatizadas de rendimiento con **Apache JMeter** para **{{APP_NAME}}**.
Creado el {{CREATED}} desde la plantilla del JMeter Control Center (`webapp/project_template`).

---

## Arquitectura del Directorio

```text
{{PROJECT_FOLDER}}/
├── data/                # Archivos de datos parametrizables (CSV, TXT)
├── results/             # Resultados: Ejecucion_<DDMMYY_HHMMSS>_<SCRIPT>/ (html_report + .jtl)
├── tests/               # Scripts .jmx organizados por nivel
├── run_by_tag.sh        # Ejecutor por tags (diccionario tag -> script)
├── run_test.sh          # Ejecucion ad-hoc (-t -u -r -d -e)
├── upload_reports.sh    # Respaldo masivo a Google Drive
└── Jenkinsfile          # Pipeline de ejemplo
```

## Convencion de Nomenclatura

`SCRIPT<NN>_<ENTORNO>_<APP>_<MODULO>_<TIPO_PRUEBA>.jmx` — ej. `SCRIPT01_QA_{{APP_SLUG}}_LOGIN_LOAD_TEST.jmx`

## Ejecucion

- Desde la web: **JMeter Control Center** → proyecto → *Tags* → ▶ Run.
- Desde terminal (raíz de este folder): `./run_by_tag.sh <tag> [-Jprop=valor]`. Sin argumentos lista los tags.

Ver **COMANDOS_EJECUCION.md** y **EJECUCION_GENERADOR_CARGA.md**.

## Gestion de Datos

- Referenciar los CSV con rutas **relativas** a este folder (`data/archivo.csv`), nunca rutas de Windows o del equipo local.
- En modo distribuido (Master + Slaves) cada Slave lee los CSV de **su propio disco**: sincronizar `data/` (botón *Sync to slaves*).
- Se prohibe el almacenamiento de credenciales reales en el repositorio.

## Metricas en vivo (InfluxDB / Grafana)

En el *Backend Listener* usar la IP privada del Master (no `localhost`) y agregar el argumento
`TAG_host = ${__machineName()}` para que las metricas de cada Slave no se sobreescriban.
