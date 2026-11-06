#!/bin/bash
# {{PROJECT_FOLDER}}/upload_reports.sh
# Sube todos los resultados de {{APP_NAME}} a Google Drive

echo "Subiendo todos los resultados de {{APP_NAME}}..."
for dir in results/Ejecucion_*; do
    if [ -d "$dir" ]; then
        bash "../scripts/upload_to_drive.sh" "$dir" "$(basename "$dir")" "{{APP_NAME}}"
    fi
done
