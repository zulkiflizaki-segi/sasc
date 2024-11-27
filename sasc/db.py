import mysql.connector

def connect_db():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='',  # Replace with your actual MySQL password
        database='sasc'
    )

