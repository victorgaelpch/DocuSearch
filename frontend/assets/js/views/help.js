import { h } from "../dom.js";

const code = (text) => h("pre", { class: "code" }, h("code", {}, text));

export default {
  path: "/ayuda",
  title: "Ayuda",
  nav: { label: "Ayuda", order: 90 },
  render(main) {
    main.append(
      h("header", { class: "page-head" }, h("h1", {}, "Ayuda"), h("p", {}, "Configuración local, roles y qué hacer ante los errores más comunes.")),
      h("h2", {}, "Crear la cuenta de Administrador"),
      h("p", {}, "No existe contraseña por defecto. En PowerShell, desde la carpeta del proyecto:"),
      code("python -m backend.app.cli hash-password\n$env:DOCUSEARCH_ADMIN_PASSWORD_HASH = 'scrypt$…'   # pegue el hash entre comillas simples\npython -m uvicorn backend.app.main:app --host 127.0.0.1"),
      h("p", {}, "Para una cuenta de solo consulta, use ", h("code", {}, "DOCUSEARCH_USER_PASSWORD_HASH"), ". Las sesiones se cierran tras 30 minutos sin actividad y al reiniciar el servidor."),
      h("h2", {}, "Roles"),
      h("dl", { class: "defs" },
        h("dt", {}, "Administrador"), h("dd", {}, "Carga, importa, edita, elimina y reindexa documentos, y puede hacer todo lo del Usuario."),
        h("dt", {}, "Usuario de consulta"), h("dd", {}, "Lista, abre, descarga y busca en los documentos cargados."),
        h("dt", {}, "Sin sesión"), h("dd", {}, "Solo puede buscar en los corpus públicos de prueba (Wikipedia en español)."),
      ),
      h("h2", {}, "Problemas frecuentes"),
      h("dl", { class: "defs" },
        h("dt", {}, "«No hay conexión con el servidor»"), h("dd", {}, "El proceso de uvicorn se detuvo. Vuelva a iniciarlo y recargue la página."),
        h("dt", {}, "«La sesión expiró»"), h("dd", {}, "Pasaron más de 30 minutos sin actividad o se reinició el servidor. Inicie sesión de nuevo."),
        h("dt", {}, "«Búsqueda semántica no disponible»"), h("dd", {}, "Falta el extra opcional: ", h("code", {}, "python -m pip install -e \".[semantic]\""), ". BM25 y TF-IDF funcionan sin él."),
        h("dt", {}, "PDF «pendiente de OCR»"), h("dd", {}, "Es un PDF escaneado y Tesseract no está instalado o le falta el idioma español. Ver docs/lectores.md."),
      ),
      h("p", {}, "La documentación completa está en la carpeta ", h("code", {}, "docs/"), " del proyecto y la API interactiva en ", h("a", { href: "/docs" }, "/docs"), "."),
    );
  },
};
