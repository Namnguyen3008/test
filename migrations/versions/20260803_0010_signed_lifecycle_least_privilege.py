"""Signed release lifecycle and PostgreSQL least-privilege roles.

Revision ID: 20260803_0010_signed_lifecycle
Revises: 20260803_0009_governance_bridge
"""

from alembic import op

revision = "20260803_0010_signed_lifecycle"
down_revision = "20260803_0009_governance_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE governance_release_routes (
            route_name text PRIMARY KEY,
            project_id text NOT NULL CHECK(project_id='VMEC-01'),
            state text NOT NULL CHECK(state IN ('ACTIVE','REVOKED')),
            generation bigint NOT NULL CHECK(generation >= 1),
            active_release_id uuid REFERENCES dataset_releases(id),
            active_manifest_id text REFERENCES governance_manifests(manifest_id),
            last_artifact_id text,
            transitioned_at timestamptz NOT NULL,
            CHECK((state='ACTIVE' AND active_release_id IS NOT NULL AND active_manifest_id IS NOT NULL)
               OR (state='REVOKED' AND active_release_id IS NULL AND active_manifest_id IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE governance_lifecycle_artifacts (
            artifact_id text PRIMARY KEY,
            artifact_digest char(64) NOT NULL UNIQUE,
            kind text NOT NULL CHECK(kind IN ('SUPERSESSION','REVOCATION')),
            key_id char(64) NOT NULL,
            trust_registry_digest char(64) NOT NULL,
            route_name text NOT NULL,
            expected_generation bigint NOT NULL,
            artifact jsonb NOT NULL,
            applied_at timestamptz NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE governance_release_transitions (
            id bigserial PRIMARY KEY,
            artifact_id text NOT NULL UNIQUE REFERENCES governance_lifecycle_artifacts(artifact_id),
            route_name text NOT NULL,
            previous_generation bigint NOT NULL,
            new_generation bigint NOT NULL,
            previous_state text NOT NULL,
            new_state text NOT NULL,
            previous_release_id uuid,
            new_release_id uuid,
            previous_manifest_id text,
            new_manifest_id text,
            created_at timestamptz NOT NULL,
            UNIQUE(route_name,new_generation),
            CHECK(new_generation=previous_generation+1)
        )
    """)
    op.execute("""
        INSERT INTO governance_release_routes(route_name,project_id,state,generation,active_release_id,
          active_manifest_id,transitioned_at)
        SELECT 'vmec-production-v1','VMEC-01','ACTIVE',1,dr.id,gp.manifest_id,gp.created_at
        FROM dataset_releases dr JOIN governance_promotions gp
          ON gp.receipt->>'production_release_id'=dr.id::text
        WHERE dr.logical_release_id='vmec-production-v1' AND dr.status='completed'
        ON CONFLICT DO NOTHING
    """)
    for table in ("governance_lifecycle_artifacts", "governance_release_transitions"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION vmec_prevent_governance_audit_mutation()"
        )
    op.execute("""
        CREATE OR REPLACE FUNCTION vmec_guard_governance_manifest_transition() RETURNS trigger AS $$
        BEGIN
          IF TG_OP='DELETE' THEN RAISE EXCEPTION 'governance manifests cannot be deleted'; END IF;
          IF OLD.status='VERIFIED' AND NEW.status='PROMOTED'
             AND OLD.manifest_id=NEW.manifest_id AND OLD.manifest_digest=NEW.manifest_digest
             AND OLD.scope_digest=NEW.scope_digest AND OLD.key_id=NEW.key_id
             AND OLD.release_scope=NEW.release_scope AND OLD.evidence_digest=NEW.evidence_digest
             AND OLD.verified_at=NEW.verified_at AND OLD.promoted_at IS NULL AND NEW.promoted_at IS NOT NULL THEN
            RETURN NEW;
          END IF;
          IF OLD.status='PROMOTED' AND NEW.status IN ('SUPERSEDED','REVOKED')
             AND OLD.manifest_id=NEW.manifest_id AND OLD.manifest_digest=NEW.manifest_digest
             AND OLD.scope_digest=NEW.scope_digest AND OLD.key_id=NEW.key_id
             AND OLD.release_scope=NEW.release_scope AND OLD.evidence_digest=NEW.evidence_digest
             AND OLD.verified_at=NEW.verified_at AND OLD.promoted_at=NEW.promoted_at
             AND EXISTS(SELECT 1 FROM governance_lifecycle_artifacts gla
               WHERE gla.artifact_id=(SELECT last_artifact_id FROM governance_release_routes
                 WHERE route_name=gla.route_name)
               AND ((gla.kind='SUPERSESSION' AND gla.artifact->'previous'->>'manifest_id'=OLD.manifest_id)
                 OR (gla.kind='REVOCATION' AND gla.artifact->'target'->>'manifest_id'=OLD.manifest_id))) THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'invalid governance manifest lifecycle transition';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE FUNCTION vmec_guard_completed_release_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.status='completed' THEN
            RAISE EXCEPTION 'completed dataset releases and their content are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER dataset_releases_completed_immutable BEFORE UPDATE OR DELETE ON dataset_releases FOR EACH ROW EXECUTE FUNCTION vmec_guard_completed_release_mutation()")
    op.execute("""
        CREATE FUNCTION vmec_guard_completed_release_child_mutation() RETURNS trigger AS $$
        DECLARE bound_release uuid;
        BEGIN
          IF TG_TABLE_NAME='knowledge_records' THEN bound_release := OLD.release_id;
          ELSIF TG_TABLE_NAME='knowledge_chunks' THEN
            SELECT release_id INTO bound_release FROM knowledge_records WHERE id=OLD.record_id;
          ELSIF TG_TABLE_NAME='knowledge_record_sources' THEN
            SELECT release_id INTO bound_release FROM knowledge_records WHERE id=OLD.record_id;
          ELSE bound_release := OLD.release_id;
          END IF;
          IF EXISTS(SELECT 1 FROM dataset_releases WHERE id=bound_release AND status='completed') THEN
            RAISE EXCEPTION 'completed release content is immutable';
          END IF;
          RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("knowledge_records", "knowledge_chunks", "knowledge_record_sources", "dataset_release_sources"):
        op.execute(f"CREATE TRIGGER {table}_completed_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION vmec_guard_completed_release_child_mutation()")

    # Cluster roles are capability groups only. Login credentials remain external.
    op.execute("""
        DO $$ DECLARE role_name text; BEGIN
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolcreaterole)) THEN
            RAISE EXCEPTION 'migration owner requires CREATEROLE to provision V7 capability roles';
          END IF;
          FOREACH role_name IN ARRAY ARRAY['vmec_migration_owner','vmec_api','vmec_worker','vmec_importer',
            'vmec_analytics','vmec_clinical_reporter','vmec_governance','vmec_backup'] LOOP
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
              EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',role_name);
            END IF;
          END LOOP;
        END $$
    """)
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO vmec_api,vmec_worker,vmec_importer,vmec_analytics,vmec_clinical_reporter,vmec_governance,vmec_backup")
    op.execute("GRANT SELECT,INSERT,UPDATE ON users,auth_sessions,consent_grants,appointments,slot_holds,clinical_review_items TO vmec_api")
    op.execute("GRANT SELECT ON slots,dataset_releases,global_sources,knowledge_records,knowledge_record_sources,knowledge_chunks,knowledge_embeddings,governance_release_routes TO vmec_api")
    op.execute("GRANT SELECT,INSERT ON idempotency_keys,audit_events,appointment_events,booking_outbox,clinical_review_decisions TO vmec_api")
    op.execute("GRANT SELECT,INSERT,UPDATE ON appointments,slot_holds,booking_outbox,appointment_reminders,embedding_jobs,embedding_job_items,embedding_quarantine TO vmec_worker")
    op.execute("GRANT SELECT ON slots,dataset_releases,global_sources,knowledge_records,knowledge_record_sources,knowledge_chunks,knowledge_embeddings,governance_release_routes TO vmec_worker")
    op.execute("GRANT INSERT ON appointment_events,audit_events,knowledge_embeddings TO vmec_worker")
    op.execute("GRANT SELECT,INSERT,UPDATE ON dataset_releases,dataset_import_jobs,global_sources,knowledge_records,knowledge_chunks TO vmec_importer")
    op.execute("GRANT SELECT,INSERT ON dataset_files,dataset_quarantine,dataset_release_sources,knowledge_record_sources TO vmec_importer")
    op.execute("GRANT SELECT ON dataset_releases,global_sources,knowledge_records,knowledge_record_sources,knowledge_chunks,dataset_release_sources TO vmec_governance")
    op.execute("GRANT INSERT ON dataset_releases,dataset_release_sources,knowledge_records,knowledge_record_sources,knowledge_chunks,governance_manifests,governance_promotions,governance_row_promotions,governance_lifecycle_artifacts,governance_release_transitions TO vmec_governance")
    op.execute("GRANT SELECT ON governance_manifests,governance_promotions,governance_row_promotions,governance_lifecycle_artifacts,governance_release_transitions,governance_release_routes TO vmec_governance")
    op.execute("GRANT UPDATE(status,imported_records,updated_at) ON dataset_releases TO vmec_governance")
    op.execute("GRANT UPDATE(status,promoted_at) ON governance_manifests TO vmec_governance")
    op.execute("GRANT UPDATE(state,generation,active_release_id,active_manifest_id,last_artifact_id,transitioned_at) ON governance_release_routes TO vmec_governance")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO vmec_api,vmec_worker,vmec_importer,vmec_governance")
    op.execute("CREATE VIEW vmec_analytics_events WITH (security_barrier=true) AS SELECT date_trunc('hour',occurred_at) event_hour,action,outcome,count(*) event_count FROM audit_events GROUP BY 1,2,3")
    op.execute("CREATE VIEW vmec_clinical_review_report WITH (security_barrier=true) AS SELECT status,safety_critical,count(*) item_count FROM clinical_review_items GROUP BY status,safety_critical")
    op.execute("GRANT SELECT ON vmec_analytics_events TO vmec_analytics")
    op.execute("GRANT SELECT ON vmec_clinical_review_report TO vmec_clinical_reporter")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO vmec_backup")
    op.execute("GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO vmec_backup")
    op.execute("ALTER ROLE vmec_backup BYPASSRLS")
    op.execute("ALTER TABLE dataset_releases ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY dataset_runtime_read ON dataset_releases FOR SELECT TO vmec_api,vmec_worker USING(mode='production' AND status='completed')")
    op.execute("CREATE POLICY dataset_importer_read ON dataset_releases FOR SELECT TO vmec_importer USING(mode IN ('development','review'))")
    op.execute("CREATE POLICY dataset_importer_write ON dataset_releases FOR ALL TO vmec_importer USING(mode IN ('development','review') AND status<>'completed') WITH CHECK(mode IN ('development','review'))")
    op.execute("CREATE POLICY dataset_governance_read ON dataset_releases FOR SELECT TO vmec_governance USING(true)")
    op.execute("CREATE POLICY dataset_governance_insert ON dataset_releases FOR INSERT TO vmec_governance WITH CHECK(mode='production')")
    op.execute("CREATE POLICY dataset_governance_update ON dataset_releases FOR UPDATE TO vmec_governance USING(mode='production' AND status<>'completed') WITH CHECK(mode='production')")
    op.execute("ALTER TABLE knowledge_records ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY records_runtime_read ON knowledge_records FOR SELECT TO vmec_api,vmec_worker USING(mode='production' AND upper(coalesce(canonical_status,'')) IN ('ACCEPTED','GOLD') AND upper(coalesce(review_status,''))='CLINICALLY_APPROVED')")
    op.execute("CREATE POLICY records_importer ON knowledge_records FOR ALL TO vmec_importer USING(mode IN ('development','review')) WITH CHECK(mode IN ('development','review'))")
    op.execute("CREATE POLICY records_governance_read ON knowledge_records FOR SELECT TO vmec_governance USING(true)")
    op.execute("CREATE POLICY records_governance_insert ON knowledge_records FOR INSERT TO vmec_governance WITH CHECK(mode='production')")
    op.execute("ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY chunks_runtime_read ON knowledge_chunks FOR SELECT TO vmec_api,vmec_worker USING(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id))")
    op.execute("CREATE POLICY chunks_importer ON knowledge_chunks FOR ALL TO vmec_importer USING(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id AND kr.mode IN ('development','review'))) WITH CHECK(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id AND kr.mode IN ('development','review')))")
    op.execute("CREATE POLICY chunks_governance_read ON knowledge_chunks FOR SELECT TO vmec_governance USING(true)")
    op.execute("CREATE POLICY chunks_governance_insert ON knowledge_chunks FOR INSERT TO vmec_governance WITH CHECK(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id AND kr.mode='production'))")
    op.execute("ALTER TABLE knowledge_record_sources ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY record_sources_runtime_read ON knowledge_record_sources FOR SELECT TO vmec_api,vmec_worker USING(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id))")
    op.execute("CREATE POLICY record_sources_importer ON knowledge_record_sources FOR ALL TO vmec_importer USING(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id AND kr.mode IN ('development','review'))) WITH CHECK(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id AND kr.mode IN ('development','review')))")
    op.execute("CREATE POLICY record_sources_governance_read ON knowledge_record_sources FOR SELECT TO vmec_governance USING(true)")
    op.execute("CREATE POLICY record_sources_governance_insert ON knowledge_record_sources FOR INSERT TO vmec_governance WITH CHECK(EXISTS(SELECT 1 FROM knowledge_records kr WHERE kr.id=record_id AND kr.mode='production'))")
    op.execute("ALTER TABLE knowledge_embeddings ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY embeddings_runtime_read ON knowledge_embeddings FOR SELECT TO vmec_api,vmec_worker USING(EXISTS(SELECT 1 FROM knowledge_chunks kc JOIN knowledge_records kr ON kr.id=kc.record_id WHERE kc.id=chunk_id))")
    op.execute("CREATE POLICY embeddings_worker_insert ON knowledge_embeddings FOR INSERT TO vmec_worker WITH CHECK(EXISTS(SELECT 1 FROM knowledge_chunks kc JOIN knowledge_records kr ON kr.id=kc.record_id WHERE kc.id=chunk_id AND kr.mode='production'))")
    op.execute("ALTER TABLE governance_release_routes ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY routes_runtime_active ON governance_release_routes FOR SELECT TO vmec_api,vmec_worker USING(state='ACTIVE')")
    op.execute("CREATE POLICY routes_governance ON governance_release_routes FOR ALL TO vmec_governance USING(true) WITH CHECK(true)")
    op.execute("REVOKE EXECUTE ON FUNCTION vmec_prevent_governance_audit_mutation() FROM PUBLIC")
    op.execute("REVOKE EXECUTE ON FUNCTION vmec_guard_completed_release_mutation() FROM PUBLIC")
    op.execute("REVOKE EXECUTE ON FUNCTION vmec_guard_completed_release_child_mutation() FROM PUBLIC")
    op.execute("REVOKE EXECUTE ON FUNCTION vmec_guard_governance_manifest_transition() FROM PUBLIC")


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_embeddings DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_record_sources DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_chunks DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance_release_routes DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_records DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dataset_releases DISABLE ROW LEVEL SECURITY")
    for policy, table in (
        ("embeddings_runtime_read", "knowledge_embeddings"), ("embeddings_worker_insert", "knowledge_embeddings"),
        ("record_sources_runtime_read", "knowledge_record_sources"), ("record_sources_importer", "knowledge_record_sources"),
        ("record_sources_governance_read", "knowledge_record_sources"), ("record_sources_governance_insert", "knowledge_record_sources"),
        ("chunks_runtime_read", "knowledge_chunks"), ("chunks_importer", "knowledge_chunks"),
        ("chunks_governance_read", "knowledge_chunks"), ("chunks_governance_insert", "knowledge_chunks"),
        ("records_runtime_read", "knowledge_records"), ("records_importer", "knowledge_records"),
        ("records_governance_read", "knowledge_records"), ("records_governance_insert", "knowledge_records"),
        ("dataset_runtime_read", "dataset_releases"), ("dataset_importer_read", "dataset_releases"),
        ("dataset_importer_write", "dataset_releases"), ("dataset_governance_read", "dataset_releases"),
        ("dataset_governance_insert", "dataset_releases"), ("dataset_governance_update", "dataset_releases"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute("DROP VIEW IF EXISTS vmec_clinical_review_report")
    op.execute("DROP VIEW IF EXISTS vmec_analytics_events")
    for table in ("knowledge_records", "knowledge_chunks", "knowledge_record_sources", "dataset_release_sources"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_completed_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS vmec_guard_completed_release_child_mutation")
    op.execute("DROP TRIGGER IF EXISTS dataset_releases_completed_immutable ON dataset_releases")
    op.execute("DROP FUNCTION IF EXISTS vmec_guard_completed_release_mutation")
    for table in ("governance_release_transitions", "governance_lifecycle_artifacts"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP TABLE IF EXISTS governance_release_transitions")
    op.execute("DROP TABLE IF EXISTS governance_lifecycle_artifacts")
    op.execute("DROP TABLE IF EXISTS governance_release_routes")
    # Cluster-wide roles are intentionally retained; an operator may have bound logins to them.
