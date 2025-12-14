// /js/main_v2.js
// UI general (nav, modales, "auth" frontend con localStorage, tabla de cámaras en index.html)
// El mapa se maneja SOLO en /js/mapa.js

function scrollToSection(id) {
  const section = document.getElementById(id);
  if (section) section.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.addEventListener("DOMContentLoaded", () => {
  const path = (window.location.pathname || "").toLowerCase();
  const isMapaPage = path === "/mapa" || path.startsWith("/mapa/");

  // =====================================================
  // "Auth" frontend (localStorage) - utilidades compartidas
  // =====================================================
  const authActionsContainer = document.getElementById("auth-actions");

  function isFrontLoggedIn() {
    return localStorage.getItem("c5_logged_in") === "1";
  }
  function setFrontLoggedIn(isLogged) {
    if (isLogged) localStorage.setItem("c5_logged_in", "1");
    else localStorage.removeItem("c5_logged_in");
  }
  function setFrontUserName(name) {
    if (name) localStorage.setItem("c5_user_name", name);
  }
  function getFrontUserName() {
    return localStorage.getItem("c5_user_name") || "Usuario";
  }

  function renderAuthUI() {
    if (!authActionsContainer) return;

    if (!isFrontLoggedIn()) {
      authActionsContainer.innerHTML = `
        <button class="btn ghost" id="btn-login-header" type="button">Iniciar sesión</button>
        <button class="btn small primary" id="btn-register-header" type="button">Crear cuenta</button>
      `;
      return;
    }

    const nombre = getFrontUserName();
    authActionsContainer.innerHTML = `
      <span class="header-user">Hola, <strong>${nombre}</strong></span>
      <button class="btn small ghost btn-logout" id="btn-logout-header" type="button">Cerrar sesión</button>
    `;
  }

  // =====================================================
  // MODO MAPA (Opción B)
  // En /mapa NO cargamos modales, NO tabla, NO hero, NO anchors.
  // Solo header auth y logout, y dejamos que /js/mapa.js controle TODO lo demás.
  // =====================================================
  if (isMapaPage) {
    renderAuthUI();

    // Eventos mínimos solo para header
    document.addEventListener("click", (e) => {
      const el = e.target.closest("[id]");
      if (!el) return;

      // En mapa no hay modales, así que mandamos al inicio con hash
      if (el.id === "btn-login-header") {
        e.preventDefault();
        window.location.href = "/#login";
        return;
      }

      if (el.id === "btn-register-header") {
        e.preventDefault();
        window.location.href = "/#register";
        return;
      }

      if (el.id === "btn-logout-header") {
        e.preventDefault();
        fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
        setFrontLoggedIn(false);
        localStorage.removeItem("c5_user_name");
        renderAuthUI();
        // recarga suave para que el mapa siga sin romperse
        window.location.reload();
        return;
      }
    });

    // IMPORTANTE: salimos aquí para NO interferir con los botones del mapa
    return;
  }

  // =====================================================
  // A PARTIR DE AQUÍ: SOLO INDEX / OTRAS PÁGINAS
  // =====================================================

  // =====================================================
  // Estadísticas dummy
  // =====================================================
  const stats = { camaras: 128, zonas: 12, alertas: 5 };
  const camarasSpan = document.getElementById("stat-camaras");
  const zonasSpan = document.getElementById("stat-zonas");
  const alertasSpan = document.getElementById("stat-alertas");
  if (camarasSpan) camarasSpan.textContent = stats.camaras;
  if (zonasSpan) zonasSpan.textContent = stats.zonas;
  if (alertasSpan) alertasSpan.textContent = stats.alertas;

  // =====================================================
  // Modales
  // =====================================================
  const modalRegister = document.getElementById("modal-register-overlay");
  const modalLogin = document.getElementById("modal-login-overlay");
  const modalSuccess = document.getElementById("modal-success-overlay");

  const closeRegister = document.getElementById("close-register");
  const closeLogin = document.getElementById("close-login");
  const closeSuccess = document.getElementById("close-success");
  const btnSuccessLogin = document.getElementById("btn-success-login");

  function openModal(modal) {
    if (modal) modal.classList.add("active");
  }
  function closeModal(modal) {
    if (modal) modal.classList.remove("active");
  }
  function showSuccessModal(message) {
    if (!modalSuccess) return;
    const text = modalSuccess.querySelector(".success-text");
    if (text && message) text.textContent = message;
    openModal(modalSuccess);
  }

  if (closeRegister) closeRegister.addEventListener("click", () => closeModal(modalRegister));
  if (closeLogin) closeLogin.addEventListener("click", () => closeModal(modalLogin));
  if (closeSuccess) closeSuccess.addEventListener("click", () => closeModal(modalSuccess));

  [modalRegister, modalLogin, modalSuccess].forEach((modal) => {
    if (!modal) return;
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal(modal);
    });
  });

  if (btnSuccessLogin) {
    btnSuccessLogin.addEventListener("click", () => {
      closeModal(modalSuccess);
      openModal(modalLogin);
    });
  }

  // =====================================================
  // Mostrar / ocultar contraseñas
  // =====================================================
  function setupPasswordToggles() {
    const toggles = document.querySelectorAll(".password-toggle");
    toggles.forEach((btn) => {
      const targetId = btn.dataset.target;
      const input = document.getElementById(targetId);
      if (!input) return;

      const iconEye = btn.querySelector(".icon-eye");
      const iconEyeOff = btn.querySelector(".icon-eye-off");

      btn.addEventListener("click", () => {
        if (input.type === "password") {
          input.type = "text";
          if (iconEye) iconEye.classList.add("hidden");
          if (iconEyeOff) iconEyeOff.classList.remove("hidden");
        } else {
          input.type = "password";
          if (iconEye) iconEye.classList.remove("hidden");
          if (iconEyeOff) iconEyeOff.classList.add("hidden");
        }
      });
    });
  }
  setupPasswordToggles();

  function goOrLogin(urlToGo) {
    if (isFrontLoggedIn()) {
      window.location.href = urlToGo;
      return;
    }
    openModal(modalLogin);
  }

  // =====================================================
  // Delegación de eventos (solo index/otras páginas)
  // =====================================================
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[id]");
    if (!el) return;

    // Header auth
    if (el.id === "btn-login-header") {
      e.preventDefault();
      openModal(modalLogin);
      return;
    }
    if (el.id === "btn-register-header") {
      e.preventDefault();
      openModal(modalRegister);
      return;
    }
    if (el.id === "btn-logout-header") {
      e.preventDefault();
      fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
      setFrontLoggedIn(false);
      localStorage.removeItem("c5_user_name");
      renderAuthUI();
      cargarCamarasTabla();
      return;
    }

    // Hero buttons
    if (el.id === "btn-ver-mapa") {
      e.preventDefault();
      goOrLogin("/mapa");
      return;
    }
    if (el.id === "btn-register-hero") {
      e.preventDefault();
      openModal(modalRegister);
      return;
    }

    // Anchors nav (#camaras, #reportes, etc.)
    if (el.classList.contains("nav-link")) {
      const href = el.getAttribute("href") || "";
      if (href.startsWith("#")) {
        const targetId = href.substring(1);
        const section = document.getElementById(targetId);
        if (section) {
          e.preventDefault();
          scrollToSection(targetId);
          document.querySelectorAll(".main-nav .nav-link").forEach((l) => l.classList.remove("active"));
          el.classList.add("active");
        }
      }
    }
  });

  // =====================================================
  // Auto abrir modales por hash
  // =====================================================
  const hash = (window.location.hash || "").toLowerCase();
  if (hash === "#login") openModal(modalLogin);
  if (hash === "#register") openModal(modalRegister);

  // =====================================================
  // Registro (backend A)
  // =====================================================
  const formRegister = document.getElementById("form-register");
  if (formRegister) {
    formRegister.addEventListener("submit", async (e) => {
      e.preventDefault();

      const data = {
        nombre: document.getElementById("reg-nombre").value.trim(),
        primer_apellido: document.getElementById("reg-apellido1").value.trim(),
        segundo_apellido: document.getElementById("reg-apellido2").value.trim(),
        email: document.getElementById("reg-email").value.trim(),
        password: document.getElementById("reg-password").value,
      };
      const pass2 = document.getElementById("reg-password2").value;

      if (data.password !== pass2) {
        alert("Las contraseñas no coinciden.");
        return;
      }

      try {
        const resp = await fetch("/api/usuarios/registro", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });

        if (!resp.ok) {
          let msg = `Error al registrar usuario (código ${resp.status}).`;
          const text = await resp.text().catch(() => "");
          if (text) msg += "\n\nRespuesta del servidor:\n" + text;
          alert(msg);
          return;
        }

        await resp.json();
        formRegister.reset();
        closeModal(modalRegister);
        showSuccessModal("Te has registrado correctamente. Ahora puedes iniciar sesión.");
      } catch (err) {
        console.error("Error en el registro:", err);
        alert("Error al comunicarse con el servidor.");
      }
    });
  }

  // =====================================================
  // Login (backend A: valida, no crea sesión)
  // =====================================================
  const formLogin = document.getElementById("form-login");
  if (formLogin) {
    formLogin.addEventListener("submit", async (e) => {
      e.preventDefault();

      const data = {
        email: document.getElementById("login-email").value.trim(),
        password: document.getElementById("login-password").value,
      };

      try {
        const resp = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });

        if (!resp.ok) {
          let msg = `Error en el login (código ${resp.status}).`;
          const text = await resp.text().catch(() => "");
          if (text) msg += "\n\nRespuesta del servidor:\n" + text;
          alert(msg);
          return;
        }

        const json = await resp.json();
        setFrontLoggedIn(true);
        setFrontUserName(json?.usuario?.nombre || "Usuario");

        alert(`Bienvenido ${json.usuario.nombre} ${json.usuario.primer_apellido}`);

        formLogin.reset();
        closeModal(modalLogin);

        renderAuthUI();
        cargarCamarasTabla();
      } catch (err) {
        console.error("Error en el login:", err);
        alert("Error al comunicarse con el servidor.");
      }
    });
  }

  // =====================================================
  // Tabla de cámaras (simulamos protección solo frontend)
  // =====================================================
  const tablaCamarasBody = document.getElementById("tabla-camaras-body");
  const btnRefrescarCamaras = document.getElementById("btn-refrescar-camaras");

  function llenarTablaCamaras(camaras) {
    if (!tablaCamarasBody) return;

    if (!Array.isArray(camaras) || camaras.length === 0) {
      tablaCamarasBody.innerHTML = `
        <tr><td colspan="6" class="camaras-empty">No hay cámaras registradas.</td></tr>
      `;
      return;
    }

    tablaCamarasBody.innerHTML = "";
    camaras.forEach((cam) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${cam.id ?? "-"}</td>
        <td>${cam.latitud ?? "-"}</td>
        <td>${cam.longitud ?? "-"}</td>
        <td>${cam.rango_m ?? "-"}</td>
        <td>${cam.tipo ?? "-"}</td>
        <td>${cam.descripcion ?? "-"}</td>
      `;
      tablaCamarasBody.appendChild(tr);
    });
  }

  async function cargarCamarasTabla() {
    if (!tablaCamarasBody) return;

    if (!isFrontLoggedIn()) {
      tablaCamarasBody.innerHTML = `
        <tr><td colspan="6" class="camaras-empty">Inicia sesión para ver las cámaras registradas.</td></tr>
      `;
      return;
    }

    tablaCamarasBody.innerHTML = `
      <tr><td colspan="6" class="camaras-empty">Cargando cámaras...</td></tr>
    `;

    try {
      const resp = await fetch("/api/camaras", { method: "GET", cache: "no-store" });
      if (!resp.ok) {
        tablaCamarasBody.innerHTML = `
          <tr><td colspan="6" class="camaras-empty">Error al cargar cámaras (código ${resp.status}).</td></tr>
        `;
        return;
      }
      const camaras = await resp.json();
      llenarTablaCamaras(camaras);
    } catch (err) {
      console.error("Error al cargar cámaras:", err);
      tablaCamarasBody.innerHTML = `
        <tr><td colspan="6" class="camaras-empty">Error de conexión al servidor.</td></tr>
      `;
    }
  }

  if (btnRefrescarCamaras) btnRefrescarCamaras.addEventListener("click", cargarCamarasTabla);

  // =====================================================
  // Inicialización
  // =====================================================
  renderAuthUI();
  if (tablaCamarasBody) cargarCamarasTabla();
});
