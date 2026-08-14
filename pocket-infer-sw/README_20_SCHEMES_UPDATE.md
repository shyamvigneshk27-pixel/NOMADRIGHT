# NomadRight DB Architecture Update: 20 Schemes Integrated

This document outlines the changes made to the NomadRight DB Architecture to integrate 15 additional schemes from `all_20_schemes.json`, bringing the total supported schemes to 20. 

## What Was Done

1. **Schema Adapter Implementation**: 
   - The ingestion script `nomadright/build_sqlite_db.py` was enhanced to support both the highly-structured, detailed schema of the original 5 schemes (e.g., `eshram_osh.json`) and the compact, seed-like schema of the new 15 schemes (e.g., `apy.json`, `pm_kisan.json`).
   - Fields that were originally expected to be lists of dictionaries (like `eligibility`, `benefits`, `exceptions`) are now robustly parsed and converted on the fly even if they are provided as simple lists of strings. 
   - Fallbacks were added for `last_updated` and other metadata fields.

2. **Scheme Extraction**: 
   - The 15 new schemes were extracted from the monolith `all_20_schemes.json` into individual JSON files in the `nomadright/` directory, maintaining consistency in how scheme files are managed.
   - The original 5 files were preserved completely without modification, keeping their rich data intact.

3. **Application Constants Updated**: 
   - We updated `python/pocketinfer/applications/nomad_right/constants.py` to register the 15 new schemes.
   - Now, `SUPPORTED_SCHEME_CODES`, `SCHEME_CODE_TO_DB_ID`, `SCHEME_HELPLINES` and `SCHEME_JSON_FILES` reflect all 20 schemes.

4. **Database Generated**:
   - `build_sqlite_db.py` was executed, successfully generating `nomadright_kb.db` with data for all 20 schemes without dropping or conflicting any existing data.

## Supported Schemes

1. PDS (One Nation One Ration Card)
2. PMJAY (Ayushman Bharat)
3. e-Shram (OSH Code)
4. BOCW (Building and Other Construction Workers)
5. MGNREGS (Mahatma Gandhi National Rural Employment Guarantee Act)
6. APY (Atal Pension Yojana)
7. NSAP (National Social Assistance Programme)
8. PM_KISAN (Pradhan Mantri Kisan Samman Nidhi)
9. PM_SURYA_GHAR (Pradhan Mantri Surya Ghar: Muft Bijli Yojana)
10. PM_SVANIDHI (PM SVANidhi)
11. PM_SYM (Pradhan Mantri Shram Yogi Maandhan)
12. PM_VISHWAKARMA (PM Vishwakarma)
13. PMAY_G (Pradhan Mantri Awas Yojana – Gramin)
14. PMFBY (Pradhan Mantri Fasal Bima Yojana)
15. PMJDY (Pradhan Mantri Jan-Dhan Yojana)
16. PMJJBY (Pradhan Mantri Jeevan Jyoti Bima Yojana)
17. PMMY (Pradhan Mantri MUDRA Yojana)
18. PMSBY (Pradhan Mantri Suraksha Bima Yojana)
19. PMUY (Pradhan Mantri Ujjwala Yojana)
20. SUKANYA_SAMRIDDHI (Sukanya Samriddhi Account)

The updated database maintains microsecond retrieval for all schemes and correctly integrates with the existing RAG routing layer.
