/**
 * PLASEA - ayudas de las pantallas de analítica (RF-45 y RF-60).
 * - Medidor de inasistencia: aplica anchos y posiciones desde atributos data-*
 *   (la política de contenido no permite estilos en línea en el HTML).
 * - Vista imprimible: botón que abre el diálogo de impresión del navegador.
 */
(() => {
  "use strict";

  const porcentaje = (valor) => {
    const numero = Number(String(valor).replace(",", "."));
    return Number.isFinite(numero) ? Math.max(0, Math.min(100, numero)) : 0;
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".medidor-barra[data-ancho]").forEach((barra) => {
      barra.style.width = `${porcentaje(barra.dataset.ancho)}%`;
    });
    document.querySelectorAll(".medidor-marca[data-posicion]").forEach((marca) => {
      marca.style.left = `${porcentaje(marca.dataset.posicion)}%`;
    });
    document.querySelectorAll("[data-imprimir]").forEach((boton) => {
      boton.addEventListener("click", () => window.print());
    });
  });
})();
