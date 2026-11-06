# Guía de Integración CI/CD — {{APP_NAME}}

1. **Generador remoto**: la carga se ejecuta en el nodo generador (Master JMeter), nunca en el master del CI.
2. **`run_by_tag.sh`**: el pipeline solo envía el tag; el script resuelve el `.jmx`, los parámetros y empaqueta el resultado.

## Jenkins
El `Jenkinsfile` incluido usa `agent { label 'generador-jmeter' }` y un parámetro `TAG`.
Al terminar archiva `results/*.tar.gz` como artefacto del build.

## GitHub Actions
Usar un *self-hosted runner* instalado en el generador (`runs-on: [self-hosted, generador-jmeter]`) y
`actions/upload-artifact@v4` para `results/*.tar.gz`.

## Flujo
1. QA/Dev inicia el build y elige el tag.
2. El generador ejecuta `./run_by_tag.sh <tag>`.
3. Métricas en vivo en InfluxDB/Grafana (o en el *Live monitor* del Control Center).
4. El `.tar.gz` con `html_report` y `.jtl` queda como artefacto y en `results/`.
