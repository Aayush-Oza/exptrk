from datetime import datetime
from extensions import db

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    type = db.Column(db.String(10))
    category = db.Column(db.String(100))
    description = db.Column(db.String(255))
    mode = db.Column(db.String(10))
    description = db.Column(db.Text)
    date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PeopleLedger(db.Model):
    __tablename__ = "people_ledger"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    person_name = db.Column(db.String(100))
    amount = db.Column(db.Numeric(10, 2))
    type = db.Column(db.String(20))
    description = db.Column(db.Text)
    date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
