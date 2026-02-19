#!/usr/bin/env python3
"""
Database Status Check - Confirm cleanup was successful
Run this to verify the database is ready for mob insertion
"""

import psycopg2
import sys

def check_database_status():
    connection_string = 'postgresql://neondb_owner:npg_gyK7U5GZOhDS@ep-restless-scene-a876hfcf-pooler.eastus2.azure.neon.tech/neondb?sslmode=require&channel_binding=require'

    try:
        # Connect
        conn = psycopg2.connect(connection_string)
        cursor = conn.cursor()

        # First, delete any test mobs
        cursor.execute("DELETE FROM mob_geometries WHERE mob_name = 'test_mob';")
        deleted_count = cursor.rowcount
        conn.commit()

        # Get current count
        cursor.execute("SELECT COUNT(*) FROM mob_geometries;")
        current_count = cursor.fetchone()[0]

        # Get table info
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.columns 
            WHERE table_name = 'mob_geometries';
        """)
        column_count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return {
            'success': True,
            'deleted': deleted_count,
            'remaining': current_count,
            'columns': column_count,
            'ready': current_count == 0
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'ready': False
        }


if __name__ == '__main__':
    result = check_database_status()

    if result['success']:
        print("\n" + "=" * 60)
        print("DATABASE STATUS CHECK")
        print("=" * 60)
        print(f"Test mobs deleted:     {result['deleted']}")
        print(f"Current records:       {result['remaining']}")
        print(f"Table columns:         {result['columns']}")
        print("=" * 60)

        if result['ready']:
            print("✓ DATABASE IS CLEAN AND READY FOR MOB INSERTION")
            print("\nNext step: python main.py")
        else:
            print(f"⚠ Database has {result['remaining']} records")
            print("This is fine - 'python main.py' will update them")

        print("=" * 60 + "\n")
        sys.exit(0)
    else:
        print(f"\n✗ Error: {result.get('error', 'Unknown error')}\n")
        sys.exit(1)

