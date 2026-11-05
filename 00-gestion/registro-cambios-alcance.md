# Registro de cambios de alcance

## CA-001 · Revisión de la docente (28/10/2026): RF-64 a RF-67

- **Fecha:** 03/11/2026 (implementación). Revisión de la docente: 28/10/2026.
- **Motivo:** la docente pidió (a) PDF del auditor con estadística por curso y por estudiante, con el motivo de pérdida en los cortes 1 y 2 y gráfica en pantalla; (b) para el profesor, una gráfica de cuántos estudiantes reportó del total matriculado, exportable a PDF por curso.
- **Requisitos nuevos:** RF-64 (pérdida reiterada), RF-65 (PDF de estadística por curso, auditor), RF-66 (gráfica del profesor), RF-67 (PDF del profesor por curso). Total: 67 RF.
- **Requisitos modificados:** RF-02, RF-26, RF-34, RF-45, RF-48, RF-60, RF-61.
- **Impacto:**
  - Base de datos: ninguno (todo se calcula desde `alertas`; no hay migración).
  - Backend: `servicios/perdida_reiterada.py`, `estadistica_curso.py`, `estadistica_profesor.py`; cambios en `analitica.py`, `seguimiento_profesor.py`, `exportacion.py`, `autorizacion.py` y en las rutas de E6, E8 y E10.
  - Interfaz: plantillas de gráficas, pantalla RF-66, documentos imprimibles RF-65 y RF-67, ajustes en RF-45, RF-48, RF-60, RF-26 y RF-34; CSS y JS.
  - Pruebas: `04-pruebas/unitarias/test_perdida_reiterada_y_reporte.py` y `04-pruebas/funcionales/test_e6_e8_e10_rf64_a_rf67.py`.
- **Aprobación:** [PENDIENTE] confirmación de la docente.

### Decisiones de implementación [SUPUESTO]
1. Los «PDF» son vistas imprimibles que el navegador guarda como PDF (sin PDF en el servidor).
2. En la gráfica de RF-48, «perdidos» se cuenta aparte y no es subconjunto de «rojo».
3. En RF-66, quien no tiene nota en el corte se evalúa solo por inasistencia («Sin nota» si no hay alerta por inasistencia).
4. En RF-66 el total de inscritos es el de la lista de RF-27 (inscripciones vigentes).
