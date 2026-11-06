#!/bin/bash

# run_test.sh
# Wrapper de ejecucion para pruebas de JMeter
# Disenado para ejecucion local y pipelines de CI/CD en un Generador

# Valores por defecto
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

if [ -z "$SCRIPT_PATH" ]; then
    echo "Error: La ruta del script (-t) es obligatoria."
    usage
fi

if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: No se encuentra el archivo $SCRIPT_PATH"
    exit 1
fi

# Extraer el nombre del script sin la ruta ni extension
SCRIPT_NAME=$(basename "$SCRIPT_PATH" .jmx)

# Crear carpeta de resultados
TIMESTAMP=$(date +"%d%m%y_%H%M%S")
DIR="results/Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}"
mkdir -p "$DIR/html_report"

echo "====================================================="
echo "Iniciando Prueba JMeter en Generador"
echo "Script:   $SCRIPT_PATH"
echo "Host:     $HOST"
echo "Threads:  $THREADS"
echo "Ramp-up:  $RAMPUP"
echo "Duracion: $DURATION"
echo "Salida:   $DIR"
echo "====================================================="

# Ejecutar JMeter pasando las properties CLI para los scripts
jmeter -n \
  -t "$SCRIPT_PATH" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report" \
  -Jthreads="$THREADS" \
  -Jrampup="$RAMPUP" \
  -Jduration="$DURATION" \
  -Jhost="$HOST" \
  -Jshared_data="../shared-data"

# Verificacion de estado de finalizacion
if [ $? -eq 0 ]; then
    echo "====================================================="
    echo "Prueba finalizada con exito en el Generador."
    echo "Resultados crudos: $DIR/resultado_${TIMESTAMP}.jtl"
    echo "Reporte HTML:      $DIR/html_report/index.html"
    echo "====================================================="
    
    # Comprimir resultados para exportar al Pipeline CI/CD facilmente
    TAR_NAME="Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}.tar.gz"
    cd results/ && tar -czf "$TAR_NAME" "Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}" && cd ..
    
    echo "Artefacto comprimido listo para recoleccion del Pipeline: results/$TAR_NAME"
    
    # --- Automatización Post-Ejecución ---
    # 1. Generar URL interna (Servidor en el Generador)
    IP_LOCAL=$(ipconfig getifaddr en0 || ipconfig getifaddr en1 || echo "localhost")
    APP_FOLDER=$(basename "$(pwd)")
    URL_INTERNA="http://${IP_LOCAL}:8080/${APP_FOLDER}/${DIR}/html_report/index.html"
    
    echo "-----------------------------------------------------"
    echo "REPORTE INTERACTIVO (VPN): $URL_INTERNA"
    echo "-----------------------------------------------------"

    # 2. Abrir reporte localmente en Mac
    if [[ "$OSTYPE" == "darwin"* ]]; then
        REPORT_PATH="$(pwd)/$DIR/html_report/index.html"
        if [ -f "$REPORT_PATH" ]; then
            echo "Abriendo reporte HTML en el navegador local..."
            open "$REPORT_PATH"
        fi
    fi

    # 3. Intentar subir a Google Drive si el script existe
    UPLOAD_SCRIPT="../scripts/upload_to_drive.sh"
    if [ -f "$UPLOAD_SCRIPT" ]; then
        bash "$UPLOAD_SCRIPT" "$DIR" "$SCRIPT_NAME" "BDT"
    fi
    # -------------------------------------
else
    echo "Error: La ejecucion de JMeter en el Generador ha fallado."
    exit 1
fi
