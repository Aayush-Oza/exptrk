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
import tempfile



def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

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
            print("ADD TXN ERROR:", e)  # 🔥 YOU NEED THIS
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500


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
                "description": t.description,   # ✅ ADD
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
        txn.description = data.get("description")  # ✅ ADD
        txn.mode = data["mode"]
        txn.date = datetime.strptime(data["date"], "%Y-%m-%d").date()

        db.session.commit()
        return jsonify({"success": True})

    # =====================================================
    # LEDGER
    # =====================================================

    @app.route("/api/ledger")
    def ledger():
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"balance": 0})

        credit = db.session.query(
            db.func.coalesce(db.func.sum(Transaction.amount), 0)
        ).filter_by(user_id=user_id, type="credit").scalar()

        debit = db.session.query(
            db.func.coalesce(db.func.sum(Transaction.amount), 0)
        ).filter_by(user_id=user_id, type="debit").scalar()

        return jsonify({"balance": float(credit - debit)})
    @app.route("/api/analytics")
    def analytics():
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({}), 401

    # Payment mode %
        mode_data = db.session.query(
            Transaction.mode,
            db.func.sum(Transaction.amount)
        ).filter_by(user_id=user_id)\
        .group_by(Transaction.mode).all()

    # Debit vs Credit
        type_data = db.session.query(
            Transaction.type,
            db.func.sum(Transaction.amount)
        ).filter_by(user_id=user_id)\
        .group_by(Transaction.type).all()

    # Category expenses (debit only)
        category_data = db.session.query(
            Transaction.category,
            db.func.sum(Transaction.amount)
        ).filter_by(user_id=user_id, type="debit")\
         .group_by(Transaction.category).all()
        return jsonify({
            "modes": dict(mode_data),
            "types": dict(type_data),
            "categories": dict(category_data)
        })
        
    @app.route("/analytics")
    def analytics_page():
        if not session.get("user_id"):
            return redirect("/")
        return render_template("analytics.html")

    @app.route("/api/download-ledger")
    def download_ledger():
        user_id = session.get("user_id")
        if not user_id:
            return redirect("/")

        user = User.query.get(user_id)
        txns = Transaction.query.filter_by(
            user_id=user_id
        ).order_by(Transaction.date.asc()).all()
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

    # ===== TITLE =====
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "ACCOUNT LEDGER", ln=True, align="C")
        pdf.ln(6)

    # ===== ACCOUNT INFO =====
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 8, f"Account Name: {user.name}", ln=True)
        pdf.cell(0, 8, f"Generated On: {datetime.now().strftime('%d-%m-%Y')}", ln=True)
        pdf.ln(6)

    # ===== TABLE HEADER =====
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(30, 8, "Date", border=1)
        pdf.cell(60, 8, "Particulars", border=1)
        pdf.cell(20, 8, "L.F.", border=1)
        pdf.cell(30, 8, "Debit", border=1)
        pdf.cell(30, 8, "Credit", border=1)
        pdf.ln()
    # ===== TABLE BODY =====
        pdf.set_font("Helvetica", size=10)

        for t in txns:
            debit = str(t.amount) if t.type == "debit" else ""
            credit = str(t.amount) if t.type == "credit" else ""

            pdf.cell(30, 8, t.date.strftime("%d-%m-%Y"), border=1)
            particulars = t.description or t.category
            pdf.cell(60, 8, particulars, border=1)
            pdf.cell(20, 8, "", border=1)
            pdf.cell(30, 8, debit, border=1)
            pdf.cell(30, 8, credit, border=1)
            pdf.ln()

    # ===== SAVE TEMP FILE =====
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf.output(tmp.name)

        return send_file(
            tmp.name,
            as_attachment=True,
            download_name="ledger.pdf",
            mimetype="application/pdf"
        )

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
