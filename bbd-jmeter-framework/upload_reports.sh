#!/bin/bash
# bdt-jmeter-framework/upload_reports.sh
# Sube todos los resultados de BDT a Google Drive

echo "Subiendo todos los resultados de BDT..."
for dir in results/Ejecucion_*; do
    if [ -d "$dir" ]; then
        bash "../scripts/upload_to_drive.sh" "$dir" "$(basename "$dir")" "BDT"
    fi
done
