"""
Test script to verify Neon PostgreSQL database connection.
Run this to test that your connection string works and the table is properly set up.
"""

import sys
from datetime import datetime
from neon_db import NeonDatabaseConnection


def test_connection():
    """Test basic database connection."""
    print("=" * 80)
    print("TEST 1: Database Connection")
    print("=" * 80)

    connection_string = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'

    db = NeonDatabaseConnection(connection_string)

    if db.connect():
        print("✓ Successfully connected to Neon PostgreSQL")
        return True
    else:
        print("✗ Failed to connect to database")
        return False


def test_table_creation(db):
    """Test table creation."""
    print("\n" + "=" * 80)
    print("TEST 2: Table Creation")
    print("=" * 80)

    if db.create_table():
        print("✓ Table created or already exists")
        return True
    else:
        print("✗ Failed to create table")
        return False


def test_insert_sample_mob(db):
    """Test inserting a sample mob."""
    print("\n" + "=" * 80)
    print("TEST 3: Insert Sample Mob")
    print("=" * 80)

    sample_geometry = {
        "format_version": "1.8.0",
        "minecraft:geometry": [
            {
                "description": {
                    "identifier": "geometry.test_mob",
                    "texture_width": 64,
                    "texture_height": 32
                },
                "bones": [
                    {
                        "name": "body",
                        "pivot": [0, 0, 0],
                        "cubes": [
                            {"origin": [-4, 0, -4], "size": [8, 8, 8], "uv": [0, 0]}
                        ]
                    }
                ]
            }
        ]
    }

    sample_bone_metadata = {
        "bones": ["body"],
        "bone_count": 1,
        "total_cubes": 1
    }

    if db.insert_mob(
        mob_name="test_mob",
        mob_description="This is a test mob for database verification",
        prompt="",
        mob_keywords=["test", "sample"],
        mob_geometry=sample_geometry,
        bone_metadata=sample_bone_metadata,
        complexity_score=10,
        is_official=False,
        creation_date=datetime.now().isoformat()
    ):
        print("✓ Successfully inserted test mob")
        return True
    else:
        print("✗ Failed to insert test mob")
        return False


def test_retrieve_mob(db):
    """Test retrieving a mob."""
    print("\n" + "=" * 80)
    print("TEST 4: Retrieve Mob Data")
    print("=" * 80)

    mob = db.get_mob("test_mob")

    if mob:
        print("✓ Successfully retrieved test mob")
        print(f"  - Mob ID: {mob['mob_id']}")
        print(f"  - Mob Name: {mob['mob_name']}")
        print(f"  - Description: {mob['mob_description']}")
        print(f"  - Keywords: {mob['mob_keywords']}")
        print(f"  - Complexity Score: {mob['complexity_score']}")
        print(f"  - Is Official: {mob['is_official']}")
        print(f"  - Geometry has {len(str(mob['mob_geometry']))} characters")
        return True
    else:
        print("✗ Failed to retrieve test mob")
        return False


def test_count_mobs(db):
    """Test counting total mobs."""
    print("\n" + "=" * 80)
    print("TEST 5: Count Total Mobs")
    print("=" * 80)

    count = db.get_all_mobs()

    if count is not None:
        print(f"✓ Total mobs in database: {count}")
        return True
    else:
        print("✗ Failed to count mobs")
        return False


def test_update_mob(db):
    """Test updating a mob."""
    print("\n" + "=" * 80)
    print("TEST 6: Update Mob Data")
    print("=" * 80)

    if db.insert_mob(
        mob_name="test_mob",
        mob_description="This is an UPDATED test mob",
        prompt="",
        mob_keywords=["test", "sample", "updated"],
        mob_geometry={"test": "geometry"},
        bone_metadata={"test": "metadata"},
        complexity_score=20,
        is_official=True,
        creation_date=datetime.now().isoformat()
    ):
        print("✓ Successfully updated test mob")

        # Verify the update
        mob = db.get_mob("test_mob")
        if mob and mob['mob_description'] == "This is an UPDATED test mob":
            print("✓ Verified: Description was updated")
            return True
        else:
            print("✗ Update verification failed")
            return False
    else:
        print("✗ Failed to update test mob")
        return False


def test_delete_test_data(db):
    """Clean up test data."""
    print("\n" + "=" * 80)
    print("TEST 7: Clean Up Test Data")
    print("=" * 80)

    try:
        cursor = db.conn.cursor()
        cursor.execute("DELETE FROM mob_geometries WHERE mob_name = 'test_mob';")
        db.conn.commit()
        cursor.close()
        print("✓ Successfully deleted test mob")
        return True
    except Exception as e:
        print(f"✗ Failed to delete test mob: {e}")
        return False


def run_all_tests():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 78 + "║")
    print("║" + "NEON PostgreSQL Database Connection Test Suite".center(78) + "║")
    print("║" + " " * 78 + "║")
    print("╚" + "=" * 78 + "╝")
    print()

    results = []

    # Test 1: Connection
    if not test_connection():
        print("\n✗ Connection test failed. Stopping tests.")
        return

    db = NeonDatabaseConnection('postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require')
    db.connect()

    # Test 2: Table Creation
    results.append(("Table Creation", test_table_creation(db)))

    # Test 3: Insert Sample Mob
    results.append(("Insert Sample Mob", test_insert_sample_mob(db)))

    # Test 4: Retrieve Mob
    results.append(("Retrieve Mob Data", test_retrieve_mob(db)))

    # Test 5: Count Mobs
    results.append(("Count Total Mobs", test_count_mobs(db)))

    # Test 6: Update Mob
    results.append(("Update Mob Data", test_update_mob(db)))

    # Test 7: Clean Up
    results.append(("Clean Up Test Data", test_delete_test_data(db)))

    # Disconnect
    db.disconnect()

    # Print summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name.ljust(30)} {status}")

    print("=" * 80)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 80)

    if passed == total:
        print("\n✓ All tests passed! Your database connection is working correctly.")
        return True
    else:
        print(f"\n✗ {total - passed} test(s) failed. Check the errors above.")
        return False


if __name__ == "__main__":
    try:
        success = run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n✗ Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

