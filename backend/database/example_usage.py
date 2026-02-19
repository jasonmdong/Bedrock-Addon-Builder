"""Example database usage script."""
from backend.database import get_connection, fetch_all, fetch_one, execute_query, Database


# Example 1: Using raw SQL with fetch_all (SELECT multiple rows)
def example_select_all():
    sql = "SELECT * FROM your_table LIMIT 10"
    rows = fetch_all(sql)
    for row in rows:
        print(row)


# Example 2: Using raw SQL with fetch_one (SELECT single row)
def example_select_one():
    sql = "SELECT * FROM your_table WHERE id = %s"
    row = fetch_one(sql, (1,))
    if row:
        print(row)


# Example 3: Using raw SQL with execute_query (INSERT, UPDATE, DELETE)
def example_insert():
    sql = "INSERT INTO your_table (name, value) VALUES (%s, %s)"
    execute_query(sql, ("test", 42))
    print("Inserted successfully")


# Example 4: Using the Database helper class (INSERT)
def example_helper_insert():
    Database.insert("your_table", {
        "name": "example",
        "value": 100,
        "status": "active"
    })
    print("Inserted using Database helper")


# Example 5: Using the Database helper class (SELECT)
def example_helper_select():
    rows = Database.select("your_table", where={"status": "active"})
    for row in rows:
        print(row)


# Example 6: Using the Database helper class (UPDATE)
def example_helper_update():
    Database.update(
        "your_table",
        {"status": "inactive", "value": 200},
        {"id": 1}
    )
    print("Updated successfully")


# Example 7: Using the Database helper class (DELETE)
def example_helper_delete():
    Database.delete("your_table", {"id": 1})
    print("Deleted successfully")


# Example 8: Direct connection if you need more control
def example_raw_connection():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"PostgreSQL version: {version}")
        conn.commit()
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    print("Database module is ready to use!")
    print("Import and use the functions in your scripts:")
    print("  from backend.database import fetch_all, fetch_one, execute_query, Database")
