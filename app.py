import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+
import tempfile

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF

from extensions import db, migrate
from models import User, Transaction


def create_app():
    app = Flask(__name__)

    # =====================================================
    # 🔥 ENV CONFIG (SINGLE SOURCE OF TRUTH)
    # =====================================================
    JWT_SECRET = os.environ.get("JWT_SECRET_KEY")
    DB_URL = os.environ.get("DATABASE_URL")

    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET_KEY is NOT set")
    if not DB_URL:
        raise RuntimeError("DATABASE_URL is NOT set")

    app.config.update(
        JWT_SECRET_KEY=JWT_SECRET,
        SQLALCHEMY_DATABASE_URI=DB_URL,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        # JWT CONFIG (FIXED)
        JWT_TOKEN_LOCATION=["headers"],
        JWT_HEADER_NAME="Authorization",
        JWT_HEADER_TYPE="Bearer",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=7),
    )

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True
    }

    # =====================================================
    # JWT
    # =====================================================
    jwt = JWTManager(app)

    @jwt.unauthorized_loader
    def missing_token(reason):
        return jsonify(error="Missing token"), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return jsonify(error="Invalid token"), 401

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return jsonify(error="Token expired"), 401

    # =====================================================
    # CORS
    # =====================================================
    CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )


    # =====================================================
    # DATABASE
    # =====================================================
    db.init_app(app)
    migrate.init_app(app, db)

    # =====================================================
    # AUTH
    # =====================================================
    @app.route("/api/register", methods=["POST"])
    def register():
        data = request.get_json() or {}

        try:
            user = User(
                name=data["name"],
                email=data["email"],
                password=generate_password_hash(data["password"])
            )
            db.session.add(user)
            db.session.commit()
            return jsonify(success=True)
        except Exception:
            db.session.rollback()
            return jsonify(error="Email already exists"), 400

    @app.route("/api/login", methods=["POST"])
    def login():
        data = request.get_json() or {}

        user = User.query.filter_by(email=data.get("email")).first()

        if not user or not check_password_hash(user.password, data.get("password")):
            return jsonify(error="Invalid credentials"), 401

        token = create_access_token(identity=str(user.id))

        return jsonify(
            success=True,
            token=token,
            user={
                "id": user.id,
                "name": user.name,
                "email": user.email
            }
        )

    # =====================================================
    # TRANSACTIONS
    # =====================================================
    @app.route("/api/add-transaction", methods=["POST"])
    @jwt_required()
    def add_transaction():
        user_id = int(get_jwt_identity())
        data = request.get_json() or {}

        required = ("amount", "type", "category", "mode", "date")
        if not all(data.get(k) for k in required):
            return jsonify(error="Missing fields"), 400

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
        return jsonify(success=True)

    @app.route("/api/transactions")
    @jwt_required()
    def transactions():
        user_id = int(get_jwt_identity())
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
            }
            for t in txns
        ])

    @app.route("/api/edit-transaction/<int:txn_id>", methods=["PUT"])
    @jwt_required()
    def edit_transaction(txn_id):
        user_id = int(get_jwt_identity())
        txn = Transaction.query.filter_by(
            id=txn_id,
            user_id=user_id
        ).first_or_404()

        data = request.get_json() or {}

        txn.amount = float(data["amount"])
        txn.type = data["type"]
        txn.category = data["category"]
        txn.description = data.get("description")
        txn.mode = data["mode"]
        txn.date = datetime.strptime(data["date"], "%Y-%m-%d").date()

        db.session.commit()
        return jsonify(success=True)

    @app.route("/api/delete-transaction/<int:txn_id>", methods=["DELETE"])
    @jwt_required()
    def delete_transaction(txn_id):
        user_id = int(get_jwt_identity())
        txn = Transaction.query.filter_by(
            id=txn_id,
            user_id=user_id
        ).first_or_404()

        db.session.delete(txn)
        db.session.commit()
        return jsonify(success=True)

    # =====================================================
    # LEDGER
    # =====================================================
    @app.route("/api/ledger")
    @jwt_required()
    def ledger():
        user_id = int(get_jwt_identity())
        txns = Transaction.query.filter_by(user_id=user_id).all()

        balance = sum(
            t.amount if t.type == "credit" else -t.amount
            for t in txns
        )

        return jsonify(balance=round(balance, 2))

    # =====================================================
    # ANALYTICS
    # =====================================================
    @app.route("/api/analytics")
    @jwt_required()
    def analytics():
        user_id = int(get_jwt_identity())
        txns = Transaction.query.filter_by(user_id=user_id).all()

        modes, types, categories = {}, {}, {}

        for t in txns:
            modes[t.mode] = modes.get(t.mode, 0) + t.amount
            types[t.type] = types.get(t.type, 0) + t.amount
            if t.type == "debit":
                categories[t.category] = categories.get(t.category, 0) + t.amount

        return jsonify(modes=modes, types=types, categories=categories)

    # =====================================================
    # DOWNLOAD LEDGER
    # =====================================================
    @app.route("/api/download-ledger")
    @jwt_required()
    def download_ledger():
        user_id = int(get_jwt_identity())
        user = User.query.get_or_404(user_id)

        txns = Transaction.query.filter_by(
            user_id=user_id
        ).order_by(Transaction.date.asc()).all()

        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

    # ================= HEADER =================
        pdf.set_font("Helvetica", "B", 15)
        pdf.cell(0, 10, "LEDGER ACCOUNT", ln=True, align="C")

        pdf.ln(6)

        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 6, f"Account Holder : {user.name}", ln=True, align="L")

        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        pdf.cell(
            0,
            6,
            f"Generated On : {now_ist.strftime('%d %b %Y, %I:%M %p IST')}",
            ln=True,
            align="L"
        )
        pdf.ln(8)

    # ================= TABLE HEADER =================
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(30, 8, "Date", border=1)
        pdf.cell(60, 8, "Particulars", border=1)
        pdf.cell(25, 8, "Debit", border=1, align="R")
        pdf.cell(25, 8, "Credit", border=1, align="R")
        pdf.cell(25, 8, "Balance", border=1, align="R")
        pdf.ln()
    # ================= TABLE BODY =================
        pdf.set_font("Helvetica", size=9)
        running_balance = 0

        for t in txns:
            date = t.date.strftime("%d-%m-%Y")

            particulars = t.category.capitalize()
            if t.description:
                particulars += f" ({t.description})"

            debit = ""
            credit = ""

            if t.type == "debit":
                running_balance -= t.amount
                debit = f"{t.amount:.2f}"
            else:
                running_balance += t.amount
                credit = f"{t.amount:.2f}"

            pdf.cell(30, 8, date, border=1)
            pdf.cell(60, 8, particulars, border=1)
            pdf.cell(25, 8, debit, border=1, align="R")
            pdf.cell(25, 8, credit, border=1, align="R")
            pdf.cell(25, 8, f"{running_balance:.2f}", border=1, align="R")
            pdf.ln()

    # ================= CLOSING BALANCE =================
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(140, 9, "Closing Balance", border=1)
        pdf.cell(
            25,
            9,
            f"{running_balance:.2f}",
            border=1,
            align="R"
        )

    # ================= SAVE & SEND =================
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf.output(tmp.name)

        return send_file(
            tmp.name,
            as_attachment=True,
            download_name="ledger.pdf"
        )


    # =====================================================
    # HEALTH
    # =====================================================
    @app.route("/health")
    def health():
        return jsonify(status="ok")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

