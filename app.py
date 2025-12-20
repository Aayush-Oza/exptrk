from flask import Flask, request, jsonify, session
import psycopg2
import os
from werkzeug.security import generate_password_hash, check_password_hash
from config import DATABASE_URL, SECRET_KEY

app = Flask(__name__)
app.secret_key = SECRET_KEY

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ---------------- AUTH ----------------

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    name = data["name"]
    email = data["email"]
    password = generate_password_hash(data["password"])

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (name, email, password) VALUES (%s,%s,%s)",
            (name, email, password)
        )
        conn.commit()
        return jsonify({"success": True})
    except:
        return jsonify({"success": False, "error": "Email already exists"})
    finally:
        cur.close()
        conn.close()

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data["email"]
    password = data["password"]

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, password FROM users WHERE email=%s", (email,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user and check_password_hash(user[1], password):
        session["user_id"] = user[0]
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/logout")
def logout():
    session.clear()
    return jsonify({"success": True})

# ---------------- TRANSACTIONS ----------------

@app.route("/add-transaction", methods=["POST"])
def add_transaction():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO transactions
        (user_id, amount, type, category, mode, description, date)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        session["user_id"],
        data["amount"],
        data["type"],
        data["category"],
        data["mode"],
        data.get("description"),
        data["date"]
    ))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"success": True})

@app.route("/transactions")
def transactions():
    if "user_id" not in session:
        return jsonify([])

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, amount, type, category, mode, description, date
        FROM transactions
        WHERE user_id=%s
        ORDER BY date DESC
    """, (session["user_id"],))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(rows)

@app.route("/edit-transaction/<int:id>", methods=["PUT"])
def edit_transaction(id):
    data = request.json
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE transactions
        SET amount=%s, category=%s, mode=%s, description=%s, date=%s
        WHERE id=%s AND user_id=%s
    """, (
        data["amount"],
        data["category"],
        data["mode"],
        data["description"],
        data["date"],
        id,
        session["user_id"]
    ))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"success": True})

@app.route("/delete-transaction/<int:id>", methods=["DELETE"])
def delete_transaction(id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM transactions WHERE id=%s AND user_id=%s",
        (id, session["user_id"])
    )
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"success": True})

# ---------------- LEDGER ----------------

@app.route("/ledger")
def ledger():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
        COALESCE(SUM(CASE WHEN type='credit' THEN amount END),0) -
        COALESCE(SUM(CASE WHEN type='debit' THEN amount END),0)
        FROM transactions
        WHERE user_id=%s
    """, (session["user_id"],))
    balance = cur.fetchone()[0]
    cur.close()
    conn.close()

    return jsonify({"balance": float(balance)})

# ---------------- MAIN ----------------

if __name__ == "__main__":
    app.run(debug=True)
