# Security Upgrades Report

This document records the dependency upgrades performed on the Audio Briefing Backend to remediate vulnerabilities discovered during the `pip-audit`.

## 🛡️ Upgraded Dependencies

| Dependency | Category | Upgraded Version | Target Vulnerability / CVEs |
| :--- | :--- | :--- | :--- |
| **`python-dotenv`** | Direct | **`1.2.2`** | CVE-2026-28684 (High) |
| **`requests`** | Direct | **`2.34.2`** | CVE-2026-25645 (High) |
| **`nltk`** | Direct | **`3.9.4`** | CVE-2026-33230, CVE-2026-33231, CVE-2026-33236 (Critical) |
| **`langgraph`** | Direct | **`1.2.2`** | PYSEC-2026-83 (Medium) |
| **`langchain`** | Direct | **`1.3.2`** | General API stabilization |
| **`langchain-openai`**| Direct | **`1.2.2`** | PYSEC-2026-76 (Medium) |
| **`aiohttp`** | Transitive | **`3.13.5`** | CVE-2025-69226, CVE-2026-34514 (Critical) |
| **`cryptography`** | Transitive | **`48.0.0`** | CVE-2026-26007, PYSEC-2026-35, PYSEC-2026-36 (High) |
| **`langchain-core`** | Transitive | **`1.4.0`** | CVE-2026-26013, CVE-2026-40087 (Medium) |
| **`litellm`** | Transitive | **`1.86.2`** | CVE-2026-35029, CVE-2026-42271 (Medium) |
| **`pillow`** | Transitive | **`12.2.0`** | CVE-2026-42309, CVE-2026-42311 (High) |
| **`urllib3`** | Transitive | **`2.7.0`** | CVE-2026-21441 (High) |
| **`pymongo`** | Transitive | **`4.16.0`** | General stabilization |

---

