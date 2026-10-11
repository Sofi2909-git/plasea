/**
 * PLASEA - comportamiento común de la interfaz (sin dependencias externas).
 * - Confirmación de acciones sensibles: <form data-confirmar="Mensaje">.
 * - Mostrar u ocultar contraseña: <button data-alternar-contrasena="id-del-campo">.
 * La validación real ocurre en el servidor; este archivo solo ayuda al usuario.
 */
(() => {
  "use strict";

  const activarConfirmaciones = () => {
    document.querySelectorAll("form[data-confirmar]").forEach((formulario) => {
      formulario.addEventListener("submit", (evento) => {
        const mensaje = formulario.getAttribute("data-confirmar");
        if (mensaje && !window.confirm(mensaje)) {
          evento.preventDefault();
        }
      });
    });
  };

  const activarAlternarContrasena = () => {
    document.querySelectorAll("[data-alternar-contrasena]").forEach((boton) => {
      const campo = document.getElementById(boton.getAttribute("data-alternar-contrasena"));
      if (!campo) {
        return;
      }
      boton.hidden = false;
      boton.addEventListener("click", () => {
        const mostrar = campo.type === "password";
        campo.type = mostrar ? "text" : "password";
        boton.textContent = mostrar ? "Ocultar" : "Mostrar";
        boton.setAttribute("aria-pressed", String(mostrar));
      });
    });
  };

  const evitarDobleEnvio = () => {
    document.querySelectorAll("form[data-un-envio]").forEach((formulario) => {
      formulario.addEventListener("submit", (evento) => {
        if (evento.defaultPrevented) {
          return;
        }
        formulario.querySelectorAll("[type=submit]").forEach((boton) => {
          boton.disabled = true;
        });
      });
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    activarConfirmaciones();
    activarAlternarContrasena();
    evitarDobleEnvio();
  });
})();
