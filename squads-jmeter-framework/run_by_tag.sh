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
    "onboarding_dry_run")
        SCRIPT="tests/Onboarding/SCRIPT01_QA_ONBOARDING_DRY_RUN.jmx"
        ;;

    "onboarding_smoke_test")
        SCRIPT="tests/Onboarding/SCRIPT01_QA_ONBOARDING_SMOKE_TEST.jmx"
        ;;

    "onboarding_load_test")
        SCRIPT="tests/Onboarding/SCRIPT01_QA_ONBOARDING_LOAD_TEST.jmx"
        ;;

    "onboarding_scalability_test")
        SCRIPT="tests/Onboarding/SCRIPT02_QA_ONBOARDING_SCALABILITY_TEST.jmx"
        ;;

    "onboarding_stress_test")
        SCRIPT="tests/Onboarding/SCRIPT03_QA_ONBOARDING_STRESS_TEST.jmx"
        ;;

 "activation_smoke_test")
        SCRIPT="tests/Activation/SCRIPT00_QA_ACTIVATION_SMOKE_TEST.jmx"
        ;;

    "activation_load_test")
        SCRIPT="tests/Activation/SCRIPT01_QA_ACTIVATION_LOAD_TEST.jmx"
        ;;
"activation_scalability_test")
        SCRIPT="tests/Activation/SCRIPT02_QA_ACTIVATION_SCALABILITY_TEST.jmx"
        ;;
"activation_stress_test")
        SCRIPT="tests/Activation/SCRIPT02_QA_ACTIVATION_STRESS_TEST.jmx"
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
