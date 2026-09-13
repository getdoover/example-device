# Lower-floor references

Captured through computer use in the user's Chrome Street View tab on 11 September 2026. All photographs show January 2016. Screenshots retain Google's attribution and serve as modelling references; they are not applied as scene textures.

## Observations

| Reference | Visible evidence |
| --- | --- |
| [01](01-ground-escalator-end.png), [02](02-ground-clockward.png) | Ground-floor escalator, large single semicircular fanlights, round columns, Country Road, Jigsaw, David Lawrence and Karen Millen. |
| [03](03-sportscraft-coach-cafe.png), [04](04-basement-void-and-floor.png) | Sportscraft and Coach, open well below G, cream fascia, dark scrollwork and timber handrail. Tile borders combine terracotta, cream, charcoal and blue-green, with diamonds and circular junctions. |
| [05](05-central-cafe.png) | Solid crossing occupied by café tables, Coach, Longchamp and Mondial. Light timber square tables and dark bentwood chairs. |
| [06](06-clockward-cafe-kiosk.png) | Metropole kiosk with timber slats, dark counter, coffee equipment and glass display. Cue opposite Oroton. Another railing begins beyond the kiosk toward the clock. |
| [07](07-basement-concourse.png) | B1 has rectangular shopfronts, a low cream ceiling, oxide-coloured piers and patterned tile flooring. |
| [08](08-from-camera-level.png), [09](09-down-escalator-void.png) | Original Level 1 panorama, upper escalator landing and tall ground-floor arches visible beneath the balustrade. |

The panorama positions are [ground escalator end](https://www.google.com/maps/@?api=1&map_action=pano&pano=uavVks5SxkDLgau_XLwTWg), [Sportscraft](https://www.google.com/maps/@?api=1&map_action=pano&pano=XVR0MGP-58yh9EAToHmW4Q), [central café](https://www.google.com/maps/@?api=1&map_action=pano&pano=4x5eukSmTHCzqKxhfBfEtA), [Metropole kiosk](https://www.google.com/maps/@?api=1&map_action=pano&pano=UnPvrZlvqZbQclB6QJsNcw), [B1](https://www.google.com/maps/@?api=1&map_action=pano&pano=_YpIwF-SUhtAWcZ8NDAHbg), and [the original camera reference](https://www.google.com/maps/@?api=1&map_action=pano&pano=ipZlepagBod9G7cYub8bAw).

## Model interpretation

The ground floor is Z=-5.0 m and B1 is Z=-9.2 m. These estimated heights accommodate the large ground-floor arches. The earlier prototype used Z=-4.4 m and repeated upstairs transoms.

Two rounded openings replace the solid floor: a long escalator-side well and a shorter clockward well. The solid area between them holds the café and kiosk. Their widths, lengths and endpoints are inferred from the photographs and fitted to the existing upstairs model. They are not survey measurements.

The mosaic reproduces the observed palette, long borders, diamond panels and circular junctions. It simplifies the fine floral insets and does not reproduce every individual tile. The café layout and merchandise are representative arrangements. No photographed people are modelled.

The scene identifies ten ground-floor businesses across sixteen model bays. The two far-end tenant names remain unlabelled. Tenant ordering follows the observed walking route; frontage widths are fitted to the existing five-metre bay grid. B1 contains unlabelled continuation shops because the visible slice does not establish a reliable complete tenant map.

`refine_lower_floor.py` archives the original lower-floor placeholders and builds collection `10 Ground floor and visible basement`. `lower-floor-manifest.json` records the openings, tenants and a signature verifying that objects outside this pass retain their transforms and visibility.
