# Relay — t54 marketplace sources on XRPL Testnet

## What is live vs mirrored

Relay now probes two real t54 XRPL AI Hub resources without payment. Each real
HTTP 402 response contains an x402 v2 `PAYMENT-REQUIRED` header with:

- the real `xrpl:0` XRP/RLUSD payment options;
- resource name, description, and tags;
- Bazaar input schema;
- an advertised sample output.

Those vendors do not advertise `xrpl:1`. To keep this demo entirely on
Testnet, Relay settles against local, clearly labelled Testnet mirror routes
at the same nominal XRP amount (20,000 drops) and returns an explicitly labeled sample. LEI uses a stored vendor example;
the wage mirror uses historical BLS wage statistics as described below. This proves discovery, policy selection, 402 handling, payment,
settlement, and delivery without claiming that the mainnet vendor was paid.

## Sources

### CompliancePulse · Global LEI lookup

- Category: `business_registration_status`
- Real resource: `https://compliancepulse.theaslangroupllc.com/api/validate/lei`
- Real rail: `xrpl:0`
- Testnet mirror: `/testnet-mirror/lei`
- Advertised price: 20,000 drops (0.02 XRP)
- Sample fields: `lei`, `legal_name`, `entity_status`,
  `registration_status`, `jurisdiction`, `next_renewal`, `source`

### MacroPulse · BLS wage benchmarks

- Category: `industry_income_benchmarks`
- Real resource: `https://macropulse.theaslangroupllc.com/api/macro/bls-series`
- Real rail: `xrpl:0`
- Testnet mirror: `/testnet-mirror/bls`
- Advertised price: 20,000 drops (0.02 XRP)
- Delivery: historical BLS OEWS wage sample, US Legal Services (NAICS 541100),
  all occupations, May 2023. Annual mean wage: USD 110,650; median hourly
  wage: USD 36.18; mean hourly wage: USD 53.20.
- Source: https://www.bls.gov/oes/2023/may/naics4_541100.htm
- This is a cited historical sample, not MacroPulse output, not a current
  applicant query, and not compliant with a 30-day data freshness requirement.
- The original vendor CPI example remains available under `advertised_sample`
  and in a collapsed declaration panel; it cannot overwrite `sample_data`
  used by the wage preview and local delivery. Annual mean is not annual median.

## Demo endpoints

- `GET /marketplace/candidates` — refresh both live unpaid 402 declarations
- `GET /testnet-mirror/lei` — paid Testnet mirror
- `GET /testnet-mirror/bls` — paid Testnet mirror
- `POST /run` with `data_type=business_registration_status`
- `POST /run` with `data_type=industry_income_benchmarks`

## Verified Testnet transactions

- LEI mirror: `6681217E3C2174A60978B18892921BDBB86E74D41057E6518B4DDD9241D06E7D`
- BLS mirror: `F45B5302C1FA07D988A09686D52FB0F69EF585D81C3D70894D152A0989C15E0E`

Both returned `tesSUCCESS` and were independently confirmed through the XRPL
Testnet RPC before the sample data was marked delivered.
