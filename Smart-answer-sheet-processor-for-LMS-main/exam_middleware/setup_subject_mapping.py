"""
Complete Subject Mapping Setup Script
=====================================
This script handles the entire process of setting up a new subject:
1. Gets assignment details from Moodle using course module ID
2. Creates/updates subject mapping in database
3. Fixes any existing artifacts with wrong assignment IDs
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select, update
from app.services.moodle_client import MoodleClient
from app.db.database import async_session_maker
from app.db.models import SubjectMapping, ExaminationArtifact, WorkflowStatus


async def find_assignment_by_cmid(moodle_client, cmid):
    """Find assignment details from course module ID"""
    try:
        # Get all courses
        print("  Fetching courses from Moodle...")
        courses_data = await moodle_client.get_courses()
        courses = courses_data.get('courses', [])
        
        if not courses:
            print("  ✗ No courses found")
            return None
        
        print(f"  ✓ Found {len(courses)} courses")
        
        # Get all assignments
        print("  Fetching assignments...")
        course_ids = [c['id'] for c in courses]
        assignments_data = await moodle_client.get_assignments(course_ids)
        
        # Search for matching CMID
        for course in assignments_data.get('courses', []):
            for assignment in course.get('assignments', []):
                if assignment.get('cmid') == int(cmid):
                    return {
                        'assignment_id': assignment.get('id'),
                        'assignment_name': assignment.get('name'),
                        'course_id': assignment.get('course'),
                        'cmid': assignment.get('cmid'),
                        'course_name': next((c['fullname'] for c in courses if c['id'] == course.get('id')), 'Unknown')
                    }
        
        return None
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def get_or_create_subject_mapping(db, subject_code, assignment_data, subject_name=None):
    """Get existing mapping or create new one"""
    try:
        # Check if mapping exists
        result = await db.execute(
            select(SubjectMapping).where(SubjectMapping.subject_code == subject_code)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            print(f"\n  📋 Existing mapping found for {subject_code}:")
            print(f"     Current Assignment ID: {existing.moodle_assignment_id}")
            print(f"     Current Course ID: {existing.moodle_course_id}")
            print(f"     Current Assignment Name: {existing.moodle_assignment_name}")
            return existing, False
        else:
            print(f"\n  ℹ️  No existing mapping for {subject_code}")
            return None, True
            
    except Exception as e:
        print(f"  ✗ Error checking mapping: {e}")
        return None, False


async def update_subject_mapping(db, subject_code, assignment_data, subject_name=None):
    """Update or insert subject mapping"""
    try:
        # Use assignment name as subject name if not provided
        final_subject_name = subject_name or assignment_data['assignment_name']
        
        # Check if exists
        result = await db.execute(
            select(SubjectMapping).where(SubjectMapping.subject_code == subject_code)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing
            existing.moodle_course_id = assignment_data['course_id']
            existing.moodle_assignment_id = assignment_data['assignment_id']
            existing.moodle_assignment_name = assignment_data['assignment_name']
            existing.subject_name = final_subject_name
            existing.is_active = True
            
            await db.commit()
            print(f"\n  ✓ Updated mapping for {subject_code}")
            return existing
        else:
            # Create new
            new_mapping = SubjectMapping(
                subject_code=subject_code,
                subject_name=final_subject_name,
                moodle_course_id=assignment_data['course_id'],
                moodle_assignment_id=assignment_data['assignment_id'],
                moodle_assignment_name=assignment_data['assignment_name'],
                exam_session='2025-2026',
                is_active=True
            )
            
            db.add(new_mapping)
            await db.commit()
            print(f"\n  ✓ Created new mapping for {subject_code}")
            return new_mapping
            
    except Exception as e:
        await db.rollback()
        print(f"  ✗ Error updating mapping: {e}")
        import traceback
        traceback.print_exc()
        return None


async def fix_existing_artifacts(db, subject_code, correct_assignment_id, correct_course_id):
    """Fix any artifacts that have wrong assignment IDs"""
    try:
        # Find artifacts for this subject with wrong assignment ID
        result = await db.execute(
            select(ExaminationArtifact)
            .where(ExaminationArtifact.parsed_subject_code == subject_code)
            .where(ExaminationArtifact.moodle_assignment_id != correct_assignment_id)
        )
        artifacts = result.scalars().all()
        
        if not artifacts:
            print(f"\n  ✓ No artifacts need fixing for {subject_code}")
            return 0
        
        print(f"\n  Found {len(artifacts)} artifact(s) with wrong assignment ID:")
        
        fixed_count = 0
        for artifact in artifacts:
            print(f"    - Artifact ID {artifact.id}: {artifact.original_filename}")
            print(f"      Old assignment ID: {artifact.moodle_assignment_id} → New: {correct_assignment_id}")
            
            # Update the artifact
            stmt = update(ExaminationArtifact).where(
                ExaminationArtifact.id == artifact.id
            ).values(
                moodle_assignment_id=correct_assignment_id,
                moodle_course_id=correct_course_id,
                workflow_status=WorkflowStatus.PENDING,
                error_message=None
            )
            
            await db.execute(stmt)
            fixed_count += 1
        
        await db.commit()
        print(f"\n  ✓ Fixed {fixed_count} artifact(s)")
        return fixed_count
        
    except Exception as e:
        await db.rollback()
        print(f"  ✗ Error fixing artifacts: {e}")
        import traceback
        traceback.print_exc()
        return 0


async def main():
    print("=" * 70)
    print("SUBJECT MAPPING SETUP - Complete Workflow")
    print("=" * 70)
    print()
    print("This script will:")
    print("  1. Find assignment details from Moodle")
    print("  2. Update/create subject mapping in database")
    print("  3. Fix any existing artifacts with wrong assignment IDs")
    print()
    print("=" * 70)
    
    # Step 1: Get subject code
    print("\n📝 Step 1: Subject Information")
    print("-" * 70)
    subject_code = input("Enter subject code (e.g., 19AI411): ").strip().upper()
    
    if not subject_code:
        print("✗ Subject code is required")
        return
    
    subject_name = input(f"Enter subject name (optional, press Enter to use assignment name): ").strip()
    
    # Step 2: Get course module ID
    print("\n🔗 Step 2: Moodle Assignment URL")
    print("-" * 70)
    print("Example URL: http://localhost/mod/assign/view.php?id=7")
    print("The 'id=7' is the course module ID (CMID)")
    print()
    
    cmid_input = input("Enter course module ID from URL: ").strip()
    
    if not cmid_input:
        print("✗ Course module ID is required")
        return
    
    try:
        cmid = int(cmid_input)
    except ValueError:
        print("✗ Invalid course module ID. Please enter a number.")
        return
    
    # Step 3: Authenticate with Moodle
    print("\n🔐 Step 3: Moodle Authentication")
    print("-" * 70)
    
    username = input("Moodle username: ").strip()
    password = input("Moodle password: ").strip()
    
    if not username or not password:
        print("✗ Username and password required")
        return
    
    # Step 4: Find assignment in Moodle
    print(f"\n🔍 Step 4: Finding Assignment (CMID={cmid})")
    print("-" * 70)
    
    moodle = MoodleClient()
    
    try:
        # Authenticate
        print("  Authenticating with Moodle...")
        token_data = await moodle.get_token(username, password)
        moodle.token = token_data['token']
        print(f"  ✓ Authenticated as {username}")
        
        # Find assignment
        assignment_data = await find_assignment_by_cmid(moodle, cmid)
        
        if not assignment_data:
            print(f"\n✗ No assignment found with CMID={cmid}")
            print("\nTroubleshooting:")
            print("  1. Verify the course module ID from the URL")
            print("  2. Make sure you have access to this assignment")
            print("  3. Check if the assignment is in a visible course")
            
            show_all = input("\nShow all available assignments? (y/n): ").strip().lower()
            if show_all == 'y':
                courses_data = await moodle.get_courses()
                courses = courses_data.get('courses', [])
                course_ids = [c['id'] for c in courses]
                assignments_data = await moodle.get_assignments(course_ids)
                
                print("\n" + "=" * 70)
                print("All Available Assignments:")
                print("=" * 70)
                for course in assignments_data.get('courses', []):
                    course_name = next((c['fullname'] for c in courses if c['id'] == course.get('id')), 'Unknown')
                    print(f"\n📚 {course_name} (ID: {course.get('id')})")
                    for assignment in course.get('assignments', []):
                        print(f"   • {assignment.get('name')}")
                        print(f"     Assignment ID: {assignment.get('id')}")
                        print(f"     CMID: {assignment.get('cmid')}")
                        print(f"     URL: http://localhost/mod/assign/view.php?id={assignment.get('cmid')}")
            
            await moodle.close()
            return
        
        print(f"\n  ✓ Found assignment:")
        print(f"     Course: {assignment_data['course_name']}")
        print(f"     Assignment Name: {assignment_data['assignment_name']}")
        print(f"     Assignment ID: {assignment_data['assignment_id']}")
        print(f"     Course Module ID: {assignment_data['cmid']}")
        print(f"     Course ID: {assignment_data['course_id']}")
        
        await moodle.close()
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        await moodle.close()
        return
    
    # Step 5: Update database
    print(f"\n💾 Step 5: Database Update")
    print("-" * 70)
    
    async with async_session_maker() as db:
        # Check existing mapping
        existing, is_new = await get_or_create_subject_mapping(db, subject_code, assignment_data, subject_name)
        
        if not is_new:
            print(f"\n  ⚠️  Mapping already exists. Do you want to update it?")
            print(f"     Old Assignment ID: {existing.moodle_assignment_id}")
            print(f"     New Assignment ID: {assignment_data['assignment_id']}")
            
            confirm = input("\n  Update mapping? (y/n): ").strip().lower()
            if confirm != 'y':
                print("\n  Cancelled by user")
                return
        
        # Update or create mapping
        mapping = await update_subject_mapping(db, subject_code, assignment_data, subject_name)
        
        if not mapping:
            print("\n✗ Failed to update mapping")
            return
        
        print(f"\n  📋 Final Mapping:")
        print(f"     Subject Code: {mapping.subject_code}")
        print(f"     Subject Name: {mapping.subject_name}")
        print(f"     Course ID: {mapping.moodle_course_id}")
        print(f"     Assignment ID: {mapping.moodle_assignment_id}")
        print(f"     Assignment Name: {mapping.moodle_assignment_name}")
        
        # Step 6: Fix existing artifacts
        print(f"\n🔧 Step 6: Fix Existing Artifacts")
        print("-" * 70)
        
        fixed_count = await fix_existing_artifacts(
            db,
            subject_code,
            assignment_data['assignment_id'],
            assignment_data['course_id']
        )
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ SETUP COMPLETE!")
    print("=" * 70)
    print(f"\nSubject Code: {subject_code}")
    print(f"Assignment ID: {assignment_data['assignment_id']}")
    print(f"Course ID: {assignment_data['course_id']}")
    print(f"Artifacts Fixed: {fixed_count}")
    print("\n✓ Students can now submit papers for this subject!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
    except Exception as e:
        print(f"\n\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
