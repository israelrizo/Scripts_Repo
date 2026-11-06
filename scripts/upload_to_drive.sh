#!/bin/bash
# Configuración de carpeta destino en Google Drive
# Cambia este nombre por tu carpeta específica en Drive
ROOT_DRIVE_FOLDER="JMeter_Reports_Framework"

RESULTS_DIR=$1
SCRIPT_NAME=$2
APP_NAME=$3

if [ -z "$RESULTS_DIR" ]; then
    echo "Error: No se proporcionó el directorio de resultados."
    exit 1
fi

if [ -z "$APP_NAME" ]; then
    APP_NAME="General"
fi

echo "-----------------------------------------------------"
echo "Iniciando proceso de respaldo en Google Drive [$APP_NAME]..."

# 1. Intentar localizar la carpeta de Google Drive en Mac
# ... (mismo código de detección) ...
DRIVE_PATHS=(
    "$HOME/Library/CloudStorage/GoogleDrive-*"
    "$HOME/Google Drive"
    "/Volumes/GoogleDrive/My Drive"
)

TARGET_DRIVE_ROOT=""

for path in "${DRIVE_PATHS[@]}"; do
    expanded_path=$(ls -d $path 2>/dev/null | head -n 1)
    if [ -d "$expanded_path" ]; then
        TARGET_DRIVE_ROOT="$expanded_path"
        if [[ "$TARGET_DRIVE_ROOT" == *"CloudStorage"* ]] && [ -d "$TARGET_DRIVE_ROOT/My Drive" ]; then
            TARGET_DRIVE_ROOT="$TARGET_DRIVE_ROOT/My Drive"
        fi
        break
    fi
done

if [ -z "$TARGET_DRIVE_ROOT" ]; then
    echo "Aviso: No se detectó la aplicación de Google Drive instalada."
    exit 0
fi

# 2. Crear estructura de carpetas: Root/App_Name
DEST_FOLDER="$TARGET_DRIVE_ROOT/$ROOT_DRIVE_FOLDER/$APP_NAME"
mkdir -p "$DEST_FOLDER"

echo "Carpeta destino: $DEST_FOLDER"

# 3. Copiar resultados
echo "Copiando resultados..."
cp -r "$RESULTS_DIR" "$DEST_FOLDER/"

if [ $? -eq 0 ]; then
    echo "¡Respaldo en Google Drive [$APP_NAME] completado!"
    echo "-----------------------------------------------------"
else
    echo "Error al copiar a Google Drive."
fi
