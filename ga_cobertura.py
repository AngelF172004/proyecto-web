# backend/ga_cobertura.py
from __future__ import annotations

from typing import Any, List, Tuple, Sequence, Optional, Dict
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


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _get_lat_lon(obj: Any) -> Tuple[float, float]:
    """Soporta ORM con .latitud/.longitud o tuplas (lat, lon)."""
    if hasattr(obj, "latitud") and hasattr(obj, "longitud"):
        return float(obj.latitud), float(obj.longitud)
    return float(obj[0]), float(obj[1])


def _bbox(camaras: Sequence[Any]) -> Tuple[float, float, float, float]:
    pts = [_get_lat_lon(c) for c in camaras]
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return min(lats), max(lats), min(lons), max(lons)


# =========================================================
#   GRID DE EVALUACIÓN (puntos dentro del bbox)
# =========================================================
def generar_grid_puntos(
    camaras: Sequence[Any],
    step_m: float = 150.0,
    margin_factor: float = 0.05,
    max_points: int = 6000,
) -> List[Tuple[float, float]]:
    """
    Genera puntos (lat, lon) en una rejilla sobre el bbox de cámaras.
    step_m = separación aproximada entre puntos en metros.
    max_points limita la cantidad final (si se excede, se submuestrea).
    """
    if not camaras:
        return []

    min_lat, max_lat, min_lon, max_lon = _bbox(camaras)

    lat_span = max(max_lat - min_lat, 1e-9)
    lon_span = max(max_lon - min_lon, 1e-9)
    min_lat -= lat_span * margin_factor
    max_lat += lat_span * margin_factor
    min_lon -= lon_span * margin_factor
    max_lon += lon_span * margin_factor

    mid_lat = (min_lat + max_lat) / 2.0
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * cos(radians(mid_lat))

    step_lat = step_m / m_per_deg_lat
    step_lon = step_m / max(m_per_deg_lon, 1e-6)

    pts: List[Tuple[float, float]] = []
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            pts.append((float(lat), float(lon)))
            lon += step_lon
        lat += step_lat

    if max_points and len(pts) > max_points:
        pts = random.sample(pts, k=max_points)

    return pts


# =========================================================
#   COBERTURA Y NIVELES
# =========================================================
def contar_cobertura_en_punto(
    punto: Tuple[float, float],
    camaras: Sequence[Tuple[float, float]],
    radio_m: float,
) -> int:
    lat, lon = punto
    count = 0
    for clat, clon in camaras:
        if haversine_m(lat, lon, clat, clon) <= radio_m:
            count += 1
    return count


def metricas_niveles_cobertura(
    puntos_eval: Sequence[Tuple[float, float]],
    camaras_totales: Sequence[Tuple[float, float]],
    radio_m: float,
) -> Dict[str, float]:
    if not puntos_eval:
        return {
            "cobertura_total": 0.0,
            "sin_cobertura": 100.0,
            "nivel_1": 0.0,
            "nivel_2": 0.0,
            "nivel_3_mas": 0.0,
        }

    n = len(puntos_eval)
    c0 = c1 = c2 = c3 = 0

    for p in puntos_eval:
        k = contar_cobertura_en_punto(p, camaras_totales, radio_m)
        if k <= 0:
            c0 += 1
        elif k == 1:
            c1 += 1
        elif k == 2:
            c2 += 1
        else:
            c3 += 1

    sin_cob = (c0 / n) * 100.0
    cov_total = 100.0 - sin_cob

    return {
        "cobertura_total": cov_total,
        "sin_cobertura": sin_cob,
        "nivel_1": (c1 / n) * 100.0,
        "nivel_2": (c2 / n) * 100.0,
        "nivel_3_mas": (c3 / n) * 100.0,
    }


# =========================================================
#   PENALIZACIÓN: cámaras demasiado cercanas
# =========================================================
def _penalizar_camaras_muy_cercanas(
    camaras_nuevas: Sequence[Tuple[float, float]],
    camaras_existentes: Sequence[Tuple[float, float]],
    min_dist_entre_nuevas_m: float,
    min_dist_a_existentes_m: float,
    peso_penalizacion: float,
) -> float:
    pen = 0.0

    # nuevas vs nuevas
    n = len(camaras_nuevas)
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_m(
                camaras_nuevas[i][0], camaras_nuevas[i][1],
                camaras_nuevas[j][0], camaras_nuevas[j][1],
            )
            if d < min_dist_entre_nuevas_m:
                pen += peso_penalizacion * (1.0 - (d / max(min_dist_entre_nuevas_m, 1e-6)))

    # nuevas vs existentes
    if min_dist_a_existentes_m > 0:
        for (lat, lon) in camaras_nuevas:
            dmin = None
            for (elat, elon) in camaras_existentes:
                d = haversine_m(lat, lon, elat, elon)
                if dmin is None or d < dmin:
                    dmin = d
            if dmin is not None and dmin < min_dist_a_existentes_m:
                pen += (peso_penalizacion * 0.75) * (1.0 - (dmin / max(min_dist_a_existentes_m, 1e-6)))

    return pen


# =========================================================
#   REPAIR: reubica puntos si violan distancias mínimas
# =========================================================
def _repair_separacion(
    ind: List[Tuple[float, float]],
    camaras_existentes: Sequence[Tuple[float, float]],
    min_lat: float, max_lat: float, min_lon: float, max_lon: float,
    min_dist_entre_nuevas_m: float,
    min_dist_a_existentes_m: float,
    max_iters: int = 35,
) -> List[Tuple[float, float]]:
    """
    Repair más robusto:
    - Trabaja sobre el bbox ampliado (min_lat/max_lat etc.)
    - Si no logra reparar en N iters, devuelve lo mejor que tenga (no se atora).
    """
    out = list(ind)

    for _ in range(max_iters):
        changed = False

        # contra existentes
        if min_dist_a_existentes_m > 0:
            for i, (lat, lon) in enumerate(out):
                too_close = False
                for (elat, elon) in camaras_existentes:
                    if haversine_m(lat, lon, elat, elon) < min_dist_a_existentes_m:
                        too_close = True
                        break
                if too_close:
                    out[i] = (
                        random.uniform(min_lat, max_lat),
                        random.uniform(min_lon, max_lon),
                    )
                    changed = True

        # nuevas vs nuevas
        n = len(out)
        for i in range(n):
            for j in range(i + 1, n):
                d = haversine_m(out[i][0], out[i][1], out[j][0], out[j][1])
                if d < min_dist_entre_nuevas_m:
                    out[j] = (
                        random.uniform(min_lat, max_lat),
                        random.uniform(min_lon, max_lon),
                    )
                    changed = True

        if not changed:
            break

    out = [(_clamp(a, min_lat, max_lat), _clamp(b, min_lon, max_lon)) for (a, b) in out]
    return out


# =========================================================
#   FITNESS (eficiencia de cobertura)
# =========================================================
def fitness_cobertura(
    puntos_eval: Sequence[Tuple[float, float]],
    camaras_existentes: Sequence[Tuple[float, float]],
    camaras_nuevas: Sequence[Tuple[float, float]],
    radio_m: float,
    penalizar_sobrecobertura: bool = True,
    peso_sobrecobertura: float = 0.15,

    # separación mínima
    penalizar_cercania: bool = True,
    min_dist_entre_nuevas_m: float = 180.0,
    min_dist_a_existentes_m: float = 60.0,
    peso_cercania: float = 10.0,  # <- un poco menos agresivo
) -> float:
    cam_tot = list(camaras_existentes) + list(camaras_nuevas)
    met = metricas_niveles_cobertura(puntos_eval, cam_tot, radio_m)

    # Base: cobertura total (0..100)
    score = met["cobertura_total"]

    # Penaliza sobrecobertura alta (3+ cámaras cubriendo el mismo punto)
    if penalizar_sobrecobertura:
        score -= peso_sobrecobertura * met["nivel_3_mas"]

    # Penaliza cercanías excesivas (para no amontonarlas)
    if penalizar_cercania and camaras_nuevas:
        score -= _penalizar_camaras_muy_cercanas(
            camaras_nuevas=camaras_nuevas,
            camaras_existentes=camaras_existentes,
            min_dist_entre_nuevas_m=min_dist_entre_nuevas_m,
            min_dist_a_existentes_m=min_dist_a_existentes_m,
            peso_penalizacion=peso_cercania,
        )

    return _clamp(score, 0.0, 100.0)


# =========================================================
#   GA: selección torneo + cruza BLX + mutación gauss
# =========================================================
def _seleccion_torneo(
    poblacion: List[List[Tuple[float, float]]],
    fitnesses: List[float],
    k: int = 4,
    n: Optional[int] = None,
) -> List[List[Tuple[float, float]]]:
    if n is None:
        n = len(poblacion)

    idxs = list(range(len(poblacion)))
    out: List[List[Tuple[float, float]]] = []

    for _ in range(n):
        contendientes = random.sample(idxs, k=min(k, len(idxs)))
        best = max(contendientes, key=lambda i: fitnesses[i])
        out.append(poblacion[best])

    return out


def _blx(a: float, b: float, alpha: float) -> float:
    lo = min(a, b)
    hi = max(a, b)
    d = hi - lo
    return random.uniform(lo - alpha * d, hi + alpha * d)


def _cruzar_individuo_blx(
    p1: List[Tuple[float, float]],
    p2: List[Tuple[float, float]],
    alpha: float = 0.5,
) -> List[Tuple[float, float]]:
    n = min(len(p1), len(p2))
    hijo: List[Tuple[float, float]] = []
    for i in range(n):
        lat = _blx(p1[i][0], p2[i][0], alpha)
        lon = _blx(p1[i][1], p2[i][1], alpha)
        hijo.append((lat, lon))
    return hijo


def _mutar_individuo_gauss(
    ind: List[Tuple[float, float]],
    min_lat: float, max_lat: float,
    min_lon: float, max_lon: float,
    prob_mut: float = 0.35,
    sigma_lat: float = 0.0007,
    sigma_lon: float = 0.0007,
) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for lat, lon in ind:
        if random.random() < prob_mut:
            lat += random.gauss(0.0, sigma_lat)
            lon += random.gauss(0.0, sigma_lon)
        lat = _clamp(lat, min_lat, max_lat)
        lon = _clamp(lon, min_lon, max_lon)
        out.append((lat, lon))
    return out


# =========================================================
#   ALGORITMO GENÉTICO: proponiendo N cámaras nuevas
# =========================================================
def algoritmo_genetico_mejorar_cobertura(
    camaras_existentes_in: Sequence[Any],
    n_camaras_nuevas: int = 5,
    radio_m: float = 120.0,

    puntos_eval: Optional[Sequence[Tuple[float, float]]] = None,
    step_grid_m: float = 150.0,
    grid_max_points: int = 6000,

    tam_poblacion: int = 80,
    generaciones: int = 80,
    elitismo: int = 3,
    k_torneo: int = 4,
    alpha_blx: float = 0.5,

    # --- CAMBIO CLAVE ---
    # 0.02 era muy pequeño (no explora). Ahora es más realista para proponer.
    bbox_margin_factor: float = 0.12,

    penalizar_sobrecobertura: bool = True,

    # separación
    penalizar_cercania: bool = True,
    min_dist_entre_nuevas_m: float = 180.0,
    min_dist_a_existentes_m: float = 60.0,
    peso_cercania: float = 10.0,

    # semillas (ej. puntos ciegos)
    puntos_semilla: Optional[Sequence[Tuple[float, float]]] = None,
    prob_usar_semilla: float = 0.60,
) -> Dict[str, Any]:
    if not camaras_existentes_in:
        return {"camaras_nuevas": [], "fitness": 0.0, "metricas": {}}

    camaras_existentes = [_get_lat_lon(c) for c in camaras_existentes_in]

    # Puntos de evaluación (grid)
    if puntos_eval is None:
        puntos_eval = generar_grid_puntos(
            camaras_existentes,
            step_m=step_grid_m,
            margin_factor=0.06,
            max_points=grid_max_points
        )

    # Fallback si el grid quedó raro
    if not puntos_eval:
        puntos_eval = [(lat, lon) for (lat, lon) in random.sample(camaras_existentes, k=min(200, len(camaras_existentes)))]

    min_lat0, max_lat0, min_lon0, max_lon0 = _bbox(camaras_existentes)

    lat_span = max(max_lat0 - min_lat0, 1e-9)
    lon_span = max(max_lon0 - min_lon0, 1e-9)

    # bbox ampliado coherente para búsqueda
    min_lat = min_lat0 - lat_span * bbox_margin_factor
    max_lat = max_lat0 + lat_span * bbox_margin_factor
    min_lon = min_lon0 - lon_span * bbox_margin_factor
    max_lon = max_lon0 + lon_span * bbox_margin_factor

    semillas = list(puntos_semilla or [])
    # semillas también se clamp-ean al bbox ampliado
    semillas = [(_clamp(a, min_lat, max_lat), _clamp(b, min_lon, max_lon)) for (a, b) in semillas]

    def _crear_individuo() -> List[Tuple[float, float]]:
        ind: List[Tuple[float, float]] = []

        # usa semillas si hay
        if semillas and random.random() < prob_usar_semilla:
            take = min(len(semillas), n_camaras_nuevas)
            ind.extend(random.sample(semillas, k=take))

        # completa aleatorio dentro bbox ampliado
        while len(ind) < n_camaras_nuevas:
            ind.append((random.uniform(min_lat, max_lat), random.uniform(min_lon, max_lon)))

        # clamp coherente al bbox ampliado
        ind = [(_clamp(a, min_lat, max_lat), _clamp(b, min_lon, max_lon)) for (a, b) in ind]

        if penalizar_cercania:
            ind = _repair_separacion(
                ind,
                camaras_existentes=camaras_existentes,
                min_lat=min_lat, max_lat=max_lat,
                min_lon=min_lon, max_lon=max_lon,
                min_dist_entre_nuevas_m=min_dist_entre_nuevas_m,
                min_dist_a_existentes_m=min_dist_a_existentes_m,
            )
        return ind

    poblacion: List[List[Tuple[float, float]]] = [_crear_individuo() for _ in range(tam_poblacion)]

    best_ind: List[Tuple[float, float]] = []
    best_fit: float = -1.0

    for _ in range(generaciones):
        fitnesses: List[float] = []

        for ind in poblacion:
            fit = fitness_cobertura(
                puntos_eval=puntos_eval,
                camaras_existentes=camaras_existentes,
                camaras_nuevas=ind,
                radio_m=radio_m,
                penalizar_sobrecobertura=penalizar_sobrecobertura,
                penalizar_cercania=penalizar_cercania,
                min_dist_entre_nuevas_m=min_dist_entre_nuevas_m,
                min_dist_a_existentes_m=min_dist_a_existentes_m,
                peso_cercania=peso_cercania,
            )
            fitnesses.append(_clamp(fit, 0.0, 100.0))

        i_best = max(range(len(poblacion)), key=lambda i: fitnesses[i])
        if fitnesses[i_best] > best_fit:
            best_fit = fitnesses[i_best]
            best_ind = poblacion[i_best]

        # elites
        orden = sorted(range(len(poblacion)), key=lambda i: fitnesses[i], reverse=True)
        elites = [poblacion[i] for i in orden[:max(1, elitismo)]]

        padres = _seleccion_torneo(poblacion, fitnesses, k=k_torneo, n=tam_poblacion)

        nueva: List[List[Tuple[float, float]]] = []
        nueva.extend(elites)

        while len(nueva) < tam_poblacion:
            p1 = random.choice(padres)
            p2 = random.choice(padres)
            hijo = _cruzar_individuo_blx(p1, p2, alpha=alpha_blx)
            hijo = _mutar_individuo_gauss(
                hijo,
                min_lat=min_lat, max_lat=max_lat,
                min_lon=min_lon, max_lon=max_lon,
            )
            hijo = [(_clamp(a, min_lat, max_lat), _clamp(b, min_lon, max_lon)) for (a, b) in hijo]

            if penalizar_cercania:
                hijo = _repair_separacion(
                    hijo,
                    camaras_existentes=camaras_existentes,
                    min_lat=min_lat, max_lat=max_lat,
                    min_lon=min_lon, max_lon=max_lon,
                    min_dist_entre_nuevas_m=min_dist_entre_nuevas_m,
                    min_dist_a_existentes_m=min_dist_a_existentes_m,
                )

            nueva.append(hijo)

        poblacion = nueva

    cam_tot = list(camaras_existentes) + list(best_ind)
    met = metricas_niveles_cobertura(puntos_eval, cam_tot, radio_m)

    return {
        "camaras_nuevas": [(float(a), float(b)) for (a, b) in best_ind],
        "fitness": float(best_fit),
        "metricas": {k: float(v) for k, v in met.items()},
    }
