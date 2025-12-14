from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Dict, Optional, Any
import inspect

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import SQLAlchemyError

from passlib.context import CryptContext

# GA 1: puntos ciegos
from .algoritmo_genetico import algoritmo_genetico_puntos_ciegos

# GA 2: mejorar cobertura (niveles)
from .ga_cobertura import (
    algoritmo_genetico_mejorar_cobertura,
    generar_grid_puntos,
    metricas_niveles_cobertura,
)

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
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/home")
async def redirect_home():
    return RedirectResponse(url="/")


@app.get("/mapa", response_class=FileResponse)
async def serve_mapa():
    return FileResponse(FRONTEND_DIR / "mapa.html")


@app.get("/api/health")
def health():
    return {"ok": True}


# =========================================================
#   BASE DE DATOS (SQLAlchemy) – POSTGRESQL
# =========================================================
DATABASE_URL = "postgresql+psycopg2://postgres:17112018Z@localhost:5432/camaras_c5"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # evita conexiones muertas
)
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
    email = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)


class Camara(Base):
    __tablename__ = "camaras"

    id = Column(Integer, primary_key=True, index=True)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    tipo = Column(String(50), nullable=True)
    descripcion = Column(String, nullable=True)


class CamaraPropuesta(Base):
    __tablename__ = "camaras_propuestas"

    id = Column(Integer, primary_key=True, index=True)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    cobertura = Column(Float, nullable=False)  # 0–100
    origen = Column(String(50), nullable=True)  # "simulacion", "AG", etc.
    descripcion = Column(String, nullable=True)


# Crea tablas (si no existen)
Base.metadata.create_all(bind=engine)


# =========================================================
#   ESQUEMAS Pydantic
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
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
        from_attributes = True


class CamaraPropuestaBase(BaseModel):
    latitud: float
    longitud: float
    cobertura: float
    origen: str | None = None
    descripcion: str | None = None


class CamaraPropuestaCreate(CamaraPropuestaBase):
    pass


class CamaraPropuestaRead(CamaraPropuestaBase):
    id: int

    class Config:
        from_attributes = True


class CamarasPropuestasBatch(BaseModel):
    camaras: List[CamaraPropuestaCreate]


class CamaraSimuladaIn(BaseModel):
    latitud: float
    longitud: float


# =========================================================
#   SEGURIDAD (hash)
# =========================================================
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# =========================================================
#   HELPER: Llamar función solo con kwargs soportados
# =========================================================
def _call_with_supported_kwargs(func, **kwargs):
    sig = inspect.signature(func)
    allowed = set(sig.parameters.keys())
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    return func(**filtered)


# =========================================================
#   AUTH (Modo A: sin sesiones)
# =========================================================
@app.post("/api/usuarios/registro", response_model=UsuarioRead, status_code=status.HTTP_201_CREATED)
def registrar_usuario(datos: UsuarioCreate, db: Session = Depends(get_db)):
    email_normalizado = datos.email.lower().strip()

    existente = db.query(Usuario).filter(Usuario.email == email_normalizado).first()
    if existente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El correo ya está registrado.")

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error BD: {str(e)}")

    return usuario


@app.post("/api/auth/login")
def login(datos: LoginRequest, db: Session = Depends(get_db)):
    email_normalizado = datos.email.lower().strip()

    usuario = db.query(Usuario).filter(Usuario.email == email_normalizado).first()
    if not usuario or not verify_password(datos.password, usuario.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Correo o contraseña incorrectos.")

    return {
        "ok": True,
        "usuario": {
            "id": usuario.id,
            "nombre": usuario.nombre,
            "primer_apellido": usuario.primer_apellido,
            "segundo_apellido": usuario.segundo_apellido,
            "email": usuario.email,
        }
    }


@app.post("/api/auth/logout")
def logout():
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me():
    return {"authenticated": False}


# =========================================================
#   CÁMARAS
# =========================================================
@app.get("/api/camaras", response_model=List[CamaraRead])
def listar_camaras(db: Session = Depends(get_db)):
    return db.query(Camara).all()


@app.post("/api/camaras", response_model=CamaraRead, status_code=status.HTTP_201_CREATED)
def crear_camara(camara_in: CamaraCreate, db: Session = Depends(get_db)):
    cam = Camara(
        latitud=camara_in.latitud,
        longitud=camara_in.longitud,
        tipo=camara_in.tipo,
        descripcion=camara_in.descripcion
    )

    try:
        db.add(cam)
        db.commit()
        db.refresh(cam)
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error BD: {str(e)}")

    return cam


@app.get("/api/camaras-propuestas", response_model=List[CamaraPropuestaRead])
def listar_camaras_propuestas(db: Session = Depends(get_db)):
    return db.query(CamaraPropuesta).all()


@app.post(
    "/api/camaras-propuestas/guardar-buenas",
    response_model=List[CamaraPropuestaRead],
    status_code=status.HTTP_201_CREATED
)
def guardar_camaras_propuestas_buenas(batch: CamarasPropuestasBatch, db: Session = Depends(get_db)):
    buenas = [c for c in batch.camaras if c.cobertura >= 80.0]
    if not buenas:
        raise HTTPException(status_code=400, detail="No hay cámaras con cobertura >= 80 para guardar.")

    guardadas: List[CamaraPropuesta] = []

    try:
        for c in buenas:
            cam = CamaraPropuesta(
                latitud=c.latitud,
                longitud=c.longitud,
                cobertura=c.cobertura,
                origen=c.origen or "simulacion",
                descripcion=c.descripcion
            )
            db.add(cam)
            guardadas.append(cam)

        db.commit()
        for cam in guardadas:
            db.refresh(cam)

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error BD: {str(e)}")

    return guardadas


# =========================================================
#   Evaluar cámara simulada (coverage + delta) - MÁS RÁPIDO
# =========================================================
@app.post("/api/cobertura/camara-simulada")
def evaluar_camara_simulada(datos: CamaraSimuladaIn, db: Session = Depends(get_db)):
    camaras_db = db.query(Camara).all()
    if not camaras_db:
        return {"coverage": 0.0, "delta": 0.0}

    camaras_existentes: List[Tuple[float, float]] = [
        (float(c.latitud), float(c.longitud)) for c in camaras_db
    ]

    # Más ligero: menos puntos (para que el front responda rápido)
    puntos_eval = generar_grid_puntos(
        camaras_existentes,
        step_m=250.0,
        margin_factor=0.05,
        max_points=1500
    )

    cam_propuesta = (float(datos.latitud), float(datos.longitud))

    met_before = metricas_niveles_cobertura(
        puntos_eval=puntos_eval,
        camaras_totales=camaras_existentes,
        radio_m=120.0
    )

    met_after = metricas_niveles_cobertura(
        puntos_eval=puntos_eval,
        camaras_totales=camaras_existentes + [cam_propuesta],
        radio_m=120.0
    )

    before = float(met_before.get("cobertura_total", 0.0))
    after = float(met_after.get("cobertura_total", 0.0))
    delta = after - before

    return {"coverage": round(after, 2), "delta": round(delta, 2)}


# =========================================================
#   GA 1: Puntos ciegos
# =========================================================
class PuntoCiego(BaseModel):
    latitud: float
    longitud: float
    fitness: float


@app.get("/api/ag/puntos-ciegos", response_model=List[PuntoCiego])
def obtener_puntos_ciegos(db: Session = Depends(get_db)):
    camaras_db = db.query(Camara).all()
    if not camaras_db:
        raise HTTPException(status_code=400, detail="No hay cámaras registradas para evaluar puntos ciegos.")

    camaras: List[Tuple[float, float]] = [(float(c.latitud), float(c.longitud)) for c in camaras_db]

    try:
        mejores = algoritmo_genetico_puntos_ciegos(camaras)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar el algoritmo genético: {str(e)}")

    return [
        PuntoCiego(latitud=float(lat), longitud=float(lon), fitness=float(fit))
        for (lat, lon, fit) in mejores
    ]


# =========================================================
#   GA 2: Mejorar cobertura (MODO PROFESOR: rápido)
# =========================================================
class GACoberturaRequest(BaseModel):
    n_camaras_nuevas: int = 8
    radio_m: float = 120.0
    step_grid_m: float = 250.0
    grid_max_points: int = 1500

    # IMPORTANTE: defaults más ligeros para NO colgar el front
    tam_poblacion: int = 25
    generaciones: int = 20
    elitismo: int = 2
    k_torneo: int = 3
    alpha_blx: float = 0.5
    penalizar_sobrecobertura: bool = True

    penalizar_cercania: bool = True
    min_dist_entre_nuevas_m: float = 220.0
    min_dist_a_existentes_m: float = 120.0
    peso_cercania: float = 12.0

    usar_puntos_ciegos_seed: bool = False
    n_puntos_ciegos_seed: int = 8


class CamaraNuevaOut(BaseModel):
    latitud: float
    longitud: float


class GACoberturaResponse(BaseModel):
    camaras_nuevas: List[CamaraNuevaOut]
    fitness: float
    metricas: Dict[str, float]


@app.post("/api/ga/mejorar-cobertura", response_model=GACoberturaResponse)
def ga_mejorar_cobertura(req: GACoberturaRequest, db: Session = Depends(get_db)):
    camaras_db = db.query(Camara).all()
    if not camaras_db:
        raise HTTPException(status_code=400, detail="No hay cámaras registradas para ejecutar GA de cobertura.")

    camaras_existentes: List[Tuple[float, float]] = [
        (float(c.latitud), float(c.longitud)) for c in camaras_db
    ]

    puntos_semilla: Optional[List[Tuple[float, float]]] = None
    if req.usar_puntos_ciegos_seed:
        mejores = algoritmo_genetico_puntos_ciegos(camaras_existentes)
        puntos_semilla = [
            (float(lat), float(lon))
            for (lat, lon, _fit) in mejores[: max(1, req.n_puntos_ciegos_seed)]
        ]

    try:
        resultado: Dict[str, Any] = _call_with_supported_kwargs(
            algoritmo_genetico_mejorar_cobertura,
            camaras_existentes_in=camaras_existentes,
            n_camaras_nuevas=req.n_camaras_nuevas,
            radio_m=req.radio_m,
            puntos_eval=None,
            step_grid_m=req.step_grid_m,
            grid_max_points=req.grid_max_points,
            tam_poblacion=req.tam_poblacion,
            generaciones=req.generaciones,
            elitismo=req.elitismo,
            k_torneo=req.k_torneo,
            alpha_blx=req.alpha_blx,
            penalizar_sobrecobertura=req.penalizar_sobrecobertura,
            penalizar_cercania=req.penalizar_cercania,
            min_dist_entre_nuevas_m=req.min_dist_entre_nuevas_m,
            min_dist_a_existentes_m=req.min_dist_a_existentes_m,
            peso_cercania=req.peso_cercania,
            puntos_semilla=puntos_semilla,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar GA de cobertura: {str(e)}")

    camaras_nuevas = resultado.get("camaras_nuevas", []) or []
    metricas = resultado.get("metricas", {}) or {}
    fitness = float(resultado.get("fitness", 0.0) or 0.0)

    cam_out = [CamaraNuevaOut(latitud=float(a), longitud=float(b)) for (a, b) in camaras_nuevas]

    return GACoberturaResponse(
        camaras_nuevas=cam_out,
        fitness=fitness,
        metricas={str(k): float(v) for k, v in metricas.items()},
    )
