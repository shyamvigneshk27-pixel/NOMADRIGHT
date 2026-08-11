# Citations - NomadRight Knowledge Base Datasets
**Generated:** 2026-08-03  
**Purpose:** Full provenance record for all official government sources used in data extraction  

---

## Official Government Sources Used

### 1. PDS / ONORC (One Nation One Ration Card)

| # | Source | Type | URL | Fields Sourced |
|---|--------|------|-----|----------------|
| 1 | MyScheme - Government of India | Official Portal (MeitY) | https://www.myscheme.gov.in/schemes/onorc | Description, Eligibility, Benefits, Application Process, Documents, Portability |
| 2 | Department of Food & Public Distribution (DFPD) | Ministry Website | https://dfpd.gov.in/ | Free foodgrains policy, NFSA implementation details |
| 3 | National Food Security Portal (NFSA) | Government Portal | https://nfsa.gov.in/ | NFSA Act text, Section 3 entitlements, Schedule I prices |
| 4 | NFSA Act, 2013 (Act No. 20 of 2013) | Legislation | https://nfsa.gov.in/portal/nfsa-act | Section 3(1), 3(2), Schedule I - Entitlements and prices |
| 5 | IMPDS Portal (NIC) | Government Dashboard | https://impds.nic.in/ | ONORC transaction data, ePoS reports, Mera Ration app |
| 6 | Press Information Bureau (PIB) | Government Press Release | https://pib.gov.in/ | PMGKAY extension, free foodgrains announcement (Jan 2023, Jan 2024) |
| 7 | UMANG Portal | Government App Platform | https://umang.gov.in/ | PDS services accessibility |
| 8 | CPGRAMS | Grievance Portal | https://pgportal.gov.in/ | Grievance redressal mechanism |

---

### 2. Ayushman Bharat PM-JAY

| # | Source | Type | URL | Fields Sourced |
|---|--------|------|-----|----------------|
| 1 | National Health Authority (NHA) | Implementing Agency Website | https://nha.gov.in/ | Scheme description, benefits, coverage details, HBP, portability, definitions |
| 2 | PM-JAY Official Portal | Scheme Website | https://pmjay.gov.in/ | Eligibility check (Am I Eligible), helpline 14555, hospital search, application process, grievance portal |
| 3 | MyScheme - Government of India | Official Portal (MeitY) | https://www.myscheme.gov.in/schemes/ab-pmjay | Scheme details, eligibility, benefits, application process, documents |
| 4 | Press Information Bureau (PIB) | Government Press Release | https://pib.gov.in/ | HBP 1.0 launch details (1,393 packages), HBP revisions, scheme statistics |
| 5 | India.gov.in - National Portal of India | Government Portal | https://india.gov.in/ | PM-JAY senior citizens expansion (70+ coverage, September 2024) |
| 6 | PM-JAY Grievance Portal | Grievance System | https://cgrms.pmjay.gov.in | Grievance redressal mechanism |
| 7 | SECC 2011 Data | Census Data | Referenced via NHA/PIB | Deprivation criteria (rural D1-D7), occupational categories (urban), exclusion criteria |
| 8 | Vaishali District NIC Portal | District Portal | https://vaishali.nic.in/ | PM-JAY eligibility details corroboration |

---

### 3. MGNREGS (Mahatma Gandhi National Rural Employment Guarantee Scheme)

| # | Source | Type | URL | Fields Sourced |
|---|--------|------|-----|----------------|
| 1 | MGNREGA Official MIS Portal | Government Portal (NIC) | https://nrega.nic.in/ | Scheme objectives, eligibility, Job Card process, social audit, worksite facilities |
| 2 | Ministry of Rural Development | Ministry Website | https://rural.gov.in/ | MGNREGA scheme overview, ministry information |
| 3 | MyScheme - Government of India | Official Portal (MeitY) | https://www.myscheme.gov.in/schemes/mgnregs | Scheme details, eligibility, benefits, application process, documents |
| 4 | Press Information Bureau (PIB) | Government Press Release | https://pib.gov.in/ | VB-G RAM G Act, 2025 details, 125 days expansion, Rs. 300 base wage, July 2026 commencement, wage revision notification |
| 5 | UMANG Portal | Government App Platform | https://umang.gov.in/ | Online Job Card application process |
| 6 | Indian Economic Service (IES) | Government Analysis | https://ies.gov.in/ | MGNREGA Act provisions analysis |
| 7 | MGNREGA Act, 2005 (Act No. 42 of 2005) | Legislation | https://nrega.nic.in/netnrega/filext/act/nrega_act.pdf | Section 3 (Employment guarantee), Section 5 (Women's participation), Section 7 (Unemployment allowance) |
| 8 | CPGRAMS | Grievance Portal | https://pgportal.gov.in/ | Grievance redressal mechanism |
| 9 | India Budget Portal | Government Portal | https://indiabudget.gov.in/ | VB-G RAM G budgetary provisions |
| 10 | VB-G RAM G Gazette Notification (June 30, 2026) | Official Gazette | Referenced via PIB | Revised state-wise wage rates, Rs. 300 minimum base wage |

---

## Sources Explicitly NOT Used (Per Requirements)

The following source categories were explicitly excluded from this dataset:

| Category | Reason |
|----------|--------|
| Wikipedia | Explicitly prohibited per project requirements |
| Quora | Explicitly prohibited per project requirements |
| Blogs | Explicitly prohibited per project requirements |
| AI-generated content | Explicitly prohibited per project requirements |
| Unofficial aggregator websites | Not used for primary data extraction |

---

## Source Verification Notes

1. **myscheme.gov.in** - Official Government of India portal operated by Digital India Corporation under the Ministry of Electronics and Information Technology (MeitY). This is an authoritative source for scheme information.

2. **nha.gov.in / pmjay.gov.in** - Official National Health Authority and PM-JAY portals. pmjay.gov.in experienced connectivity timeout during extraction (2026-08-03); data cross-verified via search results referencing this source.

3. **nrega.nic.in** - Official MGNREGA MIS portal operated by NIC under the Ministry of Rural Development. Authoritative for scheme data.

4. **pib.gov.in** - Press Information Bureau, the nodal agency for government press releases. All PIB references are to official government announcements.

5. **dfpd.gov.in / nfsa.gov.in** - Official Department of Food & Public Distribution and National Food Security portals. Some NFSA pages returned 404; data verified through PIB and DFPD references.

6. **SECC 2011** - The Socio-Economic Caste Census 2011 data is referenced as the official basis for PM-JAY eligibility. The specific deprivation criteria are summarised based on NHA's published guidelines.

---

## Citation Format

All citations in the JSON datasets use the following format:
- **In-field source attribution**: Each field/entry includes a `"source"` key referencing the official website or document.
- **Official sources array**: Each JSON file includes an `official_sources` array with structured citation entries containing `website`, `document`, `url`, `page`, and `section` fields.

---

*This citations document should be maintained alongside the JSON datasets. Any updates to the datasets should include corresponding updates to this citation record.*
