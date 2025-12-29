import os

class Config:
    # Flask session / CSRF (not used by JWT, but fine to keep)
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "unused-flask-secret")

    # JWT — THIS IS THE ONLY KEY JWT WILL USE
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
