from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for
from weasyprint import HTML
from datetime import datetime, timedelta
import io
import re
import os
import qrcode
from io import BytesIO
import base64
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from database import (
    init_db, get_or_create_client, save_service_record, search_clients,
    get_recent_clients, get_top_clients, get_client_by_id, get_client_stats,
    add_client_note, add_allergy, log_communication, get_dashboard_stats,
    get_today_appointments, get_outstanding_balances, add_expense, get_expenses,
    update_retention_status, get_at_risk_clients, get_upcoming_appointments,
    generate_invoice_number, get_db, get_client_visits, soft_delete_expense
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.permanent_session_lifetime = timedelta(hours=8)

# ============ SECURITY: Password Hashing & Rate Limiting ============
ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'JoyAdmin2026'))

# Rate limiting for login attempts
login_attempts = {}
MAX_ATTEMPTS = 5
LOCKOUT_TIME = 900  # 15 minutes in seconds

def is_rate_limited(ip):
    """Check if an IP is rate limited"""
    if ip in login_attempts:
        attempts, lockout_until = login_attempts[ip]
        if lockout_until and datetime.now() < lockout_until:
            return True
        if lockout_until and datetime.now() >= lockout_until:
            del login_attempts[ip]
    return False

def record_failed_attempt(ip):
    """Record a failed login attempt"""
    now = datetime.now()
    if ip in login_attempts:
        attempts, lockout_until = login_attempts[ip]
        attempts += 1
        if attempts >= MAX_ATTEMPTS:
            lockout_until = now + timedelta(seconds=LOCKOUT_TIME)
        login_attempts[ip] = (attempts, lockout_until)
    else:
        login_attempts[ip] = (1, None)

def clear_login_attempts(ip):
    """Clear successful login attempts"""
    if ip in login_attempts:
        del login_attempts[ip]

# ============ BUSINESS CONFIGURATION ============
BUSINESS = {
    'name': 'Joy Sisterlocks',
    'phone': '+254 713 700 421',
    'whatsapp': '254713700421',
    'location': 'Mezzanine Floor, Room 8, Highway Mall, Nairobi, Kenya',
    'instagram': '@joysisterlocks_kenya',
    'email': 'joysistalocks5@gmail.com'
}

# ============ HELPER FUNCTIONS ============
def format_money(amount):
    """Format money safely"""
    return f"KES {amount:,.0f}" if amount else "KES 0"

def calculate_vat_inclusive(total_inclusive):
    """Calculate subtotal and VAT from VAT-inclusive total"""
    vat_rate = 0.16
    subtotal = total_inclusive / (1 + vat_rate)
    vat_amount = total_inclusive - subtotal
    return round(subtotal, 2), round(vat_amount, 2)

def calculate_loyalty_stars(visits):
    """Calculate stars for loyalty display"""
    if not visits:
        visits = 0
    stars_count = (visits % 10) if (visits % 10) <= 5 else 5
    return "⭐" * stars_count

def calculate_visits_until_reward(visits):
    """Calculate visits until next reward"""
    if not visits:
        visits = 0
    return 5 - (visits % 5)

def get_reward_message(visits):
    """Get loyalty reward message"""
    visits = visits or 0
    remaining = 5 - (visits % 5)
    if remaining == 0:
        return "🎉 You've earned a FREE Wash & Style on your next visit! 🎉"
    elif remaining == 1:
        return "⭐ 1 more visit until a FREE Wash & Style!"
    else:
        return f"⭐ {remaining} more visits until a FREE Wash & Style!"

def generate_qr_code(url):
    """Generate QR code as base64 image"""
    try:
        qr = qrcode.QRCode(version=1, box_size=2, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#2d1b4e", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        print(f"QR code generation error: {e}")
        return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def validate_kenyan_phone(phone):
    phone_pattern = r'^(07|01|\+254|254)[0-9]{8,9}$'
    return bool(re.match(phone_pattern, phone))

def format_phone(phone):
    phone = re.sub(r'\D', '', phone)
    if phone.startswith('0'):
        phone = '254' + phone[1:]
    elif phone.startswith('+'):
        phone = phone[1:]
    return '+' + phone

# ============ SERVICE MENU ============
SERVICES = {
    "colour": {"name": "Colour", "price": 0},
    "retouch": {"name": "Retouch", "price": 0},
    "installation": {"name": "Installation", "price": 0},
}

# ============ AUTH ROUTES ============
@app.route('/login', methods=['GET', 'POST'])
def login():
    client_ip = request.remote_addr
    
    if request.method == 'POST':
        # Check rate limiting
        if is_rate_limited(client_ip):
            return render_template('login.html', error='Too many attempts. Please wait 15 minutes.')
        
        password = request.form.get('password')
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.permanent = True
            session['logged_in'] = True
            session['login_time'] = datetime.now().isoformat()
            clear_login_attempts(client_ip)
            return redirect(url_for('dashboard'))
        else:
            record_failed_attempt(client_ip)
            remaining = MAX_ATTEMPTS - (login_attempts.get(client_ip, (0, None))[0])
            return render_template('login.html', error=f'Invalid password. {remaining} attempts remaining.')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============ MAIN INVOICE ROUTE ============
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        client_phone = request.form.get("client_phone", "").strip()
        client_email = request.form.get("client_email", "").strip()
        
        # Handle multiple services with "Other" custom names
        service_names_raw = request.form.getlist("service_name[]")
        service_prices = request.form.getlist("service_price[]")
        
        service_names = []
        for i, name in enumerate(service_names_raw):
            if name == "Other":
                custom_name = request.form.get(f"other_service_name_{i+1}", "")
                if custom_name:
                    service_names.append(custom_name)
                else:
                    service_names.append(name)
            else:
                service_names.append(name)
        
        if not client_name:
            return "Client name is required", 400
        
        if not client_phone:
            return "Phone number is required", 400
        
        if not validate_kenyan_phone(client_phone):
            return "Invalid Kenyan phone number. Use format: 07XXXXXXXX or 01XXXXXXXX", 400
        
        if not service_names or not service_names[0]:
            return "Please select at least one service", 400
        
        # Calculate totals
        total_amount = 0
        services_list = []
        for i, name in enumerate(service_names):
            if name and i < len(service_prices):
                price = int(service_prices[i]) if service_prices[i] else 0
                total_amount += price
                services_list.append({"name": name, "price": price})
        
        # Calculate VAT inclusive
        subtotal, vat_amount = calculate_vat_inclusive(total_amount)
        total_with_vat = total_amount
        
        appointment_date = request.form.get("appointment_date", "")
        payment_method = request.form.get("payment_method", "Cash")
        amount_paid = request.form.get("amount_paid", 0)
        notes = request.form.get("notes", "")
        mpesa_code = request.form.get("mpesa_code", "")
        
        try:
            amount_paid_int = int(amount_paid) if amount_paid else 0
        except ValueError:
            amount_paid_int = 0
        
        balance = total_amount - amount_paid_int
        formatted_phone = format_phone(client_phone)
        invoice_number = generate_invoice_number()
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        client_data = {
            'client_name': client_name,
            'client_phone': formatted_phone,
            'client_email': client_email
        }
        client_id = get_or_create_client(client_data)
        client_visits = get_client_visits(client_id)
        
        invoice_data = {
            'invoice_number': invoice_number,
            'date': current_date,
            'service_name': ", ".join([s["name"] for s in services_list]),
            'service_details': "",
            'total': total_amount,
            'amount_paid': amount_paid_int,
            'balance': balance,
            'payment_method': payment_method,
            'stylist_name': 'Joy',
            'notes': notes,
            'mpesa_code': mpesa_code
        }
        save_service_record(client_id, invoice_data)
        
        log_communication(client_id, 'Invoice', f'Invoice {invoice_number} generated', 'Joy')
        
        loyalty_stars = calculate_loyalty_stars(client_visits + 1)
        reward_message = get_reward_message(client_visits + 1)
        
        whatsapp_url = f"https://wa.me/{BUSINESS['whatsapp']}"
        qr_code_url = generate_qr_code(whatsapp_url)
        
        html = render_template("invoice.html",
            invoice_number=invoice_number,
            date=current_date,
            client_name=client_name,
            client_phone=formatted_phone,
            service_name=", ".join([s["name"] for s in services_list]),
            service_details="",
            appointment_date=appointment_date,
            total=total_amount,
            amount_paid=amount_paid_int,
            balance=balance,
            payment_method=payment_method,
            notes=notes,
            stylist_name="Joy",
            mpesa_code=mpesa_code,
            services_list=services_list,
            subtotal=subtotal,
            vat_amount=vat_amount,
            total_with_vat=total_with_vat,
            loyalty_stars=loyalty_stars,
            reward_message=reward_message,
            qr_code_url=qr_code_url,
            business=BUSINESS,
            client_visits=client_visits + 1
        )
        
        try:
            pdf_file = io.BytesIO()
            HTML(string=html).write_pdf(pdf_file)
            pdf_file.seek(0)
        except Exception as e:
            return f"Error generating PDF: {str(e)}", 500
        
        return send_file(
            pdf_file,
            as_attachment=True,
            download_name=f"invoice_{invoice_number}.pdf",
            mimetype='application/pdf'
        )
    
    recent_clients = get_recent_clients(5)
    stats = get_client_stats()
    
    return render_template("form.html", services=SERVICES, recent_clients=recent_clients, stats=stats)

# ============ PAGE ROUTES ============
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")

@app.route("/expenses")
@login_required
def expenses_page():
    return render_template("expenses.html")

@app.route("/clients")
@login_required
def clients_page():
    return render_template("clients.html")

@app.route("/client/<int:client_id>")
@login_required
def client_profile(client_id):
    profile = get_client_by_id(client_id)
    if not profile:
        return "Client not found", 404
    return render_template("client_profile.html", profile=profile)

# ============ API ENDPOINTS FOR FRONTEND ============

@app.route("/api/stats")
@login_required
def api_stats():
    """Get client statistics - matches frontend expectations"""
    stats = get_client_stats()
    return jsonify({
        'total_clients': stats['total_clients'],
        'vip_count': stats['vip_count'],
        'regular_count': stats['regular_count'],
        'new_this_month': stats['new_this_month'],
        'gross_revenue': stats['gross_revenue'],
        'cash_collected': stats['cash_collected'],
        'outstanding': stats['outstanding'],
        'avg_visit': stats['avg_visit'],
        'at_risk': stats['at_risk'],
        'lost': stats['lost']
    })

@app.route("/api/recent")
@login_required
def api_recent():
    """Get recent clients - matches frontend expectations"""
    limit = request.args.get('limit', 20, type=int)
    results = get_recent_clients(limit)
    return jsonify([{
        'id': row['id'],
        'client_name': row['client_name'],
        'client_phone': row['client_phone'],
        'total_visits': row['total_visits'],
        'gross_spent': row['gross_spent'],
        'last_visit': row['last_visit'],
        'category': row['category'],
        'retention_status': row['retention_status'],
        'join_date': row['join_date']
    } for row in results])

@app.route("/api/top")
@login_required
def api_top():
    """Get top spending clients - matches frontend expectations"""
    limit = request.args.get('limit', 20, type=int)
    results = get_top_clients(limit)
    return jsonify([{
        'id': row['id'],
        'client_name': row['client_name'],
        'client_phone': row['client_phone'],
        'total_visits': row['total_visits'],
        'gross_spent': row['gross_spent'],
        'last_visit': row['last_visit'],
        'category': row['category'],
        'retention_status': row['retention_status']
    } for row in results])

@app.route("/api/search")
@login_required
def api_search():
    """Search clients - matches frontend expectations"""
    query = request.args.get("q", "")
    if len(query) < 2 or len(query) > 50:
        return jsonify([])
    
    results = search_clients(query)
    return jsonify([{
        'id': row['id'],
        'client_name': row['client_name'],
        'client_phone': row['client_phone'],
        'total_visits': row['total_visits'],
        'gross_spent': row['gross_spent'],
        'last_visit': row['last_visit'],
        'category': row['category'],
        'retention_status': row['retention_status']
    } for row in results])

@app.route("/api/at-risk-clients")
@login_required
def api_at_risk_clients():
    """Get at-risk clients - matches frontend expectations"""
    update_retention_status()
    results = get_at_risk_clients()
    return jsonify([{
        'id': row['id'],
        'client_name': row['client_name'],
        'client_phone': row['client_phone'],
        'last_visit': row['last_visit'],
        'retention_status': row['retention_status']
    } for row in results])

# ============ DASHBOARD API ENDPOINTS ============
@app.route("/api/dashboard-stats")
@login_required
def api_dashboard_stats():
    stats = get_dashboard_stats()
    client_stats = get_client_stats()
    return jsonify({
        'today_revenue': stats['today_revenue'],
        'today_appointments': stats['today_appointments'],
        'total_outstanding': stats['total_outstanding'],
        'gross_revenue': stats['gross_revenue'],
        'total_expenses': stats['total_expenses'],
        'profit': stats['profit'],
        'revenue_data': stats['revenue_data'],
        'revenue_dates': stats['revenue_dates'],
        'total_clients': client_stats['total_clients'],
        'vip_count': client_stats['vip_count'],
        'new_this_month': client_stats['new_this_month'],
        'avg_visit': client_stats['avg_visit']
    })

@app.route("/api/today-appointments")
@login_required
def api_today_appointments():
    appointments = get_today_appointments()
    return jsonify([dict(row) for row in appointments])

@app.route("/api/outstanding-balances")
@login_required
def api_outstanding_balances():
    balances = get_outstanding_balances()
    return jsonify([dict(row) for row in balances])

@app.route("/api/recent-expenses")
@login_required
def api_recent_expenses():
    expenses = get_expenses(limit=10)
    return jsonify([dict(row) for row in expenses])

# ============ EXPENSE API ENDPOINTS ============
@app.route("/api/expenses")
@login_required
def api_get_expenses():
    """Get expenses with pagination and filters"""
    page = request.args.get('page', 1, type=int)
    limit = min(request.args.get('limit', 50, type=int), 100)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    offset = (page - 1) * limit
    
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM expenses WHERE deleted_at IS NULL"
    params = []
    
    if start_date:
        query += " AND expense_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND expense_date <= ?"
        params.append(end_date)
    
    count_query = query.replace("SELECT *", "SELECT COUNT(*) as total")
    cursor.execute(count_query, params)
    total = cursor.fetchone()['total']
    
    query += " ORDER BY expense_date DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor.execute(query, params)
    expenses = cursor.fetchall()
    
    conn.close()
    
    return jsonify({
        'expenses': [dict(row) for row in expenses],
        'total': total,
        'page': page,
        'limit': limit,
        'total_pages': (total + limit - 1) // limit
    })

@app.route("/api/expense", methods=["POST"])
@login_required
def add_expense_record():
    data = request.get_json()
    amount = data.get('amount', 0)
    
    if amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400
    
    add_expense(
        data.get('category'),
        amount,
        data.get('description'),
        data.get('date', datetime.now().strftime('%Y-%m-%d'))
    )
    return jsonify({"success": True})

@app.route("/api/expense/<int:expense_id>", methods=["DELETE"])
@login_required
def api_delete_expense(expense_id):
    soft_delete_expense(expense_id)
    return jsonify({"success": True})

@app.route("/api/revenue-summary")
@login_required
def api_revenue_summary():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({"error": "Missing date range"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT SUM(amount_paid) as total_revenue 
        FROM service_history 
        WHERE service_date BETWEEN ? AND ?
    ''', (start_date, end_date))
    revenue = cursor.fetchone()['total_revenue'] or 0
    
    cursor.execute('''
        SELECT SUM(amount) as total_expenses 
        FROM expenses 
        WHERE expense_date BETWEEN ? AND ? AND deleted_at IS NULL
    ''', (start_date, end_date))
    expenses = cursor.fetchone()['total_expenses'] or 0
    
    conn.close()
    
    return jsonify({
        'revenue': revenue,
        'expenses': expenses
    })

@app.route("/api/expense-categories")
@login_required
def api_expense_categories():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses 
        WHERE deleted_at IS NULL
        GROUP BY category
        ORDER BY total DESC
    ''')
    categories = cursor.fetchall()
    conn.close()
    
    return jsonify([dict(row) for row in categories])

# ============ CLIENT NOTE & ALLERGY API ============
@app.route("/api/client/<int:client_id>/note", methods=["POST"])
@login_required
def add_note(client_id):
    data = request.get_json()
    note = data.get("note", "")
    add_client_note(client_id, note)
    log_communication(client_id, 'Note', f'Added note: {note[:100]}...', 'Joy')
    return jsonify({"success": True})

@app.route("/api/client/<int:client_id>/allergy", methods=["POST"])
@login_required
def add_allergy_record(client_id):
    data = request.get_json()
    add_allergy(client_id, data.get("type"), data.get("description"), data.get("severity", "Medium"))
    return jsonify({"success": True})

# ============ FORCE DATABASE INITIALIZATION ON STARTUP ============
with app.app_context():
    init_db()
    print("Database initialized successfully")

if __name__ == "__main__":
    app.run(debug=True)
