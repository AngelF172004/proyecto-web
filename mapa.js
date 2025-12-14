// /js/mapa.js
document.addEventListener("DOMContentLoaded", () => {
  const mapElement = document.getElementById("map");
  if (!mapElement) return;

  if (typeof L === "undefined") {
    console.error("Leaflet no está cargado.");
    return;
  }

  // =========================
  // Configuración base
  // =========================
  const DEFAULT_COVERAGE_RADIUS_M = 120;

  const REAL_CAM_COLOR = "#3b82f6";

  // Colores por cobertura
  const COV_100_COLOR = "#22c55e";   // 100%
  const COV_80_99_COLOR = "#a855f7"; // 80–99
  const COV_50_79_COLOR = "#38bdf8"; // 50–79
  const COV_LOW_COLOR = "#f59e0b";   // <50
  const COV_NOT_EVALUATED = "#64748b"; // gris

  const GA_COLOR = "#facc15";

  // =========================
  // Crear mapa
  // =========================
  const map = L.map(mapElement, {
    zoomControl: true,
    preferCanvas: true,
  }).setView([19.4326, -99.1332], 12);

  // =========================
  // Tiles
  // =========================
  const tilesVoyager = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    {
      maxZoom: 20,
      subdomains: "abcd",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
        '&copy; <a href="https://carto.com/attributions">CARTO</a>',
    }
  );

  const tilesPositron = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png",
    {
      maxZoom: 20,
      subdomains: "abcd",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
        '&copy; <a href="https://carto.com/attributions">CARTO</a>',
    }
  );

  const tilesOSM = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  });

  tilesVoyager.addTo(map);

  L.control
    .layers(
      {
        "CARTO Voyager (calles + labels)": tilesVoyager,
        "CARTO Positron (claro)": tilesPositron,
        "OSM Standard": tilesOSM,
      },
      null,
      { position: "topleft" }
    )
    .addTo(map);

  const fallbackTo = (layer) => {
    if (!map.hasLayer(layer)) layer.addTo(map);
  };

  tilesVoyager.on("tileerror", () => {
    console.warn("Falló CARTO Voyager. Cambiando a CARTO Positron.");
    if (map.hasLayer(tilesVoyager)) map.removeLayer(tilesVoyager);
    fallbackTo(tilesPositron);
  });

  tilesPositron.on("tileerror", () => {
    console.warn("Falló CARTO Positron. Cambiando a OSM.");
    if (map.hasLayer(tilesPositron)) map.removeLayer(tilesPositron);
    fallbackTo(tilesOSM);
  });

  setTimeout(() => map.invalidateSize(true), 250);

  // =========================
  // Capas
  // =========================
  const camarasLayer = L.layerGroup().addTo(map);
  const simulatedLayer = L.layerGroup().addTo(map);
  const blindSpotLayer = L.layerGroup().addTo(map);
  const gaCoverageLayer = L.layerGroup().addTo(map);

  // =========================
  // Estado
  // =========================
  let simulatedCameras = []; // {latitud, longitud, coverage?}
  let busy = {
    evaluar: false,
    gaCobertura: false,
    gaPuntos: false,
    guardar: false,
  };

  // =========================
  // UI
  // =========================
  const simulatedList = document.getElementById("simulated-cameras-list");
  const blindSpotsList = document.getElementById("blind-spots-list");
  const gaMetricsBox = document.getElementById("ga-metrics");

  const btnClearSimulated = document.getElementById("btn-clear-simulated");
  const btnSaveGoodSimulated = document.getElementById("btn-save-good-simulated");
  const btnEvaluarSimulated = document.getElementById("btn-evaluar-simulated");
  const btnDetectBlindSpots = document.getElementById("btn-ag-puntos");
  const btnGACobertura = document.getElementById("btn-ga-cobertura");

  // =========================
  // Toast / Status UI (no bloquea como alert)
  // =========================
  const toast = (() => {
    const el = document.createElement("div");
    el.style.position = "fixed";
    el.style.right = "18px";
    el.style.bottom = "18px";
    el.style.zIndex = "9999";
    el.style.padding = "12px 14px";
    el.style.borderRadius = "12px";
    el.style.background = "rgba(15, 23, 42, 0.92)";
    el.style.color = "#fff";
    el.style.fontSize = "14px";
    el.style.maxWidth = "360px";
    el.style.boxShadow = "0 10px 30px rgba(0,0,0,.35)";
    el.style.display = "none";
    el.style.pointerEvents = "none";
    document.body.appendChild(el);

    let t = null;
    function show(msg, ms = 2400) {
      el.textContent = msg;
      el.style.display = "block";
      clearTimeout(t);
      t = setTimeout(() => (el.style.display = "none"), ms);
    }
    return { show };
  })();

  function setBtnLoading(btn, isLoading, textLoading = "Procesando...") {
    if (!btn) return;
    if (!btn.dataset.originalText) btn.dataset.originalText = btn.textContent || "";
    btn.disabled = !!isLoading;
    btn.style.opacity = isLoading ? "0.75" : "1";
    btn.style.cursor = isLoading ? "not-allowed" : "pointer";
    if (isLoading) btn.textContent = textLoading;
    else btn.textContent = btn.dataset.originalText;
  }

  // =========================
  // Fetch helper (robusto)
  // =========================
  async function apiFetch(url, options = {}, timeoutMs = 30000) {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const resp = await fetch(url, {
        ...options,
        signal: controller.signal,
        cache: "no-store",
        credentials: "include",
      });
      return resp;
    } catch (err) {
      // Timeout / Abort
      if (err && (err.name === "AbortError" || String(err).includes("AbortError"))) {
        console.warn("Timeout/Abort en:", url);
        toast.show("Se tardó demasiado y se canceló. Intenta otra vez o reduce parámetros.", 3500);
        return null;
      }
      console.error("Error de red real:", err);
      toast.show("No se pudo conectar con el servidor.", 3500);
      return null;
    } finally {
      clearTimeout(t);
    }
  }

  async function checkBackendUp() {
    const resp = await apiFetch("/api/health", {}, 2500);
    if (!resp || !resp.ok) return false;
    return true;
  }

  // =========================
  // FitBounds inteligente
  // =========================
  function isInCDMXBox(lat, lng) {
    return lat >= 19.0 && lat <= 19.95 && lng >= -99.85 && lng <= -98.70;
  }

  function fitToCoords(coords) {
    if (!Array.isArray(coords) || coords.length === 0) return;

    const filtered = coords.filter(([lat, lng]) =>
      Number.isFinite(lat) && Number.isFinite(lng) && isInCDMXBox(lat, lng)
    );

    const useCoords = filtered.length >= 5 ? filtered : coords;
    const bounds = L.latLngBounds(useCoords);
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
  }

  // =========================
  // Colores por cobertura
  // =========================
  function colorPorCobertura(cov) {
    if (!Number.isFinite(cov)) return COV_NOT_EVALUATED;
    if (cov >= 100) return COV_100_COLOR;
    if (cov >= 80) return COV_80_99_COLOR;
    if (cov >= 50) return COV_50_79_COLOR;
    return COV_LOW_COLOR;
  }

  // =========================
  // Render UI
  // =========================
  function renderSimulatedList() {
    if (!simulatedList) return;

    if (!simulatedCameras.length) {
      simulatedList.innerHTML =
        `<li class="sim-empty">No hay cámaras propuestas. Da click en el mapa para agregar.</li>`;
      return;
    }

    simulatedList.innerHTML = "";
    simulatedCameras.forEach((c, idx) => {
      const lat = Number(c.latitud);
      const lng = Number(c.longitud);
      const cov = typeof c.coverage === "number" ? `${c.coverage.toFixed(2)} %` : "No evaluada";

      const li = document.createElement("li");
      li.className = "sim-item";
      li.innerHTML = `
        <div class="sim-item-main">
          <div class="sim-item-title">Propuesta ${idx + 1}</div>
          <div class="sim-item-subtitle">Cobertura: ${cov}</div>
          <div class="sim-item-coords">(${lat.toFixed(5)}, ${lng.toFixed(5)})</div>
        </div>
        <button class="sim-item-del" title="Eliminar">×</button>
      `;

      li.querySelector(".sim-item-main")?.addEventListener("click", () => {
        map.flyTo([lat, lng], 17);
      });

      li.querySelector(".sim-item-del")?.addEventListener("click", (e) => {
        e.stopPropagation();
        removeSimulatedAt(idx);
      });

      simulatedList.appendChild(li);
    });
  }

  function renderBlindSpotsList(puntos) {
    if (!blindSpotsList) return;

    if (!Array.isArray(puntos) || puntos.length === 0) {
      blindSpotsList.innerHTML =
        `<li class="sim-empty">No hay puntos ciegos detectados en esta ejecución.</li>`;
      return;
    }

    blindSpotsList.innerHTML = "";
    puntos.forEach((p, idx) => {
      const lat = Number(p.latitud);
      const lng = Number(p.longitud);
      const fitness = typeof p.fitness === "number" ? p.fitness.toFixed(2) : "—";

      const li = document.createElement("li");
      li.className = "sim-item";
      li.innerHTML = `
        <div class="sim-item-main">
          <div class="sim-item-title">Punto ciego ${idx + 1}</div>
          <div class="sim-item-subtitle">Fitness: ${fitness}</div>
          <div class="sim-item-coords">(${lat.toFixed(5)}, ${lng.toFixed(5)})</div>
        </div>
      `;

      li.addEventListener("click", () => {
        if (Number.isFinite(lat) && Number.isFinite(lng)) map.flyTo([lat, lng], 17);
      });

      blindSpotsList.appendChild(li);
    });
  }

  function renderGAMetricsBox(result) {
    if (!gaMetricsBox) return;

    if (!result || !result.metricas) {
      gaMetricsBox.innerHTML =
        `<div class="legend-note legend-note-small">No hay métricas disponibles.</div>`;
      return;
    }

    const m = result.metricas;
    const pct = (v) => (typeof v === "number" ? `${v.toFixed(2)} %` : "—");

    gaMetricsBox.innerHTML = `
      <div style="margin-top:10px;">
        <div class="legend-note"><strong>Resultado AG de cobertura</strong></div>
        <div class="legend-note legend-note-small">
          Fitness global: <strong>${(result.fitness ?? 0).toFixed(2)}</strong>
        </div>
        <ul class="map-legend-list" style="margin-top:8px;">
          <li><strong>Cobertura total:</strong> ${pct(m.cobertura_total)}</li>
          <li><strong>Sin cobertura:</strong> ${pct(m.sin_cobertura)}</li>
          <li><strong>Nivel 1 (1 cámara):</strong> ${pct(m.nivel_1)}</li>
          <li><strong>Nivel 2 (2 cámaras):</strong> ${pct(m.nivel_2)}</li>
          <li><strong>Nivel 3+ (3 o más):</strong> ${pct(m.nivel_3_mas)}</li>
        </ul>
        <div class="legend-note legend-note-small">
          Propuestas AG (amarillo): ${Array.isArray(result.camaras_nuevas) ? result.camaras_nuevas.length : 0}
        </div>
      </div>
    `;
  }

  // =========================
  // Cámaras reales
  // =========================
  async function cargarCamarasReales() {
    camarasLayer.clearLayers();

    const resp = await apiFetch("/api/camaras", {}, 12000);
    if (!resp) return;

    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      console.error("Error /api/camaras:", resp.status, text);
      toast.show("Error cargando cámaras reales.");
      return;
    }

    const camaras = await resp.json().catch(() => []);
    if (!Array.isArray(camaras) || camaras.length === 0) return;

    const coords = [];

    camaras.forEach((cam) => {
      const lat = Number(cam.latitud);
      const lng = Number(cam.longitud);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

      coords.push([lat, lng]);

      const marker = L.circleMarker([lat, lng], {
        radius: 5,
        color: REAL_CAM_COLOR,
        fillColor: REAL_CAM_COLOR,
        fillOpacity: 0.9,
        weight: 1,
      }).addTo(camarasLayer);

      L.circle([lat, lng], {
        radius: DEFAULT_COVERAGE_RADIUS_M,
        color: REAL_CAM_COLOR,
        fillColor: REAL_CAM_COLOR,
        fillOpacity: 0.15,
        weight: 1,
      }).addTo(camarasLayer);

      marker.bindPopup(`
        <strong>Cámara ID:</strong> ${cam.id ?? "-"}<br/>
        Lat: ${lat.toFixed(5)}<br/>
        Lng: ${lng.toFixed(5)}<br/>
        Tipo: ${cam.tipo ?? "-"}<br/>
        ${cam.descripcion ? `Desc: ${cam.descripcion}` : ""}
      `);
    });

    if (coords.length > 0) {
      fitToCoords(coords);
      setTimeout(() => map.invalidateSize(true), 100);
    }
  }

  // =========================
  // Manual: propuestas
  // =========================
  function redrawSimulatedLayer() {
    simulatedLayer.clearLayers();

    simulatedCameras.forEach((c) => {
      const lat = Number(c.latitud);
      const lng = Number(c.longitud);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

      const color = colorPorCobertura(c.coverage);

      const marker = L.circleMarker([lat, lng], {
        radius: 7,
        color,
        fillColor: color,
        fillOpacity: 0.95,
        weight: 2,
      }).addTo(simulatedLayer);

      L.circle([lat, lng], {
        radius: DEFAULT_COVERAGE_RADIUS_M,
        color,
        fillColor: color,
        fillOpacity: 0.12,
        weight: 1,
      }).addTo(simulatedLayer);

      const covTxt = typeof c.coverage === "number" ? `${c.coverage.toFixed(2)} %` : "No evaluada";
      marker.bindPopup(
        `<strong>Cámara propuesta</strong>
         <br/>Cobertura: ${covTxt}
         <br/>(${lat.toFixed(5)}, ${lng.toFixed(5)})`
      );
    });

    renderSimulatedList();
  }

  function addSimulatedCamera(lat, lng) {
    simulatedCameras.push({ latitud: lat, longitud: lng, coverage: null });
    redrawSimulatedLayer();
  }

  function clearSimulated() {
    simulatedCameras = [];
    simulatedLayer.clearLayers();
    renderSimulatedList();
  }

  function removeSimulatedAt(index) {
    simulatedCameras.splice(index, 1);
    redrawSimulatedLayer();
  }

  // Evita clicks accidentales si está en proceso pesado
  map.on("click", (e) => {
    addSimulatedCamera(e.latlng.lat, e.latlng.lng);
  });

  // =========================
  // Evaluar (porcentaje) - rápido + evita spam
  // =========================
  async function evaluarUltimaPropuesta() {
    if (busy.evaluar) return;
    if (!simulatedCameras.length) {
      toast.show("Agrega una cámara dando click en el mapa.");
      return;
    }

    // Backend up?
    const ok = await checkBackendUp();
    if (!ok) {
      toast.show("Backend no disponible. Asegura uvicorn corriendo en :8000.");
      return;
    }

    busy.evaluar = true;
    setBtnLoading(btnEvaluarSimulated, true, "Evaluando...");

    try {
      const last = simulatedCameras[simulatedCameras.length - 1];

      // Marcamos como "no evaluada" antes (y redibujamos)
      last.coverage = null;
      redrawSimulatedLayer();

      const resp = await apiFetch(
        "/api/cobertura/camara-simulada",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ latitud: last.latitud, longitud: last.longitud }),
        },
        45000
      );

      if (!resp) return;

      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        console.error("Error /api/cobertura/camara-simulada:", resp.status, text);
        toast.show("Error evaluando cobertura. Revisa consola.");
        return;
      }

      const data = await resp.json().catch(() => ({}));
      const raw = data.coverage ?? data.cobertura ?? data.porcentaje ?? data.coverage_pct ?? data.coveragePercent;
      const cov = Number(raw);

      if (!Number.isFinite(cov)) {
        console.warn("Respuesta backend inválida:", data);
        toast.show("Respuesta inválida del servidor (no llegó cobertura numérica).");
        return;
      }

      // ✅ aquí sí cambia el color: coverage queda numérico
      last.coverage = cov;
      redrawSimulatedLayer();

      const delta = Number(data.delta);
      if (Number.isFinite(delta)) {
        toast.show(`Cobertura: ${cov.toFixed(2)}% | Mejora: ${delta.toFixed(2)}%`, 3500);
      } else {
        toast.show(`Cobertura: ${cov.toFixed(2)}%`, 2800);
      }
    } finally {
      busy.evaluar = false;
      setBtnLoading(btnEvaluarSimulated, false);
    }
  }

  // =========================
  // Guardar buenas (>=80) - evita spam
  // =========================
  async function guardarBuenas() {
    if (busy.guardar) return;

    const buenas = simulatedCameras
      .filter((c) => typeof c.coverage === "number" && c.coverage >= 80)
      .map((c) => ({
        latitud: c.latitud,
        longitud: c.longitud,
        cobertura: c.coverage,
        origen: "simulacion",
        descripcion: "Propuesta manual",
      }));

    if (!buenas.length) {
      toast.show("No hay cámaras >= 80%. Evalúa primero.");
      return;
    }

    const ok = await checkBackendUp();
    if (!ok) {
      toast.show("Backend no disponible.");
      return;
    }

    busy.guardar = true;
    setBtnLoading(btnSaveGoodSimulated, true, "Guardando...");

    try {
      const resp = await apiFetch("/api/camaras-propuestas/guardar-buenas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camaras: buenas }),
      }, 45000);

      if (!resp) return;

      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        console.error("Error guardar-buenas:", resp.status, text);
        toast.show("No se pudieron guardar las cámaras.");
        return;
      }

      toast.show(`Guardadas: ${buenas.length} cámaras (>= 80%).`, 3200);
    } finally {
      busy.guardar = false;
      setBtnLoading(btnSaveGoodSimulated, false);
    }
  }

  // =========================
  // GA 1 – Puntos ciegos (evita spam)
  // =========================
  async function ejecutarAGPuntosCiegos() {
    if (busy.gaPuntos) return;

    const ok = await checkBackendUp();
    if (!ok) {
      toast.show("Backend no disponible.");
      return;
    }

    busy.gaPuntos = true;
    setBtnLoading(btnDetectBlindSpots, true, "Buscando puntos...");

    try {
      const resp = await apiFetch("/api/ag/puntos-ciegos", {}, 90000);
      if (!resp) return;

      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        console.error("Error /api/ag/puntos-ciegos:", resp.status, text);
        toast.show("Error ejecutando AG de puntos ciegos.");
        return;
      }

      const puntos = await resp.json().catch(() => []);
      blindSpotLayer.clearLayers();

      if (!Array.isArray(puntos) || puntos.length === 0) {
        renderBlindSpotsList([]);
        toast.show("No se encontraron puntos ciegos en esta ejecución.");
        return;
      }

      puntos.forEach((p, idx) => {
        const lat = Number(p.latitud);
        const lng = Number(p.longitud);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

        const marker = L.circleMarker([lat, lng], {
          radius: 7,
          color: "#6b7280",
          fillColor: "#9ca3af",
          fillOpacity: 0.9,
          weight: 1.5,
        }).addTo(blindSpotLayer);

        const fit = typeof p.fitness === "number" ? p.fitness.toFixed(2) : "—";
        marker.bindPopup(`<strong>Punto ciego ${idx + 1}</strong><br/>Fitness: ${fit}`);
      });

      renderBlindSpotsList(puntos);
      toast.show(`Puntos ciegos: ${puntos.length}`, 2800);
    } finally {
      busy.gaPuntos = false;
      setBtnLoading(btnDetectBlindSpots, false);
    }
  }

  // =========================
  // GA 2 – Mejorar cobertura (evita spam + parámetros ligeros)
  // =========================
  async function ejecutarGACobertura() {
    if (busy.gaCobertura) return;

    const ok = await checkBackendUp();
    if (!ok) {
      toast.show("Backend no disponible.");
      return;
    }

    busy.gaCobertura = true;
    setBtnLoading(btnGACobertura, true, "Optimizando...");

    try {
      // Parámetros demo (rápidos)
      const payload = {
        n_camaras_nuevas: 8,
        radio_m: 120.0,
        step_grid_m: 250.0,
        grid_max_points: 1500,
        tam_poblacion: 25,
        generaciones: 20,
        elitismo: 2,
        k_torneo: 3,
        alpha_blx: 0.5,
        penalizar_sobrecobertura: true,
        penalizar_cercania: true,
      };

      const resp = await apiFetch(
        "/api/ga/mejorar-cobertura",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        120000
      );

      if (!resp) return;

      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        console.error("Error /api/ga/mejorar-cobertura:", resp.status, text);
        toast.show("Error ejecutando AG cobertura. Revisa consola.");
        return;
      }

      const data = await resp.json().catch(() => null);
      gaCoverageLayer.clearLayers();

      if (!data || !Array.isArray(data.camaras_nuevas)) {
        renderGAMetricsBox(null);
        toast.show("AG devolvió resultado inválido.");
        return;
      }

      data.camaras_nuevas.forEach((c, idx) => {
        const lat = Number(c.latitud);
        const lng = Number(c.longitud);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

        const marker = L.circleMarker([lat, lng], {
          radius: 7,
          color: GA_COLOR,
          fillColor: "#fde047",
          fillOpacity: 0.95,
          weight: 2,
        }).addTo(gaCoverageLayer);

        marker.bindPopup(`<strong>Propuesta AG cobertura ${idx + 1}</strong>`);
      });

      renderGAMetricsBox(data);
      toast.show("AG de cobertura completado.", 2800);
    } finally {
      busy.gaCobertura = false;
      setBtnLoading(btnGACobertura, false);
    }
  }

  // =========================
  // Binding
  // =========================
  function bindSafe(button, fn, label) {
    if (!button) return false;
    button.onclick = null;
    button.addEventListener("click", (e) => {
      e.preventDefault();
      fn();
    });
    console.log(`Bind OK: ${label}`, button);
    return true;
  }

  bindSafe(btnEvaluarSimulated, evaluarUltimaPropuesta, "Evaluar porcentaje");
  bindSafe(btnGACobertura, ejecutarGACobertura, "AG cobertura");
  bindSafe(btnDetectBlindSpots, ejecutarAGPuntosCiegos, "AG puntos ciegos");
  if (btnClearSimulated) bindSafe(btnClearSimulated, clearSimulated, "Quitar todas");
  if (btnSaveGoodSimulated) bindSafe(btnSaveGoodSimulated, guardarBuenas, "Guardar >=80");

  // =========================
  // Inicial
  // =========================
  renderSimulatedList();
  renderBlindSpotsList([]);
  renderGAMetricsBox(null);
  cargarCamarasReales();

  setTimeout(() => map.invalidateSize(true), 800);
});
