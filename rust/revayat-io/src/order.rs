use serde_json::Value;

pub fn natural_sort_order(names: &[String]) -> Vec<usize> {
    packcore_rs::port::natural_sort_order(
        names.iter().map(|name| name.as_bytes().to_vec()).collect(),
    )
}

fn bbox(value: &Value) -> Option<[f64; 4]> {
    let values = value.as_array()?;
    if values.len() != 4 {
        return None;
    }
    let rect = [
        values[0].as_f64()?,
        values[1].as_f64()?,
        values[2].as_f64()?,
        values[3].as_f64()?,
    ];
    (rect.into_iter().all(f64::is_finite) && rect[2] > 0.0 && rect[3] > 0.0).then_some(rect)
}

pub fn assign_panel(page: &Value, region: &mut Value) {
    let panel = (|| {
        let [x, y, w, h] = bbox(region.get("bbox")?)?;
        page.get("panels")?.as_array()?.iter().find_map(|panel| {
            let [px, py, pw, ph] = bbox(panel.get("bbox")?)?;
            let width = ((x + w).min(px + pw) - x.max(px)).max(0.0);
            let height = ((y + h).min(py + ph) - y.max(py)).max(0.0);
            (width * height / (w * h) >= 0.6)
                .then(|| panel.get("id").cloned())
                .flatten()
        })
    })();
    if let Some(obj) = region.as_object_mut() {
        obj.insert("panel".into(), panel.unwrap_or(Value::Null));
    }
}
