"""
Database initialization script for Examination Middleware
Creates all tables and seeds initial data
"""

import asyncio
import sys
import os
import argparse
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.db.database import engine, Base, async_session_maker
from app.db.models import (
    StaffUser,
    SubjectMapping,
    SystemConfig,
    ExaminationArtifact,
    AuditLog,
    StudentUsernameRegister,
)
from app.core.security import get_password_hash


async def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] Database tables created successfully!")


async def seed_staff_user():
    """Create default admin staff user."""
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT id FROM staff_users WHERE username = 'admin' ORDER BY id LIMIT 1")
        )
        existing = result.fetchone()

        if not existing:
            # For production, generate a strong default password
            default_password = os.getenv('ADMIN_PASSWORD', 'ChangeMe@123')
            if default_password == 'ChangeMe@123' and os.getenv('ENVIRONMENT') == 'production':
                print("[WARNING] Using default admin password. Please change this immediately!")
                print("[WARNING] Set ADMIN_PASSWORD environment variable for custom password")
            
            admin = StaffUser(
                username="admin",
                hashed_password=get_password_hash(default_password),
                full_name="Administrator",
                email=os.getenv('ADMIN_EMAIL', 'admin@example.com'),
                role="admin",
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            print(f"[OK] Created default admin user")
            print(f"[OK] Username: admin")
            print(f"[OK] Password: {default_password}")
            print("[WARNING] Change password immediately after first login!")
        else:
            print("[INFO] Admin user already exists")


async def seed_subject_mappings():
    """Seed subject to Moodle assignment mappings."""
    # Based on the Moodle setup provided:
    # 19AI405 -> Assignment ID 4 (DEEP LEARNING)
    # 19AI411 -> Assignment ID 6 (NLP)
    # ML -> Assignment ID 2 (MACHINE LEARNING)
    
    mappings = [
        {
            "subject_code": "19AI404",
            "subject_name": "19AI404",
            "moodle_course_id": 404,
            "moodle_assignment_id": 4041,
            "moodle_assignment_name": "CIA Exam",
            "exam_session": "2024-1",
            "is_active": True,
        },
        {
            "subject_code": "19AI505",
            "subject_name": "19AI505",
            "moodle_course_id": 505,
            "moodle_assignment_id": 5051,
            "moodle_assignment_name": "CIA Exam",
            "exam_session": "2024-1",
            "is_active": True,
        },
        {
            "subject_code": "19AI405",
            "subject_name": "19AI405",
            "moodle_course_id": 405,
            "moodle_assignment_id": 4051,
            "moodle_assignment_name": "CIA Exam",
            "exam_session": "2024-1",
            "is_active": True,
        },
    ]
    
    async with async_session_maker() as session:
        for mapping in mappings:
            # Check if mapping exists
            result = await session.execute(
                text("SELECT id FROM subject_mappings WHERE subject_code = :code"),
                {"code": mapping["subject_code"]}
            )
            existing = result.fetchone()
            
            if not existing:
                subject_mapping = SubjectMapping(**mapping)
                session.add(subject_mapping)
                print(f"[OK] Created mapping: {mapping['subject_code']} -> Assignment {mapping['moodle_assignment_id']}")
            else:
                obj = await session.get(SubjectMapping, existing[0])
                obj.subject_name = mapping.get("subject_name")
                obj.moodle_course_id = mapping.get("moodle_course_id")
                obj.moodle_assignment_id = mapping.get("moodle_assignment_id")
                obj.moodle_assignment_name = mapping.get("moodle_assignment_name")
                obj.exam_session = mapping.get("exam_session")
                obj.is_active = mapping.get("is_active", True)
                print(f"[OK] Updated mapping: {mapping['subject_code']} -> Assignment {mapping['moodle_assignment_id']}")
        
        await session.commit()


async def seed_mock_student_mapping():
    """Seed development mock LMS student mapping (development only)."""
    # Skip if running in production
    if os.getenv('ENVIRONMENT') == 'production' and os.getenv('MOCK_LMS_ENABLED') == 'False':
        print("[INFO] Skipping mock student mapping (production mode)")
        return
    
    async with async_session_maker() as session:
        result = await session.execute(
            text("SELECT id FROM student_username_register LIMIT 1")
        )
        existing = result.fetchone()

        if not existing:
            # Only seed if no records exist
            session.add(
                StudentUsernameRegister(
                    moodle_username="test_user",
                    register_number="000000000000",
                )
            )
            await session.commit()
            print("[INFO] Created development test student mapping (not for production)")
        else:
            print("[INFO] Student mappings already exist")


async def seed_system_config():
    """Seed system configuration."""
    configs = [
        {
            "key": "moodle_maintenance_mode",
            "value": "false",
            "description": "Whether Moodle is in maintenance mode",
        },
        {
            "key": "max_file_size_mb",
            "value": "50",
            "description": "Maximum file size in MB for uploads",
        },
        {
            "key": "allowed_extensions",
            "value": "pdf,jpg,jpeg,png",
            "description": "Comma-separated list of allowed file extensions",
        },
        {
            "key": "exam_session",
            "value": "2024-SPRING",
            "description": "Current examination session",
        },
    ]
    
    async with async_session_maker() as session:
        for config in configs:
            result = await session.execute(
                text("SELECT id FROM system_config WHERE key = :key"),
                {"key": config["key"]}
            )
            existing = result.fetchone()
            
            if not existing:
                sys_config = SystemConfig(**config)
                session.add(sys_config)
                print(f"[OK] Created config: {config['key']} = {config['value']}")
            else:
                print(f"[OK] Config already exists: {config['key']}")
        
        await session.commit()


async def verify_database():
    """Verify database connection and tables."""
    print("\nVerifying database connection...")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("[OK] Database connection successful!")
            
        # List all tables
        async with engine.begin() as conn:
            if engine.url.get_backend_name() == "sqlite":
                result = await conn.execute(text("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """))
            else:
                result = await conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """))
            tables = [row[0] for row in result.fetchall()]
            print(f"[OK] Found {len(tables)} tables: {', '.join(tables)}")
            
    except Exception as e:
        print(f"[ERROR] Database error: {e}")
        return False
    
    return True


async def seed_sample_data():
    """Create a small sample artifact and associated audit logs (development only)."""
    # Skip if running in production
    if os.getenv('ENVIRONMENT') == 'production':
        print("[INFO] Skipping sample data (production mode)")
        return
    
    async with async_session_maker() as session:
        # Create a sample artifact
        sample = ExaminationArtifact(
            raw_filename='sample_000000000000_DEV.pdf',
            original_filename='000000000000_DEV.pdf',
            file_blob_path='storage/sample/000000000000_DEV.pdf',
            file_hash='dev0000000000000000000000000000000000000000000000000000000000000',
            parsed_reg_no='000000000000',
            parsed_subject_code='DEV',
            file_size_bytes=1024,
            mime_type='application/pdf',
            workflow_status='PENDING'
        )
        session.add(sample)
        await session.flush()

        # Create a sample report_issue audit log
        issue = AuditLog(
            action='report_issue',
            action_category='report',
            actor_type='student',
            actor_id='000000000000',
            actor_username='test_user',
            artifact_id=sample.id,
            description='Development sample report (for testing)',
            request_data={'notes': 'Sample created by init_db for development'},
        )
        session.add(issue)
        await session.flush()

        await session.commit()
        print('[OK] Seeded development sample artifact and audit log')


async def main(seed_samples: bool = False):
    """Main initialization function."""
    print("=" * 60)
    print("  Examination Middleware - Database Initialization")
    print("=" * 60)
    print()
    
    # Create tables
    await create_tables()
    print()
    
    # Seed data
    print("Seeding initial data...")
    await seed_staff_user()
    await seed_subject_mappings()
    await seed_mock_student_mapping()
    await seed_system_config()
    if seed_samples:
        print("Seeding optional sample data...")
        await seed_sample_data()
    print()
    
    # Verify
    success = await verify_database()
    
    if success:
        print()
        print("=" * 60)
        print("  Database initialization completed successfully!")
        print("=" * 60)
        print()
        print("  You can now start the application with:")
        print("  python run.py")
        print()
    else:
        print()
        print("=" * 60)
        print("  Database initialization failed!")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Initialize database and seed data')
    parser.add_argument('--seed-samples', action='store_true', help='Seed sample artifacts and audit logs for local testing')
    args = parser.parse_args()

    asyncio.run(main(seed_samples=args.seed_samples))
