# backend/algoritmo_genetico.py
from __future__ import annotations

from typing import List, Tuple, Sequence, Optional, Any
import random
from math import radians, sin, cos, asin, sqrt


# =========================================================
#   UTILIDAD: Distancia haversine en metros
# =========================================================
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)

    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    c = 2.0 * asin(sqrt(a))
    return R * c


# =========================================================
#   ADAPTADORES / HELPERS
# =========================================================
def _get_lat_lon(camara: Any) -> Tuple[float, float]:
    """Soporta ORM con .latitud/.longitud o tuplas (lat, lon)."""
    if hasattr(camara, "latitud") and hasattr(camara, "longitud"):
        return float(camara.latitud), float(camara.longitud)
    return float(camara[0]), float(camara[1])


def _bbox(camaras: Sequence[Any]) -> Tuple[float, float, float, float]:
    pts = [_get_lat_lon(c) for c in camaras]
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return min(lats), max(lats), min(lons), max(lons)


def _centroide(camaras: Sequence[Any]) -> Tuple[float, float]:
    pts = [_get_lat_lon(c) for c in camaras]
    return (
        sum(p[0] for p in pts) / len(pts),
        sum(p[1] for p in pts) / len(pts),
    )


def _dist_min_a_camaras(lat: float, lon: float, camaras: Sequence[Any]) -> float:
    return min(
        haversine_m(lat, lon, clat, clon)
        for (clat, clon) in (_get_lat_lon(c) for c in camaras)
    )


def _dist_prom_k_vecinas(lat: float, lon: float, camaras: Sequence[Any], k: int = 3) -> float:
    dists = sorted(
        haversine_m(lat, lon, clat, clon)
        for (clat, clon) in (_get_lat_lon(c) for c in camaras)
    )
    k = max(1, min(k, len(dists)))
    return sum(dists[:k]) / k


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# =========================================================
#   FITNESS COMPLETO: huecos internos + penalización bordes
# =========================================================
def fitness_punto_completo(
    punto: Tuple[float, float],
    camaras: Sequence[Any],
    # radio local aproximado de cobertura (ajusta a tu modelo real)
    radio_cobertura_m: float = 80.0,
    # hasta qué distancia es “interesante” un hueco interno
    max_interes_m: float = 350.0,
    # si te alejas demasiado del conjunto, es extrapolación (penaliza)
    max_extrapolacion_m: float = 900.0,
    # vecindad para “internidad” (a mayor k, más favorece huecos internos)
    k_vecinos: int = 4,
    # penalización si el punto se pega al borde del bbox
    borde_frac_penal: float = 0.10,  # 10% del bbox como “zona borde”
) -> float:
    """
    Score final (0..1), donde 1 = mejor candidato a punto ciego / zona subcubierta.

    Objetivo:
    - hueco: lejos de cámaras (pero limitado)
    - interno: cerca de varias cámaras (no “afuera del cluster”)
    - penalizar: extrapolación y borde del bbox

    Nota importante:
    Con muchas cámaras (densidad alta), casi todo puede quedar "cubierto" (dmin <= radio).
    Si devolvemos 0 en esos casos, el GA se queda sin gradiente y colapsa.
    Por eso aquí usamos penalización SUAVE en lugar de 0 absoluto.
    """
    if not camaras:
        return 0.0

    lat, lon = float(punto[0]), float(punto[1])

    # Distancia mínima a cámaras
    dmin = _dist_min_a_camaras(lat, lon, camaras)

    # --- CAMBIO CLAVE ---
    # Si ya está cubierto, antes era 0.0 (colapsa con muchas cámaras).
    # Ahora damos un score pequeño proporcional: mientras más cerca del borde de cobertura,
    # "menos cubierto" está (pero sigue siendo bajo).
    if dmin <= radio_cobertura_m:
        return _clamp(0.05 * (dmin / max(radio_cobertura_m, 1e-9)), 0.0, 0.05)

    # Hueco: distancia normalizada (0..1) respecto a max_interes_m
    # --- CAMBIO: más estable que (d - radio)/(max - radio) en escenarios densos ---
    d_use = min(dmin, max_interes_m)
    hueco = d_use / max(max_interes_m, 1e-9)
    hueco = _clamp(hueco, 0.0, 1.0)

    # Internidad: si está cerca de varias cámaras, d_k será moderado
    d_k = _dist_prom_k_vecinas(lat, lon, camaras, k=k_vecinos)
    interno = 1.0 - min(d_k / max(max_interes_m, 1e-9), 1.0)  # 1 = más interno
    interno = _clamp(interno, 0.0, 1.0)

    # Penalización por extrapolación (muy lejos del centroide)
    c_lat, c_lon = _centroide(camaras)
    d_cent = haversine_m(lat, lon, c_lat, c_lon)

    penal_extrap = 0.0
    if d_cent > max_interes_m:
        penal_extrap = (d_cent - max_interes_m) / max((max_extrapolacion_m - max_interes_m), 1e-9)
        penal_extrap = _clamp(penal_extrap, 0.0, 1.0)

    # --- CAMBIO: castigo menos agresivo para no matar todo en datasets grandes ---
    penal_extrap *= 0.5

    # Penalización por borde del bbox (evita “irse a orillas”)
    min_lat, max_lat, min_lon, max_lon = _bbox(camaras)
    lat_span = max(max_lat - min_lat, 1e-9)
    lon_span = max(max_lon - min_lon, 1e-9)

    lat_borde = lat_span * borde_frac_penal
    lon_borde = lon_span * borde_frac_penal

    cerca_borde = (
        (lat < min_lat + lat_borde) or
        (lat > max_lat - lat_borde) or
        (lon < min_lon + lon_borde) or
        (lon > max_lon - lon_borde)
    )
    penal_borde = 0.15 if cerca_borde else 0.0  # --- CAMBIO: un poco más suave ---

    # Combinar
    score = (0.70 * hueco + 0.30 * interno) - (0.70 * penal_extrap) - penal_borde
    return _clamp(score, 0.0, 1.0)


# =========================================================
#   SELECCIÓN: Torneo (estable)
# =========================================================
def seleccion_torneo(
    poblacion: List[Tuple[float, float]],
    fitnesses: List[float],
    k_torneo: int = 4,
    n: Optional[int] = None
) -> List[Tuple[float, float]]:
    if n is None:
        n = len(poblacion)

    idxs = list(range(len(poblacion)))
    seleccionados: List[Tuple[float, float]] = []

    for _ in range(n):
        contendientes = random.sample(idxs, k=min(k_torneo, len(idxs)))
        best = max(contendientes, key=lambda i: fitnesses[i])
        seleccionados.append(poblacion[best])

    return seleccionados


# =========================================================
#   CRUZA: BLX-alpha (reales)
# =========================================================
def cruzar_blx_alpha(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    alpha: float = 0.5
) -> Tuple[float, float]:
    (x1, y1), (x2, y2) = p1, p2

    def _blx(a: float, b: float) -> float:
        lo = min(a, b)
        hi = max(a, b)
        d = hi - lo
        return random.uniform(lo - alpha * d, hi + alpha * d)

    return (_blx(x1, x2), _blx(y1, y2))


# =========================================================
#   MUTACIÓN: Gauss + clamp bbox
# =========================================================
def mutar_gauss(
    ind: Tuple[float, float],
    min_lat: float, max_lat: float,
    min_lon: float, max_lon: float,
    sigma_lat: float = 0.0007,
    sigma_lon: float = 0.0007,
    prob_mut: float = 0.25
) -> Tuple[float, float]:
    lat, lon = ind

    if random.random() < prob_mut:
        lat += random.gauss(0.0, sigma_lat)
        lon += random.gauss(0.0, sigma_lon)

    lat = _clamp(lat, min_lat, max_lat)
    lon = _clamp(lon, min_lon, max_lon)
    return (lat, lon)


# =========================================================
#   DIVERSIDAD: puntos espaciados (niching simple)
# =========================================================
def seleccionar_espaciados(
    candidatos: List[Tuple[float, float, float]],
    min_sep_m: float,
    max_puntos: int
) -> List[Tuple[float, float, float]]:
    seleccionados: List[Tuple[float, float, float]] = []

    for lat, lon, fit in candidatos:
        if len(seleccionados) >= max_puntos:
            break

        ok = True
        for slat, slon, _ in seleccionados:
            if haversine_m(lat, lon, slat, slon) < min_sep_m:
                ok = False
                break

        if ok:
            seleccionados.append((lat, lon, fit))

    # Si faltan, rellena con mejores restantes
    if len(seleccionados) < max_puntos:
        for c in candidatos:
            if len(seleccionados) >= max_puntos:
                break
            if c not in seleccionados:
                seleccionados.append(c)

    return seleccionados


# =========================================================
#   ALGORITMO GENÉTICO PRINCIPAL
# =========================================================
def algoritmo_genetico_puntos_ciegos(
    camaras: Sequence[Any],
    tam_poblacion: int = 120,
    generaciones: int = 90,
    num_puntos_resultado: int = 10,
    min_separacion_m: float = 180.0,

    # parámetros fitness
    radio_cobertura_m: float = 80.0,
    max_interes_m: float = 350.0,
    max_extrapolacion_m: float = 900.0,
    k_vecinos: int = 4,

    # GA params
    elitismo: int = 4,
    k_torneo: int = 4,
    alpha_blx: float = 0.5,

    # --- CAMBIO CLAVE ---
    # antes 0.03 era demasiado restrictivo con datasets grandes/densos
    bbox_margin_factor: float = 0.15,
) -> List[Tuple[float, float, float]]:
    if not camaras:
        return []

    # bbox “real” del conjunto
    min_lat0, max_lat0, min_lon0, max_lon0 = _bbox(camaras)

    # margen (permite explorar alrededor del conjunto)
    lat_span = max(max_lat0 - min_lat0, 1e-9)
    lon_span = max(max_lon0 - min_lon0, 1e-9)
    lat_margin = lat_span * bbox_margin_factor
    lon_margin = lon_span * bbox_margin_factor

    min_lat = min_lat0 - lat_margin
    max_lat = max_lat0 + lat_margin
    min_lon = min_lon0 - lon_margin
    max_lon = max_lon0 + lon_margin

    # población inicial
    poblacion: List[Tuple[float, float]] = [
        (random.uniform(min_lat, max_lat), random.uniform(min_lon, max_lon))
        for _ in range(tam_poblacion)
    ]

    for _ in range(generaciones):
        fitnesses = [
            fitness_punto_completo(
                ind, camaras,
                radio_cobertura_m=radio_cobertura_m,
                max_interes_m=max_interes_m,
                max_extrapolacion_m=max_extrapolacion_m,
                k_vecinos=k_vecinos,
            )
            for ind in poblacion
        ]

        # Elitismo: top-k
        orden = sorted(range(len(poblacion)), key=lambda i: fitnesses[i], reverse=True)
        elites = [poblacion[i] for i in orden[:max(1, elitismo)]]

        # Selección torneo
        padres = seleccion_torneo(poblacion, fitnesses, k_torneo=k_torneo, n=tam_poblacion)

        nueva: List[Tuple[float, float]] = []
        nueva.extend(elites)

        while len(nueva) < tam_poblacion:
            p1 = random.choice(padres)
            p2 = random.choice(padres)
            hijo = cruzar_blx_alpha(p1, p2, alpha=alpha_blx)

            hijo = mutar_gauss(
                hijo,
                min_lat=min_lat, max_lat=max_lat,
                min_lon=min_lon, max_lon=max_lon,
            )

            # --- CAMBIO CLAVE ---
            # Ya NO hacemos clamp al bbox original, porque eso mata la exploración
            # y deja al GA sin opciones si el bbox original está totalmente cubierto.
            nueva.append(hijo)

        poblacion = nueva

    # evaluación final
    fitnesses_final = [
        fitness_punto_completo(
            ind, camaras,
            radio_cobertura_m=radio_cobertura_m,
            max_interes_m=max_interes_m,
            max_extrapolacion_m=max_extrapolacion_m,
            k_vecinos=k_vecinos,
        )
        for ind in poblacion
    ]

    candidatos = [(lat, lon, fit) for (lat, lon), fit in zip(poblacion, fitnesses_final)]
    candidatos.sort(key=lambda x: x[2], reverse=True)

    # diversidad para no amontonarse
    return seleccionar_espaciados(candidatos, min_sep_m=min_separacion_m, max_puntos=num_puntos_resultado)
