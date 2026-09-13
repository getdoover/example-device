# Scene sources

The six Street View screenshots were captured with computer use from the user's open Chrome tab on 11 September 2026. The images display Google attribution. Their capture date is January 2016. The annotated camera image was supplied by the user.

[Open the supplied Queen Victoria Building Street View](https://www.google.com/maps/place/Queen+Victoria+Building/@-33.8713639,151.2066024,2a,70.3y,129.04h,104.01t/data=!3m7!1e1!3m5!1sipZlepagBod9G7cYub8bAw!2e0!7i13312!8i6656).

The panorama ID is `ipZlepagBod9G7cYub8bAw`. Camera position was estimated from the circled housing, the underside of the bridge, the opposite shops, the escalator, and the atrium edge. Street View is captured at pedestrian height, so these screenshots are reference views rather than the simulated camera's images.

| File | Visible details |
| --- | --- |
| `00-user-camera-markup.png` | User's circled ceiling camera. |
| `01-camera-location.png` | Camera housing, curved atrium, clock direction and bridge soffit. |
| `02-clock-corridor.png` | Café seating, patterned carpet, shop depth and hanging clock. |
| `03-shopfronts.png` | Dominique's display shelving, glazing, bags and shoes. |
| `04-reverse-corridor.png` | Reverse café corridor and bentwood furniture. |
| `05-cross-atrium.png` | Escalator crossing, opposite shop rhythm and atrium void. |
| `06-roof.png` | Skylight pitch, glazing bars, trusses and upper gallery. |

Reference screenshots remain separate from model textures. No Street View image is projected onto scene geometry.

The second shop pass adds fifteen closer Street View captures under `shops/`. [Shop reference notes](shops/notes.md) record tenant identities, display details, panorama locations and remaining uncertainties.

## Material sources

These Poly Haven assets were downloaded at 2K through Blender MCP. Poly Haven distributes its assets under CC0. The model uses the diffuse, roughness, and displacement data with adjusted colour, projection and surface response.

- [American walnut veneer](https://polyhaven.com/a/american_walnut_veneer), used for the handrails and furniture.
- [Dirty carpet](https://polyhaven.com/a/dirty_carpet), used for the dark woven floor.
- [Brown leather](https://polyhaven.com/a/brown_leather), used for some shop merchandise.
- [Poly Haven asset license](https://polyhaven.com/license).

The geometry, stained-glass colours, carpet ornament and remaining materials were created procedurally for this scene. Shop signs and clock decoration are approximations of the references.
