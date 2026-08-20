"""One-off cleanup of QA/TEST seed artifacts created during regression testing."""
import asyncio
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

env = dotenv_values("/app/backend/.env")


async def main():
    cl = AsyncIOMotorClient(env["MONGO_URL"])
    db = cl[env["DB_NAME"]]
    for coll, field in [("project_ids", "code"), ("accounts", "name")]:
        r = await db[coll].delete_many({field: {"$regex": "^(TEST_|QA_)"}})
        print(coll, "deleted", r.deleted_count)
    r = await db.transactions.delete_many({"notes": {"$regex": "^(TEST_|QA_)"}})
    print("transactions deleted", r.deleted_count)
    r = await db.transactions.delete_many({"project_id": {"$regex": "^(TEST_|QA_)"}})
    print("transactions(project) deleted", r.deleted_count)
    cl.close()


asyncio.run(main())
