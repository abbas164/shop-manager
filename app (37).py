from flask import Flask, render_template, request, redirect, flash, url_for
import psycopg2
from psycopg2 import extras  # برای DictCursor
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
import jdatetime
import requests
from urllib.parse import quote

app = Flask(__name__)
app.secret_key = 's3cr3t_k3y_f0r_fl4sk'

# تنظیمات آپلود فایل
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# اطمینان از وجود پوشه آپلود
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# بررسی فرمت مجاز فایل
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# اتصال به دیتابیس
def get_db_connection():
    return psycopg2.connect(
        host='dpg-d24kfnre5dus73dcpva0-a',  # از External کپی کن
        database='shop_u2sf',              # از External کپی کن
        user='shop_u2sf_user',             # از External کپی کن
        password='xnTOqMelH98OzbHfTbS9Zf9KHTpA4LLS',  # از External کپی کن
        port='5432'
    )

# تابع ساخت جدول‌ها (اگه وجود نداشته باشن)
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                phone VARCHAR(20) DEFAULT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
                amount DECIMAL(10,2) DEFAULT NULL,
                note TEXT,
                date TIMESTAMP DEFAULT NULL,
                photo VARCHAR(255) DEFAULT NULL
            )
        """)
        conn.commit()
        print("Tables created successfully")
    except psycopg2.Error as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        conn.close()

# فراخوانی تابع ساخت جدول موقع اجرا
create_tables()

# تابع گرفتن توکن امنیتی از sms.ir
def get_sms_ir_token():
    api_key = "Q6xLf9lTTmY4TSi2WNvWLmuTs0fwcyaTOcWbWds2MqRcME3a"
    secret_key = "your_secret_key"
    url = "https://restfulsms.com/api/Token"
    headers = {"Content-Type": "application/json"}
    payload = {"UserApiKey": api_key, "SecretKey": secret_key}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"Token Response Status: {response.status_code}, Text: {response.text}")
        if response.status_code == 201:
            response_data = response.json()
            if response_data.get("IsSuccessful") and response_data.get("TokenKey"):
                return True, response_data["TokenKey"]
            else:
                return False, f"خطا در گرفتن توکن: {response_data.get('Message', response.text)}"
        else:
            return False, f"خطا در گرفتن توکن: Status {response.status_code}, {response.text}"
    except requests.RequestException as e:
        print(f"Network error in get_token: {str(e)}")
        return False, f"خطای شبکه در گرفتن توکن: {str(e)}"

# تابع ارسال پیامک با API sms.ir
def send_sms(customer_phone, message):
    sender_number = "30007487127646"
    url = "https://restfulsms.com/api/MessageSend"
    success, token_result = get_sms_ir_token()
    if not success:
        return False, token_result
    headers = {"x-sms-ir-secure-token": token_result, "Accept": "application/json"}
    cleaned_phone = customer_phone.replace('+', '').replace(' ', '')
    if cleaned_phone.startswith('0'):
        cleaned_phone = '98' + cleaned_phone[1:]
    if not cleaned_phone.isdigit() or len(cleaned_phone) < 10:
        return False, "شماره تلفن نامعتبر است."
    payload = {"MobileNumbers": [cleaned_phone], "Messages": [message], "SenderNumber": sender_number}
    try:
        print(f"Sending SMS to: {cleaned_phone}, Message: {message}")
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"Response Status: {response.status_code}, Text: {response.text}")
        response_data = response.json()
        if response.status_code == 200 and response_data.get("IsSuccessful"):
            return True, "پیامک با موفقیت ارسال شد."
        else:
            return False, f"خطا در ارسال پیامک: {response_data.get('Message', response.text)}"
    except requests.RequestException as e:
        print(f"Network error: {str(e)}")
        return False, f"خطای شبکه: {str(e)}"

# روت ارسال پیامک
@app.route('/send_sms/<int:customer_id>', methods=['POST'])
def send_sms_route(customer_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("""
        SELECT c.name, c.phone, t.last_transaction_date, t.last_transaction, t.balance 
        FROM customers c 
        LEFT JOIN (
            SELECT customer_id, 
                   MAX(date) as last_transaction_date, 
                   amount as last_transaction, 
                   SUM(amount) as balance 
            FROM transactions 
            GROUP BY customer_id
        ) t ON c.id = t.customer_id 
        WHERE c.id = %s
    """, (customer_id,))
    customer = cursor.fetchone()
    conn.close()
    if customer and customer['phone'] and customer['last_transaction_date']:
        last_transaction_date = jdatetime.datetime.fromgregorian(
            datetime=customer['last_transaction_date']
        ).strftime("%Y/%m/%d")
        message = (
            f"جناب/خانم {customer['name']} گرامی،\n"
            f"فاکتور خرید شما مورخ {last_transaction_date} به مبلغ {abs(customer['last_transaction']):,} تومان ثبت شده است.\n"
            f"مانده حساب شما: {abs(customer['balance']):,} تومان\n"
            f"با تشکر - فروشگاه لوازم ساختمانی آزادی 🏬\n"
            f"شماره کارت: 6063-7311-1219-2951 💳"
        )
        success, msg = send_sms(customer['phone'], message)
        flash(msg, 'success' if success else 'error')
    else:
        flash('اطلاعات مشتری یا تراکنش ناقص است.', 'error')
    return redirect(url_for('index'))

# روت ارسال پیام واتس‌اپ
@app.route('/send_whatsapp/<int:customer_id>', methods=['GET'])
def send_whatsapp(customer_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("""
        SELECT c.name, c.phone, t.last_transaction_date, t.last_transaction, t.balance 
        FROM customers c 
        LEFT JOIN (
            SELECT customer_id, 
                   MAX(date) as last_transaction_date, 
                   amount as last_transaction, 
                   SUM(amount) as balance 
            FROM transactions 
            GROUP BY customer_id
        ) t ON c.id = t.customer_id 
        WHERE c.id = %s
    """, (customer_id,))
    customer = cursor.fetchone()
    conn.close()
    if customer and customer['phone'] and customer['last_transaction_date']:
        phone = customer['phone'].replace('+', '').replace(' ', '')
        if not phone.isdigit() or len(phone) < 10:
            flash('شماره تلفن نامعتبر است.', 'error')
            return redirect(url_for('index'))
        last_transaction_date = jdatetime.datetime.fromgregorian(
            datetime=customer['last_transaction_date']
        ).strftime("%Y/%m/%d")
        message = (
            f"سلام {customer['name']} عزیز،\n"
            f"فاکتور خرید شما در تاریخ {last_transaction_date}: {abs(customer['last_transaction']):,} تومان\n"
            f"مانده حساب: {abs(customer['balance']):,} تومان\n"
            f"با تشکر از خرید شما فروشگاه لوازم ساختمانی آزادی 🏬\n"
            f"شماره کارت: 6063-7311-1219-2951 💳"
        )
        encoded_message = quote(message)
        whatsapp_url = f"https://api.whatsapp.com/send/?phone={phone}&text={encoded_message}"
        return redirect(whatsapp_url)
    else:
        flash('اطلاعات مشتری ناقص است.', 'error')
    return redirect(url_for('index'))

# روت نمایش سوابق مشتری
@app.route('/customer/<int:customer_id>')
def customer_details(customer_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("SELECT id, name, phone FROM customers WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()
    if not customer:
        conn.close()
        flash('مشتری یافت نشد.', 'error')
        return redirect(url_for('index'))

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS balance
        FROM transactions
        WHERE customer_id = %s
    """, (customer_id,))
    result = cursor.fetchone()
    if result and isinstance(result, dict):
        customer_dict = dict(customer)  # تبدیل DictRow به دیکشنری
        customer_dict['balance'] = result.get('balance', 0)
    else:
        customer_dict = dict(customer)
        customer_dict['balance'] = 0
    customer_dict['balance_status'] = 'بدهکار' if customer_dict['balance'] > 0 else 'طلبکار' if customer_dict['balance'] < 0 else 'تسویه'

    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS total_credit,
            COALESCE(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 0) AS total_debit
        FROM transactions
        WHERE customer_id = %s
    """, (customer_id,))
    totals = cursor.fetchone()
    if totals and isinstance(totals, dict):
        customer_dict['total_credit'] = totals.get('total_credit', 0)
        customer_dict['total_debit'] = totals.get('total_debit', 0)
    else:
        customer_dict['total_credit'] = 0
        customer_dict['total_debit'] = 0

    cursor.execute("""
        SELECT id, amount, note, date, photo,
               CASE WHEN amount > 0 THEN 'خرید' ELSE 'پرداخت' END AS transaction_type
        FROM transactions
        WHERE customer_id = %s
        ORDER BY date DESC
    """, (customer_id,))
    transactions = cursor.fetchall()
    transactions_list = [dict(t) for t in transactions]  # تبدیل همه به دیکشنری
    for t in transactions_list:
        t['date_shamsi'] = jdatetime.datetime.fromgregorian(datetime=t['date']).strftime("%Y/%m/%d %H:%M")

    conn.close()
    return render_template('customer_details.html', customer=customer_dict, transactions=transactions_list)

# صفحه اصلی: لیست مشتریان و تراکنش‌ها با قابلیت جستجو
@app.route('/', methods=['GET', 'POST'])
def index():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    search_query = request.form.get('search', '') if request.method == 'POST' else ''
    query = """
        SELECT id, name, phone FROM customers
        WHERE name LIKE %s OR phone LIKE %s
        ORDER BY name
    """
    cursor.execute(query, (f'%{search_query}%', f'%{search_query}%'))
    customers = cursor.fetchall()

    customer_dicts = []
    for c in customers:
        c_dict = dict(c)
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) AS balance
            FROM transactions
            WHERE customer_id = %s
        """, (c_dict['id'],))
        result = cursor.fetchone()
        c_dict['balance'] = result['balance'] if result and 'balance' in result else 0
        c_dict['balance_status'] = 'بدهکار' if c_dict['balance'] > 0 else 'طلبکار' if c_dict['balance'] < 0 else 'تسویه'
        cursor.execute("""
            SELECT amount, date
            FROM transactions
            WHERE customer_id = %s
            ORDER BY date DESC
            LIMIT 1
        """, (c_dict['id'],))
        last_transaction = cursor.fetchone()
        if last_transaction and 'amount' in last_transaction:
            c_dict['last_transaction'] = last_transaction['amount']
            c_dict['last_transaction_date'] = jdatetime.datetime.fromgregorian(
                datetime=last_transaction.get('date', datetime.now())
            ).strftime("%Y/%m/%d")
            c_dict['last_transaction_type'] = 'خرید (بدهی)' if last_transaction['amount'] > 0 else 'پرداخت'
        else:
            c_dict['last_transaction'] = 0
            c_dict['last_transaction_date'] = ''
            c_dict['last_transaction_type'] = ''
        customer_dicts.append(c_dict)

    cursor.execute("""
        SELECT 
            t.id, t.amount, t.note, t.date, t.photo,
            c.name, c.phone, c.id AS customer_id
        FROM transactions t
        JOIN customers c ON t.customer_id = c.id
        ORDER BY t.date DESC
    """)
    transactions = cursor.fetchall()
    transaction_dicts = []
    for t in transactions:
        t_dict = dict(t)
        t_dict['balance'] = next((c['balance'] for c in customer_dicts if c['id'] == t_dict['customer_id']), 0)
        transaction_dicts.append(t_dict)

    conn.close()
    return render_template('index.html', customers=customer_dicts, transactions=transaction_dicts, search_query=search_query)

# گزارش‌گیری جامع
@app.route('/reports')
def reports():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    cursor.execute("""
        SELECT COALESCE(SUM(balance), 0) AS total_debt
        FROM (
            SELECT SUM(amount) AS balance
            FROM transactions
            GROUP BY customer_id
            HAVING SUM(amount) > 0
        ) AS balances
    """)
    result = cursor.fetchone()
    total_debt = result['total_debt'] if result and 'total_debt' in result else 0

    cursor.execute("""
        SELECT COUNT(*) AS debtor_count
        FROM (
            SELECT customer_id
            FROM transactions
            GROUP BY customer_id
            HAVING SUM(amount) > 0
        ) AS debtors
    """)
    result = cursor.fetchone()
    debtor_count = result['debtor_count'] if result and 'debtor_count' in result else 0

    cursor.execute("""
        SELECT c.id, c.name, c.phone, COALESCE(SUM(t.amount), 0) AS balance
        FROM customers c
        LEFT JOIN transactions t ON c.id = t.customer_id
        GROUP BY c.id, c.name, c.phone
        ORDER BY balance DESC
    """)
    customer_balances = cursor.fetchall()
    customer_balances_list = [dict(c) for c in customer_balances]  # تبدیل به دیکشنری
    for customer in customer_balances_list:
        customer['balance_display'] = abs(customer['balance'])
        customer['balance_status'] = 'بدهکار' if customer['balance'] > 0 else 'طلبکار' if customer['balance'] < 0 else 'تسویه'

    cursor.execute("""
        SELECT c.id, c.name, c.phone, COALESCE(SUM(t.amount), 0) AS balance
        FROM customers c
        LEFT JOIN transactions t ON c.id = t.customer_id
        GROUP BY c.id, c.name, c.phone
        HAVING SUM(t.amount) > 0
        ORDER BY SUM(t.amount) DESC
        LIMIT 5
    """)
    top_debtors = cursor.fetchall()
    top_debtors_list = [dict(t) for t in top_debtors]  # تبدیل به دیکشنری

    thirty_days_ago = datetime.now() - timedelta(days=30)
    cursor.execute("""
        SELECT c.id, c.name, c.phone, t.amount, t.date
        FROM customers c
        JOIN transactions t ON c.id = t.customer_id
        WHERE t.amount > 0 AND t.date < %s
        ORDER BY t.date
    """, (thirty_days_ago,))
    overdue_customers = cursor.fetchall()
    overdue_customers_list = [dict(o) for o in overdue_customers]  # تبدیل به دیکشنری
    for customer in overdue_customers_list:
        customer['date_shamsi'] = jdatetime.datetime.fromgregorian(
            datetime=customer['date']
        ).strftime("%Y/%m/%d")

    conn.close()
    return render_template('reports.html', 
                         total_debt=total_debt,
                         top_debtors=top_debtors_list,
                         overdue_customers=overdue_customers_list,
                         debtor_count=debtor_count,
                         customer_balances=customer_balances_list)

# افزودن تراکنش
@app.route('/add_transaction', methods=['GET', 'POST'])
def add_transaction():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    if request.method == 'POST':
        customer_id = request.form['customer_id']
        amount = float(request.form['amount'])
        transaction_type = request.form['transaction_type']
        note = request.form['note']
        date = datetime.now()
        photo_filename = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_filename = filename
        final_amount = amount if transaction_type == 'credit' else -amount
        cursor.execute("""
            INSERT INTO transactions (customer_id, amount, note, date, photo)
            VALUES (%s, %s, %s, %s, %s)
        """, (customer_id, final_amount, note, date, photo_filename))
        conn.commit()
        conn.close()
        flash('تراکنش با موفقیت ثبت شد.', 'success')
        return redirect('/')
    cursor.execute("SELECT id, name, phone FROM customers ORDER BY name")
    customers = cursor.fetchall()
    conn.close()
    return render_template('add_transaction.html', customers=customers)

# ویرایش تراکنش
@app.route('/edit_transaction/<int:id>', methods=['GET', 'POST'])
def edit_transaction(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    if request.method == 'POST':
        customer_id = request.form['customer_id']
        amount = float(request.form['amount'])
        transaction_type = request.form['transaction_type']
        note = request.form['note']
        photo_filename = request.form.get('existing_photo')
        if 'photo' in request.files:
            file = request.files['photo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_filename = filename
        final_amount = amount if transaction_type == 'credit' else -amount
        cursor.execute("""
            UPDATE transactions
            SET customer_id = %s, amount = %s, note = %s, photo = %s
            WHERE id = %s
        """, (customer_id, final_amount, note, photo_filename, id))
        conn.commit()
        conn.close()
        flash('تراکنش با موفقیت ویرایش شد.', 'success')
        return redirect('/')
    cursor.execute("SELECT * FROM transactions WHERE id = %s", (id,))
    transaction = cursor.fetchone()
    cursor.execute("SELECT id, name FROM customers ORDER BY name")
    customers = cursor.fetchall()
    conn.close()
    return render_template('edit_transaction.html', transaction=transaction, customers=customers)

# حذف تراکنش
@app.route('/delete_transaction/<int:id>', methods=['POST'])
def delete_transaction(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT photo FROM transactions WHERE id = %s", (id,))
    photo = cursor.fetchone()[0]
    if photo:
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo)
        if os.path.exists(photo_path):
            os.remove(photo_path)
    cursor.execute("DELETE FROM transactions WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    flash('تراکنش با موفقیت حذف شد.', 'success')
    return redirect('/')

# افزودن مشتری
@app.route('/add_customer', methods=['GET', 'POST'])
def add_customer():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        if not name or not phone:
            flash('نام و شماره تلفن الزامی است.', 'error')
            return render_template('add_customer.html')
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO customers (name, phone) VALUES (%s, %s)", (name, phone))
            conn.commit()
            conn.close()
            flash('مشتری با موفقیت اضافه شد.', 'success')
            return redirect('/')
        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f'خطا در افزودن مشتری: {str(e)}', 'error')
            return render_template('add_customer.html')
    return render_template('add_customer.html')

# ویرایش مشتری
@app.route('/edit_customer/<int:id>', methods=['GET', 'POST'])
def edit_customer(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=extras.DictCursor)
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        cursor.execute("""
            UPDATE customers
            SET name = %s, phone = %s
            WHERE id = %s
        """, (name, phone, id))
        conn.commit()
        conn.close()
        flash('مشتری با موفقیت ویرایش شد.', 'success')
        return redirect('/')
    cursor.execute("SELECT * FROM customers WHERE id = %s", (id,))
    customer = cursor.fetchone()
    if customer:
        customer = dict(customer)  # تبدیل به دیکشنری
    else:
        conn.close()
        flash('مشتری یافت نشد.', 'error')
        return redirect('/')
    conn.close()
    return render_template('edit_customer.html', customer=customer)

# حذف مشتری
@app.route('/delete_customer/<int:id>', methods=['POST'])
def delete_customer(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS count FROM transactions WHERE customer_id = %s", (id,))
    count = cursor.fetchone()[0]
    if count > 0:
        conn.close()
        flash('نمی‌توانید مشتری را حذف کنید زیرا تراکنش‌هایی مرتبط با او وجود دارد.', 'error')
        return redirect('/')
    cursor.execute("DELETE FROM customers WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    flash('مشتری با موفقیت حذف شد.', 'success')
    return redirect('/')

# اجرای برنامه
if __name__ == '__main__':
    app.run(debug=True, port=10000)