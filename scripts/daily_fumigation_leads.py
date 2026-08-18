# Corregido el error de sintaxis en el script de generación de leads
import requests
import csv
import time
from bs4 import BeautifulSoup

# Nuevos portales de servicios de fumigación para scraping
portals = [
    'https://www.fumigacionprofesionales.com/',
    'https://páginasamarillas.com.co/',
    'https://www.amarillas.com.co/',
    'https://colombia.gob.co/',
    'https://www.redbus.co/'
]

# Inicializa la lista de leads
leads = []

for portal in portals:
    print(f"=== Scraping portal: '{portal}' ===")
    try:
        response = requests.get(portal)
        response.raise_for_status()  # Asegura que la petición fue exitosa
        soup = BeautifulSoup(response.content, 'html.parser')
        # Análisis del contenido para hallar enlaces relevantes
        for a in soup.find_all('a', href=True):
            url = a['href']
            if 'fumigador' in url or 'control de plagas' in url:
                leads.append({'url': url})
        print(f'  Found {len(leads)} leads on {portal}')
    except requests.exceptions.RequestException as e:
        print(f'  Error fetching {portal}: {e}')  # Manejo de errores

# Eliminar duplicados basados en URL
unique_leads = [{'url': lead['url']} for lead in set(leads)]

# Guardar los leads en un archivo CSV
with open('/home/ubuntu/.hermes/leads/fumigation_leads.csv', 'w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(['id', 'timestamp', 'company_name', 'url', 'phone'])
    for i, lead in enumerate(unique_leads):
        writer.writerow([i, time.strftime('%Y-%m-%d %H:%M:%S'), f'Empresa {i}', lead['url'], ''])

print(f'Lead generation completed. Added {len(unique_leads)} new leads.')