# Releasing Loot Advisor

Versions are SemVer tags `vX.Y.Z`; the first release is `v0.9.0` (set by `release-as` in
`release-please-config.json`; delete that line once v0.9.0 is out). The release workflow
(`.github/workflows/release.yml`) runs release-please on every push to `main`: it keeps one open pull request
"chore: release vX.Y.Z" with the next version and the `CHANGELOG.md` entry built from the Conventional Commit
messages. **Nothing is tagged until you merge that PR.** Merging it creates the tag and the GitHub Release; the
workflow then stamps the version into `meta.lsx` (Version64), builds the pak, zips the player package as
`LootAdvisor-X.Y.Z.zip`, checks the zip against `INSTALL.md` and attaches it to the Release. A manual run of the workflow
(`gh workflow run release.yml -f tag=vX.Y.Z`) rebuilds and re-attaches the zip of an existing tag.
The release PR is opened by the workflow token, so GitHub does not run CI on it: merge it as an admin (branch
protection lets admins through) after checking the CHANGELOG.

**Nexus Mods upload** (optional, skipped until configured) uses Nexus Mods' official
[upload-action](https://github.com/Nexus-Mods/upload-action) and Upload API. Setup, once the mod page exists:
1. Create the mod page on Nexus Mods and upload the first file by hand (the API adds new *versions* of an existing
   file).
2. Note the mod ID (in the page URL) and the file ID (Files tab, "Advanced", or the Manage Files edit menu).
3. Create an API key at <https://www.nexusmods.com/settings/api-keys>.
4. In this repository: `gh secret set NEXUS_API_KEY`, `gh variable set NEXUS_MOD_ID --body <mod id>`,
   `gh variable set NEXUS_FILE_ID --body <file id>`.
From then on every release also uploads the zip to Nexus as a new version of that file (the old version is archived,
the Release notes become the Nexus changelog).

**mod.io release through Larian's Toolkit** (by hand, next to the GitHub and Nexus release; the Toolkit builds and
uploads its own pak, so this is done once per version from the released source):
1. Install the Baldur's Gate 3 Toolkit app and its data DLC (Steam). On the first start, type the game's `Data`
   folder into the "Enter Data Path" field.
2. New Project > **Import** the release's `LootAdvisor.pak` (same UUID and folder as ours), then copy the mod source
   `LootAdvisor/Mods/LootAdvisor/` by hand over the Toolkit's `Data\Mods\LootAdvisor\`. Import skips every file in
   `ScriptExtender/Lua/Shared/`, so never publish from the import alone. Answer **No** when it offers to add GustavX
   as a dependency.
3. Project Settings (Ctrl+P): set Author to `Michael Dubé` (the Toolkit fills in the account name and can drop the
   `é`), select `LootAdvisor/Mods/LootAdvisor/mod_publish_logo.png` as the thumbnail (PNG, 16:9, at least 512x288, at most
   8 MB), check the Description (the Toolkit keeps at most 250 characters; the meta.lsx one is kept under that and
   a test checks it), then Save.
4. **Publish Local**. It writes `LootAdvisor_<UUID>.pak` straight into the game's mod folder
   (`%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\Mods`). Compare its file list with our build:
   `python tools/pak.py list <that pak>` against `python tools/pak.py list dist/LootAdvisor.pak` must show the same paths. Then move that pak out of
   the mod folder, since it has the same UUID as the regular install.
5. Sign in (Project Settings > Authenticate) and **Publish**: maintainer only, this uploads to mod.io.

The Toolkit regenerates `meta.lsx` from its project settings: it drops `Type`, `Tags` and the Story target mode,
adds `PublishHandle`, `Conflicts`, `FileSize` and `MD5`, and bumps the build number of `Version64` on every Publish
Local (its "Auto-increment" box). It also re-saves `GUI/metadata.lsf` with its own engine version. Once a version is
published, copy the `PublishHandle` the Toolkit assigned back into this repository's `meta.lsx`, so the Nexus and
mod.io builds stay the same mod.
