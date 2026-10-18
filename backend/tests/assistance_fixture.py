"""External operator changes for browser races, exact leased disposable DB only."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
import os
import sys
from uuid import UUID
from sqlalchemy import update,text
from sqlalchemy.ext.asyncio import create_async_engine
from app.models.identity import Membership
from tests.safety import validate_test_database,TestSafetyError

async def main():
    target=validate_test_database(os.environ)
    if target.lane!='wave3_integration':raise TestSafetyError('Assistance browser changes require its allocated lane')
    operation,business,user=sys.argv[1:]
    if operation not in ('revoke','viewer'):raise ValueError('Unknown synthetic operator change')
    engine=create_async_engine(target.url)
    try:
        async with engine.begin() as db:
            if await db.scalar(text('SELECT current_database()'))!=target.database:raise TestSafetyError('Wrong browser lane')
            values={'is_active':False} if operation=='revoke' else {'role':'viewer'}
            result=await db.execute(update(Membership).where(Membership.business_id==UUID(business),Membership.user_id==UUID(user)).values(**values))
            if result.rowcount!=1:raise AssertionError('Expected one synthetic membership')
    finally:await engine.dispose()

if __name__=='__main__':asyncio.run(main())
