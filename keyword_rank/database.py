import sqlite3
from datetime import datetime

DB_NAME = "rank_tracker.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT,
            city TEXT,
            area TEXT,
            latitude REAL,
            longitude REAL,
            brand TEXT,
            domain TEXT,
            method TEXT,
            organic_rank INTEGER,
            local_rank INTEGER,
            raw_organic_count INTEGER,
            raw_local_count INTEGER,
            date_checked TEXT,
            time_checked TEXT,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_keyword_history(keyword, city=None, limit=50):
    """Retrieve keyword ranking history for specific keyword/city."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if city:
        query = """
            SELECT keyword, city, area, organic_rank, local_rank, 
                   date_checked, time_checked, timestamp
            FROM rankings 
            WHERE keyword = ? AND city = ?
            ORDER BY timestamp DESC 
            LIMIT ?
        """
        cursor.execute(query, (keyword, city, limit))
    else:
        query = """
            SELECT keyword, city, area, organic_rank, local_rank, 
                   date_checked, time_checked, timestamp
            FROM rankings 
            WHERE keyword = ?
            ORDER BY timestamp DESC 
            LIMIT ?
        """
        cursor.execute(query, (keyword, limit))
    
    rows = cursor.fetchall()
    columns = [col[0] for col in cursor.description]
    conn.close()
    return rows, columns






def save_result(result, city, area, lat, lng, brand, domain):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    now = datetime.now()

    cursor.execute("""
        INSERT INTO rankings (
            keyword, city, area, latitude, longitude,
            brand, domain, method,
            organic_rank, local_rank,
            raw_organic_count, raw_local_count,
            date_checked, time_checked, timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result.get("keyword"),
        city,
        area,
        lat,
        lng,
        brand,
        domain,
        result.get("method"),
        result.get("organic_rank"),
        result.get("local_rank"),
        result.get("raw_organic_count"),
        result.get("raw_local_count"),

       
        now.date().isoformat(),
        now.time().isoformat(),

        now.isoformat()
    ))

    conn.commit()
    conn.close()


def get_daily_rank_range(keyword, city=None):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if city:
        cursor.execute("""
            SELECT 
                keyword,
                city,
                area,
                date_checked AS date,

                MIN(organic_rank) AS min_organic_rank,
                MAX(organic_rank) AS max_organic_rank,

                MIN(local_rank) AS min_local_rank,
                MAX(local_rank) AS max_local_rank

            FROM rankings
            WHERE keyword = ? AND city = ?
            GROUP BY keyword, city, area, date_checked
            ORDER BY date_checked DESC
        """, (keyword, city))

    else:
        cursor.execute("""
            SELECT 
                keyword,
                city,
                area,
                date_checked AS date,

                MIN(organic_rank) AS min_organic_rank,
                MAX(organic_rank) AS max_organic_rank,

                MIN(local_rank) AS min_local_rank,
                MAX(local_rank) AS max_local_rank

            FROM rankings
            WHERE keyword = ?
            GROUP BY keyword, city, area, date_checked
            ORDER BY date_checked DESC
        """, (keyword,))

    rows = cursor.fetchall()
    columns = [col[0] for col in cursor.description]

    conn.close()
    return rows, columns
