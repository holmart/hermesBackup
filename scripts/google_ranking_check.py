# Script para verificar posicionamiento de páginas en Google por verticales
import requests
import json
import time
from bs4 import BeautifulSoup

# Lista de verticales y páginas a consultar
verticals = [
    {'name': 'Fumigación', 'url': 'https://www.plusfumigaciones.com/'},
    {'name': 'Control de Plagas', 'url': 'https://www.fuseincolcolombia.com/'},
    {'name': 'Fumigacion de Colombia', 'url': 'https://fumigacioncol.com/'},
]

# Función para rastrear el ranking en Google

def check_google_ranking(vertical):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36'
    }
    query = f"{vertical['name']} site:{vertical['url']}"
    google_search_url = f'https://www.google.com/search?q={query}'
    response = requests.get(google_search_url, headers=headers)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.find_all('div', class_='g')  # Divs that contain search results
        ranking = 1
        for result in results:
            link = result.find('a')['href']
            # Check if our URL is in the results
            if vertical['url'] in link:
                return {'vertical': vertical['name'], 'ranking': ranking}
            ranking += 1
        return {'vertical': vertical['name'], 'ranking': 'Not Found'}
    else:
        return {'vertical': vertical['name'], 'ranking': 'Error'}

# Ejecutar verificación para cada vertical
results = []
for vertical in verticals:
    result = check_google_ranking(vertical)
    results.append(result)

# Guardar resultados en archivo JSON
with open('/home/ubuntu/.hermes/leads/google_ranking_results.json', 'w') as file:
    json.dump(results, file, indent=4)

print('Ranking check completed, results saved in google_ranking_results.json')