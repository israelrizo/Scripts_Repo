# Guía de Scripting JMeter y Uso del JMeter Control Center

| **Metadato** | **Valor** |
| --- | --- |
| Versión del documento | 2.0 |
| Aplica a | Apache JMeter 5.6.3 · JMeter Control Center (repositorio Scripts_Repo) |
| Responsable | QA Performance — qaperformance@bancobase.com |
| Fecha de actualización | {dd/mm/aaaa} |
| Estado | {Borrador / Publicado} |
| Documento base | Mejores prácticas de scripting (JMeter) v1 |

##  Introducción

Este documento establece los estándares para crear, mantener y ejecutar scripts de pruebas de performance con **Apache JMeter 5.6.3** dentro del **JMeter Control Center**. Integra las mejores prácticas de scripting vigentes con las reglas que la herramienta revisa automáticamente (**R01–R20**), de modo que cada script publicado en el repositorio pueda ejecutarse de forma distribuida (Master + 2 Slaves), producir métricas en vivo y generar su reporte de resultados sin ajustes manuales.

**Instrucciones:** Los marcadores entre llaves `{ }` se reemplazan al publicar en Confluence. Las reglas marcadas como **Error** bloquean la calidad mínima del script; las **Advertencias** deben corregirse antes de una prueba formal; las **Sugerencias** mejoran la mantenibilidad.

---

##  1. Configuración Inicial

###  1.1. JMeter en el equipo del ingeniero

Antes de crear scripts, asegúrese de que el entorno de JMeter esté configurado correctamente.

| **Recurso** | **Descripción / Enlace** |
| --- | --- |
| Guía de Instalación | [QA - Instalación JMeter en Generador de Carga](https://docs.google.com/document/d/18ezc7fBEDGYVJPisBymaYbM2E9x9aghJljhDRJ6YjyQ/edit?usp=sharing) |
| Versión | **Apache JMeter 5.6.3** (la misma en el equipo, el Master y los Slaves, con los mismos plugins). |
| Java | **JDK 8 o superior** instalado y configurado (recomendado JDK 17). |
| Hardware recomendado | **CPU multinúcleo**, **16+ GB** de **RAM** y **SSD**. |

###  1.2. JMeter Control Center

| **Paso** | **Detalle** |
| --- | --- |
| Clonar el repositorio | `git clone -b <rama> <url-del-repositorio>` en su equipo (macOS o Windows). |
| Instalar la aplicación | **macOS:** `webapp/tools/service/install_macos.sh` · **Windows:** `webapp\tools\service\install_windows.ps1`. Instala el servicio en segundo plano (las programaciones se ejecutan sin abrir la aplicación) y el acceso directo con icono. |
| Abrir | Acceso directo **JMeter Control Center** → `http://localhost:8090`. |
| AWS | **Settings → AWS:** perfil de AWS con acceso SSM, región, IDs de las instancias Master y Slaves, usuario y carpeta de scripts en los servidores, llave SSH (`~/.ssh/id_ed25519`), apagado automático `18:00`. Botón **Test connection**. Cada ejecución copia el proyecto **desde su clon local** a los servidores (los servidores no acceden a Bitbucket): mantenga su trabajo con *commit* y *push*. |
| JMeter local | **Account → JMeter on this computer:** ruta de su instalación de JMeter (habilita el botón **✎ JMeter** para abrir scripts en modo GUI). |
| Notificaciones | **Settings → E-mail:** su correo + una *contraseña de aplicación* de Google (SMTP). **Google Chat:** espacios por defecto y por proyecto. |
| Integraciones | **Atlassian:** Confluence, Jira y Bitbucket con sus propios tokens. **Settings → New Relic:** cuenta compartida del equipo. |

**Nota:** Los servidores generadores se apagan automáticamente todos los días a las **18:00 hrs**. El Control Center los enciende cuando una ejecución lo requiere y puede apagarlos al terminar.

---

##  2. Estructura del Script y Nomenclatura

Una nomenclatura clara y consistente es crucial para la mantenibilidad y para que los reportes, tags y tableros se lean igual en todos los proyectos.

###  2.1. Estructura del repositorio

| **Carpeta / Archivo** | **Contenido** |
| --- | --- |
| `<app>-jmeter-framework/tests/<Modulo>/` | Scripts `.jmx` agrupados por módulo, escenario u optimización. |
| `<app>-jmeter-framework/data/` | Archivos de datos (CSV/TXT). **Sin credenciales productivas.** |
| `<app>-jmeter-framework/run_by_tag.sh` | Diccionario de **tags**: cada script ejecutable tiene un tag y sus `EXTRA_ARGS`. |
| `<app>-jmeter-framework/results/` | Resultados por ejecución (`Ejecucion_<DDMMAA_HHMMSS>_<Script>`). No se versiona. |

###  2.2. Convención de nombres

| **Elemento** | **Formato de Nomenclatura** | **Ejemplo** |
| --- | --- | --- |
| Scripts | `ScriptXX_Ambiente_AppName_TestScriptObjective` | `Script01_QA_BaseInet_TransferenciaSPEI.jmx` |
| Transacciones | `ScriptXX_Ambiente_AppName_TestScriptObjectivo_TXX_DescripcionDelPaso` | `Script01_QA_BaseInet_TransferenciaSPEI_T01_AbrirPaginaInicio` |
| Parámetros | `P_ParameterName` | `P_UserName` |
| Correlaciones | `C_CorrelationName` | `C_AccessToken` |
| Tags (`run_by_tag.sh`) | `<app>_<modulo>_<tipo>` en minúsculas | `baseinet_spei_load` |
| Thread Groups | `TG_<TipoDeUsuario>` | `TG_ClienteEmpresarial` |

| **Prefijo / Elemento** | **Descripción** |
| --- | --- |
| **Ambiente** | QA, QA2 (DRP, SIL cuando aplique). |
| **XX en ScriptXX** | Número de secuencia del script (01, 02…). |
| **XX en TXX** | Número de secuencia de la transacción dentro del script (01, 02…). |
| **P_** | Variable de **P**arámetro (CSV Data Set Config o User Defined Variables). |
| **C_** | Variable de **C**orrelación (extraída durante la ejecución del script). |

**Nota:** Los scripts con la convención anterior (`G1_`, `G2_`) se renombran al modificarlos; actualice su tag en `run_by_tag.sh` en el mismo commit. *(Regla R01)*

###  2.3. Transacciones (Controllers)

| **Recomendación** | **Detalle** |
| --- | --- |
| Uso de Controllers | Utilice **Transaction Controller** (o Recording Controller) para agrupar las peticiones HTTP de un paso funcional único. |
| Nomenclatura | Siga la convención de transacciones (`…_TXX_DescripcionDelPaso`). *(R10)* |
| Generate Parent Sample | Marque **«Generate parent sample»** para que el reporte muestre la transacción y no cada request suelto. *(R10)* |
| Nombres únicos | No repita nombres de samplers: si se repiten, el reporte mezcla sus estadísticas. *(R10)* |

---

##  3. Manejo de Variables y Datos

| **Acción** | **Detalle** |
| --- | --- |
| Lectura de datos | Utilice **CSV Data Set Config** para los datos de prueba. |
| Prefijo P_ | Siempre use el prefijo **P_** en las columnas del CSV y variables de parámetro. *(R19)* |
| Ruta de los datos | Use **`${__P(data_dir,data)}/archivo.csv`**. El Control Center envía `data_dir` con la ruta absoluta del proyecto, igual en Master y Slaves. **Nunca** rutas de Windows (`C:\…`) ni absolutas. *(R04)* |
| Archivo presente | El CSV debe existir en `data/` del proyecto y estar en el repositorio. *(R04)* |
| No codificar datos sensibles | **No** codifique contraseñas, tokens ni `Authorization: Bearer/Basic` en el script: obténgalos en un paso previo (correlación) o desde el CSV / propiedades. *(R14 — Error)* |
| Variables de entorno | Use **User Defined Variables** con propiedades: `P_DNS = ${__P(P_DNS,apibdt.q.gslb)}`, `P_PORT = ${__P(P_PORT,443)}`. Así el mismo script corre en QA, QA2 o DRP cambiando solo los `EXTRA_ARGS` del tag. *(R11)* |
| Datos por usuario | Si un usuario no puede iniciar sesión dos veces, use un CSV con suficientes registros o divídalo por slave. |

###  3.2. Correlación

La correlación es el proceso de capturar datos dinámicos de las respuestas del servidor para reutilizarlos en peticiones subsiguientes.

| **Tarea** | **Detalle** |
| --- | --- |
| Captura de valores | Utilice **Regular Expression Extractor**, **JSON Extractor**, **Boundary Extractor** o **XPath Extractor**. |
| Prefijo C_ | Siempre use el prefijo **C_** para las variables de correlación. *(R20)* |
| Verificación | Valide la extracción con **Debug PostProcessor** y **View Results Tree** en modo GUI, y **deshabilítelos antes de publicar**. *(R06, R07)* |
| Valor por defecto | Defina un valor por defecto (p. ej. `C_AccessToken_NOT_FOUND`) y una aserción para detectar fallas de correlación. |

---

##  4. Estándares de Diseño del Script

###  4.1. Limpieza del Script

| **Práctica** | **Detalle** |
| --- | --- |
| Deshabilitar elementos no esenciales | Deshabilite o elimine listeners (View Results Tree, Summary/Aggregate Report, gráficas) antes de una prueba de carga: consumen memoria/CPU del generador. El reporte HTML lo genera el Control Center. *(R06 — View Results Tree habilitado es Error)* |
| Debug | Debug Sampler / Debug PostProcessor deshabilitados. *(R07)* |
| Modo funcional | **«Functional Test Mode»** del Test Plan desmarcado. *(R15 — Error)* |
| Elementos deshabilitados | Elimine lo que ya no se usa (queda en el historial de git). *(R17)* |
| Descripción | Complete **Comments** del Test Plan: objetivo, endpoints, datos requeridos, autor, fecha y ticket. *(R18)* |

###  4.2. Parametrización de la carga

| **Elemento** | **Valor obligatorio** | **Motivo** |
| --- | --- | --- |
| Número de hilos | `${__P(threads,1)}` | Ajustar la carga desde el run, el tag o la programación sin editar el script. *(R03 — Error si es fijo)* |
| Ramp-up | `${__P(rampup,1)}` | *(R03)* |
| Duración | `${__P(duration,60)}` (con «Specify Thread lifetime») | *(R03)* |
| Think time | `${__P(P_tt,1000)}` | *(R08)* |

**Nota sobre ejecución distribuida:** cada Slave ejecuta el número completo de hilos. Con 2 Slaves, `threads=50` genera **100 usuarios**. Divida la carga objetivo entre el número de Slaves.

###  4.3. HTTP Request Defaults

| **Práctica** | **Detalle** |
| --- | --- |
| Default HTTP Request | Configure un **HTTP Request Defaults** al inicio del Thread Group con protocolo, `${P_DNS}` y `${P_PORT}`. Los requests dejan el servidor vacío. *(R11)* |
| Timeouts | Connect `10000` ms y Response `60000` ms (ajustar por servicio) para no dejar hilos colgados. *(R11)* |
| Recursos embebidos | «Retrieve All Embedded Resources» desactivado, salvo pruebas de front. *(R12)* |
| Cookies | **HTTP Cookie Manager** cuando la aplicación maneja sesión por cookies. *(R13)* |

###  4.4. Think time y aserciones

| **Práctica** | **Detalle** |
| --- | --- |
| Think time | Al menos un timer (Uniform Random Timer con `${P_tt}` o Constant Throughput Timer) para representar usuarios reales. *(R08)* |
| Aserciones | Response Assertion (código + texto clave) o JSON Assertion en cada transacción crítica: una respuesta 200 con error de negocio no debe contar como éxito. *(R09)* |

###  4.5. Métricas en vivo (Backend Listener)

| **Argumento** | **Valor** | **Motivo** |
| --- | --- | --- |
| Implementación | `InfluxdbBackendListenerClient` (uno solo, a nivel Test Plan) | Live monitor, Grafana y gráficas del reporte. *(R05)* |
| influxdbUrl | `${__P(influx_url,http://<IP-privada-Master>:8086/write?db=<APP>_QA)}` | Con `localhost`, los Slaves envían a su propio equipo y se pierden las métricas. *(R05 — Error)* |
| application | `<APP>_<AMBIENTE>` (p. ej. `BlackList_QA`) | Filtro del Live monitor y Grafana. *(R05)* |
| measurement | `jmeter` | Estándar de los tableros. |
| percentiles | `90;95;99` | El reporte usa p95. *(R05)* |
| TAG_host | `${__machineName()}` | Sin este tag las series de los 2 Slaves se sobreescriben. *(R05)* |

###  4.6. Asignación de Recursos

| **Recomendación** | **Detalle** |
| --- | --- |
| Mantener Threads separados | Use **Thread Groups separados** para simular diferentes tipos de usuarios o flujos de trabajo; permite una mejor gestión de la carga y del reporte. |
| Un objetivo por script | Un script = un escenario medible. Use tags distintos para smoke, carga, estrés o escalabilidad del mismo script mediante `EXTRA_ARGS`. |

---

##  5. Flujo de Trabajo con el JMeter Control Center

| **Paso** | **Dónde** | **Detalle** |
| --- | --- | --- |
| 1. Crear o actualizar el script | **✎ JMeter** (pestañas Tags / Scripts) | Abre el `.jmx` en su JMeter local con las propiedades del tag y `data_dir`. Guarde en la misma ruta. |
| 2. Revisar calidad | Pestaña **Quality** | Puntaje 0–100 y hallazgos R01–R20 con la corrección sugerida. Descargue el feedback en `.md`. |
| 3. Subir datos | Pestaña **Data files** | CSV/TXT a `data/`. |
| 4. Registrar el tag | Pestaña **Tags → Register tag** | Tag + `EXTRA_ARGS` (`-Jthreads=… -Jrampup=… -Jduration=… -JP_DNS=…`). |
| 5. Publicar | Página **Git** | Commit & push. Los scripts con errores de calidad requieren confirmación explícita. **Nada se ejecuta en los servidores si no está en el repositorio.** |
| 6. Validar conectividad | **Servers** (botón por tag) | DNS, TCP, TLS y HTTP de cada host del script, revisados desde el Master. |
| 7. Ejecutar | **▶ Run** | Por defecto solo en el Master; marque *Distributed* para usar los Slaves. Hasta **3 proyectos a la vez** en el Master y **una ejecución por proyecto**; los Slaves atienden una prueba distribuida a la vez. Opción de encender los servidores, ticket de Jira, notas, destinatarios extra y apagado al terminar. |
| 8. Monitorear | Página del run / **Live monitor** / **Grafana** | Consola en vivo, usuarios, hits/s, errores, p95, códigos de respuesta y métricas APM de **New Relic**. |
| 9. Analizar | **Reports → Compare** | Comparación contra la línea base (umbral de regresión, tendencia, CSV). |
| 10. Reportar | **Reports → Confluence** | Reporte de resultados con la plantilla oficial, gráficas, New Relic en *Recursos Servidor* y adjuntos. |

| **Funcionalidad** | **Uso recomendado** |
| --- | --- |
| Programaciones (**Schedules**) | Pruebas nocturnas o de regresión: encienden los generadores, ejecutan y pueden apagarlos. Requieren el servicio en segundo plano instalado y el equipo conectado a corriente. Evite que una prueba larga cruce las **18:00**. |
| Servidores (**Servers**) | Estado, encendido/apagado, quién está usando el Master (espacios ocupados de 3), health check, copia de los scripts desde su equipo y túneles (Grafana 3000, InfluxDB 8086, otros). |
| Notificaciones | Correo desde su cuenta vía SMTP (con el reporte HTML adjunto), Google Chat y comentario en el ticket de Jira al terminar. |
| Shift-left | **project → Settings → Open PR in Bitbucket** agrega un *performance gate* al repositorio de la aplicación. |

---

##  6. Revisión Automática de Calidad (R01–R20)

El Control Center revisa cada script al subirlo, en la pestaña **Quality**, antes del commit (página **Git**) y en cada push al repositorio (GitHub Actions *JMX quality review*).

| **Regla** | **Severidad** | **Qué revisa** |
| --- | --- | --- |
| R01 | Advertencia / Sugerencia | Nombre `ScriptXX_Ambiente_AppName_Objetivo.jmx` (G1_/G2_ = convención anterior). |
| R02 | Advertencia | El script tiene un tag en `run_by_tag.sh`. |
| R03 | **Error** / Advertencia | Usuarios, rampa y duración con `${__P(...)}`. |
| R04 | **Error** / Advertencia | CSV con `${__P(data_dir,data)}`, sin rutas Windows/absolutas, archivo existente. |
| R05 | **Error** / Advertencia | Backend Listener InfluxDB único, sin `localhost`, con `application`, `TAG_host` y p95. |
| R06 | **Error** / Advertencia | Listeners de GUI habilitados (View Results Tree = Error). |
| R07 | Advertencia | Debug Sampler / PostProcessor habilitados. |
| R08 | Advertencia | Think time presente. |
| R09 | Advertencia | Aserciones presentes. |
| R10 | Advertencia / Sugerencia | Transaction Controllers con convención `TXX`, «Generate parent sample» y nombres únicos. |
| R11 | Advertencia / Sugerencia | HTTP Request Defaults, host parametrizado y timeouts. |
| R12 | Advertencia | Recursos embebidos desactivados. |
| R13 | Sugerencia | HTTP Cookie Manager. |
| R14 | **Error** | Contraseñas, secretos o tokens en duro. |
| R15 | **Error** | Functional Test Mode desactivado. |
| R16–R17 | Sugerencia | Tamaño del script y elementos deshabilitados. |
| R18 | Sugerencia | Descripción del Test Plan. |
| R19 | Advertencia | Parámetros con prefijo `P_`. |
| R20 | Advertencia | Correlaciones con prefijo `C_`. |

**Puntaje:** 100 − 15 por cada Error − 5 por cada Advertencia − 1 por cada Sugerencia (cada problema distinto cuenta una vez). **A** ≥ 90 · **B** ≥ 75 · **C** ≥ 55 · **D** < 55. Objetivo del equipo: **B o superior** y **cero errores** para pruebas formales.

---

##  7. Checklist antes de publicar un script

| **#** | **Verificación** | **✔** |
| --- | --- | --- |
| 1 | Nombre del script, transacciones, `P_` y `C_` según la convención. | ☐ |
| 2 | Usuarios, rampa y duración con `${__P(...)}`; think time con `${P_tt}`. | ☐ |
| 3 | HTTP Request Defaults con `${P_DNS}` / `${P_PORT}` y timeouts. | ☐ |
| 4 | CSV con `${__P(data_dir,data)}/…` y archivo en `data/`. | ☐ |
| 5 | Sin credenciales ni tokens en duro. | ☐ |
| 6 | Aserciones en las transacciones críticas; «Generate parent sample» marcado. | ☐ |
| 7 | Backend Listener con `influx_url` parametrizado, `application`, `TAG_host`, percentiles 90;95;99. | ☐ |
| 8 | Listeners, Debug y Functional Test Mode deshabilitados. | ☐ |
| 9 | Comments del Test Plan completos. | ☐ |
| 10 | Pestaña **Quality** sin errores (B o superior). | ☐ |
| 11 | Tag registrado y commit & push realizado. | ☐ |

##  8. Checklist antes de ejecutar

| **#** | **Verificación** | **✔** |
| --- | --- | --- |
| 1 | Ventana de prueba acordada con el equipo del aplicativo y ticket de Jira asignado. | ☐ |
| 2 | Conectividad validada (botón **Servers** del tag). | ☐ |
| 3 | Carga total = hilos × número de Slaves. | ☐ |
| 4 | Tiempo suficiente antes del apagado automático de las **18:00**. | ☐ |
| 5 | Prueba smoke (1 usuario) exitosa antes de la carga. | ☐ |
| 6 | Línea base identificada para la comparación. | ☐ |

---

##  9. Referencias Adicionales

| **Recurso** | **Enlace** |
| --- | --- |
| Página Oficial de Apache JMeter | [https://jmeter.apache.org/](https://jmeter.apache.org/) |
| Descargas JMeter 5.6.3 | [apache-jmeter-5.6.3.zip](https://dlcdn.apache.org//jmeter/binaries/apache-jmeter-5.6.3.zip) |
| Descarga de JDK | [https://www.oracle.com/java/technologies/javase/jdk17-archive-downloads.html](https://www.oracle.com/java/technologies/javase/jdk17-archive-downloads.html) |
| Plantilla de Reporte de Resultados | {Enlace a la página de Confluence} |
| Despliegue del JMeter Control Center | `webapp/DEPLOYMENT.md` en el repositorio |
| Funciones de JMeter (`__P`, `__machineName`) | [https://jmeter.apache.org/usermanual/functions.html](https://jmeter.apache.org/usermanual/functions.html) |

## 👥 Responsables

| **Rol** | **Nombre** | **Área / Equipo** | **Responsabilidad** | **Contacto** |
| --- | --- | --- | --- | --- |
| {Líder de Performance} | {Nombre completo} | QA Performance | Mantener esta guía y las reglas R01–R20 | qaperformance@bancobase.com |
| {Ingeniero de Performance} | {Nombre completo} | QA Performance | Aplicar la guía en cada script publicado | {Correo} |
