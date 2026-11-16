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

    # ---------------- Escenarios — Estadística Transaccional ----------------
    "bps_disperciones_smoke")
        SCRIPT="tests/Modulos/Disperciones-FileManager/SCRIPT01_BBASE_BPS_DISPERCIONES_FILE_MANAGER_SMOKE_TEST_DYNAMIC.jmx"
        ;;

    "bps_disperciones_scalability")
        SCRIPT="tests/Modulos/Disperciones-FileManager/SCRIPT01_BBASE_BPS_DISPERCIONES_FILE_MANAGER_SCALABILITY.jmx"
        ;;

"bps_disperciones_volume")
        SCRIPT="tests/Modulos/Disperciones-FileManager/SCRIPT01_BBASE_BPS_DISPERCIONES_FILE_MANAGER_VOLUME_TEST.jmx"
        ;;


"bps_disperciones_10000")
        SCRIPT="tests/Modulos/Disperciones-FileManager/BPS_DISPERCIONES_10000.jmx"
        ;;
"bps_disperciones_650")
        SCRIPT="tests/Modulos/Disperciones-FileManager/BPS_DISPERCIONES_650.jmx"
        ;;
    # ---------------- Ayuda por defecto ----------------
    *)
        echo "Uso: ./run_by_tag.sh <tag>"
        echo ""
        echo "Tags disponibles:"
        echo "  Escenarios — Estadística Transaccional:"
        echo "    bdt_estadistica_transaccional"
        echo ""
        echo "Ejemplos:"
        echo "  ./run_by_tag.sh bdt_estadistica_transaccional"
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
