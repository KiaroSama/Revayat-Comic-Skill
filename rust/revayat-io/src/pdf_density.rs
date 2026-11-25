use super::{MAX_CONTENT, MAX_DEPTH, MAX_OPERATORS, PdfDocument, matrix_values, stream_bytes};
use crate::{IoError, invalid};
use hayro::{
    hayro_syntax::{
        content::{
            TypedIter,
            ops::{InlineImage, Transform, TypedInstruction},
        },
        object::{Number, Object as SyntaxObject},
    },
    kurbo::{Affine, Rect},
};
use lopdf::{Dictionary, Object, Stream};
use std::collections::HashSet;

pub(super) struct Density<'a> {
    pub(super) pdf: &'a PdfDocument,
    pub(super) scale: f64,
    pub(super) images: usize,
    pub(super) stencils: usize,
    pub(super) source_pixels: u64,
    pub(super) operations: usize,
    pub(super) active: HashSet<*const Stream>,
}

impl Density<'_> {
    pub(super) fn program(
        &mut self,
        data: &[u8],
        resources: Option<&Dictionary>,
        base: Affine,
    ) -> Result<(), IoError> {
        let mut state = base;
        let mut states = Vec::new();
        let mut ops = TypedIter::new(data);
        while let Some(step) = ops.next() {
            self.operations += 1;
            if self.operations > MAX_OPERATORS {
                return Err(invalid("PDF content has too many operations"));
            }
            match step {
                TypedInstruction::SaveState(_) => states.push(state),
                TypedInstruction::RestoreState(_) => {
                    state = states
                        .pop()
                        .ok_or_else(|| invalid("Unbalanced PDF graphics state"))?
                }
                TypedInstruction::Transform(Transform(a, b, c, d, e, f)) => {
                    state *= Affine::new([a, b, c, d, e, f].map(|n| n.as_f64()))
                }
                TypedInstruction::XObject(name) => {
                    let object = self
                        .pdf
                        .lookup(resources, b"XObject", name.0)?
                        .ok_or_else(|| invalid("Missing PDF XObject"))?;
                    self.visit(object.as_stream()?, resources, state)?;
                }
                TypedInstruction::InlineImage(InlineImage(stream)) => {
                    let dict = stream.dict();
                    let size = |abbr: &[u8], full: &[u8]| -> Result<u32, IoError> {
                        dict.get::<Number>(abbr)
                            .or_else(|| dict.get::<Number>(full))
                            .and_then(|n| u32::try_from(n.as_i64()).ok())
                            .filter(|n| *n > 0)
                            .ok_or_else(|| invalid("Invalid PDF inline image dimensions"))
                    };
                    let stencil = matches!(
                        dict.get::<SyntaxObject>(b"IM")
                            .or_else(|| dict.get::<SyntaxObject>(b"ImageMask")),
                        Some(SyntaxObject::Boolean(true))
                    );
                    self.measure(
                        size(b"W", b"Width")?,
                        size(b"H", b"Height")?,
                        state,
                        stencil,
                    );
                }
                TypedInstruction::NonStrokeColorNamed(color) => {
                    if let Some(name) = color.1 {
                        self.pattern(resources, name, base)?;
                    }
                }
                TypedInstruction::StrokeColorNamed(color) => {
                    if let Some(name) = color.1 {
                        self.pattern(resources, name, base)?;
                    }
                }
                TypedInstruction::SetGraphicsState(gs) => {
                    if let Some(g) = self.pdf.lookup(resources, b"ExtGState", gs.0)?
                        && let Some(soft) = self.pdf.get(g.as_dict()?, b"SMask")?
                        && let Ok(mask) = soft.as_dict()
                        && let Some(group) = self.pdf.get(mask, b"G")?
                    {
                        self.visit(group.as_stream()?, resources, state)?;
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn pattern(
        &mut self,
        res: Option<&Dictionary>,
        name: &[u8],
        base: Affine,
    ) -> Result<(), IoError> {
        if let Some(object) = self.pdf.lookup(res, b"Pattern", name)?
            && let Ok(stream) = object.as_stream()
        {
            self.visit(stream, res, base)?;
        }
        Ok(())
    }

    fn visit(
        &mut self,
        stream: &Stream,
        resources: Option<&Dictionary>,
        base: Affine,
    ) -> Result<(), IoError> {
        if self.active.len() >= MAX_DEPTH || !self.active.insert(std::ptr::from_ref(stream)) {
            return Err(invalid(
                "PDF graphics contain a cycle or exceed the nesting limit",
            ));
        }
        let result = self.visit_inner(stream, resources, base);
        self.active.remove(&std::ptr::from_ref(stream));
        result
    }

    fn visit_inner(
        &mut self,
        stream: &Stream,
        resources: Option<&Dictionary>,
        base: Affine,
    ) -> Result<(), IoError> {
        let dict = &stream.dict;
        let subtype = self
            .pdf
            .get(dict, b"Subtype")?
            .and_then(|o| o.as_name().ok());
        if subtype == Some(b"Image") {
            let [w, h] = self.pdf.image_size(dict)?;
            let stencil = self
                .pdf
                .get(dict, b"ImageMask")?
                .and_then(|o| o.as_bool().ok())
                .unwrap_or(false);
            self.measure(w, h, base, stencil);
            for key in [b"Mask".as_slice(), b"SMask"] {
                if let Some(mask) = self.pdf.get(dict, key)?
                    && let Ok(stream) = mask.as_stream()
                {
                    self.visit(stream, resources, base)?;
                }
            }
        } else if subtype == Some(b"Form")
            || dict.get(b"PatternType").and_then(Object::as_i64).ok() == Some(1)
        {
            let local = self
                .pdf
                .get(dict, b"Resources")?
                .map(Object::as_dict)
                .transpose()?
                .or(resources);
            let matrix = self
                .pdf
                .get(dict, b"Matrix")?
                .map(|m| matrix_values(self.pdf, m.as_array()?))
                .transpose()?
                .map(Affine::new)
                .unwrap_or(Affine::IDENTITY);
            self.program(&stream_bytes(stream, MAX_CONTENT)?, local, base * matrix)?;
        }
        Ok(())
    }

    fn measure(&mut self, w: u32, h: u32, matrix: Affine, stencil: bool) {
        self.images += 1;
        self.stencils += usize::from(stencil);
        self.source_pixels = self.source_pixels.max(u64::from(w) * u64::from(h));
        let [a, b, c, d, _, _] = matrix.as_coeffs();
        let (a, b, c, d) = (
            a / f64::from(w),
            b / f64::from(w),
            c / f64::from(h),
            d / f64::from(h),
        );
        let det = (a * d - b * c).abs();
        if [a, b, c, d, det].into_iter().any(|v| !v.is_finite()) {
            self.scale = f64::INFINITY;
        } else if det > 0.0 {
            let largest = ((a + d).hypot(b - c) + (a - d).hypot(b + c)) / 2.0;
            self.scale = self.scale.max(largest / det);
        }
    }

    pub(super) fn annotations(
        &mut self,
        dict: &Dictionary,
        res: Option<&Dictionary>,
        base: Affine,
    ) -> Result<(), IoError> {
        let Some(annots) = self.pdf.get(dict, b"Annots")? else {
            return Ok(());
        };
        for value in annots.as_array()? {
            let annotation = self.pdf.doc.dereference(value)?.1.as_dict()?;
            // Match Hayro's visible appearance selection, including standard Invisible annotations.
            if annotation.get(b"F").and_then(Object::as_i64).unwrap_or(0) & 34 != 0 {
                continue;
            }
            let Some(ap) = self.pdf.get(annotation, b"AP")? else {
                continue;
            };
            let Some(normal) = self.pdf.get(ap.as_dict()?, b"N")? else {
                continue;
            };
            let appearance = match normal {
                Object::Stream(stream) => Some(stream),
                Object::Dictionary(states) => {
                    let mut selected = None;
                    if let Some(state) = self
                        .pdf
                        .get(annotation, b"AS")?
                        .and_then(|o| o.as_name().ok())
                        && let Some(item) = self.pdf.get(states, state)?
                    {
                        selected = item.as_stream().ok();
                    }
                    match selected {
                        Some(stream) => Some(stream),
                        None => self
                            .pdf
                            .get(states, b"Off")?
                            .and_then(|item| item.as_stream().ok()),
                    }
                }
                _ => None,
            };
            let Some(stream) = appearance else {
                continue;
            };
            let rect = self
                .pdf
                .get(annotation, b"Rect")?
                .ok_or_else(|| invalid("PDF annotation has no rectangle"))?;
            let [x, y, w, h] = self.rect(rect)?;
            let bbox = self
                .pdf
                .get(&stream.dict, b"BBox")?
                .ok_or_else(|| invalid("PDF annotation appearance has no bounding box"))?;
            let [sx, sy, sw, sh] = self.rect(bbox)?;
            let matrix = self
                .pdf
                .get(&stream.dict, b"Matrix")?
                .map(|m| matrix_values(self.pdf, m.as_array()?))
                .transpose()?
                .map(Affine::new)
                .unwrap_or(Affine::IDENTITY);
            // ISO 32000-1, 12.5.5 fits the transformed BBox into Rect, before drawing the form.
            let bounds = matrix.transform_rect_bbox(Rect::new(sx, sy, sx + sw, sy + sh));
            let [sx, sy, sw, sh] = [bounds.x0, bounds.y0, bounds.width(), bounds.height()];
            if ![sx, sy, sw, sh].into_iter().all(f64::is_finite) || sw <= 0.0 || sh <= 0.0 {
                return Err(invalid("Invalid PDF annotation appearance transform"));
            }
            let transform = Affine::translate((x, y))
                * Affine::scale_non_uniform(w / sw, h / sh)
                * Affine::translate((-sx, -sy));
            self.visit(stream, res, base * transform)?;
        }
        Ok(())
    }

    fn rect(&self, object: &Object) -> Result<[f64; 4], IoError> {
        let [x0, y0, x1, y1] = object.as_array()?.as_slice() else {
            return Err(invalid("Invalid PDF rectangle"));
        };
        let (x0, y0, x1, y1) = (
            self.pdf.number(x0)?,
            self.pdf.number(y0)?,
            self.pdf.number(x1)?,
            self.pdf.number(y1)?,
        );
        Ok([x0.min(x1), y0.min(y1), (x1 - x0).abs(), (y1 - y0).abs()])
    }
}
