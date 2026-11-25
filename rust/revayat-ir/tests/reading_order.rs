use revayat_ir::{PageRecord, ir};
use serde_json::json;

fn page(raw: bool) -> PageRecord {
    let mut page = PageRecord {
        id: "p0001".into(),
        width: 100,
        height: 100,
        ..PageRecord::default()
    };
    page.panels = if raw {
        vec![json!([0, 0, 45, 100]), json!([55, 0, 45, 100])]
    } else {
        vec![
            json!({"id":"left","bbox":[0,0,45,100]}),
            json!({"id":"right","bbox":[55,0,45,100]}),
        ]
    };
    for (id, x, y) in [
        ("rt", 60., 5.),
        ("lt", 5., 5.),
        ("rb", 60., 60.),
        ("lb", 5., 60.),
    ] {
        page.regions.push(
            ir::new_region(id, [x, y, 20., 20.], "speech", "horizontal", "manual", 1.).unwrap(),
        );
    }
    page
}

#[test]
fn panel_reading_order_does_not_interleave_adjacent_scenes() {
    for (direction, wanted) in [
        ("rtl", ["rt", "rb", "lt", "lb"]),
        ("ltr", ["lt", "lb", "rt", "rb"]),
    ] {
        let mut page = page(false);
        ir::assign_reading_order(&mut page, direction, 0.35).unwrap();
        assert_eq!(
            page.regions
                .iter()
                .map(|r| r.id.as_str())
                .collect::<Vec<_>>(),
            wanted
        );
        for region in &page.regions {
            assert_eq!(
                region.panel,
                Some(json!(if region.bbox[0] < 50 { "left" } else { "right" }))
            );
        }
        assert_eq!(
            page.regions
                .iter()
                .map(|r| r.reading_order)
                .collect::<Vec<_>>(),
            [1, 2, 3, 4]
        );
    }
}

#[test]
fn raw_v2_panels_gain_stable_identity_without_changing_region_ids() {
    let mut page = page(true);
    ir::assign_reading_order(&mut page, "rtl", 0.35).unwrap();
    let panels = page.panels.clone();
    assert!(
        panels
            .iter()
            .all(|panel| panel["id"].is_string() && panel["bbox"].is_array())
    );
    let before = page.regions.clone();
    ir::assign_reading_order(&mut page, "rtl", 0.35).unwrap();
    assert_eq!(page.panels, panels);
    assert_eq!(page.regions, before);
}
