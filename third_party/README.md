# Third-party tools (downloaded by hand, not committed)

## LSLib / ExportTool (Norbyte) - added 2026-10-09
| field    | value |
|----------|-------|
| file     | ExportTool-v1.20.4.zip (kept in `third_party/lslib_zip/`) |
| version  | v1.20.4 (latest stable release, published 2026-01-24) |
| URL      | https://github.com/Norbyte/lslib/releases/download/v1.20.4/ExportTool-v1.20.4.zip |
| release  | https://github.com/Norbyte/lslib/releases/tag/v1.20.4 |
| size     | 5,792,327 bytes |
| SHA-256  | 5e02368fb8acafda9b45acba37a3f3bf507fc3d65a083a159abbeab06337190e (matches the digest GitHub publishes for the asset) |
| unpacked | `third_party/lslib/Packed/` (ConverterApp.exe GUI; CLI tools in `Packed/Tools/`: Divine.exe, VTexTool.exe, ...) |
| downloaded | 2026-10-09 |

Runtime: every exe targets **net8.0** (`*.runtimeconfig.json`: Microsoft.NETCore.App 8.0.0; ConverterApp also
Microsoft.WindowsDesktop.App 8.0.0), so the .NET 8 runtime must be installed (with only .NET 6 the tools stop with
"You must install or update .NET to run this application ... Framework 'Microsoft.NETCore.App', version '8.0.0'").

With the .NET 8 runtime (tested with Microsoft.NETCore.App + WindowsDesktop.App 8.0.31):
- `Divine.exe -a convert-model` (GR2 -> GLB) works, but only with the working directory = `third_party/lslib/Packed/`:
  BG3 GR2 files are BitKnit-compressed (Granny compression type 4) and LSLib needs `Packed/granny2.dll` (RAD Game
  Tools' Granny runtime, shipped inside the LSLib release; not next to `Tools/Divine.exe`).
- Divine has no virtual-texture extract action; `tools/model3d/lshelper/VtExtract.cs` calls LSLib's
  `VirtualTileSet.ExtractTexture` directly. It is compiled with the Windows .NET Framework `csc.exe` against the .NET 8
  runtime assemblies (no .NET SDK needed): `sh tools/model3d/lshelper/build.sh`.
- Nothing from third_party ships with the mod; it is only used to build the private 3D test files.
