#!/bin/bash

# ==============================================================================
# run_by_tag.sh
# Ejecutor de scripts JMeter por medio de etiquetas (tags).
# Mantiene la creación nativa de la carpeta en /results con el timestamp.
# ==============================================================================

TAG=$1
EXTRA_ARGS=""

# ==========================================
# Diccionario de Tags y Rutas
# ==========================================
case "$TAG" in

    # ---------------- Monitor Plus — BBD registrando data a Monitor Plus ----------------
    "blacklist_API_Baseline")
        SCRIPT="tests/Blacklist_API/SCRIPT01_QA_Blacklist_API_CargaMasiva.jmx"
        EXTRA_ARGS=""
        ;;
    "blacklist_API_Scalability")
        SCRIPT="tests/Blacklist_API/SCRIPT02_QA_Blacklist_API_ListasNegras.jmx"
        EXTRA_ARGS=""
        ;;
    "blacklist_API_Scalability20")
        SCRIPT="tests/Blacklist_API/SCRIPT03_QA_Blacklist_API_ListasNegras.jmx"
        EXTRA_ARGS=""
        ;;
    # ---------------- Ayuda por defecto ----------------
    *)
        echo "Uso: ./run_by_tag.sh <tag>"
        echo ""
        echo "Tags disponibles:"
        echo "  Monitor Plus — BBD:"
        echo "    blacklist_API_Baseline, blacklist_API_Scalability"
        echo ""
        echo "Ejemplos:"
        echo "  ./run_by_tag.sh bbd_monitorPlus"
        exit 1
        ;;
esac

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
if [ -n "$EXTRA_ARGS" ]; then
    echo "=> Argumentos: $EXTRA_ARGS"
fi
echo "=========================================================="

jmeter -n -t "$SCRIPT" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report" \
  $EXTRA_ARGS

echo "=========================================================="
echo "=> Prueba Finalizada. Resultados guardados en: $DIR"
