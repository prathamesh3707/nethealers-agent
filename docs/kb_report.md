# Knowledge base report

Store: local file. 2960 passages from 14 of 14 documents.

## Documents

| Document | Scope | Country | Kind | Passages | SHA-256 of the downloaded file |
|---|---|---|---|---|---|
| [The Telecommunications Act, 2023 (No. 44 of 2023)](https://egazette.gov.in/WriteReadData/2023/250880.pdf) | national | India | law | 128 | `302df7ba4ed69e90…` |
| [The Digital Personal Data Protection Act, 2023](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf) | national | India | law | 106 | `4deb23981d3010c8…` |
| [TRAI Recommendations on Leveraging Artificial Intelligence and Big Data in the Telecommunication Sector (2023)](https://www.trai.gov.in/sites/default/files/2024-09/Recommendation_20072023.pdf) | national | India | recommendation | 411 | `e320879b4f7a304e…` |
| [Responsible AI for All, Part 1: Principles for Responsible AI (2021)](https://www.niti.gov.in/sites/default/files/2021-02/Responsible-AI-22022021.pdf) | national | India | guidance | 148 | `381272dfa3b7a098…` |
| [Operator policy for the self-healing agent]() | operator | India | operator | 4 | `…` |
| [ITU-T Y.3172: Architectural framework for machine learning in future networks including IMT-2020 (2019)](https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-Y.3172-201906-I!!PDF-E&type=items) | standard | International | standard | 113 | `e42f9a3be3f951d3…` |
| [ITU-T Y.3181: Architectural framework for machine learning sandbox in future networks including IMT-2020 (2022)](https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-Y.3181-202209-I!!PDF-E&type=items) | standard | International | standard | 116 | `2cfe5093db1c39ba…` |
| [ITU-T Y.3090: Digital twin network - Requirements and architecture (2022)](https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-Y.3090-202202-I!!PDF-E&type=items) | standard | International | standard | 88 | `ec7fdf4264a73975…` |
| [EU Artificial Intelligence Act: European Parliament text adopted 13 March 2024 (P9_TA(2024)0138)](https://artificialintelligenceact.eu/wp-content/uploads/2024/04/TA-9-2024-0138_EN.pdf) | global | European Union | law | 995 | `51eb24c14b4e2d27…` |
| [NIST AI Risk Management Framework (AI RMF 1.0), NIST AI 100-1 (2023)](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf) | global | United States | guidance | 168 | `7576edb531d98488…` |
| [Singapore Model Artificial Intelligence Governance Framework, Second Edition (2020)](https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/resource-for-organisation/ai/sgmodelaigovframework2.pdf) | global | Singapore | guidance | 180 | `f2d199c826207a25…` |
| [Sri Lanka Personal Data Protection Act, No. 9 of 2022](https://www.parliament.lk/uploads/acts/gbills/english/6242.pdf) | regional | Sri Lanka | law | 163 | `6fcdf94fe219d9f7…` |
| [Bangladesh Telecommunication Act, 2001 (authentic English text)](https://www.itu.int/ITU-D/treg/Documentation/Bangladesh/BTRC-TelecomLaw2001.pdf) | regional | Bangladesh | law | 258 | `1a0e2618a948a1ce…` |
| [Nepal Telecommunications Act, 2053 (1997), up to date English text](https://nta.gov.np/uploads/contents/Telecom%20Act%20Upto%20date%20Eng.pdf) | regional | Nepal | law | 82 | `754a5d2e4d9ad28b…` |

Files are downloaded once from the links above into data/kb/raw/. The Gazette of India serves an incomplete certificate chain, so the Telecommunications Act was fetched without certificate verification; its checksum is recorded here so the copy can be compared with the official one.

## Retrieval test

26 hand-written questions (config/kb_eval.yaml), each with the document that should answer it, searched over the whole knowledge base.

| Metric | Value |
|---|---|
| Recall@1 (right document in the top 1) | 81% (21/26) |
| Recall@3 (right document in the top 3) | 92% (24/26) |
| Recall@5 (right document in the top 5) | 92% (24/26) |
| Mean reciprocal rank | 0.86 |
| Recall@3 within the document's scope (how the agents search) | 100% (26/26) |

| Question | Expected | Rank of first right passage | Top result |
|---|---|---|---|
| Who must a data fiduciary inform if there is a personal data breach? | dpdp-act-2023 | 1 | dpdp-act-2023 p.7 |
| When may personal data be processed without consent for certain legitimate uses? | dpdp-act-2023 | not in top 5 | lk-pdpa-2022 p.56 |
| Can the government intercept messages or take over telecom services during a public emergency? | telecom-act-2023 | 1 | telecom-act-2023 p.9 |
| Is an authorisation needed to provide telecommunication services or establish a network? | telecom-act-2023 | 1 | telecom-act-2023 p.3 |
| Should an independent statutory body regulate responsible use of AI across sectors? | trai-ai-2023 | 1 | trai-ai-2023 p.52 |
| Regulatory sandbox for testing AI-based use cases in telecom | trai-ai-2023 | not in top 5 | eu-ai-act p.125 |
| Principle of accountability for AI systems and who is responsible for their outcomes | niti-rai-2021 | 2 | trai-ai-2023 p.27 |
| Principle of safety and reliability of AI systems | niti-rai-2021 | 3 | nist-ai-rmf p.19 |
| What is the largest single power change the agent may make on its own? | operator-policy | 1 | operator-policy p.0 |
| Must the hospital zone tower keep spare capacity? | operator-policy | 1 | operator-policy p.0 |
| ML pipeline with source, collector, preprocessor, model, policy, distributor and sink nodes | itu-y3172 | 1 | itu-y3172 p.25 |
| Machine learning function orchestrator that manages ML pipelines in the network | itu-y3172 | 2 | itu-y3181 p.10 |
| Sandbox where ML models are trained and verified before being deployed in the live network | itu-y3181 | 1 | itu-y3181 p.10 |
| Requirements and architecture of a digital twin network | itu-y3090 | 1 | itu-y3090 p.7 |
| AI used as a safety component in the management and operation of critical digital infrastructure is high-risk | eu-ai-act | 1 | eu-ai-act p.52 |
| Human oversight measures so people can intervene or stop a high-risk AI system | eu-ai-act | 1 | eu-ai-act p.72 |
| Automatic recording of events (logs) over the lifetime of a high-risk AI system | eu-ai-act | 1 | eu-ai-act p.70 |
| AI regulatory sandboxes set up by national authorities | eu-ai-act | 1 | eu-ai-act p.125 |
| Govern, map, measure and manage functions for AI risk | nist-ai-rmf | 1 | nist-ai-rmf p.4 |
| Characteristics of trustworthy AI such as valid and reliable, safe, secure and resilient | nist-ai-rmf | 1 | nist-ai-rmf p.17 |
| Human-in-the-loop, human-over-the-loop and human-out-of-the-loop levels of human involvement | sg-model-ai-gov | 1 | sg-model-ai-gov p.30 |
| Probability and severity of harm used to decide the level of human involvement | sg-model-ai-gov | 1 | sg-model-ai-gov p.31 |
| Data Protection Authority powers in Sri Lanka | lk-pdpa-2022 | 1 | lk-pdpa-2022 p.24 |
| Right of a data subject to withdraw consent and request erasure | lk-pdpa-2022, dpdp-act-2023 | 1 | lk-pdpa-2022 p.8 |
| Functions and powers of the Bangladesh Telecommunication Regulatory Commission | bd-telecom-act-2001 | 1 | bd-telecom-act-2001 p.9 |
| Licence issued by the Nepal Telecommunications Authority to operate telecommunication service | np-telecom-act-1997 | 1 | np-telecom-act-1997 p.7 |
