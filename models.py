# backend/models.py

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime

from backend.database import Base   # Base viene de database.py


# =========================================================
#   MODELO SQLAlchemy: Usuario
#   Debe coincidir con la tabla "usuarios" en PostgreSQL
# =========================================================

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    primer_apellido = Column(String(100), nullable=False)
    segundo_apellido = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False)      # NOT NULL en tu tabla
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
