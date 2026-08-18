#!/usr/bin/env python3
"""
Script de prueba para acceder al endpoint de RUES identificado en el mensaje del usuario.
Utiliza exactamente los headers, cookies y cuerpo observados en una solicitud real de navegador.
"""
import subprocess
import json
import sys
from urllib.parse import quote_plus

# Configuración basada exactamente en el message.txt proporcionado
URL = "https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM"
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9,es-CO;q=0.8,es;q=0.7",
    "app-name": "RuesFront",
    "content-type": "application/json",
    "origin": "https://www.rues.org.co",
    "referer": "https://www.rues.org.co/",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    # Nota: x-request-id probablemente cambia cada request, lo omitimos o generamos uno aleatorio
    "x-request-id": "983f0882-498d-4411-8e53-f32470106195",  # Usaremos el observado, podría necesitar renovación
}
COOKIES = {
    "rxVisitorb9g0z89y": "1786229211396NDT39F0U63OJD0NEDTN6N50G2C00PGCB",
    "dtSab9g0z89y": "-",
    "_ga": "GA1.1.1346821396.1786229212",
    "rxvtb9g0z89y": "1786231013259|1786229211397",
    "dtPCb9g0z89y": "-8869$29211396_322h-vSBFRBWRGBCFPQKAUNMNFFRUCWTIHISCT-0e0",
    "dtCookieb9g0z89y": "v_4_srv_14_sn_MS4ND2T98N0E1BN0Q1II56KQT7P4F9SF_perc_100000_ol_0_mul_1_app-3A3d39cf4448f837b2_0_app-3A95d3d7d277b025d6_0",
    "AWSALB": "3jPboRN5OwPaO26nzZz6ACncR8+cKYxkk4QKoI9mbq52U5NKFctJcFVieiToKVzATaOJnbYuRXfd0SstDJHqvvJybs9mTOYb9Tn8RDVgS9pB7h4/tiQnKf127WcW",
    "AWSALBCORS": "3jPboRN5OwPaO26nzZz6ACncR8+cKYxkk4QKoI9mbq52U5NKFctJcFVieiToKVzATaOJnbYuRXfd0SstDJHqvvJybs9mTOYb9Tn8RDVgS9pB7h4/tiQnKf127WcW",
    "_ga_WR48NTWDKJ": "GS2.1.s1786229211$o1$g1$t1786229234$j37$l0$h0",
}

# El cuerpo observado en el message.txt
REQUEST_BODY = {
    "dataBody": "U2FsdGVkX1+BaD2kYt15J6eECAw7hdvT7QwkpuspWaflX1NHZClewG2crBIIr5dK2ygPVar+QdDWWaY2YQee6cPWAJEQlGot4JVMlwkWDxo/tR2p8/+X7PzaXoOBRQ7U"
}

def build_curl_command():
    """Construye el comando curl equivalente a la request observada."""
    cmd = ["curl", "-s", "-L", "--max-time", "30"]
    
    # Agregar método POST
    cmd.extend(["-X", "POST"])
    
    # Agregar headers
    for key, value in HEADERS.items():
        cmd.extend(["-H", f"{key}: {value}"])
    
    # Agregar cookies
    cookie_string = "; ".join([f"{k}={v}" for k, v in COOKIES.items()])
    cmd.extend(["-b", cookie_string])
    
    # Agregar cuerpo (como JSON)
    cmd.extend(["-H", "Content-Type: application/json"])
    cmd.extend(["-d", json.dumps(REQUEST_BODY)])
    
    # Agregar URL
    cmd.append(URL)
    
    return cmd

def test_rues_endpoint():
    """Prueba el endpoint de RUES y muestra el resultado."""
    print("Probando acceso al endpoint de RUES...")
    print(f"URL: {URL}")
    print(f"Método: POST")
    print(f"Cookies: {len(COOKIES)} cookies cargadas")
    print()
    
    cmd = build_curl_command()
    print("Ejecutando comando curl...")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        print(f"Código de salida: {result.returncode}")
        if result.stderr:
            print(f"STDERR: {result.stderr[:200]}...")
        
        print(f"Longitud de respuesta: {len(result.stdout)} caracteres")
        
        if result.returncode != 0:
            print("Error en la ejecución de curl")
            return False
        
        # Guardar respuesta completa para inspección
        with open("/tmp/rues_response_full.txt", "w", encoding="utf-8") as f:
            f.write(result.stdout)
        print("Respuesta completa guardada en /tmp/rues_response_full.txt")
        
        # Intentar parsear como JSON
        try:
            # Buscar el inicio del JSON (podría haber texto antes)
            json_start = result.stdout.find('{"registros":')
            if json_start == -1:
                json_start = result.stdout.find('{')
            
            if json_start != -1:
                json_str = result.stdout[json_start:]
                data = json.loads(json_str)
                
                print("\n��✅ Respuesta parseada como JSON exitosamente!")
                
                # Mostrar información básica
                if "registros" in data:
                    registros = data["registros"]
                    print(f"Número de registros encontrados: {len(registros)}")
                    
                    # Mostrar primeros 3 registros como ejemplo
                    print("\nPrimeros 3 registros:")
                    for i, registro in enumerate(registros[:3]):
                        print(f"  {i+1}. {registro.get('razon_social', 'N/A')} - NIT: {registro.get('nit', 'N/A')} - Estado: {registro.get('estado_matricula', 'N/A')}")
                    
                    # Contar registros activos vs cancelados
                    activos = sum(1 for r in registros if r.get('estado_matricula') == 'ACTIVA')
                    cancelados = sum(1 for r in registros if r.get('estado_matricula') == 'CANCELADA')
                    print(f"\nResumen: {activos} activos, {cancelados} cancelados")
                    
                    # Mostrar algunos NITs de empresas activas para verificar
                    nits_activos = [r.get('nit') for r in registros if r.get('estado_matricula') == 'ACTIVA' and r.get('nit')]
                    if nits_activos:
                        print(f"Ejemplos de NITs activos: {', '.join(nits_activos[:5])}")
                
                # Guardar datos parseados
                with open("/tmp/rues_data_parsed.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print("Datos parseados guardados en /tmp/rues_data_parsed.json")
                
                return True
            else:
                print("��❌ No se encontró JSON válido en la respuesta")
                print("Primeros 500 caracteres de la respuesta:")
                print(result.stdout[:500])
                return False
                
        except json.JSONDecodeError as e:
            print(f"��❌ Error al parsear JSON: {e}")
            print("Primeros 1000 caracteres de la respuesta:")
            print(result.stdout[:1000])
            return False
            
    except subprocess.TimeoutExpired:
        print("��❌ Timeout al ejecutar curl (>30s)")
        return False
    except Exception as e:
        print(f"��❌ Error inesperado: {e}")
        return False

if __name__ == "__main__":
    success = test_rues_endpoint()
    sys.exit(0 if success else 1)