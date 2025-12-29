from flask import Flask, request, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity
)
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
    # DATABASE SAFETY (FIX RANDOM SSL DROPS)
    # =====================================================
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True
    }

    # =====================================================
    # JWT CONFIG (DO NOT CHANGE CASUALLY)
    # =====================================================
    app.config["JWT_SECRET_KEY"] = os.environ.get(
        "JWT_SECRET_KEY", "dev-secret-change-me"
    )
    app.config["JWT_TOKEN_LOCATION"] = ["headers"]
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False

    jwt = JWTManager(app)

    # =====================================================
    # JWT ERROR HANDLERS (FIX 422 HELL)
    # =====================================================
    @jwt.unauthorized_loader
    def missing_token(reason):
        return jsonify(error="Missing token", detail=reason), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return jsonify(error="Invalid token", detail=reason), 401

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return jsonify(error="Token expired"), 401

    # =====================================================
    # CORS (THIS WAS THE BIG ONE)
    # =====================================================
    CORS(
        app,
        origins=["https://aayush-oza.github.io"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["Authorization"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )

    db.init_app(app)
    migrate.init_app(app, db)

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

        if not user or not check_password_hash(user.password, data.get("password")):
            return jsonify({"error": "Invalid credentials"}), 401

        token = create_access_token(identity=user.id)

        return jsonify({
            "success": True,
            "token": token,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email
            }
        })

    # =====================================================
    # TRANSACTIONS
    # =====================================================
    @app.route("/api/add-transaction", methods=["POST"])
    @jwt_required()
    def add_transaction():
        user_id = get_jwt_identity()
        data = request.get_json()

        required = ("amount", "type", "category", "mode", "date")
        if not all(data.get(k) for k in required):
            return jsonify({"error": "Missing fields"}), 400

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

    @app.route("/api/transactions")
    @jwt_required()
    def transactions():
        user_id = get_jwt_identity()

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
    @jwt_required()
    def edit_transaction(txn_id):
        user_id = get_jwt_identity()
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
    @jwt_required()
    def delete_transaction(txn_id):
        user_id = get_jwt_identity()

        txn = Transaction.query.filter_by(
            id=txn_id, user_id=user_id
        ).first_or_404()

        db.session.delete(txn)
        db.session.commit()
        return jsonify({"success": True})

    # =====================================================
    # LEDGER
    # =====================================================
    @app.route("/api/ledger")
    @jwt_required()
    def ledger():
        user_id = get_jwt_identity()
        txns = Transaction.query.filter_by(user_id=user_id).all()

        balance = 0
        for t in txns:
            balance += t.amount if t.type == "credit" else -t.amount

        return jsonify({"balance": round(balance, 2)})

    # =====================================================
    # ANALYTICS
    # =====================================================
    @app.route("/api/analytics")
    @jwt_required()
    def analytics():
        user_id = get_jwt_identity()
        txns = Transaction.query.filter_by(user_id=user_id).all()

        modes, types, categories = {}, {}, {}

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
    @jwt_required()
    def download_ledger():
        user_id = get_jwt_identity()
        user = User.query.get(user_id)

        txns = Transaction.query.filter_by(
            user_id=user_id
        ).order_by(Transaction.date.asc()).all()

        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "LEDGER", ln=True, align="C")

        pdf.ln(2)
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 8, f"Account Name: {user.name}", ln=True)
        pdf.cell(0, 8, f"Generated On: {datetime.now().strftime('%d-%m-%Y')}", ln=True)
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(25, 8, "Date", border=1)
        pdf.cell(60, 8, "Particulars", border=1)
        pdf.cell(15, 8, "L.F.", border=1)
        pdf.cell(30, 8, "Debit", border=1, align="R")
        pdf.cell(30, 8, "Credit", border=1, ln=True, align="R")

        pdf.set_font("Helvetica", size=10)
        for t in txns:
            particulars = t.category + (f" ({t.description})" if t.description else "")
            debit = f"{t.amount:.2f}" if t.type == "debit" else ""
            credit = f"{t.amount:.2f}" if t.type == "credit" else ""

            pdf.cell(25, 8, t.date.strftime("%d-%m-%Y"), border=1)
            pdf.cell(60, 8, particulars[:35], border=1)
            pdf.cell(15, 8, "", border=1)
            pdf.cell(30, 8, debit, border=1, align="R")
            pdf.cell(30, 8, credit, border=1, ln=True, align="R")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf.output(tmp.name)

        return send_file(tmp.name, as_attachment=True, download_name="ledger.pdf")

    # =====================================================
    # HEALTH
    # =====================================================
    @app.route("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
