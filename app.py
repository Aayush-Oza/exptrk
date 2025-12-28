from flask import (
    Flask, request, jsonify, session, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from datetime import datetime
from fpdf import FPDF
import tempfile
import os

from config import Config
from extensions import db, migrate
from models import User, Transaction


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # =====================================================
    # SESSION / COOKIE (GITHUB PAGES COMPATIBLE)
    # =====================================================
    app.config.update(
        SESSION_COOKIE_SAMESITE="None",
        SESSION_COOKIE_SECURE=True
    )

    # =====================================================
    # CORS
    # =====================================================
    CORS(
        app,
        supports_credentials=True,
        origins=["https://aayush-oza.github.io"]
    )

    db.init_app(app)
    migrate.init_app(app, db)

    # =====================================================
    # HELPERS
    # =====================================================
    def require_login():
        uid = session.get("user_id")
        if not uid:
            return None, jsonify({"error": "Unauthorized"}), 401
        return uid, None, None

    # =====================================================
    # AUTH
    # =====================================================
    @app.route("/api/register", methods=["POST"])
    def register():
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid data"}), 400

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
            return jsonify({"error": "Email already exists"}), 400

    @app.route("/api/login", methods=["POST"])
    def login():
        data = request.get_json()
        user = User.query.filter_by(email=data.get("email")).first()

        if user and check_password_hash(user.password, data.get("password")):
            session["user_id"] = user.id
            session.modified = True
            return jsonify({"success": True})

        return jsonify({"error": "Invalid credentials"}), 401

    # =====================================================
    # TRANSACTIONS
    # =====================================================
    @app.route("/api/add-transaction", methods=["POST"])
    def add_transaction():
        user_id, err, code = require_login()
        if err:
            return err, code

        data = request.get_json()
        required = ("amount", "type", "category", "mode", "date")
        if not all(data.get(k) for k in required):
            return jsonify({"error": "Missing fields"}), 400

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
            return jsonify({"error": str(e)}), 500

    @app.route("/api/transactions")
    def transactions():
        user_id = session.get("user_id")
        if not user_id:
            return jsonify([])

        txns = Transaction.query.filter_by(user_id=user_id).order_by(
            Transaction.date.desc()
        ).all()

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

    @app.route("/api/edit-transaction/<int:txn_id>", methods=["PUT"])
    def edit_transaction(txn_id):
        user_id, err, code = require_login()
        if err:
            return err, code

        data = request.get_json()
        txn = Transaction.query.filter_by(
            id=txn_id, user_id=user_id
        ).first_or_404()

        txn.amount = float(data["amount"])
        txn.type = data["type"]
        txn.category = data["category"]
        txn.description = data.get("description")
        txn.mode = data["mode"]
        txn.date = datetime.strptime(data["date"], "%Y-%m-%d").date()

        db.session.commit()
        return jsonify({"success": True})

    @app.route("/api/delete-transaction/<int:txn_id>", methods=["DELETE"])
    def delete_transaction(txn_id):
        user_id, err, code = require_login()
        if err:
            return err, code

        txn = Transaction.query.filter_by(
            id=txn_id, user_id=user_id
        ).first_or_404()

        db.session.delete(txn)
        db.session.commit()
        return jsonify({"success": True})

    # =====================================================
    # LEDGER (BALANCE)
    # =====================================================
    @app.route("/api/ledger")
    def ledger():
        user_id, err, code = require_login()
        if err:
            return err, code

        txns = Transaction.query.filter_by(user_id=user_id).all()
        balance = 0

        for t in txns:
            balance += t.amount if t.type == "credit" else -t.amount

        return jsonify({"balance": round(balance, 2)})

    # =====================================================
    # ANALYTICS
    # =====================================================
    @app.route("/api/analytics")
    def analytics():
        user_id, err, code = require_login()
        if err:
            return err, code

        txns = Transaction.query.filter_by(user_id=user_id).all()

        modes = {}
        types = {}
        categories = {}

        for t in txns:
            modes[t.mode] = modes.get(t.mode, 0) + t.amount
            types[t.type] = types.get(t.type, 0) + t.amount
            if t.type == "debit":
                categories[t.category] = categories.get(t.category, 0) + t.amount

        return jsonify({
            "modes": modes,
            "types": types,
            "categories": categories
        })

    # =====================================================
    # DOWNLOAD LEDGER (PDF)
    # =====================================================
    @app.route("/api/download-ledger")
    def download_ledger():
        user_id, err, code = require_login()
        if err:
            return err, code

        txns = Transaction.query.filter_by(user_id=user_id).order_by(
            Transaction.date.asc()
        ).all()

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)

        pdf.cell(0, 10, "Ledger Report", ln=True)

        for t in txns:
            line = f"{t.date} | {t.type} | {t.category} | {t.mode} | {t.amount}"
            pdf.cell(0, 8, line, ln=True)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf.output(tmp.name)

        return send_file(
            tmp.name,
            as_attachment=True,
            download_name="ledger.pdf"
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
