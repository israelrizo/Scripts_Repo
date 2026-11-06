# Matriz de Casos de Prueba — Modulo: Dispersiones

Esta matriz detalla los scripts de JMeter para el modulo de **Dispersiones**, que cubre los flujos de alta, consulta y CRUD de destinatarios individuales en la plataforma BASEInet.

## Resumen de Scripts — Dispersiones (1 Script)

| Submodulo | Script (Nombre Completo) | Objetivo | Servicio Impactado | Datos | Status Fail/Pass | Fecha |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **Destinatario Individual — CRUD** | `G2_BASEINET_QA_CLOUD_DestIndividual_CRUD.jmx` | Flujo completo de alta, consulta, modificacion y eliminacion de destinatarios individuales en QA Cloud | `CdAddDestinatario`,<br/>`CdGetDestinatarios`,<br/>`CdDeleteDestinatario` | `usuarios_backend.csv` | | |

---

## Configuracion Sugerida (Thread Group)

- Inyecta el perfil de carga correspondiente con `-q tests/Ejecuciones/Tipos_De_Prueba/[Tipo]/perfil_carga.properties`.
- Los datos de usuarios se consumen desde `../../../data/`.
- Ajusta los parametros `${__P(threads, 1)}`, `${__P(rampup, 1)}` y `${__P(duration, 60)}` al escenario requerido.

## Comando de Ejecucion Rapida

```bash
TIMESTAMP=$(date +"%d%m%y_%H%M")
DIR="results/Ejecucion_${TIMESTAMP}_Dispersiones_DestIndividual_CRUD"
mkdir -p "$DIR/html_report"

jmeter -n \
  -t "tests/Modulos/Dispersiones/G2_BASEINET_QA_CLOUD_DestIndividual_CRUD.jmx" \
  -l "$DIR/resultado_${TIMESTAMP}.jtl" \
  -e -o "$DIR/html_report"
```
