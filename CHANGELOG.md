# Changelog

All notable changes to Loot Advisor, newest first. Versions follow [Semantic Versioning](https://semver.org/) (tags
`vX.Y.Z`). Entries are written by release-please from the Conventional Commit messages on `main` (README
"Releases"); the first release is `v0.9.0`.

## 0.9.0 (2026-10-11)


### Features

* **3d:** 3D models for every set on the private Sets page ([6301529](https://github.com/md12ol/LootAdvisor/commit/63015292cdb57b29ca7edd84a1f69ea5362a395c))
* **3d:** 3D models for every set on the private Sets page ([9785857](https://github.com/md12ol/LootAdvisor/commit/9785857ae497fe8b3e8324ee610af15908d69642))
* **3d:** mount the 3D models in the private Sets page ([53012f6](https://github.com/md12ol/LootAdvisor/commit/53012f6524993fc4a34f9d8d12b3a617032c05c5))
* closest Build Advisor build for every other character and a gear-sets api ([48bb9e1](https://github.com/md12ol/LootAdvisor/commit/48bb9e19cf76fa4bfe525614723769136bb26e44))
* closest Build Advisor build for every other character and a gear-sets api for Build Advisor ([6ce894c](https://github.com/md12ol/LootAdvisor/commit/6ce894c8047e27bd8dfd2e2edc2a521c8661c58c))
* faster gauntlet runs, timing records, enemy damage scale ([b193308](https://github.com/md12ol/LootAdvisor/commit/b1933084839200d926f2884f8d1f6e17e2340022))
* gauntlet enemy damage scale, half by default for a solo character ([4201fe3](https://github.com/md12ol/LootAdvisor/commit/4201fe3cd48d6f6ed2bd4ce76e9be8e03be23834))
* gauntlet fights by the game's rules ([0c44f8d](https://github.com/md12ol/LootAdvisor/commit/0c44f8d6a127b020dce5a5f507678513f64b379e))
* gauntlet fights by the game's rules: Attacks of Opportunity, real hit points ([d717e45](https://github.com/md12ol/LootAdvisor/commit/d717e458db21564600eb05378654281637049917))
* gauntlet setup check, any deviation fails the run ([5a0feb6](https://github.com/md12ol/LootAdvisor/commit/5a0feb67c4c9a630a9d9577b7c8758177c5ad361))
* gauntlet setup check, any deviation from the spec fails the run ([7018d6a](https://github.com/md12ol/LootAdvisor/commit/7018d6a0d3c6c17dedd96b169e3aa4c1075eba80))
* gauntlet two lanes at once, a control pair alike in damage taken, real-respec setup check ([8a79766](https://github.com/md12ol/LootAdvisor/commit/8a79766a14e80b87deece3ffa08a94d338444030))
* gauntlet two lanes at once, a control pair alike in damage taken, real-respec setup check ([44a922e](https://github.com/md12ol/LootAdvisor/commit/44a922e646413f0a8ee294b86ba32173d3d48fcb))
* **gauntlet:** drive summons, set toggles, clear carried state and check every credited effect ([1886b26](https://github.com/md12ol/LootAdvisor/commit/1886b26df93b004191902bfd860dc505462193eb))
* **gauntlet:** drive summons, set toggles, clear carried state and check every credited effect ([f7663d6](https://github.com/md12ol/LootAdvisor/commit/f7663d69de64f12332a01e4313467149fcf58b07))
* **gauntlet:** fixed arenas with high ground and a clear-area check ([e2d9f39](https://github.com/md12ol/LootAdvisor/commit/e2d9f39c7abf4d94cd03a514d92e872c14c4d243))
* **gauntlet:** fixed arenas with high ground and a clear-area check ([43b875e](https://github.com/md12ol/LootAdvisor/commit/43b875e7f3bf5eea0a4708b3bec71369478c3213))
* **gauntlet:** in-game harness that measures gear sets in the real engine ([16cb21e](https://github.com/md12ol/LootAdvisor/commit/16cb21e092feeac28f908e44e0770b597534ce80))
* **gauntlet:** in-game harness that measures gear sets in the real engine ([5b343fc](https://github.com/md12ol/LootAdvisor/commit/5b343fcd72e210b199401597c89ecf0d1551be13))
* map markers for everyone, tie picks in F6 and on the Sets page ([87ab819](https://github.com/md12ol/LootAdvisor/commit/87ab819a544072dcd7e16b8e5626712546b67b02))
* map markers for everyone, tie picks in F6 and on the Sets page ([19f2c1b](https://github.com/md12ol/LootAdvisor/commit/19f2c1bc47c1a427bbc70a18cf28a108c5567e61))
* mod.io publishing prep ([b95d8b5](https://github.com/md12ol/LootAdvisor/commit/b95d8b5a204e0efaff18328cc8029e47abdaf4bb))
* mod.io publishing prep ([f6fa0ed](https://github.com/md12ol/LootAdvisor/commit/f6fa0ed2326d0b588cb87eadd4ad1ad16e8a8427))
* **mod:** active-party owners, Dark Urge name, F6 Sets page path ([87d56b3](https://github.com/md12ol/LootAdvisor/commit/87d56b3992271d3166929901edf36b48607b0705))
* **mod:** F6 window: Sets page button showing the page path ([817e202](https://github.com/md12ol/LootAdvisor/commit/817e2027fac07e4a4f96ed6671dde17f5ec95662))
* **mod:** refresh LootData and ModData from the rescored data (game subclass names, new builds) ([8ffead9](https://github.com/md12ol/LootAdvisor/commit/8ffead9d483f70c075cf925667666121f84f36ac))
* **mod:** resolve contested owners among the active party only; Dark Urge tooltip uses the player's name ([b1ed6c1](https://github.com/md12ol/LootAdvisor/commit/b1ed6c1a4fddc51b2f3c69db3ccb8b4323b2bcff))
* **optimizer:** assign contested unique items across the party ([578a8d6](https://github.com/md12ol/LootAdvisor/commit/578a8d6b049485183ea8f675cd98d007e4811622))
* **optimizer:** assign contested unique items across the party and run jobs in parallel ([f856bca](https://github.com/md12ol/LootAdvisor/commit/f856bcac54f10af23238b200f5bd914bda4f420a))
* **optimizer:** boss scenario for gauntlet expectations and Scabby Pugilist needs two enemies near ([0454554](https://github.com/md12ol/LootAdvisor/commit/04545548b8e3ccf2f6351a9ffa6af7fdb1658dff))
* **optimizer:** boss scenario for gauntlet expectations, Giantslayer rider counted once, assumed toggles in test plans ([cb09e35](https://github.com/md12ol/LootAdvisor/commit/cb09e358d0e79e6682e5eb237897d2864ebf0a10))
* **optimizer:** keep contested items with their owner unless another character gains 10% more ([93c4a9a](https://github.com/md12ol/LootAdvisor/commit/93c4a9afae1e5eaf3394b3413df702a9032741f7))
* **optimizer:** keep contested items with their owner unless another character gains 10% more ([61b638a](https://github.com/md12ol/LootAdvisor/commit/61b638aa38e0505228522edbe69a499950437476))
* **optimizer:** party ownership, situational and defensive value, respec tuning, test plans ([5e6e97d](https://github.com/md12ol/LootAdvisor/commit/5e6e97dda1fef565dfb7b9134e142a50a731caf4))
* **optimizer:** per-build gear optimizer with a game-data combat model and tests ([a530edc](https://github.com/md12ol/LootAdvisor/commit/a530edc3344a0bf34ad1d2e322069867e1d77b27))
* **owners:** follow Build Advisor's first builds and keep the Weave kit on Gale ([2d4b928](https://github.com/md12ol/LootAdvisor/commit/2d4b9282e9d1cb58fd4efb3383eeceb5295891ea))
* **owners:** follow Build Advisor's first builds and keep the Weave kit on Gale ([0c32a67](https://github.com/md12ol/LootAdvisor/commit/0c32a67242dd1bd37a67e793d0ec5f533e7b9ae1))
* **package:** complete the install folder: handbook, Sets page copy, media ([af15550](https://github.com/md12ol/LootAdvisor/commit/af15550a431cdf8c95179c96be05e3f8f10563c0))
* **page:** Gilded Panel header with runtime game-icon strip, offline/install state for the Sets page ([08d7199](https://github.com/md12ol/LootAdvisor/commit/08d71990077fb42de360468c707e52484d877774))
* **page:** header strip shows the most-picked Legendary and Very Rare items ([b1bf05e](https://github.com/md12ol/LootAdvisor/commit/b1bf05e6397399e563076f00d2c7fb263075f9b4))
* **page:** rainbow recommended frame on every header strip item ([01261b0](https://github.com/md12ol/LootAdvisor/commit/01261b0ff3b2e20f8bdcbf0f15364d1a6395b813))
* shorter item tooltip warnings, up to three lines ([1b07a64](https://github.com/md12ol/LootAdvisor/commit/1b07a64da349eab8c1f43fd9001624d945a705f3))
* shorter item tooltip warnings, up to three lines ([561c82f](https://github.com/md12ol/LootAdvisor/commit/561c82f2424d3d0a886c8c59e64250f898b82d9b))
* warn players that Loot Advisor contains spoilers ([a9def7b](https://github.com/md12ol/LootAdvisor/commit/a9def7bb82cbf0096c4ac039b40359350fca2987))
* warn players that Loot Advisor contains spoilers ([e5f75b0](https://github.com/md12ol/LootAdvisor/commit/e5f75b02673a2196bcdaa37fbf15755161f66e28))


### Bug Fixes

* **3d:** keep the models local - viewer copy served from this machine only, never in the published page ([4167384](https://github.com/md12ol/LootAdvisor/commit/41673841eb417ca530ac5becc6a2a07013630d23))
* **data:** rename sets Hellfire Karlach and Inferno Acuity, fix README rebuild order ([8d26fed](https://github.com/md12ol/LootAdvisor/commit/8d26fedebb3f9c75abfbf8b270e4929c58bb1b9a))
* gauntlet asks again when the engine refuses a cast after an Attack of Opportunity ([dd0b63b](https://github.com/md12ol/LootAdvisor/commit/dd0b63b3bf81264d246ec5b32f29fe0d3508d5f4))
* gauntlet casts from where the character stands ([2059354](https://github.com/md12ol/LootAdvisor/commit/2059354b7f2a4040a12a3e15d632e48df03aee07))
* gauntlet enemies and setup spec match the game ([fb52c31](https://github.com/md12ol/LootAdvisor/commit/fb52c31ab1ecbf39c036bf56e02cf8a478d0aac7))
* gauntlet enemies hostile to a companion made a player by script ([a87840c](https://github.com/md12ol/LootAdvisor/commit/a87840ce54a66f4a42b8b7d489d70cc60a958f24))
* gauntlet hostility uses the faction the enemies were given ([a35922b](https://github.com/md12ol/LootAdvisor/commit/a35922b7f9c9211e8c8d20188e83b4f1bae4ab35))
* gauntlet movement comments describe the behaviour only ([5fdbb87](https://github.com/md12ol/LootAdvisor/commit/5fdbb877f23344952407c4f92b478fb2452fe3ff))
* gauntlet party includes player characters missing from the players database ([d25d77f](https://github.com/md12ol/LootAdvisor/commit/d25d77f0ca8fe7b03e61f95e82256601a2382095))
* gauntlet prep takes off the statuses an earlier run's elixir gave ([50aefa2](https://github.com/md12ol/LootAdvisor/commit/50aefa2c06ffba054ac4d5d4e8144705a18cf15b))
* gauntlet specs and enemies match the real respec and the model ([3af1828](https://github.com/md12ol/LootAdvisor/commit/3af18285189fc2359550d157eccdc3e164dab92e))
* gauntlet specs follow each set's tuned respec ([13af726](https://github.com/md12ol/LootAdvisor/commit/13af726e168125cb651b04eee532cea5310b2b81))
* **gauntlet:** confirm casts, plan affordable turns, stop reaction leaks and mark invalid runs ([38814a2](https://github.com/md12ol/LootAdvisor/commit/38814a2a06be6c96cc2c7b734bec20f389d21498))
* **gauntlet:** confirm casts, plan affordable turns, stop reaction leaks and mark invalid runs ([99cbbff](https://github.com/md12ol/LootAdvisor/commit/99cbbff202fcc6ccca57e07476522b92b50a8a2f))
* **gauntlet:** expect item-granted resources, end summon turns, move lane bystanders ([53ddfeb](https://github.com/md12ol/LootAdvisor/commit/53ddfeb413ca3e0fb5a946a7f1ee0e6cba9cc0d6))
* **gauntlet:** expect item-granted resources, end summon turns, move lane bystanders ([1ab90c4](https://github.com/md12ol/LootAdvisor/commit/1ab90c44c4234ef39e912c7ccf3cb80f754c1f0a))
* **gauntlet:** hostile enemies, solo party, class proficiencies and reactions that never ask ([afa7456](https://github.com/md12ol/LootAdvisor/commit/afa7456a8385d97cf434e0abc9bc668c17c0329a))
* **gauntlet:** hostile enemies, solo party, class proficiencies and reactions that never ask ([29b7d66](https://github.com/md12ol/LootAdvisor/commit/29b7d66da9144959baa565ed695c92ed5fc89937))
* **gauntlet:** item-granted casts are not foreign, failed item spells wait for a rest, misses log range and sight ([d1b2a5f](https://github.com/md12ol/LootAdvisor/commit/d1b2a5f733285554b04bf2908734068ce209e22a))
* **gauntlet:** item-granted casts are not foreign, failed item spells wait for a rest, misses log range and sight ([c064d33](https://github.com/md12ol/LootAdvisor/commit/c064d33ab4be10195ec9433248d7e67c07a9b881))
* **gauntlet:** refused casts, downed rounds, leftover enemies and encumbrance ([2bf7e39](https://github.com/md12ol/LootAdvisor/commit/2bf7e3976f264523b823cc976284eba8f49adcd4))
* **gauntlet:** refused casts, downed rounds, leftover enemies and encumbrance ([14d2958](https://github.com/md12ol/LootAdvisor/commit/14d2958b988be9256adb0def213add2cc36e20dc))
* give the owner of an exactly tied item a party alternative ([036e3b6](https://github.com/md12ol/LootAdvisor/commit/036e3b6aec2ce3ce2f1b07dae796751efa55d7fe))
* hide the F6 window on build screens when Build Advisor is loaded ([1a25a52](https://github.com/md12ol/LootAdvisor/commit/1a25a5269a9924902cab4f6ebaae3358502f0c7c))
* hide the F6 window on build screens when Build Advisor is loaded ([fea214f](https://github.com/md12ol/LootAdvisor/commit/fea214fea4ddc172cb0de8798002b771c22e29f5))
* **mod:** a settled tie sends the other character on even when the party owns the item ([cbbc273](https://github.com/md12ol/LootAdvisor/commit/cbbc27308fb249e599b349f9f1f7cc7b5c7b90b8))
* **mod:** detect worn tied weapons by Osiris's weapon slot names ([b0b9157](https://github.com/md12ol/LootAdvisor/commit/b0b915763d5fb3b76a4c08be6e75b50f6da7d202))
* **mod:** detect worn tied weapons by Osiris's weapon slot names ([d551892](https://github.com/md12ol/LootAdvisor/commit/d551892c01f57ea8bca8c4b21b01e039254e67ef))
* **mod:** find Minthara by her global name and match party companions by guid ([f87f183](https://github.com/md12ol/LootAdvisor/commit/f87f183dc33135994809f2bb59d5cae9c64eb70a))
* **mod:** hide the F6 window while the game's pause menu is open ([78e036e](https://github.com/md12ol/LootAdvisor/commit/78e036eed4a1d1a8f17867db3ebab4d94515cafe))
* **mod:** leave camp followers and companions left in an earlier act off the marker roster ([8022435](https://github.com/md12ol/LootAdvisor/commit/8022435569d035922d6a9676b2d25e049bd66c45))
* **mod:** marker roster, routing speed and tie fixes found in game ([8ed232e](https://github.com/md12ol/LootAdvisor/commit/8ed232e709735c48e591162ee44241d4815f459d))
* **mod:** refresh at once when equipment changes so the wearer keeps a tied item ([638ac52](https://github.com/md12ol/LootAdvisor/commit/638ac52ad0099c27314b3d3f05f0fd8f6401e687))
* **mod:** remove internal notes from Lua comments ([6587411](https://github.com/md12ol/LootAdvisor/commit/65874112c254fd2afd4617d74e2824f289f25dc3))
* **mod:** set the mod author to Michael Dubé ([ff019cd](https://github.com/md12ol/LootAdvisor/commit/ff019cdfed8bfecb6b758f2751757da4b88244e1))
* **mod:** set the mod author to Michael Dubé ([da989ad](https://github.com/md12ol/LootAdvisor/commit/da989ade406294724bfb703cd4ba62cac08fcc73))
* **mod:** touch the game UI only from Ext.UI.Defer ([ba27382](https://github.com/md12ol/LootAdvisor/commit/ba273828459093f81742847b224819affd92c5b3))
* **mod:** touch the game UI only from Ext.UI.Defer ([a8028d8](https://github.com/md12ol/LootAdvisor/commit/a8028d8f75e959b1b5df84988de0f86aae914ca0))
* **mod:** wrap long name lists in map marker labels so the tooltip does not cut them off ([d9ab463](https://github.com/md12ol/LootAdvisor/commit/d9ab46316399e2927178789a71bb60e71b87612f))
* name characters as the game shows them and hide F6 under message boxes ([d32bbbb](https://github.com/md12ol/LootAdvisor/commit/d32bbbb9b33bf60c635dc87161dad221682e7c4f))
* name characters as the game shows them and hide F6 under message boxes ([6d26eea](https://github.com/md12ol/LootAdvisor/commit/6d26eea216bf050066ce58c101b482872f27ecd6))
* **optimizer:** count a weapon's ability-modifier rider once and list assumed toggles in test plans ([b44c44e](https://github.com/md12ol/LootAdvisor/commit/b44c44e2e75ee7b9e71e1b6592386dea35c540a8))
* **optimizer:** put back an owned item a later swap made clearly better ([7e29fb2](https://github.com/md12ol/LootAdvisor/commit/7e29fb22f61481474711696c88e5a043f2079c23))
* **page:** name characters on the Sets page rail as the game does ([2a795a6](https://github.com/md12ol/LootAdvisor/commit/2a795a64f93ba3e82610f78feb901aca1a460701))
* **page:** name characters on the Sets page rail as the game does ([904d905](https://github.com/md12ol/LootAdvisor/commit/904d905e9ea5ffd4b2a3a48fa48e2cd327011794))
* **sets-page:** game subclass names, weapon stat riders and the ranged off-hand rule ([ae08778](https://github.com/md12ol/LootAdvisor/commit/ae08778a20e74fb8cc6c15f01ed33c31ffb0cd76))
* **sets-page:** game subclass names, weapon stat riders and the ranged off-hand rule ([3065ba3](https://github.com/md12ol/LootAdvisor/commit/3065ba3e0e0c7831255f0e0b9ffcf7bc9ed44e02))
* setup check reads spell slots and class resources as the fight starts ([2edef5f](https://github.com/md12ol/LootAdvisor/commit/2edef5f0a336e134226d13f8b85ad8aa812f20d5))
* take screenshots with the BG3Tools testing helper ([1eecc6a](https://github.com/md12ol/LootAdvisor/commit/1eecc6a213b32e6a32b06c28ca4f9ec1bd51dc4a))
* tie owner alternatives, exact-tie wording and the F6 window over the pause menu ([ce453c8](https://github.com/md12ol/LootAdvisor/commit/ce453c82c401b8ad7b2d7a800093b07f3cf36ed0))
* word exact ties as equal on the Sets page and in the item tooltip ([19062c4](https://github.com/md12ol/LootAdvisor/commit/19062c49b1cb39a5812ab4ebb7e8065ba79f232a))


### Performance Improvements

* faster gauntlet runs with timing records and early stopping ([8077568](https://github.com/md12ol/LootAdvisor/commit/8077568840f267838a4d2bf1576044649ee18e3d))
* **mod:** route to every entrance once per player spot instead of once per item ([6b102c3](https://github.com/md12ol/LootAdvisor/commit/6b102c3a0e0625ac2410947344673211ba5de7fd))
* **optimizer:** run jobs in parallel worker processes ([94102d5](https://github.com/md12ol/LootAdvisor/commit/94102d51d31bb5c16360146d64eb8066b854af15))

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
