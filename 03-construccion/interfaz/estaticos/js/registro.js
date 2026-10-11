/**
 * PLASEA - ayudas de la pantalla del profesor (RF-28 y RF-29).
 * - Asistencia: contador de ausentes y horas, y "Todos presentes".
 * - Notas: aviso inmediato de valores fuera de 1,0 a 5,0 o con más de un decimal
 *   y conteo de estudiantes con nota.
 * La validación real ocurre en el servidor; sin JavaScript la pantalla funciona.
 */
(() => {
  "use strict";

  const PATRON_NOTA = /^(\d+)(?:[.,](\d+))?$/;

  const activarAsistencia = (formulario) => {
    const horas = Number(formulario.dataset.horas) || 0;
    const casillas = Array.from(formulario.querySelectorAll("input[name=ausentes]"));
    const total = formulario.querySelector("[data-total]");
    const horasTotal = formulario.querySelector("[data-horas-total]");
    const botonPresentes = formulario.querySelector("[data-todos-presentes]");

    const actualizar = () => {
      const marcados = casillas.filter((casilla) => casilla.checked).length;
      total.textContent = String(marcados);
      horasTotal.textContent = String(marcados * horas);
      casillas.forEach((casilla) => {
        const fila = casilla.closest(".fila-asistencia");
        fila.classList.toggle("esta-ausente", casilla.checked);
        fila.querySelector(".fila-asistencia-estado").textContent = casilla.checked
          ? "Ausente"
          : "Presente";
      });
      if (botonPresentes) {
        botonPresentes.disabled = marcados === 0;
      }
    };

    casillas.forEach((casilla) => casilla.addEventListener("change", actualizar));
    if (botonPresentes) {
      botonPresentes.hidden = false;
      botonPresentes.addEventListener("click", () => {
        casillas.forEach((casilla) => {
          casilla.checked = false;
        });
        actualizar();
      });
    }
    actualizar();
  };

  const mensajeNota = (texto) => {
    const limpio = texto.trim();
    if (limpio === "") {
      return "";
    }
    const partes = PATRON_NOTA.exec(limpio);
    if (!partes) {
      return "Escriba un número, por ejemplo 3,5.";
    }
    if (partes[2] !== undefined && partes[2].length > 1) {
      return "Use un solo decimal, por ejemplo 3,5.";
    }
    const valor = Number(limpio.replace(",", "."));
    if (valor < 1 || valor > 5) {
      return "La nota debe estar entre 1,0 y 5,0.";
    }
    return "";
  };

  const activarNotas = (formulario) => {
    const campos = Array.from(formulario.querySelectorAll(".campo-nota"));
    const contador = formulario.querySelector("[data-con-nota]");

    const contar = () => {
      if (contador) {
        contador.textContent = String(
          campos.filter((campo) => campo.value.trim() !== "").length,
        );
      }
    };

    campos.forEach((campo) => {
      campo.addEventListener("input", contar);
      campo.addEventListener("blur", () => {
        const mensaje = mensajeNota(campo.value);
        campo.setCustomValidity(mensaje);
        campo.classList.toggle("is-invalid", mensaje !== "");
        campo.setAttribute("aria-invalid", String(mensaje !== ""));
        campo.title = mensaje;
      });
    });
    contar();
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-asistencia]").forEach(activarAsistencia);
    document.querySelectorAll("form[data-planilla-notas]").forEach(activarNotas);
  });
})();
