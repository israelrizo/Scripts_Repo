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

    # ---------------- Módulos Core ----------------
    "login_qa")
        SCRIPT="tests/Modulos/Login/G1_BASEINET_QA_LOGIN_ScDoIniciarSesion_ScDoFinalizarSesion.jmx"
        EXTRA_ARGS="-Jthreads=50 -Jrampup=10 -Jduration=300 -Jhost=qa.bancobase.com"
        ;;
    "login_sil")
        SCRIPT="tests/Modulos/Login/G1_BASEINET_SIL_LOGIN_ScDoIniciarSesion.jmx"
        ;;
    "dispersiones_qa")
        SCRIPT="tests/Modulos/Dispersiones/G2_BASEINET_QA_CLOUD_DestIndividual_CRUD.jmx"
        EXTRA_ARGS="-Jthreads=100 -Jrampup=20 -Jduration=600 -Jhost=qa.cloud.bancobase.com"
        ;;
    "edo_cuenta")
        SCRIPT="tests/Modulos/EstadoDeCuenta/G1_BASEINET_CLOUD_LOGIN_MOV_EdoCuenta.jmx"
        ;;
    "mdp_dispersion")
        SCRIPT="tests/Modulos/Dispersiones/SCRIPT01_QA_BASEINET_MDP_DISPERSION.jmx"
        ;;


    # ---------------- Escenarios DRP ----------------
    "drp_flujo_critico")
        SCRIPT="tests/Escenarios/DRP/G2_BASEINET_DRP_FlujoCritico.jmx"
        EXTRA_ARGS="-Jthreads=200 -Jrampup=30 -Jduration=1800 -Jhost=qa2.bancobase.com"
        ;;
    "eks_flujo_critico")
        SCRIPT="tests/Escenarios/EKS/G2_BASEINET_EKS_FlujoCritico.jmx"
        EXTRA_ARGS="-Jthreads=200 -Jrampup=30 -Jduration=1800"
       ;;

    # ---------------- Optimizaciones Paquete 1 ----------------
    "opt1_metodos_general")
        SCRIPT="tests/Optimizaciones/Paquete_1/Metodos_General/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_METODOS_GENERAL.jmx"
        ;;
    "opt1_autorizar_traspaso")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdDoAutorizarTraspaso_CdGetTraspasos.jmx"
        ;;
    "opt1_get_cuentas")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetCuentas.jmx"
        ;;
    "opt1_get_cuentas_traspasos")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetCuentasTraspasos.jmx"
        ;;
    "opt1_get_destinatarios")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetDestinatariosAutorizadosPageInDB.jmx"
        ;;
    "opt1_get_estado_cuenta_pdf")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetEstadoCuentaPdf_CdGetEstadoCuentaMt940Commando_CdGetMovimientos.jmx"
        ;;
    "opt1_get_movimientos")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetMovimientos.jmx"
        ;;
    "opt1_get_traspasos_comprobantes")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdGetTraspasosComprobantes.jmx"
        ;;
    "opt1_load_archivo_lote")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_CdLoadArchivoLoteBase64.jmx"
        ;;
    "opt1_validate_cuenta")
        SCRIPT="tests/Optimizaciones/Paquete_1/G2_PAQUETE_1_BASEINET_QA_DRP_OPTIMIZACIONES_ScValidateCuenta_CdGetCustomerNotices_ScDoIniciarSesion_ScDoFinalizarSesion.jmx"
        ;;

    # ---------------- Optimizaciones Paquete 2 ----------------
    "opt2_metodos_general")
        SCRIPT="tests/Optimizaciones/Paquete_2/Metodos_General/G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_METODOS_GENERAL.jmx"
        ;;
    "opt2_add_destinatario")
        SCRIPT="tests/Optimizaciones/Paquete_2/G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdAddDestinatario.jmx"
        ;;
    "opt2_capturar_traspaso")
        SCRIPT="tests/Optimizaciones/Paquete_2/G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdDoCapturarTraspasoMasivo_CdDoAutorizarTraspaso_CdGetTraspasos.jmx"
        ;;
    "opt2_get_estado_cuenta_pdf")
        SCRIPT="tests/Optimizaciones/Paquete_2/G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdGetEstadoCuentaPdf_CdGetEstadoCuentaMt940Commando.jmx"
        ;;
    "opt2_get_traspasos_comprobantes")
        SCRIPT="tests/Optimizaciones/Paquete_2/G2_PAQUETE_2_BASEINET_QA2_OPTIMIZACIONES_CdGetTraspasosComprobantes.jmx"
        ;;

    # ---------------- Optimizaciones Paquete 3 ----------------
    "opt3_CdDoCapturarTraspaso")
        SCRIPT="tests/Optimizaciones/Paquete_3/G2_PAQUETE_3_BASEINET_DRP_OPTIMIZACIONES_CdDoCapturarTraspaso.jmx"
        ;;

    # ---------------- Optimizaciones Paquete 4 ----------------
    "opt4_MetodosGenerales_QA2")
        SCRIPT="tests/Optimizaciones/Paquete_4/SCRIPT10_OPT_P4_QA2_BASEINET_METODOS_GENERAL.jmx"
        ;;
    "opt4_MetodosGenerales_QA1")
        SCRIPT="tests/Optimizaciones/Paquete_4/SCRIPT10_OPT_P4_QA_BASEINET_METODOS_GENERALES.jmx"
        ;;
    "opt4_MetodosGenerales_QAMIX")
        SCRIPT="tests/Optimizaciones/Paquete_4/SCRIPT10_OPT_P4_QAMIXTO_BASEINET_METODOS_GENERALES.jmx"
        ;;

    # ---------------- Optimizaciones Paquete 5 ----------------
    "opt5_MetodosGenerales_QA1")
        SCRIPT="tests/Optimizaciones/Paquete_5/SCRIPT09_OPT_P5_QA_BASEINET_METODOS_GENERALES.jmx"
        ;;
    "opt5_MetodosGenerales_QA2")
        SCRIPT="tests/Optimizaciones/Paquete_5/SCRIPT09_OPT_P5_QA2_BASEINET_METODOS_GENERALES.jmx"
        ;;

    # ---------------- Optimizaciones Paquete 6 ----------------
    "opt6_MetodosGenerales_QA1")
        SCRIPT="tests/Optimizaciones/Paquete_6/SCRIPT02_OPT_P6_QA_BASEINET_METODOS_GENERALES.jmx"
        ;;
    "opt5_MetodosGenerales_QA2")
        SCRIPT="tests/Optimizaciones/Paquete_5/SCRIPT09_OPT_P5_QA2_BASEINET_METODOS_GENERALES.jmx"
        ;;
"opt6_MovilData_QA")
        SCRIPT="tests/Optimizaciones/Paquete_Movil/SCRIPT01_OPT_P6_QA_BASEINET_MOVIL_SPEI_FINAL.jmx"
        ;;

"opt6_Movil_XPRESS_QA")
        SCRIPT="tests/Optimizaciones/Paquete_Movil/SCRIPT02_OPT_P6_QA_BASEINET_MOVIL_XPRESS.jmx"
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
