## 📋 Descripción

<!-- Descripción breve y clara del cambio. ¿Qué script(s) se agregan o modifican? ¿Por qué? -->

## 🗂️ Tipo de Cambio

<!-- Marca con una `x` las opciones que aplican -->

- [ ] 🆕 Nuevo script JMeter
- [ ] 🔧 Modificación de script existente
- [ ] 📁 Reorganización / renombrado de archivos
- [ ] 📊 Actualización de archivos de datos (`tests/data/`)
- [ ] 📝 Actualización de documentación (README, etc.)
- [ ] 🐛 Corrección de bug en script

---

## 📂 Scripts Afectados

<!-- Lista los archivos .jmx que se agregan, modifican o eliminan -->

| Acción | Archivo | Grupo | Ambiente |
|--------|---------|-------|----------|
| ➕ Nuevo / ✏️ Modificado / 🗑️ Eliminado | `nombre_del_script.jmx` | G1 / G2 | QA / STG / DRP |

---

## ⚙️ Configuración del Script

<!-- Llena esta sección para scripts nuevos o con cambios en la configuración de carga -->

| Parámetro | Valor |
|-----------|-------|
| **Ambiente** (`BASE_URL`) | `web-qa.baseinet.com` / `web-drp.baseinet.com` / etc. |
| **Usuarios totales** (`num_threads`) | |
| **Rampa de subida** (`rampUp`) | |
| **Tiempo de vuelo** (`flighttime`) | |
| **Think Time** (`P_tt` ms) | |
| **Archivo de datos** | `tests/data/nombre_archivo.csv` |

---

## 🧪 Flujo de Negocio Cubierto

<!-- Describe brevemente el flujo que simula el script. Ej: Login → Consulta de destinatarios → Alta → Eliminación → Logout -->

1. 
2. 
3. 

---

## ✅ Checklist pre-merge

- [ ] El script fue probado en modo GUI (sin errores en todas las transacciones)
- [ ] El script fue probado en modo No-GUI con al menos 1 usuario virtual
- [ ] Los `TransactionController` están nombrados de forma descriptiva
- [ ] Las variables de usuario están parametrizadas con CSV (`tests/data/`)
- [ ] No hay credenciales hardcodeadas (passwords, tokens, JWTs fijos en producción)
- [ ] El archivo de datos usado **no** contiene credenciales reales de producción
- [ ] El script está ubicado en la carpeta correcta (`G1_*` o `G2_*`)
- [ ] El README fue actualizado si se agregó un script nuevo

---

## 📊 Evidencia de Ejecución

<!-- Agrega capturas de pantalla, logs de summary report, o fragmentos del .jtl que demuestren el funcionamiento correcto -->

```
# Ejemplo de salida esperada (Summary Report)
Label                        # Samples  Error%   Avg (ms)
T01_AbrirPaginaDeInicio      100        0.00%    312
T02_ValidarUsuario           100        0.00%    458
...
```

<!-- Puedes adjuntar imágenes directamente en el PR de GitHub arrastrándolas aquí -->

---

## 🔗 Contexto Adicional

<!-- Ticket de Jira, historia de usuario, o cualquier referencia relevante -->
- Jira/Ticket: `BASE-XXXX`
- Ambiente de prueba validado: 
- Fecha de ejecución de validación: 
