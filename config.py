import os

class Config:
    # Required
    JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]

    # Optional / safe defaults
    SQLALCHEMY_TRACK_MODIFICATIONS = False
