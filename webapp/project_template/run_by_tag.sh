#!/bin/bash

# ==============================================================================
# run_by_tag.sh — {{APP_NAME}}
# Ejecutor de scripts JMeter por medio de etiquetas (tags).
# Mantiene la creación nativa de la carpeta en /results con el timestamp.
#
# Uso:  ./run_by_tag.sh <tag> [-Jprop=valor ...]
#       Los argumentos extra se agregan DESPUÉS de EXTRA_ARGS (tienen prioridad).
#
# Los tags pueden darse de alta desde el JMeter Control Center (webapp) o a mano:
# agrega un bloque nuevo ANTES de la línea "@@WEBAPP_TAGS_END@@".
# ==============================================================================

TAG=$1
shift
EXTRA_ARGS=""

# ==========================================
# Diccionario de Tags y Rutas
# ==========================================
case "$TAG" in

    # ---------------- Ejemplo (reemplazar) ----------------
    # "{{APP_SLUG}}_smoke_test")
    #     SCRIPT="tests/Modulos/SCRIPT00_QA_{{APP_SLUG}}_SMOKE_TEST.jmx"
    #     EXTRA_ARGS="-Jthreads=1 -Jrampup=1 -Jduration=60"
    #     ;;

    # @@WEBAPP_TAGS_END@@
    # ---------------- Ayuda por defecto ----------------
    *)
        echo "Uso: ./run_by_tag.sh <tag> [-Jprop=valor ...]"
        echo ""
        echo "Tags disponibles:"
        grep -E '^[[:space:]]*"[^"]+"\)' "$0" | sed -E 's/^[[:space:]]*"([^"]+)"\).*/    \1/'
        exit 1
        ;;
esac

if [ ! -f "$SCRIPT" ]; then
    echo "Error: no se encuentra el script $SCRIPT"
    exit 1
fi

# ==========================================
# Lógica de Ejecución (Nativa)
# ==========================================

# 1. Extraer nombre y generar timestamp
SCRIPT_NAME=$(basename "$SCRIPT" .jmx)
TIMESTAMP=$(date +"%d%m%y_%H%M%S")
DIR="results/Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}"

# 2. Crear carpeta de resultados
echo "=> Creando directorio: $DIR/html_report"
mkdir -p "$DIR/html_report"

# 3. Ejecutar JMeter en modo Non-GUI
echo "=> Ejecutando JMeter (Tag: $TAG)"
echo "=> Script: $SCRIPT"
if [ -n "$EXTRA_ARGS" ] || [ $# -gt 0 ]; then
    echo "=> Argumentos: $EXTRA_ARGS $*"
fi
echo "=========================================================="

# shellcheck disable=SC2086
jmeter -n -t "$SCRIPT" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -j "$DIR/jmeter.log" \
  -e -o "$DIR/html_report" \
  $EXTRA_ARGS "$@"
RC=$?

echo "=========================================================="
if [ $RC -eq 0 ]; then
    (cd results && tar -czf "Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}.tar.gz" "Ejecucion_${TIMESTAMP}_${SCRIPT_NAME}")
    echo "=> Prueba Finalizada. Resultados guardados en: $DIR"
else
    echo "=> JMeter terminó con código $RC. Resultados guardados en: $DIR"
fi
exit $RC
