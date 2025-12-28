from flask import (
    Flask, Response, request, jsonify,
    session, render_template, redirect
)
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from extensions import db, migrate
from models import User, Transaction
from fpdf import FPDF
from datetime import datetime
from flask import send_file
from flask_cors import CORS   # ✅ ADD
import tempfile


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # =====================================================
    # 🔥 SESSION + COOKIE CONFIG (REQUIRED FOR GITHUB PAGES)
    # =====================================================
    app.config.update(
        SESSION_COOKIE_SAMESITE="None",   # REQUIRED for cross-site
        SESSION_COOKIE_SECURE=True        # REQUIRED for HTTPS
    )

    # =====================================================
    # 🔥 CORS CONFIG (DO NOT USE *)
    # =====================================================
    CORS(
        app,
        supports_credentials=True,
        origins=[
            "https://aayush-oza.github.io"  # 👈 YOUR FRONTEND
        ]
    )

    db.init_app(app)
    migrate.init_app(app, db)

    # =====================================================
    # PAGE ROUTES
    # =====================================================

    @app.route("/")
    def login_page():
        return render_template("login.html")

    @app.route("/register")
    def register_page():
        return render_template("register.html")

    @app.route("/dashboard")
    def dashboard():
        if not session.get("user_id"):
            return redirect("/")
        return render_template("dashboard.html")

    @app.route("/transactions")
    def transactions_page():
        if not session.get("user_id"):
            return redirect("/")
        return render_template("transactions.html")

    # =====================================================
    # AUTH APIs
    # =====================================================

    @app.route("/api/register", methods=["POST"])
    def api_register():
        data = request.get_json()
        if not data or not all(k in data for k in ("name", "email", "password")):
            return jsonify({"success": False, "error": "Invalid data"}), 400

        try:
            user = User(
                name=data["name"],
                email=data["email"],
                password=generate_password_hash(data["password"])
            )
            db.session.add(user)
            db.session.commit()
            return jsonify({"success": True})
        except Exception:
            db.session.rollback()
            return jsonify({"success": False, "error": "Email exists"}), 400

    @app.route("/api/login", methods=["POST"])
    def api_login():
        data = request.get_json()
        user = User.query.filter_by(email=data.get("email")).first()

        if user and check_password_hash(user.password, data.get("password")):
            session["user_id"] = user.id
            session.modified = True  # 🔥 ENSURE COOKIE IS SENT
            return jsonify({"success": True})

        return jsonify({"success": False}), 401

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/")

    # =====================================================
    # TRANSACTION APIs
    # =====================================================

    @app.route("/api/add-transaction", methods=["POST"])
    def add_transaction():
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        data = request.get_json()
        required = ("amount", "type", "category", "mode", "date")
        if not data or not all(k in data and data[k] for k in required):
            return jsonify({"success": False, "error": "Missing fields"}), 400

        try:
            txn = Transaction(
                user_id=user_id,
                amount=float(data["amount"]),
                type=data["type"],
                category=data["category"],
                description=data.get("description"),
                mode=data["mode"],
                date=datetime.strptime(data["date"], "%Y-%m-%d").date()
            )
            db.session.add(txn)
            db.session.commit()
            return jsonify({"success": True})

        except Exception as e:
            db.session.rollback()
            print("ADD TXN ERROR:", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/transactions")
    def get_transactions():
        user_id = session.get("user_id")
        if not user_id:
            return jsonify([])

        txns = Transaction.query.filter_by(
            user_id=user_id
        ).order_by(Transaction.date.desc()).all()

        return jsonify([
            {
                "id": t.id,
                "amount": float(t.amount),
                "type": t.type,
                "category": t.category,
                "description": t.description,
                "mode": t.mode,
                "date": str(t.date)
            } for t in txns
        ])

    @app.route("/api/delete-transaction/<int:id>", methods=["DELETE"])
    def delete_transaction(id):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        txn = Transaction.query.filter_by(
            id=id, user_id=user_id
        ).first_or_404()

        db.session.delete(txn)
        db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/edit-transaction/<int:id>", methods=["PUT"])
    def edit_transaction(id):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json()
        txn = Transaction.query.filter_by(
            id=id, user_id=user_id
        ).first_or_404()

        txn.amount = data["amount"]
        txn.type = data["type"]
        txn.category = data["category"]
        txn.description = data.get("description")
        txn.mode = data["mode"]
        txn.date = datetime.strptime(data["date"], "%Y-%m-%d").date()

        db.session.commit()
        return jsonify({"success": True})

    # =====================================================
    # LEDGER + ANALYTICS (UNCHANGED)
    # =====================================================
    # (your existing code continues exactly as-is)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
