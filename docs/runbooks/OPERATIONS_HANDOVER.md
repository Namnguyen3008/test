# Operations handover checklist

Status: documentation prepared; acceptance awaits real named operators and staging evidence.

- Record service ownership, on-call rotation, escalation, clinical-safety, governance, database, and release contacts
  in the external operations system.
- Scope and rotate secrets in the approved manager; repository and logs contain none.
- Monitor API/web/worker/scheduler, PostgreSQL/pgvector, Redis, Gemini, retrieval, booking, outbox, audit integrity,
  backup age, and certificate expiry.
- Rehearse supersession, revocation, Gemini outage, embedding rebuild, incident response, backup/restore, application
  rollback, and fail-closed startup.
- Obtain external approval for SLOs, paging, capacity, retention, data-subject workflows, and evidence retention.
- Give staging and production separate signed change records. A checklist is not sign-off.

Handover is complete only after named operators record attendance, rehearsal results, access review, accepted risks,
and production ownership in the external system of record.
