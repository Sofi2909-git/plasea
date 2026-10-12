/**
 * PLASEA - gráficos del tablero (RF-54 a RF-56).
 * Aplica el ancho de cada barra desde su atributo data-ancho (0 a 100). La
 * política de contenido no permite estilos en línea en el HTML; sin JavaScript
 * las cifras y la tabla de datos siguen visibles.
 */
(() => {
  "use strict";

  const limitar = (valor) => {
    const numero = Number(String(valor).replace(",", "."));
    return Number.isFinite(numero) ? Math.max(0, Math.min(100, numero)) : 0;
  };

  document.addEventListener("DOMContentLoaded", () => {
    const barras = document.querySelectorAll(".barra[data-ancho]");
    window.requestAnimationFrame(() => {
      barras.forEach((barra) => {
        barra.style.width = `${limitar(barra.dataset.ancho)}%`;
      });
    });
  });
})();
