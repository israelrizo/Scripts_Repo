#!/bin/bash
# baseinet-jmeter-framework/upload_reports.sh
# Sube todos los resultados de BASEInet a Google Drive

echo "Subiendo todos los resultados de BASEInet..."
for dir in results/Ejecucion_*; do
    if [ -d "$dir" ]; then
        bash "../scripts/upload_to_drive.sh" "$dir" "$(basename "$dir")" "BASEInet"
    fi
done
