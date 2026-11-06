# Comandos de Ejecución por Tags (Generador de Carga)

Si necesitas ejecutar las pruebas de manera manual directamente en el **Generador de Carga**, debes utilizar el script `run_by_tag.sh`. Este script ya incluye los parámetros óptimos (hilos, rampup, duración, ambiente) y gestiona la creación de las carpetas de resultados automáticamente.

> **NOTA:** Todos los comandos deben ser ejecutados estando posicionado en la raíz del repositorio (`backoffice-jmeter-framework/`).

---

## Módulos Core

### 1. Login en QA
```bash
./run_by_tag.sh login_qa
```

### 2. Login en SIL
```bash
./run_by_tag.sh login_sil
```

### 3. Dispersiones QA Cloud
```bash
./run_by_tag.sh dispersiones_qa
```

### 4. Estado de Cuenta
```bash
./run_by_tag.sh edo_cuenta
```

---

## Escenarios DRP

### 5. Flujo Crítico DRP
```bash
./run_by_tag.sh drp_flujo_critico
```

---

## Optimizaciones - Paquete 1

### 6. Métodos General (Paquete 1)
```bash
./run_by_tag.sh opt1_metodos_general
```

### 7. Autorizar Traspaso / Get Traspasos
```bash
./run_by_tag.sh opt1_autorizar_traspaso
```

### 8. Get Cuentas
```bash
./run_by_tag.sh opt1_get_cuentas
```

### 9. Get Cuentas Traspasos
```bash
./run_by_tag.sh opt1_get_cuentas_traspasos
```

### 10. Get Destinatarios Autorizados Page In DB
```bash
./run_by_tag.sh opt1_get_destinatarios
```

### 11. Get Estado Cuenta PDF / MT940 / Movimientos
```bash
./run_by_tag.sh opt1_get_estado_cuenta_pdf
```

### 12. Get Movimientos
```bash
./run_by_tag.sh opt1_get_movimientos
```

### 13. Get Traspasos Comprobantes
```bash
./run_by_tag.sh opt1_get_traspasos_comprobantes
```

### 14. Load Archivo Lote Base64
```bash
./run_by_tag.sh opt1_load_archivo_lote
```

### 15. Validate Cuenta / Notices / Login / Logout
```bash
./run_by_tag.sh opt1_validate_cuenta
```

---

## Optimizaciones - Paquete 2

### 16. Métodos General (Paquete 2)
```bash
./run_by_tag.sh opt2_metodos_general
```

### 17. Add Destinatario
```bash
./run_by_tag.sh opt2_add_destinatario
```

### 18. Capturar Traspaso Masivo / Autorizar / Get
```bash
./run_by_tag.sh opt2_capturar_traspaso
```

### 19. Get Estado Cuenta PDF / MT940 (Paquete 2)
```bash
./run_by_tag.sh opt2_get_estado_cuenta_pdf
```

### 20. Get Traspasos Comprobantes (Paquete 2)
```bash
./run_by_tag.sh opt2_get_traspasos_comprobantes
```
