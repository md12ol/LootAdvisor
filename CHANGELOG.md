# Changelog

All notable changes to Loot Advisor, newest first. Versions follow [Semantic Versioning](https://semver.org/) (tags
`vX.Y.Z`). Entries are written by release-please from the Conventional Commit messages on `main` (README
"Releases"); the first release is `v0.9.0`.

## [Before 0.9.0] - what the first release contains

### Added
- Best items per slot and act for every origin character and build (Build Advisor's build list), Dark Urge included.
- Rainbow frame and an extra tooltip line on recommended items; contested items say which party member they suit better
  (active party only).
- Map and minimap markers at the item spots; marker hover popup listing the items.
- **F6** item list with direction and distance, including items without a fixed spot.
- Sets page (full loadouts for every origin, act by act) written by the mod to the Script Extender folder; it follows
  the running game and builds its art and texts from the player's own game install.
- Player package: `LootAdvisor.pak` with `INSTALL.md`.
- Item and set pipeline (`tools/`), regression suite with a mutation check (`tests/run.py`), leak scanner for shipped
  texts, GitHub CI.
