# VMEC-01 Data Flow

```mermaid
flowchart LR
    U["Patient or staff browser"] -->|"TLS, session, CSRF"| API["FastAPI"]
    API --> E["Deterministic emergency gate"]
    E -->|"emergency"| H["115 guidance / human handoff"]
    E -->|"routine"| R["Grounded retrieval"]
    R --> L["PostgreSQL lexical index"]
    R --> V2["Embedding 2 index"]
    R -. "degraded text" .-> V1["Embedding 1 index"]
    R --> G["Redis round-robin Gemini gateway"]
    G --> M31["gemini-3.1-flash-lite"]
    G --> M35["gemini-3.5-flash-lite"]
    API --> B["Transactional booking domain"]
    API --> P[("PostgreSQL / pgvector")]
    API --> X[("Redis sessions / limits / routing")]
    W["Worker"] --> P
    W --> X
    S["Immutable source artifacts"] --> I["Streaming importer / quarantine"]
    I --> P
```

Raw patient text is confined to the minimum application path and is excluded from model telemetry, metrics, logs, and safe exports. Source provenance and citation mappings survive every import and retrieval step.

