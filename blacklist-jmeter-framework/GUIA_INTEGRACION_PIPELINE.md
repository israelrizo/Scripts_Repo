# Guía de Integración CI/CD: Pruebas de Rendimiento BDT

Esta guía describe paso a paso cómo integrar las pruebas de carga de BDT en un pipeline de Integración Continua (como Jenkins o GitHub Actions) utilizando **Tags**. 

El objetivo es que los equipos de desarrollo y QA puedan disparar sus propias pruebas de estrés automáticamente contra sus aplicativos seleccionando el Tag deseado desde un menú desplegable.

---

## Conceptos Clave

1. **El Generador Remoto**: Es el servidor (nodo o agente) configurado específicamente con capacidad de cómputo y red para inyectar tráfico hacia BDT. **Las pruebas no se ejecutan en el servidor master del CI**.
2. **`run_by_tag.sh`**: Es el envoltorio (wrapper) que estandariza la ejecución basada en etiquetas. Ejecuta JMeter, genera la carpeta de resultados y empaqueta el reporte final sin necesidad de ingresar comandos complejos.

---

## Paso 1: Configurar el Pipeline (Ejemplo en Jenkins)

A continuación, se explica cómo funciona el `Jenkinsfile` incluido en este repositorio.

### 1.1 Definir el Agente Generador
En tu `Jenkinsfile`, asegúrate de que el bloque `agent` apunte a la etiqueta (label) correcta del servidor generador de carga.

```groovy
pipeline {
    agent { label 'generador-jmeter' } // <-- Cambia esto por el nodo real de carga
    // ...
```

### 1.2 Seleccionar el Tag mediante Parámetros (Choice)
El pipeline utiliza una lista desplegable (Choice) para permitir al usuario seleccionar la prueba sin equivocarse en la ruta.

```groovy
    parameters {
        choice(name: 'TAG', choices: ['login_qa', 'login_sil', 'dispersiones_qa', 'edo_cuenta', 'drp_flujo_critico', 'opt1_metodos_general'], description: 'Tag del script a ejecutar')
    }
```

### 1.3 Ejecución a través del Wrapper
Dentro de los `stages`, el pipeline llamará al script `run_by_tag.sh`, enviando el Tag seleccionado.

```groovy
        stage('Ejecutar Prueba en Generador') {
            steps {
                script {
                    sh """
                    ./run_by_tag.sh ${params.TAG}
                    """
                }
            }
        }
```
*No es necesario que modifiques esta sección, `run_by_tag.sh` se encarga de todo.*

---

## Paso 2: Recuperación de Resultados (Artefactos)

El framework crea un archivo comprimido `.tar.gz` que contiene:
1. El archivo crudo de resultados de JMeter (`resultado_FECHA.jtl`).
2. El dashboard HTML dinámico listo para verse en el navegador (`/html_report/index.html`).

Para que no se pierdan, Jenkins los captura. El bloque `post` del `Jenkinsfile` hace exactamente esto:

```groovy
    post {
        always {
            script {
                def tarFile = sh(script: "ls results/*.tar.gz", returnStdout: true).trim()
                if (tarFile) {
                    archiveArtifacts artifacts: "${tarFile}", allowEmptyArchive: false
                }
            }
        }
    }
```

---

## Resumen del Flujo de Ejecución (End-to-End)

1. Un desarrollador/QA inicia el Build en Jenkins para la prueba del Aplicativo.
2. Selecciona el **Tag** deseado desde el menú desplegable (ej. `login_qa`).
3. El Máster de Jenkins envía la instrucción al **Nodo Generador**.
4. El Generador clona este repositorio y ejecuta `./run_by_tag.sh login_qa`.
5. JMeter inyecta la carga contra BDT.
6. Al finalizar, el Generador empaqueta el HTML y el `.jtl` en un `.tar.gz`.
7. Jenkins descarga el `.tar.gz` y lo adjunta a la vista del Build (Artifacts).
8. El equipo descarga el Artefacto, lo descomprime y abre el `index.html` para analizar cuellos de botella.

---

## Integración con GitHub Actions

El concepto es idéntico para GitHub Actions. El archivo `.github/workflows/performance-tests.yml` ya incluye los `inputs` de tipo `choice` con todos los tags, el `runs-on: ubuntu-latest` y utiliza `actions/upload-artifact@v4` para capturar los resultados.
