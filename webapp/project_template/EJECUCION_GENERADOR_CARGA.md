# Ejecución en el Generador de Carga — {{APP_NAME}}

## Topología
- **Master** (EC2): repositorio `Scripts_Repo`, JMeter Control Center (`localhost:8090`), InfluxDB/Grafana.
- **Slaves** (EC2 x2): `jmeter-server` escuchando en `1099` + puerto RMI fijo; misma versión de JMeter y plugins que el Master.

## Escenarios registrados

| Tag | Script | Tipo de prueba | Usuarios | Rampa | Duración |
|-----|--------|----------------|----------|-------|----------|
| | | | | | |

## Checklist antes de ejecutar
1. Tag registrado y script presente (pestaña *Tags*, sin badge `missing file`).
2. Datos en `data/` y sincronizados a los Slaves si la prueba es distribuida.
3. Backend Listener apuntando al InfluxDB del Master.
4. Ventana de prueba acordada con el equipo del aplicativo.

## Notas de Operación
- Resultados: `results/Ejecucion_<TIMESTAMP>_<SCRIPT_NAME>/` (`html_report/` + `resultado_<TIMESTAMP>.jtl`).
- *Stop* en la web = apagado ordenado (el reporte HTML se genera); *Kill* = corte inmediato (sin reporte).
