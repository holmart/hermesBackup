# Script para generar reporte de la ejecución del job
import csv

# Definir rutas
log_file_path = '/home/ubuntu/.hermes/leads/cron_output.log'
report_file_path = '/home/ubuntu/.hermes/leads/execution_report.csv'

# Leer el log y generar el reporte
with open(log_file_path, 'r') as log_file:
    lines = log_file.readlines()
    report_data = []
    for line in lines:
        if 'Found' in line or 'Inserted' in line or 'Error' in line:
            report_data.append(line.strip())

# Escribir el reporte en un CSV
with open(report_file_path, 'w', newline='') as report_file:
    writer = csv.writer(report_file)
    writer.writerow(['Execution Log'])  # Encabezado
    for entry in report_data:
        writer.writerow([entry])

print('Execution report generated successfully at:', report_file_path)