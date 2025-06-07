from flask import Flask, render_template, request, redirect, url_for, flash
import MySQLdb
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'secret'

# MySQL connection config
app.config['MYSQL_HOST'] = '172.25.86.213'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'yourpassword'
app.config['MYSQL_DB'] = 'ecommerce_db'

mysql = MySQLdb.connect(
    host=app.config['MYSQL_HOST'],
    user=app.config['MYSQL_USER'],
    password=app.config['MYSQL_PASSWORD'],
    db=app.config['MYSQL_DB']
)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/shop', methods=['POST'])
def shop_redirect():
    cust_id = request.form.get('cust_id')
    return redirect(url_for('shop', cust_id=cust_id))

@app.route('/shop/<int:cust_id>')
def shop(cust_id):
    cursor = mysql.cursor()
    cursor.execute("SELECT * FROM Customer WHERE cust_id = %s", (cust_id,))
    customer = cursor.fetchone()
    if not customer:
        flash("Customer not found!", "danger")
        return redirect(url_for('index'))

    cursor.execute("SELECT * FROM Product WHERE stock > 0")
    products = cursor.fetchall()
    return render_template('shop.html', products=products, cust_id=cust_id)

@app.route('/add_to_cart/<int:cust_id>/<int:prod_id>')
def add_to_cart(cust_id, prod_id):
    cursor = mysql.cursor()

    # Check if the product already exists in the customer's cart
    cursor.execute("SELECT * FROM Cart WHERE cust_id = %s AND prod_id = %s", (cust_id, prod_id))
    existing_item = cursor.fetchone()

    # If the product already exists in the cart, just update the quantity or total
    if existing_item:
        flash("Product is already in your cart!", "info")
    else:
        cursor.execute("SELECT price FROM Product WHERE prod_id = %s", (prod_id,))
        product = cursor.fetchone()
        if not product:
            flash("Product not found!", "danger")
            return redirect(url_for('shop', cust_id=cust_id))

        price = product[0]
        try:
            cursor.execute("INSERT INTO Cart (cust_id, prod_id, total) VALUES (%s, %s, %s)",
                           (cust_id, prod_id, price))
            mysql.commit()
            flash("Product added to cart!", "success")
        except MySQLdb.Error as e:
            flash(str(e), "danger")

    return redirect(url_for('shop', cust_id=cust_id))

@app.route('/cart/<int:cust_id>')
def view_cart(cust_id):
    cursor = mysql.cursor()
    cursor.execute("SELECT * FROM Customer WHERE cust_id = %s", (cust_id,))
    customer = cursor.fetchone()
    if not customer:
        flash("Customer not found!", "danger")
        return redirect(url_for('index'))

    cursor.execute("""
        SELECT Product.prod_name, Product.price, Cart.total, Product.prod_id
        FROM Cart
        JOIN Product ON Cart.prod_id = Product.prod_id
        WHERE Cart.cust_id = %s
    """, (cust_id,))
    cart_items = cursor.fetchall()
    return render_template('cart.html', cart=cart_items, cust_id=cust_id)

# STEP 1: Show address + payment form
@app.route('/place_order/<int:cust_id>', methods=['GET', 'POST'])
def place_order(cust_id):
    cursor = mysql.cursor()
    cursor.execute("SELECT * FROM Customer WHERE cust_id = %s", (cust_id,))
    if not cursor.fetchone():
        flash("Customer not found!", "danger")
        return redirect(url_for('index'))

    cursor.execute("SELECT * FROM Address WHERE cust_id = %s", (cust_id,))
    addresses = cursor.fetchall()

    cursor.execute("SELECT SUM(total) FROM Cart WHERE cust_id = %s", (cust_id,))
    total = cursor.fetchone()[0]

    if total is None:
        flash("Cart is empty.", "danger")
        return redirect(url_for('view_cart', cust_id=cust_id))

    # Handle POST request when form is submitted
    if request.method == 'POST':
        selected_address = request.form.get('address')
        new_apart = request.form.get('apart_no')
        new_street = request.form.get('street_name')
        new_city = request.form.get('city')
        new_state = request.form.get('state')
        new_pin = request.form.get('pincode')
        payment_mode = request.form.get('payment_mode')

        # Check if selected_address is None (i.e., no address selected)
        if selected_address is None:
            flash("Please select an address", "danger")
            return redirect(url_for('place_order', cust_id=cust_id))

        # Use new address if 'new' is selected
        if selected_address == 'new':
            cursor.execute("""
                INSERT INTO Address (cust_id, apart_no, street_name, city, state, pincode)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (cust_id, new_apart, new_street, new_city, new_state, new_pin))
            mysql.commit()
            address_id = cursor.lastrowid  # Get the newly inserted address ID
        else:
            address_id = int(selected_address)

        cursor.execute("SELECT SUM(total) FROM Cart WHERE cust_id = %s", (cust_id,))
        total = cursor.fetchone()[0]

        order_date = datetime.today().date()
        ship_date = order_date + timedelta(days=7)

        cursor.execute("""
            INSERT INTO Orders (cust_id, order_date, order_amount, ship_date)
            VALUES (%s, %s, %s, %s)
        """, (cust_id, order_date, total, ship_date))
        order_id = cursor.lastrowid

        cursor.execute("INSERT INTO Status (order_id, status) VALUES (%s, %s)", (order_id, 'Pending'))
        cursor.execute("INSERT INTO Payment_mode (order_id, payment_mode) VALUES (%s, %s)",
                       (order_id, payment_mode))
        mysql.commit()

        cursor.execute("SELECT first_name, last_name FROM Customer WHERE cust_id = %s", (cust_id,))
        name = cursor.fetchone()

        cursor.execute("SELECT * FROM Address WHERE address_id = %s", (address_id,))
        address = cursor.fetchone()

        return render_template('order_summary.html', name=name, address=address,
                               payment_mode=payment_mode, total=total,
                               order_date=order_date, ship_date=ship_date)

    return render_template('place_order.html', cust_id=cust_id, addresses=addresses, total=total)

# STEP 2: Finalize the order and show summary
@app.route('/finalize_order/<int:cust_id>', methods=['POST'])
def finalize_order(cust_id):
    cursor = mysql.cursor()

    selected_address = request.form.get('address')
    new_apart = request.form.get('apart_no')
    new_street = request.form.get('street_name')
    new_city = request.form.get('city')
    new_state = request.form.get('state')
    new_pin = request.form.get('pincode')
    payment_mode = request.form.get('payment_mode')

    # Use new address if 'new' is selected
    if selected_address == 'new':
        cursor.execute("""
            INSERT INTO Address (cust_id, apart_no, street_name, city, state, pincode)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (cust_id, new_apart, new_street, new_city, new_state, new_pin))
        mysql.commit()
        address_id = cursor.lastrowid
    else:
        address_id = int(selected_address)

    cursor.execute("SELECT SUM(total) FROM Cart WHERE cust_id = %s", (cust_id,))
    total = cursor.fetchone()[0]

    order_date = datetime.today().date()
    ship_date = order_date + timedelta(days=7)

    cursor.execute("""
        INSERT INTO Orders (cust_id, order_date, order_amount, ship_date)
        VALUES (%s, %s, %s, %s)
    """, (cust_id, order_date, total, ship_date))
    order_id = cursor.lastrowid

    cursor.execute("INSERT INTO Status (order_id, status) VALUES (%s, %s)", (order_id, 'Pending'))
    cursor.execute("INSERT INTO Payment_mode (order_id, payment_mode) VALUES (%s, %s)",
                   (order_id, payment_mode))
    mysql.commit()

    cursor.execute("SELECT first_name, last_name FROM Customer WHERE cust_id = %s", (cust_id,))
    name = cursor.fetchone()

    cursor.execute("SELECT * FROM Address WHERE address_id = %s", (address_id,))
    address = cursor.fetchone()

    return render_template('order_summary.html', name=name, address=address,
                           payment_mode=payment_mode, total=total,
                           order_date=order_date, ship_date=ship_date)

# User Registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')

        cursor = mysql.cursor()

        try:
            cursor.execute("""
                INSERT INTO Customer (first_name, last_name, email, phone)
                VALUES (%s, %s, %s, %s)
            """, (first_name, last_name, email, phone))
            mysql.commit()

            cust_id = cursor.lastrowid  # get the auto-generated ID
            flash(f"Registration successful! Your Customer ID is {cust_id}. Use this to log in.", "success")
            return render_template('show_cust_id.html', cust_id=cust_id)

        except MySQLdb.IntegrityError:
            flash("Email already exists. Try logging in or use a different email.", "danger")
            return redirect(url_for('register'))

    return render_template('register.html')


if __name__ == '__main__':
    app.run(debug=True)
