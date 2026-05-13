# WSFEv1 v4.3 (RG-4291) — Estado de compliance del proyecto

**Fecha auditoría:** 2026-05-13 · **Spec referenciada:** [manual WSFEv1 v4.3 RG-4291](https://www.arca.gob.ar/fe/ayuda/documentos/wsfev1-RG-4291.pdf) · **Endpoint homo:** `http://wswhomo.afip.gov.ar/wsfev1/service.asmx`

---

## TL;DR

**Estamos compliant para emitir hoy.** Falta detalle en 2 frentes:

1. **Catálogo `CondicionIVAReceptorId`**: el helper no contemplaba dos códigos (`7` Sujeto No Categorizado y `16` Monotributo Trabajador Independiente Promovido). ✅ Corregido en este commit.
2. **Códigos de error nuevos** que ARCA da de alta el **14/05/2026 22:00 hs** (evento WSFE `Code 43`): `10247`, `10248`, `10249` para CAE y `827`, `828`, `829` para CAEA. ✅ Agregados al catálogo de `errors.py` con descripción inferida — refinar cuando ARCA publique las descripciones definitivas.

**Deadline crítica:** **01/06/2026** — desde esa fecha ARCA rechaza solicitudes sin `CondicionIVAReceptorId` (evento WSFE `Code 39`, RG 5616). Faltan 18 días al momento de este commit. Nuestro helper ya defaultea a `5` (Consumidor Final) si el partner no tiene responsabilidad asignada, así que no se cae a `None` desde el flujo normal de Odoo.

---

## 1. Eventos relevantes hoy en WSFEv1

### Code 39 — RG 5616 `CondicionIVAReceptorId`

> El día 6 de abril de 2025, se actualizó la versión del WS que permite enviar, de forma opcional, el campo Condición Frente al IVA del receptor. (…) Se mantendrá como un dato no excluyente hasta el **31/05/2026**, inclusive. **A partir del 01/06/2026 se rechazarán las solicitudes** de emisión de comprobantes sin este dato.

**Nuestro estado:**

| Aspecto | Status |
|---|---|
| Helper `_l10n_ar_get_condicion_iva_receptor_id` en `account.move` | ✅ siempre devuelve int (default `5` = CF) |
| Inclusión en payload `FECAESolicitar` | ✅ `payload.py:164` |
| Mapeo por `l10n_ar_afip_responsibility_type_id` | ✅ cubre los 11 códigos oficiales |
| Test de payload con `CondicionIVAReceptorId` | ✅ `test_payload.py:47` |
| Test de payload sin `CondicionIVAReceptorId` (`None`) | ✅ `test_payload.py:139` — verifica que NO se incluya si vino `None` |

### Code 43 — Alta de códigos 14/05/2026

> Los cambios del apartado 4.2 impactarán en producción el día jueves 14/05/2026 a partir de las 22:00 hs. Alta de códigos, CAE 10247, 10248, 10249, CAEA 827, 828, 829. El sistema estará fuera de servicio por el transcurso de 1 hora.

**Implicancia:** desde 14/05/2026 22:00 hs, el WS puede devolvernos esos códigos de error sin que los tengamos catalogados. Como nuestro `WsfeError` ya muestra `code + msg + hint`, **igual va a ser legible para el operador** — pero el hint estaría vacío.

**Nuestro estado:** ✅ catalogados con descripción inferida en `errors.py` con marcador `(v4.3)` para revisar cuando salga la doc oficial.

---

## 2. Catálogo oficial `CondicionIVAReceptorId` (v4.3)

| Id | Descripción | Cmp_Clase compatible |
|---|---|---|
| 1 | IVA Responsable Inscripto | A / M / C |
| 4 | IVA Sujeto Exento | B / C |
| 5 | Consumidor Final | B / C |
| 6 | Responsable Monotributo | A / M / C |
| 7 | Sujeto No Categorizado | B / C |
| 8 | Proveedor del Exterior | B / C |
| 9 | Cliente del Exterior | B / C |
| 10 | IVA Liberado – Ley N° 19.640 | B / C |
| 13 | Monotributista Social | A / M / C |
| 15 | IVA No Alcanzado | B / C |
| 16 | Monotributo Trabajador Independiente Promovido (Dto 444/2023) | A / M / C |

**Cmp_Clase**: cada código sólo es válido contra ciertas letras de comprobante. Una FA-A a Consumidor Final (Id=5, B/C) sería rechazada con error **10154**.

**Fuente:** `FEParamGetCondicionIvaReceptor` en `wswhomo.afip.gov.ar/wsfev1/service.asmx` + reporte público de [afipsdk.com](https://afipsdk.com/blog/factura-electronica-solucion-a-error-10242/).

---

## 3. Códigos de error nuevos catalogados

### 10242 (clásico, ya disparado en producción de muchos)

> `(10242) El campo Condición IVA receptor no es un valor válido / es obligatorio. Consultar método FEParamGetCondicionIvaReceptor`

Causa: omitiste `CondicionIVAReceptorId` o pasaste un id no listado. Acción: ver tabla de la sección 2 y ajustar el partner.

### 10247 / 10248 / 10249 (CAE — nuevos 14/05/2026)

Sin descripción oficial al día del commit. Hipótesis razonables por contexto (validaciones que ARCA ha venido pidiendo durante 2026):

- **10247** — validación cruzada `CondicionIVAReceptorId` ↔ tipo de comprobante (Cmp_Clase).
- **10248** — validación cruzada `DocTipo` + `DocNro` + `CondicionIVAReceptor` (consistencia con padrón).
- **10249** — validación adicional, sin patrón claro.

### 827 / 828 / 829 (CAEA — nuevos 14/05/2026)

Sin descripción oficial. Probablemente validaciones de:

- Ventana de rendición / consistencia período-orden ampliada.
- Validación CAEA al consumir contra `FECAEARegInformativo`.

**Acción pendiente:** revisar el PDF oficial v4.3 cuando ARCA lo libere definitivamente (hoy la URL devuelve un PDF en testing) y refinar los hints en `addons/l10n_ar_afip_ws/lib/errors.py`.

---

## 4. Plan post-deadline (01/06/2026)

Después del 01/06/2026 podemos volver a este doc y:

1. Cambiar `payload.py:164` de `if cond_iva_receptor_id is not None:` a un `assert cond_iva_receptor_id is not None` (fail-fast en vez de generar payloads sin el campo).
2. Quitar la nota "compat con cuentas que no migraron" — todas migraron por fuerza.
3. Si ya aparecieron los `Err.Msg` reales de 10247-10249 y 827-829, refinar las descripciones en `errors.py`.

---

## 5. Verificaciones que querría tener hechas pre-01/06/2026

- [ ] **Smoke en demo19 prod** confirmando que una factura B a CF emite limpia (debe pasar `CondicionIVAReceptorId=5`).
- [ ] **Smoke con partner código 16** (Monotributo Promovido) → emitir FA-A → verificar que el payload contiene `CondicionIVAReceptorId=16`.
- [ ] **Smoke negativo**: forzar mismatch (FA-A a CF Id=5) y verificar que devuelve **10154**, no un genérico.
- [ ] **Verificar comportamiento contra el nuevo entorno post-14/05/2026 22hs** — emitir un comprobante test y revisar si aparecen los códigos 10247-9 con `Msg` legible.

---

## 6. Cambios aplicados en este commit

```
addons/l10n_ar_edi/models/account_move.py
    + códigos 7 y 16 en el mapping
    + docstring con catálogo completo y notación Cmp_Clase
    + nota deadline 2026-06-01

addons/l10n_ar_edi/lib/payload.py
    ~ refinada nota sobre el default None y la deadline

addons/l10n_ar_afip_ws/lib/errors.py
    + 10242, 10247, 10248, 10249, 827, 828, 829
    ~ refinados 10074 y 10154 con catálogo completo

docs/wsfev1_RG4291_v43_compliance.md   ← este archivo
```

---

**Sources:**

- [Manual WSFEv1 v4.3 RG-4291 (ARCA, en testing)](https://www.arca.gob.ar/fe/ayuda/documentos/wsfev1-RG-4291.pdf)
- [WSFEv1 endpoint homologación](http://wswhomo.afip.gov.ar/wsfev1/service.asmx)
- [FEParamGetCondicionIvaReceptor — WSDL operation](https://wswhomo.afip.gov.ar/wsfev1/service.asmx?op=FEParamGetCondicionIvaReceptor)
- [Error (10242) explicación detallada — afipsdk.com](https://afipsdk.com/blog/factura-electronica-solucion-a-error-10242/)
