from pathlib import Path
from typing import List

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import SQLAlchemyError

from passlib.context import CryptContext

# =========================================================
#   CONFIG FASTAPI
# =========================================================

app = FastAPI(title="Sistema C5 – Proyectoweb")

# =========================================================
#   RUTAS DE ARCHIVOS (FRONTEND)
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = BASE_DIR / "frontend"
CSS_DIR = BASE_DIR / "css"
JS_DIR = BASE_DIR / "js"
ASSETS_DIR = BASE_DIR / "assets"

app.mount("/css", StaticFiles(directory=CSS_DIR), name="css")
app.mount("/js", StaticFiles(directory=JS_DIR), name="js")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/", response_class=FileResponse)
async def serve_home():
    index_path = FRONTEND_DIR / "index.html"
    return FileResponse(index_path)


@app.get("/home")
async def redirect_home():
    return RedirectResponse(url="/")


# =========================================================
#   BASE DE DATOS – POSTGRESQL
# =========================================================

DATABASE_URL = "postgresql+psycopg2://postgres:17112018Z@localhost:5432/camaras_c5"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
#   MODELOS SQLAlchemy
# =========================================================

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    primer_apellido = Column(String(100), nullable=False)
    segundo_apellido = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)


# IMPORTANTE: esta definición coincide con tu tabla real:
# id (integer), latitud (double precision),
# longitud (double precision), tipo (varchar(50)), descripcion (text)
class Camara(Base):
    __tablename__ = "camaras"

    id = Column(Integer, primary_key=True, index=True)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    tipo = Column(String(50), nullable=True)
    descripcion = Column(String, nullable=True)


Base.metadata.create_all(bind=engine)

# =========================================================
#   ESQUEMAS Pydantic – USUARIOS
# =========================================================

class UsuarioCreate(BaseModel):
    nombre: str
    primer_apellido: str
    segundo_apellido: str
    email: EmailStr
    password: str


class UsuarioRead(BaseModel):
    id: int
    nombre: str
    primer_apellido: str
    segundo_apellido: str
    email: EmailStr

    class Config:
        orm_mode = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# =========================================================
#   ESQUEMAS Pydantic – CÁMARAS
# =========================================================

class CamaraBase(BaseModel):
    latitud: float
    longitud: float
    tipo: str | None = None
    descripcion: str | None = None


class CamaraCreate(CamaraBase):
    pass


class CamaraRead(CamaraBase):
    id: int

    class Config:
        orm_mode = True


# =========================================================
#   SEGURIDAD
# =========================================================

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto"
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# =========================================================
#   ENDPOINT: Registro de usuario
# =========================================================

@app.post("/api/usuarios/registro", response_model=UsuarioRead, status_code=status.HTTP_201_CREATED)
def registrar_usuario(datos: UsuarioCreate, db: Session = Depends(get_db)):
    email_normalizado = datos.email.lower().strip()

    existente = db.query(Usuario).filter(Usuario.email == email_normalizado).first()
    if existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo ya está registrado."
        )

    usuario = Usuario(
        nombre=datos.nombre.strip(),
        primer_apellido=datos.primer_apellido.strip(),
        segundo_apellido=datos.segundo_apellido.strip(),
        email=email_normalizado,
        password_hash=hash_password(datos.password),
    )

    try:
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error BD: {str(e)}"
        )

    return usuario


# =========================================================
#   ENDPOINT: Login
# =========================================================

@app.post("/api/auth/login")
def login(datos: LoginRequest, db: Session = Depends(get_db)):
    email_normalizado = datos.email.lower().strip()

    usuario = db.query(Usuario).filter(Usuario.email == email_normalizado).first()
    if not usuario or not verify_password(datos.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos."
        )

    return {
        "message": "Login correcto",
        "usuario": {
            "id": usuario.id,
            "nombre": usuario.nombre,
            "primer_apellido": usuario.primer_apellido,
            "segundo_apellido": usuario.segundo_apellido,
            "email": usuario.email,
        }
    }


# =========================================================
#   ENDPOINTS: Cámaras
# =========================================================

@app.get("/api/camaras", response_model=List[CamaraRead])
def listar_camaras(db: Session = Depends(get_db)):
    """
    Devuelve todas las cámaras registradas.
    """
    camaras = db.query(Camara).all()
    return camaras


@app.post("/api/camaras", response_model=CamaraRead, status_code=status.HTTP_201_CREATED)
def crear_camara(camara_in: CamaraCreate, db: Session = Depends(get_db)):
    """
    Crea una cámara (la usaremos para pruebas o para el GA después).
    """
    camara = Camara(
        latitud=camara_in.latitud,
        longitud=camara_in.longitud,
        tipo=camara_in.tipo,
        descripcion=camara_in.descripcion,
    )

    try:
        db.add(camara)
        db.commit()
        db.refresh(camara)
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error BD: {str(e)}"
        )

    return camara
