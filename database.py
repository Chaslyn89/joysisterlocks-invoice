import sqlite3
from datetime import datetime, timedelta
import uuid
from functools import wraps
import time

DB_PATH = 'clients.db'

# Simple in-memory cache for dashboard stats
_cache = {}
CACHE_TTL = 60  # seconds

def cache_result(ttl=CACHE_TTL):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{args}:{kwargs}"
            now = time.time()
            if cache_key in _cache:
                result, timestamp = _cache[cache_key]
                if now - timestamp < ttl:
                    return result
            result = func(*args, **kwargs)
            _cache[cache_key] = (result, now)
            return result
        return wrapper
    return decorator

def get_db():
    """Get database connection with foreign keys enabled"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def get_current_date():
    """Get current date in consistent YYYY-MM-DD format"""
    return datetime.now().strftime('%Y-%m-%d')

def init_db():
    """Initialize database with all tables and indexes"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Main clients table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                client_phone TEXT UNIQUE NOT NULL,
                client_email TEXT,
                join_date TEXT,
                total_visits INTEGER DEFAULT 0,
                gross_spent INTEGER DEFAULT 0,
                total_paid INTEGER DEFAULT 0,
                last_visit TEXT,
                category TEXT DEFAULT 'New',
                retention_status TEXT DEFAULT 'Active',
                notes TEXT,
                preferred_stylist TEXT DEFAULT 'Joy',
                preferred_contact TEXT DEFAULT 'WhatsApp',
                birthday TEXT,
                referrer TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        
        # Services catalog table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                price INTEGER NOT NULL,
                category TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
        ''')
        
        # Insert default services
        default_services = [
            ('Sister Locs Retie', 3500, 'Retie'),
            ('Micro Locs Retie', 3500, 'Retie'),
            ('Sister Locs Full Installation', 15000, 'Installation'),
            ('Sister Locs Colour & Styling', 4500, 'Colour'),
            ('Sister Locs Colour + Retie', 5500, 'Combo'),
            ('Wash, Retie, Massage & Styling', 3000, 'Package')
        ]
        for name, price, category in default_services:
            cursor.execute('''
                INSERT OR IGNORE INTO services (name, price, category, is_active, created_at)
                VALUES (?, ?, ?, 1, ?)
            ''', (name, price, category, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        # Service history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS service_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                invoice_number TEXT,
                service_date TEXT,
                service_name TEXT,
                service_details TEXT,
                amount INTEGER,
                amount_paid INTEGER,
                balance INTEGER,
                payment_method TEXT,
                stylist_name TEXT,
                notes TEXT,
                mpesa_code TEXT,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
        ''')
        
        # Appointments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                appointment_date TEXT,
                appointment_time TEXT,
                service_name TEXT,
                status TEXT DEFAULT 'scheduled',
                reminder_sent INTEGER DEFAULT 0,
                created_at TEXT,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
        ''')
        
        # Expenses table with deleted_at for soft delete
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                amount INTEGER,
                description TEXT,
                expense_date TEXT,
                created_at TEXT,
                deleted_at TEXT
            )
        ''')
        
        # Client health/allergies table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS client_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                allergy_type TEXT,
                allergy_description TEXT,
                severity TEXT DEFAULT 'Medium',
                recorded_date TEXT,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
        ''')
        
        # Communications table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS communications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                comm_date TEXT,
                comm_type TEXT,
                message TEXT,
                sent_by TEXT,
                FOREIGN KEY (client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
        ''')
        
        # INDEXES for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_phone ON clients(client_phone)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_name ON clients(client_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_visit ON clients(last_visit)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_service_client ON service_history(client_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_appointment_date ON appointments(appointment_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_expense_date ON expenses(expense_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_expense_deleted ON expenses(deleted_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_service_history_date ON service_history(service_date)')
        
        conn.commit()

def get_or_create_client(client_data):
    """Get existing client by phone or create new one"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM clients WHERE client_phone = ?', (client_data['client_phone'],))
        client = cursor.fetchone()
        
        if client:
            cursor.execute('''
                UPDATE clients 
                SET client_name = ?, client_email = ?, updated_at = ?
                WHERE client_phone = ?
            ''', (client_data['client_name'], client_data.get('client_email', ''), 
                  get_current_date(), client_data['client_phone']))
            client_id = client['id']
        else:
            cursor.execute('''
                INSERT INTO clients (
                    client_name, client_phone, client_email, join_date, 
                    category, retention_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (client_data['client_name'], client_data['client_phone'], 
                  client_data.get('client_email', ''), get_current_date(),
                  'New', 'Active', get_current_date(), get_current_date()))
            client_id = cursor.lastrowid
        
        conn.commit()
        return client_id

def generate_invoice_number():
    """Generate unique invoice number using UUID"""
    return f"JSL-{uuid.uuid4().hex[:8].upper()}"

def get_client_visits(client_id):
    """Get total visits count for a client"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT total_visits FROM clients WHERE id = ?', (client_id,))
        result = cursor.fetchone()
        return result['total_visits'] if result else 0

def save_service_record(client_id, invoice_data):
    """Save service history after invoice - wrapped in transaction"""
    with get_db() as conn:
        try:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO service_history (
                    client_id, invoice_number, service_date, service_name, 
                    service_details, amount, amount_paid, balance, 
                    payment_method, stylist_name, notes, mpesa_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (client_id, invoice_data['invoice_number'], invoice_data['date'],
                  invoice_data['service_name'], invoice_data.get('service_details', ''),
                  invoice_data['total'], invoice_data['amount_paid'], invoice_data['balance'],
                  invoice_data['payment_method'], invoice_data.get('stylist_name', 'Joy'),
                  invoice_data.get('notes', ''), invoice_data.get('mpesa_code', '')))
            
            cursor.execute('''
                UPDATE clients 
                SET total_visits = total_visits + 1,
                    gross_spent = gross_spent + ?,
                    total_paid = total_paid + ?,
                    last_visit = ?,
                    category = CASE 
                        WHEN total_visits + 1 >= 10 THEN 'VIP'
                        WHEN total_visits + 1 >= 5 THEN 'Regular'
                        ELSE category
                    END,
                    retention_status = 'Active',
                    updated_at = ?
                WHERE id = ?
            ''', (invoice_data['total'], invoice_data['amount_paid'], invoice_data['date'], 
                  get_current_date(), client_id))
            
            _cache.clear()
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

def update_retention_status():
    """Update client retention status based on last visit"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE clients 
            SET retention_status = CASE
                WHEN julianday(?) - julianday(last_visit) <= 30 THEN 'Active'
                WHEN julianday(?) - julianday(last_visit) <= 60 THEN 'At Risk'
                WHEN julianday(?) - julianday(last_visit) <= 90 THEN 'Inactive'
                ELSE 'Lost'
            END
            WHERE last_visit IS NOT NULL
        ''', (get_current_date(), get_current_date(), get_current_date()))
        conn.commit()

def search_clients(search_term, request_count=1):
    """Search clients by name or phone with rate limiting protection"""
    if len(search_term) > 50:
        return []
    
    if request_count > 100:
        return []
    
    with get_db() as conn:
        cursor = conn.cursor()
        search_term_escaped = search_term.replace('%', r'\%').replace('_', r'\_')
        search_pattern = f'%{search_term_escaped}%'
        cursor.execute('''
            SELECT id, client_name, client_phone, total_visits, gross_spent, 
                   last_visit, category, retention_status
            FROM clients 
            WHERE client_name LIKE ? ESCAPE '\' OR client_phone LIKE ? ESCAPE '\'
            ORDER BY gross_spent DESC, last_visit DESC
            LIMIT 50
        ''', (search_pattern, search_pattern))
        
        return cursor.fetchall()

def get_recent_clients(limit=10):
    """Get most recent clients"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, client_name, client_phone, total_visits, gross_spent, 
                   last_visit, category, retention_status, join_date
            FROM clients 
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

def get_top_clients(limit=10):
    """Get top spending clients by gross_spent"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, client_name, client_phone, total_visits, gross_spent, 
                   last_visit, category, retention_status
            FROM clients 
            ORDER BY gross_spent DESC
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

def get_at_risk_clients():
    """Get clients who are At Risk or Inactive or Lost"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, client_name, client_phone, last_visit, retention_status
            FROM clients 
            WHERE retention_status IN ('At Risk', 'Inactive', 'Lost')
            ORDER BY last_visit ASC
        ''')
        return cursor.fetchall()

def get_client_by_id(client_id):
    """Get complete client profile"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM clients WHERE id = ?', (client_id,))
        client = cursor.fetchone()
        
        if client:
            cursor.execute('''
                SELECT * FROM service_history 
                WHERE client_id = ? 
                ORDER BY service_date DESC
            ''', (client_id,))
            services = cursor.fetchall()
            
            cursor.execute('SELECT * FROM client_health WHERE client_id = ?', (client_id,))
            health = cursor.fetchall()
            
            cursor.execute('''
                SELECT * FROM communications 
                WHERE client_id = ? 
                ORDER BY comm_date DESC LIMIT 10
            ''', (client_id,))
            communications = cursor.fetchall()
            
            cursor.execute('''
                SELECT * FROM appointments 
                WHERE client_id = ? 
                ORDER BY appointment_date DESC LIMIT 5
            ''', (client_id,))
            appointments = cursor.fetchall()
            
            return {
                'client': client,
                'services': services,
                'health': health,
                'communications': communications,
                'appointments': appointments
            }
        return None

@cache_result(ttl=CACHE_TTL)
def get_client_stats():
    """Get overall business statistics with caching"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        update_retention_status()
        
        cursor.execute('SELECT COUNT(*) AS total FROM clients')
        total_clients = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) AS vip FROM clients WHERE category = 'VIP'")
        vip_count = cursor.fetchone()['vip']
        
        cursor.execute("SELECT COUNT(*) AS regular FROM clients WHERE category = 'Regular'")
        regular_count = cursor.fetchone()['regular']
        
        current_month = get_current_date()[:7]
        cursor.execute('''
            SELECT COUNT(*) AS new_this_month FROM clients 
            WHERE join_date LIKE ?
        ''', (f'{current_month}%',))
        new_this_month = cursor.fetchone()['new_this_month']
        
        cursor.execute('SELECT COALESCE(SUM(amount), 0) AS gross_revenue FROM service_history')
        gross_revenue = cursor.fetchone()['gross_revenue']
        
        cursor.execute('SELECT COALESCE(SUM(amount_paid), 0) AS cash_collected FROM service_history')
        cash_collected = cursor.fetchone()['cash_collected']
        
        cursor.execute('SELECT COALESCE(SUM(balance), 0) AS outstanding FROM service_history')
        outstanding = cursor.fetchone()['outstanding']
        
        cursor.execute('SELECT COALESCE(AVG(amount), 0) AS avg_visit FROM service_history')
        avg_visit = cursor.fetchone()['avg_visit']
        
        cursor.execute("SELECT COUNT(*) AS at_risk FROM clients WHERE retention_status = 'At Risk'")
        at_risk = cursor.fetchone()['at_risk']
        
        cursor.execute("SELECT COUNT(*) AS lost FROM clients WHERE retention_status = 'Lost'")
        lost = cursor.fetchone()['lost']
        
        return {
            'total_clients': total_clients,
            'vip_count': vip_count,
            'regular_count': regular_count,
            'new_this_month': new_this_month,
            'gross_revenue': gross_revenue,
            'cash_collected': cash_collected,
            'outstanding': outstanding,
            'avg_visit': avg_visit,
            'at_risk': at_risk,
            'lost': lost
        }

@cache_result(ttl=CACHE_TTL)
def get_dashboard_stats():
    """Get statistics for dashboard with revenue data for chart"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        today = get_current_date()
        
        cursor.execute('''
            SELECT COALESCE(SUM(amount_paid), 0) AS today_revenue 
            FROM service_history 
            WHERE service_date = ?
        ''', (today,))
        today_revenue = cursor.fetchone()['today_revenue']
        
        cursor.execute('''
            SELECT COUNT(*) AS today_appointments 
            FROM appointments 
            WHERE appointment_date = ? AND status != 'cancelled'
        ''', (today,))
        today_appointments = cursor.fetchone()['today_appointments']
        
        cursor.execute('SELECT COALESCE(SUM(balance), 0) AS total_outstanding FROM service_history')
        total_outstanding = cursor.fetchone()['total_outstanding']
        
        cursor.execute('SELECT COALESCE(SUM(amount), 0) AS gross_revenue FROM service_history')
        gross_revenue = cursor.fetchone()['gross_revenue']
        
        cursor.execute('SELECT COALESCE(SUM(amount), 0) AS total_expenses FROM expenses WHERE deleted_at IS NULL')
        total_expenses = cursor.fetchone()['total_expenses']
        
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT service_date, COALESCE(SUM(amount_paid), 0) AS daily_revenue
            FROM service_history
            WHERE service_date >= ?
            GROUP BY service_date
            ORDER BY service_date
        ''', (thirty_days_ago,))
        revenue_data_rows = cursor.fetchall()
        
        revenue_data = [row['daily_revenue'] for row in revenue_data_rows]
        revenue_dates = [row['service_date'] for row in revenue_data_rows]
        
        return {
            'today_revenue': today_revenue,
            'today_appointments': today_appointments,
            'total_outstanding': total_outstanding,
            'gross_revenue': gross_revenue,
            'total_expenses': total_expenses,
            'profit': gross_revenue - total_expenses,
            'revenue_data': revenue_data,
            'revenue_dates': revenue_dates
        }

def create_appointment(client_id, appointment_date, appointment_time, service_name):
    """Create a new appointment"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO appointments (client_id, appointment_date, appointment_time, service_name, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (client_id, appointment_date, appointment_time, service_name, get_current_date()))
        conn.commit()
        _cache.clear()
        return cursor.lastrowid

def get_today_appointments():
    """Get today's appointments"""
    with get_db() as conn:
        cursor = conn.cursor()
        today = get_current_date()
        cursor.execute('''
            SELECT a.*, c.client_name, c.client_phone 
            FROM appointments a
            JOIN clients c ON a.client_id = c.id
            WHERE a.appointment_date = ? AND a.status != 'cancelled'
            ORDER BY a.appointment_time
        ''', (today,))
        return cursor.fetchall()

def get_upcoming_appointments(days=7):
    """Get upcoming appointments"""
    with get_db() as conn:
        cursor = conn.cursor()
        today = get_current_date()
        future_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT a.*, c.client_name, c.client_phone 
            FROM appointments a
            JOIN clients c ON a.client_id = c.id
            WHERE a.appointment_date BETWEEN ? AND ? AND a.status != 'cancelled'
            ORDER BY a.appointment_date, a.appointment_time
        ''', (today, future_date))
        return cursor.fetchall()

def get_outstanding_balances():
    """Get clients with outstanding balances"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.id, c.client_name, c.client_phone, SUM(s.balance) as total_balance
            FROM service_history s
            JOIN clients c ON s.client_id = c.id
            WHERE s.balance > 0
            GROUP BY c.id
            ORDER BY total_balance DESC
            LIMIT 10
        ''')
        return cursor.fetchall()

def add_expense(category, amount, description, expense_date):
    """Add an expense record with soft delete support"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO expenses (category, amount, description, expense_date, created_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, NULL)
        ''', (category, amount, description, expense_date, get_current_date()))
        conn.commit()
        _cache.clear()

def soft_delete_expense(expense_id):
    """Soft delete an expense by setting deleted_at timestamp"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE expenses 
            SET deleted_at = ? 
            WHERE id = ?
        ''', (get_current_date(), expense_id))
        conn.commit()
        _cache.clear()

def get_expenses(limit=50):
    """Get expense records (non-deleted only)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM expenses 
            WHERE deleted_at IS NULL
            ORDER BY expense_date DESC 
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

def get_expenses_by_category():
    """Get expenses grouped by category (non-deleted only)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT category, SUM(amount) as total
            FROM expenses
            WHERE deleted_at IS NULL
            GROUP BY category
            ORDER BY total DESC
        ''')
        return cursor.fetchall()

def get_profit_summary():
    """Get profit summary by month"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                strftime('%Y-%m', service_date) as month,
                SUM(amount) as revenue,
                (SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE strftime('%Y-%m', expense_date) = month AND deleted_at IS NULL) as expenses,
                SUM(amount) - (SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE strftime('%Y-%m', expense_date) = month AND deleted_at IS NULL) as profit
            FROM service_history
            GROUP BY month
            ORDER BY month DESC
            LIMIT 12
        ''')
        return cursor.fetchall()

def add_client_note(client_id, note):
    """Add a note to client profile"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT notes FROM clients WHERE id = ?', (client_id,))
        current = cursor.fetchone()
        current_notes = current['notes'] if current and current['notes'] else ''
        
        timestamp = get_current_date()
        new_note = f"{current_notes}\n\n[{timestamp}] {note}" if current_notes else f"[{timestamp}] {note}"
        
        cursor.execute('UPDATE clients SET notes = ?, updated_at = ? WHERE id = ?', 
                      (new_note.strip(), get_current_date(), client_id))
        conn.commit()
        _cache.clear()

def add_allergy(client_id, allergy_type, description, severity='Medium'):
    """Add allergy/sensitivity record"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO client_health (client_id, allergy_type, allergy_description, severity, recorded_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (client_id, allergy_type, description, severity, get_current_date()))
        conn.commit()

def log_communication(client_id, comm_type, message, sent_by='System'):
    """Log communication with client"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO communications (client_id, comm_date, comm_type, message, sent_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (client_id, get_current_date(), comm_type, message, sent_by))
        conn.commit()
