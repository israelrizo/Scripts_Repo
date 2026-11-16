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

    # ---------------- Escenarios BOW ----------------
    "bow_unit_test")
        SCRIPT="tests/Optimizaciones/SCRIPT00_QA_BOW_UNIT_TEST.jmx"
        ;;
    "bow_smoke_test")
        SCRIPT="tests/Optimizaciones/SCRIPT00_QA_BOW_SMOKE_TEST.jmx"
        ;;
    "bow_load_test")
        SCRIPT="tests/Optimizaciones/SCRIPT01_QA_BOW_LOAD_TEST.jmx"
        ;;
    "bow_scalability_test")
        SCRIPT="tests/Optimizaciones/SCRIPT02_QA_BOW_SCALABILITY_TEST.jmx"
        ;;

    # ---------------- Ayuda por defecto ----------------
    *)
        echo "Uso: ./run_by_tag.sh <tag>"
        echo ""
        echo "Tags disponibles:"
        echo "  Módulos Core:   login_qa, login_sil, dispersiones_qa, edo_cuenta"
        echo "  Escenarios DRP: drp_flujo_critico"
        echo "  Optimizaciones 1: opt1_metodos_general, opt1_autorizar_traspaso, opt1_get_cuentas,"
        echo "                    opt1_get_cuentas_traspasos, opt1_get_destinatarios, opt1_get_estado_cuenta_pdf,"
        echo "                    opt1_get_movimientos, opt1_get_traspasos_comprobantes, opt1_load_archivo_lote,"
        echo "                    opt1_validate_cuenta"
        echo "  Optimizaciones 2: opt2_metodos_general, opt2_add_destinatario, opt2_capturar_traspaso,"
        echo "                    opt2_get_estado_cuenta_pdf, opt2_get_traspasos_comprobantes"
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
