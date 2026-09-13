# Level 1 shop reference pass

Reference appearance: **January 2016**, as displayed by Google Street View. Captured through the user's open Chrome tab on 11 September 2026. These screenshots are visual references, not model textures.

The original camera panorama is [ipZlepagBod9G7cYub8bAw](https://www.google.com/maps/@?api=1&map_action=pano&pano=ipZlepagBod9G7cYub8bAw). Walking in Street View provided closer views at these panorama IDs:

- Clockward, Dominique's entry: `_DPPYW0MnxJUDNzlbrDVkg`.
- Clockward, GS Diamonds: `rThkEECr2XklO3czvGueiA`.
- Escalator direction, Volls and Tribeca: `J5gADp140FqUV4BMWSBffA`.
- Escalator end, George and Old Vienna opposite: `2XgbT2lx-Za57Ouv8Vv-Cg`.

## Observations used in the model

| Shop | Captures | Visible details reproduced |
| --- | --- | --- |
| Dominique's | 05, 07 | White stepped shoe plinths, floating shelves, mixed pumps and handbags, sale decal, chrome soffit, sash windows, wallpaper panel, crystal chandelier. |
| Volls Jewellery | 04, 13 | Projecting glass cabinets, gold and black frames, white necklace busts, pearl strands, ring trays, illuminated name and flower emblem. The close view in 13 corrects an initial misreading of the name. |
| Tribeca | 12 | Red full-length dress, headless torso display, dark tables, handbag display, clothes rails, dark perforated pendant globes. |
| George | 14 | Ivory mannequins with formal dresses, black and ivory clothing, warm vertical timber display slats, rear clothes rails and sash windows. This is a fashion store, not the adjacent café seating. |
| QVB Cashmere Collection | 06, 11 | Warm honey timber interior, pigeonhole shelves of folded sweaters, scarf display, dark mannequins in pale garments. |
| GS Diamonds | 08 | Dark charcoal display furniture, white and dark busts, glass counters, cool display lighting, gold window lettering and hanging pin-like light decoration. |
| Via Condotti | 01, 02, 09 | Two neighbouring accessory bays, mixed footwear and handbags, warm cream/gold displays, illuminated wordmark and chandelier. |
| Blooms | 09, 10 | Two clearly identifiable bright fashion bays, multiple mannequins, blue/ivory and patterned garments, rails behind, large red 50% sale poster. |
| Crabtree & Evelyn | 03, 15 | White cabinetry, sage accents, rows of packaged products, floral arrangement, large sage lampshade and circular blue tree logo. |
| Old Vienna Coffee House | 15 | Name readable on the end poster; glass cake cabinet, oxblood banquette, cream/gold interior, burgundy drapes and chandeliers. |
| Clockward fashion bay adjoining Blooms | 10 | Warm fashion window with red and dark garments. Its precise tenancy boundary and name are unresolved, so its model has no invented tenant lettering. |

## Limits of this pass

This pass replaces the first model's repeated handbag shelves and arbitrary cyclic tenant names. Shop identities, relative order, merchandise categories, colours and visible fixtures are based on the captures. Product geometry and unseen interiors are authored approximations.

The first model's 5 m bay grid, gallery proportions and camera mount are retained. The outer Old Vienna, Tribeca and George frontages are compressed into one model bay each, although the imagery shows longer frontages. Connected model bays share interior space for Dominique's, Via Condotti, Blooms, Crabtree & Evelyn and GS Diamonds. This is an accuracy improvement within the existing scene, not a measured reconstruction of tenancy widths.

The new objects are in `08 Level 1 shops`. The original Level 1 fixtures are retained in the hidden `09 Archived Level 1 placeholders` collection. `shop-manifest.json` maps each shop to its side, model bays, references and object count. Its scene signature checks that objects outside the replaced fixtures kept their transforms, material assignments and render visibility.

All signs and product labels are model geometry. The system serif font is used during construction and visible lettering is converted to meshes. Street View screenshot pixels are not embedded in the scene.
