import subprocess
import json

url = "https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM"
headers = {
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
    "x-request-id": "983f0882-498d-4411-8e53-f32470106195",
}
cookies = {
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

# Try with text and matricula=0
payload = {
    "texto": "control de plagas",
    "matricula": "0"
}
print(f"Testing payload: {payload}")
cmd = ["curl", "-s", "-L", "--max-time", "30", "-X", "POST"]
for k, v in headers.items():
    cmd.extend(["-H", f"{k}: {v}"])
cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
cmd.extend(["-b", cookie_str])
cmd.extend(["-H", "Content-Type: application/json"])
cmd.extend(["-d", json.dumps(payload)])
cmd.append(url)
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print(f"Curl error: {result.stderr}")
else:
    print(f"Response length: {len(result.stdout)}")
    # Try to parse JSON
    try:
        data = json.loads(result.stdout)
        registros = data.get("registros", [])
        print(f"Registros encontrados: {len(registros)}")
        if registros:
            for reg in registros[:3]:
                print(f"  NIT={reg.get('nit')}, RazonSocial={reg.get('razon_social')}, Camara={reg.get('cod_camara')}")
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print(result.stdout[:200])