from flask import Flask, request, render_template, redirect, url_for, session, jsonify, make_response
import mysql.connector
import hashlib
import random
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import calendar
import json

app = Flask(__name__)
app.secret_key = 'pepsi'  # Required for session management

# MySQL Database Configuration
db_config = {
    'host': 'localhost',
    'user': 'root',  # Your MySQL username
    'password': 'Sparky@159',  # Your MySQL password
    'database': 'envision_db'  # Your database name
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

#############################
# Landing Page
#############################
@app.route('/')
def index():
    return render_template('index.html')

#############################
# Consumer Routes
#############################
# Consumer Login Page (GET)
@app.route('/login', methods=['GET'])
def consumer_login_page():
    return render_template('login.html')

# Consumer Login Authentication (POST)
@app.route('/login', methods=['POST'])
def consumer_login():
    username = request.form['username']
    password = request.form['password']
    hashed_password = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT id, first_name, last_name, email_id 
        FROM consumer_data 
        WHERE (email_id = %s OR id = %s) AND pwd = %s
    """
    cursor.execute(query, (username, username, hashed_password))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user:
        session['user_id'] = user['id']
        session['first_name'] = user['first_name']
        return redirect(url_for('dashboard'))
    else:
        return "Invalid credentials. Try again."

# Consumer Dashboard
@app.route('/dashboard')
def dashboard():
    if 'user_id' in session:
        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Transaction history query (unchanged)
        query = """
            SELECT 
                t.transaction_id, 
                t.date_time, 
                s.seller_name, 
                p.product_name, 
                t.quantity, 
                t.pcf, 
                t.amount
            FROM transaction_data t
            JOIN seller_data s ON t.seller_id = s.id
            JOIN product_data p ON t.product_id = p.product_id
            WHERE t.buyer_id = %s
            ORDER BY t.date_time DESC
        """
        cursor.execute(query, (user_id,))
        transactions = cursor.fetchall()

        #### 1. Data for "Today": Group by hour (0 to 23)
        cursor.execute(
            "SELECT HOUR(date_time) as hr, SUM(pcf) as total FROM transaction_data WHERE buyer_id = %s AND DATE(date_time) = CURDATE() GROUP BY HOUR(date_time) ORDER BY hr",
            (user_id,)
        )
        today_results = cursor.fetchall()
        today_dict = {row['hr']: float(row['total']) for row in today_results}
        today_labels = []
        today_data = []
        for h in range(24):
            if h == 0:
                label = "12 AM"
            elif h < 12:
                label = f"{h} AM"
            elif h == 12:
                label = "12 PM"
            else:
                label = f"{h-12} PM"
            today_labels.append(label)
            today_data.append(today_dict.get(h, 0))

        #### 2. Data for "Past 7 Days": Daily totals for today and past 6 days
        cursor.execute(
            "SELECT DATE(date_time) as dt, SUM(pcf) as total FROM transaction_data WHERE buyer_id = %s AND DATE(date_time) >= CURDATE() - INTERVAL 6 DAY GROUP BY DATE(date_time) ORDER BY dt",
            (user_id,)
        )
        past7_results = cursor.fetchall()
        past7_dict = {row['dt'].strftime("%m-%d"): float(row['total']) for row in past7_results}
        past7_labels = []
        past7_data = []
        today_date = datetime.today().date()
        for i in range(6, -1, -1):
            d = today_date - timedelta(days=i)
            label = d.strftime("%m-%d")
            past7_labels.append(label)
            past7_data.append(past7_dict.get(label, 0))

        #### 3. Data for "This Month": Daily totals for current month
        now = datetime.now()
        year = now.year
        month = now.month
        days_in_month = calendar.monthrange(year, month)[1]
        cursor.execute(
            "SELECT DAY(date_time) as day, SUM(pcf) as total FROM transaction_data WHERE buyer_id = %s AND YEAR(date_time)=%s AND MONTH(date_time)=%s GROUP BY DAY(date_time) ORDER BY day",
            (user_id, year, month)
        )
        this_month_results = cursor.fetchall()
        month_dict = {row['day']: float(row['total']) for row in this_month_results}
        this_month_labels = [str(d) for d in range(1, days_in_month+1)]
        this_month_data = [month_dict.get(d, 0) for d in range(1, days_in_month+1)]

        #### 4. Data for "This Year": Monthly totals for current year
        cursor.execute(
            "SELECT MONTH(date_time) as mon, SUM(pcf) as total FROM transaction_data WHERE buyer_id = %s AND YEAR(date_time)=%s GROUP BY MONTH(date_time) ORDER BY mon",
            (user_id, year)
        )
        this_year_results = cursor.fetchall()
        year_dict = {row['mon']: float(row['total']) for row in this_year_results}
        this_year_labels = [calendar.month_abbr[m] for m in range(1, 13)]
        this_year_data = [year_dict.get(m, 0) for m in range(1, 13)]

        #### 5. Data for "All Time": Yearly totals (from the year of the first transaction)
        cursor.execute(
            "SELECT YEAR(date_time) as yr, SUM(pcf) as total FROM transaction_data WHERE buyer_id = %s GROUP BY YEAR(date_time) ORDER BY yr",
            (user_id,)
        )
        all_time_results = cursor.fetchall()
        all_time_labels = [str(row['yr']) for row in all_time_results]
        all_time_data = [float(row['total']) for row in all_time_results]

        #### Sector-wise emissions (unchanged)
        cursor.execute("""
            SELECT p.sector AS sector, SUM(t.pcf) AS total 
            FROM transaction_data t 
            JOIN product_data p ON t.product_id = p.product_id 
            WHERE t.buyer_id = %s 
            GROUP BY p.sector
        """, (user_id,))
        sector_results = cursor.fetchall()
        sector_labels = [row['sector'] for row in sector_results]
        sector_values = [float(row['total']) for row in sector_results]

        #### AEPD calculation (unchanged)
        cursor.execute("SELECT total_carbon_debt, amount_spent FROM consumer_data WHERE id = %s", (user_id,))
        consumer_record = cursor.fetchone()
        if consumer_record:
            total_carbon_debt = float(consumer_record['total_carbon_debt'])
            total_amount_spent = float(consumer_record['amount_spent'])
            aepd = total_carbon_debt / total_amount_spent if total_amount_spent > 0 else 0
        else:
            aepd = 0
        max_aepd = 1.0

        # --- GREEN SUGGESTIONS ---
        # Take up to 3 most recent purchases
        recent = transactions[:3]
        suggests = []
        for t in recent:
                # pick a keyword (first word >4 chars, or full name)
                words = [w for w in t['product_name'].split() if len(w) > 4]
                kw = words[0] if words else t['product_name']
                like = f"%{kw}%"
                # find similar products with LOWER PCF
                cursor.execute("""
                    SELECT product_id, product_name, company_name, pcf
                    FROM product_data
                    WHERE product_name LIKE %s
                      AND pcf < %s
                    LIMIT 3
                """, (like, t['pcf']))
                suggests.extend(cursor.fetchall())

            # dedupe by product_id
        seen = set()
        green_suggestions = []
        for p in suggests:
                if p['product_id'] not in seen:
                    seen.add(p['product_id'])
                    green_suggestions.append(p)
                if len(green_suggestions) >= 4:
                    break
    
        cursor.close()
        conn.close()

        rendered = render_template(
            'cons_dash.html',
            name=session['first_name'],
            transactions=transactions or [],
            today_labels=today_labels or [],
            today_data=today_data or [],
            past7_labels=past7_labels or [],
            past7_data=past7_data or [],
            this_month_labels=this_month_labels or [],
            this_month_data=this_month_data or [],
            this_year_labels=this_year_labels or [],
            this_year_data=this_year_data or [],
            all_time_labels=all_time_labels or [],
            all_time_data=all_time_data or [],
            sector_labels=sector_labels or [],
            sector_values=sector_values or [],
            aepd=aepd,
            max_aepd=max_aepd,
            green_suggestions=green_suggestions
        )
        response = make_response(rendered)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    else:
        return redirect(url_for('index'))

# Consumer Logout (redirects to homepage with cache prevention headers)
@app.route('/logout')
def logout():
    session.clear()
    response = redirect(url_for('index'))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Consumer Product Search (unchanged)
@app.route('/search_products', methods=['GET'])
def search_products():
    query = request.args.get('q', '')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = """
        SELECT product_id, product_name, company_name, country, sector,
               upstream_emissions, operational_emissions, downstream_emissions, pcf
        FROM product_data
        WHERE product_name LIKE %s
        LIMIT 10
    """
    like_param = f"%{query}%"
    cursor.execute(sql, (like_param,))
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"products": products}

#############################
# Seller Routes (unchanged)
#############################
@app.route('/seller_login', methods=['GET'])
def seller_login_page():
    return render_template('seller_login.html')

@app.route('/seller_login', methods=['POST'])
def seller_login():
    username = request.form['username']
    password = request.form['password']
    hashed_password = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT id, seller_name, email_id 
        FROM seller_data 
        WHERE (email_id = %s OR id = %s) AND pwd = %s
    """
    cursor.execute(query, (username, username, hashed_password))
    seller = cursor.fetchone()
    cursor.close()
    conn.close()

    if seller:
        session['seller_id'] = seller['id']
        session['seller_name'] = seller['seller_name']
        return redirect(url_for('seller_dashboard'))
    else:
        return "Invalid seller credentials."

@app.route('/seller_dashboard')
def seller_dashboard():
    if 'seller_id' not in session:
        return redirect(url_for('seller_login_page'))
    return render_template('seller_dash.html', seller_name=session['seller_name'])

@app.route('/seller_search_products', methods=['GET'])
def seller_search_products():
    query = request.args.get('q', '')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sql = """
        SELECT product_id, product_name, company_name, country, sector,
               mrp, upstream_emissions, operational_emissions, downstream_emissions, pcf
        FROM product_data
        WHERE product_name LIKE %s
        LIMIT 10
    """
    like_param = f"%{query}%"
    cursor.execute(sql, (like_param,))
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({"products": products})

@app.route('/send_otp', methods=['POST'])
def send_otp():
    buyer_email = request.form.get('buyer_email')
    if not buyer_email:
        return jsonify({"error": "Buyer email required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM consumer_data WHERE email_id = %s", (buyer_email,))
    buyer_row = cursor.fetchone()
    if not buyer_row:
        cursor.close()
        conn.close()
        return jsonify({"error": "Buyer not found in database"}), 400
    
    buyer_id = buyer_row['id']
    cursor.close()
    conn.close()

    session['buyer_id'] = buyer_id
    session['buyer_email'] = buyer_email

    otp = str(random.randint(100000, 999999))
    session['otp'] = otp

    smtp_server = 'smtp.gmail.com'
    smtp_port = 587
    sender_email = 'envision.otp@gmail.com'
    sender_password = 'nbzb gina qjtn dszg'

    subject = 'Your Transaction OTP'
    body = f'Your OTP for the transaction is: {otp}'

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = buyer_email

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, [buyer_email], msg.as_string())
        server.quit()
        return jsonify({"message": "OTP sent successfully"})
    except Exception as e:
        print(e)
        return jsonify({"error": "Failed to send OTP"}), 500

@app.route('/submit_transaction', methods=['POST'])
def submit_transaction():
    if 'seller_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    submitted_otp = request.form.get('otp')
    if not submitted_otp or submitted_otp != session.get('otp'):
        return jsonify({"error": "Invalid OTP"}), 400

    buyer_id = session.get('buyer_id')
    if not buyer_id:
        return jsonify({"error": "Buyer not found"}), 400

    cart_json = request.form.get('cart')
    if not cart_json:
        return jsonify({"error": "Cart is empty"}), 400

    try:
        cart = json.loads(cart_json)
    except Exception:
        return jsonify({"error": "Invalid cart data"}), 400

    seller_id = session['seller_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT transaction_id FROM transaction_data ORDER BY transaction_id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        last_tx_id = row[0]
        numeric_part = int(last_tx_id.split('-')[1])
        next_num = numeric_part + 1
        new_tx_id = f"T-{next_num:04d}"
    else:
        new_tx_id = "T-0001"

    date_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total_amount = 0
    total_pcf = 0

    for item in cart:
        product_id = item.get('product_id')
        quantity = item.get('quantity')
        computed_amount = item.get('mrp') * quantity
        computed_pcf = item.get('pcf') * quantity
        total_amount += computed_amount
        total_pcf += computed_pcf

        insert_query = """
            INSERT INTO transaction_data 
            (transaction_id, date_time, seller_id, buyer_id, product_id, quantity, pcf, amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (
            new_tx_id,
            date_time,
            seller_id,
            buyer_id,
            product_id,
            quantity,
            computed_pcf,
            computed_amount
        ))
    
    update_consumer_query = """
        UPDATE consumer_data 
        SET amount_spent = amount_spent + %s, total_carbon_debt = total_carbon_debt + %s
        WHERE id = %s
    """
    cursor.execute(update_consumer_query, (total_amount, total_pcf, buyer_id))

    update_seller_query = """
        UPDATE seller_data 
        SET revenue = revenue + %s, carbon_debt_sold = carbon_debt_sold + %s
        WHERE id = %s
    """
    cursor.execute(update_seller_query, (total_amount, total_pcf, seller_id))

    conn.commit()
    cursor.close()
    conn.close()

    session.pop('otp', None)
    session.pop('buyer_email', None)
    session.pop('buyer_id', None)

    return jsonify({"message": "Transaction submitted successfully"})

@app.route('/estimate_emissions', methods=['POST'])
def estimate_emissions():
    category = request.form.get('category')
    price_input = request.form.get('price')
    if not category or not price_input:
        return jsonify({"error": "Category and Price are required"}), 400
    try:
        price_input = float(price_input)
    except ValueError:
        return jsonify({"error": "Invalid price value"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    # Sum total PCF and total MRP for the given sector/category.
    query = "SELECT SUM(pcf) AS total_pcf, SUM(mrp) AS total_price FROM product_data WHERE sector = %s"
    cursor.execute(query, (category,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if result is None or result['total_price'] is None or result['total_price'] == 0:
        return jsonify({"error": "No data available for the selected category"}), 400

    # Calculate average emissions per dollar for that category
    avg_emission_per_dollar = result['total_pcf'] / result['total_price']
    estimated_pcf = avg_emission_per_dollar * price_input
    return jsonify({"estimated_pcf": estimated_pcf})

@app.route('/signup_consumer', methods=['GET', 'POST'])
def signup_consumer():
    if request.method == 'GET':
        # Render the form without OTP field
        return render_template('cons_signup.html', otp_sent=False, success=False)
    else:
        # Check if OTP field is present in the submitted form
        if 'otp' not in request.form:
            # First submission: store data and send OTP
            signup_data = {
                'first_name': request.form.get('first_name'),
                'last_name': request.form.get('last_name'),
                'sex': request.form.get('sex'),
                'dob': request.form.get('dob'),
                'email_id': request.form.get('email_id'),
                'password': request.form.get('password'),
                'contact_no': request.form.get('contact_no'),
                'city': request.form.get('city'),
                'nationality': request.form.get('nationality')
            }
            session['signup_data'] = signup_data

            # Generate OTP (6-digit)
            signup_otp = str(random.randint(100000, 999999))
            session['signup_otp'] = signup_otp

            # Send OTP via email
            sender_email = 'envision.otp@gmail.com'
            sender_password = 'nbzb gina qjtn dszg'  # Use an app password if necessary
            subject = 'Your OTP for Consumer Sign Up'
            body = f'Your OTP for sign up is: {signup_otp}'
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = sender_email
            msg['To'] = signup_data['email_id']
            
            try:
                smtp_server = 'smtp.gmail.com'
                smtp_port = 587
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, [signup_data['email_id']], msg.as_string())
                server.quit()
            except Exception as e:
                print(e)
                return "Failed to send OTP. Please try again later.", 500

            # Re-render the same sign-up form with OTP field visible
            return render_template('cons_signup.html', otp_sent=True, success=False)
        else:
            # Second submission: OTP verification and DB insertion
            submitted_otp = request.form.get('otp')
            if submitted_otp != session.get('signup_otp'):
                error_message = "OTP incorrect. Please try again."
                return render_template('cons_signup.html', otp_sent=True, error=error_message, success=False)
            
            # OTP verified; proceed to insert data into DB
            data = session.get('signup_data')
            if not data:
                return "Session expired. Please try signing up again.", 400

            hashed_password = hashlib.sha256(data['password'].encode()).hexdigest()
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Generate new consumer ID
            cursor.execute("SELECT id FROM consumer_data ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                last_id = row[0]  # e.g., "C-0001"
                numeric_part = int(last_id.split('-')[1])
                new_numeric = numeric_part + 1
                new_id = f"C-{new_numeric:04d}"
            else:
                new_id = "C-0001"

            # Set total_carbon_debt and amount_spent to zero, and set account_creation_date to current datetime
            account_creation_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            total_carbon_debt = 0
            amount_spent = 0

            insert_query = """
                INSERT INTO consumer_data 
                (id, first_name, last_name, sex, dob, email_id, pwd, contact_no, city, nationality, total_carbon_debt, amount_spent, account_creation_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (
                new_id,
                data['first_name'],
                data['last_name'],
                data['sex'],
                data['dob'],
                data['email_id'],
                hashed_password,
                data['contact_no'],
                data['city'],
                data['nationality'],
                total_carbon_debt,
                amount_spent,
                account_creation_date
            ))
            conn.commit()
            cursor.close()
            conn.close()

            # Clear temporary sign-up data
            session.pop('signup_data', None)
            session.pop('signup_otp', None)

            # Render a success message on the same page
            return render_template('cons_signup.html', otp_sent=False, success=True)




if __name__ == '__main__':
    app.run(debug=True)
