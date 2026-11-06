# Framework de Pruebas de Rendimiento — BASEInet

Este repositorio (`baseinet-jmeter-framework`) contiene el framework de pruebas automatizadas de rendimiento utilizando **Apache JMeter** para la plataforma **BASEInet**.

---

## Arquitectura del Directorio

El framework esta organizado en tres capas logicas para separar funcionalidades, servicios optimizados y escenarios de contingencia:

```text
baseinet-jmeter-framework/
├── data/                          # Archivos de datos parametrizables (CSV, TXT)
├── results/                       # Resultados de las pruebas (HTML, JTL)
└── tests/                         # Repositorio de scripts organizados por nivel
    ├── Modulos/                   # Scripts funcionales estandar (G1)
    │   ├── Login/
    │   ├── EstadoDeCuenta/
    │   └── Dispersiones/
    ├── Optimizaciones/            # Servicios atomicos optimizados (G2)
    │   ├── Paquete_1/
    │   └── Paquete_2/
    └── Escenarios/                # Pruebas integrales o de ambiente especifico
        └── DRP/                   # Disaster Recovery Plan
```

---

## Convencion de Nomenclatura

Los scripts siguen el patron estandar:
`G[generacion]_BASEINET_[ENTORNO]_[MODULO]_[Funcion].jmx`

---

## Ejecucion de Pruebas

Consulte el archivo **COMANDOS_EJECUCION.md** para obtener referencias de los scripts.

Para facilitar la Integración Continua, todas las pruebas deben ejecutarse utilizando el wrapper unificado:
`./run_test.sh -t <script.jmx> -e <ambiente> -u <hilos> -r <rampup> -d <duracion>`

---

## Arquitectura CI/CD (Ejecución en Generador Remoto)

Este framework está diseñado para la **ejecución distribuida** en integración continua:
1. **Pipeline Orquestador:** Las pruebas se disparan desde herramientas como GitHub Actions o Jenkins. (Ver `.github/workflows/performance-tests.yml` o `Jenkinsfile`).
2. **Generador de Carga:** El pipeline delega la ejecución real de JMeter a un nodo generador (Self-hosted runner o Agent) que tiene la capacidad de inyectar la carga, llamando automáticamente a `run_test.sh`.
3. **Retorno de Resultados:** El generador empaqueta los resultados `.jtl` y el reporte HTML (`.tar.gz`) y el pipeline orquestador los captura como Artefactos de la ejecución para su análisis y auditoría posterior.

---

## Gestion de Datos

- **Portabilidad**: Las rutas de los archivos de datos se ajustan automaticamente segun la profundidad del script o mediante el flag `-Jdata_dir`.
- **Seguridad**: Se prohibe el almacenamiento de credenciales reales en el repositorio.
