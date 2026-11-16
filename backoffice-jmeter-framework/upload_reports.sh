#!/bin/bash
# backoffice-jmeter-framework/upload_reports.sh
# Sube todos los resultados de Backoffice a Google Drive

echo "Subiendo todos los resultados de Backoffice..."
for dir in results/Ejecucion_*; do
    if [ -d "$dir" ]; then
        bash "../scripts/upload_to_drive.sh" "$dir" "$(basename "$dir")" "Backoffice"
    fi
done
