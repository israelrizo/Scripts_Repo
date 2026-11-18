# JMeter Control Center — Instalación, credenciales, uso y desinstalación

| | |
|---|---|
| **Audiencia** | Ingenieros de Performance (Windows y macOS) |
| **Video** | `JMeter_Control_Center_Tutorial.mp4` (mismo orden que este documento) |
| **Tiempo** | 20–30 min la primera vez |
| **Regla de oro** | Instale y desinstale **con su usuario normal**: nunca `sudo` (macOS) ni *Ejecutar como administrador* (Windows). |

---

## 1. Qué se instala y dónde

El Control Center corre **en su computadora** (`http://localhost:8090`). Desde ahí enciende y apaga el Master y los
Slaves en AWS, **copia el proyecto desde su clon local** a los servidores (SSH dentro de SSM; los servidores no
necesitan acceso a Bitbucket), lanza la prueba, muestra la consola y las gráficas en vivo y descarga el reporte.

| Elemento | Dónde queda |
|----------|-------------|
| Aplicación | `<su clon>/webapp` (dentro del repositorio `jmeter-framework` de Bitbucket) |
| Entorno de Python | `webapp/.venv` (se crea solo) |
| Configuración, usuarios, tokens cifrados, historial, reportes | `webapp/instance` (nunca se sube a Git) |
| Servicio en segundo plano | macOS: LaunchAgent `com.bancobase.jmeter-control-center` · Windows: Programador de tareas `\JMeterControlCenter\` |
| Llave SSH | `~/.ssh/id_ed25519` (Windows: `C:\Users\<usuario>\.ssh\id_ed25519`) |

---

## 2. Requisitos

| Herramienta | Windows | macOS |
|-------------|---------|-------|
| Python 3.9+ | El instalador lo ofrece con *winget* (**no** use el acceso directo de Microsoft Store) | Incluido / `brew install python` |
| Git | El instalador lo ofrece con *winget* | `xcode-select --install` |
| AWS CLI v2 + Session Manager plugin | El instalador los ofrece con *winget* | Instaladores `.pkg` de AWS |
| Cliente OpenSSH | *Configuración → Sistema → Características opcionales → Cliente OpenSSH* | Incluido |
| JMeter 5.6.3 (opcional, para abrir scripts en GUI) | Carpeta de JMeter | Carpeta de JMeter |

---

## 3. Instalación

### 3.1 Clonar el repositorio (una vez)

1. Bitbucket → su avatar → **Personal settings → API tokens** (o *id.atlassian.com → Security → Create API token
   with scopes*, aplicación **Bitbucket**, permisos `read:repository` y `write:repository`). Copie el token.
2. Clone con **su usuario de Bitbucket** (no el correo) y pegue el token cuando pida la contraseña:

   ```
   git clone https://<su-usuario>@bitbucket.org/<workspace>/jmeter-framework.git
   ```

3. Autor de sus commits: `git config user.name "Su Nombre"` y `git config user.email "su-correo@bancobase.com"`.

### 3.2 Windows

1. Abra la carpeta `jmeter-framework\webapp\tools\service` en el Explorador.
2. Doble clic en **`install_windows.cmd`** (no *Ejecutar como administrador*).
   * Evita el error *"running scripts is disabled on this system"* sin cambiar ninguna política del equipo.
   * Si falta Python, Git, AWS CLI o Session Manager plugin, responde **Y** para instalarlos con *winget*
     (Windows puede pedir confirmación para alguno).
   * Pide el **usuario y contraseña del Control Center** (locales a su equipo; usted será *admin*).
   * Ofrece **crear su llave SSH** si no tiene una.
   * Crea el servicio en segundo plano y los accesos directos **JMeter Control Center** (Inicio y Escritorio).
3. Se abre el navegador en `http://localhost:8090`.

> Si ve *"no se encontró Python; ejecutar sin argumentos para instalar desde Microsoft Store"*, es el acceso directo
> de la Tienda, no Python. El instalador lo ignora y ofrece instalar Python real. También puede desactivarlo en
> *Configuración → Aplicaciones → Configuración avanzada de aplicaciones → Alias de ejecución de aplicaciones*.

### 3.3 macOS

En Terminal, **sin sudo**:

```
cd ~/Documents/BitBucket/jmeter-framework/webapp
./tools/service/install_macos.sh
./tools/launcher/build_macos_app.sh      # ícono en Launchpad / Dock (opcional)
```

El instalador crea el entorno, su usuario, su llave SSH (si no existe), el servicio y abre el navegador. Al final
pregunta si permite **despertar la Mac** antes de una ejecución programada (pide su contraseña una sola vez).

---

## 4. Credenciales y configuración (una vez por equipo)

| # | Credencial | Dónde se obtiene | Dónde se captura |
|---|-----------|------------------|------------------|
| 1 | **Usuario del Control Center** | Lo crea el instalador | Pantalla de inicio de sesión (2FA opcional en *My account*) |
| 2 | **Perfil de AWS (SSO)** | `aws configure sso` (URL de inicio de SSO, región, cuenta y rol *Performance-Engineering*) | *Settings → AWS → AWS profile* + *Region* |
| 3 | **Llave SSH** | La crea el instalador o *Settings → AWS → Create SSH key* | Automático: la app la instala en los servidores por SSM |
| 4 | **Contraseña de aplicación de Google** | myaccount.google.com/apppasswords (requiere verificación en 2 pasos) | *Settings → E-mail* (host `smtp.gmail.com`, puerto 587, `starttls`) |
| 5 | **Webhook de Google Chat** | Espacio → *Apps e integraciones → Webhooks* | *Settings → Google Chat spaces* |
| 6 | **Token de Atlassian** (Confluence / Jira / Bitbucket) | id.atlassian.com → *Security → API tokens* | Menú superior **Atlassian** (*My Atlassian connections*) |
| 7 | **New Relic User key** (`NRAK-…`) | one.newrelic.com → *API keys → Create a key → User* | *Settings → New Relic* (una vez, cuenta compartida) |
| 8 | **Ruta de JMeter** (opcional) | Carpeta donde instaló JMeter | Su usuario (arriba a la derecha) → *My account → JMeter on this computer* |

### 4.1 AWS (SSO)

```
aws configure sso                 # nombre de perfil sugerido: performance
aws sso login --profile performance
```

En el Control Center: **Settings → AWS**

1. Marque *Run tests on the AWS servers*.
2. *AWS profile* = `performance`, *Region* = región de los generadores.
3. *Master instance id* y *Slave instance ids* (los comparte el líder del equipo).
4. *Linux user* = `ubuntu`, *Scripts folder* = `/mnt/jmeter/JMeter_Scripts/jmeter-framework`.
5. *How scripts reach the servers* = **Copy from this computer**; *Tests at the same time* = **3**.
6. **Save** → **Test connection**: debe mostrar *Master via SSM* y *Master via SSH (push sync): OK*.

Cuando la sesión de AWS expire, use **Servers → AWS SSO login** (abre el navegador).

Permisos de IAM que necesita su rol (los configura el administrador de AWS): `ec2:DescribeInstances`,
`ec2:StartInstances`, `ec2:StopInstances`, `ssm:SendCommand` (instancias + documento `AWS-RunShellScript`),
`ssm:GetCommandInvocation`, `ssm:DescribeInstanceInformation`, `ssm:StartSession` (documentos
`AWS-StartPortForwardingSession` y `AWS-StartSSHSession`), `ssm:TerminateSession`, `ssm:ResumeSession`,
`sts:GetCallerIdentity`.

### 4.2 Correo (contraseña de aplicación)

1. Cuenta de Google → **Seguridad → Verificación en 2 pasos** (activada).
2. **myaccount.google.com/apppasswords** → nombre *JMeter Control Center* → **Crear** → copie los 16 caracteres.
3. **Settings → E-mail**: *Enabled*, host `smtp.gmail.com`, puerto `587`, `starttls`, su correo y la contraseña de
   aplicación (los espacios se quitan solos) → **Save** → **Send test**.

### 4.3 Google Chat

Espacio del equipo → **Apps e integraciones → Webhooks → Agregar** → copie la URL → **Settings → Google Chat
spaces → Add** (márquelo *default*). Los espacios de cada proyecto se eligen en *proyecto → Settings*.

### 4.4 Atlassian y New Relic

* Menú **Atlassian** (*My Atlassian connections*): URL de Confluence/Jira, su correo y el token de id.atlassian.com; para Bitbucket su usuario
  y un API token con permisos de repositorio y *pull requests* (shift-left).
* **Settings → New Relic** (admin, una vez): Account ID, región y la *User key* `NRAK-…` → **Test connection**.

---

## 5. Uso diario

| Acción | Cómo |
|--------|------|
| **Ejecutar rápido** | <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>K</kbd> → escriba el tag → <kbd>Enter</kbd> → <kbd>Enter</kbd> |
| Ejecutar desde el proyecto | *Projects → proyecto → Tags → ▶ Run*. Por defecto solo en el **Master**; marque *Distributed* para usar los Slaves |
| Límites | Hasta **3 proyectos a la vez** en el Master, **una ejecución por proyecto**; los Slaves atienden una prueba distribuida a la vez |
| Encender / apagar servidores | *Servers* (o la casilla *Start the servers if they are stopped* del diálogo). Se apagan solos a las **18:00** |
| Ver en vivo | Página de la ejecución (consola + gráficas) o *Live monitor*; Grafana con **Open ↗** en *Servers → Tunnels* |
| Reportes | *proyecto → Reports* (HTML, comparación con la línea base, reporte de Confluence) |
| Calidad del script | Al subir un `.jmx` y en la pestaña *Quality* (reglas R01–R20) |
| Programar | *Schedules* (el servicio enciende los servidores y lanza la prueba aunque la app esté cerrada) |
| Compartir cambios | *Git* → commit & push (la ejecución copia su versión local, incluso sin commit) |

---

## 6. Actualizar

1. `git pull` en su clon (o descomprima el paquete de actualización en la raíz del repositorio).
2. Windows: doble clic en **`install_windows.cmd`** (repara y actualiza; conserva su configuración).
   macOS: `./tools/service/install_macos.sh` (sin sudo).

---

## 7. Desinstalar y reinstalar (sin errores)

### Windows

| Situación | Acción |
|-----------|--------|
| Quitar el servicio y accesos directos (conserva configuración) | Doble clic en **`uninstall_windows.cmd`** |
| La reinstalación falla | `uninstall_windows.cmd -Purge` (borra `.venv`) y luego `install_windows.cmd` |
| Se instaló antes *como administrador* | `uninstall_windows.cmd -Elevated` (acepte el aviso de UAC) y luego `install_windows.cmd` normal |
| Borrar todo (configuración, tokens, historial) | `uninstall_windows.cmd -RemoveData` (pide escribir `DELETE`) |

Para pasar opciones: abra *Símbolo del sistema* en `webapp\tools\service` y escriba, por ejemplo,
`uninstall_windows.cmd -Purge`.

### macOS

| Situación | Acción |
|-----------|--------|
| Quitar el servicio | `./tools/service/uninstall_macos.sh` |
| La reinstalación falla | `./tools/service/uninstall_macos.sh --purge` y luego `./tools/service/install_macos.sh` |
| Se instaló antes con `sudo` (*Bootstrap failed: 125*) | Ejecute `./tools/service/install_macos.sh` **sin sudo**: detecta los archivos de *root* y ofrece devolverlos a su usuario |
| Borrar todo | `./tools/service/uninstall_macos.sh --remove-data` (pide escribir `DELETE`) |

---

## 8. Problemas frecuentes

| Mensaje | Solución |
|---------|----------|
| *running scripts is disabled on this system* | Use `install_windows.cmd` (doble clic), no el `.ps1` directamente |
| *no se encontró Python…Microsoft Store* | El instalador ofrece Python real con *winget*; o desactive el alias de la Tienda |
| *This window runs as Administrator* | Cierre la ventana y use una normal |
| *Bootstrap failed: 125* (macOS) | Se usó `sudo`: ejecute el instalador sin sudo |
| *AccessDenied … ssm:SendCommand / StartSession* | Falta un permiso en su rol de AWS (sección 4.1) |
| *the server rejected your SSH key* | *Settings → AWS → Test connection*; si su llave tiene contraseña, cárguela en `ssh-agent` |
| *Unknown host name* | Abra la app como `http://localhost:8090` |
| *X is already running…one execution per project* | Espere a que termine o deténgala desde su página |

## 9. Responsables

| Rol | Responsable |
|-----|-------------|
| Administración del Control Center y de la cuenta de New Relic | Líder de QA Performance |
| Permisos de AWS (IAM / SSO) | Administrador de AWS |
| Altas y bajas de llaves SSH en los servidores | Líder de QA Performance |
