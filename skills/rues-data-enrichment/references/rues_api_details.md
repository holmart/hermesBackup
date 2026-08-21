# RUES API Details - Session Specific Information

Based on network traffic analysis from the user's browser on 2026-08-08.

## Endpoint
```
POST https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM
```

## Required Headers (as observed)
```
accept: application/json, text/plain, */*
accept-encoding: gzip, deflate, br, zstd
accept-language: en-US,en;q=0.9,es-CO;q=0.8,es;q=0.7
app-name: RuesFront
content-type: application/json
origin: https://www.rues.org.co
referer: https://www.rues.org.co/
sec-ch-ua: "Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "macOS"
sec-fetch-dest: empty
sec-fetch-mode: cors
sec-fetch-site: same-site
user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36
x-request-id: [unique per request, observed: 983f0882-498d-4411-8e53-f32470106195]
```

## Required Cookies (as observed)
```
rxVisitorb9g0z89y=1786229211396NDT39F0U63OJD0NEDTN6N50G2C00PGCB
dtSab9g0z89y=-
_ga=GA1.1.1346821396.1786229212
rxvtb9g0z89y=1786231013259|1786229211397
dtPCb9g0z89y=-8869$29211396_322h-vSBFRBWRGBCFPQKAUNMNFFRUCWTIHISCT-0e0
dtCookieb9g0z89y=v_4_srv_14_sn_MS4ND2T98N0E1BN0Q1II56KQT7P4F9SF_perc_100000_ol_0_mul_1_app-3A3d39cf4448f837b2_0_app-3A95d3d7d277b025d6_0
AWSALB=3jPboRN5OwPaO26nzZz6ACncR8+cKYxkk4QKoI9mbq52U5NKFctJcFVieiToKVzATaOJnbYuRXfd0SstDJHqvvJybs9mTOYb9Tn8RDVgS9pB7h4/tiQnKf127WcW
AWSALBCORS=3jPboRN5OwPaO26nzZz6ACncR8+cKYxkk4QKoI9mbq52U5NKFctJcFVieiToKVzATaOJnbYuRXfd0SstDJHqvvJybs9mTOYb9Tn8RDVgS9pB7h4/tiQnKf127WcW
_ga_WR48NTWDKJ=GS2.1.s1786229211$o1$g1$t1786229234$j37$l0$h0
```

## Request Body (as observed)
```json
{
  "dataBody": "U2FsdGVkX1+BaD2kYt15J6eECAw7hdvT7QwkpuspWaflX1NHZClewG2crBIIr5dK2ygPVar+QdDWWaY2YQee6cPWAJEQlGot4JVMlwkWDxo/tR2p8/+X7PzaXoOBRQ7U"
}
```

## Response Structure (as observed)
```json
{
  "registros": [
    {
      "tipo_documento": "NIT",
      "nit": "800204301",
      "dv": "0",
      "id_rm": "40000560714",
      "razon_social": "ACPI SAS ASESORIAS CONTRA PLAGAS E INFESTACIONES",
      "cod_camara": "04",
      "nom_camara": "BOGOTA",
      "matricula": "560714",
      "organizacion_juridica": "SOCIEDADES POR ACCIONES SIMPLIFICADAS SAS",
      "estado_matricula": "ACTIVA",
      "ultimo_ano_renovado": "2025",
      "categoria": "SOCIEDAD ó PERSONA JURIDICA PRINCIPAL ó ESAL"
    },
    // ... more records
  ],
  "cant_registros": 71,
  "fecha_respuesta": "8/8/2026",
  "hora_respuesta": "5:47 PM",
  "error": {
    "code": "0000",
    "message": "OK"
  }
}
```

## Important Observations

1. The endpoint requires specific cookies that appear to be session-based and may expire
2. The `dataBody` parameter is encrypted and appears to be consistent for the observed search
3. The response includes companies with various statuses (ACTIVA, CANCELADA)
4. Only records with `"estado_matricula": "ACTIVA"` and a present `"nit"` should be considered for enrichment
5. The `cod_camara` field indicates the Chamber of Commerce (04 = Bogotá)
6. The skill focuses on the `nit` and `razon_social` fields for enrichment

## Notes for Maintenance

- If the skill stops working, check if the cookies have expired by repeating the browser session analysis
- The `dataBody` may need to be updated if search behavior changes
- Consider implementing a session initialization step that visits the RUES homepage first to obtain fresh cookies