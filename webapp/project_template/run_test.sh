#!/bin/bash

# run_test.sh — {{APP_NAME}}
# Wrapper de ejecucion para pruebas de JMeter (ejecucion ad-hoc, local o CI/CD en el Generador)

SCRIPT_PATH=""
THREADS=1
RAMPUP=1
DURATION=60
HOST="qa2.bancobase.com"

usage() {
    echo "Uso: $0 -t <script.jmx> [-e host] [-u threads] [-r rampup] [-d duration]"
    echo "  -t   Ruta del script JMeter a ejecutar (ej. tests/Modulos/Login/script.jmx)"
    echo "  -e   Host / Ambiente (default: qa2.bancobase.com)"
    echo "  -u   Numero de Usuarios/Threads (default: 1)"
    echo "  -r   Ramp-up period en segundos (default: 1)"
    echo "  -d   Duracion de la prueba en segundos (default: 60)"
    exit 1
}

while getopts "t:e:u:r:d:h" opt; do
    case "$opt" in
        t) SCRIPT_PATH=$OPTARG ;;
        e) HOST=$OPTARG ;;
        u) THREADS=$OPTARG ;;
        r) RAMPUP=$OPTARG ;;
        d) DURATION=$OPTARG ;;
        h|?) usage ;;
    esac
done

[ -z "$SCRIPT_PATH" ] && { echo "Error: La ruta del script (-t) es obligatoria."; usage; }
[ ! -f "$SCRIPT_PATH" ] && { echo "Error: No se encuentra el archivo $SCRIPT_PATH"; exit 1; }

SCRIPT_NAME=$(basename "$SCRIPT_PATH" .jmx)
TIMESTAMP=$(date +"%d%m%y_%H%M%S")
DIR="results/Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}"
mkdir -p "$DIR/html_report"

echo "====================================================="
echo "Iniciando Prueba JMeter en Generador — {{APP_NAME}}"
echo "Script:   $SCRIPT_PATH"
echo "Host:     $HOST"
echo "Threads:  $THREADS"
echo "Ramp-up:  $RAMPUP"
echo "Duracion: $DURATION"
echo "Salida:   $DIR"
echo "====================================================="

jmeter -n \
  -t "$SCRIPT_PATH" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -j "$DIR/jmeter.log" \
  -e -o "$DIR/html_report" \
  -Jthreads="$THREADS" \
  -Jrampup="$RAMPUP" \
  -Jduration="$DURATION" \
  -Jhost="$HOST" \
  -Jshared_data="../shared-data"

if [ $? -ne 0 ]; then
    echo "Error: La ejecucion de JMeter en el Generador ha fallado."
    exit 1
fi

echo "====================================================="
echo "Prueba finalizada con exito en el Generador."
echo "Resultados crudos: $DIR/resultado_${TIMESTAMP}.jtl"
echo "Reporte HTML:      $DIR/html_report/index.html"
echo "====================================================="

TAR_NAME="Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}.tar.gz"
(cd results && tar -czf "$TAR_NAME" "Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}")
echo "Artefacto comprimido listo para recoleccion del Pipeline: results/$TAR_NAME"

# --- Automatización Post-Ejecución ---
# IP local portable (Linux: hostname -I / macOS: ipconfig)
IP_LOCAL=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP_LOCAL" ] && IP_LOCAL=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "localhost")
APP_FOLDER=$(basename "$(pwd)")
echo "-----------------------------------------------------"
echo "REPORTE (JMeter Control Center): http://localhost:8090/p/${APP_FOLDER}?tab=results"
echo "-----------------------------------------------------"

if [[ "$OSTYPE" == "darwin"* ]] && [ -f "$(pwd)/$DIR/html_report/index.html" ]; then
    open "$(pwd)/$DIR/html_report/index.html"
fi

UPLOAD_SCRIPT="../scripts/upload_to_drive.sh"
if [ -f "$UPLOAD_SCRIPT" ]; then
    bash "$UPLOAD_SCRIPT" "$DIR" "$SCRIPT_NAME" "{{APP_NAME}}"
fi
