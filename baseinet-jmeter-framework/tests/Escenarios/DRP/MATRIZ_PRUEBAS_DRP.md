# Matriz de Casos de Prueba — Modulo: DRP (Disaster Recovery Plan)

Esta matriz detalla los scripts de JMeter para el modulo de **Disaster Recovery Plan (DRP)**, que cubre los flujos criticos de negocio que deben continuar operando ante una contingencia mayor en la plataforma BASEInet.

## Resumen de Scripts — DRP (1 Script)

| Submodulo | Script (Nombre Completo) | Objetivo | Servicio Impactado | Datos | Status Fail/Pass | Fecha |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **Flujo Critico** | `G2_BASEINET_DRP_FlujoCritico.jmx` | Validacion de disponibilidad y rendimiento de los servicios criticos de BASEInet bajo escenario de contingencia DRP | `ScDoIniciarSesion`,<br/>`CdGetCuentas`,<br/>`CdGetMovimientos` | `usuarios_backend.csv` | | |

---

## Configuracion Sugerida (Thread Group)

- Inyecta el perfil de carga correspondiente con `-q tests/Ejecuciones/Tipos_De_Prueba/[Tipo]/perfil_carga.properties`.
- Los datos de usuarios se consumen desde `../../../data/`.
- Ajusta los parametros `${__P(threads, 1)}`, `${__P(rampup, 1)}` y `${__P(duration, 60)}` al escenario requerido.

> IMPORTANTE: Las pruebas de DRP **solo deben ejecutarse en ventanas de mantenimiento autorizadas**. Coordina con el equipo de infraestructura antes de ejecutar este script.

## Comando de Ejecucion Rapida

```bash
TIMESTAMP=$(date +"%d%m%y_%H%M")
DIR="results/Ejecucion_${TIMESTAMP}_DRP_FlujoCritico"
mkdir -p "$DIR/html_report"

jmeter -n \
  -t "tests/Escenarios/DRP/G2_BASEINET_DRP_FlujoCritico.jmx" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report"
```
