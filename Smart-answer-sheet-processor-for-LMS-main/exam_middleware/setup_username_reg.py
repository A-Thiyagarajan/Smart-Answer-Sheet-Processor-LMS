"""
Interactive setup script to add or update a single `moodle_username -> register_number` mapping.

Usage examples:
  # interactive prompt
  python setup_username_reg.py

  # provide on the command line
  python setup_username_reg.py --username 22007928 --register 212222240047

This is intended for development: no CSV processing. For bulk imports use migrations or a separate tool.
"""
import argparse
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import StudentUsernameRegister
from app.core.config import settings


async def upsert_mapping(username: str, register: str):
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        # Ensure tables exist in development; production should use alembic
        await conn.run_sync(Base.metadata.create_all)

    AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with AsyncSessionLocal() as session:
        # Try to find existing mapping
        result = await session.execute(
            StudentUsernameRegister.__table__.select().where(StudentUsernameRegister.moodle_username == username)
        )
        found = result.fetchone()
        if found:
            # Update existing
            await session.execute(
                StudentUsernameRegister.__table__.update()
                .where(StudentUsernameRegister.moodle_username == username)
                .values(register_number=register)
            )
            await session.commit()
            print(f"Updated mapping: {username} -> {register}")
        else:
            obj = StudentUsernameRegister(moodle_username=username, register_number=register)
            session.add(obj)
            await session.commit()
            print(f"Inserted mapping: {username} -> {register}")


def parse_args():
    parser = argparse.ArgumentParser(description='Add or update a Moodle username -> register mapping')
    parser.add_argument('--username', '-u', help='Moodle username (e.g. 22007928)')
    parser.add_argument('--register', '-r', help='12-digit register number (e.g. 212222240047)')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    if args.username and args.register:
        uname = args.username.strip()
        reg = args.register.strip()
    else:
        try:
            uname = input('Moodle username: ').strip()
            reg = input('Register number: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nAborted')
            raise SystemExit(1)

    if not uname or not reg:
        print('Both username and register number are required')
        raise SystemExit(1)

    asyncio.run(upsert_mapping(uname, reg))
