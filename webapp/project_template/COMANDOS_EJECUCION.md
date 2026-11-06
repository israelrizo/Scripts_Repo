# Comandos de Ejecución JMeter — {{APP_NAME}}

La ejecución se basa en **`run_by_tag.sh`**: crea `results/Ejecucion_<TIMESTAMP>_<SCRIPT>/`, ejecuta JMeter en modo non-GUI,
genera el `html_report` y comprime el resultado (`.tar.gz`) para CI/CD.

> Todos los comandos se ejecutan desde la raíz de `{{PROJECT_FOLDER}}/`.

## Listar tags disponibles
```bash
./run_by_tag.sh
```

## Ejecutar un tag
```bash
./run_by_tag.sh <tag>
```

## Override de propiedades (tienen prioridad sobre EXTRA_ARGS)
```bash
./run_by_tag.sh <tag> -Jthreads=100 -Jrampup=60 -Jduration=900
```

## Ejecución distribuida manual (Master + Slaves)
Desde la web basta con marcar *Distributed*. Manualmente, `-R` y propiedades globales `-G` (llegan a los Slaves):
```bash
./run_by_tag.sh <tag> -R 10.0.1.11,10.0.1.12 -Gthreads=100
```

## Ejecución ad-hoc sin tag
```bash
./run_test.sh -t tests/<carpeta>/<script>.jmx -u 10 -r 10 -d 300 -e qa2.bancobase.com
```

## Respaldo masivo a Google Drive
```bash
./upload_reports.sh
```
