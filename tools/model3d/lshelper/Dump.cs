using System;
using System.Reflection;
public static class Dump {
  public static int Main(string[] a) {
    var asm = Assembly.LoadFrom(a[0]);
    foreach (var t in asm.GetTypes()) {
      if (a.Length > 1 && t.FullName.IndexOf(a[1]) < 0) continue;
      Console.WriteLine("TYPE " + t.FullName);
      foreach (var m in t.GetMembers(BindingFlags.Public|BindingFlags.Instance|BindingFlags.Static|BindingFlags.DeclaredOnly))
        Console.WriteLine("   " + m.MemberType + " " + m.ToString());
    }
    return 0;
  }
}
