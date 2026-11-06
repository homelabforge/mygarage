# Brand logos

The 143 thumbnails in this folder come from
[filippofilip95/car-logos-dataset](https://github.com/filippofilip95/car-logos-dataset) at commit `e334a4d2e8742108ba164c629dff5636576d3808`,
MIT licensed. That dataset crawled them from carlogos.org.

The logos are trademarks of their respective owners and are shown only to
identify each make. A maker that wants its logo removed: delete its PNG and
the `logo` field of its entry in `src/constants/carCatalog.json`.

Regenerate with `bun run scripts/fetch-brand-logos.ts` from `frontend/`.
