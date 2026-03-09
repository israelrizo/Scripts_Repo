# Scripts_Repo — JMeter Performance Tests (Banca Cloud)

Repositorio centralizado de scripts de pruebas de rendimiento para la plataforma **Banca Cloud (Baseinet)**, implementados con **Apache JMeter**. Los scripts simulan flujos reales de usuarios bancarios para evaluar la estabilidad, capacidad y tiempos de respuesta de los servicios.

---

## 📁 Estructura del Repositorio

La estructura ha sido organizada para separar los scripts por procesos de negocio y módulos del sistema.

```
Scripts_Repo/
├── README.md
├── .gitignore
├── .github/pull_request_template.md  # Template para envíos de scripts
├── data/                             # Archivos CSV de usuarios y configuración
└── tests/
    └── scripts/
        └── Baseinet/
            ├── BASEInet-Login/              # Flujos puros de autenticación
            ├── BASEInet-EstadoDeCuenta/     # Consultas de movimientos y EDO-Cuenta
            ├── BASEInet-DispersionesCRUD/   # Flujos de dispersión y CRUD de destinatarios
            └── BASEInet-Optimizaciones/     # Módulos optimizados (MCD)
                ├── Cuentas Digitales/
                ├── Inicio/
                ├── Modulo Autorizaciones/
                ├── Modulo Consultas/
                └── PF Web/
```

---

## 🗂️ Módulos de Scripts

### 🔑 Autenticación (BASEInet-Login)
Scripts para pruebas de carga en el proceso de login en distintos ambientes.
- `G1_BASEINET_CLOUD_LOGIN_STG_v7.jmx` (STG)
- `G1_BASEINET_CLOUD_LOGIN_UTG_v7.jmx` (UTG)
- `G1_SIL_LOGIN_v1.jmx` (Módulo SIL)

### 📊 Consultas (BASEInet-EstadoDeCuenta)
- `G1_BASEINET_CLOUD_LOGIN_MOV_EDO-CUENTA_v7.jmx`: Flujo que incluye login, consulta de movimientos y descarga de PDF de estado de cuenta.

### 💳 Dispersiones y Destinatarios (BASEInet-DispersionesCRUD)
Flujos de operación de negocio y administración de cuentas destino.
- `G2_..._DESTINDIVIDUAL_CRUD.jmx`
- `G2_..._DISPERSIONES_V1-V3.jmx`
- `G2_..._DISPERSIONES_TC_V1-V4.jmx`

### ⚡ Optimizaciones MCD (BASEInet-Optimizaciones)
Scripts optimizados para alta concurrencia en microservicios específicos. Divididos por submódulos.
> 📄 **Ver [Matriz de Casos de Prueba - Optimizaciones](tests/scripts/Baseinet/BASEInet-Optimizaciones/MATRIZ_PRUEBAS_OPTIMIZACIONES.md)**

- **Cuentas Digitales**: Consulta de destinatarios autorizados, traspasos, carga de lotes (`CdLoadArchivoLoteBase64`).
- **Modulo Consultas**: Movimientos MCD, estados de cuenta MT940 y PDF.
- **Modulo Autorizaciones**: Autorización de traspasos SPEI.
- **Inicio**: Flujos simplificados de Login/Logout para pruebas de estrés de sesión.

---

## ⚙️ Pre-requisitos

1. **Apache JMeter** `>= 5.5`
2. **Java** `>= 11`
3. **Plugins Manager**: Se recomienda instalar el JMeter Plugins Manager para manejar dependencias de hilos (Stepping Thread Group, etc.).

---

## 🚀 Cómo Ejecutar los Scripts

Para asegurar que los scripts encuentren los datos correctamente, **siempre ejecuta JMeter desde la raíz del repositorio**.

### Modo No-GUI (Recomendado para pruebas reales)
```bash
jmeter -n \
  -t tests/scripts/Baseinet/BASEInet-Login/G1_BASEINET_CLOUD_LOGIN_STG_v7.jmx \
  -l results/resultado.jtl \
  -e -o results/report/
```

---

## 📊 Datos y Resultados

- **Datos de entrada**: Siempre en la carpeta `data/`. Los scripts ya están configurados con rutas relativas (`data/usuarios_...csv`).
- **Resultados**: Se recomienda guardar los archivos `.jtl` y reportes HTML en una carpeta `results/` no rastreada por Git.

> ⚠️ **IMPORTANTE**: No incluyas credenciales reales en las cargas a Git. El archivo `.gitignore` ya está configurado para proteger archivos de datos sensibles.

---

## 📝 Contribución

Al agregar un nuevo script o modificar uno existente:
1. Crea una rama descriptiva (`feature/nuevo-script`).
2. Sigue la convención de nombres: `G<Grupo>_<Paquete>_<Script>_<Ambiente>_<Descripcion>.jmx`.
3. Abre un Pull Request utilizando el template predefinido para documentar el flujo y la configuración de carga.
