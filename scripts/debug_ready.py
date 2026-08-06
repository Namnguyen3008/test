import asyncio
import traceback
from pathlib import Path
from sqlalchemy import text
from redis.asyncio import Redis
from src.config import get_settings
from src.persistence.database import get_engine
from src.governance.manifest import GovernanceManifest, TrustRegistry, verify_evidence, verify_manifest
from src.governance.canonical import digest, strict_json_loads

async def check():
    settings = get_settings()
    print("Database URL:", settings.database_url)
    print("App env:", settings.app_env)
    print("App data mode:", settings.app_data_mode)
    
    with get_engine().connect() as connection:
        migration = connection.scalar(text("SELECT version_num FROM alembic_version"))
        print("Alembic version:", repr(migration))
        extensions = set(
            connection.scalars(
                text("SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm','unaccent')")
            )
        )
        print("Extensions:", extensions)
        active_route = 1
        if settings.app_data_mode == "production":
            manifest = GovernanceManifest.model_validate(
                strict_json_loads(Path(settings.approved_corpus_manifest_path).read_text(encoding="utf-8"))
            )
            manifest_digest = digest(manifest.model_dump(mode="json"))
            active_route = connection.scalar(
                text("SELECT count(*) FROM governance_release_routes grr JOIN governance_manifests gm ON gm.manifest_id=grr.active_manifest_id WHERE grr.route_name='vmec-production-v1' AND grr.state='ACTIVE' AND grr.active_release_id IS NOT NULL AND gm.manifest_id=:manifest_id AND gm.manifest_digest=:manifest_digest AND gm.status='PROMOTED'"),
                {"manifest_id": manifest.manifest_id, "manifest_digest": manifest_digest},
            )
            print("Active route:", active_route)
    
    check_mig = bool(migration and migration.startswith("20260803_0010_signed_"))
    print("Migration match check:", check_mig)
    print("Extensions match check:", extensions == {"vector", "pg_trgm", "unaccent"})
    print("Active route check:", active_route == 1)

    redis = Redis.from_url(settings.redis_url)
    sessions = Redis.from_url(settings.session_redis_url)
    try:
        r_ping = await redis.ping()
        s_ping = await sessions.ping()
        print("Redis ping:", r_ping)
        print("Sessions ping:", s_ping)
    finally:
        await redis.aclose()
        await sessions.aclose()

if __name__ == "__main__":
    try:
        asyncio.run(check())
    except Exception as e:
        traceback.print_exc()
