# Matriz de Casos de Prueba — Modulo: Estado de Cuenta

Esta matriz detalla los scripts de JMeter para el modulo de **Estado de Cuenta**, que cubre los flujos de consulta de movimientos y descarga de estados de cuenta en la plataforma BASEInet.

## Resumen de Scripts — Estado de Cuenta (1 Script)

| Submodulo | Script (Nombre Completo) | Objetivo | Servicio Impactado | Datos | Status Fail/Pass | Fecha |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **Consultas — Movimientos y EDO** | `G1_BASEINET_CLOUD_LOGIN_MOV_EdoCuenta.jmx` | Login, consulta de movimientos y estado de cuenta en entorno Cloud QA | `ScDoIniciarSesion`,<br/>`CdGetMovimientos`,<br/>`CdGetEstadoCuenta` | `usuarios_backend.csv` | | |

---

## Configuracion Sugerida (Thread Group)

- Inyecta el perfil de carga correspondiente con `-q tests/Ejecuciones/Tipos_De_Prueba/[Tipo]/perfil_carga.properties`.
- Los datos de usuarios se consumen desde `../../../data/`.
- Ajusta los parametros `${__P(threads, 1)}`, `${__P(rampup, 1)}` y `${__P(duration, 60)}` al escenario requerido.

## Comando de Ejecucion Rapida

```bash
TIMESTAMP=$(date +"%d%m%y_%H%M")
DIR="results/Ejecucion_${TIMESTAMP}_EdoCuenta_Login_Mov"
mkdir -p "$DIR/html_report"

jmeter -n \
  -t "tests/Modulos/EstadoDeCuenta/G1_BASEINET_CLOUD_LOGIN_MOV_EdoCuenta.jmx" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report"
```
