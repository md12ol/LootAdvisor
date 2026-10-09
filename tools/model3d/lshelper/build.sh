#!/bin/sh
# Compiles the LSLib helpers with the Windows .NET Framework csc against the .NET 8 runtime assemblies
# (no .NET SDK needed). Run: sh tools/model3d/lshelper/build.sh
cd "$(dirname "$0")"
NET="/c/Program Files/dotnet/shared/Microsoft.NETCore.App/$(ls "/c/Program Files/dotnet/shared/Microsoft.NETCore.App" | grep '^8\.' | tail -1)"
LS=../../../third_party/lslib/Packed/Tools
for src in VtExtract VtBatch; do
  /c/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe -nologo -nostdlib -noconfig -out:$src.dll -target:exe \
    "-r:$(cygpath -w "$NET/System.Private.CoreLib.dll")" "-r:$(cygpath -w "$NET/System.Runtime.dll")" \
    "-r:$(cygpath -w "$NET/System.Console.dll")" "-r:$(cygpath -w "$NET/System.Collections.dll")" \
    "-r:$(cygpath -w $LS/LSLib.dll)" $src.cs || exit 1
  printf '{"runtimeOptions":{"tfm":"net8.0","framework":{"name":"Microsoft.NETCore.App","version":"8.0.0"}}}' > $src.runtimeconfig.json
done
