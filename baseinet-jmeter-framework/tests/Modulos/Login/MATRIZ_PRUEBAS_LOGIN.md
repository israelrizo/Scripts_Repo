# Matriz de Casos de Prueba — Modulo: Login

Esta matriz detalla los scripts de JMeter para el modulo de **Login**, que cubre los flujos de inicio y cierre de sesion de la plataforma BASEInet.

## Resumen de Scripts — Login (2 Scripts)

| Submodulo | Script (Nombre Completo) | Objetivo | Servicio Impactado | Datos | Status Fail/Pass | Fecha |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **QA — Login Flujo Completo** | `G1_BASEINET_QA_LOGIN_ScDoIniciarSesion_ScDoFinalizarSesion.jmx` | Inicio y cierre de sesion del usuario en entorno QA | `ScDoIniciarSesion`,<br/>`ScDoFinalizarSesion` | `usuarios_backend.csv` | | |
| **SIL — Login** | `G1_BASEINET_SIL_LOGIN_ScDoIniciarSesion.jmx` | Inicio de sesion en entorno SIL (Sistema de Integracion Local) | `ScDoIniciarSesion` | `usuarios_backend.csv` | | |

---

## Configuracion Sugerida (Thread Group)

- Inyecta el perfil de carga correspondiente con `-q tests/Ejecuciones/Tipos_De_Prueba/[Tipo]/perfil_carga.properties`.
- Los datos de usuarios se consumen desde `../../../data/`.
- Ajusta los parametros `${__P(threads, 1)}`, `${__P(rampup, 1)}` y `${__P(duration, 60)}` al escenario requerido.

## Comando de Ejecucion Rapida

```bash
TIMESTAMP=$(date +"%d%m%y_%H%M")
DIR="results/Ejecucion_${TIMESTAMP}_Login_IniciarSesion_FinalizarSesion"
mkdir -p "$DIR/html_report"

jmeter -n \
  -t "tests/Modulos/Login/G1_BASEINET_QA_LOGIN_ScDoIniciarSesion_ScDoFinalizarSesion.jmx" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report"
```
